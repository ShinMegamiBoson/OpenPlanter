import { vi, describe, it, expect, afterEach } from "vitest";

// Track registered listeners
const listeners: Map<string, Function> = new Map();
const mockUnlisten = vi.fn();

vi.mock("@tauri-apps/api/event", () => ({
  listen: vi.fn((event: string, handler: Function) => {
    listeners.set(event, handler);
    return Promise.resolve(mockUnlisten);
  }),
}));

import {
  onAgentTrace,
  onAgentStep,
  onAgentDelta,
  onAgentComplete,
  onAgentCompleteEvent,
  onAgentError,
  onLoopHealth,
  onMigrationProgress,
  onWikiUpdated,
} from "./events";

describe("event listeners", () => {
  afterEach(() => {
    listeners.clear();
    mockUnlisten.mockClear();
  });

  it("onAgentTrace registers listener and extracts message", async () => {
    const callback = vi.fn();
    const unlisten = await onAgentTrace(callback);

    expect(listeners.has("agent:trace")).toBe(true);

    // Simulate Tauri event
    const handler = listeners.get("agent:trace")!;
    handler({ payload: { message: "trace info" } });
    expect(callback).toHaveBeenCalledWith("trace info");

    expect(unlisten).toBe(mockUnlisten);
  });

  it("onAgentStep registers listener and forwards payload", async () => {
    const callback = vi.fn();
    await onAgentStep(callback);

    const handler = listeners.get("agent:step")!;
    const payload = {
      type: "step",
      step: 1,
      depth: 0,
      tokens: { input_tokens: 100, output_tokens: 50 },
      elapsed_ms: 1200,
      is_final: false,
    };
    handler({ payload });
    expect(callback).toHaveBeenCalledWith(payload);
  });

  it("onAgentDelta registers listener and forwards payload", async () => {
    const callback = vi.fn();
    await onAgentDelta(callback);

    const handler = listeners.get("agent:delta")!;
    const payload = { type: "delta", kind: "text", text: "hello" };
    handler({ payload });
    expect(callback).toHaveBeenCalledWith(payload);
  });

  it("onAgentComplete registers listener and extracts result", async () => {
    const callback = vi.fn();
    await onAgentComplete(callback);

    const handler = listeners.get("agent:complete")!;
    handler({
      payload: {
        result: "final answer",
        loop_metrics: { final_rejections: 1 },
      },
    });
    expect(callback).toHaveBeenCalledWith("final answer");
  });

  it("onAgentCompleteEvent registers listener and forwards full payload", async () => {
    const callback = vi.fn();
    await onAgentCompleteEvent(callback);

    const handler = listeners.get("agent:complete")!;
    const payload = {
      result: "final answer",
      loop_metrics: {
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
      },
    };
    handler({ payload });
    expect(callback).toHaveBeenCalledWith(payload);
  });

  it("onAgentError registers listener and extracts message", async () => {
    const callback = vi.fn();
    await onAgentError(callback);

    const handler = listeners.get("agent:error")!;
    handler({ payload: { message: "something broke" } });
    expect(callback).toHaveBeenCalledWith("something broke");
  });

  it("onWikiUpdated registers listener and forwards graph data", async () => {
    const callback = vi.fn();
    await onWikiUpdated(callback);

    const handler = listeners.get("wiki:updated")!;
    const graphData = {
      nodes: [{ id: "n1", label: "Test", category: "corporate" }],
      edges: [],
    };
    handler({ payload: graphData });
    expect(callback).toHaveBeenCalledWith(graphData);
  });

  it("onMigrationProgress registers listener and forwards progress payload", async () => {
    const callback = vi.fn();
    await onMigrationProgress(callback);

    const handler = listeners.get("init:migration-progress")!;
    const payload = {
      stage: "copy",
      message: "Copying raw content",
      current: 1,
      total: 3,
    };
    handler({ payload });
    expect(callback).toHaveBeenCalledWith(payload);
  });

  it("onLoopHealth registers listener and forwards payload", async () => {
    const callback = vi.fn();
    await onLoopHealth(callback);

    const handler = listeners.get("agent:loop-health")!;
    const payload = {
      depth: 0,
      step: 3,
      phase: "investigate",
      metrics: {
        steps: 3,
        model_turns: 3,
        tool_calls: 2,
        investigate_steps: 2,
        build_steps: 0,
        iterate_steps: 0,
        finalize_steps: 0,
        recon_streak: 2,
        max_recon_streak: 2,
        guardrail_warnings: 1,
        final_rejections: 1,
      },
      is_final: false,
    };
    handler({ payload });
    expect(callback).toHaveBeenCalledWith(payload);
  });

  it("all listeners return unlisten function", async () => {
    const noop = vi.fn();
    const unlistens = await Promise.all([
      onAgentTrace(noop),
      onAgentStep(noop),
      onAgentDelta(noop),
      onAgentComplete(noop),
      onAgentCompleteEvent(noop),
      onAgentError(noop),
      onLoopHealth(noop),
      onMigrationProgress(noop),
      onWikiUpdated(noop),
    ]);
    for (const u of unlistens) {
      expect(u).toBe(mockUnlisten);
    }
  });
});
