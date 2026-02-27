use std::collections::HashSet;
use std::fs;
use regex::Regex;
use tauri::State;
use crate::state::AppState;
use op_core::events::{GraphData, GraphEdge, GraphNode};

/// Get the wiki knowledge graph data by parsing wiki/index.md.
#[tauri::command]
pub async fn get_graph_data(
    state: State<'_, AppState>,
) -> Result<GraphData, String> {
    let cfg = state.config.lock().await;
    let wiki_dir = cfg.workspace.join("wiki");
    let index_path = wiki_dir.join("index.md");

    if !index_path.exists() {
        return Ok(GraphData {
            nodes: vec![],
            edges: vec![],
        });
    }

    let content = fs::read_to_string(&index_path).map_err(|e| e.to_string())?;

    let mut nodes = Vec::new();
    let mut current_category = String::new();

    // Parse index.md for table rows: | Name | ... | [file.md](path) |
    let link_re = Regex::new(r"\[([^\]]+)\]\(([^)]+\.md)\)").unwrap();
    let category_re = Regex::new(r"^###\s+(.+)").unwrap();

    for line in content.lines() {
        if let Some(caps) = category_re.captures(line) {
            current_category = caps[1].trim().to_lowercase().replace(' ', "-");
            // Normalize: "government contracts" -> "contracts"
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

        // Look for table rows with markdown links
        if !line.trim_start().starts_with('|') {
            continue;
        }
        // Skip header/separator rows
        if line.contains("---") || line.contains("Source") {
            continue;
        }

        if let Some(caps) = link_re.captures(line) {
            let label = caps[1].to_string();
            let path = caps[2].to_string();

            // Build node ID from filename
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

    // Parse individual wiki files for cross-references to build edges
    let mut edges = Vec::new();
    let node_ids: HashSet<&str> = nodes.iter().map(|n| n.id.as_str()).collect();

    for node in &nodes {
        let file_path = cfg.workspace.join(&node.path);
        if !file_path.exists() {
            continue;
        }
        let file_content = match fs::read_to_string(&file_path) {
            Ok(c) => c,
            Err(_) => continue,
        };

        // Look for cross-references: links to other wiki files
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

    Ok(GraphData { nodes, edges })
}
