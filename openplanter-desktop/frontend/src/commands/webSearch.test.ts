import { vi, describe, it, expect, beforeEach, afterEach } from "vitest";
import { __setHandler, __clearHandlers } from "../__mocks__/tauri";

vi.mock("@tauri-apps/api/core", async () => {
  const mock = await import("../__mocks__/tauri");
  return { invoke: mock.invoke };
});

import { appState } from "../state/store";
import { handleWebSearchCommand } from "./webSearch";

describe("handleWebSearchCommand", () => {
  const originalState = appState.get();

  beforeEach(() => {
    appState.set({
      ...originalState,
      webSearchProvider: "exa",
    });
  });

  afterEach(() => {
    __clearHandlers();
    appState.set(originalState);
  });

  it("no args shows current provider", async () => {
    const result = await handleWebSearchCommand("");
    expect(result.lines).toContain("Web search provider: exa");
  });

  it("switches provider for the current session", async () => {
    __setHandler("update_config", ({ partial }: { partial: Record<string, string> }) => {
      expect(partial.web_search_provider).toBe("firecrawl");
      return {
        provider: "anthropic",
        model: "claude-opus-4-6",
        zai_plan: "paygo",
        workspace: ".",
        session_id: null,
        recursive: true,
        max_depth: 4,
        max_steps_per_call: 100,
        reasoning_effort: "high",
        web_search_provider: "firecrawl",
        demo: false,
      };
    });

    const result = await handleWebSearchCommand("firecrawl");
    expect(result.lines).toContain("Web search provider set to: firecrawl");
    expect(appState.get().webSearchProvider).toBe("firecrawl");
  });

  it("save persists the selected provider", async () => {
    __setHandler("update_config", () => ({
      provider: "anthropic",
      model: "claude-opus-4-6",
      zai_plan: "coding",
      workspace: ".",
      session_id: null,
      recursive: true,
      max_depth: 4,
      max_steps_per_call: 100,
      reasoning_effort: "high",
      web_search_provider: "firecrawl",
      demo: false,
    }));
    __setHandler("save_settings", ({ settings }: { settings: Record<string, string> }) => {
      expect(settings.web_search_provider).toBe("firecrawl");
    });

    const result = await handleWebSearchCommand("firecrawl --save");
    expect(result.lines).toContain("(Settings saved)");
  });
});
