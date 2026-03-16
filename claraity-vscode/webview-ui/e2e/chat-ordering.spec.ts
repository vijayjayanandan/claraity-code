/**
 * E2E: Chat ordering — text, tool cards, and follow-up text appear in correct order.
 */
import { test, expect } from "@playwright/test";
import {
  openHarness,
  bootstrap,
  injectSequence,
  chatHistory,
} from "./helpers";
import { toolExecution, multipleTools, resetCounters } from "../src/test-harness/scenarios";

test.beforeEach(async ({ page }) => {
  resetCounters();
  await openHarness(page);
  await bootstrap(page);
});

test("text -> tool -> text renders in correct order", async ({ page }) => {
  await injectSequence(page, toolExecution());

  // Wait for stream to finish (stream_end removes streaming state)
  await expect(page.locator(".streaming-dots")).toHaveCount(0, { timeout: 5_000 });

  const children = chatHistory(page).locator("> *");

  // Should have: assistant_text, tool-card, assistant_text, turn-stats
  // (at minimum: text, tool, text)
  const count = await children.count();
  expect(count).toBeGreaterThanOrEqual(3);

  // First child: assistant text with "Let me read that file"
  const first = children.first();
  await expect(first).toHaveClass(/assistant/);
  await expect(first).toContainText("Let me read that file");

  // Second child: tool card for read_file
  const toolCard = page.locator(".tool-card").first();
  await expect(toolCard).toBeVisible();
  await expect(toolCard.locator(".tool-name")).toContainText("read_file");
  await expect(toolCard.locator(".tool-badge")).toHaveClass(/success/);

  // Third: follow-up assistant text
  const followUp = chatHistory(page).locator(".message.assistant").last();
  await expect(followUp).toContainText("simple main function");
});

test("tool card shows correct arguments summary", async ({ page }) => {
  await injectSequence(page, toolExecution());

  await expect(page.locator(".streaming-dots")).toHaveCount(0, { timeout: 5_000 });

  const toolArgs = page.locator(".tool-card .tool-args").first();
  await expect(toolArgs).toContainText("src/main.py");
});

test("multiple tools render in insertion order", async ({ page }) => {
  await injectSequence(page, multipleTools());

  await expect(page.locator(".streaming-dots")).toHaveCount(0, { timeout: 5_000 });

  // Three tool cards
  const toolCards = page.locator(".tool-card");
  await expect(toolCards).toHaveCount(3, { timeout: 5_000 });

  // Verify order by tool name
  await expect(toolCards.nth(0).locator(".tool-name")).toContainText("read_file");
  await expect(toolCards.nth(1).locator(".tool-name")).toContainText("list_files");
  await expect(toolCards.nth(2).locator(".tool-name")).toContainText("run_command");
});

test("multiple tools all show success status", async ({ page }) => {
  await injectSequence(page, multipleTools());

  await expect(page.locator(".streaming-dots")).toHaveCount(0, { timeout: 5_000 });

  const badges = page.locator(".tool-card .tool-badge");
  await expect(badges).toHaveCount(3, { timeout: 5_000 });

  for (let i = 0; i < 3; i++) {
    await expect(badges.nth(i)).toHaveClass(/success/);
  }
});

test("assistant text appears before and after tool cards", async ({ page }) => {
  await injectSequence(page, multipleTools());

  await expect(page.locator(".streaming-dots")).toHaveCount(0, { timeout: 5_000 });

  // First text: "I'll check three files."
  const textBefore = chatHistory(page).locator(".message.assistant").first();
  await expect(textBefore).toContainText("check three files");

  // Last text: "All three checks passed."
  const textAfter = chatHistory(page).locator(".message.assistant").last();
  await expect(textAfter).toContainText("All three checks passed");
});
