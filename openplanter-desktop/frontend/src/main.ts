import { createApp } from "./components/App";
import { getConfig, getInitStatus } from "./api/invoke";
import {
  onAgentTrace,
  onAgentDelta,
  onAgentCompleteEvent,
  onAgentError,
  onAgentStep,
  onWikiUpdated,
  onCuratorUpdate,
  onLoopHealth,
  onMigrationProgress,
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
    const initStatus = await getInitStatus();
    appState.update((s) => ({
      ...s,
      provider: config.provider,
      model: config.model,
      zaiPlan: config.zai_plan,
      webSearchProvider: config.web_search_provider,
      sessionId: config.session_id,
      reasoningEffort: config.reasoning_effort,
      recursive: config.recursive,
      workspace: config.workspace,
      maxDepth: config.max_depth,
      maxStepsPerCall: config.max_steps_per_call,
      initStatus,
      initGateState: initStatus.gate_state,
      initGateVisible: initStatus.gate_state !== "ready",
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
          `z.ai plan: ${state.zaiPlan || "paygo"}`,
          `web search: ${state.webSearchProvider || "exa"}`,
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
      ...(state.initGateState !== "ready"
        ? [
            {
              id: crypto.randomUUID(),
              role: "system" as const,
              content:
                "Workspace initialization is required before running the agent. Use the setup panel or /init.",
              timestamp: Date.now(),
            },
          ]
        : []),
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
      lastLoopMetrics: event.loop_metrics ?? s.lastLoopMetrics,
    }));

    // Dispatch to ChatPane for rich step summary rendering
    window.dispatchEvent(new CustomEvent("agent-step", { detail: event }));
  });

  await onAgentDelta((event) => {
    const detail = new CustomEvent("agent-delta", { detail: event });
    window.dispatchEvent(detail);
  });

  await onAgentCompleteEvent((event) => {
    appState.update((s) => ({
      ...s,
      isRunning: false,
      currentStep: 0,
      currentDepth: 0,
      loopHealth: null,
      lastLoopMetrics: event.loop_metrics ?? s.lastLoopMetrics,
      lastCompletion: event.completion ?? null,
      messages: [
        ...s.messages,
        {
          id: crypto.randomUUID(),
          role: "assistant" as const,
          content: event.result,
          timestamp: Date.now(),
          isRendered: true,
        },
        ...(event.completion?.kind === "partial"
          ? [
              {
                id: crypto.randomUUID(),
                role: "system" as const,
                content:
                  "Partial completion: the run used its bounded step budget and stopped cleanly. Resume to continue from the saved state.",
                timestamp: Date.now(),
              },
            ]
          : []),
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
      loopHealth: null,
      lastCompletion: null,
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

  await onCuratorUpdate(() => {
    // Notify graph pane to refresh with curator's wiki changes
    window.dispatchEvent(new CustomEvent("curator-done"));
  });

  await onLoopHealth((event) => {
    appState.update((s) => ({
      ...s,
      loopHealth: event,
      lastLoopMetrics: event.metrics,
    }));
  });

  await onMigrationProgress((event) => {
    appState.update((s) => ({
      ...s,
      migrationProgress: event,
      isInitBusy: event.stage !== "done",
    }));
  });
}

function processQueue() {
  const state = appState.get();
  if (state.inputQueue.length > 0) {
    const [next, ...rest] = state.inputQueue;
    appState.update((s) => ({ ...s, inputQueue: rest }));
    // Dispatch queued-submit event for InputBar to pick up
    window.dispatchEvent(
      new CustomEvent("queued-submit", { detail: { text: next } }),
    );
  }
}

init();
