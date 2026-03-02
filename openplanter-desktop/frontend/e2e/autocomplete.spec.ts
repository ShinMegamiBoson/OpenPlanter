import { test, expect, type Page } from "@playwright/test";
import {
  MOCK_GRAPH_DATA,
  MOCK_CONFIG,
  MOCK_SESSIONS,
  MOCK_CREDENTIALS,
} from "./fixtures/graph-data";

async function injectTauriMocks(page: Page) {
  await page.addInitScript(
    ({ graphData, config, sessions, credentials }) => {
      (window as any).__TAURI_INTERNALS__ = {
        invoke: async (cmd: string, _args?: any) => {
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
            case "save_settings":
            case "solve":
            case "cancel":
            case "list_models":
            case "get_session_history":
              return;
            default:
              return;
          }
        },
        transformCallback: (callback: Function, _once = false) => {
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
    },
  );
}

test.describe("Autocomplete", () => {
  test.beforeEach(async ({ page }) => {
    await injectTauriMocks(page);
    await page.goto("/");
    await page.waitForSelector(".chat-pane", { timeout: 5000 });
    await page.waitForTimeout(500);
  });

  test("typing / shows autocomplete popup with all commands", async ({
    page,
  }) => {
    const textarea = page.locator(".input-bar textarea");
    await textarea.focus();
    await textarea.fill("/");

    const popup = page.locator(".autocomplete-popup");
    await expect(popup).toBeVisible();

    const items = popup.locator(".autocomplete-item");
    const count = await items.count();
    expect(count).toBeGreaterThanOrEqual(8); // /help, /new, /clear, /quit, /exit, /status, /model, /reasoning

    // Verify some expected values
    const values = await popup
      .locator(".autocomplete-value")
      .allTextContents();
    expect(values).toContain("/help");
    expect(values).toContain("/model");
    expect(values).toContain("/reasoning");

    await page.screenshot({
      path: "e2e/screenshots/40-autocomplete-slash.png",
    });
  });

  test("typing /mo filters to /model", async ({ page }) => {
    const textarea = page.locator(".input-bar textarea");
    await textarea.focus();
    await textarea.fill("/mo");

    const popup = page.locator(".autocomplete-popup");
    await expect(popup).toBeVisible();

    const items = popup.locator(".autocomplete-item");
    expect(await items.count()).toBe(1);

    const value = popup.locator(".autocomplete-value").first();
    await expect(value).toHaveText("/model");

    await page.screenshot({
      path: "e2e/screenshots/41-autocomplete-filter.png",
    });
  });

  test("Tab accepts /model and shows subcommands", async ({ page }) => {
    const textarea = page.locator(".input-bar textarea");
    await textarea.focus();
    await textarea.fill("/mo");

    await page.keyboard.press("Tab");

    // Textarea should now contain "/model "
    const val = await textarea.inputValue();
    expect(val).toBe("/model ");

    // Popup should show model subcommands
    const popup = page.locator(".autocomplete-popup");
    await expect(popup).toBeVisible();

    const values = await popup
      .locator(".autocomplete-value")
      .allTextContents();
    expect(values).toContain("list");
    expect(values).toContain("opus");

    await page.screenshot({
      path: "e2e/screenshots/42-autocomplete-model-children.png",
    });
  });

  test("ArrowDown navigates and Tab accepts selected item", async ({
    page,
  }) => {
    const textarea = page.locator(".input-bar textarea");
    await textarea.focus();
    await textarea.fill("/model ");

    const popup = page.locator(".autocomplete-popup");
    await expect(popup).toBeVisible();

    // Move down to select second item
    await page.keyboard.press("ArrowDown");

    const selectedItems = popup.locator(".autocomplete-item.selected");
    expect(await selectedItems.count()).toBe(1);

    // Accept with Tab
    await page.keyboard.press("Tab");

    const val = await textarea.inputValue();
    // Should have accepted the second child of /model
    expect(val.startsWith("/model ")).toBe(true);
    expect(val.length).toBeGreaterThan("/model ".length);
  });

  test("Escape dismisses popup", async ({ page }) => {
    const textarea = page.locator(".input-bar textarea");
    await textarea.focus();
    await textarea.fill("/");

    const popup = page.locator(".autocomplete-popup");
    await expect(popup).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(popup).not.toBeVisible();
  });

  test("/help + Enter submits (auto-hide rule)", async ({ page }) => {
    const textarea = page.locator(".input-bar textarea");
    await textarea.focus();
    await textarea.fill("/help");

    // Popup should be hidden (auto-hide: single exact match, no children)
    const popup = page.locator(".autocomplete-popup");
    await expect(popup).not.toBeVisible();

    // Enter should submit the command directly
    await page.keyboard.press("Enter");

    // Should produce a system message with help text
    const msg = page.locator('.message.system:has-text("Available commands")');
    await expect(msg).toBeVisible();
  });

  test("empty textarea + ArrowUp does not show popup", async ({ page }) => {
    const textarea = page.locator(".input-bar textarea");
    await textarea.focus();

    await page.keyboard.press("ArrowUp");

    const popup = page.locator(".autocomplete-popup");
    await expect(popup).not.toBeVisible();
  });

  test("clicking an item accepts it", async ({ page }) => {
    const textarea = page.locator(".input-bar textarea");
    await textarea.focus();
    await textarea.fill("/");

    const popup = page.locator(".autocomplete-popup");
    await expect(popup).toBeVisible();

    // Click on /help
    const helpItem = popup.locator(
      '.autocomplete-item:has(.autocomplete-value:text-is("/help"))',
    );
    await helpItem.click();

    const val = await textarea.inputValue();
    expect(val).toBe("/help");
  });

  test("/model list shows provider filters", async ({ page }) => {
    const textarea = page.locator(".input-bar textarea");
    await textarea.focus();
    await textarea.fill("/model list ");

    const popup = page.locator(".autocomplete-popup");
    await expect(popup).toBeVisible();

    const values = await popup
      .locator(".autocomplete-value")
      .allTextContents();
    expect(values).toContain("all");
    expect(values).toContain("openai");
    expect(values).toContain("anthropic");
    expect(values).toContain("ollama");

    await page.screenshot({
      path: "e2e/screenshots/43-autocomplete-providers.png",
    });
  });

  test("/reasoning shows level options", async ({ page }) => {
    const textarea = page.locator(".input-bar textarea");
    await textarea.focus();
    await textarea.fill("/reasoning ");

    const popup = page.locator(".autocomplete-popup");
    await expect(popup).toBeVisible();

    const values = await popup
      .locator(".autocomplete-value")
      .allTextContents();
    expect(values).toEqual(["low", "medium", "high", "off"]);

    await page.screenshot({
      path: "e2e/screenshots/44-autocomplete-reasoning.png",
    });
  });

  test("popup hides for non-slash input", async ({ page }) => {
    const textarea = page.locator(".input-bar textarea");
    await textarea.focus();
    await textarea.fill("hello world");

    const popup = page.locator(".autocomplete-popup");
    await expect(popup).not.toBeVisible();
  });
});
