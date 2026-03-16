/** TypeScript interfaces matching Rust event types. */

export interface TokenUsage {
  input_tokens: number;
  output_tokens: number;
}

export interface TraceEvent {
  message: string;
}

export type LoopPhase = "investigate" | "build" | "iterate" | "finalize";

export interface LoopMetrics {
  steps: number;
  model_turns: number;
  tool_calls: number;
  investigate_steps: number;
  build_steps: number;
  iterate_steps: number;
  finalize_steps: number;
  recon_streak: number;
  max_recon_streak: number;
  guardrail_warnings: number;
  final_rejections: number;
  extensions_granted: number;
  extension_eligible_checks: number;
  extension_denials_no_progress: number;
  extension_denials_cap: number;
  termination_reason: string;
}

export interface StepEvent {
  depth: number;
  step: number;
  tool_name: string | null;
  tokens: TokenUsage;
  elapsed_ms: number;
  is_final: boolean;
  loop_phase?: LoopPhase;
  loop_metrics?: LoopMetrics;
}

export type DeltaKind = "text" | "thinking" | "tool_call_start" | "tool_call_args";

export interface DeltaEvent {
  kind: DeltaKind;
  text: string;
}

export interface CompletionMeta {
  kind: string;
  reason: string;
  steps_used: number;
  max_steps: number;
  extensions_granted: number;
  extension_block_steps: number;
  extension_max_blocks: number;
}

export interface CompleteEvent {
  result: string;
  loop_metrics?: LoopMetrics;
  completion?: CompletionMeta;
}

export interface LoopHealthEvent {
  depth: number;
  step: number;
  phase: LoopPhase;
  metrics: LoopMetrics;
  is_final: boolean;
}

export interface ErrorEvent {
  message: string;
}

export interface CuratorUpdateEvent {
  summary: string;
  files_changed: number;
}

export type NodeType = "source" | "section" | "fact";

export interface GraphNode {
  id: string;
  label: string;
  category: string;
  path: string;
  node_type?: NodeType;
  parent_id?: string;
  content?: string;
}

export interface GraphEdge {
  source: string;
  target: string;
  label: string | null;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface ConfigView {
  provider: string;
  model: string;
  reasoning_effort: string | null;
  zai_plan: string;
  web_search_provider: string;
  workspace: string;
  session_id: string | null;
  recursive: boolean;
  max_depth: number;
  max_steps_per_call: number;
  demo: boolean;
}

export interface PartialConfig {
  provider?: string;
  model?: string;
  reasoning_effort?: string;
  zai_plan?: string;
  web_search_provider?: string;
}

export interface ModelInfo {
  id: string;
  name: string | null;
  provider: string;
}

export interface SessionInfo {
  id: string;
  created_at: string;
  turn_count: number;
  last_objective: string | null;
}

export interface PersistentSettings {
  default_model?: string | null;
  default_reasoning_effort?: string | null;
  default_model_openai?: string | null;
  default_model_anthropic?: string | null;
  default_model_openrouter?: string | null;
  default_model_cerebras?: string | null;
  default_model_zai?: string | null;
  default_model_ollama?: string | null;
  zai_plan?: string | null;
  web_search_provider?: string | null;
}

export interface SlashResult {
  output: string;
  success: boolean;
}

export type InitGateState = "ready" | "requires_action" | "blocked";
export type MigrationSourceKind = "openplanter_workspace" | "manual_research" | "unknown";
export type MigrationProgressStage =
  | "inspect"
  | "copy"
  | "merge_sessions"
  | "merge_settings"
  | "merge_credentials"
  | "synthesize"
  | "rewrite"
  | "done";

export interface StandardInitReportView {
  workspace: string;
  created_paths: string[];
  copied_paths: string[];
  skipped_existing: number;
  errors: string[];
  onboarding_required: boolean;
}

export interface InitStatusView {
  runtime_workspace: string;
  gate_state: InitGateState;
  onboarding_completed: boolean;
  has_openplanter_root: boolean;
  has_runtime_wiki: boolean;
  has_runtime_index: boolean;
  init_state_path: string;
  last_migration_target: string | null;
  warnings: string[];
}

export interface MigrationSourceInspection {
  path: string;
  kind: MigrationSourceKind;
  has_sessions: boolean;
  has_settings: boolean;
  has_credentials: boolean;
  has_runtime_wiki: boolean;
  has_baseline_wiki: boolean;
  markdown_files: number;
  warnings: string[];
}

export interface MigrationSourceInput {
  path: string;
}

export interface MigrationInitRequest {
  target_workspace: string;
  sources: MigrationSourceInput[];
}

export interface MigrationProgressEvent {
  stage: MigrationProgressStage;
  message: string;
  current: number;
  total: number;
}

export interface MigrationInitResultView {
  target_workspace: string;
  sources: string[];
  sessions_copied: number;
  sessions_renamed: number;
  settings_merged_fields: string[];
  credentials_merged_fields: string[];
  wiki_files_synthesized: number;
  raw_preservation_root: string;
  rewrite_summary: string;
  restart_required: boolean;
  restart_message: string;
  warnings: string[];
}

export interface StepToolCallEntry {
  name: string;
  key_arg: string;
  elapsed: number;
}

export interface ReplayEntry {
  seq: number;
  timestamp: string;
  role: string;
  content: string;
  tool_name?: string;
  is_rendered?: boolean;
  step_number?: number;
  step_tokens_in?: number;
  step_tokens_out?: number;
  step_elapsed?: number;
  step_model_preview?: string;
  step_tool_calls?: StepToolCallEntry[];
}

export type AgentEvent =
  | { type: "trace"; message: string }
  | {
      type: "step";
      depth: number;
      step: number;
      tool_name: string | null;
      tokens: TokenUsage;
      elapsed_ms: number;
      is_final: boolean;
      loop_phase?: LoopPhase;
      loop_metrics?: LoopMetrics;
    }
  | { type: "delta"; kind: DeltaKind; text: string }
  | { type: "complete"; result: string; loop_metrics?: LoopMetrics; completion?: CompletionMeta }
  | { type: "error"; message: string }
  | { type: "wiki_updated"; nodes: GraphNode[]; edges: GraphEdge[] }
  | { type: "loop_health"; depth: number; step: number; phase: LoopPhase; metrics: LoopMetrics; is_final: boolean };
