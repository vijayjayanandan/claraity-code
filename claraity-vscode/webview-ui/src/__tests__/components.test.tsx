/**
 * Unit tests for ClarAIty webview React components and tool utilities.
 *
 * Coverage:
 * - MessageBubble: role rendering, CSS classes, markdown content
 * - CodeBlock: language label, code content, block cursor, copy button
 * - ThinkingBlock: details element, summary text, content
 * - TurnStats: token formatting, duration display
 * - StatusBar: title, toolbar button callbacks
 * - BottomBar: connection status, model name, Plan/Act toggle
 * - TodoPanel: summary counts, collapsible list, status markers
 * - AutoApprovePanel: expand/collapse, checkboxes, summary text
 * - Tool utilities: TOOL_ICONS, getPrimaryArg, formatDuration
 *
 * Total: 55 tests
 */
import { describe, test, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { MessageBubble } from "../components/MessageBubble";
import { CodeBlock } from "../components/CodeBlock";
import { ThinkingBlock } from "../components/ThinkingBlock";
import { ContextBar } from "../components/ContextBar";
import { TurnStats } from "../components/TurnStats";
import { StatusBar } from "../components/StatusBar";
import { BottomBar } from "../components/BottomBar";
import { TodoPanel } from "../components/TodoPanel";
import { AutoApprovePanel } from "../components/AutoApprovePanel";
import { TOOL_ICONS, getPrimaryArg, formatDuration } from "../utils/tools";

import type { ChatMessage, ThinkingBlock as ThinkingBlockType, CodeBlock as CodeBlockType } from "../state/reducer";

// ============================================================================
// MessageBubble
// ============================================================================

describe("MessageBubble", () => {
  test("renders user message content without role icon", () => {
    const msg: ChatMessage = {
      id: "u1",
      role: "user",
      content: "Hello agent",
      finalized: true,
    };
    const { container } = render(<MessageBubble message={msg} />);

    expect(screen.getByText("Hello agent")).toBeInTheDocument();
    expect(container.querySelector(".role-icon")).not.toBeInTheDocument();
  });

  test("renders assistant message content without role icon", () => {
    const msg: ChatMessage = {
      id: "a1",
      role: "assistant",
      content: "Hi there",
      finalized: true,
    };
    const { container } = render(<MessageBubble message={msg} />);

    expect(screen.getByText("Hi there")).toBeInTheDocument();
    expect(container.querySelector(".role-icon")).not.toBeInTheDocument();
  });

  test("applies correct CSS class for user role", () => {
    const msg: ChatMessage = {
      id: "u2",
      role: "user",
      content: "Test",
      finalized: true,
    };
    const { container } = render(<MessageBubble message={msg} />);

    const messageDiv = container.querySelector(".message.user");
    expect(messageDiv).toBeInTheDocument();
  });

  test("applies correct CSS class for assistant role", () => {
    const msg: ChatMessage = {
      id: "a2",
      role: "assistant",
      content: "Test",
      finalized: true,
    };
    const { container } = render(<MessageBubble message={msg} />);

    const messageDiv = container.querySelector(".message.assistant");
    expect(messageDiv).toBeInTheDocument();
  });

  test("renders markdown content as HTML", () => {
    const msg: ChatMessage = {
      id: "a3",
      role: "assistant",
      content: "**bold text**",
      finalized: true,
    };
    const { container } = render(<MessageBubble message={msg} />);

    // marked should render **bold text** as <strong>bold text</strong>
    const strong = container.querySelector("strong");
    expect(strong).toBeInTheDocument();
    expect(strong!.textContent).toBe("bold text");
  });

  test("renders empty content without error", () => {
    const msg: ChatMessage = {
      id: "a4",
      role: "assistant",
      content: "",
      finalized: true,
    };
    const { container } = render(<MessageBubble message={msg} />);

    const contentDiv = container.querySelector(".content");
    expect(contentDiv).toBeInTheDocument();
    expect(contentDiv!.innerHTML).toBe("");
  });

  test("renders system role message with correct CSS class (no role icon)", () => {
    const msg: ChatMessage = {
      id: "s1",
      role: "system",
      content: "System message",
      finalized: true,
    };
    const { container } = render(<MessageBubble message={msg} />);

    expect(screen.getByText("System message")).toBeInTheDocument();
    const messageDiv = container.querySelector(".message.system");
    expect(messageDiv).toBeInTheDocument();
    expect(container.querySelector(".role-icon")).not.toBeInTheDocument();
  });
});

// ============================================================================
// CodeBlock
// ============================================================================

describe("CodeBlock", () => {
  const mockPostMessage = vi.fn();

  beforeEach(() => {
    mockPostMessage.mockClear();
  });

  test("renders language label", () => {
    const block: CodeBlockType = { language: "python", content: "x = 1", complete: true };
    render(<CodeBlock block={block} postMessage={mockPostMessage} />);

    expect(screen.getByText("python")).toBeInTheDocument();
  });

  test("renders 'code' as default language label when language is empty", () => {
    const block: CodeBlockType = { language: "", content: "some code", complete: true };
    render(<CodeBlock block={block} postMessage={mockPostMessage} />);

    expect(screen.getByText("code")).toBeInTheDocument();
  });

  test("renders code content", () => {
    const block: CodeBlockType = { language: "js", content: "const x = 42;", complete: true };
    render(<CodeBlock block={block} postMessage={mockPostMessage} />);

    expect(screen.getByText("const x = 42;")).toBeInTheDocument();
  });

  test("shows block cursor when not complete", () => {
    const block: CodeBlockType = { language: "ts", content: "let y", complete: false };
    const { container } = render(<CodeBlock block={block} postMessage={mockPostMessage} />);

    const codeEl = container.querySelector("code");
    expect(codeEl).toBeInTheDocument();
    // \u2588 is the block cursor character
    expect(codeEl!.textContent).toBe("let y\u2588");
  });

  test("does not show block cursor when complete", () => {
    const block: CodeBlockType = { language: "ts", content: "let y = 1;", complete: true };
    const { container } = render(<CodeBlock block={block} postMessage={mockPostMessage} />);

    const codeEl = container.querySelector("code");
    expect(codeEl!.textContent).toBe("let y = 1;");
    expect(codeEl!.textContent).not.toContain("\u2588");
  });

  test("copy button calls postMessage with copyToClipboard", () => {
    const block: CodeBlockType = { language: "py", content: "print('hi')", complete: true };
    render(<CodeBlock block={block} postMessage={mockPostMessage} />);

    const copyBtn = screen.getByText("Copy");
    fireEvent.click(copyBtn);

    expect(mockPostMessage).toHaveBeenCalledOnce();
    expect(mockPostMessage).toHaveBeenCalledWith({
      type: "copyToClipboard",
      text: "print('hi')",
    });
  });

  test("shows 'Copied!' after clicking copy", () => {
    const block: CodeBlockType = { language: "py", content: "x = 1", complete: true };
    render(<CodeBlock block={block} postMessage={mockPostMessage} />);

    const copyBtn = screen.getByText("Copy");
    fireEvent.click(copyBtn);

    expect(screen.getByText("Copied!")).toBeInTheDocument();
    expect(screen.queryByText("Copy")).not.toBeInTheDocument();
  });

  test("renders code inside pre > code elements", () => {
    const block: CodeBlockType = { language: "rust", content: "fn main() {}", complete: true };
    const { container } = render(<CodeBlock block={block} postMessage={mockPostMessage} />);

    const pre = container.querySelector("pre");
    expect(pre).toBeInTheDocument();
    const code = pre!.querySelector("code");
    expect(code).toBeInTheDocument();
    expect(code!.textContent).toBe("fn main() {}");
  });
});

// ============================================================================
// ThinkingBlock
// ============================================================================

describe("ThinkingBlock", () => {
  test("renders as a details element", () => {
    const thinking: ThinkingBlockType = { content: "Analyzing...", open: true };
    const { container } = render(<ThinkingBlock thinking={thinking} />);

    const details = container.querySelector("details");
    expect(details).toBeInTheDocument();
    expect(details!.classList.contains("thinking-block")).toBe(true);
  });

  test("shows 'Thinking...' in summary when open", () => {
    const thinking: ThinkingBlockType = { content: "Working on it", open: true };
    render(<ThinkingBlock thinking={thinking} />);

    // summary text: "Thinking..."  (Thinking + "..." because open is true)
    const summary = screen.getByText(/^Thinking/);
    expect(summary).toBeInTheDocument();
    expect(summary.textContent).toContain("...");
  });

  test("shows 'Thinking' without ellipsis when closed", () => {
    const thinking: ThinkingBlockType = { content: "Done thinking", open: false };
    render(<ThinkingBlock thinking={thinking} />);

    const summary = screen.getByText(/^Thinking/);
    // When not open, the summary should be just "Thinking" without trailing "..."
    expect(summary.textContent).toBe("Thinking");
  });

  test("shows token count in summary when available", () => {
    const thinking: ThinkingBlockType = { content: "Thinking deeply", tokenCount: 150, open: true };
    render(<ThinkingBlock thinking={thinking} />);

    const summary = screen.getByText(/150 tokens/);
    expect(summary).toBeInTheDocument();
  });

  test("does not show token count when not available", () => {
    const thinking: ThinkingBlockType = { content: "Quick thought", open: false };
    render(<ThinkingBlock thinking={thinking} />);

    expect(screen.queryByText(/tokens/)).not.toBeInTheDocument();
  });

  test("shows content text", () => {
    const thinking: ThinkingBlockType = { content: "I need to analyze the file structure", open: true };
    render(<ThinkingBlock thinking={thinking} />);

    expect(screen.getByText("I need to analyze the file structure")).toBeInTheDocument();
  });

  test("renders content inside thinking-content div", () => {
    const thinking: ThinkingBlockType = { content: "Analysis text", open: true };
    const { container } = render(<ThinkingBlock thinking={thinking} />);

    const contentDiv = container.querySelector(".thinking-content");
    expect(contentDiv).toBeInTheDocument();
    expect(contentDiv!.textContent).toBe("Analysis text");
  });

  test("details element has open attribute when thinking.open is true", () => {
    const thinking: ThinkingBlockType = { content: "open block", open: true };
    const { container } = render(<ThinkingBlock thinking={thinking} />);

    const details = container.querySelector("details");
    expect(details!.hasAttribute("open")).toBe(true);
  });

  test("adds 'active' class when isActive is true", () => {
    const thinking: ThinkingBlockType = { content: "Streaming thought", open: true };
    const { container } = render(<ThinkingBlock thinking={thinking} isActive />);

    const details = container.querySelector("details");
    expect(details!.classList.contains("active")).toBe(true);
  });

  test("does not add 'active' class when isActive is not set", () => {
    const thinking: ThinkingBlockType = { content: "Done", open: false };
    const { container } = render(<ThinkingBlock thinking={thinking} />);

    const details = container.querySelector("details");
    expect(details!.classList.contains("active")).toBe(false);
  });
});

// ============================================================================
// ContextBar
// ============================================================================

describe("ContextBar", () => {
  const baseProps = {
    used: 0,
    limit: 100000,
    totalTokens: 5000,
    turnCount: 3,
    modelName: "gpt-4o",
  };

  test("applies context-fill-ok class when usage is below 60%", () => {
    const { container } = render(<ContextBar {...baseProps} used={50000} />);
    const fill = container.querySelector(".context-bar-fill");
    expect(fill!.classList.contains("context-fill-ok")).toBe(true);
  });

  test("applies context-fill-warning class when usage is 60-84%", () => {
    const { container } = render(<ContextBar {...baseProps} used={70000} />);
    const fill = container.querySelector(".context-bar-fill");
    expect(fill!.classList.contains("context-fill-warning")).toBe(true);
  });

  test("applies context-fill-danger class when usage is 85%+", () => {
    const { container } = render(<ContextBar {...baseProps} used={90000} />);
    const fill = container.querySelector(".context-bar-fill");
    expect(fill!.classList.contains("context-fill-danger")).toBe(true);
  });

  test("applies context-fill-ok when usage is 0%", () => {
    const { container } = render(<ContextBar {...baseProps} used={0} />);
    const fill = container.querySelector(".context-bar-fill");
    expect(fill!.classList.contains("context-fill-ok")).toBe(true);
  });

  test("applies context-fill-warning at exactly 60%", () => {
    const { container } = render(<ContextBar {...baseProps} used={60000} />);
    const fill = container.querySelector(".context-bar-fill");
    expect(fill!.classList.contains("context-fill-warning")).toBe(true);
  });

  test("applies context-fill-danger at exactly 85%", () => {
    const { container } = render(<ContextBar {...baseProps} used={85000} />);
    const fill = container.querySelector(".context-bar-fill");
    expect(fill!.classList.contains("context-fill-danger")).toBe(true);
  });
});

// ============================================================================
// TurnStats
// ============================================================================

describe("TurnStats", () => {
  test("shows formatted token count", () => {
    render(<TurnStats tokens={1500} durationMs={0} />);

    // toLocaleString formats 1500 as locale-appropriate (e.g., "1,500")
    expect(screen.getByText(/1.*500 tokens/)).toBeInTheDocument();
  });

  test("shows duration when > 0", () => {
    render(<TurnStats tokens={100} durationMs={2500} />);

    // 2500ms -> "2.5s"
    expect(screen.getByText(/2\.5s/)).toBeInTheDocument();
  });

  test("does not show duration when durationMs is 0", () => {
    const { container } = render(<TurnStats tokens={100} durationMs={0} />);

    expect(container.textContent).not.toContain("|");
    // Should not contain a duration like "X.Xs" -- only "100 tokens" text
    expect(container.textContent).not.toMatch(/\d+\.\d+s/);
  });

  test("shows pipe separator between tokens and duration", () => {
    const { container } = render(<TurnStats tokens={500} durationMs={3000} />);

    expect(container.textContent).toContain("|");
    expect(container.textContent).toContain("3.0s");
  });

  test("renders inside turn-stats div", () => {
    const { container } = render(<TurnStats tokens={100} durationMs={0} />);

    const statsDiv = container.querySelector(".turn-stats");
    expect(statsDiv).toBeInTheDocument();
  });

  test("formats large token counts with locale separator", () => {
    render(<TurnStats tokens={125000} durationMs={0} />);

    // Should contain 125,000 or locale equivalent
    expect(screen.getByText(/125.*000 tokens/)).toBeInTheDocument();
  });

  test("formats sub-second durations", () => {
    render(<TurnStats tokens={50} durationMs={500} />);

    // 500ms -> "0.5s"
    expect(screen.getByText(/0\.5s/)).toBeInTheDocument();
  });
});

// ============================================================================
// StatusBar
// ============================================================================

describe("StatusBar", () => {
  const defaultProps = {
    onNewChat: vi.fn(),
    onShowHistory: vi.fn(),
    onShowConfig: vi.fn(),
    onShowJira: vi.fn(),
    onShowMcp: vi.fn(),
  };

  beforeEach(() => {
    defaultProps.onNewChat.mockClear();
    defaultProps.onShowHistory.mockClear();
    defaultProps.onShowConfig.mockClear();
    defaultProps.onShowJira.mockClear();
    defaultProps.onShowMcp.mockClear();
  });

  test("renders title 'ClarAIty'", () => {
    render(<StatusBar {...defaultProps} />);

    expect(screen.getByText("ClarAIty")).toBeInTheDocument();
  });

  test("renders title with correct CSS class", () => {
    const { container } = render(<StatusBar {...defaultProps} />);

    const title = container.querySelector(".title");
    expect(title).toBeInTheDocument();
    expect(title!.textContent).toBe("ClarAIty");
  });

  test("New Chat button triggers onNewChat callback", () => {
    render(<StatusBar {...defaultProps} />);

    const newChatBtn = screen.getByTitle("New Chat");
    fireEvent.click(newChatBtn);

    expect(defaultProps.onNewChat).toHaveBeenCalledOnce();
  });

  test("Session History button triggers onShowHistory callback", () => {
    render(<StatusBar {...defaultProps} />);

    const historyBtn = screen.getByTitle("Session History");
    fireEvent.click(historyBtn);

    expect(defaultProps.onShowHistory).toHaveBeenCalledOnce();
  });

  test("LLM Configuration button triggers onShowConfig callback", () => {
    render(<StatusBar {...defaultProps} />);

    const configBtn = screen.getByTitle("LLM Configuration");
    fireEvent.click(configBtn);

    expect(defaultProps.onShowConfig).toHaveBeenCalledOnce();
  });

  test("Jira Integration button triggers onShowJira callback", () => {
    render(<StatusBar {...defaultProps} />);

    const jiraBtn = screen.getByTitle("Jira Integration");
    fireEvent.click(jiraBtn);

    expect(defaultProps.onShowJira).toHaveBeenCalledOnce();
  });

  test("renders four toolbar buttons", () => {
    const { container } = render(<StatusBar {...defaultProps} />);

    const buttons = container.querySelectorAll(".toolbar-icon");
    expect(buttons).toHaveLength(4);
  });
});

// ============================================================================
// BottomBar
// ============================================================================

describe("BottomBar", () => {
  test("shows 'Connected' when connected is true", () => {
    render(
      <BottomBar connected={true} modelName="gpt-4o" permissionMode="normal" onSetMode={vi.fn()} onShowArchitecture={vi.fn()} onShowBeads={vi.fn()} />
    );

    expect(screen.getByText("Connected")).toBeInTheDocument();
  });

  test("shows 'Disconnected' when connected is false", () => {
    render(
      <BottomBar connected={false} modelName="gpt-4o" permissionMode="normal" onSetMode={vi.fn()} onShowArchitecture={vi.fn()} onShowBeads={vi.fn()} />
    );

    expect(screen.getByText("Disconnected")).toBeInTheDocument();
  });

  test("applies 'connected' CSS class when connected", () => {
    const { container } = render(
      <BottomBar connected={true} modelName="" permissionMode="normal" onSetMode={vi.fn()} onShowArchitecture={vi.fn()} onShowBeads={vi.fn()} />
    );

    const statusSpan = container.querySelector(".connection-status.connected");
    expect(statusSpan).toBeInTheDocument();
  });

  test("applies 'disconnected' CSS class when not connected", () => {
    const { container } = render(
      <BottomBar connected={false} modelName="" permissionMode="normal" onSetMode={vi.fn()} onShowArchitecture={vi.fn()} onShowBeads={vi.fn()} />
    );

    const statusSpan = container.querySelector(".connection-status.disconnected");
    expect(statusSpan).toBeInTheDocument();
  });

  test("shows model name when provided", () => {
    render(
      <BottomBar connected={true} modelName="claude-opus-4" permissionMode="normal" onSetMode={vi.fn()} onShowArchitecture={vi.fn()} onShowBeads={vi.fn()} />
    );

    expect(screen.getByText("claude-opus-4")).toBeInTheDocument();
  });

  test("does not show model name when empty", () => {
    const { container } = render(
      <BottomBar connected={true} modelName="" permissionMode="normal" onSetMode={vi.fn()} onShowArchitecture={vi.fn()} onShowBeads={vi.fn()} />
    );

    const modelSpan = container.querySelector(".model-name");
    expect(modelSpan).not.toBeInTheDocument();
  });

  test("Plan button triggers onSetMode with 'plan'", () => {
    const onSetMode = vi.fn();
    render(
      <BottomBar connected={true} modelName="" permissionMode="normal" onSetMode={onSetMode} onShowArchitecture={vi.fn()} onShowBeads={vi.fn()} />
    );

    fireEvent.click(screen.getByText("Plan"));

    expect(onSetMode).toHaveBeenCalledWith("plan");
  });

  test("Act button triggers onSetMode with 'normal'", () => {
    const onSetMode = vi.fn();
    render(
      <BottomBar connected={true} modelName="" permissionMode="plan" onSetMode={onSetMode} onShowArchitecture={vi.fn()} onShowBeads={vi.fn()} />
    );

    fireEvent.click(screen.getByText("Act"));

    expect(onSetMode).toHaveBeenCalledWith("normal");
  });

  test("Plan button has 'active' class when mode is 'plan'", () => {
    render(
      <BottomBar connected={true} modelName="" permissionMode="plan" onSetMode={vi.fn()} onShowArchitecture={vi.fn()} onShowBeads={vi.fn()} />
    );

    const planBtn = screen.getByText("Plan");
    expect(planBtn.className).toContain("active");
  });

  test("Act button has 'active' class when mode is not 'plan'", () => {
    render(
      <BottomBar connected={true} modelName="" permissionMode="normal" onSetMode={vi.fn()} onShowArchitecture={vi.fn()} onShowBeads={vi.fn()} />
    );

    const actBtn = screen.getByText("Act");
    expect(actBtn.className).toContain("active");
  });

  test("Plan button does not have 'active' class when mode is 'normal'", () => {
    render(
      <BottomBar connected={true} modelName="" permissionMode="normal" onSetMode={vi.fn()} onShowArchitecture={vi.fn()} onShowBeads={vi.fn()} />
    );

    const planBtn = screen.getByText("Plan");
    expect(planBtn.className).not.toContain("active");
  });
});

// ============================================================================
// TodoPanel
// ============================================================================

describe("TodoPanel", () => {
  const sampleTodos = [
    { id: "t1", subject: "Fix bug", status: "in_progress", activeForm: "Fixing the critical bug" },
    { id: "t2", subject: "Write tests", status: "completed" },
    { id: "t3", subject: "Deploy", status: "pending" },
    { id: "t4", subject: "Review PR", status: "in_progress", activeForm: "Reviewing changes" },
  ];

  test("shows active task activeForm in collapsed summary", () => {
    render(<TodoPanel todos={sampleTodos} />);

    // First in_progress task's activeForm is shown
    expect(screen.getByText(">>> Fixing the critical bug")).toBeInTheDocument();
  });

  test("starts collapsed (list not visible)", () => {
    const { container } = render(<TodoPanel todos={sampleTodos} />);

    const todoList = container.querySelector(".todo-list");
    expect(todoList).not.toBeInTheDocument();
  });

  test("clicking header toggles list visibility", () => {
    const { container } = render(<TodoPanel todos={sampleTodos} />);

    const header = container.querySelector(".todo-header")!;

    // Click to expand
    fireEvent.click(header);
    expect(container.querySelector(".todo-list")).toBeInTheDocument();

    // Click to collapse
    fireEvent.click(header);
    expect(container.querySelector(".todo-list")).not.toBeInTheDocument();
  });

  test("shows collapsed indicator '+' initially", () => {
    render(<TodoPanel todos={sampleTodos} />);

    expect(screen.getByText("+")).toBeInTheDocument();
  });

  test("shows expanded indicator '-' after clicking header", () => {
    const { container } = render(<TodoPanel todos={sampleTodos} />);

    const header = container.querySelector(".todo-header")!;
    fireEvent.click(header);

    expect(screen.getByText("-")).toBeInTheDocument();
  });

  test("shows todo items with correct status markers when expanded", () => {
    const { container } = render(<TodoPanel todos={sampleTodos} />);

    // Expand
    fireEvent.click(container.querySelector(".todo-header")!);

    // Check status markers
    expect(screen.getAllByText("[>>>]")).toHaveLength(2);  // 2 in_progress
    expect(screen.getByText("[x]")).toBeInTheDocument();   // 1 completed
    expect(screen.getByText("[ ]")).toBeInTheDocument();   // 1 pending
  });

  test("in_progress items show activeForm text, others show subject", () => {
    const { container } = render(<TodoPanel todos={sampleTodos} />);

    // Expand
    fireEvent.click(container.querySelector(".todo-header")!);

    // in_progress items show activeForm
    expect(screen.getByText("Fixing the critical bug")).toBeInTheDocument();
    expect(screen.getByText("Reviewing changes")).toBeInTheDocument();

    // completed/pending items show subject
    expect(screen.getByText("Write tests")).toBeInTheDocument();
    expect(screen.getByText("Deploy")).toBeInTheDocument();
  });

  test("shows correct counts with empty todos", () => {
    render(<TodoPanel todos={[]} />);

    expect(screen.getByText("Tasks: 0/0 done")).toBeInTheDocument();
  });

  test("applies status class to todo items", () => {
    const { container } = render(<TodoPanel todos={sampleTodos} />);

    // Expand
    fireEvent.click(container.querySelector(".todo-header")!);

    const items = container.querySelectorAll(".todo-item");
    expect(items).toHaveLength(4);
    expect(items[0].classList.contains("in_progress")).toBe(true);
    expect(items[1].classList.contains("completed")).toBe(true);
    expect(items[2].classList.contains("pending")).toBe(true);
  });
});

// ============================================================================
// AutoApprovePanel
// ============================================================================

describe("AutoApprovePanel", () => {
  test("starts collapsed (checkboxes not visible)", () => {
    const { container } = render(
      <AutoApprovePanel
        autoApprove={{ edit: false, execute: false, browser: false }}
        onChange={vi.fn()}
      />
    );

    const body = container.querySelector(".auto-approve-body");
    expect(body).not.toBeInTheDocument();
  });

  test("expand/collapse works by clicking header", () => {
    const { container } = render(
      <AutoApprovePanel
        autoApprove={{ edit: false, execute: false, browser: false }}
        onChange={vi.fn()}
      />
    );

    const header = container.querySelector(".auto-approve-header")!;

    // Expand
    fireEvent.click(header);
    expect(container.querySelector(".auto-approve-body")).toBeInTheDocument();

    // Collapse
    fireEvent.click(header);
    expect(container.querySelector(".auto-approve-body")).not.toBeInTheDocument();
  });

  test("shows '+' when collapsed and '-' when expanded", () => {
    const { container } = render(
      <AutoApprovePanel
        autoApprove={{ edit: false, execute: false, browser: false }}
        onChange={vi.fn()}
      />
    );

    expect(screen.getByText("+")).toBeInTheDocument();

    fireEvent.click(container.querySelector(".auto-approve-header")!);
    expect(screen.getByText("-")).toBeInTheDocument();
  });

  test("edit checkbox triggers onChange with correct categories", () => {
    const onChange = vi.fn();
    const { container } = render(
      <AutoApprovePanel
        autoApprove={{ edit: false, execute: false, browser: false }}
        onChange={onChange}
      />
    );

    // Expand first
    fireEvent.click(container.querySelector(".auto-approve-header")!);

    // Find checkboxes - there are 3 checkboxes for edit, execute, browser
    const checkboxes = container.querySelectorAll("input[type='checkbox']");
    expect(checkboxes).toHaveLength(3);

    // Check the "Edit files" checkbox (first one)
    fireEvent.click(checkboxes[0]);

    expect(onChange).toHaveBeenCalledWith({
      edit: true,
      execute: false,
      browser: false,
    });
  });

  test("execute checkbox triggers onChange with correct categories", () => {
    const onChange = vi.fn();
    const { container } = render(
      <AutoApprovePanel
        autoApprove={{ edit: false, execute: false, browser: false }}
        onChange={onChange}
      />
    );

    fireEvent.click(container.querySelector(".auto-approve-header")!);

    const checkboxes = container.querySelectorAll("input[type='checkbox']");
    // Check the "Run commands" checkbox (second one)
    fireEvent.click(checkboxes[1]);

    expect(onChange).toHaveBeenCalledWith({
      edit: false,
      execute: true,
      browser: false,
    });
  });

  test("browser checkbox triggers onChange with correct categories", () => {
    const onChange = vi.fn();
    const { container } = render(
      <AutoApprovePanel
        autoApprove={{ edit: false, execute: false, browser: false }}
        onChange={onChange}
      />
    );

    fireEvent.click(container.querySelector(".auto-approve-header")!);

    const checkboxes = container.querySelectorAll("input[type='checkbox']");
    // Check the "Browser tools" checkbox (third one)
    fireEvent.click(checkboxes[2]);

    expect(onChange).toHaveBeenCalledWith({
      edit: false,
      execute: false,
      browser: true,
    });
  });

  test("summary shows 'Auto-approve' when no categories active", () => {
    render(
      <AutoApprovePanel
        autoApprove={{ edit: false, execute: false, browser: false }}
        onChange={vi.fn()}
      />
    );

    expect(screen.getByText("Auto-approve")).toBeInTheDocument();
  });

  test("summary shows active categories", () => {
    render(
      <AutoApprovePanel
        autoApprove={{ edit: true, execute: false, browser: true }}
        onChange={vi.fn()}
      />
    );

    expect(screen.getByText("Auto-approve: Edit, Browser")).toBeInTheDocument();
  });

  test("summary shows all active categories", () => {
    render(
      <AutoApprovePanel
        autoApprove={{ edit: true, execute: true, browser: true }}
        onChange={vi.fn()}
      />
    );

    expect(screen.getByText("Auto-approve: Edit, Commands, Browser")).toBeInTheDocument();
  });

  test("summary has 'has-active' class when categories are active", () => {
    const { container } = render(
      <AutoApprovePanel
        autoApprove={{ edit: true, execute: false, browser: false }}
        onChange={vi.fn()}
      />
    );

    const summary = container.querySelector(".auto-approve-summary.has-active");
    expect(summary).toBeInTheDocument();
  });

  test("summary does not have 'has-active' class when no categories active", () => {
    const { container } = render(
      <AutoApprovePanel
        autoApprove={{ edit: false, execute: false, browser: false }}
        onChange={vi.fn()}
      />
    );

    const summary = container.querySelector(".auto-approve-summary.has-active");
    expect(summary).not.toBeInTheDocument();
  });

  test("checkboxes reflect current autoApprove state", () => {
    const { container } = render(
      <AutoApprovePanel
        autoApprove={{ edit: true, execute: false, browser: true }}
        onChange={vi.fn()}
      />
    );

    // Expand
    fireEvent.click(container.querySelector(".auto-approve-header")!);

    const checkboxes = container.querySelectorAll("input[type='checkbox']") as NodeListOf<HTMLInputElement>;
    expect(checkboxes[0].checked).toBe(true);   // edit
    expect(checkboxes[1].checked).toBe(false);  // execute
    expect(checkboxes[2].checked).toBe(true);   // browser
  });

  test("unchecking an active checkbox sends false for that category", () => {
    const onChange = vi.fn();
    const { container } = render(
      <AutoApprovePanel
        autoApprove={{ edit: true, execute: true, browser: false }}
        onChange={onChange}
      />
    );

    fireEvent.click(container.querySelector(".auto-approve-header")!);

    const checkboxes = container.querySelectorAll("input[type='checkbox']");
    // Uncheck edit (first checkbox)
    fireEvent.click(checkboxes[0]);

    expect(onChange).toHaveBeenCalledWith({
      edit: false,
      execute: true,
      browser: false,
    });
  });
});

// ============================================================================
// Tool Utilities: TOOL_ICONS
// ============================================================================

describe("TOOL_ICONS", () => {
  test("has expected keys", () => {
    const expectedKeys = [
      "read_file",
      "write_file",
      "edit_file",
      "run_command",
      "list_directory",
      "search_files",
      "clarify",
      "plan",
      "delegate_task",
      "delegate_to_subagent",
    ];

    for (const key of expectedKeys) {
      expect(TOOL_ICONS).toHaveProperty(key);
    }
  });

  test("all values are non-empty strings", () => {
    for (const [key, value] of Object.entries(TOOL_ICONS)) {
      expect(typeof value).toBe("string");
      expect(value.length).toBeGreaterThan(0);
    }
  });

  test("maps run_command to '>'", () => {
    expect(TOOL_ICONS.run_command).toBe(">");
  });

  test("maps read_file to 'R'", () => {
    expect(TOOL_ICONS.read_file).toBe("R");
  });

  test("maps delegate_to_subagent to 'SA'", () => {
    expect(TOOL_ICONS.delegate_to_subagent).toBe("SA");
  });
});

// ============================================================================
// Tool Utilities: getPrimaryArg
// ============================================================================

describe("getPrimaryArg", () => {
  test("extracts command for run_command", () => {
    const result = getPrimaryArg("run_command", { command: "npm test" });
    expect(result).toBe("npm test");
  });

  test("extracts path when present", () => {
    const result = getPrimaryArg("read_file", { path: "/src/app.py" });
    expect(result).toBe("/src/app.py");
  });

  test("extracts file_path when present", () => {
    const result = getPrimaryArg("write_file", { file_path: "/src/main.ts" });
    expect(result).toBe("/src/main.ts");
  });

  test("extracts query when present", () => {
    const result = getPrimaryArg("search_files", { query: "TODO", directory: "/src" });
    expect(result).toBe("TODO");
  });

  test("extracts directory when present (and no path/file_path/query)", () => {
    const result = getPrimaryArg("list_directory", { directory: "/src/components" });
    expect(result).toBe("/src/components");
  });

  test("prefers path over file_path", () => {
    const result = getPrimaryArg("some_tool", { path: "/a", file_path: "/b" });
    expect(result).toBe("/a");
  });

  test("falls back to first short string value", () => {
    const result = getPrimaryArg("custom_tool", { data: "short value", count: 42 });
    expect(result).toBe("short value");
  });

  test("skips long strings in fallback (>= 200 chars)", () => {
    const longString = "x".repeat(200);
    const result = getPrimaryArg("custom_tool", { long: longString, short: "fallback" });
    expect(result).toBe("fallback");
  });

  test("returns empty string for null/undefined args", () => {
    expect(getPrimaryArg("tool", undefined)).toBe("");
    expect(getPrimaryArg("tool")).toBe("");
  });

  test("returns empty string when args is an empty object", () => {
    expect(getPrimaryArg("tool", {})).toBe("");
  });

  test("returns empty string when all values are non-string or too long", () => {
    const longStr = "x".repeat(250);
    const result = getPrimaryArg("tool", { num: 42, flag: true, big: longStr });
    expect(result).toBe("");
  });

  test("run_command returns empty string when command is falsy", () => {
    const result = getPrimaryArg("run_command", { command: "" });
    expect(result).toBe("");
  });

  test("run_command takes priority over path for run_command tool", () => {
    const result = getPrimaryArg("run_command", { command: "ls", path: "/src" });
    expect(result).toBe("ls");
  });
});

// ============================================================================
// Tool Utilities: formatDuration
// ============================================================================

describe("formatDuration", () => {
  test("formats milliseconds under 1000 as 'Xms'", () => {
    expect(formatDuration(50)).toBe("50ms");
    expect(formatDuration(999)).toBe("999ms");
    expect(formatDuration(0)).toBe("0ms");
  });

  test("formats exactly 1000ms as '1.0s'", () => {
    expect(formatDuration(1000)).toBe("1.0s");
  });

  test("formats seconds with one decimal", () => {
    expect(formatDuration(1500)).toBe("1.5s");
    expect(formatDuration(2000)).toBe("2.0s");
    expect(formatDuration(10300)).toBe("10.3s");
  });

  test("formats large durations correctly", () => {
    expect(formatDuration(65000)).toBe("65.0s");
    expect(formatDuration(120500)).toBe("120.5s");
  });

  test("handles single millisecond", () => {
    expect(formatDuration(1)).toBe("1ms");
  });
});
