import { vi, describe, it, expect, beforeEach, afterEach } from "vitest";
import { __setHandler, __clearHandlers } from "../__mocks__/tauri";

vi.mock("@tauri-apps/api/core", async () => {
  const mock = await import("../__mocks__/tauri");
  return { invoke: mock.invoke };
});

import { inferProvider, MODEL_ALIASES, handleModelCommand } from "./model";
import { appState } from "../state/store";

describe("inferProvider", () => {
  it("claude returns anthropic", () => {
    expect(inferProvider("claude-opus-4-6")).toBe("anthropic");
    expect(inferProvider("anthropic-foundry/claude-opus-4-6")).toBe("anthropic");
  });

  it("gpt returns openai", () => {
    expect(inferProvider("gpt-5.2")).toBe("openai");
    expect(inferProvider("azure-foundry/gpt-5.3-codex")).toBe("openai");
  });

  it("o1 returns openai", () => {
    expect(inferProvider("o1")).toBe("openai");
  });

  it("slash returns openrouter", () => {
    expect(inferProvider("anthropic/claude-sonnet-4-5")).toBe("openrouter");
  });

  it("llama returns ollama", () => {
    expect(inferProvider("llama3.2")).toBe("ollama");
  });

  it("qwen-3 returns cerebras", () => {
    expect(inferProvider("qwen-3-235b-a22b-instruct-2507")).toBe("cerebras");
  });

  it("glm returns zai", () => {
    expect(inferProvider("glm-5")).toBe("zai");
    expect(inferProvider("zai-glm-4.6")).toBe("zai");
  });

  it("qwen without 3 returns ollama", () => {
    expect(inferProvider("qwen2")).toBe("ollama");
  });

  it("unknown returns null", () => {
    expect(inferProvider("foobar")).toBeNull();
  });
});

describe("MODEL_ALIASES", () => {
  it("aliases resolve correctly", () => {
    for (const [alias, model] of Object.entries(MODEL_ALIASES)) {
      expect(typeof model).toBe("string");
      expect(model.length).toBeGreaterThan(0);
    }
  });

  it("opus alias", () => {
    expect(MODEL_ALIASES["opus"]).toBe("anthropic-foundry/claude-opus-4-6");
  });

  it("gpt5 alias", () => {
    expect(MODEL_ALIASES["gpt5"]).toBe("azure-foundry/gpt-5.3-codex");
  });

  it("gpt-5.4 alias", () => {
    expect(MODEL_ALIASES["gpt-5.4"]).toBe("azure-foundry/gpt-5.4");
  });

  it("zai alias", () => {
    expect(MODEL_ALIASES["zai"]).toBe("glm-5");
  });
});

describe("handleModelCommand", () => {
  const originalState = appState.get();

  beforeEach(() => {
    appState.set({
      ...originalState,
      provider: "anthropic",
      model: "claude-opus-4-6",
      webSearchProvider: "exa",
    });
  });

  afterEach(() => {
    __clearHandlers();
    appState.set(originalState);
  });

  it("no args shows current model", async () => {
    const result = await handleModelCommand("");
    expect(result.action).toBe("handled");
    expect(result.lines.some((l) => l.includes("Provider:"))).toBe(true);
    expect(result.lines.some((l) => l.includes("Model:"))).toBe(true);
  });

  it("list calls backend", async () => {
    __setHandler("list_models", ({ provider }: { provider: string }) => {
      expect(provider).toBe("all");
      return [
        { id: "gpt-5.2", name: "GPT-5.2", provider: "openai" },
      ];
    });

    const result = await handleModelCommand("list all");
    expect(result.action).toBe("handled");
    expect(result.lines.some((l) => l.includes("gpt-5.2"))).toBe(true);
  });

  it("save persists provider-specific model default", async () => {
    __setHandler("update_config", ({ partial }: { partial: Record<string, string> }) => {
      expect(partial.model).toBe("glm-5");
      expect(partial.provider).toBe("zai");
      return {
        provider: "zai",
        model: "glm-5",
        zai_plan: "coding",
        workspace: ".",
        session_id: null,
        recursive: true,
        max_depth: 4,
        max_steps_per_call: 100,
        reasoning_effort: "high",
        web_search_provider: "exa",
        demo: false,
      };
    });
    __setHandler("save_settings", ({ settings }: { settings: Record<string, string> }) => {
      expect(settings.default_model).toBe("glm-5");
      expect(settings.default_model_zai).toBe("glm-5");
    });

    const result = await handleModelCommand("zai --save");
    expect(result.lines).toContain("(Settings saved)");
    expect(appState.get().provider).toBe("zai");
    expect(appState.get().model).toBe("glm-5");
    expect(appState.get().zaiPlan).toBe("coding");
  });
});
