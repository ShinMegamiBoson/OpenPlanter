import { vi, describe, it, expect, beforeEach, afterEach } from "vitest";
import { __setHandler, __clearHandlers } from "../__mocks__/tauri";

vi.mock("@tauri-apps/api/core", async () => {
  const mock = await import("../__mocks__/tauri");
  return { invoke: mock.invoke };
});

import { dispatchSlashCommand } from "./slash";
import { appState } from "../state/store";

describe("dispatchSlashCommand", () => {
  const originalState = appState.get();

  beforeEach(() => {
    appState.set({
      ...originalState,
      provider: "anthropic",
      model: "claude-opus-4-6",
      zaiPlan: "paygo",
      webSearchProvider: "exa",
      sessionId: "20260101-120000-deadbeef",
      reasoningEffort: "medium",
      initGateState: "ready",
    });
  });

  afterEach(() => {
    __clearHandlers();
    appState.set(originalState);
  });

  it("non-slash returns null", async () => {
    const result = await dispatchSlashCommand("hello");
    expect(result).toBeNull();
  });

  it("help returns commands", async () => {
    const result = await dispatchSlashCommand("/help");
    expect(result).not.toBeNull();
    expect(result!.lines.some((l) => l.includes("Available commands"))).toBe(
      true
    );
  });

  it("clear returns clear action", async () => {
    const result = await dispatchSlashCommand("/clear");
    expect(result).not.toBeNull();
    expect(result!.action).toBe("clear");
  });

  it("quit returns quit action", async () => {
    const result = await dispatchSlashCommand("/quit");
    expect(result).not.toBeNull();
    expect(result!.action).toBe("quit");
  });

  it("exit returns quit action", async () => {
    const result = await dispatchSlashCommand("/exit");
    expect(result).not.toBeNull();
    expect(result!.action).toBe("quit");
  });

  it("status shows provider", async () => {
    const result = await dispatchSlashCommand("/status");
    expect(result).not.toBeNull();
    expect(result!.lines.some((l) => l.includes("Provider:"))).toBe(true);
  });

  it("status shows session", async () => {
    const result = await dispatchSlashCommand("/status");
    expect(result).not.toBeNull();
    expect(result!.lines.some((l) => l.includes("Session:"))).toBe(true);
  });

  it("status shows web search provider", async () => {
    const result = await dispatchSlashCommand("/status");
    expect(result).not.toBeNull();
    expect(result!.lines.some((l) => l.includes("Web search:"))).toBe(true);
  });

  it("status shows zai plan", async () => {
    const result = await dispatchSlashCommand("/status");
    expect(result).not.toBeNull();
    expect(result!.lines.some((l) => l.includes("Z.AI plan:"))).toBe(true);
  });

  it("unknown command", async () => {
    const result = await dispatchSlashCommand("/foobar");
    expect(result).not.toBeNull();
    expect(result!.lines.some((l) => l.includes("Unknown command"))).toBe(
      true
    );
  });

  it("case insensitive", async () => {
    const result = await dispatchSlashCommand("/HELP");
    expect(result).not.toBeNull();
    expect(result!.lines.some((l) => l.includes("Available commands"))).toBe(
      true
    );
  });

  it("leading whitespace", async () => {
    const result = await dispatchSlashCommand("  /help");
    expect(result).not.toBeNull();
    expect(result!.lines.some((l) => l.includes("Available commands"))).toBe(
      true
    );
  });

  it("model dispatches", async () => {
    // /model with no args should show current info
    const result = await dispatchSlashCommand("/model");
    expect(result).not.toBeNull();
    expect(result!.action).toBe("handled");
    expect(result!.lines.some((l) => l.includes("Provider:"))).toBe(true);
  });

  it("reasoning dispatches", async () => {
    // /reasoning with no args should show current level
    const result = await dispatchSlashCommand("/reasoning");
    expect(result).not.toBeNull();
    expect(result!.action).toBe("handled");
    expect(
      result!.lines.some((l) => l.includes("Reasoning effort:"))
    ).toBe(true);
  });

  it("web search dispatches", async () => {
    const result = await dispatchSlashCommand("/web-search");
    expect(result).not.toBeNull();
    expect(result!.action).toBe("handled");
    expect(result!.lines.some((l) => l.includes("Web search provider:"))).toBe(true);
  });

  it("zai plan dispatches", async () => {
    const result = await dispatchSlashCommand("/zai-plan");
    expect(result).not.toBeNull();
    expect(result!.action).toBe("handled");
    expect(result!.lines.some((l) => l.includes("Z.AI plan:"))).toBe(true);
  });

  it("new creates session", async () => {
    __setHandler(
      "open_session",
      ({ id, resume }: { id: string | null; resume: boolean }) => {
        return {
          id: "20260227-100000-abcd1234",
          created_at: "2026-02-27T10:00:00Z",
          turn_count: 0,
          last_objective: null,
        };
      }
    );

    // Mock window.dispatchEvent since we're in node environment
    const origWindow = globalThis.window;
    (globalThis as any).window = {
      dispatchEvent: () => {},
    };

    const result = await dispatchSlashCommand("/new");
    expect(result).not.toBeNull();
    expect(result!.action).toBe("handled");
    expect(result!.lines.some((l) => l.includes("New session:"))).toBe(true);

    (globalThis as any).window = origWindow;
  });

  it("/init status dispatches", async () => {
    __setHandler("get_init_status", () => ({
      runtime_workspace: "/tmp/ws",
      gate_state: "requires_action",
      onboarding_completed: false,
      has_openplanter_root: true,
      has_runtime_wiki: true,
      has_runtime_index: true,
      init_state_path: "/tmp/ws/.openplanter/init-state.json",
      last_migration_target: null,
      warnings: [],
    }));
    const result = await dispatchSlashCommand("/init status");
    expect(result).not.toBeNull();
    expect(result!.lines.some((l) => l.includes("Gate:"))).toBe(true);
  });

  it("/init standard dispatches", async () => {
    __setHandler("run_standard_init", () => ({
      workspace: "/tmp/ws",
      created_paths: [],
      copied_paths: [],
      skipped_existing: 0,
      errors: [],
      onboarding_required: false,
    }));
    __setHandler("get_init_status", () => ({
      runtime_workspace: "/tmp/ws",
      gate_state: "ready",
      onboarding_completed: true,
      has_openplanter_root: true,
      has_runtime_wiki: true,
      has_runtime_index: true,
      init_state_path: "/tmp/ws/.openplanter/init-state.json",
      last_migration_target: null,
      warnings: [],
    }));
    const result = await dispatchSlashCommand("/init standard");
    expect(result).not.toBeNull();
    expect(result!.lines.some((l) => l.includes("Standard init completed"))).toBe(true);
  });
});
