/**
 * E2E: Tool card status lifecycle — pending, running, success, error, approval.
 */
import { test, expect } from "@playwright/test";
import {
  openHarness,
  bootstrap,
  injectServerMessage,
  injectSequence,
} from "./helpers";
import { toolApproval, resetCounters } from "../src/test-harness/scenarios";

test.beforeEach(async ({ page }) => {
  resetCounters();
  await openHarness(page);
  await bootstrap(page);
});

test("tool badge transitions through pending -> running -> success", async ({
  page,
}) => {
  const callId = "lifecycle_test_1";

  // Inject stream start
  await injectServerMessage(page, { type: "stream_start" });

  // Step 1: pending
  await injectServerMessage(page, {
    type: "store",
    event: "tool_state_updated",
    data: {
      call_id: callId,
      tool_name: "read_file",
      status: "pending",
      arguments: { file_path: "test.py" },
      args_summary: "test.py",
    },
  });
  const badge = page.locator(".tool-card .tool-badge").first();
  await expect(badge).toHaveClass(/pending/, { timeout: 3_000 });

  // Step 2: running
  await injectServerMessage(page, {
    type: "store",
    event: "tool_state_updated",
    data: {
      call_id: callId,
      tool_name: "read_file",
      status: "running",
      arguments: { file_path: "test.py" },
      args_summary: "test.py",
    },
  });
  await expect(badge).toHaveClass(/running/, { timeout: 3_000 });

  // Step 3: success
  await injectServerMessage(page, {
    type: "store",
    event: "tool_state_updated",
    data: {
      call_id: callId,
      tool_name: "read_file",
      status: "success",
      arguments: { file_path: "test.py" },
      result: "file contents here",
      duration_ms: 55,
    },
  });
  await expect(badge).toHaveClass(/success/, { timeout: 3_000 });
  await expect(badge).toContainText("success");
});

test("tool card shows error badge on failure", async ({ page }) => {
  const callId = "error_test_1";

  await injectServerMessage(page, { type: "stream_start" });
  await injectServerMessage(page, {
    type: "store",
    event: "tool_state_updated",
    data: {
      call_id: callId,
      tool_name: "run_command",
      status: "running",
      arguments: { command: "bad-command" },
      args_summary: "bad-command",
    },
  });

  await injectServerMessage(page, {
    type: "store",
    event: "tool_state_updated",
    data: {
      call_id: callId,
      tool_name: "run_command",
      status: "error",
      arguments: { command: "bad-command" },
      error: "Command not found: bad-command",
      duration_ms: 100,
    },
  });

  const badge = page.locator(".tool-card .tool-badge").first();
  await expect(badge).toHaveClass(/error/, { timeout: 3_000 });
});

test("tool card shows duration when available", async ({ page }) => {
  await injectServerMessage(page, { type: "stream_start" });
  await injectServerMessage(page, {
    type: "store",
    event: "tool_state_updated",
    data: {
      call_id: "duration_test_1",
      tool_name: "read_file",
      status: "success",
      arguments: { file_path: "foo.py" },
      result: "contents",
      duration_ms: 1234,
    },
  });

  const duration = page.locator(".tool-card .tool-duration").first();
  await expect(duration).toBeVisible({ timeout: 3_000 });
  // Duration should be formatted (e.g. "1.2s" or "1234ms")
  await expect(duration).not.toBeEmpty();
});

test("awaiting_approval tool shows Accept and Reject buttons", async ({
  page,
}) => {
  await injectSequence(page, toolApproval());

  const card = page.locator(".tool-card").first();
  await expect(card).toBeVisible({ timeout: 5_000 });

  // Should show approval buttons
  const approveBtn = card.locator(".btn-approve");
  const rejectBtn = card.locator(".btn-reject");
  await expect(approveBtn).toBeVisible({ timeout: 3_000 });
  await expect(rejectBtn).toBeVisible();
  await expect(approveBtn).toContainText("Accept");
  await expect(rejectBtn).toContainText("Reject");
});

test("awaiting_approval badge has correct class", async ({ page }) => {
  await injectSequence(page, toolApproval());

  const badge = page.locator(".tool-card .tool-badge").first();
  await expect(badge).toHaveClass(/awaiting_approval/, { timeout: 5_000 });
});

test("approval section includes feedback textarea", async ({ page }) => {
  await injectSequence(page, toolApproval());

  const textarea = page.locator(".tool-card .tool-feedback-textarea").first();
  await expect(textarea).toBeVisible({ timeout: 5_000 });
  await expect(textarea).toHaveAttribute(
    "placeholder",
    /Feedback for the agent/,
  );
});
