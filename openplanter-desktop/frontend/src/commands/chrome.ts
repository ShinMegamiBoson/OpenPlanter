/** /chrome slash command handler. */
import { saveSettings, updateConfig } from "../api/invoke";
import type { ConfigView } from "../api/types";
import { appState, type AppState } from "../state/store";
import type { CommandResult } from "./model";

export const VALID_CHROME_CHANNELS = ["stable", "beta", "dev", "canary"] as const;
export const CHROME_USAGE =
  "Usage: /chrome status|on|off|auto|url <endpoint>|channel <stable|beta|dev|canary> [--save]";

type ChromeStatusSource = Pick<
  AppState,
  | "chromeMcpEnabled"
  | "chromeMcpAutoConnect"
  | "chromeMcpBrowserUrl"
  | "chromeMcpChannel"
  | "chromeMcpStatus"
  | "chromeMcpStatusDetail"
>;

function applyChromeConfig(config: ConfigView): void {
  appState.update((state) => ({
    ...state,
    chromeMcpEnabled: config.chrome_mcp_enabled,
    chromeMcpAutoConnect: config.chrome_mcp_auto_connect,
    chromeMcpBrowserUrl: config.chrome_mcp_browser_url,
    chromeMcpChannel: config.chrome_mcp_channel,
    chromeMcpConnectTimeoutSec: config.chrome_mcp_connect_timeout_sec,
    chromeMcpRpcTimeoutSec: config.chrome_mcp_rpc_timeout_sec,
    chromeMcpStatus: config.chrome_mcp_status,
    chromeMcpStatusDetail: config.chrome_mcp_status_detail,
  }));
}

function describeAttachMode(state: ChromeStatusSource): string {
  if (state.chromeMcpBrowserUrl) {
    return `browser_url=${state.chromeMcpBrowserUrl}`;
  }
  return state.chromeMcpAutoConnect ? "auto-connect" : "manual-disabled";
}

export function formatChromeStatusLines(state: ChromeStatusSource): string[] {
  return [
    `Chrome MCP: enabled=${state.chromeMcpEnabled} | attach=${describeAttachMode(state)} | channel=${state.chromeMcpChannel}`,
    `Chrome runtime: ${state.chromeMcpStatus} | ${state.chromeMcpStatusDetail}`,
  ];
}

/** Handle /chrome [status|on|off|auto|url|channel]. */
export async function handleChromeCommand(args: string): Promise<CommandResult> {
  const parts = args.trim().split(/\s+/).filter(Boolean);
  const save = parts.includes("--save");
  const filtered = parts.filter((part) => part !== "--save");
  const action = filtered[0]?.toLowerCase() ?? "";

  if (!action || action === "status") {
    const lines = formatChromeStatusLines(appState.get());
    if (!action) {
      lines.push(CHROME_USAGE);
    }
    return { action: "handled", lines };
  }

  let partial: Record<string, unknown>;
  switch (action) {
    case "on":
      partial = { chrome_mcp_enabled: true };
      break;
    case "off":
      partial = { chrome_mcp_enabled: false };
      break;
    case "auto":
      partial = {
        chrome_mcp_enabled: true,
        chrome_mcp_auto_connect: true,
        // Tauri partial config treats `null` as "field omitted", so send an
        // empty string and let the Rust normalizer clear the stored URL.
        chrome_mcp_browser_url: "",
      };
      break;
    case "url":
      if (filtered.length < 2) {
        return { action: "handled", lines: ["Usage: /chrome url <endpoint> [--save]"] };
      }
      partial = {
        chrome_mcp_enabled: true,
        chrome_mcp_auto_connect: false,
        chrome_mcp_browser_url: filtered[1].trim(),
      };
      break;
    case "channel": {
      const channel = filtered[1]?.trim().toLowerCase() ?? "";
      if (!channel) {
        return {
          action: "handled",
          lines: ["Usage: /chrome channel <stable|beta|dev|canary> [--save]"],
        };
      }
      if (!VALID_CHROME_CHANNELS.includes(channel as (typeof VALID_CHROME_CHANNELS)[number])) {
        return {
          action: "handled",
          lines: [`Invalid Chrome channel "${channel}". Expected: ${VALID_CHROME_CHANNELS.join(", ")}`],
        };
      }
      partial = { chrome_mcp_channel: channel };
      break;
    }
    default:
      return {
        action: "handled",
        lines: [`Unknown /chrome action "${action}".`, CHROME_USAGE],
      };
  }

  try {
    const config = await updateConfig(partial);
    applyChromeConfig(config);

    const lines = formatChromeStatusLines(appState.get());
    if (save) {
      await saveSettings({
        chrome_mcp_enabled: config.chrome_mcp_enabled,
        chrome_mcp_auto_connect: config.chrome_mcp_auto_connect,
        chrome_mcp_browser_url: config.chrome_mcp_browser_url,
        chrome_mcp_channel: config.chrome_mcp_channel,
        chrome_mcp_connect_timeout_sec: config.chrome_mcp_connect_timeout_sec,
        chrome_mcp_rpc_timeout_sec: config.chrome_mcp_rpc_timeout_sec,
      });
      lines.push("(Settings saved)");
    }
    return { action: "handled", lines };
  } catch (e) {
    return {
      action: "handled",
      lines: [`Failed to update Chrome MCP settings: ${e}`],
    };
  }
}
