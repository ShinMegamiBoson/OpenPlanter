// @vitest-environment happy-dom
import { vi, describe, it, expect, beforeEach, afterEach } from "vitest";
import { __setHandler, __clearHandlers } from "../__mocks__/tauri";

vi.mock("@tauri-apps/api/core", async () => {
  const mock = await import("../__mocks__/tauri");
  return { invoke: mock.invoke };
});

// Mock sub-components that have heavy dependencies (markdown-it, three.js)
vi.mock("./StatusBar", () => ({
  createStatusBar: () => document.createElement("div"),
}));
vi.mock("./ChatPane", () => ({
  createChatPane: () => document.createElement("div"),
  KEY_ARGS: {},
}));
vi.mock("./GraphPane", () => ({
  createGraphPane: () => document.createElement("div"),
}));

import { appState } from "../state/store";
import { createApp } from "./App";

// Deterministic UUIDs
let uuidCounter = 0;
vi.stubGlobal("crypto", { randomUUID: () => `uuid-${++uuidCounter}` });

const SESSION_A = {
  id: "20260227-100000-aaaa1111",
  created_at: "2026-02-27T10:00:00Z",
  turn_count: 2,
  last_objective: "Test objective A",
};
const SESSION_B = {
  id: "20260227-110000-bbbb2222",
  created_at: "2026-02-27T11:00:00Z",
  turn_count: 0,
  last_objective: null,
};

describe("createApp", () => {
  const originalState = appState.get();

  beforeEach(() => {
    uuidCounter = 0;
    appState.set({ ...originalState, messages: [], sessionId: null });
    __setHandler("list_sessions", () => [SESSION_B, SESSION_A]);
    __setHandler("get_credentials_status", () => ({
      openai: true, anthropic: true, openrouter: false,
      cerebras: false, ollama: true, exa: false,
    }));
    __setHandler("open_session", () => ({
      id: "20260227-120000-cccc3333",
      created_at: "2026-02-27T12:00:00Z",
      turn_count: 0,
      last_objective: null,
    }));
    __setHandler("delete_session", () => {});
  });

  afterEach(() => {
    __clearHandlers();
    appState.set(originalState);
    document.body.innerHTML = "";
  });

  it("renders sidebar with session list", async () => {
    const root = document.createElement("div");
    document.body.appendChild(root);
    createApp(root);

    // Wait for async loadSessions
    await vi.waitFor(() => {
      const items = root.querySelectorAll(".session-list .session-item");
      expect(items.length).toBe(2);
    });
  });

  it("renders settings display", () => {
    appState.update((s) => ({ ...s, provider: "anthropic", model: "claude-opus-4-6" }));
    const root = document.createElement("div");
    createApp(root);
    const settings = root.querySelector(".settings-display");
    expect(settings).not.toBeNull();
    expect(settings!.textContent).toContain("anthropic");
    expect(settings!.textContent).toContain("claude-opus-4-6");
  });

  it("renders credential status", async () => {
    const root = document.createElement("div");
    document.body.appendChild(root);
    createApp(root);

    await vi.waitFor(() => {
      const creds = root.querySelector(".cred-status");
      expect(creds!.children.length).toBe(6);
      expect(creds!.querySelector(".cred-ok")!.textContent).toContain("openai");
      expect(creds!.querySelector(".cred-missing")!.textContent).toContain("openrouter");
    });
  });

  it("new session button creates session and clears state", async () => {
    const root = document.createElement("div");
    document.body.appendChild(root);
    createApp(root);

    await vi.waitFor(() => {
      expect(root.querySelectorAll(".session-list .session-item").length).toBe(2);
    });

    const newBtn = root.querySelector(".sidebar > .session-item") as HTMLElement;
    expect(newBtn.textContent).toBe("+ New Session");
    newBtn.click();

    await vi.waitFor(() => {
      expect(appState.get().sessionId).toBe("20260227-120000-cccc3333");
    });
  });

  it("shows 'No sessions yet' when list is empty", async () => {
    __setHandler("list_sessions", () => []);
    const root = document.createElement("div");
    document.body.appendChild(root);
    createApp(root);

    await vi.waitFor(() => {
      const items = root.querySelectorAll(".session-list .session-item");
      expect(items.length).toBe(1);
      expect(items[0].textContent).toBe("No sessions yet");
    });
  });
});

describe("session delete confirmation flow", () => {
  const originalState = appState.get();
  let deletedIds: string[] = [];

  beforeEach(() => {
    uuidCounter = 0;
    deletedIds = [];
    appState.set({ ...originalState, messages: [], sessionId: null });
    __setHandler("list_sessions", () => [SESSION_A]);
    __setHandler("get_credentials_status", () => ({}));
    __setHandler("open_session", () => ({
      id: "new-session",
      created_at: "2026-02-27T12:00:00Z",
      turn_count: 0,
      last_objective: null,
    }));
    __setHandler("delete_session", ({ id }: { id: string }) => {
      deletedIds.push(id);
      // After delete, list_sessions returns empty
      __setHandler("list_sessions", () => []);
    });
  });

  afterEach(() => {
    __clearHandlers();
    appState.set(originalState);
    document.body.innerHTML = "";
  });

  it("first click shows 'Delete?' confirmation", async () => {
    const root = document.createElement("div");
    document.body.appendChild(root);
    createApp(root);

    await vi.waitFor(() => {
      expect(root.querySelectorAll(".session-list .session-item").length).toBe(1);
    });

    const deleteBtn = root.querySelector(".session-delete") as HTMLElement;
    expect(deleteBtn.textContent).toBe("\u00d7");

    // First click: enters confirmation state
    deleteBtn.click();
    expect(deleteBtn.textContent).toBe("Delete?");
    expect(deleteBtn.style.color).toBe("var(--error)");
    expect(deleteBtn.style.fontWeight).toBe("600");
    expect(deleteBtn.style.display).toBe("inline");

    // Session should NOT be deleted yet
    expect(deletedIds).toEqual([]);
  });

  it("second click actually deletes", async () => {
    const root = document.createElement("div");
    document.body.appendChild(root);
    createApp(root);

    await vi.waitFor(() => {
      expect(root.querySelectorAll(".session-list .session-item").length).toBe(1);
    });

    const deleteBtn = root.querySelector(".session-delete") as HTMLElement;

    // First click: confirm
    deleteBtn.click();
    expect(deleteBtn.textContent).toBe("Delete?");

    // Second click: delete
    deleteBtn.click();

    await vi.waitFor(() => {
      expect(deletedIds).toEqual([SESSION_A.id]);
    });
  });

  it("confirmation resets after timeout", async () => {
    vi.useFakeTimers();

    const root = document.createElement("div");
    document.body.appendChild(root);
    createApp(root);

    // Wait for async session loading
    await vi.waitFor(() => {
      expect(root.querySelectorAll(".session-list .session-item").length).toBe(1);
    });

    const deleteBtn = root.querySelector(".session-delete") as HTMLElement;

    // First click: confirm
    deleteBtn.click();
    expect(deleteBtn.textContent).toBe("Delete?");

    // Advance past 3s timeout
    vi.advanceTimersByTime(3100);

    // Should be reset
    expect(deleteBtn.textContent).toBe("\u00d7");
    expect(deleteBtn.style.color).toBe("");
    expect(deleteBtn.style.fontWeight).toBe("");
    expect(deleteBtn.style.display).toBe("");
    expect(deletedIds).toEqual([]);

    vi.useRealTimers();
  });

  it("shows error on delete failure", async () => {
    __setHandler("delete_session", () => {
      throw new Error("Permission denied");
    });

    const root = document.createElement("div");
    document.body.appendChild(root);
    createApp(root);

    await vi.waitFor(() => {
      expect(root.querySelectorAll(".session-list .session-item").length).toBe(1);
    });

    const deleteBtn = root.querySelector(".session-delete") as HTMLElement;

    // First click: confirm
    deleteBtn.click();
    // Second click: delete (will fail)
    deleteBtn.click();

    await vi.waitFor(() => {
      expect(deleteBtn.textContent).toBe("Error!");
    });
  });

  it("clicking session label switches session", async () => {
    __setHandler("open_session", ({ id, resume }: any) => {
      expect(id).toBe(SESSION_A.id);
      expect(resume).toBe(true);
      return SESSION_A;
    });

    const root = document.createElement("div");
    document.body.appendChild(root);
    createApp(root);

    await vi.waitFor(() => {
      expect(root.querySelectorAll(".session-list .session-item").length).toBe(1);
    });

    const label = root.querySelector(".session-list .session-item span") as HTMLElement;
    label.click();

    await vi.waitFor(() => {
      expect(appState.get().sessionId).toBe(SESSION_A.id);
    });
  });

  it("deleting active session switches to new one", async () => {
    appState.update((s) => ({ ...s, sessionId: SESSION_A.id }));

    const root = document.createElement("div");
    document.body.appendChild(root);
    createApp(root);

    await vi.waitFor(() => {
      expect(root.querySelectorAll(".session-list .session-item").length).toBe(1);
    });

    const deleteBtn = root.querySelector(".session-delete") as HTMLElement;
    deleteBtn.click(); // confirm
    deleteBtn.click(); // delete

    await vi.waitFor(() => {
      expect(deletedIds).toEqual([SESSION_A.id]);
      // Should have switched to new session
      expect(appState.get().sessionId).toBe("new-session");
    });
  });
});
