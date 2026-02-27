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

  // Load credentials status
  loadCredentials(credsDisplay);
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
      item.title = session.id;

      item.addEventListener("click", async () => {
        try {
          const resumed = await openSession(session.id, true);
          appState.update((s) => ({ ...s, sessionId: resumed.id }));
        } catch (e) {
          console.error("Failed to resume session:", e);
        }
      });

      container.appendChild(item);
    }
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
