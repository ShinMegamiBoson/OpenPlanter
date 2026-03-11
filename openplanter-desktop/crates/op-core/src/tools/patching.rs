/// Codex-style patch application and hashline editing.
use std::collections::HashSet;
use std::path::{Path, PathBuf};

use regex::Regex;
use std::sync::LazyLock;

use super::ToolResult;

static HASHLINE_PREFIX_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^\d+:[0-9a-f]{2}\|").unwrap());

fn line_hash(line: &str) -> String {
    let normalized: String = line.split_whitespace().collect();
    let crc = crc32fast::hash(normalized.as_bytes());
    format!("{:02x}", crc & 0xFF)
}

fn resolve_path(root: &Path, raw_path: &str) -> Result<PathBuf, String> {
    super::filesystem::resolve_workspace_path(root, raw_path)
}

// ── Codex-style patch format ──

enum PatchOp {
    Add {
        path: String,
        content: String,
    },
    Delete {
        path: String,
    },
    Update {
        path: String,
        move_to: Option<String>,
        chunks: Vec<PatchChunk>,
    },
}

struct PatchChunk {
    old_lines: Vec<String>,
    new_lines: Vec<String>,
}

fn parse_agent_patch(text: &str) -> Result<Vec<PatchOp>, String> {
    let lines: Vec<&str> = text.lines().collect();
    if lines.is_empty() {
        return Err("Empty patch".into());
    }

    let start = lines
        .iter()
        .position(|l| l.trim() == "*** Begin Patch")
        .ok_or("Missing '*** Begin Patch' marker")?;

    let end = lines
        .iter()
        .rposition(|l| l.trim() == "*** End Patch")
        .ok_or("Missing '*** End Patch' marker")?;

    if end <= start {
        return Err("Invalid patch structure".into());
    }

    let body = &lines[start + 1..end];
    let mut ops: Vec<PatchOp> = Vec::new();
    let mut i = 0;

    while i < body.len() {
        let line = body[i].trim();

        if line.starts_with("*** Add File:") {
            let path = line.trim_start_matches("*** Add File:").trim().to_string();
            i += 1;
            let mut content_lines: Vec<String> = Vec::new();
            while i < body.len() && !body[i].trim().starts_with("***") {
                if let Some(stripped) = body[i].strip_prefix('+') {
                    content_lines.push(stripped.to_string());
                }
                i += 1;
            }
            ops.push(PatchOp::Add {
                path,
                content: if content_lines.is_empty() {
                    String::new()
                } else {
                    content_lines.join("\n") + "\n"
                },
            });
        } else if line.starts_with("*** Delete File:") {
            let path = line
                .trim_start_matches("*** Delete File:")
                .trim()
                .to_string();
            ops.push(PatchOp::Delete { path });
            i += 1;
        } else if line.starts_with("*** Update File:") {
            let path = line
                .trim_start_matches("*** Update File:")
                .trim()
                .to_string();
            i += 1;

            let mut move_to = None;
            if i < body.len() && body[i].trim().starts_with("*** Move to:") {
                move_to = Some(
                    body[i]
                        .trim()
                        .trim_start_matches("*** Move to:")
                        .trim()
                        .to_string(),
                );
                i += 1;
            }

            let mut raw_lines: Vec<&str> = Vec::new();
            while i < body.len() {
                let trimmed = body[i].trim();
                if trimmed.starts_with("*** Add File:")
                    || trimmed.starts_with("*** Delete File:")
                    || trimmed.starts_with("*** Update File:")
                {
                    break;
                }
                if trimmed.starts_with("@@") || trimmed == "*** End of File" {
                    i += 1;
                    continue;
                }
                raw_lines.push(body[i]);
                i += 1;
            }

            let chunks = parse_chunks(&raw_lines);
            ops.push(PatchOp::Update {
                path,
                move_to,
                chunks,
            });
        } else {
            i += 1;
        }
    }

    Ok(ops)
}

fn parse_chunks(raw_lines: &[&str]) -> Vec<PatchChunk> {
    if raw_lines.is_empty() {
        return Vec::new();
    }

    let mut old_lines: Vec<String> = Vec::new();
    let mut new_lines: Vec<String> = Vec::new();

    for line in raw_lines {
        if let Some(removed) = line.strip_prefix('-') {
            old_lines.push(removed.to_string());
        } else if let Some(added) = line.strip_prefix('+') {
            new_lines.push(added.to_string());
        } else {
            // Context line
            let content = line.strip_prefix(' ').unwrap_or(line).to_string();
            old_lines.push(content.clone());
            new_lines.push(content);
        }
    }

    if old_lines.is_empty() && new_lines.is_empty() {
        Vec::new()
    } else {
        vec![PatchChunk {
            old_lines,
            new_lines,
        }]
    }
}

fn find_subsequence(haystack: &[String], needle: &[String], start_idx: usize) -> Option<usize> {
    if needle.is_empty() {
        return Some(start_idx.min(haystack.len()));
    }
    if needle.len() > haystack.len() {
        return None;
    }

    let max_start = haystack.len() - needle.len();

    // Pass 1: exact match, searching from start_idx first
    let search_start = start_idx.min(max_start);
    for i in search_start..=max_start {
        if haystack[i..i + needle.len()] == needle[..] {
            return Some(i);
        }
    }
    for i in 0..search_start {
        if haystack[i..i + needle.len()] == needle[..] {
            return Some(i);
        }
    }

    // Pass 2: whitespace-normalized match
    let normalize = |s: &str| -> String { s.split_whitespace().collect::<Vec<_>>().join(" ") };
    let norm_needle: Vec<String> = needle.iter().map(|s| normalize(s)).collect();

    for i in 0..=max_start {
        let matches = haystack[i..i + needle.len()]
            .iter()
            .zip(norm_needle.iter())
            .all(|(h, n)| normalize(h) == *n);
        if matches {
            return Some(i);
        }
    }

    None
}

pub fn apply_patch(root: &Path, patch_text: &str, files_read: &mut HashSet<PathBuf>) -> ToolResult {
    if patch_text.trim().is_empty() {
        return ToolResult::error("apply_patch requires non-empty patch text".into());
    }

    let ops = match parse_agent_patch(patch_text) {
        Ok(o) => o,
        Err(e) => return ToolResult::error(format!("Patch failed: {e}")),
    };

    let mut added: Vec<String> = Vec::new();
    let mut updated: Vec<String> = Vec::new();
    let mut deleted: Vec<String> = Vec::new();

    for op in ops {
        match op {
            PatchOp::Add { path, content } => {
                let resolved = match resolve_path(root, &path) {
                    Ok(r) => r,
                    Err(e) => return ToolResult::error(format!("Patch failed: {e}")),
                };
                if let Some(parent) = resolved.parent() {
                    let _ = std::fs::create_dir_all(parent);
                }
                if let Err(e) = std::fs::write(&resolved, &content) {
                    return ToolResult::error(format!("Patch failed: could not write {path}: {e}"));
                }
                files_read.insert(resolved);
                added.push(path);
            }
            PatchOp::Delete { path } => {
                let resolved = match resolve_path(root, &path) {
                    Ok(r) => r,
                    Err(e) => return ToolResult::error(format!("Patch failed: {e}")),
                };
                if !resolved.exists() {
                    return ToolResult::error(format!("Patch failed: file not found: {path}"));
                }
                if let Err(e) = std::fs::remove_file(&resolved) {
                    return ToolResult::error(format!(
                        "Patch failed: could not delete {path}: {e}"
                    ));
                }
                deleted.push(path);
            }
            PatchOp::Update {
                path,
                move_to,
                chunks,
            } => {
                let resolved = match resolve_path(root, &path) {
                    Ok(r) => r,
                    Err(e) => return ToolResult::error(format!("Patch failed: {e}")),
                };
                let content = match std::fs::read_to_string(&resolved) {
                    Ok(c) => c,
                    Err(e) => {
                        return ToolResult::error(format!(
                            "Patch failed: could not read {path}: {e}"
                        ));
                    }
                };
                files_read.insert(resolved.clone());

                let had_trailing_newline = content.ends_with('\n');
                let mut lines: Vec<String> = content.lines().map(|l| l.to_string()).collect();
                let mut cursor = 0usize;

                for chunk in &chunks {
                    match find_subsequence(&lines, &chunk.old_lines, cursor) {
                        Some(idx) => {
                            lines.splice(
                                idx..idx + chunk.old_lines.len(),
                                chunk.new_lines.iter().cloned(),
                            );
                            cursor = idx + chunk.new_lines.len();
                        }
                        None => {
                            return ToolResult::error(format!(
                                "Patch failed: could not find matching context in {path}"
                            ));
                        }
                    }
                }

                let mut result = lines.join("\n");
                if had_trailing_newline {
                    result.push('\n');
                }

                let target = if let Some(ref new_path) = move_to {
                    let target_resolved = match resolve_path(root, new_path) {
                        Ok(r) => r,
                        Err(e) => return ToolResult::error(format!("Patch failed: {e}")),
                    };
                    let _ = std::fs::remove_file(&resolved);
                    target_resolved
                } else {
                    resolved
                };

                if let Some(parent) = target.parent() {
                    let _ = std::fs::create_dir_all(parent);
                }
                if let Err(e) = std::fs::write(&target, &result) {
                    return ToolResult::error(format!("Patch failed: could not write {path}: {e}"));
                }
                files_read.insert(target);
                updated.push(path);
            }
        }
    }

    let mut report_parts: Vec<String> = Vec::new();
    if !added.is_empty() {
        report_parts.push(format!("Added: {}", added.join(", ")));
    }
    if !updated.is_empty() {
        report_parts.push(format!("Updated: {}", updated.join(", ")));
    }
    if !deleted.is_empty() {
        report_parts.push(format!("Deleted: {}", deleted.join(", ")));
    }
    if report_parts.is_empty() {
        ToolResult::ok("No operations in patch".into())
    } else {
        ToolResult::ok(report_parts.join("\n"))
    }
}

pub fn hashline_edit(
    root: &Path,
    path: &str,
    edits: &[serde_json::Value],
    files_read: &mut HashSet<PathBuf>,
) -> ToolResult {
    let resolved = match resolve_path(root, path) {
        Ok(r) => r,
        Err(e) => return ToolResult::error(e),
    };
    if !resolved.exists() {
        return ToolResult::error(format!("File not found: {path}"));
    }
    if resolved.is_dir() {
        return ToolResult::error(format!("Path is a directory, not a file: {path}"));
    }
    let content = match std::fs::read_to_string(&resolved) {
        Ok(c) => c,
        Err(e) => return ToolResult::error(format!("Failed to read file {path}: {e}")),
    };
    files_read.insert(resolved.clone());

    let mut lines: Vec<String> = content.lines().map(|l| l.to_string()).collect();
    let line_hashes: std::collections::HashMap<usize, String> = lines
        .iter()
        .enumerate()
        .map(|(i, l)| (i + 1, line_hash(l)))
        .collect();

    struct ParsedEdit {
        op: String,
        start: usize,
        #[allow(dead_code)]
        end: usize,
        new_lines: Vec<String>,
    }

    let mut parsed: Vec<ParsedEdit> = Vec::new();

    for edit in edits {
        if let Some(anchor) = edit.get("set_line").and_then(|v| v.as_str()) {
            let (lineno, err) = validate_anchor(anchor, &line_hashes, &lines);
            if let Some(e) = err {
                return ToolResult::error(e);
            }
            let raw = edit.get("content").and_then(|v| v.as_str()).unwrap_or("");
            let new_line = HASHLINE_PREFIX_RE.replace(raw, "").to_string();
            parsed.push(ParsedEdit {
                op: "set".into(),
                start: lineno,
                end: lineno,
                new_lines: vec![new_line],
            });
        } else if let Some(range) = edit.get("replace_lines") {
            let start_anchor = range.get("start").and_then(|v| v.as_str()).unwrap_or("");
            let end_anchor = range.get("end").and_then(|v| v.as_str()).unwrap_or("");
            let (start, err) = validate_anchor(start_anchor, &line_hashes, &lines);
            if let Some(e) = err {
                return ToolResult::error(e);
            }
            let (end, err) = validate_anchor(end_anchor, &line_hashes, &lines);
            if let Some(e) = err {
                return ToolResult::error(e);
            }
            if end < start {
                return ToolResult::error(format!("End line {end} is before start line {start}"));
            }
            let raw_content = edit.get("content").and_then(|v| v.as_str()).unwrap_or("");
            let new_lines: Vec<String> = raw_content
                .lines()
                .map(|l| HASHLINE_PREFIX_RE.replace(l, "").to_string())
                .collect();
            parsed.push(ParsedEdit {
                op: "replace".into(),
                start,
                end,
                new_lines,
            });
        } else if let Some(anchor) = edit.get("insert_after").and_then(|v| v.as_str()) {
            let (lineno, err) = validate_anchor(anchor, &line_hashes, &lines);
            if let Some(e) = err {
                return ToolResult::error(e);
            }
            let raw_content = edit.get("content").and_then(|v| v.as_str()).unwrap_or("");
            let new_lines: Vec<String> = raw_content
                .lines()
                .map(|l| HASHLINE_PREFIX_RE.replace(l, "").to_string())
                .collect();
            parsed.push(ParsedEdit {
                op: "insert".into(),
                start: lineno,
                end: lineno,
                new_lines,
            });
        } else {
            return ToolResult::error(format!(
                "Unknown edit operation: {}. Use set_line, replace_lines, or insert_after.",
                edit
            ));
        }
    }

    // Sort descending by line number for bottom-up application
    parsed.sort_by(|a, b| b.start.cmp(&a.start));

    let mut changed = 0;
    for edit in &parsed {
        match edit.op.as_str() {
            "set" => {
                if lines[edit.start - 1] != edit.new_lines[0] {
                    lines[edit.start - 1] = edit.new_lines[0].clone();
                    changed += 1;
                }
            }
            "replace" => {
                let old_slice: Vec<String> = lines[edit.start - 1..edit.end].to_vec();
                if old_slice != edit.new_lines {
                    lines.splice(edit.start - 1..edit.end, edit.new_lines.iter().cloned());
                    changed += 1;
                }
            }
            "insert" => {
                for (j, line) in edit.new_lines.iter().enumerate() {
                    lines.insert(edit.start + j, line.clone());
                }
                changed += 1;
            }
            _ => {}
        }
    }

    if changed == 0 {
        return ToolResult::ok(format!("No changes needed in {path}"));
    }

    let mut new_content = lines.join("\n");
    if content.ends_with('\n') {
        new_content.push('\n');
    }
    if let Err(e) = std::fs::write(&resolved, &new_content) {
        return ToolResult::error(format!("Failed to write {path}: {e}"));
    }
    files_read.insert(resolved);
    ToolResult::ok(format!("Edited {path} ({changed} edit(s) applied)"))
}

fn validate_anchor(
    anchor: &str,
    line_hashes: &std::collections::HashMap<usize, String>,
    lines: &[String],
) -> (usize, Option<String>) {
    let parts: Vec<&str> = anchor.splitn(2, ':').collect();
    if parts.len() != 2 || parts[1].len() != 2 {
        return (
            0,
            Some(format!("Invalid anchor format: {anchor:?} (expected N:HH)")),
        );
    }
    let lineno: usize = match parts[0].parse() {
        Ok(n) => n,
        Err(_) => {
            return (
                0,
                Some(format!("Invalid anchor format: {anchor:?} (expected N:HH)")),
            );
        }
    };
    let expected_hash = parts[1];
    if lineno < 1 || lineno > lines.len() {
        return (
            0,
            Some(format!(
                "Line {lineno} out of range (file has {} lines)",
                lines.len()
            )),
        );
    }
    let actual_hash = line_hashes.get(&lineno).map(|s| s.as_str()).unwrap_or("");
    if actual_hash != expected_hash {
        let ctx_start = lineno.saturating_sub(2).max(1);
        let ctx_end = (lineno + 2).min(lines.len());
        let ctx_lines: Vec<String> = (ctx_start..=ctx_end)
            .map(|i| {
                format!(
                    "  {}:{}|{}",
                    i,
                    line_hashes.get(&i).map(|s| s.as_str()).unwrap_or("??"),
                    lines[i - 1]
                )
            })
            .collect();
        return (
            0,
            Some(format!(
                "Hash mismatch at line {lineno}: expected {expected_hash}, \
                 got {actual_hash}. Current context:\n{}",
                ctx_lines.join("\n")
            )),
        );
    }
    (lineno, None)
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[test]
    fn test_apply_patch_add_file() {
        let dir = TempDir::new().unwrap();
        let mut files_read = HashSet::new();
        let patch = "\
*** Begin Patch
*** Add File: new_file.txt
+hello
+world
*** End Patch";
        let result = apply_patch(dir.path(), patch, &mut files_read);
        assert!(!result.is_error, "error: {}", result.content);
        assert!(result.content.contains("Added"));
        let content = std::fs::read_to_string(dir.path().join("new_file.txt")).unwrap();
        assert_eq!(content, "hello\nworld\n");
    }

    #[test]
    fn test_apply_patch_delete_file() {
        let dir = TempDir::new().unwrap();
        std::fs::write(dir.path().join("to_delete.txt"), "content").unwrap();
        let mut files_read = HashSet::new();
        let patch = "\
*** Begin Patch
*** Delete File: to_delete.txt
*** End Patch";
        let result = apply_patch(dir.path(), patch, &mut files_read);
        assert!(!result.is_error, "error: {}", result.content);
        assert!(!dir.path().join("to_delete.txt").exists());
    }

    #[test]
    fn test_apply_patch_update_file() {
        let dir = TempDir::new().unwrap();
        std::fs::write(dir.path().join("test.txt"), "line1\nline2\nline3\n").unwrap();
        let mut files_read = HashSet::new();
        let patch = "\
*** Begin Patch
*** Update File: test.txt
@@
 line1
-line2
+line2_modified
 line3
*** End Patch";
        let result = apply_patch(dir.path(), patch, &mut files_read);
        assert!(!result.is_error, "error: {}", result.content);
        let content = std::fs::read_to_string(dir.path().join("test.txt")).unwrap();
        assert!(content.contains("line2_modified"));
        assert!(!content.contains("\nline2\n"));
    }

    #[test]
    fn test_hashline_edit_set_line() {
        let dir = TempDir::new().unwrap();
        std::fs::write(dir.path().join("test.txt"), "aaa\nbbb\nccc\n").unwrap();
        let mut files_read = HashSet::new();

        let hash = line_hash("bbb");
        let edits = vec![serde_json::json!({
            "set_line": format!("2:{hash}"),
            "content": "BBB"
        })];
        let result = hashline_edit(dir.path(), "test.txt", &edits, &mut files_read);
        assert!(!result.is_error, "error: {}", result.content);
        let content = std::fs::read_to_string(dir.path().join("test.txt")).unwrap();
        assert!(content.contains("BBB"));
        assert!(!content.contains("\nbbb\n"));
    }

    #[test]
    fn test_hashline_edit_insert_after() {
        let dir = TempDir::new().unwrap();
        std::fs::write(dir.path().join("test.txt"), "aaa\nbbb\nccc\n").unwrap();
        let mut files_read = HashSet::new();

        let hash = line_hash("bbb");
        let edits = vec![serde_json::json!({
            "insert_after": format!("2:{hash}"),
            "content": "inserted_line"
        })];
        let result = hashline_edit(dir.path(), "test.txt", &edits, &mut files_read);
        assert!(!result.is_error, "error: {}", result.content);
        let content = std::fs::read_to_string(dir.path().join("test.txt")).unwrap();
        let lines: Vec<&str> = content.lines().collect();
        assert_eq!(lines[2], "inserted_line");
    }

    #[test]
    fn test_parse_patch_missing_markers() {
        let result = parse_agent_patch("no markers here");
        assert!(result.is_err());
    }

    #[test]
    fn test_find_subsequence_exact() {
        let haystack: Vec<String> = vec!["a".into(), "b".into(), "c".into()];
        let needle: Vec<String> = vec!["b".into(), "c".into()];
        assert_eq!(find_subsequence(&haystack, &needle, 0), Some(1));
    }

    #[test]
    fn test_find_subsequence_whitespace() {
        let haystack: Vec<String> = vec!["a".into(), "  b  ".into(), "c".into()];
        let needle: Vec<String> = vec!["b".into(), "c".into()];
        assert_eq!(find_subsequence(&haystack, &needle, 0), Some(1));
    }
}
