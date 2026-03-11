import { vi, describe, it, expect, beforeEach, afterEach } from "vitest";
import { __setHandler, __clearHandlers } from "../__mocks__/tauri";

vi.mock("@tauri-apps/api/core", async () => {
  const mock = await import("../__mocks__/tauri");
  return { invoke: mock.invoke };
});

import { appState } from "../state/store";
import { handleZaiPlanCommand } from "./zaiPlan";

describe("handleZaiPlanCommand", () => {
  const originalState = appState.get();

  beforeEach(() => {
    appState.set({
      ...originalState,
      provider: "zai",
      model: "glm-5",
      zaiPlan: "paygo",
    });
  });

  afterEach(() => {
    __clearHandlers();
    appState.set(originalState);
  });

  it("no args shows current plan", async () => {
    const result = await handleZaiPlanCommand("");
    expect(result.lines).toContain("Z.AI plan: paygo");
  });

  it("switches plan for the current session", async () => {
    __setHandler("update_config", ({ partial }: { partial: Record<string, string> }) => {
      expect(partial.zai_plan).toBe("coding");
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
        web_search_provider: "firecrawl",
        demo: false,
      };
    });

    const result = await handleZaiPlanCommand("coding");
    expect(result.lines).toContain("Z.AI plan set to: coding");
    expect(result.lines).toContain("Endpoint family: https://api.z.ai/api/coding/paas/v4");
    expect(appState.get().zaiPlan).toBe("coding");
  });

  it("save persists the selected plan", async () => {
    __setHandler("update_config", () => ({
      provider: "zai",
      model: "glm-5",
      zai_plan: "paygo",
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
      expect(settings.zai_plan).toBe("paygo");
    });

    const result = await handleZaiPlanCommand("paygo --save");
    expect(result.lines).toContain("(Settings saved)");
  });
});
