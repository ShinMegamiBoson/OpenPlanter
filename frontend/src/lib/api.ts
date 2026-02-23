/**
 * REST API client for the Redthread backend.
 * Base URL comes from NEXT_PUBLIC_API_URL (defaults to http://localhost:8000).
 */

import type {
  Investigation,
  EvidenceChain,
  GraphData,
  TimelineEvent,
  Message,
} from "./types";

const BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const API_PREFIX = `${BASE_URL}/api/v1`;

/** Shared fetch wrapper that throws on non-OK responses. */
async function apiFetch<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const url = `${API_PREFIX}${path}`;
  const res = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...(options?.headers as Record<string, string> | undefined),
    },
    ...options,
  });

  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(
      `API error ${res.status}: ${res.statusText}${body ? ` - ${body}` : ""}`,
    );
  }

  return res.json() as Promise<T>;
}

// -------------------------------------------------------
// Investigations
// -------------------------------------------------------

/** Create a new investigation session. */
export async function createInvestigation(
  title: string,
): Promise<Investigation> {
  return apiFetch<Investigation>("/investigations", {
    method: "POST",
    body: JSON.stringify({ title }),
  });
}

/** List all investigations, newest first. */
export async function listInvestigations(): Promise<Investigation[]> {
  return apiFetch<Investigation[]>("/investigations");
}

/** Get a single investigation by ID. */
export async function getInvestigation(
  id: string,
): Promise<Investigation> {
  return apiFetch<Investigation>(`/investigations/${id}`);
}

// -------------------------------------------------------
// Evidence
// -------------------------------------------------------

/** Get evidence chains for an investigation, with optional filters. */
export async function getEvidence(
  investigationId: string,
  filters?: { entity_id?: string; confidence?: string },
): Promise<EvidenceChain[]> {
  const params = new URLSearchParams();
  if (filters?.entity_id) params.set("entity_id", filters.entity_id);
  if (filters?.confidence) params.set("confidence", filters.confidence);
  const qs = params.toString();
  return apiFetch<EvidenceChain[]>(
    `/investigations/${investigationId}/evidence${qs ? `?${qs}` : ""}`,
  );
}

// -------------------------------------------------------
// Graph
// -------------------------------------------------------

/** Get the entity graph data formatted for Cytoscape.js. */
export async function getGraph(
  investigationId: string,
): Promise<GraphData> {
  return apiFetch<GraphData>(
    `/investigations/${investigationId}/graph`,
  );
}

// -------------------------------------------------------
// Timeline
// -------------------------------------------------------

/** Get timeline events for an investigation. */
export async function getTimeline(
  investigationId: string,
): Promise<{ events: TimelineEvent[] }> {
  return apiFetch<{ events: TimelineEvent[] }>(
    `/investigations/${investigationId}/timeline`,
  );
}

// -------------------------------------------------------
// Messages
// -------------------------------------------------------

/** Get chat history for an investigation. */
export async function getMessages(
  investigationId: string,
): Promise<Message[]> {
  return apiFetch<Message[]>(
    `/investigations/${investigationId}/messages`,
  );
}

// -------------------------------------------------------
// File Upload
// -------------------------------------------------------

export interface UploadResult {
  filename: string;
  size: number;
  path: string;
}

/** Upload a file to an investigation (multipart form data). */
export async function uploadFile(
  investigationId: string,
  file: File,
): Promise<UploadResult> {
  const url = `${API_PREFIX}/investigations/${investigationId}/upload`;

  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch(url, {
    method: "POST",
    body: formData,
    // Do NOT set Content-Type header -- browser sets it with boundary for multipart
  });

  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(
      `Upload failed ${res.status}: ${res.statusText}${body ? ` - ${body}` : ""}`,
    );
  }

  return res.json() as Promise<UploadResult>;
}

/** Get the WebSocket URL for a given investigation. */
export function getWebSocketUrl(investigationId: string): string {
  // Derive WS URL from BASE_URL: http -> ws, https -> wss
  const wsBase = BASE_URL.replace(/^http/, "ws");
  return `${wsBase}/ws/chat/${investigationId}`;
}
