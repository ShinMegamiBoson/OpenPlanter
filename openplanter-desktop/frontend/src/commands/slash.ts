/** Slash command dispatcher. */
import { appState } from "../state/store";
import { openSession } from "../api/invoke";
import { handleModelCommand, type CommandResult } from "./model";
import { handleReasoningCommand } from "./reasoning";

/** Dispatch a slash command. Returns null if not a slash command. */
export async function dispatchSlashCommand(input: string): Promise<CommandResult | null> {
  const trimmed = input.trim();
  if (!trimmed.startsWith("/")) return null;

  const spaceIdx = trimmed.indexOf(" ");
  const cmd = spaceIdx === -1 ? trimmed.toLowerCase() : trimmed.slice(0, spaceIdx).toLowerCase();
  const args = spaceIdx === -1 ? "" : trimmed.slice(spaceIdx + 1);

  switch (cmd) {
    case "/help":
      return {
        action: "handled",
        lines: [
          "Available commands:",
          "  /help               Show this help",
          "  /new                Start a new session",
          "  /clear              Clear chat messages",
          "  /quit, /exit        Quit the application",
          "  /status             Show current status",
          "  /model              Show/switch model (aliases: opus, sonnet, haiku, gpt5, ...)",
          "  /model <name>       Switch model (auto-detects provider)",
          "  /model <name> --save  Switch and persist",
          "  /model list [provider]  List available models",
          "  /reasoning          Show/set reasoning effort",
          "  /reasoning <level>  Set level (low, medium, high, off)",
        ],
      };

    case "/new": {
      try {
        const session = await openSession();
        appState.update((s) => ({
          ...s,
          sessionId: session.id,
          messages: [],
          inputTokens: 0,
          outputTokens: 0,
          currentStep: 0,
          currentDepth: 0,
          inputQueue: [],
        }));
        window.dispatchEvent(new CustomEvent("session-changed", { detail: { isNew: true } }));
        return {
          action: "handled",
          lines: [`New session: ${session.id.slice(0, 8)}`],
        };
      } catch (e) {
        return {
          action: "handled",
          lines: [`Failed to create session: ${e}`],
        };
      }
    }

    case "/clear":
      return { action: "clear", lines: [] };

    case "/quit":
    case "/exit":
      return { action: "quit", lines: ["Goodbye."] };

    case "/status": {
      const s = appState.get();
      const inK = (s.inputTokens / 1000).toFixed(1);
      const outK = (s.outputTokens / 1000).toFixed(1);
      return {
        action: "handled",
        lines: [
          `Provider:    ${s.provider || "auto"}`,
          `Model:       ${s.model || "—"}`,
          `Reasoning:   ${s.reasoningEffort ?? "off"}`,
          `Mode:        ${s.recursive ? "recursive" : "flat"}`,
          `Max depth:   ${s.maxDepth}`,
          `Max steps:   ${s.maxStepsPerCall}`,
          `Workspace:   ${s.workspace || "."}`,
          `Session:     ${s.sessionId ? s.sessionId.slice(0, 8) : "—"}`,
          `Tokens:      ${inK}k in / ${outK}k out`,
          `Running:     ${s.isRunning ? "yes" : "no"}`,
          `Queue:       ${s.inputQueue.length} item(s)`,
        ],
      };
    }

    case "/model":
      return handleModelCommand(args);

    case "/reasoning":
      return handleReasoningCommand(args);

    default:
      return {
        action: "handled",
        lines: [`Unknown command: ${cmd}. Type /help for available commands.`],
      };
  }
}
