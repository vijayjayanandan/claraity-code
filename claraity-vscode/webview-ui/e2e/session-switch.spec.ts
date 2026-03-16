/**
 * E2E: Session switch clears stale content and reinitializes.
 */
import { test, expect } from "@playwright/test";
import {
  openHarness,
  bootstrap,
  injectSequence,
  injectMessage,
  chatHistory,
} from "./helpers";
import { basicChat, resetCounters } from "../src/test-harness/scenarios";

test.beforeEach(async ({ page }) => {
  resetCounters();
  await openHarness(page);
  await bootstrap(page);
});

test("session switch clears existing messages", async ({ page }) => {
  // Inject a basic chat to populate timeline
  await injectSequence(page, basicChat());

  // Verify content rendered
  await expect(page.locator(".streaming-dots")).toHaveCount(0, { timeout: 5_000 });
  const assistantMsg = chatHistory(page).locator(".message.assistant").first();
  await expect(assistantMsg).toContainText("ClarAIty");

  // Switch session — new sessionInfo should clear timeline
  await injectMessage(page, {
    type: "sessionInfo",
    sessionId: "test-session-002",
    model: "gpt-4o-mini",
    permissionMode: "strict",
  });

  // Timeline should be cleared — no assistant messages from old session
  // Give React a tick to process
  await page.waitForTimeout(200);
  const oldMessages = chatHistory(page).locator(".message.assistant");
  await expect(oldMessages).toHaveCount(0);
});

test("new messages render after session switch", async ({ page }) => {
  // Populate session 1
  await injectSequence(page, basicChat());
  await expect(page.locator(".streaming-dots")).toHaveCount(0, { timeout: 5_000 });

  // Switch to session 2
  await injectMessage(page, {
    type: "sessionInfo",
    sessionId: "test-session-002",
    model: "gpt-4o-mini",
    permissionMode: "strict",
  });
  await page.waitForTimeout(200);

  // Send new messages in session 2
  await injectSequence(page, [
    {
      msg: {
        type: "serverMessage",
        payload: { type: "stream_start" },
      },
    },
    {
      msg: {
        type: "serverMessage",
        payload: { type: "text_delta", content: "Welcome to session 2!" },
      },
      delayMs: 50,
    },
    {
      msg: {
        type: "serverMessage",
        payload: {
          type: "stream_end",
          tool_calls: 0,
          elapsed_s: 0.5,
          total_tokens: 50,
          duration_ms: 500,
        },
      },
    },
  ]);

  await expect(page.locator(".streaming-dots")).toHaveCount(0, { timeout: 5_000 });

  // Only session 2 content should be visible
  const messages = chatHistory(page).locator(".message.assistant");
  await expect(messages).toHaveCount(1, { timeout: 3_000 });
  await expect(messages.first()).toContainText("session 2");
});

test("no stale tool cards after session switch", async ({ page }) => {
  // Populate with tool scenario
  resetCounters();
  const { toolExecution } = await import("../src/test-harness/scenarios");
  await injectSequence(page, toolExecution());
  await expect(page.locator(".streaming-dots")).toHaveCount(0, { timeout: 5_000 });

  // Verify tool card exists
  await expect(page.locator(".tool-card")).toHaveCount(1, { timeout: 3_000 });

  // Switch session
  await injectMessage(page, {
    type: "sessionInfo",
    sessionId: "test-session-003",
    model: "gpt-4o",
    permissionMode: "normal",
  });
  await page.waitForTimeout(200);

  // No tool cards should remain
  await expect(page.locator(".tool-card")).toHaveCount(0);
});
