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
  getInitStatus,
  inspectMigrationSource,
  debugLog,
  runMigrationInit,
  runStandardInit,
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
      model: "anthropic-foundry/claude-opus-4-6",
      zai_plan: "paygo",
      workspace: ".",
      session_id: null,
      recursive: true,
      max_depth: 4,
      max_steps_per_call: 100,
      reasoning_effort: "high",
      web_search_provider: "exa",
      demo: false,
    }));
    const config = await getConfig();
    expect(config.provider).toBe("anthropic");
    expect(config.model).toBe("anthropic-foundry/claude-opus-4-6");
    expect(config.zai_plan).toBe("paygo");
    expect(config.web_search_provider).toBe("exa");
  });

  it("updateConfig sends partial and returns config", async () => {
    __setHandler("update_config", ({ partial }: any) => {
      expect(partial.model).toBe("azure-foundry/gpt-5.4");
      return {
        provider: "openai",
        model: "azure-foundry/gpt-5.4",
        zai_plan: "coding",
        workspace: ".",
        session_id: null,
        recursive: true,
        max_depth: 4,
        max_steps_per_call: 100,
        reasoning_effort: null,
        web_search_provider: "firecrawl",
        demo: false,
      };
    });
    const config = await updateConfig({ model: "azure-foundry/gpt-5.4" });
    expect(config.model).toBe("azure-foundry/gpt-5.4");
    expect(config.zai_plan).toBe("coding");
    expect(config.web_search_provider).toBe("firecrawl");
  });

  it("listModels sends provider filter", async () => {
    __setHandler("list_models", ({ provider }: any) => {
      expect(provider).toBe("openai");
      return [
        {
          id: "azure-foundry/gpt-5.4",
          name: "GPT-5.4 (Foundry)",
          provider: "openai",
        },
      ];
    });
    const models = await listModels("openai");
    expect(models).toHaveLength(1);
    expect(models[0].id).toBe("azure-foundry/gpt-5.4");
  });

  it("saveSettings sends settings object", async () => {
    __setHandler("save_settings", ({ settings }: any) => {
      expect(settings.default_model_zai).toBe("glm-5");
      expect(settings.zai_plan).toBe("coding");
      expect(settings.web_search_provider).toBe("firecrawl");
    });
    await saveSettings({
      default_model_zai: "glm-5",
      zai_plan: "coding",
      web_search_provider: "firecrawl",
    });
  });

  it("getCredentialsStatus returns provider map", async () => {
    __setHandler("get_credentials_status", () => ({
      openai: true,
      anthropic: true,
      openrouter: false,
      cerebras: false,
      zai: true,
      ollama: true,
      exa: false,
      firecrawl: true,
      brave: false,
      tavily: true,
      voyage: true,
      mistral_transcription: true,
    }));
    const status = await getCredentialsStatus();
    expect(status.openai).toBe(true);
    expect(status.openrouter).toBe(false);
    expect(status.zai).toBe(true);
    expect(status.firecrawl).toBe(true);
    expect(status.brave).toBe(false);
    expect(status.tavily).toBe(true);
    expect(status.voyage).toBe(true);
    expect(status.mistral_transcription).toBe(true);
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

  it("getInitStatus calls invoke", async () => {
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
    const status = await getInitStatus();
    expect(status.runtime_workspace).toBe("/tmp/ws");
    expect(status.gate_state).toBe("requires_action");
  });

  it("runStandardInit calls invoke", async () => {
    __setHandler("run_standard_init", () => ({
      workspace: "/tmp/ws",
      created_paths: ["/tmp/ws/.openplanter"],
      copied_paths: ["/tmp/ws/.openplanter/wiki/index.md"],
      skipped_existing: 0,
      errors: [],
      onboarding_required: false,
    }));
    const report = await runStandardInit();
    expect(report.workspace).toBe("/tmp/ws");
    expect(report.created_paths).toHaveLength(1);
  });

  it("inspectMigrationSource sends path", async () => {
    __setHandler("inspect_migration_source", ({ path }: any) => {
      expect(path).toBe("/tmp/source");
      return {
        path,
        kind: "manual_research",
        has_sessions: false,
        has_settings: false,
        has_credentials: false,
        has_runtime_wiki: false,
        has_baseline_wiki: false,
        markdown_files: 4,
        warnings: [],
      };
    });
    const inspection = await inspectMigrationSource("/tmp/source");
    expect(inspection.kind).toBe("manual_research");
    expect(inspection.markdown_files).toBe(4);
  });

  it("runMigrationInit sends request payload", async () => {
    __setHandler("run_migration_init", ({ request }: any) => {
      expect(request.target_workspace).toBe("/tmp/target");
      expect(request.sources).toEqual([{ path: "/tmp/a" }, { path: "/tmp/b" }]);
      return {
        target_workspace: "/tmp/target",
        sources: ["/tmp/a", "/tmp/b"],
        sessions_copied: 2,
        sessions_renamed: 1,
        settings_merged_fields: ["default_model"],
        credentials_merged_fields: ["openai_api_key"],
        wiki_files_synthesized: 3,
        raw_preservation_root: "/tmp/target/.openplanter/migration/raw",
        rewrite_summary: "Curator rewrote 3 wiki files from imported sources.",
        restart_required: true,
        restart_message: "Restart required",
        warnings: [],
      };
    });
    const result = await runMigrationInit({
      target_workspace: "/tmp/target",
      sources: [{ path: "/tmp/a" }, { path: "/tmp/b" }],
    });
    expect(result.sessions_copied).toBe(2);
    expect(result.restart_required).toBe(true);
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
