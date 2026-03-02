// @vitest-environment happy-dom
import { vi, describe, it, expect, beforeEach, afterEach } from "vitest";

vi.mock("@tauri-apps/api/core", async () => {
  const mock = await import("../__mocks__/tauri");
  return { invoke: mock.invoke };
});

vi.mock("./InputBar", () => ({
  createInputBar: () => {
    const el = document.createElement("div");
    el.className = "input-bar";
    return el;
  },
}));

import { appState, type ChatMessage } from "../state/store";
import { createChatPane, KEY_ARGS } from "./ChatPane";

function makeMsg(overrides: Partial<ChatMessage> & { role: ChatMessage["role"]; content: string }): ChatMessage {
  return {
    id: crypto.randomUUID(),
    timestamp: Date.now(),
    ...overrides,
  };
}

describe("KEY_ARGS", () => {
  it("maps tool names to argument keys", () => {
    expect(KEY_ARGS["read_file"]).toBe("path");
    expect(KEY_ARGS["run_shell"]).toBe("command");
    expect(KEY_ARGS["web_search"]).toBe("query");
    expect(KEY_ARGS["fetch_url"]).toBe("url");
  });
});

describe("createChatPane", () => {
  const originalState = appState.get();

  beforeEach(() => {
    appState.set({ ...originalState, messages: [] });
  });

  afterEach(() => {
    appState.set(originalState);
  });

  it("creates element with correct class", () => {
    const pane = createChatPane();
    expect(pane.className).toBe("chat-pane");
  });

  it("renders user message", () => {
    const pane = createChatPane();
    appState.update((s) => ({
      ...s,
      messages: [makeMsg({ role: "user", content: "hello world" })],
    }));
    const msg = pane.querySelector(".message.user");
    expect(msg).not.toBeNull();
    expect(msg!.textContent).toBe("hello world");
  });

  it("renders system message", () => {
    const pane = createChatPane();
    appState.update((s) => ({
      ...s,
      messages: [makeMsg({ role: "system", content: "system info" })],
    }));
    const msg = pane.querySelector(".message.system");
    expect(msg).not.toBeNull();
    expect(msg!.textContent).toBe("system info");
  });

  it("renders splash message", () => {
    const pane = createChatPane();
    appState.update((s) => ({
      ...s,
      messages: [makeMsg({ role: "splash", content: "SPLASH ART" })],
    }));
    const msg = pane.querySelector(".message.splash");
    expect(msg).not.toBeNull();
    expect(msg!.textContent).toBe("SPLASH ART");
  });

  it("renders step-header message", () => {
    const pane = createChatPane();
    appState.update((s) => ({
      ...s,
      messages: [makeMsg({ role: "step-header", content: "--- Step 1 ---" })],
    }));
    const msg = pane.querySelector(".message.step-header");
    expect(msg).not.toBeNull();
    expect(msg!.textContent).toBe("--- Step 1 ---");
  });

  it("renders thinking message", () => {
    const pane = createChatPane();
    appState.update((s) => ({
      ...s,
      messages: [makeMsg({ role: "thinking", content: "pondering..." })],
    }));
    const msg = pane.querySelector(".message.thinking");
    expect(msg).not.toBeNull();
    expect(msg!.textContent).toBe("pondering...");
  });

  it("renders assistant message as plain text when not rendered", () => {
    const pane = createChatPane();
    appState.update((s) => ({
      ...s,
      messages: [makeMsg({ role: "assistant", content: "streaming text", isRendered: false })],
    }));
    const msg = pane.querySelector(".message.assistant");
    expect(msg).not.toBeNull();
    expect(msg!.textContent).toBe("streaming text");
    expect(msg!.classList.contains("rendered")).toBe(false);
  });

  it("renders assistant message as markdown when isRendered", () => {
    const pane = createChatPane();
    appState.update((s) => ({
      ...s,
      messages: [makeMsg({ role: "assistant", content: "**bold text**", isRendered: true })],
    }));
    const msg = pane.querySelector(".message.assistant.rendered");
    expect(msg).not.toBeNull();
    expect(msg!.innerHTML).toContain("<strong>");
    expect(msg!.innerHTML).toContain("bold text");
  });

  it("renders tool message with tool name label", () => {
    const pane = createChatPane();
    appState.update((s) => ({
      ...s,
      messages: [makeMsg({ role: "tool", content: "file contents here", toolName: "read_file" })],
    }));
    const msg = pane.querySelector(".message.tool");
    expect(msg).not.toBeNull();
    const label = msg!.querySelector(".tool-name");
    expect(label).not.toBeNull();
    expect(label!.textContent).toBe("read_file");
  });

  it("renders tool-tree message with tool calls", () => {
    const pane = createChatPane();
    appState.update((s) => ({
      ...s,
      messages: [
        makeMsg({
          role: "tool-tree",
          content: "",
          toolCalls: [
            { name: "read_file", args: "/src/main.ts" },
            { name: "run_shell", args: "ls -la" },
          ],
        }),
      ],
    }));
    const lines = pane.querySelectorAll(".tool-tree-line");
    expect(lines.length).toBe(2);
    expect(lines[0].querySelector(".tool-fn")!.textContent).toBe("read_file");
    expect(lines[0].querySelector(".tool-arg")!.textContent).toBe(" /src/main.ts");
    expect(lines[1].querySelector(".tool-fn")!.textContent).toBe("run_shell");
  });

  it("renders tool-tree fallback when no toolCalls", () => {
    const pane = createChatPane();
    appState.update((s) => ({
      ...s,
      messages: [makeMsg({ role: "tool-tree", content: "fallback text" })],
    }));
    const msg = pane.querySelector(".message.tool-tree");
    expect(msg!.textContent).toBe("fallback text");
  });

  it("renders multiple messages in order", () => {
    const pane = createChatPane();
    appState.update((s) => ({
      ...s,
      messages: [
        makeMsg({ role: "user", content: "first" }),
        makeMsg({ role: "assistant", content: "second" }),
        makeMsg({ role: "system", content: "third" }),
      ],
    }));
    const msgs = pane.querySelectorAll(".message");
    expect(msgs.length).toBe(3);
    expect(msgs[0].textContent).toBe("first");
    expect(msgs[1].textContent).toBe("second");
    expect(msgs[2].textContent).toBe("third");
  });

  it("incrementally renders new messages", () => {
    const pane = createChatPane();
    appState.update((s) => ({
      ...s,
      messages: [makeMsg({ role: "user", content: "msg1" })],
    }));
    expect(pane.querySelectorAll(".message").length).toBe(1);

    appState.update((s) => ({
      ...s,
      messages: [...s.messages, makeMsg({ role: "assistant", content: "msg2" })],
    }));
    expect(pane.querySelectorAll(".message").length).toBe(2);
  });

  // ── Activity indicator tests ──

  it("shows activity indicator on thinking delta", () => {
    const pane = createChatPane();
    document.body.appendChild(pane);

    window.dispatchEvent(
      new CustomEvent("agent-delta", { detail: { kind: "thinking", text: "analyzing..." } })
    );

    const indicator = pane.querySelector(".activity-indicator");
    expect(indicator).not.toBeNull();
    expect(indicator!.getAttribute("data-mode")).toBe("thinking");
    expect(pane.querySelector(".activity-label")!.textContent).toBe("Thinking...");

    document.body.removeChild(pane);
  });

  it("transitions activity indicator from thinking to streaming on text delta", () => {
    const pane = createChatPane();
    document.body.appendChild(pane);

    // Start with thinking
    window.dispatchEvent(
      new CustomEvent("agent-delta", { detail: { kind: "thinking", text: "hmm" } })
    );
    expect(pane.querySelector(".activity-indicator")!.getAttribute("data-mode")).toBe("thinking");

    // Transition to text
    window.dispatchEvent(
      new CustomEvent("agent-delta", { detail: { kind: "text", text: "answer" } })
    );
    expect(pane.querySelector(".activity-indicator")!.getAttribute("data-mode")).toBe("streaming");
    expect(pane.querySelector(".activity-label")!.textContent).toBe("Responding...");

    document.body.removeChild(pane);
  });

  it("shows activity indicator in tool_args mode on tool_call_start", () => {
    const pane = createChatPane();
    document.body.appendChild(pane);

    window.dispatchEvent(
      new CustomEvent("agent-delta", { detail: { kind: "tool_call_start", text: "read_file" } })
    );

    const indicator = pane.querySelector(".activity-indicator");
    expect(indicator).not.toBeNull();
    expect(indicator!.getAttribute("data-mode")).toBe("tool_args");
    expect(pane.querySelector(".activity-label")!.textContent).toBe("Generating read_file...");

    document.body.removeChild(pane);
  });

  it("transitions to tool mode when key arg is extracted", () => {
    const pane = createChatPane();
    document.body.appendChild(pane);

    window.dispatchEvent(
      new CustomEvent("agent-delta", { detail: { kind: "tool_call_start", text: "read_file" } })
    );
    window.dispatchEvent(
      new CustomEvent("agent-delta", { detail: { kind: "tool_call_args", text: '{"path": "/src/main.ts"}' } })
    );

    const indicator = pane.querySelector(".activity-indicator");
    expect(indicator!.getAttribute("data-mode")).toBe("tool");
    expect(pane.querySelector(".activity-label")!.textContent).toBe("Running read_file...");
    expect(pane.querySelector(".activity-preview")!.textContent).toBe("/src/main.ts");

    document.body.removeChild(pane);
  });

  it("renders step summary on agent-step event", () => {
    const pane = createChatPane();
    document.body.appendChild(pane);

    // Simulate some streaming
    window.dispatchEvent(
      new CustomEvent("agent-delta", { detail: { kind: "text", text: "The answer is 42." } })
    );
    window.dispatchEvent(
      new CustomEvent("agent-delta", { detail: { kind: "tool_call_start", text: "read_file" } })
    );
    window.dispatchEvent(
      new CustomEvent("agent-delta", { detail: { kind: "tool_call_args", text: '{"path": "/src/main.ts"}' } })
    );

    // Fire step event
    window.dispatchEvent(
      new CustomEvent("agent-step", {
        detail: {
          step: 1,
          depth: 0,
          tokens: { input_tokens: 12300, output_tokens: 2100 },
          elapsed_ms: 5000,
          is_final: false,
          tool_name: null,
        },
      })
    );

    // Activity indicator should be removed
    expect(pane.querySelector(".activity-indicator")).toBeNull();

    // Step summary should be rendered
    const summary = pane.querySelector(".message.step-summary");
    expect(summary).not.toBeNull();

    const header = summary!.querySelector(".step-header-line");
    expect(header).not.toBeNull();
    expect(header!.textContent).toContain("Step 1");
    expect(header!.textContent).toContain("12.3k in");
    expect(header!.textContent).toContain("2.1k out");

    // Model text preview
    const modelText = summary!.querySelector(".step-model-text");
    expect(modelText).not.toBeNull();
    expect(modelText!.textContent).toContain("The answer is 42.");

    // Tool tree
    const toolLines = summary!.querySelectorAll(".step-tool-line");
    expect(toolLines.length).toBe(1);
    expect(toolLines[0].querySelector(".tool-fn")!.textContent).toBe("read_file");
    expect(toolLines[0].querySelector(".tool-arg")!.textContent).toContain("/src/main.ts");

    document.body.removeChild(pane);
  });

  it("removes activity indicator on complete (isRunning false)", () => {
    const pane = createChatPane();
    document.body.appendChild(pane);

    // Start streaming
    appState.update((s) => ({ ...s, isRunning: true }));
    window.dispatchEvent(
      new CustomEvent("agent-delta", { detail: { kind: "text", text: "streaming" } })
    );
    expect(pane.querySelector(".activity-indicator")).not.toBeNull();

    // Complete
    appState.update((s) => ({ ...s, isRunning: false }));
    expect(pane.querySelector(".activity-indicator")).toBeNull();

    document.body.removeChild(pane);
  });

  it("clears pane on session-changed event", () => {
    const pane = createChatPane();
    document.body.appendChild(pane);

    appState.update((s) => ({
      ...s,
      messages: [makeMsg({ role: "user", content: "old message" })],
    }));
    expect(pane.querySelectorAll(".message").length).toBe(1);

    window.dispatchEvent(new CustomEvent("session-changed"));
    const messagesContainer = pane.querySelector(".chat-messages")!;
    expect(messagesContainer.innerHTML).toBe("");

    document.body.removeChild(pane);
  });

  // ── Tool XML rendering in assistant messages ──

  it("renders tool_call XML as styled block in rendered assistant message", () => {
    const pane = createChatPane();
    const content = `Some intro text.

<tool_call>
{"name": "run_shell", "arguments": {"command": "echo hello"}}
</tool_call>

Trailing text.`;
    appState.update((s) => ({
      ...s,
      messages: [makeMsg({ role: "assistant", content, isRendered: true })],
    }));
    const msg = pane.querySelector(".message.assistant.rendered");
    expect(msg).not.toBeNull();
    // Should have a tool-call-block element
    const toolBlock = msg!.querySelector(".tool-call-block");
    expect(toolBlock).not.toBeNull();
    expect(toolBlock!.querySelector(".tool-fn")!.textContent).toBe("run_shell");
    expect(toolBlock!.querySelector(".tool-arg")!.textContent).toContain("echo hello");
    // Should NOT contain raw XML tags as text
    expect(msg!.textContent).not.toContain("<tool_call>");
  });

  it("renders tool_result XML as collapsible block in rendered assistant message", () => {
    const pane = createChatPane();
    const content = `<tool_result>
{"stdout": "hello\\nworld", "stderr": "", "returncode": 0}
</tool_result>`;
    appState.update((s) => ({
      ...s,
      messages: [makeMsg({ role: "assistant", content, isRendered: true })],
    }));
    const msg = pane.querySelector(".message.assistant.rendered");
    expect(msg).not.toBeNull();
    const resultBlock = msg!.querySelector(".tool-result-block");
    expect(resultBlock).not.toBeNull();
    expect(resultBlock!.textContent).toContain("hello");
    expect(resultBlock!.textContent).toContain("world");
  });

  it("renders tool_result with error styling when returncode != 0", () => {
    const pane = createChatPane();
    const content = `<tool_result>
{"stdout": "", "stderr": "command not found", "returncode": 127}
</tool_result>`;
    appState.update((s) => ({
      ...s,
      messages: [makeMsg({ role: "assistant", content, isRendered: true })],
    }));
    const msg = pane.querySelector(".message.assistant.rendered");
    const resultBlock = msg!.querySelector(".tool-result-block");
    expect(resultBlock).not.toBeNull();
    expect(resultBlock!.classList.contains("has-error")).toBe(true);
  });

  it("renders plain markdown for assistant message with no tool XML (fast path)", () => {
    const pane = createChatPane();
    appState.update((s) => ({
      ...s,
      messages: [makeMsg({ role: "assistant", content: "Just **markdown** text.", isRendered: true })],
    }));
    const msg = pane.querySelector(".message.assistant.rendered");
    expect(msg).not.toBeNull();
    expect(msg!.innerHTML).toContain("<strong>");
    // No tool blocks
    expect(msg!.querySelector(".tool-call-block")).toBeNull();
    expect(msg!.querySelector(".tool-result-block")).toBeNull();
  });

  it("strips tool XML from step summary model preview", () => {
    const pane = createChatPane();
    const previewWithXml = `Checking workspace...\n\n<tool_call>\n{"name":"run_shell","arguments":{"command":"ls"}}\n</tool_call>\n\n<tool_result>\n{"stdout":"file.txt","stderr":"","returncode":0}\n</tool_result>\n\nAll good.`;
    appState.update((s) => ({
      ...s,
      messages: [
        makeMsg({
          role: "step-summary",
          content: "",
          stepNumber: 1,
          stepTokensIn: 1000,
          stepTokensOut: 500,
          stepElapsed: 1000,
          stepModelPreview: previewWithXml,
          stepToolCalls: [],
        }),
      ],
    }));
    const summary = pane.querySelector(".message.step-summary");
    const modelText = summary!.querySelector(".step-model-text");
    expect(modelText).not.toBeNull();
    expect(modelText!.textContent).toContain("Checking workspace");
    expect(modelText!.textContent).toContain("All good");
    expect(modelText!.textContent).not.toContain("<tool_call>");
    expect(modelText!.textContent).not.toContain("<tool_result>");
  });

  it("hides step model preview when only tool XML (no prose)", () => {
    const pane = createChatPane();
    const onlyXml = `<tool_call>\n{"name":"run_shell","arguments":{"command":"ls"}}\n</tool_call>\n\n<tool_result>\n{"stdout":"ok","stderr":"","returncode":0}\n</tool_result>`;
    appState.update((s) => ({
      ...s,
      messages: [
        makeMsg({
          role: "step-summary",
          content: "",
          stepNumber: 1,
          stepTokensIn: 1000,
          stepTokensOut: 500,
          stepElapsed: 1000,
          stepModelPreview: onlyXml,
          stepToolCalls: [],
        }),
      ],
    }));
    const summary = pane.querySelector(".message.step-summary");
    // No model text preview since stripped content is empty
    const modelText = summary!.querySelector(".step-model-text");
    expect(modelText).toBeNull();
  });

  it("strips tool XML from streaming activity preview", () => {
    const pane = createChatPane();
    document.body.appendChild(pane);

    window.dispatchEvent(
      new CustomEvent("agent-delta", { detail: { kind: "text", text: "Starting...\n\n<tool_call>\n{\"name\":\"x\"}\n</tool_call>" } })
    );

    const preview = pane.querySelector(".activity-preview");
    expect(preview).not.toBeNull();
    expect(preview!.textContent).toContain("Starting...");
    expect(preview!.textContent).not.toContain("<tool_call>");

    document.body.removeChild(pane);
  });

  // ── Step summary rendering tests ──

  it("renders step-summary message from state", () => {
    const pane = createChatPane();
    appState.update((s) => ({
      ...s,
      messages: [
        makeMsg({
          role: "step-summary",
          content: "",
          stepNumber: 2,
          stepTokensIn: 5000,
          stepTokensOut: 1500,
          stepElapsed: 3200,
          stepModelPreview: "Some model output text",
          stepToolCalls: [
            { name: "read_file", keyArg: "/src/app.ts", elapsed: 800 },
            { name: "run_shell", keyArg: "npm test", elapsed: 2400 },
          ],
        }),
      ],
    }));

    const summary = pane.querySelector(".message.step-summary");
    expect(summary).not.toBeNull();

    const header = summary!.querySelector(".step-header-line");
    expect(header!.textContent).toContain("Step 2");
    expect(header!.textContent).toContain("5.0k in");
    expect(header!.textContent).toContain("1.5k out");

    const toolLines = summary!.querySelectorAll(".step-tool-line");
    expect(toolLines.length).toBe(2);
    // First tool line uses ├─ connector
    expect(toolLines[0].textContent).toContain("read_file");
    expect(toolLines[0].textContent).toContain("/src/app.ts");
    // Last tool line uses └─ connector and has .last class
    expect(toolLines[1].classList.contains("last")).toBe(true);
    expect(toolLines[1].textContent).toContain("run_shell");
    expect(toolLines[1].textContent).toContain("npm test");
  });
});
