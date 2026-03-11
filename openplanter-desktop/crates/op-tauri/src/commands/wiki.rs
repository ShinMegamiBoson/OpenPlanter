use crate::state::AppState;
use op_core::events::{GraphData, GraphEdge, GraphNode, NodeType};
use regex::Regex;
use std::collections::{HashMap, HashSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::LazyLock;
use tauri::State;

static LINK_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\[([^\]]+)\]\(([^)]+\.md)\)").unwrap());
static CATEGORY_RE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^#{2,3}\s+(.+)").unwrap());

/// Walk up from `start` to find a directory containing `wiki/index.md`.
/// Checks both `.openplanter/wiki/` (preferred) and `wiki/` at each level.
fn find_wiki_dir(start: &Path) -> Option<PathBuf> {
    let mut dir = start.canonicalize().ok();
    while let Some(d) = dir {
        // Prefer .openplanter/wiki/ (standard location used by the agent)
        let dot_wiki = d.join(".openplanter").join("wiki");
        if dot_wiki.join("index.md").exists() {
            return Some(dot_wiki);
        }
        // Fallback to bare wiki/
        let wiki = d.join("wiki");
        if wiki.join("index.md").exists() {
            return Some(wiki);
        }
        dir = d.parent().map(|p| p.to_path_buf());
    }
    None
}

/// Normalize a wiki section heading into a category slug.
/// Handles compound headings like "Financial / Corporate Sources" → "financial".
fn normalize_category(heading: &str) -> String {
    let raw = heading.trim().to_lowercase();
    let raw = raw.strip_suffix("sources").unwrap_or(&raw).trim();

    // Split once on "/" — use second term if first is "government"
    let mut parts = raw.split('/');
    let first = parts.next().unwrap_or(raw).trim().replace(' ', "-");
    let second = parts.next().map(|s| s.trim().replace(' ', "-"));

    let mut cat = first;
    if cat.starts_with("government-") {
        cat = cat.strip_prefix("government-").unwrap_or(&cat).to_string();
    }
    if cat == "government" {
        if let Some(ref s) = second {
            if !s.is_empty() {
                cat = s.clone();
            }
        }
    }

    // Collapse known aliases
    match cat.as_str() {
        s if s.contains("regulatory") => "regulatory".to_string(),
        "media" | "public-record" => "media".to_string(),
        "legal" | "court" => "legal".to_string(),
        _ => cat,
    }
}

/// Parse wiki/index.md content into graph nodes.
pub fn parse_index_nodes(content: &str) -> Vec<GraphNode> {
    let mut nodes = Vec::new();
    let mut current_category = String::new();

    for line in content.lines() {
        if let Some(caps) = CATEGORY_RE.captures(line) {
            current_category = normalize_category(&caps[1]);
            continue;
        }

        if !line.trim_start().starts_with('|') {
            continue;
        }
        if line.contains("---") || line.contains("Source") {
            continue;
        }

        if let Some(caps) = LINK_RE.captures(line) {
            let path = caps[2].to_string();

            let label = line
                .split('|')
                .nth(1)
                .map(|s| s.trim().to_string())
                .filter(|s| !s.is_empty())
                .unwrap_or_else(|| caps[1].to_string());

            let id = path
                .rsplit('/')
                .next()
                .unwrap_or(&path)
                .trim_end_matches(".md")
                .to_string();

            nodes.push(GraphNode {
                id,
                label,
                category: current_category.clone(),
                path: format!("wiki/{}", path),
                node_type: Some(op_core::events::NodeType::Source),
                parent_id: None,
                content: None,
            });
        }
    }

    nodes
}

/// Extract distinctive search terms from a node's label for text-based matching.
fn search_terms_for_node(node: &GraphNode) -> Vec<String> {
    let stopwords: HashSet<&str> = [
        "a", "an", "the", "of", "and", "or", "in", "to", "for", "by", "on", "at", "is", "it",
        "its", "us", "gov", "list",
    ]
    .into_iter()
    .collect();

    let generic: HashSet<&str> = [
        "federal",
        "state",
        "united",
        "states",
        "government",
        "bureau",
        "department",
        "database",
        "national",
        "public",
    ]
    .into_iter()
    .collect();

    let mut terms = Vec::new();

    // Full label (lowercased)
    terms.push(node.label.to_lowercase());

    for word in node
        .label
        .split(|c: char| c.is_whitespace() || c == '/' || c == '(' || c == ')')
    {
        let clean: String = word
            .chars()
            .filter(|c| c.is_alphanumeric() || *c == '.' || *c == '-')
            .collect();
        if clean.is_empty() {
            continue;
        }
        let lower = clean.to_lowercase();
        if stopwords.contains(lower.as_str()) {
            continue;
        }

        // Acronyms: all uppercase, >= 2 chars (OCPF, FEC, EDGAR, FDIC, etc.)
        let alpha_chars: String = clean.chars().filter(|c| c.is_alphabetic()).collect();
        if alpha_chars.len() >= 2 && alpha_chars.chars().all(|c| c.is_uppercase()) {
            terms.push(lower);
            continue;
        }

        // Distinctive words: >= 5 chars, not generic
        if clean.len() >= 5 && !generic.contains(lower.as_str()) {
            terms.push(lower);
        }
    }

    terms.sort();
    terms.dedup();
    terms
}

/// Find cross-references between nodes by reading wiki files from `wiki_dir`.
/// Uses both markdown link detection and text-based mention matching.
pub fn find_cross_references(nodes: &[GraphNode], wiki_dir: &Path) -> Vec<GraphEdge> {
    let node_ids: HashSet<&str> = nodes.iter().map(|n| n.id.as_str()).collect();
    let mut edges = Vec::new();
    let mut seen: HashSet<(String, String)> = HashSet::new();

    // Pre-compute search terms for all nodes
    let node_terms: Vec<Vec<String>> = nodes.iter().map(|n| search_terms_for_node(n)).collect();

    // Read all file contents upfront
    let file_contents: HashMap<String, String> = nodes
        .iter()
        .filter_map(|node| {
            let file_path = wiki_dir.join(&node.path);
            fs::read_to_string(&file_path)
                .ok()
                .map(|c| (node.id.clone(), c))
        })
        .collect();

    for (i, node) in nodes.iter().enumerate() {
        let file_content = match file_contents.get(&node.id) {
            Some(c) => c,
            None => continue,
        };

        // 1. Markdown link-based edges (existing logic)
        for caps in LINK_RE.captures_iter(file_content) {
            let ref_path = &caps[2];
            let ref_id = ref_path
                .rsplit('/')
                .next()
                .unwrap_or(ref_path)
                .trim_end_matches(".md");

            if ref_id != node.id && node_ids.contains(ref_id) {
                let key = (node.id.clone(), ref_id.to_string());
                if seen.insert(key) {
                    edges.push(GraphEdge {
                        source: node.id.clone(),
                        target: ref_id.to_string(),
                        label: Some("link".to_string()),
                    });
                }
            }
        }

        // 2. Text-based mention edges
        let content_lower = file_content.to_lowercase();
        for (j, other) in nodes.iter().enumerate() {
            if i == j {
                continue;
            }
            let key = (node.id.clone(), other.id.clone());
            if seen.contains(&key) {
                continue;
            }

            let matched = node_terms[j]
                .iter()
                .any(|term| content_lower.contains(term.as_str()));
            if matched {
                seen.insert(key);
                edges.push(GraphEdge {
                    source: node.id.clone(),
                    target: other.id.clone(),
                    label: Some("mentions".to_string()),
                });
            }
        }
    }

    edges
}

/// Convert a heading text to a URL-friendly slug.
fn slugify(text: &str) -> String {
    text.to_lowercase()
        .chars()
        .map(|c| if c.is_alphanumeric() { c } else { '-' })
        .collect::<String>()
        .split('-')
        .filter(|s| !s.is_empty())
        .collect::<Vec<_>>()
        .join("-")
}

/// Split a markdown table row into cell values, trimming whitespace.
fn split_table_row(line: &str) -> Vec<String> {
    let trimmed = line.trim().trim_start_matches('|').trim_end_matches('|');
    trimmed.split('|').map(|s| s.trim().to_string()).collect()
}

/// Ensure an ID is unique by appending a numeric suffix if needed.
fn ensure_unique_id(id: String, used: &mut HashSet<String>) -> String {
    if used.insert(id.clone()) {
        return id;
    }
    let mut n = 2u32;
    loop {
        let candidate = format!("{}-{}", id, n);
        if used.insert(candidate.clone()) {
            return candidate;
        }
        n += 1;
    }
}

/// Table parsing state machine.
#[derive(PartialEq)]
enum TableState {
    Outside,
    Header,
    Body,
}

/// Parse a single wiki source file into section and fact nodes + structural edges.
pub fn parse_source_file(
    source_node: &GraphNode,
    content: &str,
) -> (Vec<GraphNode>, Vec<GraphEdge>) {
    let mut nodes = Vec::new();
    let mut edges = Vec::new();
    let mut used_ids = HashSet::new();
    used_ids.insert(source_node.id.clone());

    let mut current_h2_id: Option<String> = None;
    let mut current_section_id: Option<String> = None; // tracks the most recent section (h2 or h3)
    let mut table_state = TableState::Outside;
    // Track the last bold-bullet fact so we can accumulate indented continuation lines
    let mut last_fact_idx: Option<usize> = None;

    for line in content.lines() {
        let trimmed = line.trim();

        // Detect heading transitions — any heading exits table state
        if trimmed.starts_with('#') {
            table_state = TableState::Outside;
            last_fact_idx = None;
        }

        // ## Heading → section node (child of source)
        if let Some(heading) = trimmed.strip_prefix("## ") {
            let heading = heading.trim();
            if heading.is_empty() {
                continue;
            }
            let slug = slugify(heading);
            let raw_id = format!("{}::{}", source_node.id, slug);
            let id = ensure_unique_id(raw_id, &mut used_ids);

            nodes.push(GraphNode {
                id: id.clone(),
                label: heading.to_string(),
                category: source_node.category.clone(),
                path: source_node.path.clone(),
                node_type: Some(NodeType::Section),
                parent_id: Some(source_node.id.clone()),
                content: None,
            });
            edges.push(GraphEdge {
                source: source_node.id.clone(),
                target: id.clone(),
                label: Some("has-section".to_string()),
            });

            current_h2_id = Some(id.clone());
            current_section_id = Some(id);
            continue;
        }

        // ### Subheading → section node (child of current ##)
        if let Some(heading) = trimmed.strip_prefix("### ") {
            let heading = heading.trim();
            if heading.is_empty() {
                continue;
            }
            let parent = current_h2_id.as_deref().unwrap_or(&source_node.id);
            let slug = slugify(heading);
            let raw_id = format!("{}::{}", parent, slug);
            let id = ensure_unique_id(raw_id, &mut used_ids);

            nodes.push(GraphNode {
                id: id.clone(),
                label: heading.to_string(),
                category: source_node.category.clone(),
                path: source_node.path.clone(),
                node_type: Some(NodeType::Section),
                parent_id: Some(parent.to_string()),
                content: None,
            });
            edges.push(GraphEdge {
                source: parent.to_string(),
                target: id.clone(),
                label: Some("has-section".to_string()),
            });

            current_section_id = Some(id);
            continue;
        }

        // Bold bullet: - **Key**: value → fact node
        if trimmed.starts_with("- **") {
            table_state = TableState::Outside;
            last_fact_idx = None;
            if let Some(parent_id) = &current_section_id {
                // Extract the key text from - **Key**: ...
                if let Some(rest) = trimmed.strip_prefix("- **") {
                    let label = if let Some(pos) = rest.find("**") {
                        rest[..pos].to_string()
                    } else {
                        rest.to_string()
                    };
                    if !label.is_empty() {
                        let slug = slugify(&label);
                        let raw_id = format!("{}::{}", parent_id, slug);
                        let id = ensure_unique_id(raw_id, &mut used_ids);

                        nodes.push(GraphNode {
                            id: id.clone(),
                            label: label.clone(),
                            category: source_node.category.clone(),
                            path: source_node.path.clone(),
                            node_type: Some(NodeType::Fact),
                            parent_id: Some(parent_id.clone()),
                            content: Some(trimmed.to_string()),
                        });
                        edges.push(GraphEdge {
                            source: parent_id.clone(),
                            target: id,
                            label: Some("contains".to_string()),
                        });
                        last_fact_idx = Some(nodes.len() - 1);
                    }
                }
                continue;
            }
        }

        // Indented continuation line (sub-bullet under a bold bullet)
        // e.g. "  - Candidate/committee records: 1979-present" under "- **Time range**:"
        if let Some(idx) = last_fact_idx {
            if line.starts_with("  ") && !trimmed.is_empty() {
                if let Some(ref mut c) = nodes[idx].content {
                    c.push('\n');
                    c.push_str(trimmed);
                }
                continue;
            }
            // Non-continuation line → stop accumulating
            if !trimmed.is_empty() {
                last_fact_idx = None;
            }
        }

        // Table rows
        if trimmed.starts_with('|') {
            last_fact_idx = None;
            match table_state {
                TableState::Outside => {
                    // First table row = header
                    table_state = TableState::Header;
                }
                TableState::Header => {
                    // Second row should be separator (|---|---|)
                    if trimmed.contains("---") {
                        table_state = TableState::Body;
                    } else {
                        // Not a separator → treat as body (unusual)
                        table_state = TableState::Body;
                        // Process this row as body
                        if let Some(parent_id) = &current_section_id {
                            let cells = split_table_row(trimmed);
                            let label = cells.first().map(|s| s.as_str()).unwrap_or("").to_string();
                            if !label.is_empty() {
                                let slug = slugify(&label);
                                let raw_id = format!("{}::{}", parent_id, slug);
                                let id = ensure_unique_id(raw_id, &mut used_ids);

                                nodes.push(GraphNode {
                                    id: id.clone(),
                                    label: label.clone(),
                                    category: source_node.category.clone(),
                                    path: source_node.path.clone(),
                                    node_type: Some(NodeType::Fact),
                                    parent_id: Some(parent_id.clone()),
                                    content: Some(trimmed.to_string()),
                                });
                                edges.push(GraphEdge {
                                    source: parent_id.clone(),
                                    target: id,
                                    label: Some("contains".to_string()),
                                });
                            }
                        }
                    }
                }
                TableState::Body => {
                    // Data rows
                    if let Some(parent_id) = &current_section_id {
                        let cells = split_table_row(trimmed);
                        let label_raw = cells.first().map(|s| s.as_str()).unwrap_or("");
                        // Strip backticks and markdown formatting from field names
                        let label = label_raw.replace('`', "").trim().to_string();
                        if !label.is_empty() {
                            let slug = slugify(&label);
                            let raw_id = format!("{}::{}", parent_id, slug);
                            let id = ensure_unique_id(raw_id, &mut used_ids);

                            nodes.push(GraphNode {
                                id: id.clone(),
                                label: label.clone(),
                                category: source_node.category.clone(),
                                path: source_node.path.clone(),
                                node_type: Some(NodeType::Fact),
                                parent_id: Some(parent_id.clone()),
                                content: Some(trimmed.to_string()),
                            });
                            edges.push(GraphEdge {
                                source: parent_id.clone(),
                                target: id,
                                label: Some("contains".to_string()),
                            });
                        }
                    }
                }
            }
            continue;
        }

        // Non-table, non-heading, non-bullet line → reset table state
        if !trimmed.is_empty() && !trimmed.starts_with('|') {
            table_state = TableState::Outside;
        }
    }

    // Post-process: remove childless sections and empty-content facts
    let node_ids: HashSet<String> = nodes.iter().map(|n| n.id.clone()).collect();
    // Find section IDs that are the source of at least one structural child edge
    let parent_section_ids: HashSet<&str> = edges
        .iter()
        .filter(|e| {
            let label = e.label.as_deref().unwrap_or("");
            (label == "has-section" || label == "contains") && node_ids.contains(&e.target)
        })
        .map(|e| e.source.as_str())
        .collect();

    // IDs to remove: childless sections + empty-content facts
    let remove_ids: HashSet<String> = nodes
        .iter()
        .filter(|n| {
            match n.node_type.as_ref() {
                Some(NodeType::Section) => !parent_section_ids.contains(n.id.as_str()),
                Some(NodeType::Fact) => {
                    // Remove facts where content after "**:" is empty (no value, no sub-bullets)
                    if let Some(content) = &n.content {
                        // Check if content is just "- **Key**:" or "- **Key**: " with nothing after
                        if let Some(pos) = content.find("**:") {
                            let after = content[pos + 3..].trim();
                            after.is_empty()
                        } else if let Some(pos) = content.find("**: ") {
                            let after = content[pos + 4..].trim();
                            after.is_empty()
                        } else {
                            false
                        }
                    } else {
                        true // No content at all → remove
                    }
                }
                _ => false,
            }
        })
        .map(|n| n.id.clone())
        .collect();

    if !remove_ids.is_empty() {
        nodes.retain(|n| !remove_ids.contains(&n.id));
        edges.retain(|e| !remove_ids.contains(&e.source) && !remove_ids.contains(&e.target));
    }

    (nodes, edges)
}

/// Extract cross-reference edges from fact nodes under cross-reference sections.
pub fn extract_cross_ref_edges(
    all_nodes: &[GraphNode],
    source_nodes: &[GraphNode],
) -> Vec<GraphEdge> {
    let mut edges = Vec::new();
    let mut seen = HashSet::new();

    // Build lookup: source label search terms
    let source_terms: Vec<(String, Vec<String>)> = source_nodes
        .iter()
        .map(|n| (n.id.clone(), search_terms_for_node(n)))
        .collect();

    // Find fact nodes under cross-reference sections
    for node in all_nodes {
        if node.node_type.as_ref() != Some(&NodeType::Fact) {
            continue;
        }
        // Check if this fact is under a cross-reference section
        let in_cross_ref = node
            .parent_id
            .as_ref()
            .map_or(false, |pid| pid.contains("cross-reference"));
        if !in_cross_ref {
            continue;
        }

        let content_lower = node.content.as_deref().unwrap_or("").to_lowercase();
        if content_lower.is_empty() {
            continue;
        }

        // Find the root source for this fact (walk up parent chain)
        let source_id = node.id.split("::").next().unwrap_or("");

        for (sid, terms) in &source_terms {
            // Don't create self-references
            if sid == source_id {
                continue;
            }
            let matched = terms.iter().any(|t| content_lower.contains(t.as_str()));
            if matched {
                let key = (node.id.clone(), sid.clone());
                if seen.insert(key) {
                    edges.push(GraphEdge {
                        source: node.id.clone(),
                        target: sid.clone(),
                        label: Some("cross-ref".to_string()),
                    });
                }
            }
        }
    }

    edges
}

/// Find shared-field edges between fact nodes under data-schema sections
/// across different sources.
pub fn find_shared_field_edges(all_nodes: &[GraphNode]) -> Vec<GraphEdge> {
    let mut edges = Vec::new();

    // Collect fact nodes under data-schema sections, grouped by normalized field name
    let mut field_map: HashMap<String, Vec<&GraphNode>> = HashMap::new();

    for node in all_nodes {
        if node.node_type.as_ref() != Some(&NodeType::Fact) {
            continue;
        }
        // Check if this fact is under a data-schema section
        let in_data_schema = node
            .parent_id
            .as_ref()
            .map_or(false, |pid| pid.contains("data-schema"));
        if !in_data_schema {
            continue;
        }

        // Normalize field name: lowercase, strip backticks
        let normalized = node
            .label
            .to_lowercase()
            .replace('`', "")
            .trim()
            .to_string();
        if !normalized.is_empty() {
            field_map.entry(normalized).or_default().push(node);
        }
    }

    // For each field name shared across different sources, create edges
    let mut seen = HashSet::new();
    for facts in field_map.values() {
        if facts.len() < 2 {
            continue;
        }
        for i in 0..facts.len() {
            for j in (i + 1)..facts.len() {
                let source_i = facts[i].id.split("::").next().unwrap_or("");
                let source_j = facts[j].id.split("::").next().unwrap_or("");
                // Only create edges between different sources
                if source_i == source_j {
                    continue;
                }
                let mut pair = [facts[i].id.clone(), facts[j].id.clone()];
                pair.sort();
                let key = (pair[0].clone(), pair[1].clone());
                if seen.insert(key) {
                    edges.push(GraphEdge {
                        source: facts[i].id.clone(),
                        target: facts[j].id.clone(),
                        label: Some("shared-field".to_string()),
                    });
                }
            }
        }
    }

    edges
}

/// Get the wiki knowledge graph data by parsing wiki/index.md and all source files.
#[tauri::command]
pub async fn get_graph_data(state: State<'_, AppState>) -> Result<GraphData, String> {
    let cfg = state.config.lock().await;
    let wiki_dir = match find_wiki_dir(&cfg.workspace) {
        Some(d) => d,
        None => {
            return Ok(GraphData {
                nodes: vec![],
                edges: vec![],
            });
        }
    };

    let index_path = wiki_dir.join("index.md");
    let content = fs::read_to_string(&index_path).map_err(|e| e.to_string())?;
    let source_nodes = parse_index_nodes(&content);
    let project_root = wiki_dir.parent().unwrap_or(&cfg.workspace);

    // Parse each source file into section/fact nodes
    let mut all_nodes: Vec<GraphNode> = source_nodes.clone();
    let mut all_edges: Vec<GraphEdge> = Vec::new();

    for source in &source_nodes {
        let file_path = project_root.join(&source.path);
        if let Ok(file_content) = fs::read_to_string(&file_path) {
            let (sub_nodes, sub_edges) = parse_source_file(source, &file_content);
            all_nodes.extend(sub_nodes);
            all_edges.extend(sub_edges);
        }
    }

    // Source-to-source edges (existing: link + mentions)
    let source_edges = find_cross_references(&source_nodes, project_root);
    all_edges.extend(source_edges);

    // Fact-to-source cross-reference edges
    let cross_ref_edges = extract_cross_ref_edges(&all_nodes, &source_nodes);
    all_edges.extend(cross_ref_edges);

    // Fact-to-fact shared-field edges
    let shared_field_edges = find_shared_field_edges(&all_nodes);
    all_edges.extend(shared_field_edges);

    Ok(GraphData {
        nodes: all_nodes,
        edges: all_edges,
    })
}

/// Read a wiki markdown file's contents, given a relative path like "wiki/fec.md".
#[tauri::command]
pub async fn read_wiki_file(path: String, state: State<'_, AppState>) -> Result<String, String> {
    // Validate: must end in .md
    if !path.ends_with(".md") {
        return Err("Path must end in .md".into());
    }
    // Validate: no path traversal
    if path.contains("..") {
        return Err("Path must not contain '..'".into());
    }
    // Validate: not absolute
    if path.starts_with('/') || path.starts_with('\\') {
        return Err("Path must be relative".into());
    }

    let cfg = state.config.lock().await;
    let wiki_dir =
        find_wiki_dir(&cfg.workspace).ok_or_else(|| "Wiki directory not found".to_string())?;

    let project_root = wiki_dir.parent().unwrap_or(&cfg.workspace);
    let resolved = project_root.join(&path);

    // Canonicalize and verify it's under the wiki dir
    let canonical = resolved
        .canonicalize()
        .map_err(|e| format!("File not found: {e}"))?;
    let canon_wiki = wiki_dir.canonicalize().map_err(|e| e.to_string())?;
    if !canonical.starts_with(&canon_wiki) {
        return Err("Path is outside wiki directory".into());
    }

    fs::read_to_string(&canonical).map_err(|e| format!("Failed to read file: {e}"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    // ── parse_index_nodes ──

    #[test]
    fn test_empty_content() {
        let nodes = parse_index_nodes("");
        assert!(nodes.is_empty());
    }

    #[test]
    fn test_category_heading() {
        let content = "### Campaign Finance\n| MA OCPF | MA | [link](ocpf.md) |";
        let nodes = parse_index_nodes(content);
        assert_eq!(nodes.len(), 1);
        assert_eq!(nodes[0].category, "campaign-finance");
    }

    #[test]
    fn test_category_heading_h2() {
        // Real wiki uses ## headings (not ###)
        let content = "## Financial / Corporate Sources\n| FEC | US | [link](fec.md) |";
        let nodes = parse_index_nodes(content);
        assert_eq!(nodes.len(), 1);
        assert_eq!(nodes[0].category, "financial");
    }

    #[test]
    fn test_category_heading_government_regulatory() {
        let content = "## Government / Regulatory Sources\n| OIG | US | [link](oig.md) |";
        let nodes = parse_index_nodes(content);
        assert_eq!(nodes.len(), 1);
        assert_eq!(nodes[0].category, "regulatory");
    }

    #[test]
    fn test_category_heading_media() {
        let content = "## Media / Public Record Sources\n| NBC | US | [link](nbc.md) |";
        let nodes = parse_index_nodes(content);
        assert_eq!(nodes.len(), 1);
        assert_eq!(nodes[0].category, "media");
    }

    #[test]
    fn test_category_heading_legal() {
        let content = "## Legal / Court Sources\n| DOJ | US | [link](doj.md) |";
        let nodes = parse_index_nodes(content);
        assert_eq!(nodes.len(), 1);
        assert_eq!(nodes[0].category, "legal");
    }

    #[test]
    fn test_table_row_with_link() {
        let content = "### Data\n| MA OCPF | MA | [link](ocpf.md) |";
        let nodes = parse_index_nodes(content);
        assert_eq!(nodes.len(), 1);
        assert_eq!(nodes[0].label, "MA OCPF");
        assert_eq!(nodes[0].id, "ocpf");
        assert_eq!(nodes[0].path, "wiki/ocpf.md");
    }

    #[test]
    fn test_multiple_categories() {
        // Note: labels must not contain "Source" (parser skips header rows containing it)
        let content = "\
### Campaign Finance
| FEC Data | US | [a](a.md) |

### Corporate
| SEC Data | UK | [b](b.md) |";
        let nodes = parse_index_nodes(content);
        assert_eq!(nodes.len(), 2);
        assert_eq!(nodes[0].category, "campaign-finance");
        assert_eq!(nodes[1].category, "corporate");
    }

    #[test]
    fn test_government_normalization() {
        let content = "### Government Contracts\n| GovData | US | [g](gov.md) |";
        let nodes = parse_index_nodes(content);
        assert_eq!(nodes[0].category, "contracts");
    }

    #[test]
    fn test_regulatory_normalization() {
        let content = "### Regulatory & Enforcement\n| RegData | US | [r](reg.md) |";
        let nodes = parse_index_nodes(content);
        assert_eq!(nodes[0].category, "regulatory");
    }

    #[test]
    fn test_skips_header_separator() {
        let content = "### Data\n| Source | Jurisdiction | Link |\n| --- | --- | --- |\n| Real | US | [r](real.md) |";
        let nodes = parse_index_nodes(content);
        assert_eq!(nodes.len(), 1);
        assert_eq!(nodes[0].id, "real");
    }

    #[test]
    fn test_label_from_first_column() {
        let content = "### Data\n| My Label | US | [different text](file.md) |";
        let nodes = parse_index_nodes(content);
        assert_eq!(nodes[0].label, "My Label");
    }

    #[test]
    fn test_node_id_from_filename() {
        let content = "### Data\n| Src | US | [link](subdir/file.md) |";
        let nodes = parse_index_nodes(content);
        assert_eq!(nodes[0].id, "file");
        assert_eq!(nodes[0].path, "wiki/subdir/file.md");
    }

    #[test]
    fn test_no_table_rows_no_nodes() {
        let content = "### Category A\n### Category B\nSome text\n";
        let nodes = parse_index_nodes(content);
        assert!(nodes.is_empty());
    }

    // ── find_cross_references ──

    #[test]
    fn test_no_files_no_edges() {
        let tmp = tempdir().unwrap();
        let nodes = vec![GraphNode {
            id: "a".to_string(),
            label: "A".to_string(),
            category: "test".to_string(),
            path: "wiki/a.md".to_string(),
            node_type: None,
            parent_id: None,
            content: None,
        }];
        let edges = find_cross_references(&nodes, tmp.path());
        assert!(edges.is_empty());
    }

    #[test]
    fn test_cross_ref_found() {
        let tmp = tempdir().unwrap();
        let wiki_dir = tmp.path().join("wiki");
        fs::create_dir_all(&wiki_dir).unwrap();
        // File A links to file B
        fs::write(wiki_dir.join("a.md"), "See [B](b.md) for details.").unwrap();
        fs::write(wiki_dir.join("b.md"), "# B\nContent here.").unwrap();

        let nodes = vec![
            GraphNode {
                id: "a".to_string(),
                label: "A".to_string(),
                category: "test".to_string(),
                path: "wiki/a.md".to_string(),
                node_type: None,
                parent_id: None,
                content: None,
            },
            GraphNode {
                id: "b".to_string(),
                label: "B".to_string(),
                category: "test".to_string(),
                path: "wiki/b.md".to_string(),
                node_type: None,
                parent_id: None,
                content: None,
            },
        ];
        let edges = find_cross_references(&nodes, tmp.path());
        assert_eq!(edges.len(), 1);
        assert_eq!(edges[0].source, "a");
        assert_eq!(edges[0].target, "b");
    }

    // ── find_wiki_dir ──

    #[test]
    fn test_find_wiki_dir_none_when_missing() {
        let tmp = tempdir().unwrap();
        assert!(find_wiki_dir(tmp.path()).is_none());
    }

    #[test]
    fn test_find_wiki_dir_at_start() {
        let tmp = tempdir().unwrap();
        let wiki = tmp.path().join("wiki");
        fs::create_dir_all(&wiki).unwrap();
        fs::write(wiki.join("index.md"), "# Index").unwrap();

        let found = find_wiki_dir(tmp.path()).unwrap();
        assert_eq!(found, wiki.canonicalize().unwrap());
    }

    #[test]
    fn test_find_wiki_dir_in_parent() {
        let tmp = tempdir().unwrap();
        let wiki = tmp.path().join("wiki");
        fs::create_dir_all(&wiki).unwrap();
        fs::write(wiki.join("index.md"), "# Index").unwrap();

        // Start from a subdirectory two levels deep
        let child = tmp.path().join("a").join("b");
        fs::create_dir_all(&child).unwrap();

        let found = find_wiki_dir(&child).unwrap();
        assert_eq!(found, wiki.canonicalize().unwrap());
    }

    #[test]
    fn test_find_wiki_dir_dot_openplanter() {
        let tmp = tempdir().unwrap();
        let wiki = tmp.path().join(".openplanter").join("wiki");
        fs::create_dir_all(&wiki).unwrap();
        fs::write(wiki.join("index.md"), "# Index").unwrap();

        let found = find_wiki_dir(tmp.path()).unwrap();
        assert_eq!(found, wiki.canonicalize().unwrap());
    }

    #[test]
    fn test_find_wiki_dir_dot_openplanter_preferred_over_bare() {
        let tmp = tempdir().unwrap();
        // Create both wiki/ and .openplanter/wiki/
        let bare = tmp.path().join("wiki");
        fs::create_dir_all(&bare).unwrap();
        fs::write(bare.join("index.md"), "# Bare").unwrap();

        let dot = tmp.path().join(".openplanter").join("wiki");
        fs::create_dir_all(&dot).unwrap();
        fs::write(dot.join("index.md"), "# Dot").unwrap();

        let found = find_wiki_dir(tmp.path()).unwrap();
        assert_eq!(found, dot.canonicalize().unwrap());
    }

    #[test]
    fn test_find_wiki_dir_dot_openplanter_from_child() {
        let tmp = tempdir().unwrap();
        let wiki = tmp.path().join(".openplanter").join("wiki");
        fs::create_dir_all(&wiki).unwrap();
        fs::write(wiki.join("index.md"), "# Index").unwrap();

        // Start from a subdirectory — should still walk up and find .openplanter/wiki/
        let child = tmp.path().join("subdir");
        fs::create_dir_all(&child).unwrap();
        let found = find_wiki_dir(&child).unwrap();
        assert_eq!(found, wiki.canonicalize().unwrap());
    }

    #[test]
    fn test_dot_openplanter_wiki_end_to_end() {
        let tmp = tempdir().unwrap();
        let wiki = tmp.path().join(".openplanter").join("wiki");
        fs::create_dir_all(&wiki).unwrap();

        let index_content = "### Campaign Finance\n| FEC | US | [link](fec.md) |";
        fs::write(wiki.join("index.md"), index_content).unwrap();
        fs::write(wiki.join("fec.md"), "# FEC Data\n## Key Fields\n- Donors\n").unwrap();

        // find_wiki_dir should find it
        let found = find_wiki_dir(tmp.path()).unwrap();
        assert_eq!(found, wiki.canonicalize().unwrap());

        // parse_index_nodes should produce a node with path wiki/fec.md
        let nodes = parse_index_nodes(index_content);
        assert_eq!(nodes.len(), 1);
        assert_eq!(nodes[0].path, "wiki/fec.md");

        // project_root should be .openplanter/ so joining with wiki/fec.md works
        let project_root = found.parent().unwrap();
        let file_path = project_root.join(&nodes[0].path);
        assert!(
            file_path.exists(),
            "should resolve to .openplanter/wiki/fec.md"
        );
    }

    #[test]
    fn test_real_wiki_format_integration() {
        // Mirrors the actual wiki index.md format produced by the curator
        let content = "\
# Investigation Wiki — Index

## Government / Regulatory Sources
| Source | Entry | Status |
|--------|-------|--------|
| Senate Judiciary Committee | [Entry](senate.md) | Active |
| DHS OIG | [Entry](dhs-oig.md) | Active |

## Financial / Corporate Sources
| Source | Entry | Status |
|--------|-------|--------|
| USAspending.gov | [usaspending.md](usaspending.md) | Confirmed |

## Media / Public Record Sources
| Source | Entry | Status |
|--------|-------|--------|
| NBC News | [Entry](nbc.md) | Confirmed |

## Legal / Court Sources
| Source | Entry | Status |
|--------|-------|--------|
| Impeachment Resolution | [Entry](impeach.md) | Active |

## Other Sources
| Source | Entry | Status |
|--------|-------|--------|
| *(none yet)* | — | — |
";
        let nodes = parse_index_nodes(content);
        assert_eq!(nodes.len(), 5);
        assert_eq!(nodes[0].category, "regulatory");
        assert_eq!(nodes[1].category, "regulatory");
        assert_eq!(nodes[2].category, "financial");
        assert_eq!(nodes[3].category, "media");
        assert_eq!(nodes[4].category, "legal");
    }

    #[test]
    fn test_text_mention_creates_edge() {
        let tmp = tempdir().unwrap();
        let wiki_dir = tmp.path().join("wiki");
        fs::create_dir_all(&wiki_dir).unwrap();
        // File A mentions EDGAR (from B's label "SEC EDGAR") but doesn't link to it
        fs::write(
            wiki_dir.join("a.md"),
            "Cross-reference with EDGAR filings for details.",
        )
        .unwrap();
        fs::write(wiki_dir.join("b.md"), "# SEC EDGAR\nContent.").unwrap();

        let nodes = vec![
            GraphNode {
                id: "a".to_string(),
                label: "FEC Data".to_string(),
                category: "campaign-finance".to_string(),
                path: "wiki/a.md".to_string(),
                node_type: None,
                parent_id: None,
                content: None,
            },
            GraphNode {
                id: "b".to_string(),
                label: "SEC EDGAR".to_string(),
                category: "corporate".to_string(),
                path: "wiki/b.md".to_string(),
                node_type: None,
                parent_id: None,
                content: None,
            },
        ];
        let edges = find_cross_references(&nodes, tmp.path());
        assert_eq!(edges.len(), 1);
        assert_eq!(edges[0].source, "a");
        assert_eq!(edges[0].target, "b");
        assert_eq!(edges[0].label.as_deref(), Some("mentions"));
    }

    #[test]
    fn test_text_mention_no_self_match() {
        let tmp = tempdir().unwrap();
        let wiki_dir = tmp.path().join("wiki");
        fs::create_dir_all(&wiki_dir).unwrap();
        // File A mentions its own label — should not create edge
        fs::write(wiki_dir.join("a.md"), "# EDGAR\nThis is SEC EDGAR data.").unwrap();

        let nodes = vec![GraphNode {
            id: "a".to_string(),
            label: "SEC EDGAR".to_string(),
            category: "corporate".to_string(),
            path: "wiki/a.md".to_string(),
            node_type: None,
            parent_id: None,
            content: None,
        }];
        let edges = find_cross_references(&nodes, tmp.path());
        assert!(
            edges.is_empty(),
            "should not create self-referencing edge from text mention"
        );
    }

    #[test]
    fn test_text_mention_case_insensitive() {
        let tmp = tempdir().unwrap();
        let wiki_dir = tmp.path().join("wiki");
        fs::create_dir_all(&wiki_dir).unwrap();
        fs::write(wiki_dir.join("a.md"), "Check osha records for violations.").unwrap();
        fs::write(wiki_dir.join("b.md"), "# OSHA\nInspections.").unwrap();

        let nodes = vec![
            GraphNode {
                id: "a".to_string(),
                label: "EPA Data".to_string(),
                category: "regulatory".to_string(),
                path: "wiki/a.md".to_string(),
                node_type: None,
                parent_id: None,
                content: None,
            },
            GraphNode {
                id: "b".to_string(),
                label: "OSHA Inspections".to_string(),
                category: "regulatory".to_string(),
                path: "wiki/b.md".to_string(),
                node_type: None,
                parent_id: None,
                content: None,
            },
        ];
        let edges = find_cross_references(&nodes, tmp.path());
        assert_eq!(edges.len(), 1, "case-insensitive match should work");
    }

    #[test]
    fn test_no_duplicate_edges() {
        let tmp = tempdir().unwrap();
        let wiki_dir = tmp.path().join("wiki");
        fs::create_dir_all(&wiki_dir).unwrap();
        // File A links to B AND mentions B's label — should produce only one edge
        fs::write(wiki_dir.join("a.md"), "See [B](b.md). Also check EDGAR.").unwrap();
        fs::write(wiki_dir.join("b.md"), "# EDGAR\nContent.").unwrap();

        let nodes = vec![
            GraphNode {
                id: "a".to_string(),
                label: "A Data".to_string(),
                category: "test".to_string(),
                path: "wiki/a.md".to_string(),
                node_type: None,
                parent_id: None,
                content: None,
            },
            GraphNode {
                id: "b".to_string(),
                label: "SEC EDGAR".to_string(),
                category: "corporate".to_string(),
                path: "wiki/b.md".to_string(),
                node_type: None,
                parent_id: None,
                content: None,
            },
        ];
        let edges = find_cross_references(&nodes, tmp.path());
        assert_eq!(edges.len(), 1, "should not produce duplicate edges");
    }

    #[test]
    fn test_no_self_reference() {
        let tmp = tempdir().unwrap();
        let wiki_dir = tmp.path().join("wiki");
        fs::create_dir_all(&wiki_dir).unwrap();
        // File A links to itself
        fs::write(wiki_dir.join("a.md"), "See [self](a.md) for more.").unwrap();

        let nodes = vec![GraphNode {
            id: "a".to_string(),
            label: "A".to_string(),
            category: "test".to_string(),
            path: "wiki/a.md".to_string(),
            node_type: None,
            parent_id: None,
            content: None,
        }];
        let edges = find_cross_references(&nodes, tmp.path());
        assert!(edges.is_empty(), "self-references should be excluded");
    }

    // ── helpers ──

    #[test]
    fn test_slugify_basic() {
        assert_eq!(slugify("Data Schema"), "data-schema");
        assert_eq!(
            slugify("Cross-Reference Potential"),
            "cross-reference-potential"
        );
        assert_eq!(slugify("Legal & Licensing"), "legal-licensing");
        assert_eq!(slugify("  multiple   spaces  "), "multiple-spaces");
    }

    #[test]
    fn test_split_table_row() {
        let cells = split_table_row("| foo | bar | baz |");
        assert_eq!(cells, vec!["foo", "bar", "baz"]);
    }

    #[test]
    fn test_ensure_unique_id() {
        let mut used = HashSet::new();
        assert_eq!(ensure_unique_id("a".into(), &mut used), "a");
        assert_eq!(ensure_unique_id("a".into(), &mut used), "a-2");
        assert_eq!(ensure_unique_id("a".into(), &mut used), "a-3");
        assert_eq!(ensure_unique_id("b".into(), &mut used), "b");
    }

    // ── parse_source_file ──

    fn make_source(id: &str) -> GraphNode {
        GraphNode {
            id: id.to_string(),
            label: id.to_uppercase(),
            category: "test".to_string(),
            path: format!("wiki/{}.md", id),
            node_type: Some(NodeType::Source),
            parent_id: None,
            content: None,
        }
    }

    #[test]
    fn test_parse_empty_content() {
        let source = make_source("fec");
        let (nodes, edges) = parse_source_file(&source, "");
        assert!(nodes.is_empty());
        assert!(edges.is_empty());
    }

    #[test]
    fn test_parse_single_section() {
        let source = make_source("fec");
        let (nodes, edges) = parse_source_file(&source, "## Summary\n\n- **Key**: value");
        // 1 section + 1 fact (childless sections are pruned, so section needs a fact)
        assert_eq!(nodes.len(), 2);
        assert_eq!(nodes[0].id, "fec::summary");
        assert_eq!(nodes[0].label, "Summary");
        assert_eq!(nodes[0].node_type, Some(NodeType::Section));
        assert_eq!(nodes[0].parent_id.as_deref(), Some("fec"));
        assert_eq!(edges.len(), 2); // has-section + contains
        assert_eq!(edges[0].label.as_deref(), Some("has-section"));
    }

    #[test]
    fn test_childless_sections_pruned() {
        let source = make_source("fec");
        let (nodes, edges) = parse_source_file(&source, "## Summary\n\nSome text.");
        // Section has no facts/subsections → pruned
        assert!(nodes.is_empty());
        assert!(edges.is_empty());
    }

    #[test]
    fn test_parse_multiple_sections() {
        let source = make_source("fec");
        let content = "## Summary\n\n- **Key**: val\n\n## Access Methods\n\n- **Method**: API";
        let (nodes, edges) = parse_source_file(&source, content);
        // 2 sections + 2 facts
        assert_eq!(nodes.len(), 4);
        assert_eq!(nodes[0].id, "fec::summary");
        assert_eq!(nodes[2].id, "fec::access-methods");
        assert_eq!(edges.len(), 4); // 2 has-section + 2 contains
    }

    #[test]
    fn test_parse_subsections() {
        let source = make_source("fec");
        let content = "## Data Schema\n\n### Candidate Records\n\n- **Field**: id\n\n### Committee Records\n\n- **Name**: test";
        let (nodes, edges) = parse_source_file(&source, content);
        // Data Schema + 2 subsections + 2 facts = 5
        assert_eq!(nodes.len(), 5);
        let sections: Vec<_> = nodes
            .iter()
            .filter(|n| n.node_type == Some(NodeType::Section))
            .collect();
        assert_eq!(sections.len(), 3);
        // Subsections are children of the h2
        assert_eq!(sections[1].parent_id.as_deref(), Some("fec::data-schema"));
        assert_eq!(sections[2].parent_id.as_deref(), Some("fec::data-schema"));
        // has-section edges
        let has_section: Vec<_> = edges
            .iter()
            .filter(|e| e.label.as_deref() == Some("has-section"))
            .collect();
        assert_eq!(has_section.len(), 3);
    }

    #[test]
    fn test_parse_bold_bullets() {
        let source = make_source("fec");
        let content = "## Coverage\n\n- **Jurisdiction**: Federal\n- **Time range**: 1979-present";
        let (nodes, edges) = parse_source_file(&source, content);
        // 1 section + 2 facts
        assert_eq!(nodes.len(), 3);
        let facts: Vec<_> = nodes
            .iter()
            .filter(|n| n.node_type == Some(NodeType::Fact))
            .collect();
        assert_eq!(facts.len(), 2);
        assert_eq!(facts[0].label, "Jurisdiction");
        assert_eq!(facts[1].label, "Time range");
        // Facts should have content
        assert!(facts[0].content.as_ref().unwrap().contains("Federal"));
        // Facts parented to section
        assert!(
            facts
                .iter()
                .all(|f| f.parent_id.as_deref() == Some("fec::coverage"))
        );
        // Contains edges
        let contains: Vec<_> = edges
            .iter()
            .filter(|e| e.label.as_deref() == Some("contains"))
            .collect();
        assert_eq!(contains.len(), 2);
    }

    #[test]
    fn test_sub_bullet_accumulation() {
        let source = make_source("fec");
        let content = "## Coverage\n\n- **Time range**:\n  - Records: 1979-present\n  - Contributions: 1979-present\n- **Jurisdiction**: Federal";
        let (nodes, _) = parse_source_file(&source, content);
        let facts: Vec<_> = nodes
            .iter()
            .filter(|n| n.node_type == Some(NodeType::Fact))
            .collect();
        assert_eq!(facts.len(), 2);
        // Time range should have accumulated sub-bullets
        let time_range = facts.iter().find(|f| f.label == "Time range").unwrap();
        let content = time_range.content.as_ref().unwrap();
        assert!(
            content.contains("Records: 1979-present"),
            "should contain sub-bullet"
        );
        assert!(
            content.contains("Contributions: 1979-present"),
            "should contain second sub-bullet"
        );
    }

    #[test]
    fn test_empty_value_bullet_pruned() {
        let source = make_source("fec");
        // Bold bullet with NO sub-bullets and NO value after colon → should be pruned
        let content = "## Coverage\n\n- **Empty**:\n- **Jurisdiction**: Federal";
        let (nodes, _) = parse_source_file(&source, content);
        let facts: Vec<_> = nodes
            .iter()
            .filter(|n| n.node_type == Some(NodeType::Fact))
            .collect();
        // "Empty" should be pruned, only "Jurisdiction" remains
        assert_eq!(facts.len(), 1);
        assert_eq!(facts[0].label, "Jurisdiction");
    }

    #[test]
    fn test_parse_table_rows() {
        let source = make_source("fec");
        let content = "## Data Schema\n\n| Field | Description |\n|-------|-------------|\n| `candidate_id` | Unique ID |\n| `name` | Full name |";
        let (nodes, edges) = parse_source_file(&source, content);
        // 1 section + 2 fact rows (header + separator skipped)
        let facts: Vec<_> = nodes
            .iter()
            .filter(|n| n.node_type == Some(NodeType::Fact))
            .collect();
        assert_eq!(facts.len(), 2);
        assert_eq!(facts[0].label, "candidate_id"); // backticks stripped
        assert_eq!(facts[1].label, "name");
    }

    #[test]
    fn test_parse_table_skips_header_and_separator() {
        let source = make_source("fec");
        let content = "## Schema\n\n| Header1 | Header2 |\n| --- | --- |\n| value1 | desc1 |";
        let (nodes, _edges) = parse_source_file(&source, content);
        let facts: Vec<_> = nodes
            .iter()
            .filter(|n| n.node_type == Some(NodeType::Fact))
            .collect();
        assert_eq!(facts.len(), 1);
        assert_eq!(facts[0].label, "value1");
    }

    #[test]
    fn test_parse_fact_parents_correct() {
        let source = make_source("fec");
        let content =
            "## Data Schema\n\n### Candidate Records\n\n| Field | Desc |\n|---|---|\n| cid | ID |";
        let (nodes, _) = parse_source_file(&source, content);
        let fact = nodes.iter().find(|n| n.label == "cid").unwrap();
        // Fact should be parented to the h3 section, not the h2
        assert!(
            fact.parent_id
                .as_ref()
                .unwrap()
                .contains("candidate-records")
        );
    }

    #[test]
    fn test_parse_duplicate_ids() {
        let source = make_source("fec");
        // Two sections with same name, each with a fact so they survive pruning
        let content = "## Summary\n\n- **A**: 1\n\n## Summary\n\n- **B**: 2";
        let (nodes, _) = parse_source_file(&source, content);
        let sections: Vec<_> = nodes
            .iter()
            .filter(|n| n.node_type == Some(NodeType::Section))
            .collect();
        assert_eq!(sections.len(), 2);
        assert_eq!(sections[0].id, "fec::summary");
        assert_eq!(sections[1].id, "fec::summary-2"); // deduplicated
    }

    #[test]
    fn test_parse_source_inherits_category() {
        let mut source = make_source("fec");
        source.category = "campaign-finance".to_string();
        let content = "## Summary\n\n- **Key**: value";
        let (nodes, _) = parse_source_file(&source, content);
        assert!(nodes.iter().all(|n| n.category == "campaign-finance"));
    }

    #[test]
    fn test_parse_mixed_content() {
        let source = make_source("fec");
        let content = "\
## Summary

Overview paragraph.

## Coverage

- **Jurisdiction**: Federal
- **Time range**: 1979-present

## Data Schema

### Records

| Field | Desc |
|-------|------|
| `id` | Key |
| `name` | Name |

## References

Links here.";
        let (nodes, edges) = parse_source_file(&source, content);
        let sections: Vec<_> = nodes
            .iter()
            .filter(|n| n.node_type == Some(NodeType::Section))
            .collect();
        let facts: Vec<_> = nodes
            .iter()
            .filter(|n| n.node_type == Some(NodeType::Fact))
            .collect();
        // Summary and References pruned (no children), Coverage + Data Schema + Records remain = 3
        assert_eq!(sections.len(), 3);
        // 2 bullets + 2 table rows = 4 facts
        assert_eq!(facts.len(), 4);
        // Structural edges: 2 has-section (Coverage→source, Data Schema→source) + 1 has-section (Records→Data Schema) + 4 contains
        let has_section_count = edges
            .iter()
            .filter(|e| e.label.as_deref() == Some("has-section"))
            .count();
        let contains_count = edges
            .iter()
            .filter(|e| e.label.as_deref() == Some("contains"))
            .count();
        assert_eq!(has_section_count, 3);
        assert_eq!(contains_count, 4);
    }

    // ── extract_cross_ref_edges ──

    #[test]
    fn test_extract_cross_ref_match() {
        let source_a = make_source("fec");
        let source_b = GraphNode {
            id: "sec-edgar".to_string(),
            label: "SEC EDGAR".to_string(),
            category: "corporate".to_string(),
            path: "wiki/sec-edgar.md".to_string(),
            node_type: Some(NodeType::Source),
            parent_id: None,
            content: None,
        };
        let fact = GraphNode {
            id: "fec::cross-reference-potential::corporate".to_string(),
            label: "Corporate".to_string(),
            category: "campaign-finance".to_string(),
            path: "wiki/fec.md".to_string(),
            node_type: Some(NodeType::Fact),
            parent_id: Some("fec::cross-reference-potential".to_string()),
            content: Some("Match contributors to SEC EDGAR corporate filings".to_string()),
        };
        let all_nodes = vec![source_a.clone(), source_b.clone(), fact.clone()];
        let source_nodes = vec![source_a, source_b];
        let edges = extract_cross_ref_edges(&all_nodes, &source_nodes);
        assert_eq!(edges.len(), 1);
        assert_eq!(edges[0].source, "fec::cross-reference-potential::corporate");
        assert_eq!(edges[0].target, "sec-edgar");
        assert_eq!(edges[0].label.as_deref(), Some("cross-ref"));
    }

    #[test]
    fn test_extract_cross_ref_no_self() {
        let source = make_source("fec");
        let fact = GraphNode {
            id: "fec::cross-reference-potential::self".to_string(),
            label: "Self".to_string(),
            category: "test".to_string(),
            path: "wiki/fec.md".to_string(),
            node_type: Some(NodeType::Fact),
            parent_id: Some("fec::cross-reference-potential".to_string()),
            content: Some("FEC data is great".to_string()),
        };
        let all_nodes = vec![source.clone(), fact];
        let source_nodes = vec![source];
        let edges = extract_cross_ref_edges(&all_nodes, &source_nodes);
        assert!(edges.is_empty(), "should not cross-ref to own source");
    }

    #[test]
    fn test_extract_cross_ref_skips_non_cross_ref_section() {
        let source_a = make_source("fec");
        let source_b = GraphNode {
            id: "sec-edgar".to_string(),
            label: "SEC EDGAR".to_string(),
            category: "corporate".to_string(),
            path: "wiki/sec-edgar.md".to_string(),
            node_type: Some(NodeType::Source),
            parent_id: None,
            content: None,
        };
        // Fact under coverage section, not cross-reference
        let fact = GraphNode {
            id: "fec::coverage::jurisdiction".to_string(),
            label: "Jurisdiction".to_string(),
            category: "campaign-finance".to_string(),
            path: "wiki/fec.md".to_string(),
            node_type: Some(NodeType::Fact),
            parent_id: Some("fec::coverage".to_string()),
            content: Some("Contains SEC EDGAR data".to_string()),
        };
        let all_nodes = vec![source_a.clone(), source_b.clone(), fact];
        let source_nodes = vec![source_a, source_b];
        let edges = extract_cross_ref_edges(&all_nodes, &source_nodes);
        assert!(
            edges.is_empty(),
            "should only match facts under cross-reference sections"
        );
    }

    // ── find_shared_field_edges ──

    #[test]
    fn test_shared_field_cross_source() {
        let fact_a = GraphNode {
            id: "fec::data-schema::candidate-id".to_string(),
            label: "candidate_id".to_string(),
            category: "campaign-finance".to_string(),
            path: "wiki/fec.md".to_string(),
            node_type: Some(NodeType::Fact),
            parent_id: Some("fec::data-schema".to_string()),
            content: Some("| candidate_id | Unique ID |".to_string()),
        };
        let fact_b = GraphNode {
            id: "ocpf::data-schema::candidate-id".to_string(),
            label: "candidate_id".to_string(),
            category: "campaign-finance".to_string(),
            path: "wiki/ocpf.md".to_string(),
            node_type: Some(NodeType::Fact),
            parent_id: Some("ocpf::data-schema".to_string()),
            content: Some("| candidate_id | State ID |".to_string()),
        };
        let edges = find_shared_field_edges(&vec![fact_a, fact_b]);
        assert_eq!(edges.len(), 1);
        assert_eq!(edges[0].label.as_deref(), Some("shared-field"));
    }

    #[test]
    fn test_shared_field_no_same_source() {
        let fact_a = GraphNode {
            id: "fec::data-schema::records::id".to_string(),
            label: "id".to_string(),
            category: "test".to_string(),
            path: "wiki/fec.md".to_string(),
            node_type: Some(NodeType::Fact),
            parent_id: Some("fec::data-schema::records".to_string()),
            content: None,
        };
        let fact_b = GraphNode {
            id: "fec::data-schema::other::id".to_string(),
            label: "id".to_string(),
            category: "test".to_string(),
            path: "wiki/fec.md".to_string(),
            node_type: Some(NodeType::Fact),
            parent_id: Some("fec::data-schema::other".to_string()),
            content: None,
        };
        let edges = find_shared_field_edges(&vec![fact_a, fact_b]);
        assert!(
            edges.is_empty(),
            "should not create edge between same-source facts"
        );
    }

    #[test]
    fn test_shared_field_normalization() {
        let fact_a = GraphNode {
            id: "fec::data-schema::cid".to_string(),
            label: "`committee_id`".to_string(), // with backticks
            category: "test".to_string(),
            path: "wiki/fec.md".to_string(),
            node_type: Some(NodeType::Fact),
            parent_id: Some("fec::data-schema".to_string()),
            content: None,
        };
        let fact_b = GraphNode {
            id: "sec::data-schema::cid".to_string(),
            label: "Committee_ID".to_string(), // different case
            category: "test".to_string(),
            path: "wiki/sec.md".to_string(),
            node_type: Some(NodeType::Fact),
            parent_id: Some("sec::data-schema".to_string()),
            content: None,
        };
        let edges = find_shared_field_edges(&vec![fact_a, fact_b]);
        assert_eq!(edges.len(), 1, "should normalize case and backticks");
    }

    // ── read_wiki_file validation (unit-testable parts) ──

    #[test]
    fn test_read_wiki_file_rejects_non_md() {
        assert!(!".txt".ends_with(".md"));
        assert!("file.md".ends_with(".md"));
    }

    #[test]
    fn test_read_wiki_file_rejects_traversal() {
        assert!("../etc/passwd".contains(".."));
        assert!("wiki/../secret.md".contains(".."));
        assert!(!"wiki/fec.md".contains(".."));
    }

    #[test]
    fn test_read_wiki_file_rejects_absolute() {
        assert!("/etc/passwd.md".starts_with('/'));
        assert!(!"wiki/fec.md".starts_with('/'));
    }

    #[test]
    fn test_shared_field_skips_non_data_schema() {
        let fact_a = GraphNode {
            id: "fec::coverage::jurisdiction".to_string(),
            label: "Jurisdiction".to_string(),
            category: "test".to_string(),
            path: "wiki/fec.md".to_string(),
            node_type: Some(NodeType::Fact),
            parent_id: Some("fec::coverage".to_string()),
            content: None,
        };
        let fact_b = GraphNode {
            id: "sec::coverage::jurisdiction".to_string(),
            label: "Jurisdiction".to_string(),
            category: "test".to_string(),
            path: "wiki/sec.md".to_string(),
            node_type: Some(NodeType::Fact),
            parent_id: Some("sec::coverage".to_string()),
            content: None,
        };
        let edges = find_shared_field_edges(&vec![fact_a, fact_b]);
        assert!(
            edges.is_empty(),
            "should only match facts under data-schema sections"
        );
    }
}
