/** Chat pane: messages, streaming, tool cards. */
import { appState, type ChatMessage } from "../state/store";

export function createChatPane(): HTMLElement {
  const pane = document.createElement("div");
  pane.className = "chat-pane";

  let renderedCount = 0;

  function renderMessage(msg: ChatMessage): HTMLElement {
    const el = document.createElement("div");
    el.className = `message ${msg.role}`;

    if (msg.toolName) {
      const toolLabel = document.createElement("div");
      toolLabel.className = "tool-name";
      toolLabel.textContent = msg.toolName;
      el.appendChild(toolLabel);
    }

    const content = document.createElement("div");
    content.textContent = msg.content;
    el.appendChild(content);

    return el;
  }

  function render() {
    const messages = appState.get().messages;
    // Only render new messages
    while (renderedCount < messages.length) {
      const msgEl = renderMessage(messages[renderedCount]);
      pane.appendChild(msgEl);
      renderedCount++;
    }
    // Auto-scroll
    pane.scrollTop = pane.scrollHeight;
  }

  appState.subscribe(render);

  // Handle streaming deltas
  let streamingEl: HTMLElement | null = null;
  window.addEventListener("agent-delta", ((e: CustomEvent) => {
    const { kind, text } = e.detail;
    if (kind === "text" || kind === "thinking") {
      if (!streamingEl) {
        streamingEl = document.createElement("div");
        streamingEl.className = "message assistant streaming";
        pane.appendChild(streamingEl);
      }
      streamingEl.textContent += text;
      pane.scrollTop = pane.scrollHeight;
    } else if (kind === "tool_call_start") {
      // Finalize previous stream
      streamingEl = null;
      const toolEl = document.createElement("div");
      toolEl.className = "message tool";
      const label = document.createElement("div");
      label.className = "tool-name";
      label.textContent = text;
      toolEl.appendChild(label);
      pane.appendChild(toolEl);
    }
  }) as EventListener);

  // When complete event fires, clear streaming element
  appState.subscribe(() => {
    if (!appState.get().isRunning && streamingEl) {
      streamingEl = null;
    }
  });

  return pane;
}
