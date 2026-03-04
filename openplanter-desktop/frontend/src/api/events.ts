/** Tauri event subscriptions. */
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import type { AgentEvent, CuratorUpdateEvent, GraphData } from "./types";

export function onAgentTrace(
  callback: (message: string) => void
): Promise<UnlistenFn> {
  return listen<{ message: string }>("agent:trace", (e) =>
    callback(e.payload.message)
  );
}

export function onAgentStep(
  callback: (event: AgentEvent & { type: "step" }) => void
): Promise<UnlistenFn> {
  return listen("agent:step", (e) => callback(e.payload as any));
}

export function onAgentDelta(
  callback: (event: AgentEvent & { type: "delta" }) => void
): Promise<UnlistenFn> {
  return listen("agent:delta", (e) => callback(e.payload as any));
}

export function onAgentComplete(
  callback: (result: string) => void
): Promise<UnlistenFn> {
  return listen<{ result: string }>("agent:complete", (e) =>
    callback(e.payload.result)
  );
}

export function onAgentError(
  callback: (message: string) => void
): Promise<UnlistenFn> {
  return listen<{ message: string }>("agent:error", (e) =>
    callback(e.payload.message)
  );
}

export function onWikiUpdated(
  callback: (data: GraphData) => void
): Promise<UnlistenFn> {
  return listen<GraphData>("wiki:updated", (e) => callback(e.payload));
}

export function onCuratorUpdate(
  callback: (event: CuratorUpdateEvent) => void
): Promise<UnlistenFn> {
  return listen<CuratorUpdateEvent>("agent:curator-update", (e) =>
    callback(e.payload)
  );
}
