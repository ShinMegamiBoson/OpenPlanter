import { createApp } from "./components/App";
import { getConfig, openSession } from "./api/invoke";
import {
  onAgentTrace,
  onAgentDelta,
  onAgentComplete,
  onAgentError,
  onAgentStep,
  onWikiUpdated,
} from "./api/events";
import { appState } from "./state/store";

async function init() {
  const app = document.getElementById("app")!;
  createApp(app);

  // Load initial config
  try {
    const config = await getConfig();
    appState.update((s) => ({
      ...s,
      provider: config.provider,
      model: config.model,
      sessionId: config.session_id,
    }));
  } catch (e) {
    console.error("Failed to load config:", e);
  }

  // Open a new session
  try {
    const session = await openSession();
    appState.update((s) => ({ ...s, sessionId: session.id }));
  } catch (e) {
    console.error("Failed to open session:", e);
  }

  // Subscribe to agent events
  onAgentTrace((msg) => {
    console.log("[trace]", msg);
  });

  onAgentStep((event) => {
    appState.update((s) => ({
      ...s,
      inputTokens: s.inputTokens + event.tokens.input_tokens,
      outputTokens: s.outputTokens + event.tokens.output_tokens,
    }));
  });

  onAgentDelta((event) => {
    // Streaming text updates handled by ChatPane
    const detail = new CustomEvent("agent-delta", { detail: event });
    window.dispatchEvent(detail);
  });

  onAgentComplete((result) => {
    appState.update((s) => ({
      ...s,
      isRunning: false,
      messages: [
        ...s.messages,
        {
          id: crypto.randomUUID(),
          role: "assistant" as const,
          content: result,
          timestamp: Date.now(),
        },
      ],
    }));
  });

  onAgentError((message) => {
    appState.update((s) => ({
      ...s,
      isRunning: false,
      messages: [
        ...s.messages,
        {
          id: crypto.randomUUID(),
          role: "system" as const,
          content: `Error: ${message}`,
          timestamp: Date.now(),
        },
      ],
    }));
  });

  onWikiUpdated((data) => {
    const detail = new CustomEvent("wiki-updated", { detail: data });
    window.dispatchEvent(detail);
  });
}

init();
