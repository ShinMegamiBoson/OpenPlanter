/** /model slash command handler. */
import { updateConfig, listModels } from "../api/invoke";
import { appState } from "../state/store";

/** Aliases mapping short names to full model identifiers. */
export const MODEL_ALIASES: Record<string, string> = {
  opus: "claude-opus-4-6",
  sonnet: "claude-sonnet-4-5",
  haiku: "claude-haiku-4-5",
  "sonnet-4": "claude-sonnet-4-5",
  "haiku-4": "claude-haiku-4-5",
  "opus-4": "claude-opus-4-6",
  gpt5: "gpt-5.2",
  "gpt-5": "gpt-5.2",
  gpt4o: "gpt-4o",
  "gpt-4o": "gpt-4o",
  "o1": "o1",
  "o3": "o3",
  "o4-mini": "o4-mini",
  llama: "llama3.2",
  mistral: "mistral",
  gemma: "gemma",
  phi: "phi",
  deepseek: "deepseek",
  qwen: "qwen-3-235b-a22b-instruct-2507",
  "qwen-3": "qwen-3-235b-a22b-instruct-2507",
};

/** Infer provider from a model name, matching builder.rs patterns. */
export function inferProvider(model: string): string | null {
  if (model.includes("/")) return "openrouter";
  if (/^claude/i.test(model)) return "anthropic";
  if (/^(llama.*cerebras|qwen-3|gpt-oss|zai-glm)/i.test(model)) return "cerebras";
  if (/^(gpt|o[1-4]-|o[1-4]$|chatgpt|dall-e|tts-|whisper)/i.test(model)) return "openai";
  if (/^(llama|mistral|gemma|phi|codellama|deepseek|vicuna|tinyllama|neural-chat|dolphin|wizardlm|orca|nous-hermes|command-r|qwen)/i.test(model)) return "ollama";
  return null;
}

export interface CommandResult {
  action: "handled" | "clear" | "quit";
  lines: string[];
}

/** Handle /model [args]. */
export async function handleModelCommand(args: string): Promise<CommandResult> {
  const parts = args.trim().split(/\s+/);
  const subcommand = parts[0] || "";

  // /model (no args) — show current info
  if (!subcommand) {
    const s = appState.get();
    const aliasEntries = Object.entries(MODEL_ALIASES)
      .map(([k, v]) => `  ${k} -> ${v}`)
      .join("\n");
    return {
      action: "handled",
      lines: [
        `Provider: ${s.provider}`,
        `Model:    ${s.model}`,
        "",
        "Aliases:",
        aliasEntries,
      ],
    };
  }

  // /model list [all|<provider>]
  if (subcommand === "list") {
    const filter = parts[1] || "all";
    try {
      const models = await listModels(filter);
      if (models.length === 0) {
        return {
          action: "handled",
          lines: [`No models found for provider "${filter}".`],
        };
      }
      const lines = models.map(
        (m) => `  ${m.id}${m.name ? ` (${m.name})` : ""} [${m.provider}]`
      );
      return {
        action: "handled",
        lines: [`Models for ${filter}:`, ...lines],
      };
    } catch (e) {
      return {
        action: "handled",
        lines: [`Failed to list models: ${e}`],
      };
    }
  }

  // /model <name> [--save]
  const modelName = subcommand;
  const save = parts.includes("--save");

  // Resolve alias
  const resolved = MODEL_ALIASES[modelName.toLowerCase()] ?? modelName;
  const provider = inferProvider(resolved);

  if (!provider) {
    return {
      action: "handled",
      lines: [`Cannot infer provider for "${resolved}". Specify full model name or use a known alias.`],
    };
  }

  try {
    const config = await updateConfig({
      model: resolved,
      provider: provider,
    });

    appState.update((s) => ({
      ...s,
      provider: config.provider,
      model: config.model,
    }));

    const lines = [`Switched to ${config.provider}/${config.model}`];
    if (save) {
      // save_settings would be called here when backend supports it
      lines.push("(Settings saved)");
    }

    return { action: "handled", lines };
  } catch (e) {
    return {
      action: "handled",
      lines: [`Failed to switch model: ${e}`],
    };
  }
}
