import { describe, it, expect, vi } from "vitest";
import { Store, appState, type AppState } from "./store";

describe("Store", () => {
  it("get returns initial value", () => {
    const s = new Store(42);
    expect(s.get()).toBe(42);
  });

  it("set updates value", () => {
    const s = new Store("hello");
    s.set("world");
    expect(s.get()).toBe("world");
  });

  it("update applies function", () => {
    const s = new Store(10);
    s.update((v) => v + 5);
    expect(s.get()).toBe(15);
  });

  it("subscribe called on set", () => {
    const s = new Store(0);
    const fn = vi.fn();
    s.subscribe(fn);
    s.set(1);
    expect(fn).toHaveBeenCalledWith(1);
  });

  it("subscribe called on update", () => {
    const s = new Store(0);
    const fn = vi.fn();
    s.subscribe(fn);
    s.update((v) => v + 1);
    expect(fn).toHaveBeenCalledWith(1);
  });

  it("unsubscribe stops notifications", () => {
    const s = new Store(0);
    const fn = vi.fn();
    const unsub = s.subscribe(fn);
    unsub();
    s.set(1);
    expect(fn).not.toHaveBeenCalled();
  });

  it("multiple subscribers all notified", () => {
    const s = new Store(0);
    const fn1 = vi.fn();
    const fn2 = vi.fn();
    s.subscribe(fn1);
    s.subscribe(fn2);
    s.set(99);
    expect(fn1).toHaveBeenCalledWith(99);
    expect(fn2).toHaveBeenCalledWith(99);
  });
});

describe("appState", () => {
  it("has correct initial values", () => {
    const state = appState.get();
    expect(state.provider).toBe("");
    expect(state.model).toBe("");
    expect(state.sessionId).toBeNull();
    expect(state.inputTokens).toBe(0);
    expect(state.outputTokens).toBe(0);
    expect(state.isRunning).toBe(false);
    expect(state.messages).toEqual([]);
    expect(state.reasoningEffort).toBeNull();
    expect(state.recursive).toBe(true);
    expect(state.maxDepth).toBe(4);
    expect(state.maxStepsPerCall).toBe(100);
    expect(state.inputQueue).toEqual([]);
  });

  it("message append via update", () => {
    // Save original state
    const original = appState.get();

    appState.update((s) => ({
      ...s,
      messages: [
        ...s.messages,
        {
          id: "1",
          role: "user" as const,
          content: "hello",
          timestamp: 1000,
        },
      ],
    }));

    const state = appState.get();
    expect(state.messages.length).toBe(original.messages.length + 1);
    expect(state.messages[state.messages.length - 1].content).toBe("hello");

    // Restore
    appState.set(original);
  });

  it("queue operations via update", () => {
    const original = appState.get();

    // Push
    appState.update((s) => ({
      ...s,
      inputQueue: [...s.inputQueue, "item1", "item2"],
    }));
    expect(appState.get().inputQueue).toEqual(["item1", "item2"]);

    // Shift
    appState.update((s) => ({
      ...s,
      inputQueue: s.inputQueue.slice(1),
    }));
    expect(appState.get().inputQueue).toEqual(["item2"]);

    // Restore
    appState.set(original);
  });
});
