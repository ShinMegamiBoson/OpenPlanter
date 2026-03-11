import { describe, it, expect } from "vitest";
import { COMMAND_COMPLETIONS, type CompletionItem } from "./completionRegistry";
import { MODEL_ALIASES } from "./model";

describe("completionRegistry", () => {
  it("exports a non-empty COMMAND_COMPLETIONS array", () => {
    expect(Array.isArray(COMMAND_COMPLETIONS)).toBe(true);
    expect(COMMAND_COMPLETIONS.length).toBeGreaterThan(0);
  });

  it("all top-level items start with /", () => {
    for (const item of COMMAND_COMPLETIONS) {
      expect(item.value.startsWith("/")).toBe(true);
    }
  });

  it("includes all expected top-level commands", () => {
    const values = COMMAND_COMPLETIONS.map((c) => c.value);
    expect(values).toContain("/help");
    expect(values).toContain("/new");
    expect(values).toContain("/clear");
    expect(values).toContain("/quit");
    expect(values).toContain("/exit");
    expect(values).toContain("/status");
    expect(values).toContain("/model");
    expect(values).toContain("/zai-plan");
    expect(values).toContain("/web-search");
    expect(values).toContain("/reasoning");
  });

  it("every item has a non-empty value and description", () => {
    function check(items: CompletionItem[]) {
      for (const item of items) {
        expect(item.value.length).toBeGreaterThan(0);
        expect(item.description.length).toBeGreaterThan(0);
        if (item.children) check(item.children);
      }
    }
    check(COMMAND_COMPLETIONS);
  });

  it("/model has 'list' and all MODEL_ALIASES as children", () => {
    const modelCmd = COMMAND_COMPLETIONS.find((c) => c.value === "/model");
    expect(modelCmd).toBeDefined();
    expect(modelCmd!.children).toBeDefined();

    const childValues = modelCmd!.children!.map((c) => c.value);
    expect(childValues).toContain("list");

    for (const alias of Object.keys(MODEL_ALIASES)) {
      expect(childValues).toContain(alias);
    }
  });

  it("/model list has provider filter children", () => {
    const modelCmd = COMMAND_COMPLETIONS.find((c) => c.value === "/model")!;
    const listCmd = modelCmd.children!.find((c) => c.value === "list")!;
    expect(listCmd.children).toBeDefined();

    const providerValues = listCmd.children!.map((c) => c.value);
    expect(providerValues).toContain("all");
    expect(providerValues).toContain("openai");
    expect(providerValues).toContain("anthropic");
    expect(providerValues).toContain("ollama");
    expect(providerValues).toContain("zai");
  });

  it("model alias children have --save flag", () => {
    const modelCmd = COMMAND_COMPLETIONS.find((c) => c.value === "/model")!;
    const opusChild = modelCmd.children!.find((c) => c.value === "opus")!;
    expect(opusChild.children).toBeDefined();
    expect(opusChild.children![0].value).toBe("--save");
  });

  it("/reasoning has low, medium, high, off children", () => {
    const reasoningCmd = COMMAND_COMPLETIONS.find((c) => c.value === "/reasoning");
    expect(reasoningCmd).toBeDefined();
    expect(reasoningCmd!.children).toBeDefined();

    const childValues = reasoningCmd!.children!.map((c) => c.value);
    expect(childValues).toEqual(["low", "medium", "high", "off"]);
  });

  it("/web-search has exa and firecrawl children", () => {
    const webSearchCmd = COMMAND_COMPLETIONS.find((c) => c.value === "/web-search");
    expect(webSearchCmd).toBeDefined();
    expect(webSearchCmd!.children).toBeDefined();

    const childValues = webSearchCmd!.children!.map((c) => c.value);
    expect(childValues).toEqual(["exa", "firecrawl"]);
    expect(webSearchCmd!.children![0].children?.[0].value).toBe("--save");
  });

  it("/zai-plan has paygo and coding children", () => {
    const zaiPlanCmd = COMMAND_COMPLETIONS.find((c) => c.value === "/zai-plan");
    expect(zaiPlanCmd).toBeDefined();
    expect(zaiPlanCmd!.children).toBeDefined();

    const childValues = zaiPlanCmd!.children!.map((c) => c.value);
    expect(childValues).toEqual(["paygo", "coding"]);
    expect(zaiPlanCmd!.children![0].children?.[0].value).toBe("--save");
  });

  it("reasoning level children have --save flag", () => {
    const reasoningCmd = COMMAND_COMPLETIONS.find((c) => c.value === "/reasoning")!;
    for (const level of reasoningCmd.children!) {
      expect(level.children).toBeDefined();
      expect(level.children![0].value).toBe("--save");
    }
  });

  it("/help has no children", () => {
    const helpCmd = COMMAND_COMPLETIONS.find((c) => c.value === "/help");
    expect(helpCmd).toBeDefined();
    expect(helpCmd!.children).toBeUndefined();
  });
});
