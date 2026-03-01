use std::collections::{HashMap, HashSet};
use std::fs;
use std::path::{Path, PathBuf};
use regex::Regex;
use tauri::State;
use crate::state::AppState;
use op_core::events::{GraphData, GraphEdge, GraphNode};

/// Walk up from `start` to find a directory containing `wiki/index.md`.
fn find_wiki_dir(start: &Path) -> Option<PathBuf> {
    let mut dir = start.canonicalize().ok();
    while let Some(d) = dir {
        let wiki = d.join("wiki");
        if wiki.join("index.md").exists() {
            return Some(wiki);
        }
        dir = d.parent().map(|p| p.to_path_buf());
    }
    None
}

/// Parse wiki/index.md content into graph nodes.
pub fn parse_index_nodes(content: &str) -> Vec<GraphNode> {
    let mut nodes = Vec::new();
    let mut current_category = String::new();

    let link_re = Regex::new(r"\[([^\]]+)\]\(([^)]+\.md)\)").unwrap();
    let category_re = Regex::new(r"^###\s+(.+)").unwrap();

    for line in content.lines() {
        if let Some(caps) = category_re.captures(line) {
            current_category = caps[1].trim().to_lowercase().replace(' ', "-");
            if current_category.starts_with("government-") {
                current_category = current_category
                    .strip_prefix("government-")
                    .unwrap_or(&current_category)
                    .to_string();
            }
            if current_category.contains("regulatory") {
                current_category = "regulatory".to_string();
            }
            continue;
        }

        if !line.trim_start().starts_with('|') {
            continue;
        }
        if line.contains("---") || line.contains("Source") {
            continue;
        }

        if let Some(caps) = link_re.captures(line) {
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
            });
        }
    }

    nodes
}

/// Extract distinctive search terms from a node's label for text-based matching.
fn search_terms_for_node(node: &GraphNode) -> Vec<String> {
    let stopwords: HashSet<&str> = [
        "a", "an", "the", "of", "and", "or", "in", "to", "for", "by",
        "on", "at", "is", "it", "its", "us", "gov", "list",
    ].into_iter().collect();

    let generic: HashSet<&str> = [
        "federal", "state", "united", "states", "government", "bureau",
        "department", "database", "national", "public",
    ].into_iter().collect();

    let mut terms = Vec::new();

    // Full label (lowercased)
    terms.push(node.label.to_lowercase());

    for word in node.label.split(|c: char| c.is_whitespace() || c == '/' || c == '(' || c == ')') {
        let clean: String = word.chars()
            .filter(|c| c.is_alphanumeric() || *c == '.' || *c == '-')
            .collect();
        if clean.is_empty() { continue; }
        let lower = clean.to_lowercase();
        if stopwords.contains(lower.as_str()) { continue; }

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
    let link_re = Regex::new(r"\[([^\]]+)\]\(([^)]+\.md)\)").unwrap();
    let node_ids: HashSet<&str> = nodes.iter().map(|n| n.id.as_str()).collect();
    let mut edges = Vec::new();
    let mut seen: HashSet<(String, String)> = HashSet::new();

    // Pre-compute search terms for all nodes
    let node_terms: Vec<Vec<String>> = nodes.iter()
        .map(|n| search_terms_for_node(n))
        .collect();

    // Read all file contents upfront
    let file_contents: HashMap<String, String> = nodes.iter()
        .filter_map(|node| {
            let file_path = wiki_dir.join(&node.path);
            fs::read_to_string(&file_path).ok().map(|c| (node.id.clone(), c))
        })
        .collect();

    for (i, node) in nodes.iter().enumerate() {
        let file_content = match file_contents.get(&node.id) {
            Some(c) => c,
            None => continue,
        };

        // 1. Markdown link-based edges (existing logic)
        for caps in link_re.captures_iter(file_content) {
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
            if i == j { continue; }
            let key = (node.id.clone(), other.id.clone());
            if seen.contains(&key) { continue; }

            let matched = node_terms[j].iter().any(|term| content_lower.contains(term.as_str()));
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

/// Get the wiki knowledge graph data by parsing wiki/index.md.
#[tauri::command]
pub async fn get_graph_data(
    state: State<'_, AppState>,
) -> Result<GraphData, String> {
    let cfg = state.config.lock().await;
    let wiki_dir = match find_wiki_dir(&cfg.workspace) {
        Some(d) => d,
        None => return Ok(GraphData { nodes: vec![], edges: vec![] }),
    };

    let index_path = wiki_dir.join("index.md");
    let content = fs::read_to_string(&index_path).map_err(|e| e.to_string())?;
    let nodes = parse_index_nodes(&content);
    let project_root = wiki_dir.parent().unwrap_or(&cfg.workspace);
    let edges = find_cross_references(&nodes, project_root);

    Ok(GraphData { nodes, edges })
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
            },
            GraphNode {
                id: "b".to_string(),
                label: "B".to_string(),
                category: "test".to_string(),
                path: "wiki/b.md".to_string(),
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
    fn test_text_mention_creates_edge() {
        let tmp = tempdir().unwrap();
        let wiki_dir = tmp.path().join("wiki");
        fs::create_dir_all(&wiki_dir).unwrap();
        // File A mentions EDGAR (from B's label "SEC EDGAR") but doesn't link to it
        fs::write(wiki_dir.join("a.md"), "Cross-reference with EDGAR filings for details.").unwrap();
        fs::write(wiki_dir.join("b.md"), "# SEC EDGAR\nContent.").unwrap();

        let nodes = vec![
            GraphNode {
                id: "a".to_string(),
                label: "FEC Data".to_string(),
                category: "campaign-finance".to_string(),
                path: "wiki/a.md".to_string(),
            },
            GraphNode {
                id: "b".to_string(),
                label: "SEC EDGAR".to_string(),
                category: "corporate".to_string(),
                path: "wiki/b.md".to_string(),
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

        let nodes = vec![
            GraphNode {
                id: "a".to_string(),
                label: "SEC EDGAR".to_string(),
                category: "corporate".to_string(),
                path: "wiki/a.md".to_string(),
            },
        ];
        let edges = find_cross_references(&nodes, tmp.path());
        assert!(edges.is_empty(), "should not create self-referencing edge from text mention");
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
            },
            GraphNode {
                id: "b".to_string(),
                label: "OSHA Inspections".to_string(),
                category: "regulatory".to_string(),
                path: "wiki/b.md".to_string(),
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
            },
            GraphNode {
                id: "b".to_string(),
                label: "SEC EDGAR".to_string(),
                category: "corporate".to_string(),
                path: "wiki/b.md".to_string(),
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
        }];
        let edges = find_cross_references(&nodes, tmp.path());
        assert!(edges.is_empty(), "self-references should be excluded");
    }
}
