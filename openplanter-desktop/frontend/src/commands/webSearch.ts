/** /web-search slash command handler. */
import { saveSettings, updateConfig } from "../api/invoke";
import { appState } from "../state/store";
import type { CommandResult } from "./model";

const VALID_WEB_SEARCH_PROVIDERS = ["exa", "firecrawl"];

/** Handle /web-search [provider] [--save]. */
export async function handleWebSearchCommand(args: string): Promise<CommandResult> {
  const parts = args.trim().split(/\s+/).filter(Boolean);
  const requestedProvider = parts[0]?.toLowerCase() ?? "";
  const save = parts.includes("--save");

  if (!requestedProvider) {
    const current = appState.get().webSearchProvider || "exa";
    return {
      action: "handled",
      lines: [
        `Web search provider: ${current}`,
        `Valid providers: ${VALID_WEB_SEARCH_PROVIDERS.join(", ")}`,
      ],
    };
  }

  if (!VALID_WEB_SEARCH_PROVIDERS.includes(requestedProvider)) {
    return {
      action: "handled",
      lines: [
        `Invalid web search provider "${requestedProvider}". Expected: ${VALID_WEB_SEARCH_PROVIDERS.join(", ")}`,
      ],
    };
  }

  try {
    const config = await updateConfig({
      web_search_provider: requestedProvider,
    });

    appState.update((s) => ({
      ...s,
      zaiPlan: config.zai_plan,
      webSearchProvider: config.web_search_provider,
    }));

    const lines = [`Web search provider set to: ${config.web_search_provider}`];
    if (save) {
      await saveSettings({ web_search_provider: config.web_search_provider });
      lines.push("(Settings saved)");
    }

    return { action: "handled", lines };
  } catch (e) {
    return {
      action: "handled",
      lines: [`Failed to set web search provider: ${e}`],
    };
  }
}
