/** Chat pane: terminal-style messages, streaming, markdown rendering. */
import { appState, type ChatMessage } from "../state/store";
import MarkdownIt from "markdown-it";
import hljs from "highlight.js";

/** Key argument names for tool call display. */
const KEY_ARGS: Record<string, string> = {
  read_file: "path",
  write_file: "path",
  edit_file: "path",
  list_files: "directory",
  run_shell: "command",
  run_shell_bg: "command",
  kill_shell_bg: "pid",
  web_search: "query",
  fetch_url: "url",
  apply_patch: "path",
  hashline_edit: "path",
};

const md = new MarkdownIt({
  html: false,
  linkify: true,
  typographer: false,
  highlight(str: string, lang: string) {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return hljs.highlight(str, { language: lang }).value;
      } catch { /* fallback */ }
    }
    return "";
  },
});

export function createChatPane(): HTMLElement {
  const pane = document.createElement("div");
  pane.className = "chat-pane";

  let renderedCount = 0;

  function renderMessage(msg: ChatMessage): HTMLElement {
    const el = document.createElement("div");
    el.className = `message ${msg.role}`;

    switch (msg.role) {
      case "splash":
        el.textContent = msg.content;
        break;

      case "step-header":
        el.textContent = msg.content;
        break;

      case "tool-tree": {
        if (msg.toolCalls && msg.toolCalls.length > 0) {
          for (const tc of msg.toolCalls) {
            const line = document.createElement("div");
            line.className = "tool-tree-line";
            const fn = document.createElement("span");
            fn.className = "tool-fn";
            fn.textContent = tc.name;
            line.appendChild(fn);
            if (tc.args) {
              const arg = document.createElement("span");
              arg.className = "tool-arg";
              arg.textContent = ` ${tc.args}`;
              line.appendChild(arg);
            }
            el.appendChild(line);
          }
        } else {
          el.textContent = msg.content;
        }
        break;
      }

      case "thinking":
        el.textContent = msg.content;
        break;

      case "user":
      case "system":
        el.textContent = msg.content;
        break;

      case "tool":
        if (msg.toolName) {
          const toolLabel = document.createElement("div");
          toolLabel.className = "tool-name";
          toolLabel.textContent = msg.toolName;
          el.appendChild(toolLabel);
        }
        el.appendChild(document.createTextNode(msg.content));
        break;

      case "assistant":
        if (msg.isRendered) {
          el.classList.add("rendered");
          el.innerHTML = md.render(msg.content);
        } else {
          el.textContent = msg.content;
        }
        break;

      default:
        el.textContent = msg.content;
    }

    return el;
  }

  function render() {
    const messages = appState.get().messages;
    while (renderedCount < messages.length) {
      const msgEl = renderMessage(messages[renderedCount]);
      pane.appendChild(msgEl);
      renderedCount++;
    }
    pane.scrollTop = pane.scrollHeight;
  }

  appState.subscribe(render);

  // Handle streaming deltas
  let streamingEl: HTMLElement | null = null;
  let thinkingEl: HTMLElement | null = null;

  window.addEventListener("agent-delta", ((e: CustomEvent) => {
    const { kind, text } = e.detail;

    if (kind === "thinking") {
      if (!thinkingEl) {
        thinkingEl = document.createElement("div");
        thinkingEl.className = "message thinking";
        pane.appendChild(thinkingEl);
      }
      thinkingEl.textContent += text;
      pane.scrollTop = pane.scrollHeight;
    } else if (kind === "text") {
      // Transition from thinking to streaming
      if (thinkingEl) {
        thinkingEl = null;
      }
      if (!streamingEl) {
        streamingEl = document.createElement("div");
        streamingEl.className = "message assistant streaming";
        pane.appendChild(streamingEl);
      }
      streamingEl.textContent += text;
      pane.scrollTop = pane.scrollHeight;
    } else if (kind === "tool_call_start") {
      // Finalize previous stream
      thinkingEl = null;
      streamingEl = null;
      const toolEl = document.createElement("div");
      toolEl.className = "tool-tree-line";
      const fn = document.createElement("span");
      fn.className = "tool-fn";
      fn.textContent = text;
      toolEl.appendChild(fn);
      pane.appendChild(toolEl);
      pane.scrollTop = pane.scrollHeight;
    } else if (kind === "tool_call_args") {
      // Append args to last tool tree line
      const lastTool = pane.querySelector(".tool-tree-line:last-child");
      if (lastTool) {
        let argSpan = lastTool.querySelector(".tool-arg");
        if (!argSpan) {
          argSpan = document.createElement("span");
          argSpan.className = "tool-arg";
          lastTool.appendChild(argSpan);
        }
        argSpan.textContent += text;
      }
    }
  }) as EventListener);

  // When complete event fires, clear streaming elements
  appState.subscribe(() => {
    if (!appState.get().isRunning) {
      if (streamingEl) {
        streamingEl.classList.remove("streaming");
        streamingEl = null;
      }
      thinkingEl = null;
    }
  });

  // Clear pane DOM when session changes
  window.addEventListener("session-changed", () => {
    pane.innerHTML = "";
    renderedCount = 0;
    streamingEl = null;
    thinkingEl = null;
  });

  return pane;
}

export { KEY_ARGS };
