import { vi, describe, it, expect, beforeEach, afterEach } from "vitest";
import { __setHandler, __clearHandlers } from "../__mocks__/tauri";

vi.mock("@tauri-apps/api/core", async () => {
  const mock = await import("../__mocks__/tauri");
  return { invoke: mock.invoke };
});

import { handleReasoningCommand } from "./reasoning";
import { appState } from "../state/store";

describe("handleReasoningCommand", () => {
  const originalState = appState.get();

  beforeEach(() => {
    appState.set({
      ...originalState,
      reasoningEffort: "medium",
    });
  });

  afterEach(() => {
    __clearHandlers();
    appState.set(originalState);
  });

  it("no args shows current", async () => {
    const result = await handleReasoningCommand("");
    expect(result.action).toBe("handled");
    expect(result.lines.some((l) => l.includes("Reasoning effort:"))).toBe(
      true
    );
  });

  it("valid level low", async () => {
    __setHandler("update_config", ({ partial }: any) => {
      expect(partial.reasoning_effort).toBe("low");
      return {
        provider: "anthropic",
        model: "claude-opus-4-6",
        zai_plan: "paygo",
        reasoning_effort: "low",
        workspace: ".",
        session_id: null,
        recursive: true,
        max_depth: 4,
        max_steps_per_call: 100,
        demo: false,
      };
    });

    const result = await handleReasoningCommand("low");
    expect(result.action).toBe("handled");
    expect(result.lines.some((l) => l.includes("low"))).toBe(true);
  });

  it("valid level high", async () => {
    __setHandler("update_config", ({ partial }: any) => ({
      provider: "anthropic",
      model: "claude-opus-4-6",
      zai_plan: "coding",
      reasoning_effort: "high",
      workspace: ".",
      session_id: null,
      recursive: true,
      max_depth: 4,
      max_steps_per_call: 100,
      demo: false,
    }));

    const result = await handleReasoningCommand("high");
    expect(result.action).toBe("handled");
    expect(result.lines.some((l) => l.includes("high"))).toBe(true);
  });

  it("off sends empty string", async () => {
    __setHandler("update_config", ({ partial }: any) => {
      expect(partial.reasoning_effort).toBe("");
      return {
        provider: "anthropic",
        model: "claude-opus-4-6",
        zai_plan: "paygo",
        reasoning_effort: null,
        workspace: ".",
        session_id: null,
        recursive: true,
        max_depth: 4,
        max_steps_per_call: 100,
        demo: false,
      };
    });

    const result = await handleReasoningCommand("off");
    expect(result.action).toBe("handled");
  });

  it("invalid level", async () => {
    const result = await handleReasoningCommand("extreme");
    expect(result.action).toBe("handled");
    expect(result.lines.some((l) => l.includes("Invalid"))).toBe(true);
  });

  it("case insensitive", async () => {
    __setHandler("update_config", ({ partial }: any) => {
      expect(partial.reasoning_effort).toBe("high");
      return {
        provider: "anthropic",
        model: "claude-opus-4-6",
        zai_plan: "coding",
        reasoning_effort: "high",
        workspace: ".",
        session_id: null,
        recursive: true,
        max_depth: 4,
        max_steps_per_call: 100,
        demo: false,
      };
    });

    const result = await handleReasoningCommand("HIGH");
    expect(result.action).toBe("handled");
    expect(result.lines.some((l) => l.includes("high"))).toBe(true);
  });

  it("save flag", async () => {
    __setHandler("update_config", ({ partial }: any) => ({
      provider: "anthropic",
      model: "claude-opus-4-6",
      zai_plan: "coding",
      reasoning_effort: "high",
      workspace: ".",
      session_id: null,
      recursive: true,
      max_depth: 4,
      max_steps_per_call: 100,
      demo: false,
    }));
    __setHandler("save_settings", ({ settings }: any) => {
      expect(settings.default_reasoning_effort).toBe("high");
    });

    const result = await handleReasoningCommand("high --save");
    expect(result.action).toBe("handled");
    expect(result.lines.some((l) => l.includes("(Settings saved)"))).toBe(
      true
    );
  });

  it("valid levels list in error message", async () => {
    const result = await handleReasoningCommand("extreme");
    expect(
      result.lines.some(
        (l) =>
          l.includes("low") &&
          l.includes("medium") &&
          l.includes("high") &&
          l.includes("off")
      )
    ).toBe(true);
  });
});
