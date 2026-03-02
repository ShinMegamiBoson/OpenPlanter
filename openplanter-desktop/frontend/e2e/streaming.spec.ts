import { test, expect, type Page } from "@playwright/test";
import {
  MOCK_GRAPH_DATA,
  MOCK_CONFIG,
  MOCK_SESSIONS,
  MOCK_CREDENTIALS,
} from "./fixtures/graph-data";

/** Inject Tauri IPC mocks with event dispatch support. */
async function injectTauriMocks(page: Page) {
  await page.addInitScript(
    ({ graphData, config, sessions, credentials }) => {
      // Store event listeners so we can fire events from tests
      const listeners: Record<string, Function[]> = {};

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
                id: "test-session",
                created_at: new Date().toISOString(),
                turn_count: 0,
                last_objective: null,
              };
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

/** Dispatch an agent-delta CustomEvent inside the page. */
async function sendDelta(page: Page, kind: string, text: string) {
  await page.evaluate(
    ({ kind, text }) => {
      window.dispatchEvent(
        new CustomEvent("agent-delta", { detail: { kind, text } })
      );
    },
    { kind, text }
  );
}

/** Dispatch an agent-step CustomEvent inside the page. */
async function sendStep(
  page: Page,
  step: number,
  inputTokens: number,
  outputTokens: number
) {
  await page.evaluate(
    ({ step, inputTokens, outputTokens }) => {
      window.dispatchEvent(
        new CustomEvent("agent-step", {
          detail: {
            step,
            depth: 0,
            tokens: {
              input_tokens: inputTokens,
              output_tokens: outputTokens,
            },
            elapsed_ms: 5000,
            is_final: false,
            tool_name: null,
          },
        })
      );
    },
    { step, inputTokens, outputTokens }
  );
}

test.describe("Streaming Display", () => {
  test.beforeEach(async ({ page }) => {
    await injectTauriMocks(page);
    await page.goto("/");
    await page.waitForSelector(".chat-pane", { timeout: 5000 });
    await page.waitForTimeout(500);
  });

  test("activity indicator appears during thinking", async ({ page }) => {
    await sendDelta(page, "thinking", "Let me analyze this...");

    const indicator = page.locator(".activity-indicator");
    await expect(indicator).toBeVisible();
    expect(await indicator.getAttribute("data-mode")).toBe("thinking");

    const label = page.locator(".activity-label");
    await expect(label).toHaveText("Thinking...");

    const preview = page.locator(".activity-preview");
    const previewText = await preview.textContent();
    expect(previewText).toContain("analyze");

    await page.screenshot({
      path: "e2e/screenshots/30-activity-thinking.png",
    });
  });

  test("activity indicator transitions to streaming on text", async ({
    page,
  }) => {
    await sendDelta(page, "thinking", "analyzing...");
    await sendDelta(page, "text", "The answer is ");
    await sendDelta(page, "text", "42.");

    const indicator = page.locator(".activity-indicator");
    await expect(indicator).toBeVisible();
    expect(await indicator.getAttribute("data-mode")).toBe("streaming");

    const label = page.locator(".activity-label");
    await expect(label).toHaveText("Responding...");

    await page.screenshot({
      path: "e2e/screenshots/31-activity-streaming.png",
    });
  });

  test("activity indicator shows tool generation and running", async ({
    page,
  }) => {
    await sendDelta(page, "tool_call_start", "read_file");

    let indicator = page.locator(".activity-indicator");
    await expect(indicator).toBeVisible();
    expect(await indicator.getAttribute("data-mode")).toBe("tool_args");

    const label = page.locator(".activity-label");
    await expect(label).toHaveText("Generating read_file...");

    // Send args with key arg
    await sendDelta(
      page,
      "tool_call_args",
      '{"path": "/src/main.ts"}'
    );

    // Should transition to "Running" mode
    expect(await indicator.getAttribute("data-mode")).toBe("tool");
    await expect(label).toHaveText("Running read_file...");

    const preview = page.locator(".activity-preview");
    await expect(preview).toHaveText("/src/main.ts");

    await page.screenshot({
      path: "e2e/screenshots/32-activity-tool-running.png",
    });
  });

  test("step summary replaces activity indicator", async ({ page }) => {
    // Simulate a complete step
    await sendDelta(page, "text", "The analysis shows the code is correct.");
    await sendDelta(page, "tool_call_start", "read_file");
    await sendDelta(
      page,
      "tool_call_args",
      '{"path": "/src/main.ts"}'
    );

    // Activity indicator should be visible
    await expect(page.locator(".activity-indicator")).toBeVisible();

    // Fire step event
    await sendStep(page, 1, 12300, 2100);

    // Activity indicator should be gone
    await expect(page.locator(".activity-indicator")).not.toBeVisible();

    // Step summary should be rendered
    const summary = page.locator(".message.step-summary");
    await expect(summary).toBeVisible();

    // Check header
    const header = page.locator(".step-header-line");
    const headerText = await header.textContent();
    expect(headerText).toContain("Step 1");
    expect(headerText).toContain("12.3k in");
    expect(headerText).toContain("2.1k out");

    // Check model text preview
    const modelText = page.locator(".step-model-text");
    await expect(modelText).toBeVisible();
    const modelContent = await modelText.textContent();
    expect(modelContent).toContain("analysis shows");

    // Check tool tree
    const toolLines = page.locator(".step-tool-line");
    await expect(toolLines).toHaveCount(1);
    const toolText = await toolLines.first().textContent();
    expect(toolText).toContain("read_file");
    expect(toolText).toContain("/src/main.ts");

    await page.screenshot({
      path: "e2e/screenshots/33-step-summary.png",
    });
  });

  test("multiple tool calls appear in step summary tool tree", async ({
    page,
  }) => {
    await sendDelta(page, "text", "Let me check a few files.");
    await sendDelta(page, "tool_call_start", "read_file");
    await sendDelta(
      page,
      "tool_call_args",
      '{"path": "/src/main.ts"}'
    );
    await sendDelta(page, "tool_call_start", "run_shell");
    await sendDelta(
      page,
      "tool_call_args",
      '{"command": "npm test"}'
    );

    await sendStep(page, 1, 8000, 1500);

    const toolLines = page.locator(".step-tool-line");
    await expect(toolLines).toHaveCount(2);

    // First tool: ├─ connector
    const first = await toolLines.nth(0).textContent();
    expect(first).toContain("read_file");
    expect(first).toContain("/src/main.ts");

    // Last tool: └─ connector, has .last class
    const last = toolLines.nth(1);
    await expect(last).toHaveClass(/last/);
    const lastText = await last.textContent();
    expect(lastText).toContain("run_shell");
    expect(lastText).toContain("npm test");

    await page.screenshot({
      path: "e2e/screenshots/34-step-summary-multi-tools.png",
    });
  });

  test("elapsed time updates in activity indicator", async ({ page }) => {
    await sendDelta(page, "thinking", "processing...");

    const elapsed = page.locator(".activity-elapsed");
    await expect(elapsed).toBeVisible();

    // Wait a bit and check elapsed updates
    await page.waitForTimeout(1200);
    const text = await elapsed.textContent();
    // Should show >= 1s
    expect(text).toMatch(/[1-9]/);

    await page.screenshot({
      path: "e2e/screenshots/35-activity-elapsed.png",
    });
  });
});
