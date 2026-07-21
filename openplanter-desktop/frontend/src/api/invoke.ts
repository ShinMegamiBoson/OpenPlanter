/** Typed Tauri invoke wrappers. */
import { invoke } from "@tauri-apps/api/core";
import type {
  ConfigView,
  CrowdTaskPreview,
  GraphData,
  ModelInfo,
  PartialConfig,
  PersistentSettings,
  ReplayEntry,
  SessionInfo,
  SlashResult,
} from "./types";

export async function solve(objective: string, sessionId: string): Promise<void> {
  return invoke("solve", { objective, sessionId });
}

export async function getSessionHistory(sessionId: string): Promise<ReplayEntry[]> {
  return invoke("get_session_history", { sessionId });
}

export async function cancel(): Promise<void> {
  return invoke("cancel");
}

export async function getConfig(): Promise<ConfigView> {
  return invoke("get_config");
}

export async function updateConfig(partial: PartialConfig): Promise<ConfigView> {
  return invoke("update_config", { partial });
}

export async function listModels(provider: string): Promise<ModelInfo[]> {
  return invoke("list_models", { provider });
}

export async function saveSettings(settings: PersistentSettings): Promise<void> {
  return invoke("save_settings", { settings });
}

export async function getCredentialsStatus(): Promise<Record<string, boolean>> {
  return invoke("get_credentials_status");
}

export async function listSessions(limit?: number): Promise<SessionInfo[]> {
  return invoke("list_sessions", { limit: limit ?? null });
}

export async function openSession(
  id?: string,
  resume: boolean = false
): Promise<SessionInfo> {
  return invoke("open_session", { id: id ?? null, resume });
}

export async function deleteSession(id: string): Promise<void> {
  return invoke("delete_session", { id });
}

export async function getGraphData(): Promise<GraphData> {
  return invoke("get_graph_data");
}

export async function readWikiFile(path: string): Promise<string> {
  return invoke("read_wiki_file", { path });
}

export async function debugLog(msg: string): Promise<void> {
  return invoke("debug_log", { msg });
}

export async function crowdPublish(input: string): Promise<SlashResult> {
  return invoke("crowd_publish", { input });
}

export async function crowdList(status?: string, tags?: string[]): Promise<{ tasks: CrowdTaskPreview[] }> {
  return invoke("crowd_list", { status: status ?? null, tags: tags ?? null });
}

export async function crowdClaim(hash: string): Promise<SlashResult> {
  return invoke("crowd_claim", { hash });
}

export async function crowdCancel(hash: string): Promise<SlashResult> {
  return invoke("crowd_cancel", { hash });
}

export async function crowdResult(hash: string, content: string): Promise<SlashResult> {
  return invoke("crowd_result", { hash, content });
}

export async function crowdTrust(npub: string): Promise<SlashResult> {
  return invoke("crowd_trust", { npub });
}
