/// Serializable event types for Tauri IPC.
///
/// These events are emitted by the engine and consumed by the frontend.
use serde::{Deserialize, Serialize};

/// A trace message from the engine.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TraceEvent {
    pub message: String,
}

/// An engine step completion event.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StepEvent {
    pub depth: u32,
    pub step: u32,
    pub tool_name: Option<String>,
    pub tokens: TokenUsage,
    pub elapsed_ms: u64,
    pub is_final: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub loop_phase: Option<LoopPhase>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub loop_metrics: Option<LoopMetrics>,
}

/// High-level phase classification for the current loop step.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum LoopPhase {
    Investigate,
    Build,
    Iterate,
    Finalize,
}

/// Cumulative loop telemetry for health and governance UX.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct LoopMetrics {
    pub steps: u32,
    pub model_turns: u32,
    pub tool_calls: u32,
    pub investigate_steps: u32,
    pub build_steps: u32,
    pub iterate_steps: u32,
    pub finalize_steps: u32,
    pub recon_streak: u32,
    pub max_recon_streak: u32,
    pub guardrail_warnings: u32,
    pub final_rejections: u32,
    pub extensions_granted: u32,
    pub extension_eligible_checks: u32,
    pub extension_denials_no_progress: u32,
    pub extension_denials_cap: u32,
    pub termination_reason: String,
}

/// Token usage counters.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct TokenUsage {
    pub input_tokens: u64,
    pub output_tokens: u64,
}

/// Streaming delta — partial text from the model.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DeltaEvent {
    pub kind: DeltaKind,
    pub text: String,
}

/// The kind of streaming delta.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DeltaKind {
    Text,
    Thinking,
    ToolCallStart,
    ToolCallArgs,
}

/// Agent solve completed successfully.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum CompletionKind {
    Final,
    Partial,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum CompletionReason {
    FinalAnswer,
    BudgetNoProgress,
    BudgetCap,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
#[serde(default)]
pub struct CompletionMeta {
    pub kind: String,
    pub reason: String,
    pub steps_used: u32,
    pub max_steps: u32,
    pub extensions_granted: u32,
    pub extension_block_steps: u32,
    pub extension_max_blocks: u32,
}

/// Agent solve completed successfully.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CompleteEvent {
    pub result: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub loop_metrics: Option<LoopMetrics>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub completion: Option<CompletionMeta>,
}

/// Periodic loop health telemetry event.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LoopHealthEvent {
    pub depth: u32,
    pub step: u32,
    pub phase: LoopPhase,
    pub metrics: LoopMetrics,
    pub is_final: bool,
}

/// Agent encountered an error.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ErrorEvent {
    pub message: String,
}

/// Checkpointed wiki curator completed an update.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CuratorUpdateEvent {
    pub summary: String,
    pub files_changed: u32,
}

/// Wiki knowledge graph data for the frontend.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GraphData {
    pub nodes: Vec<GraphNode>,
    pub edges: Vec<GraphEdge>,
}

/// The tier of a node in the wiki knowledge graph hierarchy.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum NodeType {
    Source,
    Section,
    Fact,
}

/// A node in the wiki knowledge graph.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GraphNode {
    pub id: String,
    pub label: String,
    pub category: String,
    pub path: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub node_type: Option<NodeType>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub parent_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub content: Option<String>,
}

/// An edge in the wiki knowledge graph.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GraphEdge {
    pub source: String,
    pub target: String,
    pub label: Option<String>,
}

/// All events the engine can emit to the frontend.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum AgentEvent {
    Trace(TraceEvent),
    Step(StepEvent),
    Delta(DeltaEvent),
    Complete(CompleteEvent),
    Error(ErrorEvent),
    WikiUpdated(GraphData),
    LoopHealth(LoopHealthEvent),
}

/// Configuration view sent to the frontend.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ConfigView {
    pub provider: String,
    pub model: String,
    pub reasoning_effort: Option<String>,
    pub zai_plan: String,
    pub web_search_provider: String,
    pub workspace: String,
    pub session_id: Option<String>,
    pub recursive: bool,
    pub max_depth: i64,
    pub max_steps_per_call: i64,
    pub demo: bool,
}

/// Partial configuration update from the frontend.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct PartialConfig {
    pub provider: Option<String>,
    pub model: Option<String>,
    pub reasoning_effort: Option<String>,
    pub zai_plan: Option<String>,
    pub web_search_provider: Option<String>,
}

/// Model information for the model list.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ModelInfo {
    pub id: String,
    pub name: Option<String>,
    pub provider: String,
}

/// Session information for the session list.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SessionInfo {
    pub id: String,
    pub created_at: String,
    pub turn_count: u32,
    pub last_objective: Option<String>,
}

/// Slash command result.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SlashResult {
    pub output: String,
    pub success: bool,
}

/// Frontend gate state for workspace initialization.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum InitGateState {
    Ready,
    RequiresAction,
    Blocked,
}

/// Report returned by standard workspace initialization.
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct StandardInitReportView {
    pub workspace: String,
    pub created_paths: Vec<String>,
    pub copied_paths: Vec<String>,
    pub skipped_existing: u64,
    pub errors: Vec<String>,
    pub onboarding_required: bool,
}

/// Current initialization state for the runtime workspace.
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct InitStatusView {
    pub runtime_workspace: String,
    pub gate_state: String,
    pub onboarding_completed: bool,
    pub has_openplanter_root: bool,
    pub has_runtime_wiki: bool,
    pub has_runtime_index: bool,
    pub init_state_path: String,
    pub last_migration_target: Option<String>,
    pub warnings: Vec<String>,
}

/// Migration source classification.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum MigrationSourceKind {
    OpenPlanterWorkspace,
    ManualResearch,
    Unknown,
}

/// Inspection data for a migration source.
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct MigrationSourceInspection {
    pub path: String,
    pub kind: String,
    pub has_sessions: bool,
    pub has_settings: bool,
    pub has_credentials: bool,
    pub has_runtime_wiki: bool,
    pub has_baseline_wiki: bool,
    pub markdown_files: u64,
    pub warnings: Vec<String>,
}

/// A user-selected migration source.
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct MigrationSourceInput {
    pub path: String,
}

/// Request payload for migration init.
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct MigrationInitRequest {
    pub target_workspace: String,
    pub sources: Vec<MigrationSourceInput>,
}

/// Progress stages emitted during migration.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum MigrationProgressStage {
    Inspect,
    Copy,
    MergeSessions,
    MergeSettings,
    MergeCredentials,
    Synthesize,
    Rewrite,
    Done,
}

/// Progress event emitted while migration runs.
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct MigrationProgressEvent {
    pub stage: String,
    pub message: String,
    pub current: u32,
    pub total: u32,
}

/// Result payload returned after migration init completes.
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct MigrationInitResultView {
    pub target_workspace: String,
    pub sources: Vec<String>,
    pub sessions_copied: u64,
    pub sessions_renamed: u64,
    pub settings_merged_fields: Vec<String>,
    pub credentials_merged_fields: Vec<String>,
    pub wiki_files_synthesized: u64,
    pub raw_preservation_root: String,
    pub rewrite_summary: String,
    pub restart_required: bool,
    pub restart_message: String,
    pub warnings: Vec<String>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_agent_event_serialization() {
        let event = AgentEvent::Trace(TraceEvent {
            message: "Starting solve".into(),
        });
        let json = serde_json::to_string(&event).unwrap();
        assert!(json.contains("\"type\":\"trace\""));
        assert!(json.contains("Starting solve"));
    }

    #[test]
    fn test_delta_kind_serialization() {
        let delta = DeltaEvent {
            kind: DeltaKind::ToolCallStart,
            text: "read_file".into(),
        };
        let json = serde_json::to_string(&delta).unwrap();
        assert!(json.contains("\"kind\":\"tool_call_start\""));
    }

    #[test]
    fn test_graph_data_serialization() {
        let graph = GraphData {
            nodes: vec![GraphNode {
                id: "fec".into(),
                label: "FEC Federal".into(),
                category: "campaign-finance".into(),
                path: "wiki/campaign-finance/fec-federal.md".into(),
                node_type: None,
                parent_id: None,
                content: None,
            }],
            edges: vec![GraphEdge {
                source: "fec".into(),
                target: "sec-edgar".into(),
                label: Some("cross-ref".into()),
            }],
        };
        let json = serde_json::to_string(&graph).unwrap();
        assert!(json.contains("fec"));
        assert!(json.contains("sec-edgar"));
        // Optional fields should be omitted when None
        assert!(!json.contains("node_type"));
        assert!(!json.contains("parent_id"));
        assert!(!json.contains("content"));
    }

    #[test]
    fn test_graph_node_with_type_serialization() {
        let node = GraphNode {
            id: "fec::summary".into(),
            label: "Summary".into(),
            category: "campaign-finance".into(),
            path: "wiki/campaign-finance/fec-federal.md".into(),
            node_type: Some(NodeType::Section),
            parent_id: Some("fec".into()),
            content: Some("The FEC maintains data...".into()),
        };
        let json = serde_json::to_string(&node).unwrap();
        assert!(json.contains("\"node_type\":\"section\""));
        assert!(json.contains("\"parent_id\":\"fec\""));
        assert!(json.contains("\"content\":"));
    }

    #[test]
    fn test_node_type_serialization() {
        let source = NodeType::Source;
        let section = NodeType::Section;
        let fact = NodeType::Fact;
        assert_eq!(serde_json::to_string(&source).unwrap(), "\"source\"");
        assert_eq!(serde_json::to_string(&section).unwrap(), "\"section\"");
        assert_eq!(serde_json::to_string(&fact).unwrap(), "\"fact\"");
    }

    #[test]
    fn test_step_event_serialization() {
        let step = StepEvent {
            depth: 0,
            step: 3,
            tool_name: Some("read_file".into()),
            tokens: TokenUsage {
                input_tokens: 1234,
                output_tokens: 567,
            },
            elapsed_ms: 2345,
            is_final: false,
            loop_phase: None,
            loop_metrics: None,
        };
        let json = serde_json::to_string(&step).unwrap();
        let parsed: serde_json::Value = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed["depth"], 0);
        assert_eq!(parsed["step"], 3);
        assert_eq!(parsed["tool_name"], "read_file");
        assert_eq!(parsed["tokens"]["input_tokens"], 1234);
    }

    #[test]
    fn test_loop_metrics_deserialize_backfills_new_fields() {
        let parsed: LoopMetrics = serde_json::from_str(
            r#"{
                "steps": 2,
                "model_turns": 2,
                "tool_calls": 1,
                "investigate_steps": 1,
                "build_steps": 0,
                "iterate_steps": 0,
                "finalize_steps": 1,
                "recon_streak": 0,
                "max_recon_streak": 1,
                "final_rejections": 1
            }"#,
        )
        .unwrap();

        assert_eq!(
            parsed,
            LoopMetrics {
                steps: 2,
                model_turns: 2,
                tool_calls: 1,
                investigate_steps: 1,
                build_steps: 0,
                iterate_steps: 0,
                finalize_steps: 1,
                recon_streak: 0,
                max_recon_streak: 1,
                guardrail_warnings: 0,
                final_rejections: 1,
                extensions_granted: 0,
                extension_eligible_checks: 0,
                extension_denials_no_progress: 0,
                extension_denials_cap: 0,
                termination_reason: String::new(),
            }
        );
    }

    #[test]
    fn test_init_gate_state_serialization() {
        assert_eq!(
            serde_json::to_string(&InitGateState::RequiresAction).unwrap(),
            "\"requires_action\""
        );
    }

    #[test]
    fn test_migration_progress_stage_serialization() {
        assert_eq!(
            serde_json::to_string(&MigrationProgressStage::MergeSessions).unwrap(),
            "\"merge_sessions\""
        );
    }
}
