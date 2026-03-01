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

  it("handles streaming text delta", () => {
    const pane = createChatPane();
    document.body.appendChild(pane);

    window.dispatchEvent(
      new CustomEvent("agent-delta", { detail: { kind: "text", text: "Hello " } })
    );
    window.dispatchEvent(
      new CustomEvent("agent-delta", { detail: { kind: "text", text: "world" } })
    );

    const streaming = pane.querySelector(".message.assistant.streaming");
    expect(streaming).not.toBeNull();
    expect(streaming!.textContent).toBe("Hello world");

    document.body.removeChild(pane);
  });

  it("handles streaming thinking delta", () => {
    const pane = createChatPane();
    document.body.appendChild(pane);

    window.dispatchEvent(
      new CustomEvent("agent-delta", { detail: { kind: "thinking", text: "thinking..." } })
    );

    const thinking = pane.querySelector(".message.thinking");
    expect(thinking).not.toBeNull();
    expect(thinking!.textContent).toBe("thinking...");

    document.body.removeChild(pane);
  });

  it("transitions from thinking to text stream", () => {
    const pane = createChatPane();
    document.body.appendChild(pane);

    // Start with thinking
    window.dispatchEvent(
      new CustomEvent("agent-delta", { detail: { kind: "thinking", text: "hmm" } })
    );
    expect(pane.querySelector(".message.thinking")).not.toBeNull();

    // Transition to text
    window.dispatchEvent(
      new CustomEvent("agent-delta", { detail: { kind: "text", text: "answer" } })
    );
    const streaming = pane.querySelector(".message.assistant.streaming");
    expect(streaming).not.toBeNull();
    expect(streaming!.textContent).toBe("answer");

    document.body.removeChild(pane);
  });

  it("handles tool_call_start delta", () => {
    const pane = createChatPane();
    document.body.appendChild(pane);

    window.dispatchEvent(
      new CustomEvent("agent-delta", { detail: { kind: "tool_call_start", text: "read_file" } })
    );

    const toolLine = pane.querySelector(".tool-tree-line");
    expect(toolLine).not.toBeNull();
    expect(toolLine!.querySelector(".tool-fn")!.textContent).toBe("read_file");

    document.body.removeChild(pane);
  });

  it("handles tool_call_args delta", () => {
    const pane = createChatPane();
    document.body.appendChild(pane);

    // First create a tool call
    window.dispatchEvent(
      new CustomEvent("agent-delta", { detail: { kind: "tool_call_start", text: "read_file" } })
    );
    // Then add args
    window.dispatchEvent(
      new CustomEvent("agent-delta", { detail: { kind: "tool_call_args", text: "/src" } })
    );
    window.dispatchEvent(
      new CustomEvent("agent-delta", { detail: { kind: "tool_call_args", text: "/main.ts" } })
    );

    const argSpan = pane.querySelector(".tool-tree-line .tool-arg");
    expect(argSpan).not.toBeNull();
    expect(argSpan!.textContent).toBe("/src/main.ts");

    document.body.removeChild(pane);
  });

  it("clears streaming on complete (isRunning false)", () => {
    const pane = createChatPane();
    document.body.appendChild(pane);

    // Start streaming
    appState.update((s) => ({ ...s, isRunning: true }));
    window.dispatchEvent(
      new CustomEvent("agent-delta", { detail: { kind: "text", text: "streaming" } })
    );
    expect(pane.querySelector(".streaming")).not.toBeNull();

    // Complete
    appState.update((s) => ({ ...s, isRunning: false }));
    expect(pane.querySelector(".streaming")).toBeNull();

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
});
