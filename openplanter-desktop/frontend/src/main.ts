import { createApp } from "./components/App";
import { getConfig } from "./api/invoke";
import {
  onAgentTrace,
  onAgentDelta,
  onAgentComplete,
  onAgentError,
  onAgentStep,
  onWikiUpdated,
  onCuratorUpdate,
} from "./api/events";
import { appState } from "./state/store";

const SPLASH_ART = [
  " .oOo.      ___                   ____  _             _                .oOo. ",
  "oO.|.Oo    / _ \\ _ __   ___ _ __ |  _ \\| | __ _ _ __ | |_ ___ _ __    oO.|.Oo",
  "Oo.|.oO   | | | | '_ \\ / _ \\ '_ \\| |_) | |/ _` | '_ \\| __/ _ \\ '__|   Oo.|.oO",
  "  .|.     | |_| | |_) |  __/ | | |  __/| | (_| | | | | ||  __/ |        .|.  ",
  "[=====]    \\___/| .__/ \\___|_| |_|_|   |_|\\__,_|_| |_|\\__\\___|_|      [=====]",
  " \\___/          |_|                                                    \\___/ ",
].join("\n");

async function init() {
  const app = document.getElementById("app")!;
  createApp(app);

  // Load initial config
  let provider = "";
  let model = "";
  try {
    const config = await getConfig();
    provider = config.provider;
    model = config.model;
    appState.update((s) => ({
      ...s,
      provider: config.provider,
      model: config.model,
      sessionId: config.session_id,
      reasoningEffort: config.reasoning_effort,
      recursive: config.recursive,
      workspace: config.workspace,
      maxDepth: config.max_depth,
      maxStepsPerCall: config.max_steps_per_call,
    }));
  } catch (e) {
    console.error("Failed to load config:", e);
  }

  // Add splash art and startup info (session created lazily on first message)
  const state = appState.get();
  const reasoningLabel = state.reasoningEffort ?? "off";
  const modeLabel = state.recursive ? "recursive" : "flat";

  appState.update((s) => ({
    ...s,
    messages: [
      {
        id: crypto.randomUUID(),
        role: "splash" as const,
        content: SPLASH_ART,
        timestamp: Date.now(),
      },
      {
        id: crypto.randomUUID(),
        role: "system" as const,
        content: [
          `provider: ${provider || "auto"}`,
          `model: ${model || "—"}`,
          `reasoning: ${reasoningLabel}`,
          `mode: ${modeLabel}`,
          `workspace: ${state.workspace || "."}`,
        ].join("  |  "),
        timestamp: Date.now(),
      },
      {
        id: crypto.randomUUID(),
        role: "system" as const,
        content: "Type /help for commands. ESC to cancel a running task.",
        timestamp: Date.now(),
      },
    ],
  }));

  // Subscribe to agent events — await each to ensure listeners are registered
  await onAgentTrace((msg) => {
    console.log("[trace]", msg);
  });

  await onAgentStep((event) => {
    appState.update((s) => ({
      ...s,
      inputTokens: s.inputTokens + event.tokens.input_tokens,
      outputTokens: s.outputTokens + event.tokens.output_tokens,
      currentStep: event.step,
      currentDepth: event.depth,
    }));

    // Dispatch to ChatPane for rich step summary rendering
    window.dispatchEvent(
      new CustomEvent("agent-step", { detail: event })
    );
  });

  await onAgentDelta((event) => {
    const detail = new CustomEvent("agent-delta", { detail: event });
    window.dispatchEvent(detail);
  });

  await onAgentComplete((result) => {
    appState.update((s) => ({
      ...s,
      isRunning: false,
      currentStep: 0,
      currentDepth: 0,
      messages: [
        ...s.messages,
        {
          id: crypto.randomUUID(),
          role: "assistant" as const,
          content: result,
          timestamp: Date.now(),
          isRendered: true,
        },
      ],
    }));

    // Process input queue
    processQueue();
  });

  await onAgentError((message) => {
    appState.update((s) => ({
      ...s,
      isRunning: false,
      currentStep: 0,
      currentDepth: 0,
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

    // Process input queue even on error
    processQueue();
  });

  await onWikiUpdated((data) => {
    const detail = new CustomEvent("wiki-updated", { detail: data });
    window.dispatchEvent(detail);
  });

  await onCuratorUpdate((event) => {
    appState.update((s) => ({
      ...s,
      messages: [
        ...s.messages,
        {
          id: crypto.randomUUID(),
          role: "system" as const,
          content: `[Wiki Curator] ${event.summary}`,
          timestamp: Date.now(),
        },
      ],
    }));

    // Notify graph pane to refresh with curator's wiki changes
    window.dispatchEvent(new CustomEvent("curator-done"));
  });
}

function processQueue() {
  const state = appState.get();
  if (state.inputQueue.length > 0) {
    const [next, ...rest] = state.inputQueue;
    appState.update((s) => ({ ...s, inputQueue: rest }));
    // Dispatch queued-submit event for InputBar to pick up
    window.dispatchEvent(
      new CustomEvent("queued-submit", { detail: { text: next } })
    );
  }
}

init();
