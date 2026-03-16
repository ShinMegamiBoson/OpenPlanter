import { vi, describe, it, expect, beforeEach, afterEach } from "vitest";
import { __setHandler, __clearHandlers } from "../__mocks__/tauri";

vi.mock("@tauri-apps/api/core", async () => {
  const mock = await import("../__mocks__/tauri");
  return { invoke: mock.invoke };
});

import { appState } from "../state/store";
import { CHROME_USAGE, handleChromeCommand } from "./chrome";

function makeChromeConfig(overrides: Record<string, unknown> = {}) {
  return {
    provider: "anthropic",
    model: "claude-opus-4-6",
    reasoning_effort: "medium",
    zai_plan: "paygo",
    web_search_provider: "exa",
    chrome_mcp_enabled: true,
    chrome_mcp_auto_connect: true,
    chrome_mcp_browser_url: null,
    chrome_mcp_channel: "stable",
    chrome_mcp_connect_timeout_sec: 15,
    chrome_mcp_rpc_timeout_sec: 45,
    chrome_mcp_status: "ready",
    chrome_mcp_status_detail: "Connected to Chrome.",
    workspace: ".",
    session_id: null,
    recursive: true,
    max_depth: 4,
    max_steps_per_call: 100,
    demo: false,
    ...overrides,
  };
}

describe("handleChromeCommand", () => {
  const originalState = appState.get();

  beforeEach(() => {
    appState.set({
      ...originalState,
      chromeMcpEnabled: false,
      chromeMcpAutoConnect: true,
      chromeMcpBrowserUrl: null,
      chromeMcpChannel: "stable",
      chromeMcpStatus: "disabled",
      chromeMcpStatusDetail: "Chrome DevTools MCP is disabled.",
    });
  });

  afterEach(() => {
    __clearHandlers();
    appState.set(originalState);
  });

  it("shows current status with usage when called without args", async () => {
    const result = await handleChromeCommand("");
    expect(result.lines[0]).toContain("Chrome MCP:");
    expect(result.lines[1]).toContain("Chrome runtime:");
    expect(result.lines).toContain(CHROME_USAGE);
  });

  it("updates auto-connect mode", async () => {
    __setHandler("update_config", ({ partial }: { partial: Record<string, unknown> }) => {
      expect(partial.chrome_mcp_enabled).toBe(true);
      expect(partial.chrome_mcp_auto_connect).toBe(true);
      expect(partial.chrome_mcp_browser_url).toBe("");
      return makeChromeConfig();
    });

    const result = await handleChromeCommand("auto");
    expect(result.lines[0]).toContain("attach=auto-connect");
    expect(appState.get().chromeMcpEnabled).toBe(true);
    expect(appState.get().chromeMcpAutoConnect).toBe(true);
    expect(appState.get().chromeMcpBrowserUrl).toBeNull();
  });

  it("updates explicit browser url and persists when requested", async () => {
    __setHandler("update_config", ({ partial }: { partial: Record<string, unknown> }) => {
      expect(partial.chrome_mcp_enabled).toBe(true);
      expect(partial.chrome_mcp_auto_connect).toBe(false);
      expect(partial.chrome_mcp_browser_url).toBe("http://127.0.0.1:9222");
      return makeChromeConfig({
        chrome_mcp_auto_connect: false,
        chrome_mcp_browser_url: "http://127.0.0.1:9222",
        chrome_mcp_status_detail: "Attached to remote debugging endpoint.",
      });
    });
    __setHandler("save_settings", ({ settings }: { settings: Record<string, unknown> }) => {
      expect(settings.chrome_mcp_enabled).toBe(true);
      expect(settings.chrome_mcp_auto_connect).toBe(false);
      expect(settings.chrome_mcp_browser_url).toBe("http://127.0.0.1:9222");
      expect(settings.chrome_mcp_channel).toBe("stable");
    });

    const result = await handleChromeCommand("url http://127.0.0.1:9222 --save");
    expect(result.lines[0]).toContain("browser_url=http://127.0.0.1:9222");
    expect(result.lines).toContain("(Settings saved)");
    expect(appState.get().chromeMcpBrowserUrl).toBe("http://127.0.0.1:9222");
  });

  it("updates the Chrome channel", async () => {
    __setHandler("update_config", ({ partial }: { partial: Record<string, unknown> }) => {
      expect(partial.chrome_mcp_channel).toBe("beta");
      return makeChromeConfig({
        chrome_mcp_channel: "beta",
        chrome_mcp_status: "unavailable",
        chrome_mcp_status_detail: "Chrome Beta is not running.",
      });
    });

    const result = await handleChromeCommand("channel beta");
    expect(result.lines[0]).toContain("channel=beta");
    expect(result.lines[1]).toContain("unavailable");
    expect(appState.get().chromeMcpChannel).toBe("beta");
  });

  it("rejects invalid channels", async () => {
    const result = await handleChromeCommand("channel nightly");
    expect(result.lines[0]).toContain("Invalid Chrome channel");
  });

  it("shows url usage when endpoint is missing", async () => {
    const result = await handleChromeCommand("url");
    expect(result.lines).toEqual(["Usage: /chrome url <endpoint> [--save]"]);
  });
});
