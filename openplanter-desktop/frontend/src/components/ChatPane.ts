/** Chat pane: terminal-style messages, streaming, markdown rendering. */
import { appState, type ChatMessage, type StepToolCall } from "../state/store";
import { createInputBar } from "./InputBar";
import { parseAgentContent, stripToolXml, type ContentSegment } from "./contentParser";
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

/** Extract the key argument value from a partial JSON string. */
function extractKeyArg(toolName: string, argsJson: string): string | null {
  const keyName = KEY_ARGS[toolName];
  if (!keyName) return null;
  // Try to extract "keyName": "value" from possibly-incomplete JSON
  const regex = new RegExp(`"${keyName}"\\s*:\\s*"([^"]*)"?`);
  const m = argsJson.match(regex);
  return m ? m[1] : null;
}

/** Format elapsed milliseconds as a readable string. */
function formatElapsed(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

/** Get last N lines of text for preview. */
function lastLines(text: string, n: number): string {
  const lines = text.split("\n").filter((l) => l.trim());
  return lines.slice(-n).join("\n");
}

type ActivityMode = "thinking" | "streaming" | "tool_args" | "tool";

/**
 * Manages the transient activity indicator shown during streaming.
 * A single DOM element updated in-place, removed when the step completes.
 */
class ActivityIndicator {
  private el: HTMLElement;
  private iconEl: HTMLElement;
  private labelEl: HTMLElement;
  private elapsedEl: HTMLElement;
  private stepEl: HTMLElement;
  private previewEl: HTMLElement;
  private mode: ActivityMode = "thinking";
  private startTime: number = Date.now();
  private timerId: ReturnType<typeof setInterval> | null = null;

  constructor() {
    this.el = document.createElement("div");
    this.el.className = "activity-indicator";

    const row = document.createElement("div");
    row.className = "activity-row";

    this.iconEl = document.createElement("span");
    this.iconEl.className = "activity-icon";

    this.labelEl = document.createElement("span");
    this.labelEl.className = "activity-label";

    this.elapsedEl = document.createElement("span");
    this.elapsedEl.className = "activity-elapsed";

    this.stepEl = document.createElement("span");
    this.stepEl.className = "activity-step";

    row.appendChild(this.iconEl);
    row.appendChild(this.labelEl);
    row.appendChild(this.elapsedEl);
    row.appendChild(this.stepEl);

    this.previewEl = document.createElement("div");
    this.previewEl.className = "activity-preview";

    this.el.appendChild(row);
    this.el.appendChild(this.previewEl);

    this.setMode("thinking");
    this.startTimer();
  }

  get element(): HTMLElement {
    return this.el;
  }

  private startTimer() {
    this.startTime = Date.now();
    this.updateElapsed();
    this.timerId = setInterval(() => this.updateElapsed(), 100);
  }

  private updateElapsed() {
    const ms = Date.now() - this.startTime;
    this.elapsedEl.textContent = formatElapsed(ms);
  }

  setMode(mode: ActivityMode, toolName?: string) {
    this.mode = mode;
    this.el.dataset.mode = mode;
    switch (mode) {
      case "thinking":
        this.labelEl.textContent = "Thinking...";
        break;
      case "streaming":
        this.labelEl.textContent = "Responding...";
        break;
      case "tool_args":
        this.labelEl.textContent = `Generating ${toolName || "tool"}...`;
        break;
      case "tool":
        this.labelEl.textContent = `Running ${toolName || "tool"}...`;
        break;
    }
  }

  setStep(step: number) {
    this.stepEl.textContent = step > 0 ? `Step ${step}` : "";
  }

  setPreview(text: string) {
    this.previewEl.textContent = lastLines(text, 3);
  }

  /** Transition to tool mode with key arg as preview. */
  setToolRunning(toolName: string, keyArg: string) {
    this.setMode("tool", toolName);
    this.previewEl.textContent = keyArg;
  }

  destroy() {
    if (this.timerId !== null) {
      clearInterval(this.timerId);
      this.timerId = null;
    }
    this.el.remove();
  }
}

/** Render a tool call as a compact inline block: ├─ tool_name "key arg" */
function renderToolCallBlock(seg: Extract<ContentSegment, { type: "tool_call" }>): HTMLElement {
  const block = document.createElement("div");
  block.className = "tool-call-block";

  const connector = document.createTextNode("\u251C\u2500 ");
  block.appendChild(connector);

  const fn = document.createElement("span");
  fn.className = "tool-fn";
  fn.textContent = seg.name;
  block.appendChild(fn);

  if (seg.keyArg) {
    const arg = document.createElement("span");
    arg.className = "tool-arg";
    arg.textContent = ` "${seg.keyArg}"`;
    block.appendChild(arg);
  }

  return block;
}

/** Render a tool result as a collapsible output block. */
function renderToolResultBlock(seg: Extract<ContentSegment, { type: "tool_result" }>): HTMLElement {
  const wrapper = document.createElement("div");
  wrapper.className = "tool-result-wrapper";

  const output = seg.stdout || seg.stderr || "";
  const lines = output.split("\n").filter((l) => l !== "");
  const hasError = seg.stderr.length > 0 || (seg.returncode !== null && seg.returncode !== 0);
  const collapsible = lines.length > 4;

  // Toggle header
  const toggle = document.createElement("div");
  toggle.className = "tool-result-toggle";
  toggle.textContent = collapsible
    ? `\u25B6 Output (${lines.length} lines)`
    : `\u25BC Output`;
  wrapper.appendChild(toggle);

  // Output block
  const block = document.createElement("div");
  block.className = "tool-result-block";
  if (hasError) block.classList.add("has-error");
  if (collapsible) {
    // Collapsed by default
  } else {
    block.classList.add("expanded");
  }

  // Build content with │ prefix
  const prefixed = lines.map((l) => `\u2502 ${l}`).join("\n");
  block.textContent = prefixed;
  wrapper.appendChild(block);

  // Toggle click handler
  if (collapsible) {
    toggle.addEventListener("click", () => {
      const isExpanded = block.classList.toggle("expanded");
      toggle.textContent = isExpanded
        ? `\u25BC Output (${lines.length} lines)`
        : `\u25B6 Output (${lines.length} lines)`;
    });
  }

  return wrapper;
}

export function createChatPane(): HTMLElement {
  const pane = document.createElement("div");
  pane.className = "chat-pane";

  const messagesEl = document.createElement("div");
  messagesEl.className = "chat-messages";
  pane.appendChild(messagesEl);

  pane.appendChild(createInputBar());

  let renderedCount = 0;

  // ── Auto-scroll with proximity check ──
  function autoScroll() {
    // Don't scroll when only the splash message exists — prevents the
    // activity indicator from pushing the splash text out of view.
    const msgs = appState.get().messages;
    if (msgs.length > 0 && msgs.every((m) => m.role === "splash")) return;

    const isNearBottom =
      messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight < 40;
    if (isNearBottom) {
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }
  }

  // ── Streaming state ──
  let activity: ActivityIndicator | null = null;
  let thinkingBuf = "";
  let streamingBuf = "";
  let toolArgsBuf = "";
  let currentToolName = "";
  let stepToolCalls: { name: string; keyArg: string; startTime: number }[] = [];
  let stepStartTime = Date.now();

  function resetBuffers() {
    thinkingBuf = "";
    streamingBuf = "";
    toolArgsBuf = "";
    currentToolName = "";
    stepToolCalls = [];
    stepStartTime = Date.now();
  }

  function ensureActivity(): ActivityIndicator {
    if (!activity) {
      activity = new ActivityIndicator();
      const step = appState.get().currentStep;
      activity.setStep(step);
      messagesEl.appendChild(activity.element);
    }
    return activity;
  }

  function removeActivity() {
    if (activity) {
      activity.destroy();
      activity = null;
    }
  }

  // ── Message rendering (state-driven) ──

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

      case "step-summary":
        renderStepSummaryEl(el, msg);
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
          const segments = parseAgentContent(msg.content);
          if (segments.length === 1 && segments[0].type === "text") {
            // Fast path: no tool XML
            el.innerHTML = md.render(msg.content);
          } else {
            for (const seg of segments) {
              if (seg.type === "text" && seg.text.trim()) {
                const textEl = document.createElement("div");
                textEl.innerHTML = md.render(seg.text);
                el.appendChild(textEl);
              } else if (seg.type === "tool_call") {
                el.appendChild(renderToolCallBlock(seg));
              } else if (seg.type === "tool_result") {
                el.appendChild(renderToolResultBlock(seg));
              }
            }
          }
        } else {
          el.textContent = msg.content;
        }
        break;

      default:
        el.textContent = msg.content;
    }

    return el;
  }

  function renderStepSummaryEl(el: HTMLElement, msg: ChatMessage) {
    // Header line: timestamp  Step N  ·  Xk in / Yk out
    const header = document.createElement("div");
    header.className = "step-header-line";
    const ts = new Date(msg.timestamp);
    const timeStr = [
      ts.getHours().toString().padStart(2, "0"),
      ts.getMinutes().toString().padStart(2, "0"),
      ts.getSeconds().toString().padStart(2, "0"),
    ].join(":");
    const inK = ((msg.stepTokensIn || 0) / 1000).toFixed(1);
    const outK = ((msg.stepTokensOut || 0) / 1000).toFixed(1);
    header.textContent = `${timeStr}  Step ${msg.stepNumber || "?"}  ·  ${inK}k in / ${outK}k out`;
    el.appendChild(header);

    // Model text preview (if any)
    if (msg.stepModelPreview) {
      const cleanPreview = stripToolXml(msg.stepModelPreview);
      if (cleanPreview.trim()) {
        const preview = document.createElement("div");
        preview.className = "step-model-text";
        const elapsedStr = msg.stepElapsed ? `(${formatElapsed(msg.stepElapsed)}) ` : "";
        // Truncate to ~200 chars
        const truncated =
          cleanPreview.length > 200
            ? cleanPreview.slice(0, 200) + "..."
            : cleanPreview;
        preview.textContent = elapsedStr + truncated;
        el.appendChild(preview);
      }
    }

    // Tool tree
    const tools = msg.stepToolCalls;
    if (tools && tools.length > 0) {
      const tree = document.createElement("div");
      tree.className = "step-tool-tree";
      for (let i = 0; i < tools.length; i++) {
        const tc = tools[i];
        const isLast = i === tools.length - 1;
        const line = document.createElement("div");
        line.className = "step-tool-line";
        if (isLast) line.classList.add("last");

        const connector = isLast ? "\u2514\u2500 " : "\u251C\u2500 ";
        const fnSpan = document.createElement("span");
        fnSpan.className = "tool-fn";
        fnSpan.textContent = tc.name;

        const argSpan = document.createElement("span");
        argSpan.className = "tool-arg";
        argSpan.textContent = tc.keyArg ? ` "${tc.keyArg}"` : "";

        const elSpan = document.createElement("span");
        elSpan.className = "tool-elapsed";
        elSpan.textContent = tc.elapsed > 0 ? ` ${formatElapsed(tc.elapsed)}` : "";

        line.appendChild(document.createTextNode(connector));
        line.appendChild(fnSpan);
        line.appendChild(argSpan);
        line.appendChild(elSpan);
        tree.appendChild(line);
      }
      el.appendChild(tree);
    }
  }

  function render() {
    const messages = appState.get().messages;
    while (renderedCount < messages.length) {
      const msgEl = renderMessage(messages[renderedCount]);
      // Insert before activity indicator if it exists
      if (activity) {
        messagesEl.insertBefore(msgEl, activity.element);
      } else {
        messagesEl.appendChild(msgEl);
      }
      renderedCount++;
    }
    autoScroll();
  }

  appState.subscribe(render);

  // ── Handle streaming deltas ──

  window.addEventListener("agent-delta", ((e: CustomEvent) => {
    const { kind, text } = e.detail;

    if (kind === "thinking") {
      thinkingBuf += text;
      const ai = ensureActivity();
      ai.setMode("thinking");
      ai.setPreview(thinkingBuf);
      autoScroll();
    } else if (kind === "text") {
      // Transition from thinking to streaming
      if (thinkingBuf && !streamingBuf) {
        // First text delta after thinking — switch mode
      }
      streamingBuf += text;
      const ai = ensureActivity();
      ai.setMode("streaming");
      ai.setPreview(stripToolXml(streamingBuf));
      autoScroll();
    } else if (kind === "tool_call_start") {
      currentToolName = text;
      toolArgsBuf = "";
      stepToolCalls.push({
        name: text,
        keyArg: "",
        startTime: Date.now(),
      });

      const ai = ensureActivity();
      ai.setMode("tool_args", text);
      ai.setPreview("");
      autoScroll();
    } else if (kind === "tool_call_args") {
      toolArgsBuf += text;
      const ai = ensureActivity();

      // Always re-extract key arg as more chunks arrive — partial JSON
      // grows with each chunk so the extracted value gets more complete.
      const keyArg = extractKeyArg(currentToolName, toolArgsBuf);
      if (keyArg) {
        const current = stepToolCalls[stepToolCalls.length - 1];
        if (current) current.keyArg = keyArg;
        ai.setToolRunning(currentToolName, keyArg);
      } else {
        ai.setPreview(toolArgsBuf.slice(-120));
      }
      autoScroll();
    }
  }) as EventListener);

  // ── Handle step events — render step summary ──

  window.addEventListener("agent-step", ((e: CustomEvent) => {
    const event = e.detail;
    const now = Date.now();

    // Finalize elapsed times for tool calls in this step
    for (const tc of stepToolCalls) {
      if (tc.elapsed === undefined || tc.elapsed === 0) {
        (tc as any).elapsed = now - tc.startTime;
      }
    }

    // Build step summary tool calls
    const summaryTools: StepToolCall[] = stepToolCalls.map((tc) => ({
      name: tc.name,
      keyArg: tc.keyArg,
      elapsed: (tc as any).elapsed || now - tc.startTime,
    }));

    // Remove activity indicator
    removeActivity();

    // Create step summary message
    const stepElapsed = now - stepStartTime;
    const modelPreview = streamingBuf.trim();

    appState.update((s) => ({
      ...s,
      messages: [
        ...s.messages,
        {
          id: crypto.randomUUID(),
          role: "step-summary" as const,
          content: "",
          timestamp: now,
          stepNumber: event.step,
          stepTokensIn: event.tokens.input_tokens,
          stepTokensOut: event.tokens.output_tokens,
          stepElapsed: stepElapsed,
          stepToolCalls: summaryTools,
          stepModelPreview: modelPreview,
        },
      ],
    }));

    // Reset buffers for next step
    resetBuffers();
  }) as EventListener);

  // ── When complete event fires, clean up ──
  appState.subscribe(() => {
    if (!appState.get().isRunning) {
      removeActivity();
      resetBuffers();
    }
  });

  // ── Clear messages DOM when session changes ──
  window.addEventListener("session-changed", () => {
    messagesEl.innerHTML = "";
    renderedCount = 0;
    removeActivity();
    resetBuffers();
  });

  return pane;
}

export { KEY_ARGS };
