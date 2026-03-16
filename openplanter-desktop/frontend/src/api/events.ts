/** Tauri event subscriptions. */
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import type {
  CompleteEvent,
  CuratorUpdateEvent,
  DeltaEvent,
  GraphData,
  LoopHealthEvent,
  StepEvent,
} from "./types";

export function onAgentTrace(
  callback: (message: string) => void
): Promise<UnlistenFn> {
  return listen<{ message: string }>("agent:trace", (e) =>
    callback(e.payload.message)
  );
}

export function onAgentStep(
  callback: (event: StepEvent) => void
): Promise<UnlistenFn> {
  return listen<StepEvent>("agent:step", (e) => callback(e.payload));
}

export function onAgentDelta(
  callback: (event: DeltaEvent) => void
): Promise<UnlistenFn> {
  return listen<DeltaEvent>("agent:delta", (e) => callback(e.payload));
}

export function onAgentCompleteEvent(
  callback: (event: CompleteEvent) => void
): Promise<UnlistenFn> {
  return listen<CompleteEvent>("agent:complete", (e) => callback(e.payload));
}

export function onAgentComplete(
  callback: (result: string) => void
): Promise<UnlistenFn> {
  return onAgentCompleteEvent((event) => callback(event.result));
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
export function onLoopHealth(
  callback: (event: LoopHealthEvent) => void
): Promise<UnlistenFn> {
  return listen<LoopHealthEvent>("agent:loop-health", (e) => callback(e.payload));
}
