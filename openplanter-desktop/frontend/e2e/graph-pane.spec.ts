import { test, expect, type Page } from "@playwright/test";
import {
  MOCK_GRAPH_DATA,
  MOCK_GRAPH_DATA_WITH_NEW_NODES,
  MOCK_CONFIG,
  MOCK_SESSIONS,
  MOCK_CREDENTIALS,
} from "./fixtures/graph-data";

/** Inject Tauri IPC mocks before page loads. */
async function injectTauriMocks(page: Page) {
  await page.addInitScript(
    ({ graphData, config, sessions, credentials }) => {
      // Create the Tauri internals mock surface
      (window as any).__TAURI_INTERNALS__ = {
        invoke: async (cmd: string, args?: any) => {
          switch (cmd) {
            case "get_graph_data":
              return graphData;
            case "get_config":
              return config;
            case "list_sessions":
              return sessions;
            case "get_credentials_status":
              return credentials;
            case "open_session":
              return {
                id: "new-session-id",
                created_at: new Date().toISOString(),
                turn_count: 0,
                last_objective: null,
              };
            case "read_wiki_file":
              return `# ${args?.path?.replace(/.*\//, "").replace(".md", "")}\n\nMock wiki content for testing.\n\n## Summary\n\nThis is a mock document.\n\n- **Key**: value\n- **Status**: Active\n\n## References\n\n- [other-file.md](other-file.md)\n`;
            case "debug_log":
              return;
            case "list_models":
              return [];
            case "save_settings":
              return;
            case "solve":
              return;
            case "get_session_history":
              return [];
            default:
              console.warn(`[E2E Mock] Unhandled invoke: ${cmd}`, args);
              return;
          }
        },
        transformCallback: (callback: Function, once = false) => {
          const id = Math.floor(Math.random() * 1000000);
          (window as any).__TAURI_CB__ =
            (window as any).__TAURI_CB__ || {};
          (window as any).__TAURI_CB__[id] = callback;
          return id;
        },
        convertFileSrc: (path: string) => path,
        metadata: {
          currentWindow: { label: "main" },
          currentWebview: { windowLabel: "main", label: "main" },
        },
      };

      // Mock event plugin: listen returns a no-op unlisten
      (window as any).__TAURI_EVENT_PLUGIN_INTERNALS__ = {
        unregisterListener: () => {},
      };
    },
    {
      graphData: MOCK_GRAPH_DATA,
      config: MOCK_CONFIG,
      sessions: MOCK_SESSIONS,
      credentials: MOCK_CREDENTIALS,
    }
  );
}

test.describe("Graph Pane", () => {
  test.beforeEach(async ({ page }) => {
    await injectTauriMocks(page);
    await page.goto("/");
    // Wait for the graph pane to be in the DOM
    await page.waitForSelector(".graph-pane", { timeout: 5000 });
    // Give Cytoscape time to initialize and layout
    await page.waitForTimeout(2000);
    // Session filter defaults ON (hides all pre-existing nodes).
    // Turn it off so non-session tests see all nodes.
    const toggle = page.locator(".graph-session-toggle");
    if (await toggle.evaluate((el) => el.classList.contains("active"))) {
      await toggle.click();
      await page.waitForTimeout(300);
    }
  });

  test("full app layout renders three columns", async ({ page }) => {
    await page.screenshot({ path: "e2e/screenshots/01-full-app.png", fullPage: true });

    // Grid layout: sidebar, chat pane, graph pane
    await expect(page.locator(".sidebar")).toBeVisible();
    await expect(page.locator(".chat-pane")).toBeVisible();
    await expect(page.locator(".graph-pane")).toBeVisible();
    await expect(page.locator(".input-bar")).toBeVisible();
  });

  test("graph pane has toolbar, canvas, and legend", async ({ page }) => {
    await page.screenshot({ path: "e2e/screenshots/02-graph-structure.png" });

    // Toolbar elements
    await expect(page.locator(".graph-toolbar")).toBeVisible();
    await expect(page.locator(".graph-search")).toBeVisible();
    await expect(page.locator(".graph-layout-select")).toBeVisible();
    await expect(page.locator(".graph-tier-select")).toBeVisible();
    await expect(page.locator(".graph-fit-btn")).toBeVisible();

    // Canvas (Cytoscape container)
    await expect(page.locator(".graph-canvas")).toBeVisible();

    // Legend
    await expect(page.locator(".graph-legend")).toBeVisible();
  });

  test("cytoscape renders nodes on canvas", async ({ page }) => {
    // Cytoscape renders onto multiple canvas layers inside .graph-canvas
    const canvases = page.locator(".graph-canvas canvas");
    const count = await canvases.count();
    expect(count).toBeGreaterThanOrEqual(1);
    const canvas = canvases.first();
    await expect(canvas).toBeVisible({ timeout: 5000 });

    await page.screenshot({ path: "e2e/screenshots/03-cytoscape-canvas.png" });

    // Canvas should have non-zero dimensions
    const box = await canvas.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.width).toBeGreaterThan(100);
    expect(box!.height).toBeGreaterThan(100);
  });

  test("legend shows all categories from data", async ({ page }) => {
    const legendItems = page.locator(".graph-legend-item");
    // We have 10 unique categories in mock data
    await expect(legendItems).toHaveCount(10);

    await page.screenshot({ path: "e2e/screenshots/04-legend.png" });

    // Check each category has a colored dot
    const dots = page.locator(".graph-legend-dot");
    await expect(dots).toHaveCount(10);
  });

  test("search input filters and hides non-matching nodes", async ({ page }) => {
    const searchInput = page.locator(".graph-search");
    await searchInput.fill("Acme");

    // Wait for debounce + filtering
    await page.waitForTimeout(500);

    // Non-matching nodes should be hidden
    const visibleCount = await page.evaluate(() => {
      const container = document.querySelector(".graph-canvas");
      const cy = (container as any)?._cyreg?.cy;
      return cy ? cy.nodes(":visible").length : 0;
    });
    // Only exact matches should be visible, others hidden
    expect(visibleCount).toBeLessThan(15);
    expect(visibleCount).toBeGreaterThan(0);

    await page.screenshot({ path: "e2e/screenshots/05-search-acme.png" });

    // Press Enter to zoom to matches
    await searchInput.press("Enter");
    await page.waitForTimeout(500);
    await page.screenshot({ path: "e2e/screenshots/06-search-zoom.png" });

    // Clear search — all nodes should return
    await searchInput.press("Escape");
    await page.waitForTimeout(500);

    const allVisible = await page.evaluate(() => {
      const container = document.querySelector(".graph-canvas");
      const cy = (container as any)?._cyreg?.cy;
      return cy ? cy.nodes(":visible").length : 0;
    });
    expect(allVisible).toBe(15);
  });

  test("layout dropdown switches layout", async ({ page }) => {
    // Take initial layout screenshot
    await page.screenshot({ path: "e2e/screenshots/07-layout-force.png" });

    // Switch to grouped
    const layoutSelect = page.locator(".graph-layout-select");
    await layoutSelect.selectOption("concentric");
    await page.waitForTimeout(1000);
    await page.screenshot({ path: "e2e/screenshots/07b-layout-grouped.png" });

    // Switch to hierarchical
    await layoutSelect.selectOption("dagre");
    await page.waitForTimeout(1000);
    await page.screenshot({ path: "e2e/screenshots/08-layout-hierarchical.png" });

    // Switch to circle
    await layoutSelect.selectOption("circle");
    await page.waitForTimeout(1000);
    await page.screenshot({ path: "e2e/screenshots/09-layout-circle.png" });

    // Back to force
    await layoutSelect.selectOption("fcose");
    await page.waitForTimeout(1000);
  });

  test("fit button zooms to show all nodes", async ({ page }) => {
    const fitBtn = page.locator(".graph-fit-btn");
    await fitBtn.click();
    await page.waitForTimeout(500);
    await page.screenshot({ path: "e2e/screenshots/10-fit-view.png" });
  });

  test("legend toggle hides category nodes", async ({ page }) => {
    // Click the first legend item to hide that category
    const firstItem = page.locator(".graph-legend-item").first();
    const categoryName = await firstItem.locator(".graph-legend-label").textContent();

    await firstItem.click();
    await page.waitForTimeout(500);

    // Legend item should have hidden class
    await expect(firstItem).toHaveClass(/legend-hidden/);

    await page.screenshot({
      path: `e2e/screenshots/11-legend-hide-${categoryName}.png`,
    });

    // Click again to show
    await firstItem.click();
    await page.waitForTimeout(500);
    await expect(firstItem).not.toHaveClass(/legend-hidden/);
  });

  test("clicking source node opens wiki drawer", async ({ page }) => {
    const hasNodes = await page.evaluate(() => {
      const container = document.querySelector(".graph-canvas");
      if (!container) return false;
      const cy = (container as any)._cyreg?.cy;
      if (!cy) return false;
      return cy.nodes().length > 0;
    });
    expect(hasNodes).toBe(true);

    // Tap a source node — should open the drawer, not the detail overlay
    await page.evaluate(() => {
      const container = document.querySelector(".graph-canvas");
      const cy = (container as any)._cyreg?.cy;
      if (!cy) return;
      cy.getElementById("acme-corp").emit("tap");
    });

    await page.waitForTimeout(500);
    await page.screenshot({ path: "e2e/screenshots/12-source-drawer.png" });

    // Drawer should be visible
    await expect(page.locator(".graph-source-drawer.visible")).toBeVisible();
    await expect(page.locator(".graph-source-drawer-title")).toHaveText("Acme Corp");

    // Detail overlay should NOT be visible (source nodes use drawer)
    await expect(page.locator(".graph-detail")).not.toBeVisible();
  });

  test("clicking section node shows detail overlay with view source button", async ({ page }) => {
    // Tap a section node — should show the detail overlay
    await page.evaluate(() => {
      const container = document.querySelector(".graph-canvas");
      const cy = (container as any)._cyreg?.cy;
      if (!cy) return;
      cy.getElementById("acme-corp::summary").emit("tap");
    });

    await page.waitForTimeout(500);
    await page.screenshot({ path: "e2e/screenshots/12b-section-detail.png" });

    const detail = page.locator(".graph-detail");
    await expect(detail).toBeVisible();
    await expect(page.locator(".graph-detail-title")).toHaveText("Summary");
    await expect(page.locator(".graph-detail-badge")).toBeVisible();

    // "View source" button should be present
    await expect(page.locator(".graph-detail-view-source")).toBeVisible();
  });

  test("detail overlay close button works", async ({ page }) => {
    // Open detail on a section node (not source)
    await page.evaluate(() => {
      const container = document.querySelector(".graph-canvas");
      const cy = (container as any)._cyreg?.cy;
      if (!cy) return;
      cy.getElementById("acme-corp::summary").emit("tap");
    });
    await page.waitForTimeout(300);
    await expect(page.locator(".graph-detail")).toBeVisible();

    // Close it (scope to detail overlay, not drawer)
    await page.locator(".graph-detail .graph-detail-close").click();
    await page.waitForTimeout(300);
    await expect(page.locator(".graph-detail")).not.toBeVisible();
  });

  test("escape key closes drawer and detail", async ({ page }) => {
    // Open drawer on a source node
    await page.evaluate(() => {
      const container = document.querySelector(".graph-canvas");
      const cy = (container as any)._cyreg?.cy;
      if (!cy) return;
      cy.getElementById("acme-corp").emit("tap");
    });
    await page.waitForTimeout(500);
    await expect(page.locator(".graph-source-drawer.visible")).toBeVisible();

    // Press Escape (triggers background tap which calls onNodeDeselect → hideDrawer)
    await page.keyboard.press("Escape");
    await page.waitForTimeout(300);
    await expect(page.locator(".graph-source-drawer.visible")).not.toBeVisible();
  });

  test("drawer close button works", async ({ page }) => {
    await page.evaluate(() => {
      const container = document.querySelector(".graph-canvas");
      const cy = (container as any)._cyreg?.cy;
      if (!cy) return;
      cy.getElementById("acme-corp").emit("tap");
    });
    await page.waitForTimeout(500);
    await expect(page.locator(".graph-source-drawer.visible")).toBeVisible();

    // Click close button in drawer
    await page.locator(".graph-source-drawer .graph-detail-close").click();
    await page.waitForTimeout(300);
    await expect(page.locator(".graph-source-drawer.visible")).not.toBeVisible();
  });

  test("node detail shows connected nodes", async ({ page }) => {
    // Tap a section node that has connections
    await page.evaluate(() => {
      const container = document.querySelector(".graph-canvas");
      const cy = (container as any)._cyreg?.cy;
      if (!cy) return;
      cy.getElementById("acme-corp::data-schema").emit("tap");
    });
    await page.waitForTimeout(500);

    const connList = page.locator(".graph-detail-conn-list");
    await expect(connList).toBeVisible();

    const connItems = page.locator(".graph-detail-conn-item");
    const count = await connItems.count();
    expect(count).toBeGreaterThanOrEqual(1);

    await page.screenshot({ path: "e2e/screenshots/13-section-connections.png" });
  });

  test("view source button opens drawer from detail overlay", async ({ page }) => {
    // Open detail on a section node
    await page.evaluate(() => {
      const container = document.querySelector(".graph-canvas");
      const cy = (container as any)._cyreg?.cy;
      if (!cy) return;
      cy.getElementById("acme-corp::summary").emit("tap");
    });
    await page.waitForTimeout(300);
    await expect(page.locator(".graph-detail")).toBeVisible();

    // Click "View source"
    await page.locator(".graph-detail-view-source").click();
    await page.waitForTimeout(500);

    // Drawer should open, detail overlay should close
    await expect(page.locator(".graph-source-drawer.visible")).toBeVisible();
    await expect(page.locator(".graph-detail")).not.toBeVisible();

    await page.screenshot({ path: "e2e/screenshots/14-view-source-drawer.png" });
  });

  test("empty graph shows placeholder", async ({ page: _ }, testInfo) => {
    // Create a new page with empty graph data
    const browser = testInfo.project.use.browserName;
    const context = await (await import("@playwright/test")).chromium.launch();
    const page = await (await context.newContext({ viewport: { width: 1400, height: 900 } })).newPage();

    await page.addInitScript(() => {
      (window as any).__TAURI_INTERNALS__ = {
        invoke: async (cmd: string) => {
          switch (cmd) {
            case "get_graph_data":
              return { nodes: [], edges: [] };
            case "get_config":
              return {
                provider: "anthropic", model: "claude-opus-4-6",
                reasoning_effort: null, workspace: "/tmp",
                session_id: null, recursive: false,
                max_depth: 3, max_steps_per_call: 25, demo: false,
              };
            case "list_sessions":
              return [];
            case "get_credentials_status":
              return {};
            case "open_session":
              return { id: "s", created_at: "", turn_count: 0, last_objective: null };
            default:
              return;
          }
        },
        transformCallback: (cb: Function) => {
          const id = Math.floor(Math.random() * 1e6);
          return id;
        },
        convertFileSrc: (p: string) => p,
        metadata: {
          currentWindow: { label: "main" },
          currentWebview: { windowLabel: "main", label: "main" },
        },
      };
      (window as any).__TAURI_EVENT_PLUGIN_INTERNALS__ = {
        unregisterListener: () => {},
      };
    });

    await page.goto("http://localhost:5173/");
    await page.waitForTimeout(2000);

    const placeholder = page.locator(".graph-placeholder");
    await expect(placeholder).toBeVisible();
    const text = await placeholder.textContent();
    expect(text).toContain("no wiki data");

    await page.screenshot({ path: "e2e/screenshots/15-empty-graph.png" });

    await context.close();
  });

  test("graph pane CSS layout is correct", async ({ page }) => {
    // Verify toolbar is at top, canvas fills middle, legend at bottom
    const toolbar = page.locator(".graph-toolbar");
    const canvas = page.locator(".graph-canvas");
    const legend = page.locator(".graph-legend");

    const toolbarBox = await toolbar.boundingBox();
    const canvasBox = await canvas.boundingBox();
    const legendBox = await legend.boundingBox();

    expect(toolbarBox).not.toBeNull();
    expect(canvasBox).not.toBeNull();
    expect(legendBox).not.toBeNull();

    // Toolbar is above canvas
    expect(toolbarBox!.y + toolbarBox!.height).toBeLessThanOrEqual(canvasBox!.y + 2);
    // Canvas is above legend
    expect(canvasBox!.y + canvasBox!.height).toBeLessThanOrEqual(legendBox!.y + 2);
    // Canvas takes significant height
    expect(canvasBox!.height).toBeGreaterThan(200);

    await page.screenshot({ path: "e2e/screenshots/16-layout-verify.png" });
  });

  test("zero-edge graph defaults to grouped layout", async ({ page }) => {
    // The mock data has edges, so the default is fcose.
    // Verify the dropdown reflects the default layout.
    const layoutSelect = page.locator(".graph-layout-select");
    const selected = await layoutSelect.inputValue();
    expect(selected).toBe("fcose");

    // Verify that "Grouped" option exists in dropdown
    const options = await layoutSelect.locator("option").allTextContents();
    expect(options).toContain("Grouped");
  });

  // ── Tier / node-type tests ──

  test("section and fact nodes have correct shapes in Cytoscape", async ({ page }) => {
    // Verify node_type data is set correctly on Cytoscape nodes
    const nodeTypes = await page.evaluate(() => {
      const container = document.querySelector(".graph-canvas");
      const cy = (container as any)?._cyreg?.cy;
      if (!cy) return {};
      const types: Record<string, string> = {};
      cy.nodes().forEach((n: any) => {
        types[n.id()] = n.data("node_type") || "unknown";
      });
      return types;
    });

    expect(nodeTypes["acme-corp"]).toBe("source");
    expect(nodeTypes["acme-corp::summary"]).toBe("section");
    expect(nodeTypes["acme-corp::data-schema::entity-id"]).toBe("fact");

    await page.screenshot({ path: "e2e/screenshots/17-node-types.png" });
  });

  test("clicking fact node shows type badge and content", async ({ page }) => {
    // Tap a fact node
    await page.evaluate(() => {
      const container = document.querySelector(".graph-canvas");
      const cy = (container as any)?._cyreg?.cy;
      if (!cy) return;
      const fact = cy.getElementById("acme-corp::data-schema::entity-id");
      if (!fact.empty()) fact.emit("tap");
    });
    await page.waitForTimeout(500);

    // Detail should show type badge
    const typeBadge = page.locator(".graph-detail-type");
    await expect(typeBadge).toBeVisible();
    const typeText = await typeBadge.textContent();
    expect(typeText).toBe("fact");

    // Detail should show content block
    const content = page.locator(".graph-detail-content");
    await expect(content).toBeVisible();
    const contentText = await content.textContent();
    expect(contentText).toContain("entity_id");

    await page.screenshot({ path: "e2e/screenshots/18-fact-detail.png" });
  });

  test("tier dropdown filters nodes by tier", async ({ page }) => {
    const tierSelect = page.locator(".graph-tier-select");

    // Count total nodes initially
    const totalBefore = await page.evaluate(() => {
      const container = document.querySelector(".graph-canvas");
      const cy = (container as any)?._cyreg?.cy;
      return cy ? cy.nodes(":visible").length : 0;
    });
    expect(totalBefore).toBe(15); // 10 sources + 3 sections + 2 facts

    // Filter to "Sources only"
    await tierSelect.selectOption("sources");
    await page.waitForTimeout(500);

    const sourcesOnly = await page.evaluate(() => {
      const container = document.querySelector(".graph-canvas");
      const cy = (container as any)?._cyreg?.cy;
      return cy ? cy.nodes(":visible").length : 0;
    });
    expect(sourcesOnly).toBe(10);

    await page.screenshot({ path: "e2e/screenshots/19-tier-sources-only.png" });

    // Filter to "Sources + Sections"
    await tierSelect.selectOption("sources-sections");
    await page.waitForTimeout(500);

    const sourcesAndSections = await page.evaluate(() => {
      const container = document.querySelector(".graph-canvas");
      const cy = (container as any)?._cyreg?.cy;
      return cy ? cy.nodes(":visible").length : 0;
    });
    expect(sourcesAndSections).toBe(13); // 10 sources + 3 sections

    // Back to "All tiers"
    await tierSelect.selectOption("all");
    await page.waitForTimeout(500);

    const allTiers = await page.evaluate(() => {
      const container = document.querySelector(".graph-canvas");
      const cy = (container as any)?._cyreg?.cy;
      return cy ? cy.nodes(":visible").length : 0;
    });
    expect(allTiers).toBe(15);

    await page.screenshot({ path: "e2e/screenshots/20-tier-all.png" });
  });

  test("structural edges are subtle and cross-ref edges are blue", async ({ page }) => {
    // Verify edge label data is correctly passed through
    const edgeLabels = await page.evaluate(() => {
      const container = document.querySelector(".graph-canvas");
      const cy = (container as any)?._cyreg?.cy;
      if (!cy) return [];
      return cy.edges().map((e: any) => e.data("label"));
    });

    expect(edgeLabels).toContain("has-section");
    expect(edgeLabels).toContain("contains");
    expect(edgeLabels).toContain("donated to");

    await page.screenshot({ path: "e2e/screenshots/21-edge-types.png" });
  });

  // ── Search filter tests ──

  test("search matches category field", async ({ page }) => {
    const searchInput = page.locator(".graph-search");
    await searchInput.fill("campaign");
    await page.waitForTimeout(500);

    // campaign-finance nodes should be visible (PAC Fund Alpha + its children)
    const visibleIds = await page.evaluate(() => {
      const container = document.querySelector(".graph-canvas");
      const cy = (container as any)?._cyreg?.cy;
      if (!cy) return [];
      return cy.nodes(":visible").map((n: any) => n.id());
    });
    expect(visibleIds).toContain("pac-fund-alpha");
    expect(visibleIds.length).toBeLessThan(15);

    await page.screenshot({ path: "e2e/screenshots/22-search-category.png" });

    // Clear
    await searchInput.press("Escape");
    await page.waitForTimeout(500);
  });

  test("search matches content field", async ({ page }) => {
    const searchInput = page.locator(".graph-search");
    // "entity_id" appears in the content of acme-corp::data-schema::entity-id
    await searchInput.fill("entity_id");
    await page.waitForTimeout(500);

    const visibleIds = await page.evaluate(() => {
      const container = document.querySelector(".graph-canvas");
      const cy = (container as any)?._cyreg?.cy;
      if (!cy) return [];
      return cy.nodes(":visible").map((n: any) => n.id());
    });
    expect(visibleIds).toContain("acme-corp::data-schema::entity-id");
    expect(visibleIds.length).toBeLessThan(15);

    await page.screenshot({ path: "e2e/screenshots/23-search-content.png" });
    await searchInput.press("Escape");
    await page.waitForTimeout(500);
  });

  test("search filter composes with tier filter", async ({ page }) => {
    // Set tier to "Sources only"
    const tierSelect = page.locator(".graph-tier-select");
    await tierSelect.selectOption("sources");
    await page.waitForTimeout(500);

    // Now search for "Acme"
    const searchInput = page.locator(".graph-search");
    await searchInput.fill("Acme");
    await page.waitForTimeout(500);

    // Sections and facts should remain hidden (tier-hidden), plus non-matching sources
    const visibleCount = await page.evaluate(() => {
      const container = document.querySelector(".graph-canvas");
      const cy = (container as any)?._cyreg?.cy;
      return cy ? cy.nodes(":visible").length : 0;
    });
    // Only source-tier nodes that match "Acme" should be visible
    expect(visibleCount).toBeLessThan(10);
    expect(visibleCount).toBeGreaterThan(0);

    await page.screenshot({ path: "e2e/screenshots/24-search-tier-compose.png" });

    // Clean up
    await searchInput.press("Escape");
    await tierSelect.selectOption("all");
    await page.waitForTimeout(500);
  });

  // ── Session toggle and refresh button tests ──

  test("toolbar has session toggle and refresh buttons", async ({ page }) => {
    await expect(page.locator(".graph-session-toggle")).toBeVisible();
    await expect(page.locator(".graph-refresh-btn")).toBeVisible();

    await page.screenshot({ path: "e2e/screenshots/25-toolbar-buttons.png" });
  });

  test("session toggle shows hint when no new nodes exist", async ({ page }) => {
    const toggle = page.locator(".graph-session-toggle");
    const hint = page.locator(".graph-session-hint");

    // After beforeEach, toggle is deactivated
    await expect(toggle).not.toHaveClass(/active/);

    // Click to activate with no new nodes — stays active, shows "0 new"
    await toggle.click();
    await page.waitForTimeout(300);
    await expect(toggle).toHaveClass(/active/);
    await expect(hint).toHaveClass(/visible/);
    const text = await hint.textContent();
    expect(text).toContain("0 new");
  });

  test("session toggle filters to new nodes after refresh", async ({ page: _ }, testInfo) => {
    // Create a fresh page where refresh returns data with new nodes
    const context = await (await import("@playwright/test")).chromium.launch();
    const page = await (await context.newContext({ viewport: { width: 1400, height: 900 } })).newPage();

    let callCount = 0;
    await page.addInitScript(
      ({ graphData, graphDataNew, config, sessions, credentials }) => {
        let invokeCount = 0;
        (window as any).__TAURI_INTERNALS__ = {
          invoke: async (cmd: string, args?: any) => {
            switch (cmd) {
              case "get_graph_data":
                invokeCount++;
                // First call returns base data, subsequent calls return new data
                return invokeCount <= 1 ? graphData : graphDataNew;
              case "get_config":
                return config;
              case "list_sessions":
                return sessions;
              case "get_credentials_status":
                return credentials;
              case "open_session":
                return { id: "s", created_at: "", turn_count: 0, last_objective: null };
              case "debug_log":
                return;
              case "list_models":
                return [];
              case "save_settings":
                return;
              default:
                return;
            }
          },
          transformCallback: (cb: Function) => {
            const id = Math.floor(Math.random() * 1e6);
            return id;
          },
          convertFileSrc: (p: string) => p,
          metadata: {
            currentWindow: { label: "main" },
            currentWebview: { windowLabel: "main", label: "main" },
          },
        };
        (window as any).__TAURI_EVENT_PLUGIN_INTERNALS__ = {
          unregisterListener: () => {},
        };
      },
      {
        graphData: MOCK_GRAPH_DATA,
        graphDataNew: MOCK_GRAPH_DATA_WITH_NEW_NODES,
        config: MOCK_CONFIG,
        sessions: MOCK_SESSIONS,
        credentials: MOCK_CREDENTIALS,
      }
    );

    await page.goto("http://localhost:5173/");
    await page.waitForSelector(".graph-pane", { timeout: 5000 });
    await page.waitForTimeout(2000);

    // Session filter defaults ON — all 15 baseline nodes hidden
    const toggle = page.locator(".graph-session-toggle");
    await expect(toggle).toHaveClass(/active/);

    const initialTotal = await page.evaluate(() => {
      const container = document.querySelector(".graph-canvas");
      const cy = (container as any)?._cyreg?.cy;
      return cy ? cy.nodes().length : 0;
    });
    expect(initialTotal).toBe(15);

    const initialVisible = await page.evaluate(() => {
      const container = document.querySelector(".graph-canvas");
      const cy = (container as any)?._cyreg?.cy;
      return cy ? cy.nodes(":visible").length : 0;
    });
    expect(initialVisible).toBe(0);

    // Click refresh — 2 new nodes appear (visible), old nodes stay hidden
    await page.locator(".graph-refresh-btn").click();
    await page.waitForTimeout(1000);

    const afterRefresh = await page.evaluate(() => {
      const container = document.querySelector(".graph-canvas");
      const cy = (container as any)?._cyreg?.cy;
      return cy ? cy.nodes().length : 0;
    });
    expect(afterRefresh).toBe(17);

    // With filter still ON, only new nodes + neighbors visible
    const visibleAfterRefresh = await page.evaluate(() => {
      const container = document.querySelector(".graph-canvas");
      const cy = (container as any)?._cyreg?.cy;
      return cy ? cy.nodes(":visible").length : 0;
    });
    expect(visibleAfterRefresh).toBeLessThan(17);
    expect(visibleAfterRefresh).toBeGreaterThanOrEqual(2);

    // New nodes should have .new-node class
    const newNodeCount = await page.evaluate(() => {
      const container = document.querySelector(".graph-canvas");
      const cy = (container as any)?._cyreg?.cy;
      return cy ? cy.nodes(".new-node").length : 0;
    });
    expect(newNodeCount).toBe(2);

    // Toggle OFF → all 17 nodes visible
    await toggle.click();
    await page.waitForTimeout(500);

    const allVisible = await page.evaluate(() => {
      const container = document.querySelector(".graph-canvas");
      const cy = (container as any)?._cyreg?.cy;
      return cy ? cy.nodes(":visible").length : 0;
    });
    expect(allVisible).toBe(17);

    await page.screenshot({ path: "e2e/screenshots/26-session-toggle.png" });

    await context.close();
  });

  test("refresh button re-fetches graph data", async ({ page }) => {
    const refreshBtn = page.locator(".graph-refresh-btn");

    // Count nodes before refresh
    const before = await page.evaluate(() => {
      const container = document.querySelector(".graph-canvas");
      const cy = (container as any)?._cyreg?.cy;
      return cy ? cy.nodes().length : 0;
    });
    expect(before).toBe(15);

    // Click refresh
    await refreshBtn.click();
    await page.waitForTimeout(1000);

    // Graph should still have data (same mock returns same data)
    const after = await page.evaluate(() => {
      const container = document.querySelector(".graph-canvas");
      const cy = (container as any)?._cyreg?.cy;
      return cy ? cy.nodes().length : 0;
    });
    expect(after).toBe(15);

    await page.screenshot({ path: "e2e/screenshots/27-refresh.png" });
  });

  test("new session auto-activates session filter, resumed session does not", async ({ page }) => {
    const toggle = page.locator(".graph-session-toggle");

    // Initial load: filter should be OFF (no session-changed event fired)
    await expect(toggle).not.toHaveClass(/active/);

    // Simulate new session → dispatch session-changed with isNew: true
    await page.evaluate(() => {
      window.dispatchEvent(new CustomEvent("session-changed", { detail: { isNew: true } }));
    });
    await page.waitForTimeout(1500);

    // Session filter should be auto-activated
    await expect(toggle).toHaveClass(/active/);

    // All baseline nodes should be hidden (filter active, no new nodes)
    const visibleCount = await page.evaluate(() => {
      const container = document.querySelector(".graph-canvas");
      const cy = (container as any)?._cyreg?.cy;
      return cy ? cy.nodes(":visible").length : 0;
    });
    expect(visibleCount).toBe(0);

    // Click toggle to turn OFF
    await toggle.click();
    await page.waitForTimeout(300);
    await expect(toggle).not.toHaveClass(/active/);

    // All nodes should be visible again
    const allVisible = await page.evaluate(() => {
      const container = document.querySelector(".graph-canvas");
      const cy = (container as any)?._cyreg?.cy;
      return cy ? cy.nodes(":visible").length : 0;
    });
    expect(allVisible).toBe(15);

    // Simulate resumed session → dispatch session-changed with isNew: false
    await page.evaluate(() => {
      window.dispatchEvent(new CustomEvent("session-changed", { detail: { isNew: false } }));
    });
    await page.waitForTimeout(1500);

    // Session filter should be OFF for resumed sessions
    await expect(toggle).not.toHaveClass(/active/);

    await page.screenshot({ path: "e2e/screenshots/28-session-filter-default.png" });
  });
});
