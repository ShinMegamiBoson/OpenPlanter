/**
 * Shared TypeScript interfaces for the Redthread frontend.
 * These mirror the backend Pydantic models.
 */

/** Chat message in an investigation conversation. */
export interface Message {
  id: string;
  investigation_id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string; // ISO 8601
}

/** Entity node in the investigation graph. */
export interface Entity {
  id: string;
  investigation_id: string;
  entity_type: "person" | "organization" | "address" | "account" | "unknown";
  name: string;
  properties: Record<string, unknown>;
}

/** Typed relationship between two entities. */
export interface Relationship {
  id: string;
  source_id: string;
  target_id: string;
  relationship_type:
    | "TRANSACTED_WITH"
    | "AFFILIATED_WITH"
    | "LOCATED_AT"
    | "RELATES_TO";
  properties: Record<string, unknown>;
  created_at: string; // ISO 8601
}

/** Confidence level for evidence chain entries. */
export type Confidence = "confirmed" | "probable" | "possible" | "unresolved";

/** A single evidence chain entry linking a claim to source data. */
export interface EvidenceChain {
  id: string;
  investigation_id: string;
  entity_id?: string;
  claim: string;
  supporting_evidence: string;
  source_record_id?: string;
  source_dataset_id?: string;
  confidence: Confidence;
  created_at: string; // ISO 8601
  metadata?: Record<string, unknown>;
}

/** A dated event for the transaction timeline visualization. */
export interface TimelineEvent {
  id: string;
  investigation_id: string;
  entity_id?: string;
  entity_name?: string;
  event_date: string; // ISO 8601
  amount?: number;
  description?: string;
  source_record_id?: string;
  source_dataset_id?: string;
  created_at: string; // ISO 8601
}

/** Top-level investigation session. */
export interface Investigation {
  id: string;
  title: string;
  created_at: string; // ISO 8601
  updated_at: string; // ISO 8601
  status: "active" | "archived";
  metadata?: Record<string, unknown>;
}

/** Cytoscape.js-compatible graph data format. */
export interface GraphData {
  nodes: Array<{
    data: {
      id: string;
      label: string;
      type: string;
    };
  }>;
  edges: Array<{
    data: {
      id?: string;
      source: string;
      target: string;
      type: string;
    };
  }>;
}

/** WebSocket message frame types (server -> client). */
export type ServerFrame =
  | { type: "text_delta"; content: string }
  | { type: "tool_call"; tool: string; input: Record<string, unknown> }
  | { type: "tool_result"; tool: string; output: string }
  | { type: "message_complete"; content: string }
  | { type: "graph_update"; data: GraphData }
  | { type: "evidence_update"; data: EvidenceChain }
  | { type: "error"; message: string };

/** WebSocket message frame types (client -> server). */
export type ClientFrame =
  | { type: "message"; content: string }
  | { type: "sub_investigate"; question: string };
