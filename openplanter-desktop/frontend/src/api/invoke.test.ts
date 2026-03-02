import { vi, describe, it, expect, afterEach } from "vitest";
import { __setHandler, __clearHandlers } from "../__mocks__/tauri";

vi.mock("@tauri-apps/api/core", async () => {
  const mock = await import("../__mocks__/tauri");
  return { invoke: mock.invoke };
});

import {
  solve,
  cancel,
  getConfig,
  updateConfig,
  listModels,
  saveSettings,
  getCredentialsStatus,
  listSessions,
  openSession,
  deleteSession,
  getGraphData,
  debugLog,
} from "./invoke";

describe("invoke wrappers", () => {
  afterEach(() => {
    __clearHandlers();
  });

  it("solve calls invoke with objective and sessionId", async () => {
    __setHandler("solve", ({ objective, sessionId }: any) => {
      expect(objective).toBe("test goal");
      expect(sessionId).toBe("session-1");
    });
    await solve("test goal", "session-1");
  });

  it("cancel calls invoke with no args", async () => {
    let called = false;
    __setHandler("cancel", () => {
      called = true;
    });
    await cancel();
    expect(called).toBe(true);
  });

  it("getConfig returns config", async () => {
    __setHandler("get_config", () => ({
      provider: "anthropic",
      model: "claude-opus-4-6",
      workspace: ".",
      session_id: null,
      recursive: true,
      max_depth: 4,
      max_steps_per_call: 100,
      reasoning_effort: "high",
      demo: false,
    }));
    const config = await getConfig();
    expect(config.provider).toBe("anthropic");
    expect(config.model).toBe("claude-opus-4-6");
  });

  it("updateConfig sends partial and returns config", async () => {
    __setHandler("update_config", ({ partial }: any) => {
      expect(partial.model).toBe("gpt-5.2");
      return {
        provider: "openai",
        model: "gpt-5.2",
        workspace: ".",
        session_id: null,
        recursive: true,
        max_depth: 4,
        max_steps_per_call: 100,
        reasoning_effort: null,
        demo: false,
      };
    });
    const config = await updateConfig({ model: "gpt-5.2" });
    expect(config.model).toBe("gpt-5.2");
  });

  it("listModels sends provider filter", async () => {
    __setHandler("list_models", ({ provider }: any) => {
      expect(provider).toBe("openai");
      return [{ id: "gpt-5.2", name: "GPT-5.2", provider: "openai" }];
    });
    const models = await listModels("openai");
    expect(models).toHaveLength(1);
    expect(models[0].id).toBe("gpt-5.2");
  });

  it("saveSettings sends settings object", async () => {
    __setHandler("save_settings", ({ settings }: any) => {
      expect(settings.model).toBe("claude-opus-4-6");
    });
    await saveSettings({ model: "claude-opus-4-6" } as any);
  });

  it("getCredentialsStatus returns provider map", async () => {
    __setHandler("get_credentials_status", () => ({
      openai: true,
      anthropic: true,
      openrouter: false,
      cerebras: false,
      ollama: true,
      exa: false,
    }));
    const status = await getCredentialsStatus();
    expect(status.openai).toBe(true);
    expect(status.openrouter).toBe(false);
  });

  it("listSessions sends limit", async () => {
    __setHandler("list_sessions", ({ limit }: any) => {
      expect(limit).toBe(10);
      return [];
    });
    const sessions = await listSessions(10);
    expect(sessions).toEqual([]);
  });

  it("listSessions defaults limit to null", async () => {
    __setHandler("list_sessions", ({ limit }: any) => {
      expect(limit).toBeNull();
      return [];
    });
    await listSessions();
  });

  it("openSession with no args", async () => {
    __setHandler("open_session", ({ id, resume }: any) => {
      expect(id).toBeNull();
      expect(resume).toBe(false);
      return {
        id: "20260227-100000-abcd1234",
        created_at: "2026-02-27T10:00:00Z",
        turn_count: 0,
        last_objective: null,
      };
    });
    const session = await openSession();
    expect(session.id).toBe("20260227-100000-abcd1234");
  });

  it("openSession with id and resume", async () => {
    __setHandler("open_session", ({ id, resume }: any) => {
      expect(id).toBe("session-123");
      expect(resume).toBe(true);
      return {
        id: "session-123",
        created_at: "2026-02-27T10:00:00Z",
        turn_count: 5,
        last_objective: "prior task",
      };
    });
    const session = await openSession("session-123", true);
    expect(session.last_objective).toBe("prior task");
  });

  it("deleteSession sends id", async () => {
    __setHandler("delete_session", ({ id }: any) => {
      expect(id).toBe("session-to-delete");
    });
    await deleteSession("session-to-delete");
  });

  it("getGraphData returns graph structure", async () => {
    __setHandler("get_graph_data", () => ({
      nodes: [{ id: "n1", label: "Test", category: "corporate" }],
      edges: [],
    }));
    const data = await getGraphData();
    expect(data.nodes).toHaveLength(1);
    expect(data.nodes[0].label).toBe("Test");
  });

  it("debugLog sends message", async () => {
    __setHandler("debug_log", ({ msg }: any) => {
      expect(msg).toBe("test message");
    });
    await debugLog("test message");
  });

  it("unhandled command rejects", async () => {
    await expect(solve("test", "s1")).rejects.toThrow("No mock for command: solve");
  });

  it("getSessionHistory calls invoke with sessionId", async () => {
    const { getSessionHistory } = await import("./invoke");
    __setHandler("get_session_history", ({ sessionId }: any) => {
      expect(sessionId).toBe("session-1");
      return [];
    });
    const history = await getSessionHistory("session-1");
    expect(history).toEqual([]);
  });
});
