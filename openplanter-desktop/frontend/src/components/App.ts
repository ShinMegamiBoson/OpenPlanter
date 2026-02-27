/** Root layout component. */
import { createStatusBar } from "./StatusBar";
import { createChatPane } from "./ChatPane";
import { createInputBar } from "./InputBar";
import { createGraphPane } from "./GraphPane";
import { appState } from "../state/store";
import { listSessions, openSession, getCredentialsStatus } from "../api/invoke";

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

  // Input bar
  const inputBar = createInputBar();
  root.appendChild(inputBar);

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

/** Switch to an existing session, clearing chat state. */
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
    // Add info message
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
      const date = new Date(session.created_at);
      const dateStr = date.toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
      item.textContent = session.last_objective
        ? `${dateStr} \u2014 ${session.last_objective}`
        : dateStr;

      item.addEventListener("click", () => switchToSession(session.id, container));
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
    const providers = ["openai", "anthropic", "openrouter", "cerebras", "ollama"];
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
