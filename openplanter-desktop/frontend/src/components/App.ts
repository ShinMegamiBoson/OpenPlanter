/** Root layout component. */
import { createStatusBar } from "./StatusBar";
import { createChatPane } from "./ChatPane";
import { createInputBar } from "./InputBar";
import { createGraphPane } from "./GraphPane";

export function createApp(root: HTMLElement): void {
  // Status bar
  const statusBar = createStatusBar();
  root.appendChild(statusBar);

  // Sidebar
  const sidebar = document.createElement("div");
  sidebar.className = "sidebar";
  sidebar.innerHTML = `
    <h3>Sessions</h3>
    <div class="session-list"></div>
    <h3 style="margin-top: 16px;">Settings</h3>
  `;
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
}
