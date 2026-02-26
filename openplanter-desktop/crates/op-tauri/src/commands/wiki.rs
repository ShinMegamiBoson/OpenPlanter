use tauri::State;
use crate::state::AppState;
use op_core::events::GraphData;

/// Get the wiki knowledge graph data.
#[tauri::command]
pub async fn get_graph_data(
    _state: State<'_, AppState>,
) -> Result<GraphData, String> {
    // Phase 5: read wiki and build graph
    Ok(GraphData {
        nodes: vec![],
        edges: vec![],
    })
}
