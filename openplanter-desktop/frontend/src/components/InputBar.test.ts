// @vitest-environment happy-dom
import { vi, describe, it, expect, beforeEach, afterEach } from "vitest";
import { __setHandler, __clearHandlers } from "../__mocks__/tauri";

vi.mock("@tauri-apps/api/core", async () => {
  const mock = await import("../__mocks__/tauri");
  return { invoke: mock.invoke };
});

import { appState } from "../state/store";
import { createInputBar } from "./InputBar";

// Mock crypto.randomUUID for deterministic IDs
let uuidCounter = 0;
vi.stubGlobal("crypto", {
  randomUUID: () => `uuid-${++uuidCounter}`,
});

describe("createInputBar", () => {
  const originalState = appState.get();

  beforeEach(() => {
    uuidCounter = 0;
    appState.set({ ...originalState, messages: [], inputHistory: [], inputQueue: [] });
    // Default handlers to prevent unhandled rejection
    __setHandler("solve", () => {});
    __setHandler("cancel", () => {});
    __setHandler("open_session", () => ({
      id: "20260227-100000-abcd1234",
      created_at: "2026-02-27T10:00:00Z",
      turn_count: 0,
      last_objective: null,
    }));
  });

  afterEach(() => {
    __clearHandlers();
    appState.set(originalState);
  });

  it("creates element with correct class", () => {
    const bar = createInputBar();
    expect(bar.className).toBe("input-bar");
  });

  it("has textarea, send button, and cancel button", () => {
    const bar = createInputBar();
    const textarea = bar.querySelector("textarea");
    const buttons = bar.querySelectorAll("button");
    expect(textarea).not.toBeNull();
    expect(buttons.length).toBe(2);
    expect(buttons[0].textContent).toBe("Send");
    expect(buttons[1].textContent).toBe("Cancel");
  });

  it("textarea has correct placeholder", () => {
    const bar = createInputBar();
    const textarea = bar.querySelector("textarea")!;
    expect(textarea.placeholder).toBe("Enter objective or /command...");
  });

  it("cancel button is hidden by default", () => {
    const bar = createInputBar();
    const cancelBtn = bar.querySelectorAll("button")[1];
    expect(cancelBtn.style.display).toBe("none");
  });

  it("shows cancel button and hides send when running", () => {
    const bar = createInputBar();
    const sendBtn = bar.querySelectorAll("button")[0];
    const cancelBtn = bar.querySelectorAll("button")[1];

    appState.update((s) => ({ ...s, isRunning: true }));
    expect(sendBtn.style.display).toBe("none");
    expect(cancelBtn.style.display).toBe("");
  });

  it("changes placeholder when running", () => {
    const bar = createInputBar();
    const textarea = bar.querySelector("textarea")!;

    appState.update((s) => ({ ...s, isRunning: true }));
    expect(textarea.placeholder).toBe("Type to queue...");
  });

  it("submit clears textarea and sets isRunning", async () => {
    const bar = createInputBar();
    document.body.appendChild(bar);
    const textarea = bar.querySelector("textarea")!;
    const sendBtn = bar.querySelectorAll("button")[0];

    textarea.value = "solve this";
    sendBtn.click();

    // Wait for async handling
    await vi.waitFor(() => {
      expect(textarea.value).toBe("");
      expect(appState.get().isRunning).toBe(true);
    });

    document.body.removeChild(bar);
  });

  it("submit adds user message to state", async () => {
    const bar = createInputBar();
    document.body.appendChild(bar);
    const textarea = bar.querySelector("textarea")!;
    const sendBtn = bar.querySelectorAll("button")[0];

    textarea.value = "my objective";
    sendBtn.click();

    await vi.waitFor(() => {
      const msgs = appState.get().messages;
      expect(msgs.length).toBeGreaterThan(0);
      const userMsg = msgs.find((m) => m.role === "user");
      expect(userMsg).toBeDefined();
      expect(userMsg!.content).toBe("my objective");
    });

    document.body.removeChild(bar);
  });

  it("submit calls solve via invoke", async () => {
    let solvedObjective = "";
    __setHandler("solve", ({ objective }: any) => {
      solvedObjective = objective;
    });

    const bar = createInputBar();
    document.body.appendChild(bar);
    const textarea = bar.querySelector("textarea")!;

    textarea.value = "test objective";
    bar.querySelectorAll("button")[0].click();

    await vi.waitFor(() => {
      expect(solvedObjective).toBe("test objective");
    });

    document.body.removeChild(bar);
  });

  it("empty submit does nothing", () => {
    const bar = createInputBar();
    const textarea = bar.querySelector("textarea")!;

    textarea.value = "";
    bar.querySelectorAll("button")[0].click();

    expect(appState.get().isRunning).toBe(false);
    expect(appState.get().messages.length).toBe(0);
  });

  it("whitespace-only submit does nothing", () => {
    const bar = createInputBar();
    const textarea = bar.querySelector("textarea")!;

    textarea.value = "   ";
    bar.querySelectorAll("button")[0].click();

    expect(appState.get().isRunning).toBe(false);
  });

  it("cancel button calls cancel", async () => {
    let cancelCalled = false;
    __setHandler("cancel", () => {
      cancelCalled = true;
    });

    const bar = createInputBar();
    document.body.appendChild(bar);
    appState.update((s) => ({ ...s, isRunning: true }));

    const cancelBtn = bar.querySelectorAll("button")[1];
    cancelBtn.click();

    await vi.waitFor(() => {
      expect(cancelCalled).toBe(true);
    });

    document.body.removeChild(bar);
  });

  it("adds input to history on submit", async () => {
    const bar = createInputBar();
    document.body.appendChild(bar);
    const textarea = bar.querySelector("textarea")!;

    textarea.value = "first command";
    bar.querySelectorAll("button")[0].click();

    await vi.waitFor(() => {
      expect(appState.get().inputHistory).toContain("first command");
    });

    document.body.removeChild(bar);
  });

  it("deduplicates history entries", async () => {
    appState.update((s) => ({ ...s, inputHistory: ["old command"] }));

    const bar = createInputBar();
    document.body.appendChild(bar);
    const textarea = bar.querySelector("textarea")!;

    textarea.value = "old command";
    bar.querySelectorAll("button")[0].click();

    await vi.waitFor(() => {
      const hist = appState.get().inputHistory;
      expect(hist.filter((h) => h === "old command").length).toBe(1);
      expect(hist[0]).toBe("old command");
    });

    document.body.removeChild(bar);
  });

  it("queues input when running", async () => {
    appState.update((s) => ({ ...s, isRunning: true }));

    const bar = createInputBar();
    document.body.appendChild(bar);
    const textarea = bar.querySelector("textarea")!;

    textarea.value = "queued task";
    bar.querySelectorAll("button")[0].click();

    await vi.waitFor(() => {
      expect(appState.get().inputQueue).toContain("queued task");
      const msgs = appState.get().messages;
      expect(msgs.some((m) => m.content.includes("Queued:"))).toBe(true);
    });

    document.body.removeChild(bar);
  });

  it("slash command dispatches without setting isRunning", async () => {
    const bar = createInputBar();
    document.body.appendChild(bar);
    const textarea = bar.querySelector("textarea")!;

    textarea.value = "/help";
    bar.querySelectorAll("button")[0].click();

    await vi.waitFor(() => {
      expect(appState.get().isRunning).toBe(false);
      const msgs = appState.get().messages;
      expect(msgs.some((m) => m.content.includes("Available commands"))).toBe(true);
    });

    document.body.removeChild(bar);
  });

  it("/clear command clears messages", async () => {
    appState.update((s) => ({
      ...s,
      messages: [{ id: "1", role: "user" as const, content: "old", timestamp: 0 }],
    }));

    const bar = createInputBar();
    document.body.appendChild(bar);
    const textarea = bar.querySelector("textarea")!;

    textarea.value = "/clear";
    bar.querySelectorAll("button")[0].click();

    await vi.waitFor(() => {
      expect(appState.get().messages.length).toBe(0);
    });

    document.body.removeChild(bar);
  });

  it("Enter key triggers submit", async () => {
    const bar = createInputBar();
    document.body.appendChild(bar);
    const textarea = bar.querySelector("textarea")!;

    textarea.value = "enter submit";
    textarea.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter" }));

    await vi.waitFor(() => {
      expect(appState.get().isRunning).toBe(true);
    });

    document.body.removeChild(bar);
  });

  it("Shift+Enter does not submit", () => {
    const bar = createInputBar();
    const textarea = bar.querySelector("textarea")!;

    textarea.value = "no submit";
    textarea.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", shiftKey: true }));

    expect(appState.get().isRunning).toBe(false);
  });

  it("Escape triggers cancel", async () => {
    let cancelCalled = false;
    __setHandler("cancel", () => {
      cancelCalled = true;
    });

    const bar = createInputBar();
    document.body.appendChild(bar);
    const textarea = bar.querySelector("textarea")!;

    textarea.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));

    await vi.waitFor(() => {
      expect(cancelCalled).toBe(true);
    });

    document.body.removeChild(bar);
  });

  it("creates session lazily on first submit", async () => {
    let sessionCreated = false;
    __setHandler("open_session", () => {
      sessionCreated = true;
      return {
        id: "new-session-id",
        created_at: "2026-02-27T10:00:00Z",
        turn_count: 0,
        last_objective: null,
      };
    });

    appState.update((s) => ({ ...s, sessionId: null }));

    const bar = createInputBar();
    document.body.appendChild(bar);
    const textarea = bar.querySelector("textarea")!;

    textarea.value = "first message";
    bar.querySelectorAll("button")[0].click();

    await vi.waitFor(() => {
      expect(sessionCreated).toBe(true);
      expect(appState.get().sessionId).toBe("new-session-id");
    });

    document.body.removeChild(bar);
  });

  it("handles solve error gracefully", async () => {
    __setHandler("solve", () => {
      throw new Error("API unreachable");
    });

    const bar = createInputBar();
    document.body.appendChild(bar);
    const textarea = bar.querySelector("textarea")!;

    textarea.value = "will fail";
    bar.querySelectorAll("button")[0].click();

    await vi.waitFor(() => {
      expect(appState.get().isRunning).toBe(false);
      const msgs = appState.get().messages;
      expect(msgs.some((m) => m.content.includes("Failed to start"))).toBe(true);
    });

    document.body.removeChild(bar);
  });

  it("handles queued-submit custom event", async () => {
    let solvedText = "";
    __setHandler("solve", ({ objective }: any) => {
      solvedText = objective;
    });

    const bar = createInputBar();
    document.body.appendChild(bar);

    window.dispatchEvent(
      new CustomEvent("queued-submit", { detail: { text: "queued objective" } })
    );

    await vi.waitFor(() => {
      expect(solvedText).toBe("queued objective");
      expect(appState.get().isRunning).toBe(true);
    });

    document.body.removeChild(bar);
  });
});
