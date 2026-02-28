/** Typed Tauri invoke wrappers. */
import { invoke } from "@tauri-apps/api/core";
import type {
  ConfigView,
  GraphData,
  ModelInfo,
  PartialConfig,
  PersistentSettings,
  SessionInfo,
} from "./types";

export async function solve(objective: string): Promise<void> {
  return invoke("solve", { objective });
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

export async function debugLog(msg: string): Promise<void> {
  return invoke("debug_log", { msg });
}
