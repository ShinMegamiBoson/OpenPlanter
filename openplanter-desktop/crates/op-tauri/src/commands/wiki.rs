use std::collections::HashSet;
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

/// Find cross-references between nodes by reading wiki files from `wiki_dir`.
pub fn find_cross_references(nodes: &[GraphNode], wiki_dir: &Path) -> Vec<GraphEdge> {
    let link_re = Regex::new(r"\[([^\]]+)\]\(([^)]+\.md)\)").unwrap();
    let node_ids: HashSet<&str> = nodes.iter().map(|n| n.id.as_str()).collect();
    let mut edges = Vec::new();

    // wiki_dir is the workspace root; node.path is relative (e.g. "wiki/file.md")
    for node in nodes {
        let file_path = wiki_dir.join(&node.path);
        if !file_path.exists() {
            continue;
        }
        let file_content = match fs::read_to_string(&file_path) {
            Ok(c) => c,
            Err(_) => continue,
        };

        for caps in link_re.captures_iter(&file_content) {
            let ref_path = &caps[2];
            let ref_id = ref_path
                .rsplit('/')
                .next()
                .unwrap_or(ref_path)
                .trim_end_matches(".md");

            if ref_id != node.id && node_ids.contains(ref_id) {
                edges.push(GraphEdge {
                    source: node.id.clone(),
                    target: ref_id.to_string(),
                    label: Some("cross-ref".to_string()),
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
