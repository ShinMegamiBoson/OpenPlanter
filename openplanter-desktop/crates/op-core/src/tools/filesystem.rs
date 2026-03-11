/// Filesystem tools: read, write, edit, list, search.
use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::process::Command;

use super::ToolResult;

const MAX_WALK_ENTRIES: usize = 50_000;

pub(crate) fn line_hash(line: &str) -> String {
    let normalized: String = line.split_whitespace().collect();
    let crc = crc32fast::hash(normalized.as_bytes());
    format!("{:02x}", crc & 0xFF)
}

pub(crate) fn clip(text: &str, max_chars: usize) -> String {
    if text.len() <= max_chars {
        return text.to_string();
    }
    let end = text.floor_char_boundary(max_chars);
    let omitted = text.len() - end;
    format!("{}\n\n...[truncated {omitted} chars]...", &text[..end])
}

pub(crate) fn resolve_path(root: &Path, raw_path: &str) -> Result<PathBuf, String> {
    let canon_root = std::fs::canonicalize(root).unwrap_or_else(|_| root.to_path_buf());
    let candidate = Path::new(raw_path);
    let full = if candidate.is_absolute() {
        candidate.to_path_buf()
    } else {
        canon_root.join(candidate)
    };

    // Try to canonicalize (resolves symlinks, .., etc.)
    let resolved = match std::fs::canonicalize(&full) {
        Ok(r) => r,
        Err(_) => {
            // For new files that don't exist yet, canonicalize the parent if it exists
            if let Some(parent) = full.parent() {
                if let Ok(canon_parent) = std::fs::canonicalize(parent) {
                    let filename = full.file_name().unwrap_or_default();
                    canon_parent.join(filename)
                } else {
                    // Parent doesn't exist either — build path from canon_root
                    let mut result = canon_root.clone();
                    if !candidate.is_absolute() {
                        for component in candidate.components() {
                            match component {
                                std::path::Component::ParentDir => {
                                    result.pop();
                                }
                                std::path::Component::CurDir => {}
                                std::path::Component::Normal(c) => {
                                    result.push(c);
                                }
                                _ => {}
                            }
                        }
                        result
                    } else {
                        return Err(format!("Path escapes workspace: {raw_path}"));
                    }
                }
            } else {
                return Err(format!("Path escapes workspace: {raw_path}"));
            }
        }
    };

    if resolved == canon_root || resolved.starts_with(&canon_root) {
        Ok(resolved)
    } else {
        Err(format!("Path escapes workspace: {raw_path}"))
    }
}

pub fn read_file(
    root: &Path,
    path: &str,
    hashline: bool,
    max_file_chars: usize,
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
    let text = match std::fs::read_to_string(&resolved) {
        Ok(t) => t,
        Err(e) => return ToolResult::error(format!("Failed to read file {path}: {e}")),
    };
    files_read.insert(resolved.clone());
    let clipped = clip(&text, max_file_chars);
    let canon_root = std::fs::canonicalize(root).unwrap_or_else(|_| root.to_path_buf());
    let rel = resolved
        .strip_prefix(&canon_root)
        .unwrap_or(&resolved)
        .to_string_lossy();
    let numbered = if hashline {
        clipped
            .lines()
            .enumerate()
            .map(|(i, line)| format!("{}:{}|{}", i + 1, line_hash(line), line))
            .collect::<Vec<_>>()
            .join("\n")
    } else {
        clipped
            .lines()
            .enumerate()
            .map(|(i, line)| format!("{}|{}", i + 1, line))
            .collect::<Vec<_>>()
            .join("\n")
    };
    ToolResult::ok(format!("# {rel}\n{numbered}"))
}

pub fn write_file(
    root: &Path,
    path: &str,
    content: &str,
    files_read: &mut HashSet<PathBuf>,
) -> ToolResult {
    let resolved = match resolve_path(root, path) {
        Ok(r) => r,
        Err(e) => return ToolResult::error(e),
    };
    if resolved.exists() && resolved.is_file() && !files_read.contains(&resolved) {
        return ToolResult::error(format!(
            "BLOCKED: {path} already exists but has not been read. \
             Use read_file('{path}') first, then edit via apply_patch or write_file."
        ));
    }
    if let Some(parent) = resolved.parent() {
        if let Err(e) = std::fs::create_dir_all(parent) {
            return ToolResult::error(format!("Failed to create directory: {e}"));
        }
    }
    if let Err(e) = std::fs::write(&resolved, content) {
        return ToolResult::error(format!("Failed to write {path}: {e}"));
    }
    files_read.insert(resolved.clone());
    let canon_root = std::fs::canonicalize(root).unwrap_or_else(|_| root.to_path_buf());
    let rel = resolved
        .strip_prefix(&canon_root)
        .unwrap_or(&resolved)
        .to_string_lossy();
    ToolResult::ok(format!("Wrote {} chars to {rel}", content.len()))
}

pub fn edit_file(
    root: &Path,
    path: &str,
    old_text: &str,
    new_text: &str,
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
        Ok(t) => t,
        Err(e) => return ToolResult::error(format!("Failed to read file {path}: {e}")),
    };
    files_read.insert(resolved.clone());

    let new_content = if content.contains(old_text) {
        let count = content.matches(old_text).count();
        if count > 1 {
            return ToolResult::error(format!(
                "edit_file failed: old_text appears {count} times in {path}. \
                 Provide more context to make it unique."
            ));
        }
        content.replacen(old_text, new_text, 1)
    } else {
        // Fuzzy fallback: whitespace-normalized match
        let norm_old: String = old_text.split_whitespace().collect::<Vec<_>>().join(" ");
        let old_lines: Vec<&str> = old_text.lines().collect();
        let lines: Vec<&str> = content.lines().collect();
        let mut found = false;
        let mut result_content = String::new();
        if !old_lines.is_empty() && old_lines.len() <= lines.len() {
            for i in 0..=(lines.len() - old_lines.len()) {
                let candidate: String = lines[i..i + old_lines.len()].join(" ");
                let norm_candidate: String =
                    candidate.split_whitespace().collect::<Vec<_>>().join(" ");
                if norm_candidate == norm_old {
                    let before: String = lines[..i].join("\n");
                    let after: String = lines[i + old_lines.len()..].join("\n");
                    result_content = if before.is_empty() && after.is_empty() {
                        new_text.to_string()
                    } else if before.is_empty() {
                        format!("{new_text}\n{after}")
                    } else if after.is_empty() {
                        format!("{before}\n{new_text}")
                    } else {
                        format!("{before}\n{new_text}\n{after}")
                    };
                    found = true;
                    break;
                }
            }
        }
        if !found {
            return ToolResult::error(format!("edit_file failed: old_text not found in {path}"));
        }
        result_content
    };

    if let Err(e) = std::fs::write(&resolved, &new_content) {
        return ToolResult::error(format!("Failed to write {path}: {e}"));
    }
    let canon_root = std::fs::canonicalize(root).unwrap_or_else(|_| root.to_path_buf());
    let rel = resolved
        .strip_prefix(&canon_root)
        .unwrap_or(&resolved)
        .to_string_lossy();
    ToolResult::ok(format!("Edited {rel}"))
}

pub fn list_files(
    root: &Path,
    glob_pattern: Option<&str>,
    max_files: usize,
    _timeout_sec: u64,
) -> ToolResult {
    // Try ripgrep first
    if which_rg() {
        let mut cmd = Command::new("rg");
        cmd.args(["--files", "--hidden", "-g", "!.git"]);
        if let Some(g) = glob_pattern {
            cmd.args(["-g", g]);
        }
        cmd.current_dir(root);
        match run_cmd(&mut cmd) {
            Ok(output) => {
                let lines: Vec<&str> = output.lines().filter(|l| !l.is_empty()).collect();
                if lines.is_empty() {
                    return ToolResult::ok("(no files)".into());
                }
                let clipped: Vec<&str> = lines.iter().take(max_files).copied().collect();
                let mut result = clipped.join("\n");
                if lines.len() > clipped.len() {
                    result.push_str(&format!(
                        "\n...[omitted {} files]...",
                        lines.len() - clipped.len()
                    ));
                }
                return ToolResult::ok(result);
            }
            Err(_) => return ToolResult::ok("(list_files timed out)".into()),
        }
    }

    // Fallback: walkdir
    let mut all_paths: Vec<String> = Vec::new();
    let mut count = 0usize;
    for entry in walkdir::WalkDir::new(root)
        .into_iter()
        .filter_entry(|e| e.file_name() != ".git")
    {
        let entry = match entry {
            Ok(e) => e,
            Err(_) => continue,
        };
        if entry.file_type().is_file() {
            count += 1;
            if count > MAX_WALK_ENTRIES {
                break;
            }
            if let Ok(rel) = entry.path().strip_prefix(root) {
                all_paths.push(rel.to_string_lossy().to_string());
            }
        }
    }

    if all_paths.is_empty() {
        return ToolResult::ok("(no files)".into());
    }
    all_paths.sort();
    let clipped: Vec<&str> = all_paths
        .iter()
        .take(max_files)
        .map(|s| s.as_str())
        .collect();
    let mut result = clipped.join("\n");
    if all_paths.len() > clipped.len() {
        result.push_str(&format!(
            "\n...[omitted {} files]...",
            all_paths.len() - clipped.len()
        ));
    }
    ToolResult::ok(result)
}

pub fn search_files(
    root: &Path,
    query: &str,
    glob_pattern: Option<&str>,
    max_hits: usize,
    _timeout_sec: u64,
) -> ToolResult {
    if query.trim().is_empty() {
        return ToolResult::error("query cannot be empty".into());
    }

    if which_rg() {
        let mut cmd = Command::new("rg");
        cmd.args(["-n", "--hidden", "-S", query, "."]);
        if let Some(g) = glob_pattern {
            cmd.args(["-g", g]);
        }
        cmd.current_dir(root);
        match run_cmd(&mut cmd) {
            Ok(output) => {
                let lines: Vec<&str> = output.lines().filter(|l| !l.is_empty()).collect();
                if lines.is_empty() {
                    return ToolResult::ok("(no matches)".into());
                }
                let clipped: Vec<&str> = lines.iter().take(max_hits).copied().collect();
                let mut result = clipped.join("\n");
                if lines.len() > clipped.len() {
                    result.push_str(&format!(
                        "\n...[omitted {} matches]...",
                        lines.len() - clipped.len()
                    ));
                }
                return ToolResult::ok(result);
            }
            Err(_) => return ToolResult::ok("(search_files timed out)".into()),
        }
    }

    // Fallback: walk + case-insensitive search
    let lower_query = query.to_lowercase();
    let mut matches: Vec<String> = Vec::new();
    let mut count = 0usize;
    for entry in walkdir::WalkDir::new(root)
        .into_iter()
        .filter_entry(|e| e.file_name() != ".git")
    {
        let entry = match entry {
            Ok(e) => e,
            Err(_) => continue,
        };
        if !entry.file_type().is_file() {
            continue;
        }
        count += 1;
        if count > MAX_WALK_ENTRIES {
            break;
        }
        let text = match std::fs::read_to_string(entry.path()) {
            Ok(t) => t,
            Err(_) => continue,
        };
        let rel = entry.path().strip_prefix(root).unwrap_or(entry.path());
        for (idx, line) in text.lines().enumerate() {
            if line.to_lowercase().contains(&lower_query) {
                matches.push(format!("{}:{}:{}", rel.to_string_lossy(), idx + 1, line));
                if matches.len() >= max_hits {
                    let mut result = matches.join("\n");
                    result.push_str("\n...[match limit reached]...");
                    return ToolResult::ok(result);
                }
            }
        }
    }
    if matches.is_empty() {
        ToolResult::ok("(no matches)".into())
    } else {
        ToolResult::ok(matches.join("\n"))
    }
}

fn which_rg() -> bool {
    Command::new("which")
        .arg("rg")
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

fn run_cmd(cmd: &mut Command) -> Result<String, ()> {
    cmd.stdout(std::process::Stdio::piped());
    cmd.stderr(std::process::Stdio::piped());
    let output = cmd.output().map_err(|_| ())?;
    Ok(String::from_utf8_lossy(&output.stdout).to_string())
}

// Re-export for use by patching module
pub(crate) use self::resolve_path as resolve_workspace_path;

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[test]
    fn test_read_file_basic() {
        let dir = TempDir::new().unwrap();
        std::fs::write(dir.path().join("hello.txt"), "line1\nline2\n").unwrap();
        let mut files_read = HashSet::new();
        let result = read_file(dir.path(), "hello.txt", true, 20000, &mut files_read);
        assert!(!result.is_error);
        assert!(result.content.contains("hello.txt"));
        assert!(result.content.contains("line1"));
        assert!(result.content.contains("line2"));
    }

    #[test]
    fn test_read_file_not_found() {
        let dir = TempDir::new().unwrap();
        let mut files_read = HashSet::new();
        let result = read_file(dir.path(), "missing.txt", true, 20000, &mut files_read);
        assert!(result.is_error);
        assert!(result.content.contains("not found"));
    }

    #[test]
    fn test_write_file_new() {
        let dir = TempDir::new().unwrap();
        let mut files_read = HashSet::new();
        let result = write_file(dir.path(), "new.txt", "hello world", &mut files_read);
        assert!(!result.is_error);
        assert!(result.content.contains("Wrote"));
        assert_eq!(
            std::fs::read_to_string(dir.path().join("new.txt")).unwrap(),
            "hello world"
        );
    }

    #[test]
    fn test_write_file_blocked_if_not_read() {
        let dir = TempDir::new().unwrap();
        std::fs::write(dir.path().join("existing.txt"), "old content").unwrap();
        let mut files_read = HashSet::new();
        let result = write_file(dir.path(), "existing.txt", "new content", &mut files_read);
        assert!(result.is_error);
        assert!(result.content.contains("BLOCKED"));
    }

    #[test]
    fn test_edit_file_basic() {
        let dir = TempDir::new().unwrap();
        std::fs::write(dir.path().join("test.txt"), "hello world").unwrap();
        let mut files_read = HashSet::new();
        let result = edit_file(dir.path(), "test.txt", "hello", "goodbye", &mut files_read);
        assert!(!result.is_error);
        assert_eq!(
            std::fs::read_to_string(dir.path().join("test.txt")).unwrap(),
            "goodbye world"
        );
    }

    #[test]
    fn test_edit_file_not_found_old_text() {
        let dir = TempDir::new().unwrap();
        std::fs::write(dir.path().join("test.txt"), "hello world").unwrap();
        let mut files_read = HashSet::new();
        let result = edit_file(
            dir.path(),
            "test.txt",
            "nonexistent",
            "replacement",
            &mut files_read,
        );
        assert!(result.is_error);
        assert!(result.content.contains("not found"));
    }

    #[test]
    fn test_edit_file_duplicate_old_text() {
        let dir = TempDir::new().unwrap();
        std::fs::write(dir.path().join("test.txt"), "hello hello").unwrap();
        let mut files_read = HashSet::new();
        let result = edit_file(dir.path(), "test.txt", "hello", "bye", &mut files_read);
        assert!(result.is_error);
        assert!(result.content.contains("2 times"));
    }

    #[test]
    fn test_list_files() {
        let dir = TempDir::new().unwrap();
        std::fs::write(dir.path().join("a.txt"), "").unwrap();
        std::fs::write(dir.path().join("b.txt"), "").unwrap();
        let result = list_files(dir.path(), None, 400, 45);
        assert!(!result.is_error);
        assert!(result.content.contains("a.txt"));
        assert!(result.content.contains("b.txt"));
    }

    #[test]
    fn test_search_files() {
        let dir = TempDir::new().unwrap();
        std::fs::write(dir.path().join("test.txt"), "needle in haystack").unwrap();
        let result = search_files(dir.path(), "needle", None, 200, 45);
        assert!(!result.is_error);
        assert!(result.content.contains("needle"));
    }

    #[test]
    fn test_resolve_path_escape() {
        let dir = TempDir::new().unwrap();
        let result = resolve_path(dir.path(), "../../etc/passwd");
        assert!(result.is_err());
    }

    #[test]
    fn test_line_hash_whitespace_invariant() {
        let h1 = line_hash("hello world");
        let h2 = line_hash("hello  world");
        assert_eq!(h1, h2, "whitespace-invariant hash");
        assert_eq!(h1.len(), 2);
    }
}
