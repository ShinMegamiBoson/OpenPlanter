import { describe, it, expect } from "vitest";
import { CATEGORY_COLORS, getCategoryColor } from "./colors";

describe("CATEGORY_COLORS", () => {
  it("has all expected categories", () => {
    const expected = [
      "campaign-finance",
      "contracts",
      "corporate",
      "financial",
      "infrastructure",
      "international",
      "lobbying",
      "nonprofits",
      "regulatory",
      "sanctions",
      "media",
      "legal",
    ];
    for (const cat of expected) {
      expect(CATEGORY_COLORS[cat]).toBeDefined();
    }
  });

  it("all values are hex colors", () => {
    for (const [, color] of Object.entries(CATEGORY_COLORS)) {
      expect(color).toMatch(/^#[0-9a-f]{6}$/i);
    }
  });
});

describe("getCategoryColor", () => {
  it("returns correct color for known category", () => {
    expect(getCategoryColor("contracts")).toBe("#79c0ff");
    expect(getCategoryColor("corporate")).toBe("#56d364");
    expect(getCategoryColor("sanctions")).toBe("#f778ba");
  });

  it("returns default gray for unknown category", () => {
    expect(getCategoryColor("unknown")).toBe("#8b949e");
    expect(getCategoryColor("")).toBe("#8b949e");
    expect(getCategoryColor("foobar")).toBe("#8b949e");
  });
});
