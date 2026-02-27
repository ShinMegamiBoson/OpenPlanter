/** /reasoning slash command handler. */
import { updateConfig } from "../api/invoke";
import { appState } from "../state/store";
import type { CommandResult } from "./model";

const VALID_LEVELS = ["low", "medium", "high", "off"];

/** Handle /reasoning [args]. */
export async function handleReasoningCommand(args: string): Promise<CommandResult> {
  const parts = args.trim().split(/\s+/);
  const level = parts[0] || "";

  // /reasoning (no args) — show current
  if (!level) {
    const s = appState.get();
    return {
      action: "handled",
      lines: [
        `Reasoning effort: ${s.reasoningEffort ?? "off"}`,
        `Valid levels: ${VALID_LEVELS.join(", ")}`,
      ],
    };
  }

  const normalized = level.toLowerCase();
  if (!VALID_LEVELS.includes(normalized)) {
    return {
      action: "handled",
      lines: [`Invalid reasoning level "${level}". Expected: ${VALID_LEVELS.join(", ")}`],
    };
  }

  const effort = normalized === "off" ? "" : normalized;
  const save = parts.includes("--save");

  try {
    const config = await updateConfig({
      reasoning_effort: effort,
    });

    appState.update((s) => ({
      ...s,
      reasoningEffort: config.reasoning_effort,
    }));

    const lines = [`Reasoning effort set to: ${config.reasoning_effort ?? "off"}`];
    if (save) {
      lines.push("(Settings saved)");
    }

    return { action: "handled", lines };
  } catch (e) {
    return {
      action: "handled",
      lines: [`Failed to set reasoning: ${e}`],
    };
  }
}
