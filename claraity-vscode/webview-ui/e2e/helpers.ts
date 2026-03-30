/**
 * Shared E2E test utilities for Playwright specs.
 */
import { type Page, expect } from "@playwright/test";
import type { ExtensionMessage } from "../src/types";

/** Navigate to the harness and wait for React to mount. */
export async function openHarness(page: Page): Promise<void> {
  await page.goto("/");
  // Wait for React root to render the .app container
  await page.locator(".app").waitFor({ state: "visible", timeout: 10_000 });
}

/** Inject connectionStatus + sessionInfo so the app is in a usable state. */
export async function bootstrap(
  page: Page,
  sessionId = "test-session-001",
): Promise<void> {
  await injectMessage(page, {
    type: "connectionStatus",
    status: "connected",
  });
  await injectMessage(page, {
    type: "sessionInfo",
    sessionId,
    model: "gpt-4o",
    permissionMode: "normal",
  });
}

/** Inject a single ExtensionMessage via the global helper. */
export async function injectMessage(
  page: Page,
  msg: ExtensionMessage,
): Promise<void> {
  await page.evaluate((m) => window.__claraityInject(m), msg);
}

/** Inject a sequence of messages with optional inter-message delays. */
export async function injectSequence(
  page: Page,
  steps: Array<{ msg: ExtensionMessage; delayMs?: number }>,
): Promise<void> {
  await page.evaluate((s) => window.__claraityInjectSequence(s), steps);
}

/** Inject a ServerMessage wrapped in the ExtensionMessage envelope. */
export async function injectServerMessage(
  page: Page,
  payload: ExtensionMessage extends { type: "serverMessage"; payload: infer P }
    ? P
    : never,
): Promise<void> {
  await injectMessage(page, { type: "serverMessage", payload });
}

/** Get the chat-history container locator. */
export function chatHistory(page: Page) {
  return page.locator(".chat-history");
}

/**
 * Wait until the timeline contains at least `count` direct child elements
 * (messages, tool cards, etc.).
 */
export async function waitForTimeline(
  page: Page,
  count: number,
  timeout = 5_000,
): Promise<void> {
  await expect(chatHistory(page).locator("> *")).toHaveCount(count, {
    timeout,
  });
}

/**
 * Wait for at least `count` children and return all direct child elements.
 * Useful for checking ordering.
 */
export async function getTimelineChildren(page: Page, minCount: number) {
  await expect(
    chatHistory(page).locator("> *"),
  ).toHaveCount(minCount, { timeout: 5_000 });
  return chatHistory(page).locator("> *");
}

/** Wait for a tool card with a specific tool name to appear. */
export async function waitForToolCard(
  page: Page,
  toolName: string,
  timeout = 5_000,
) {
  const card = page.locator(`.tool-card:has(.tool-name:text("${toolName}"))`);
  await card.first().waitFor({ state: "visible", timeout });
  return card;
}

/** Wait for a tool badge with a specific status. */
export async function waitForToolStatus(
  page: Page,
  toolName: string,
  status: string,
  timeout = 5_000,
) {
  const badge = page.locator(
    `.tool-card:has(.tool-name:text("${toolName}")) .tool-badge.${status}`,
  );
  await badge.first().waitFor({ state: "visible", timeout });
  return badge;
}

/** Shorthand: inject bootstrap + a scenario's steps, wait for streaming to finish. */
export async function runScenario(
  page: Page,
  steps: Array<{ msg: ExtensionMessage; delayMs?: number }>,
): Promise<void> {
  await bootstrap(page);
  await injectSequence(page, steps);
}
