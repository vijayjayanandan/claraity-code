/**
 * Comprehensive unit tests for interactive widget components.
 *
 * Coverage:
 * - ToolCard: 9 tests (rendering, approval flow, diff, result, duration)
 * - PauseWidget: 7 tests (rendering, continue/stop, feedback toggle)
 * - ClarifyWidget: 7 tests (single/multi/open questions, submit/cancel, dismissed)
 * - PlanWidget: 6 tests (markdown rendering, truncation, approve/reject, dismissed)
 * - UndoBar: 3 tests (file info, undo message, disabled state)
 *
 * Total: 32 tests
 */
import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, within, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ToolCard } from "../components/ToolCard";
import { PauseWidget } from "../components/PauseWidget";
import { ClarifyWidget } from "../components/ClarifyWidget";
import { PlanWidget } from "../components/PlanWidget";
import { UndoBar } from "../components/UndoBar";
import type { ToolStateData, WebViewMessage } from "../types";

// ============================================================================
// ToolCard
// ============================================================================

describe("ToolCard", () => {
  let postMessage: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    postMessage = vi.fn();
  });

  function renderToolCard(overrides: Partial<ToolStateData> = {}) {
    const data: ToolStateData = {
      call_id: "call-1",
      tool_name: "read_file",
      status: "running",
      arguments: { file_path: "/src/main.py" },
      ...overrides,
    };
    return render(<ToolCard data={data} postMessage={postMessage} />);
  }

  test("renders tool name, icon, and status badge", () => {
    renderToolCard({ tool_name: "read_file", status: "success" });

    // Icon for read_file is "R"
    expect(screen.getByText("R")).toBeInTheDocument();
    // Tool name
    expect(screen.getByText("read_file")).toBeInTheDocument();
    // Status badge
    const badge = screen.getByText("success");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveClass("tool-badge", "success");
  });

  test("shows arguments summary via getPrimaryArg", () => {
    renderToolCard({
      tool_name: "read_file",
      arguments: { file_path: "/src/utils.ts" },
    });

    // getPrimaryArg returns file_path for read_file
    expect(screen.getByText("/src/utils.ts")).toBeInTheDocument();
  });

  test("shows approval buttons when status is awaiting_approval", () => {
    renderToolCard({ status: "awaiting_approval" });

    expect(screen.getByRole("button", { name: "Accept" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reject" })).toBeInTheDocument();
    // Feedback textarea is also shown
    expect(
      screen.getByPlaceholderText("Feedback for the agent (sent with Reject)...")
    ).toBeInTheDocument();
  });

  test("Accept button calls postMessage with approved: true", async () => {
    renderToolCard({ call_id: "call-42", status: "awaiting_approval" });

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Accept" }));

    expect(postMessage).toHaveBeenCalledTimes(1);
    expect(postMessage).toHaveBeenCalledWith({
      type: "approvalResult",
      callId: "call-42",
      approved: true,
    });
  });

  test("Reject button calls postMessage with approved: false and feedback", async () => {
    renderToolCard({ call_id: "call-42", status: "awaiting_approval" });

    const user = userEvent.setup();

    // Type feedback before rejecting
    const textarea = screen.getByPlaceholderText(
      "Feedback for the agent (sent with Reject)..."
    );
    await user.type(textarea, "This approach is wrong");
    await user.click(screen.getByRole("button", { name: "Reject" }));

    expect(postMessage).toHaveBeenCalledTimes(1);
    expect(postMessage).toHaveBeenCalledWith({
      type: "approvalResult",
      callId: "call-42",
      approved: false,
      feedback: "This approach is wrong",
    });
  });

  test("shows View Diff button for write_file in approval mode", () => {
    renderToolCard({
      tool_name: "write_file",
      status: "awaiting_approval",
      arguments: { file_path: "/test.py", content: "print('hello')" },
    });

    expect(screen.getByRole("button", { name: "View Diff" })).toBeInTheDocument();
  });

  test("shows View Diff button for edit_file in approval mode", async () => {
    renderToolCard({
      tool_name: "edit_file",
      status: "awaiting_approval",
      arguments: { file_path: "/test.py", old_str: "a", new_str: "b" },
    });

    const diffBtn = screen.getByRole("button", { name: "View Diff" });
    expect(diffBtn).toBeInTheDocument();

    // Click it and verify postMessage
    const user = userEvent.setup();
    await user.click(diffBtn);

    expect(postMessage).toHaveBeenCalledWith({
      type: "showDiff",
      callId: "call-1",
      toolName: "edit_file",
      arguments: { file_path: "/test.py", old_str: "a", new_str: "b" },
    });
  });

  test("hides approval buttons for non-approval statuses", () => {
    for (const status of ["running", "success", "error", "pending"] as const) {
      const { unmount } = renderToolCard({ status });

      expect(screen.queryByRole("button", { name: "Accept" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Reject" })).not.toBeInTheDocument();

      unmount();
    }
  });

  test("shows expandable result details when result is set", () => {
    renderToolCard({ result: "File contents: hello world" });

    // The <details> element with <summary>Result</summary>
    expect(screen.getByText("Result")).toBeInTheDocument();
    expect(screen.getByText("File contents: hello world")).toBeInTheDocument();
  });

  test("shows duration when available", () => {
    // duration_ms < 1000 => displayed as "250ms"
    renderToolCard({ duration_ms: 250 });
    expect(screen.getByText("250ms")).toBeInTheDocument();
  });

  test("shows duration in seconds when >= 1000ms", () => {
    renderToolCard({ duration_ms: 2500 });
    expect(screen.getByText("2.5s")).toBeInTheDocument();
  });

  test("does not show duration when not available", () => {
    const { container } = renderToolCard({ duration_ms: undefined });
    expect(container.querySelector(".tool-duration")).not.toBeInTheDocument();
  });

  test("does not render arguments for delegate_to_subagent", () => {
    renderToolCard({
      tool_name: "delegate_to_subagent",
      arguments: { task: "research something" },
    });

    // delegate_to_subagent explicitly skips primaryArg
    expect(screen.queryByText("research something")).not.toBeInTheDocument();
  });

  test("Reject with empty feedback sends undefined feedback", async () => {
    renderToolCard({ call_id: "call-99", status: "awaiting_approval" });

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Reject" }));

    expect(postMessage).toHaveBeenCalledWith({
      type: "approvalResult",
      callId: "call-99",
      approved: false,
      feedback: undefined,
    });
  });
});

// ============================================================================
// PauseWidget
// ============================================================================

describe("PauseWidget", () => {
  let postMessage: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    postMessage = vi.fn();
  });

  function renderPauseWidget(overrides: Partial<Parameters<typeof PauseWidget>[0]> = {}) {
    const props = {
      reason: "Max iterations reached",
      reasonCode: "max_iterations",
      stats: {},
      postMessage,
      ...overrides,
    };
    return render(<PauseWidget {...props} />);
  }

  test("renders reason text", () => {
    renderPauseWidget({ reason: "Token budget exceeded" });
    expect(screen.getByText("Token budget exceeded")).toBeInTheDocument();
  });

  test("renders default reason when empty", () => {
    renderPauseWidget({ reason: "" });
    expect(screen.getByText("Agent has paused.")).toBeInTheDocument();
  });

  test("shows stats entries with formatted keys", () => {
    renderPauseWidget({
      stats: { total_tokens: 5000, iterations_used: 10 },
    });

    // Keys have underscores replaced with spaces
    expect(screen.getByText(/total tokens: 5000/)).toBeInTheDocument();
    expect(screen.getByText(/iterations used: 10/)).toBeInTheDocument();
  });

  test("shows pending todos as ordered list", () => {
    renderPauseWidget({
      pendingTodos: ["Fix failing tests", "Update documentation"],
    });

    expect(screen.getByText("Pending tasks:")).toBeInTheDocument();
    expect(screen.getByText("Fix failing tests")).toBeInTheDocument();
    expect(screen.getByText("Update documentation")).toBeInTheDocument();

    // Verify they are in an ordered list
    const list = screen.getByRole("list");
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("Fix failing tests");
    expect(items[1]).toHaveTextContent("Update documentation");
  });

  test("Continue button sends pauseResult with continueWork: true", async () => {
    renderPauseWidget();

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Continue" }));

    expect(postMessage).toHaveBeenCalledTimes(1);
    expect(postMessage).toHaveBeenCalledWith({
      type: "pauseResult",
      continueWork: true,
      feedback: null,
    });
  });

  test("Stop button sends pauseResult with continueWork: false", async () => {
    renderPauseWidget();

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Stop" }));

    expect(postMessage).toHaveBeenCalledTimes(1);
    expect(postMessage).toHaveBeenCalledWith({
      type: "pauseResult",
      continueWork: false,
      feedback: null,
    });
  });

  test("feedback toggle shows and hides feedback textarea", async () => {
    renderPauseWidget();

    const user = userEvent.setup();

    // Initially hidden
    expect(
      screen.queryByPlaceholderText("Optional: add guidance for the agent...")
    ).not.toBeInTheDocument();

    // Click to show
    await user.click(screen.getByRole("button", { name: "+ Add feedback" }));
    expect(
      screen.getByPlaceholderText("Optional: add guidance for the agent...")
    ).toBeInTheDocument();
    // Toggle button text changed
    expect(screen.getByRole("button", { name: "- Hide feedback" })).toBeInTheDocument();

    // Click to hide
    await user.click(screen.getByRole("button", { name: "- Hide feedback" }));
    expect(
      screen.queryByPlaceholderText("Optional: add guidance for the agent...")
    ).not.toBeInTheDocument();
  });

  test("feedback text is included in pauseResult", async () => {
    renderPauseWidget();

    const user = userEvent.setup();

    // Open feedback and type
    await user.click(screen.getByRole("button", { name: "+ Add feedback" }));
    await user.type(
      screen.getByPlaceholderText("Optional: add guidance for the agent..."),
      "Focus on the API module"
    );

    // Click Continue
    await user.click(screen.getByRole("button", { name: "Continue" }));

    expect(postMessage).toHaveBeenCalledWith({
      type: "pauseResult",
      continueWork: true,
      feedback: "Focus on the API module",
    });
  });

  test("does not show stats row when stats is empty", () => {
    const { container } = renderPauseWidget({ stats: {} });
    expect(container.querySelector(".stats-row")).not.toBeInTheDocument();
  });

  test("does not show pending todos when list is empty", () => {
    renderPauseWidget({ pendingTodos: [] });
    expect(screen.queryByText("Pending tasks:")).not.toBeInTheDocument();
  });
});

// ============================================================================
// ClarifyWidget
// ============================================================================

describe("ClarifyWidget", () => {
  let postMessage: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    postMessage = vi.fn();
  });

  function renderClarifyWidget(
    overrides: Partial<Parameters<typeof ClarifyWidget>[0]> = {}
  ) {
    const props = {
      callId: "clarify-1",
      questions: [],
      postMessage,
      ...overrides,
    };
    return render(<ClarifyWidget {...props} />);
  }

  test("renders header and context", () => {
    renderClarifyWidget({ context: "I need some details about the task." });

    expect(screen.getByText("Clarification Needed")).toBeInTheDocument();
    expect(
      screen.getByText("I need some details about the task.")
    ).toBeInTheDocument();
  });

  test("shows questions with radio buttons for single-choice", () => {
    renderClarifyWidget({
      questions: [
        {
          id: "lang",
          question: "Which language?",
          options: ["Python", "TypeScript", "Go"],
        },
      ],
    });

    expect(screen.getByText("Which language?")).toBeInTheDocument();

    // All options rendered as radio buttons
    const radios = screen.getAllByRole("radio");
    expect(radios).toHaveLength(3);

    // Labels present
    expect(screen.getByText("Python")).toBeInTheDocument();
    expect(screen.getByText("TypeScript")).toBeInTheDocument();
    expect(screen.getByText("Go")).toBeInTheDocument();
  });

  test("shows questions with checkboxes for multi-choice", () => {
    renderClarifyWidget({
      questions: [
        {
          id: "features",
          question: "Select features:",
          multi_select: true,
          options: ["Auth", "Logging", "Caching"],
        },
      ],
    });

    expect(screen.getByText("Select features:")).toBeInTheDocument();

    const checkboxes = screen.getAllByRole("checkbox");
    expect(checkboxes).toHaveLength(3);
  });

  test("shows textarea for open-ended questions (no options)", () => {
    renderClarifyWidget({
      questions: [
        {
          id: "details",
          question: "Describe the requirements:",
        },
      ],
    });

    expect(screen.getByText("Describe the requirements:")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Your answer...")).toBeInTheDocument();
  });

  test("Submit sends clarifyResult with responses", async () => {
    renderClarifyWidget({
      callId: "clarify-42",
      questions: [
        {
          id: "lang",
          question: "Which language?",
          options: ["Python", "TypeScript"],
        },
      ],
    });

    const user = userEvent.setup();

    // Select "TypeScript" radio
    const radios = screen.getAllByRole("radio");
    await user.click(radios[1]); // second option = TypeScript

    // Submit
    await user.click(screen.getByRole("button", { name: "Submit" }));

    expect(postMessage).toHaveBeenCalledTimes(1);
    expect(postMessage).toHaveBeenCalledWith({
      type: "clarifyResult",
      callId: "clarify-42",
      submitted: true,
      responses: { lang: "TypeScript" },
    });
  });

  test("Cancel sends clarifyResult with submitted: false", async () => {
    renderClarifyWidget({ callId: "clarify-42" });

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(postMessage).toHaveBeenCalledTimes(1);
    expect(postMessage).toHaveBeenCalledWith({
      type: "clarifyResult",
      callId: "clarify-42",
      submitted: false,
      responses: null,
    });
  });

  test("after submit, shows '[Clarification submitted]'", async () => {
    renderClarifyWidget();

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Submit" }));

    expect(screen.getByText("[Clarification submitted]")).toBeInTheDocument();
    // Original form elements are gone
    expect(
      screen.queryByRole("button", { name: "Submit" })
    ).not.toBeInTheDocument();
  });

  test("after cancel, shows '[Clarification submitted]' (responses still set)", async () => {
    // Note: The component checks `responses` truthiness, not `submitted`.
    // After cancel, `responses` state is still the init object (truthy),
    // so the text says "submitted" rather than "cancelled".
    renderClarifyWidget();

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    // The dismissed text checks `responses` which is the state value (init obj = truthy)
    expect(screen.getByText("[Clarification submitted]")).toBeInTheDocument();
  });

  test("multi-choice checkboxes toggle selections correctly", async () => {
    renderClarifyWidget({
      callId: "clarify-multi",
      questions: [
        {
          id: "features",
          question: "Select features:",
          multi_select: true,
          options: ["Auth", "Logging", "Caching"],
        },
      ],
    });

    const user = userEvent.setup();
    const checkboxes = screen.getAllByRole("checkbox");

    // Select Auth and Caching
    await user.click(checkboxes[0]); // Auth
    await user.click(checkboxes[2]); // Caching

    await user.click(screen.getByRole("button", { name: "Submit" }));

    expect(postMessage).toHaveBeenCalledWith({
      type: "clarifyResult",
      callId: "clarify-multi",
      submitted: true,
      responses: { features: ["Auth", "Caching"] },
    });
  });

  test("open-ended textarea response is sent on submit", async () => {
    renderClarifyWidget({
      callId: "clarify-open",
      questions: [
        {
          id: "details",
          question: "Describe the requirements:",
        },
      ],
    });

    const user = userEvent.setup();
    await user.type(
      screen.getByPlaceholderText("Your answer..."),
      "Build a REST API"
    );
    await user.click(screen.getByRole("button", { name: "Submit" }));

    expect(postMessage).toHaveBeenCalledWith({
      type: "clarifyResult",
      callId: "clarify-open",
      submitted: true,
      responses: { details: "Build a REST API" },
    });
  });

  test("renders questions using label as fallback id and question text", () => {
    renderClarifyWidget({
      questions: [
        {
          label: "Framework Choice",
          options: ["React", "Vue"],
        },
      ],
    });

    // label is used as question text when question field is missing
    expect(screen.getByText("Framework Choice")).toBeInTheDocument();
  });
});

// ============================================================================
// PlanWidget
// ============================================================================

describe("PlanWidget", () => {
  let postMessage: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    postMessage = vi.fn();
  });

  function renderPlanWidget(overrides: Partial<Parameters<typeof PlanWidget>[0]> = {}) {
    const props = {
      callId: "plan-1",
      planHash: "abc123",
      excerpt: "## Plan\n- Step 1: Read files\n- Step 2: Implement changes",
      truncated: false,
      postMessage,
      ...overrides,
    };
    return render(<PlanWidget {...props} />);
  }

  test("renders plan excerpt as markdown HTML", () => {
    const { container } = renderPlanWidget({
      excerpt: "**Bold text** and `code`",
    });

    // renderMarkdown processes marked + DOMPurify
    const planContent = container.querySelector(".plan-content");
    expect(planContent).not.toBeNull();
    // The HTML should contain <strong> and <code> tags
    expect(planContent!.innerHTML).toContain("<strong>");
    expect(planContent!.innerHTML).toContain("<code>");
  });

  test("shows truncation note when truncated", () => {
    renderPlanWidget({
      truncated: true,
      planPath: "/tmp/full-plan.md",
    });

    expect(
      screen.getByText(/Plan was truncated/)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/\/tmp\/full-plan\.md/)
    ).toBeInTheDocument();
  });

  test("does not show truncation note when not truncated", () => {
    const { container } = renderPlanWidget({ truncated: false });
    expect(container.querySelector(".truncation-note")).not.toBeInTheDocument();
  });

  test("Approve sends planApprovalResult with approved: true", async () => {
    renderPlanWidget({ planHash: "hash-xyz" });

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Approve" }));

    expect(postMessage).toHaveBeenCalledTimes(1);
    expect(postMessage).toHaveBeenCalledWith({
      type: "planApprovalResult",
      planHash: "hash-xyz",
      approved: true,
      autoAcceptEdits: false,
    });
  });

  test("Auto-accept sends planApprovalResult with autoAcceptEdits: true", async () => {
    renderPlanWidget({ planHash: "hash-xyz" });

    const user = userEvent.setup();
    await user.click(
      screen.getByRole("button", { name: "Approve + Auto-accept Edits" })
    );

    expect(postMessage).toHaveBeenCalledTimes(1);
    expect(postMessage).toHaveBeenCalledWith({
      type: "planApprovalResult",
      planHash: "hash-xyz",
      approved: true,
      autoAcceptEdits: true,
    });
  });

  test("Reject sends planApprovalResult with approved: false and feedback", async () => {
    renderPlanWidget({ planHash: "hash-xyz" });

    const user = userEvent.setup();

    // Type feedback
    const textarea = screen.getByPlaceholderText(
      "Feedback for the agent (sent with Reject)..."
    );
    await user.type(textarea, "Need more detail on step 2");

    await user.click(screen.getByRole("button", { name: "Reject" }));

    expect(postMessage).toHaveBeenCalledTimes(1);
    expect(postMessage).toHaveBeenCalledWith({
      type: "planApprovalResult",
      planHash: "hash-xyz",
      approved: false,
      feedback: "Need more detail on step 2",
    });
  });

  test("Reject with no feedback sends feedback: null", async () => {
    renderPlanWidget({ planHash: "hash-xyz" });

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Reject" }));

    expect(postMessage).toHaveBeenCalledWith({
      type: "planApprovalResult",
      planHash: "hash-xyz",
      approved: false,
      feedback: null,
    });
  });

  test("after approval, shows '[Plan approved]'", async () => {
    renderPlanWidget();

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Approve" }));

    expect(screen.getByText("[Plan approved]")).toBeInTheDocument();
    // Action buttons are gone
    expect(
      screen.queryByRole("button", { name: "Approve" })
    ).not.toBeInTheDocument();
  });

  test("after auto-accept approval, shows '[Plan approved (auto-accept edits)]'", async () => {
    renderPlanWidget();

    const user = userEvent.setup();
    await user.click(
      screen.getByRole("button", { name: "Approve + Auto-accept Edits" })
    );

    expect(
      screen.getByText("[Plan approved (auto-accept edits)]")
    ).toBeInTheDocument();
  });

  test("after rejection, shows '[Plan rejected]'", async () => {
    renderPlanWidget();

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Reject" }));

    expect(screen.getByText("[Plan rejected]")).toBeInTheDocument();
  });

  test("shows default plan path text when truncated and no planPath", () => {
    renderPlanWidget({ truncated: true, planPath: undefined });
    expect(screen.getByText(/plan file/)).toBeInTheDocument();
  });

  test("renders Plan Approval header", () => {
    renderPlanWidget();
    expect(screen.getByText("Plan Approval")).toBeInTheDocument();
  });
});

// ============================================================================
// UndoBar
// ============================================================================

describe("UndoBar", () => {
  let postMessage: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    postMessage = vi.fn();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  function renderUndoBar(overrides: Partial<Parameters<typeof UndoBar>[0]> = {}) {
    const props = {
      turnId: "turn-1",
      files: ["/src/main.py", "/src/utils.py"],
      undone: false,
      postMessage,
      ...overrides,
    };
    return render(<UndoBar {...props} />);
  }

  test("shows file count and names", () => {
    renderUndoBar({
      files: ["/src/main.py", "/src/utils.py", "/tests/test_main.py"],
    });

    // Format: "3 files modified: main.py, utils.py, test_main.py"
    expect(
      screen.getByText("3 files modified: main.py, utils.py, test_main.py")
    ).toBeInTheDocument();
  });

  test("shows singular 'file' for single file", () => {
    renderUndoBar({ files: ["/src/main.py"] });
    expect(screen.getByText("1 file modified: main.py")).toBeInTheDocument();
  });

  test("Undo button sends undoTurn message", () => {
    renderUndoBar({ turnId: "turn-42" });

    fireEvent.click(screen.getByRole("button", { name: "Undo" }));

    expect(postMessage).toHaveBeenCalledTimes(1);
    expect(postMessage).toHaveBeenCalledWith({
      type: "undoTurn",
      turnId: "turn-42",
    });
  });

  test("after clicking Undo, button is disabled and shows 'Undoing...'", () => {
    renderUndoBar();

    fireEvent.click(screen.getByRole("button", { name: "Undo" }));

    const btn = screen.getByRole("button", { name: "Undoing..." });
    expect(btn).toBeInTheDocument();
    expect(btn).toBeDisabled();
  });

  test("when undone prop is true, shows restored message and hides undo button", () => {
    const { rerender } = renderUndoBar({ files: ["/src/main.py", "/src/utils.py"] });

    // Simulate server confirming the undo via undone prop
    rerender(
      <UndoBar
        turnId="turn-1"
        files={["/src/main.py", "/src/utils.py"]}
        undone={true}
        postMessage={postMessage}
      />,
    );

    expect(screen.getByText("2 file(s) restored")).toBeInTheDocument();
    // Undo button should be gone
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  test("full file paths are in title attribute for tooltip", () => {
    const { container } = renderUndoBar({ files: ["/src/main.py", "/src/utils.py"] });

    const infoSpan = container.querySelector(".undo-info");
    expect(infoSpan).not.toBeNull();
    // files.join("\n") produces a newline-separated title
    expect(infoSpan!.getAttribute("title")).toBe("/src/main.py\n/src/utils.py");
  });

  test("undo button has descriptive title for accessibility", () => {
    renderUndoBar({ files: ["/a.py", "/b.py"] });

    const btn = screen.getByRole("button", { name: "Undo" });
    expect(btn).toHaveAttribute(
      "title",
      "Revert 2 file(s) to their state before this turn"
    );
  });
});
