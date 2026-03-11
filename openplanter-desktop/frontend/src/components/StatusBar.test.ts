// @vitest-environment happy-dom
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { appState } from "../state/store";
import { createStatusBar } from "./StatusBar";

describe("createStatusBar", () => {
  const originalState = appState.get();

  beforeEach(() => {
    appState.set({ ...originalState });
  });

  afterEach(() => {
    appState.set(originalState);
  });

  it("creates element with correct class", () => {
    const bar = createStatusBar();
    expect(bar.className).toBe("status-bar");
  });

  it("has all child spans", () => {
    const bar = createStatusBar();
    expect(bar.querySelector(".provider")).not.toBeNull();
    expect(bar.querySelector(".model")).not.toBeNull();
    expect(bar.querySelector(".reasoning")).not.toBeNull();
    expect(bar.querySelector(".zai-plan")).not.toBeNull();
    expect(bar.querySelector(".mode")).not.toBeNull();
    expect(bar.querySelector(".session")).not.toBeNull();
    expect(bar.querySelector(".tokens")).not.toBeNull();
  });

  it("shows em dash when provider/model empty", () => {
    const bar = createStatusBar();
    expect(bar.querySelector(".provider")!.textContent).toBe("\u2014");
    expect(bar.querySelector(".model")!.textContent).toBe("\u2014");
  });

  it("renders provider and model", () => {
    appState.update((s) => ({ ...s, provider: "anthropic", model: "claude-opus-4-6" }));
    const bar = createStatusBar();
    expect(bar.querySelector(".provider")!.textContent).toBe("anthropic");
    expect(bar.querySelector(".model")!.textContent).toBe("claude-opus-4-6");
  });

  it("renders reasoning effort when set", () => {
    appState.update((s) => ({ ...s, reasoningEffort: "high" }));
    const bar = createStatusBar();
    expect(bar.querySelector(".reasoning")!.textContent).toBe("reasoning:high");
  });

  it("reasoning is empty when null", () => {
    appState.update((s) => ({ ...s, reasoningEffort: null }));
    const bar = createStatusBar();
    expect(bar.querySelector(".reasoning")!.textContent).toBe("");
  });

  it("renders Z.AI plan when provider is zai", () => {
    appState.update((s) => ({ ...s, provider: "zai", zaiPlan: "coding" }));
    const bar = createStatusBar();
    expect(bar.querySelector(".zai-plan")!.textContent).toBe("zai:coding");
  });

  it("hides Z.AI plan when provider is not zai", () => {
    appState.update((s) => ({ ...s, provider: "anthropic", zaiPlan: "coding" }));
    const bar = createStatusBar();
    expect(bar.querySelector(".zai-plan")!.textContent).toBe("");
  });

  it("renders recursive mode", () => {
    appState.update((s) => ({ ...s, recursive: true }));
    const bar = createStatusBar();
    expect(bar.querySelector(".mode")!.textContent).toBe("recursive");
  });

  it("renders flat mode", () => {
    appState.update((s) => ({ ...s, recursive: false }));
    const bar = createStatusBar();
    expect(bar.querySelector(".mode")!.textContent).toBe("flat");
  });

  it("renders session id (first 8 chars)", () => {
    appState.update((s) => ({ ...s, sessionId: "20260227-100000-abcd1234" }));
    const bar = createStatusBar();
    expect(bar.querySelector(".session")!.textContent).toBe("session 20260227");
  });

  it("session is empty when no session", () => {
    appState.update((s) => ({ ...s, sessionId: null }));
    const bar = createStatusBar();
    expect(bar.querySelector(".session")!.textContent).toBe("");
  });

  it("shows step/depth when running", () => {
    appState.update((s) => ({ ...s, isRunning: true, currentStep: 3, currentDepth: 1 }));
    const bar = createStatusBar();
    expect(bar.querySelector(".session")!.textContent).toBe("step 3 depth 1");
  });

  it("renders token counts", () => {
    appState.update((s) => ({ ...s, inputTokens: 5000, outputTokens: 2500 }));
    const bar = createStatusBar();
    expect(bar.querySelector(".tokens")!.textContent).toBe("5.0k in / 2.5k out");
  });

  it("renders zero tokens", () => {
    const bar = createStatusBar();
    expect(bar.querySelector(".tokens")!.textContent).toBe("0.0k in / 0.0k out");
  });

  it("updates reactively on state change", () => {
    const bar = createStatusBar();
    expect(bar.querySelector(".provider")!.textContent).toBe("\u2014");

    appState.update((s) => ({ ...s, provider: "openai" }));
    expect(bar.querySelector(".provider")!.textContent).toBe("openai");
  });
});
