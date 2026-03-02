// @vitest-environment happy-dom
import { vi, describe, it, expect, beforeEach, afterEach } from "vitest";
import { AutocompleteController } from "./Autocomplete";

function setup() {
  const anchor = document.createElement("div");
  anchor.className = "input-bar";
  const textarea = document.createElement("textarea");
  anchor.appendChild(textarea);
  document.body.appendChild(anchor);

  let lastAccepted = "";
  let dismissCount = 0;

  const ctrl = new AutocompleteController(anchor, {
    onAccept: (text) => {
      lastAccepted = text;
      textarea.value = text;
    },
    onDismiss: () => {
      dismissCount++;
    },
  });

  return {
    anchor,
    textarea,
    ctrl,
    getAccepted: () => lastAccepted,
    getDismissCount: () => dismissCount,
    cleanup: () => {
      ctrl.destroy();
      document.body.removeChild(anchor);
    },
  };
}

describe("AutocompleteController", () => {
  let env: ReturnType<typeof setup>;

  beforeEach(() => {
    env = setup();
  });

  afterEach(() => {
    env.cleanup();
  });

  it("creates popup element inside anchor", () => {
    const popup = env.anchor.querySelector(".autocomplete-popup");
    expect(popup).not.toBeNull();
    expect(popup!.getAttribute("style")).toContain("display: none");
  });

  it("is hidden by default", () => {
    expect(env.ctrl.isVisible()).toBe(false);
  });

  it("shows popup when typing /", () => {
    env.ctrl.update("/");
    expect(env.ctrl.isVisible()).toBe(true);
    const items = env.anchor.querySelectorAll(".autocomplete-item");
    expect(items.length).toBeGreaterThan(0);
  });

  it("hides popup for non-slash input", () => {
    env.ctrl.update("/");
    expect(env.ctrl.isVisible()).toBe(true);
    env.ctrl.update("hello");
    expect(env.ctrl.isVisible()).toBe(false);
  });

  it("filters commands by prefix", () => {
    env.ctrl.update("/mo");
    expect(env.ctrl.isVisible()).toBe(true);
    const items = env.anchor.querySelectorAll(".autocomplete-item");
    expect(items.length).toBe(1);
    expect(items[0].querySelector(".autocomplete-value")!.textContent).toBe("/model");
  });

  it("is case-insensitive when filtering", () => {
    env.ctrl.update("/MO");
    expect(env.ctrl.isVisible()).toBe(true);
    const items = env.anchor.querySelectorAll(".autocomplete-item");
    expect(items.length).toBe(1);
  });

  it("hides when no matches", () => {
    env.ctrl.update("/xyz");
    expect(env.ctrl.isVisible()).toBe(false);
  });

  it("auto-hides when single exact match has no children", () => {
    // /help has no children — typing it fully should hide popup
    env.ctrl.update("/help");
    expect(env.ctrl.isVisible()).toBe(false);
  });

  it("stays visible for exact match with children", () => {
    // /model has children — typing it fully should still show popup
    env.ctrl.update("/model");
    expect(env.ctrl.isVisible()).toBe(true);
  });

  it("shows children after descending with trailing space", () => {
    env.ctrl.update("/model ");
    expect(env.ctrl.isVisible()).toBe(true);
    const items = env.anchor.querySelectorAll(".autocomplete-item");
    // Should show "list" plus all model aliases
    expect(items.length).toBeGreaterThan(1);
    const values = Array.from(items).map(
      (i) => i.querySelector(".autocomplete-value")!.textContent,
    );
    expect(values).toContain("list");
    expect(values).toContain("opus");
  });

  it("filters children by prefix", () => {
    env.ctrl.update("/model op");
    expect(env.ctrl.isVisible()).toBe(true);
    const items = env.anchor.querySelectorAll(".autocomplete-item");
    const values = Array.from(items).map(
      (i) => i.querySelector(".autocomplete-value")!.textContent,
    );
    expect(values).toContain("opus");
    expect(values).toContain("opus-4");
  });

  it("shows provider filters for /model list ", () => {
    env.ctrl.update("/model list ");
    expect(env.ctrl.isVisible()).toBe(true);
    const items = env.anchor.querySelectorAll(".autocomplete-item");
    const values = Array.from(items).map(
      (i) => i.querySelector(".autocomplete-value")!.textContent,
    );
    expect(values).toContain("all");
    expect(values).toContain("openai");
    expect(values).toContain("anthropic");
  });

  it("shows reasoning levels for /reasoning ", () => {
    env.ctrl.update("/reasoning ");
    expect(env.ctrl.isVisible()).toBe(true);
    const items = env.anchor.querySelectorAll(".autocomplete-item");
    const values = Array.from(items).map(
      (i) => i.querySelector(".autocomplete-value")!.textContent,
    );
    expect(values).toEqual(["low", "medium", "high", "off"]);
  });

  // ── Keyboard navigation ──

  it("ArrowDown advances selection", () => {
    env.ctrl.update("/");
    const e = new KeyboardEvent("keydown", { key: "ArrowDown" });
    const consumed = env.ctrl.handleKeydown(e);
    expect(consumed).toBe(true);
    const items = env.anchor.querySelectorAll(".autocomplete-item");
    expect(items[1].classList.contains("selected")).toBe(true);
  });

  it("ArrowUp wraps to bottom", () => {
    env.ctrl.update("/");
    const e = new KeyboardEvent("keydown", { key: "ArrowUp" });
    env.ctrl.handleKeydown(e);
    const items = env.anchor.querySelectorAll(".autocomplete-item");
    expect(items[items.length - 1].classList.contains("selected")).toBe(true);
  });

  it("Tab accepts selected item", () => {
    env.ctrl.update("/mo");
    const e = new KeyboardEvent("keydown", { key: "Tab" });
    env.ctrl.handleKeydown(e);
    // /model has children so text should end with trailing space
    expect(env.getAccepted()).toBe("/model ");
  });

  it("Enter accepts selected item", () => {
    env.ctrl.update("/mo");
    const e = new KeyboardEvent("keydown", { key: "Enter" });
    env.ctrl.handleKeydown(e);
    expect(env.getAccepted()).toBe("/model ");
  });

  it("Escape hides popup and calls onDismiss", () => {
    env.ctrl.update("/");
    expect(env.ctrl.isVisible()).toBe(true);
    const e = new KeyboardEvent("keydown", { key: "Escape" });
    env.ctrl.handleKeydown(e);
    expect(env.ctrl.isVisible()).toBe(false);
    expect(env.getDismissCount()).toBe(1);
  });

  it("does not consume keys when hidden", () => {
    expect(env.ctrl.isVisible()).toBe(false);
    const e = new KeyboardEvent("keydown", { key: "Enter" });
    expect(env.ctrl.handleKeydown(e)).toBe(false);
  });

  it("accepting a leaf item hides the popup", () => {
    env.ctrl.update("/hel");
    const e = new KeyboardEvent("keydown", { key: "Tab" });
    env.ctrl.handleKeydown(e);
    expect(env.getAccepted()).toBe("/help");
    expect(env.ctrl.isVisible()).toBe(false);
  });

  // ── Mouse interaction ──

  it("click on item accepts it", () => {
    env.ctrl.update("/");
    const items = env.anchor.querySelectorAll(".autocomplete-item");
    const helpItem = Array.from(items).find(
      (i) => i.querySelector(".autocomplete-value")!.textContent === "/help",
    );
    expect(helpItem).toBeDefined();
    helpItem!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(env.getAccepted()).toBe("/help");
  });

  it("mouseenter changes selection", () => {
    env.ctrl.update("/");
    const items = env.anchor.querySelectorAll(".autocomplete-item");
    expect(items.length).toBeGreaterThan(1);
    items[2].dispatchEvent(new MouseEvent("mouseenter", { bubbles: true }));
    expect(items[2].classList.contains("selected")).toBe(true);
    expect(items[0].classList.contains("selected")).toBe(false);
  });

  it("destroy removes popup from DOM", () => {
    expect(env.anchor.querySelector(".autocomplete-popup")).not.toBeNull();
    env.ctrl.destroy();
    expect(env.anchor.querySelector(".autocomplete-popup")).toBeNull();
    // Prevent double-remove in cleanup
    env.cleanup = () => {
      document.body.removeChild(env.anchor);
    };
  });

  it("hides for unmatched token in middle of chain", () => {
    env.ctrl.update("/model bogus ");
    expect(env.ctrl.isVisible()).toBe(false);
  });

  it("shows --save after /reasoning high ", () => {
    env.ctrl.update("/reasoning high ");
    expect(env.ctrl.isVisible()).toBe(true);
    const items = env.anchor.querySelectorAll(".autocomplete-item");
    expect(items.length).toBe(1);
    expect(items[0].querySelector(".autocomplete-value")!.textContent).toBe("--save");
  });
});
