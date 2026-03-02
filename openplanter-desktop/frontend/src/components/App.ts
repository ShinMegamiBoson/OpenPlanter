/** Root layout component. */
import { createStatusBar } from "./StatusBar";
import { createChatPane } from "./ChatPane";
import { createGraphPane } from "./GraphPane";
import { appState } from "../state/store";
import { listSessions, openSession, deleteSession, getCredentialsStatus, getSessionHistory } from "../api/invoke";
import type { ChatMessage } from "../state/store";
import type { ReplayEntry } from "../api/types";

export function createApp(root: HTMLElement): void {
  // Status bar
  const statusBar = createStatusBar();
  root.appendChild(statusBar);

  // Sidebar
  const sidebar = document.createElement("div");
  sidebar.className = "sidebar";

  const sessionsHeader = document.createElement("h3");
  sessionsHeader.textContent = "Sessions";
  sidebar.appendChild(sessionsHeader);

  // New session button
  const newSessionBtn = document.createElement("div");
  newSessionBtn.className = "session-item";
  newSessionBtn.style.color = "var(--accent)";
  newSessionBtn.style.fontWeight = "600";
  newSessionBtn.textContent = "+ New Session";
  newSessionBtn.addEventListener("click", () => switchToNewSession(sessionList));
  sidebar.appendChild(newSessionBtn);

  const sessionList = document.createElement("div");
  sessionList.className = "session-list";
  sidebar.appendChild(sessionList);

  const settingsHeader = document.createElement("h3");
  settingsHeader.style.marginTop = "16px";
  settingsHeader.textContent = "Settings";
  sidebar.appendChild(settingsHeader);

  const settingsDisplay = document.createElement("div");
  settingsDisplay.className = "settings-display";
  sidebar.appendChild(settingsDisplay);

  const credsHeader = document.createElement("h3");
  credsHeader.style.marginTop = "16px";
  credsHeader.textContent = "Credentials";
  sidebar.appendChild(credsHeader);

  const credsDisplay = document.createElement("div");
  credsDisplay.className = "cred-status";
  sidebar.appendChild(credsDisplay);

  root.appendChild(sidebar);

  // Chat pane
  const chatPane = createChatPane();
  root.appendChild(chatPane);

  // Graph pane
  const graphPane = createGraphPane();
  root.appendChild(graphPane);

  // Reactive settings display
  function renderSettings() {
    const s = appState.get();
    settingsDisplay.innerHTML = [
      `<div><span class="label">provider:</span> <span class="value">${s.provider || "auto"}</span></div>`,
      `<div><span class="label">model:</span> <span class="value">${s.model || "\u2014"}</span></div>`,
      `<div><span class="label">reasoning:</span> <span class="value">${s.reasoningEffort ?? "off"}</span></div>`,
      `<div><span class="label">mode:</span> <span class="value">${s.recursive ? "recursive" : "flat"}</span></div>`,
    ].join("");
  }
  appState.subscribe(renderSettings);
  renderSettings();

  // Load sessions
  loadSessions(sessionList);

  // Reload session list when session changes
  appState.subscribe(() => {
    highlightActiveSession(sessionList);
  });

  // Load credentials status
  loadCredentials(credsDisplay);
}

/** Switch to a new session, clearing chat state. */
async function switchToNewSession(sessionList: HTMLElement): Promise<void> {
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
    // Dispatch event to clear ChatPane DOM
    window.dispatchEvent(new CustomEvent("session-changed"));
    // Add welcome message
    appState.update((s) => ({
      ...s,
      messages: [
        {
          id: crypto.randomUUID(),
          role: "system" as const,
          content: `New session: ${session.id.slice(0, 8)}`,
          timestamp: Date.now(),
        },
      ],
    }));
    // Reload session list
    loadSessions(sessionList);
  } catch (e) {
    console.error("Failed to create new session:", e);
  }
}

/** Convert a ReplayEntry to a ChatMessage for display. */
function replayEntryToMessage(entry: ReplayEntry): ChatMessage {
  return {
    id: crypto.randomUUID(),
    role: entry.role as ChatMessage["role"],
    content: entry.content,
    toolName: entry.tool_name ?? undefined,
    timestamp: new Date(entry.timestamp).getTime() || Date.now(),
    isRendered: entry.is_rendered ?? (entry.role === "assistant"),
    stepNumber: entry.step_number ?? undefined,
    stepTokensIn: entry.step_tokens_in ?? undefined,
    stepTokensOut: entry.step_tokens_out ?? undefined,
    stepElapsed: entry.step_elapsed ?? undefined,
    stepModelPreview: entry.step_model_preview ?? undefined,
    stepToolCalls: entry.step_tool_calls?.map((tc) => ({
      name: tc.name,
      keyArg: tc.key_arg,
      elapsed: tc.elapsed,
    })),
  };
}

/** Switch to an existing session, loading message history. */
async function switchToSession(sessionId: string, sessionList: HTMLElement): Promise<void> {
  try {
    const resumed = await openSession(sessionId, true);
    appState.update((s) => ({
      ...s,
      sessionId: resumed.id,
      messages: [],
      inputTokens: 0,
      outputTokens: 0,
      currentStep: 0,
      currentDepth: 0,
      inputQueue: [],
    }));
    // Dispatch event to clear ChatPane DOM
    window.dispatchEvent(new CustomEvent("session-changed"));

    // Load message history from replay.jsonl
    let messages: ChatMessage[] = [];
    try {
      const history = await getSessionHistory(resumed.id);
      messages = history.map(replayEntryToMessage);
    } catch (e) {
      console.error("Failed to load session history:", e);
    }

    // Add info message, then history
    const info = resumed.last_objective
      ? `Resumed session ${resumed.id.slice(0, 8)} \u2014 ${resumed.last_objective}`
      : `Resumed session ${resumed.id.slice(0, 8)}`;
    appState.update((s) => ({
      ...s,
      messages: [
        {
          id: crypto.randomUUID(),
          role: "system" as const,
          content: info,
          timestamp: Date.now(),
        },
        ...messages,
      ],
    }));
    highlightActiveSession(sessionList);
  } catch (e) {
    console.error("Failed to resume session:", e);
  }
}

function highlightActiveSession(container: HTMLElement): void {
  const currentId = appState.get().sessionId;
  for (const item of container.querySelectorAll(".session-item")) {
    const el = item as HTMLElement;
    if (el.title === currentId) {
      el.style.background = "var(--bg-tertiary)";
      el.style.color = "var(--accent)";
    } else {
      el.style.background = "";
      el.style.color = "";
    }
  }
}

async function loadSessions(container: HTMLElement): Promise<void> {
  try {
    const sessions = await listSessions(20);
    container.innerHTML = "";
    if (sessions.length === 0) {
      const empty = document.createElement("div");
      empty.className = "session-item";
      empty.style.color = "var(--text-muted)";
      empty.textContent = "No sessions yet";
      container.appendChild(empty);
      return;
    }
    for (const session of sessions) {
      const item = document.createElement("div");
      item.className = "session-item";
      item.title = session.id;
      item.style.display = "flex";
      item.style.alignItems = "center";
      item.style.justifyContent = "space-between";

      const label = document.createElement("span");
      label.style.overflow = "hidden";
      label.style.textOverflow = "ellipsis";
      label.style.whiteSpace = "nowrap";
      label.style.flex = "1";
      const date = new Date(session.created_at);
      const dateStr = date.toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
      label.textContent = session.last_objective
        ? `${dateStr} \u2014 ${session.last_objective}`
        : dateStr;

      label.addEventListener("click", () => switchToSession(session.id, container));

      const deleteBtn = document.createElement("span");
      deleteBtn.className = "session-delete";
      deleteBtn.textContent = "\u00d7";
      deleteBtn.title = "Delete session";
      let confirmPending = false;
      let confirmTimer: ReturnType<typeof setTimeout> | null = null;
      function resetDeleteBtn() {
        confirmPending = false;
        deleteBtn.textContent = "\u00d7";
        deleteBtn.style.color = "";
        deleteBtn.style.fontWeight = "";
        deleteBtn.style.display = "";
      }
      deleteBtn.addEventListener("click", async (e) => {
        e.stopPropagation();
        if (!confirmPending) {
          // First click: enter confirmation state
          confirmPending = true;
          deleteBtn.textContent = "Delete?";
          deleteBtn.style.color = "var(--error)";
          deleteBtn.style.fontWeight = "600";
          deleteBtn.style.display = "inline"; // override CSS display:none
          confirmTimer = setTimeout(resetDeleteBtn, 3000);
          return;
        }
        // Second click: actually delete
        if (confirmTimer) clearTimeout(confirmTimer);
        confirmPending = false;
        deleteBtn.textContent = "...";
        try {
          await deleteSession(session.id);
          if (appState.get().sessionId === session.id) {
            await switchToNewSession(container);
          } else {
            await loadSessions(container);
          }
        } catch (err) {
          deleteBtn.textContent = "Error!";
          console.error("Failed to delete session:", err);
          setTimeout(resetDeleteBtn, 2000);
        }
      });

      item.appendChild(label);
      item.appendChild(deleteBtn);
      container.appendChild(item);
    }
    highlightActiveSession(container);
  } catch (e) {
    console.error("Failed to load sessions:", e);
  }
}

async function loadCredentials(container: HTMLElement): Promise<void> {
  try {
    const status = await getCredentialsStatus();
    container.innerHTML = "";
    const providers = ["openai", "anthropic", "openrouter", "cerebras", "ollama", "exa"];
    for (const p of providers) {
      const row = document.createElement("div");
      const hasKey = status[p] ?? false;
      row.className = hasKey ? "cred-ok" : "cred-missing";
      row.textContent = `${hasKey ? "\u2713" : "\u2717"} ${p}`;
      container.appendChild(row);
    }
  } catch (e) {
    console.error("Failed to load credentials:", e);
  }
}
