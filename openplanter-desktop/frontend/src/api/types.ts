/** TypeScript interfaces matching Rust event types. */

export interface TokenUsage {
  input_tokens: number;
  output_tokens: number;
}

export interface TraceEvent {
  message: string;
}

export interface StepEvent {
  depth: number;
  step: number;
  tool_name: string | null;
  tokens: TokenUsage;
  elapsed_ms: number;
  is_final: boolean;
}

export type DeltaKind = "text" | "thinking" | "tool_call_start" | "tool_call_args";

export interface DeltaEvent {
  kind: DeltaKind;
  text: string;
}

export interface CompleteEvent {
  result: string;
}

export interface ErrorEvent {
  message: string;
}

export interface GraphNode {
  id: string;
  label: string;
  category: string;
  path: string;
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

export interface SlashResult {
  output: string;
  success: boolean;
}

export type AgentEvent =
  | { type: "trace"; message: string }
  | { type: "step"; depth: number; step: number; tool_name: string | null; tokens: TokenUsage; elapsed_ms: number; is_final: boolean }
  | { type: "delta"; kind: DeltaKind; text: string }
  | { type: "complete"; result: string }
  | { type: "error"; message: string }
  | { type: "wiki_updated"; nodes: GraphNode[]; edges: GraphEdge[] };
