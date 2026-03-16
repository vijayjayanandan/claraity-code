/**
 * E2E: Subagent cards with nested tool rendering.
 */
import { test, expect } from "@playwright/test";
import {
  openHarness,
  bootstrap,
  injectSequence,
  chatHistory,
} from "./helpers";
import { subagentDelegation, resetCounters } from "../src/test-harness/scenarios";

test.beforeEach(async ({ page }) => {
  resetCounters();
  await openHarness(page);
  await bootstrap(page);
});

test("subagent card renders with correct name", async ({ page }) => {
  await injectSequence(page, subagentDelegation());

  await expect(page.locator(".streaming-dots")).toHaveCount(0, { timeout: 5_000 });

  // SubagentCard wraps a .tool-card — find it by the SA icon
  const saCard = page.locator(".tool-card:has(.tool-icon:text('SA'))");
  await expect(saCard).toBeVisible({ timeout: 5_000 });

  // Subagent name should appear in the summary-level tool-name
  await expect(saCard.locator("> details > summary .tool-name")).toContainText("research");
});

test("subagent card contains nested tool cards", async ({ page }) => {
  await injectSequence(page, subagentDelegation());

  await expect(page.locator(".streaming-dots")).toHaveCount(0, { timeout: 5_000 });

  // The subagent card's <details> should contain nested tool cards
  const saCard = page.locator(".tool-card:has(.tool-icon:text('SA'))");
  await expect(saCard).toBeVisible({ timeout: 5_000 });

  const nestedTools = saCard.locator(".tool-card");
  await expect(nestedTools).toHaveCount(2, { timeout: 5_000 });
});

test("nested tools appear in correct order", async ({ page }) => {
  await injectSequence(page, subagentDelegation());

  await expect(page.locator(".streaming-dots")).toHaveCount(0, { timeout: 5_000 });

  const saCard = page.locator(".tool-card:has(.tool-icon:text('SA'))");
  const nestedTools = saCard.locator(".tool-card .tool-name");
  await expect(nestedTools).toHaveCount(2, { timeout: 5_000 });

  // First nested tool: web_search, second: read_file
  await expect(nestedTools.nth(0)).toContainText("web_search");
  await expect(nestedTools.nth(1)).toContainText("read_file");
});

test("subagent card shows done badge after unregistered", async ({ page }) => {
  await injectSequence(page, subagentDelegation());

  await expect(page.locator(".streaming-dots")).toHaveCount(0, { timeout: 5_000 });

  const saCard = page.locator(".tool-card:has(.tool-icon:text('SA'))");
  const badge = saCard.locator("> details > summary .tool-badge").first();
  await expect(badge).toHaveClass(/success/, { timeout: 5_000 });
  await expect(badge).toContainText("done");
});

test("assistant text appears before and after subagent card", async ({
  page,
}) => {
  await injectSequence(page, subagentDelegation());

  await expect(page.locator(".streaming-dots")).toHaveCount(0, { timeout: 5_000 });

  // Text before subagent
  const firstText = chatHistory(page).locator(".message.assistant").first();
  await expect(firstText).toContainText("delegate the research");

  // Text after subagent
  const lastText = chatHistory(page).locator(".message.assistant").last();
  await expect(lastText).toContainText("useful patterns");
});

test("subagent model name shown in parentheses", async ({ page }) => {
  await injectSequence(page, subagentDelegation());

  await expect(page.locator(".streaming-dots")).toHaveCount(0, { timeout: 5_000 });

  const saCard = page.locator(".tool-card:has(.tool-icon:text('SA'))");
  await expect(saCard.locator("> details > summary .tool-name")).toContainText("gpt-4o-mini");
});
