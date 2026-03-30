/**
 * Unit tests for appReducer and dispatchServerMessage.
 *
 * Tests all 35+ action types, 70+ server message mappings,
 * and timeline architecture (commitMarkdownBuffer, chronological ordering).
 */
import { describe, test, expect, vi, beforeEach } from "vitest";
import {
  appReducer,
  initialState,
  dispatchServerMessage,
  resetTimelineCounter,
  type AppState,
  type Action,
} from "../state/reducer";
import type { ServerMessage, ToolStateData } from "../types";

// Helper: apply an action to initial state
function reduce(action: Action, state: AppState = initialState): AppState {
  return appReducer(state, action);
}

// Reset timeline counter before each test for deterministic IDs
beforeEach(() => {
  resetTimelineCounter();
});

// ============================================================================
// Connection actions
// ============================================================================

describe("appReducer — Connection", () => {
  test("SET_CONNECTED sets connected to true", () => {
    const s = reduce({ type: "SET_CONNECTED", connected: true });
    expect(s.connected).toBe(true);
  });

  test("SET_CONNECTED sets connected to false", () => {
    const s = reduce(
      { type: "SET_CONNECTED", connected: false },
      { ...initialState, connected: true },
    );
    expect(s.connected).toBe(false);
  });

  test("SET_SESSION_INFO sets session metadata", () => {
    const s = reduce({
      type: "SET_SESSION_INFO",
      sessionId: "sess-1",
      model: "gpt-4o",
      permissionMode: "plan",
      workingDirectory: "/work",
      autoApprove: { read: true, edit: true, execute: false, browser: true, knowledge_update: false, subagent: false },
    });
    expect(s.sessionId).toBe("sess-1");
    expect(s.modelName).toBe("gpt-4o");
    expect(s.permissionMode).toBe("plan");
    expect(s.workingDirectory).toBe("/work");
    expect(s.autoApprove).toEqual({ read: true, edit: true, execute: false, browser: true, knowledge_update: false, subagent: false });
  });

  test("SET_SESSION_INFO preserves existing workingDirectory when not provided", () => {
    const base = { ...initialState, workingDirectory: "/existing" };
    const s = reduce(
      { type: "SET_SESSION_INFO", sessionId: "s", model: "m", permissionMode: "n" },
      base,
    );
    expect(s.workingDirectory).toBe("/existing");
  });

  test("SET_SESSION_INFO preserves existing autoApprove when not provided", () => {
    const base = { ...initialState, autoApprove: { read: true, edit: true, execute: true, browser: false, knowledge_update: false, subagent: false } };
    const s = reduce(
      { type: "SET_SESSION_INFO", sessionId: "s", model: "m", permissionMode: "n" },
      base,
    );
    expect(s.autoApprove).toEqual({ read: true, edit: true, execute: true, browser: false, knowledge_update: false, subagent: false });
  });

  test("SET_SESSION_INFO resets conversation state on session change (GAP 16)", () => {
    // First set a session
    let s = reduce({
      type: "SET_SESSION_INFO",
      sessionId: "sess-1",
      model: "gpt-4o",
      permissionMode: "normal",
    });
    // Add some state
    s = reduce({ type: "ADD_USER_MESSAGE", content: "Hello" }, s);
    s = reduce({
      type: "TOOL_STATE_UPDATED",
      data: { call_id: "c1", status: "running", tool_name: "read_file" },
    }, s);
    expect(s.messages.length).toBeGreaterThan(0);
    expect(s.timeline.length).toBeGreaterThan(0);
    expect(Object.keys(s.toolCards).length).toBeGreaterThan(0);

    // Switch to a different session
    s = reduce({
      type: "SET_SESSION_INFO",
      sessionId: "sess-2",
      model: "gpt-4o",
      permissionMode: "normal",
    }, s);

    // All conversation state should be cleared
    expect(s.messages).toEqual([]);
    expect(s.timeline).toEqual([]);
    expect(s.toolCards).toEqual({});
    expect(s.toolOrder).toEqual([]);
    expect(s.subagents).toEqual({});
    expect(s.markdownBuffer).toBe("");
    expect(s.currentThinking).toBeNull();
    expect(s.currentCodeBlock).toBeNull();
    expect(s.isCompacting).toBe(false);
  });

  test("SET_SESSION_INFO does not reset state for same session", () => {
    let s = reduce({
      type: "SET_SESSION_INFO",
      sessionId: "sess-1",
      model: "gpt-4o",
      permissionMode: "normal",
    });
    s = reduce({ type: "ADD_USER_MESSAGE", content: "Hello" }, s);
    const msgCount = s.messages.length;

    // Same sessionId — should preserve state
    s = reduce({
      type: "SET_SESSION_INFO",
      sessionId: "sess-1",
      model: "gpt-4o-mini",
      permissionMode: "plan",
    }, s);

    expect(s.messages.length).toBe(msgCount);
    expect(s.modelName).toBe("gpt-4o-mini");
  });
});

// ============================================================================
// Streaming actions
// ============================================================================

describe("appReducer — Streaming", () => {
  test("STREAM_START enables streaming and clears buffers", () => {
    const base: AppState = {
      ...initialState,
      markdownBuffer: "leftover",
      currentThinking: { content: "old", open: true },
      currentCodeBlock: { language: "js", content: "x", complete: false },
      lastTurnStats: { tokens: 100, durationMs: 500 },
    };
    const s = reduce({ type: "STREAM_START" }, base);
    expect(s.isStreaming).toBe(true);
    expect(s.markdownBuffer).toBe("");
    expect(s.currentThinking).toBeNull();
    expect(s.currentCodeBlock).toBeNull();
    expect(s.lastTurnStats).toBeNull();
  });

  test("STREAM_END disables streaming and sets turn stats", () => {
    const base = { ...initialState, isStreaming: true, sessionTurnCount: 2, sessionTotalTokens: 500 };
    const s = reduce({ type: "STREAM_END", tokens: 150, durationMs: 1200 }, base);
    expect(s.isStreaming).toBe(false);
    expect(s.lastTurnStats).toEqual({ tokens: 150, durationMs: 1200 });
    expect(s.sessionTurnCount).toBe(3);
    expect(s.sessionTotalTokens).toBe(650);
  });

  test("STREAM_END with no tokens sets null stats", () => {
    const s = reduce({ type: "STREAM_END" }, { ...initialState, isStreaming: true });
    expect(s.lastTurnStats).toBeNull();
    expect(s.sessionTurnCount).toBe(1); // still increments
  });

  test("STREAM_END flushes markdown buffer to timeline (GAP 3)", () => {
    let s: AppState = { ...initialState, isStreaming: true, markdownBuffer: "Hello world" };
    s = reduce({ type: "STREAM_END", tokens: 100, durationMs: 500 }, s);
    expect(s.markdownBuffer).toBe("");
    expect(s.timeline).toHaveLength(1);
    expect(s.timeline[0].type).toBe("assistant_text");
    if (s.timeline[0].type === "assistant_text") {
      expect(s.timeline[0].content).toBe("Hello world");
    }
  });

  test("STREAM_END does not create empty timeline entry for whitespace-only buffer", () => {
    const s = reduce({ type: "STREAM_END" }, { ...initialState, isStreaming: true, markdownBuffer: "   " });
    expect(s.timeline).toHaveLength(0);
  });

  test("TEXT_DELTA appends to markdownBuffer", () => {
    const s1 = reduce({ type: "TEXT_DELTA", content: "Hello " });
    const s2 = reduce({ type: "TEXT_DELTA", content: "world" }, s1);
    expect(s2.markdownBuffer).toBe("Hello world");
  });
});

// ============================================================================
// Code blocks
// ============================================================================

describe("appReducer — Code blocks", () => {
  test("CODE_BLOCK_START creates a new code block", () => {
    const s = reduce({ type: "CODE_BLOCK_START", language: "python" });
    expect(s.currentCodeBlock).toEqual({ language: "python", content: "", complete: false });
  });

  test("CODE_BLOCK_START defaults language to empty string", () => {
    const s = reduce({ type: "CODE_BLOCK_START" });
    expect(s.currentCodeBlock!.language).toBe("");
  });

  test("CODE_BLOCK_START flushes markdown buffer (GAP 9)", () => {
    let s: AppState = { ...initialState, markdownBuffer: "Some text before code" };
    s = reduce({ type: "CODE_BLOCK_START", language: "js" }, s);
    expect(s.markdownBuffer).toBe("");
    expect(s.timeline).toHaveLength(1);
    expect(s.timeline[0].type).toBe("assistant_text");
  });

  test("CODE_BLOCK_DELTA appends content", () => {
    const base = reduce({ type: "CODE_BLOCK_START", language: "js" });
    const s1 = reduce({ type: "CODE_BLOCK_DELTA", content: "const x" }, base);
    const s2 = reduce({ type: "CODE_BLOCK_DELTA", content: " = 1;" }, s1);
    expect(s2.currentCodeBlock!.content).toBe("const x = 1;");
  });

  test("CODE_BLOCK_DELTA is no-op when no current code block", () => {
    const s = reduce({ type: "CODE_BLOCK_DELTA", content: "orphan" });
    expect(s).toBe(initialState);
  });

  test("CODE_BLOCK_END commits to timeline and clears currentCodeBlock (GAP 9)", () => {
    let s = reduce({ type: "CODE_BLOCK_START", language: "ts" });
    s = reduce({ type: "CODE_BLOCK_DELTA", content: "let x = 1;" }, s);
    s = reduce({ type: "CODE_BLOCK_END" }, s);
    expect(s.currentCodeBlock).toBeNull();
    const codeEntry = s.timeline.find((e) => e.type === "code");
    expect(codeEntry).toBeDefined();
    if (codeEntry && codeEntry.type === "code") {
      expect(codeEntry.language).toBe("ts");
      expect(codeEntry.content).toBe("let x = 1;");
    }
  });

  test("CODE_BLOCK_END when no block returns null", () => {
    const s = reduce({ type: "CODE_BLOCK_END" });
    expect(s.currentCodeBlock).toBeNull();
  });
});

// ============================================================================
// Thinking
// ============================================================================

describe("appReducer — Thinking", () => {
  test("THINKING_START creates open thinking block", () => {
    const s = reduce({ type: "THINKING_START" });
    expect(s.currentThinking).toEqual({ content: "", open: true });
  });

  test("THINKING_START flushes markdown buffer (GAP 10)", () => {
    let s: AppState = { ...initialState, markdownBuffer: "Text before thinking" };
    s = reduce({ type: "THINKING_START" }, s);
    expect(s.markdownBuffer).toBe("");
    expect(s.timeline).toHaveLength(1);
    expect(s.timeline[0].type).toBe("assistant_text");
  });

  test("THINKING_DELTA appends content", () => {
    const base = reduce({ type: "THINKING_START" });
    const s = reduce({ type: "THINKING_DELTA", content: "Analyzing..." }, base);
    expect(s.currentThinking!.content).toBe("Analyzing...");
  });

  test("THINKING_DELTA is no-op without active thinking", () => {
    const s = reduce({ type: "THINKING_DELTA", content: "orphan" });
    expect(s).toBe(initialState);
  });

  test("THINKING_END commits to timeline and clears currentThinking (GAP 10)", () => {
    let s = reduce({ type: "THINKING_START" });
    s = reduce({ type: "THINKING_DELTA", content: "Deep analysis" }, s);
    s = reduce({ type: "THINKING_END" }, s);
    expect(s.currentThinking).toBeNull();
    const thinkingEntry = s.timeline.find((e) => e.type === "thinking");
    expect(thinkingEntry).toBeDefined();
    if (thinkingEntry && thinkingEntry.type === "thinking") {
      expect(thinkingEntry.content).toBe("Deep analysis");
    }
  });

  test("THINKING_END is no-op without active thinking", () => {
    const s = reduce({ type: "THINKING_END" });
    expect(s).toBe(initialState);
  });
});

// ============================================================================
// Messages
// ============================================================================

describe("appReducer — Messages", () => {
  test("ADD_USER_MESSAGE appends to both messages and timeline", () => {
    const s = reduce({ type: "ADD_USER_MESSAGE", content: "Hello" });
    expect(s.messages).toHaveLength(1);
    expect(s.messages[0].role).toBe("user");
    expect(s.messages[0].content).toBe("Hello");
    expect(s.messages[0].finalized).toBe(true);
    expect(s.messages[0].id).toMatch(/^user-/);
    // Timeline entry
    expect(s.timeline).toHaveLength(1);
    expect(s.timeline[0].type).toBe("user_message");
  });

  test("MESSAGE_ADDED ignores system messages (GAP 7)", () => {
    const s = reduce({
      type: "MESSAGE_ADDED",
      data: { uuid: "msg-sys", role: "system", content: "System prompt" },
    });
    expect(s.messages).toHaveLength(0);
  });

  test("MESSAGE_ADDED ignores user messages (already local)", () => {
    const s = reduce({
      type: "MESSAGE_ADDED",
      data: { uuid: "msg-user", role: "user", content: "Hello" },
    });
    expect(s.messages).toHaveLength(0);
  });

  test("MESSAGE_ADDED ignores assistant messages (built from streaming)", () => {
    const s = reduce({
      type: "MESSAGE_ADDED",
      data: { uuid: "msg-asst", role: "assistant", content: "Hi" },
    });
    expect(s.messages).toHaveLength(0);
  });

  test("MESSAGE_ADDED routes subagent messages to subagent (GAP 5)", () => {
    const saInfo = {
      subagentId: "sa-1",
      parentToolCallId: "call-parent",
      modelName: "gpt-4o-mini",
      subagentName: "researcher",
      startTime: 1000,
      toolCount: 0,
      active: true,
      messages: [],
      timeline: [],
      totalTokens: 0,
      contextTokens: 0,
      contextWindow: 0,
    };
    let s = reduce({ type: "SUBAGENT_REGISTERED", data: saInfo });
    s = reduce({
      type: "MESSAGE_ADDED",
      data: { uuid: "msg-sa", role: "assistant", content: "Subagent says hi" },
      subagentId: "sa-1",
    }, s);
    expect(s.subagents["sa-1"].messages).toEqual(["Subagent says hi"]);
    expect(s.messages).toHaveLength(0); // not in main messages
  });

  test("MESSAGE_UPDATED updates content by uuid", () => {
    // First add a message directly to state for backward compat testing
    const base: AppState = {
      ...initialState,
      messages: [{ id: "msg-2", role: "assistant", content: "Draft", finalized: false }],
    };
    const s = reduce(
      { type: "MESSAGE_UPDATED", data: { uuid: "msg-2", content: "Final" } },
      base,
    );
    expect(s.messages[0].content).toBe("Final");
  });

  test("MESSAGE_UPDATED routes subagent text update (GAP 5)", () => {
    const saInfo = {
      subagentId: "sa-1",
      parentToolCallId: "call-parent",
      modelName: "gpt-4o-mini",
      subagentName: "researcher",
      startTime: 1000,
      toolCount: 0,
      active: true,
      messages: ["Old text"],
      timeline: [{ type: "text" as const, index: 0 }],
      totalTokens: 0,
      contextTokens: 0,
      contextWindow: 0,
    };
    let s = reduce({ type: "SUBAGENT_REGISTERED", data: saInfo });
    s = reduce({
      type: "MESSAGE_UPDATED",
      data: { uuid: "msg-sa", content: "Updated text" },
      subagentId: "sa-1",
    }, s);
    expect(s.subagents["sa-1"].messages).toEqual(["Updated text"]);
  });

  test("MESSAGE_UPDATED ignores unknown uuid", () => {
    const base: AppState = {
      ...initialState,
      messages: [{ id: "msg-3", role: "assistant", content: "X", finalized: false }],
    };
    const s = reduce(
      { type: "MESSAGE_UPDATED", data: { uuid: "unknown", content: "Y" } },
      base,
    );
    expect(s.messages[0].content).toBe("X");
  });

  test("MESSAGE_FINALIZED marks messages with matching streamId", () => {
    const base: AppState = {
      ...initialState,
      messages: [{ id: "m1", role: "assistant", content: "X", streamId: "stream-1", finalized: false }],
    };
    const s = reduce({ type: "MESSAGE_FINALIZED", streamId: "stream-1" }, base);
    expect(s.messages[0].finalized).toBe(true);
  });

  test("MESSAGE_FINALIZED ignores non-matching streamIds", () => {
    const base: AppState = {
      ...initialState,
      messages: [{ id: "m2", role: "assistant", content: "Y", streamId: "stream-2", finalized: false }],
    };
    const s = reduce({ type: "MESSAGE_FINALIZED", streamId: "other" }, base);
    expect(s.messages[0].finalized).toBe(false);
  });
});

// ============================================================================
// Tools
// ============================================================================

describe("appReducer — Tools", () => {
  const toolData: ToolStateData = {
    call_id: "call-1",
    tool_name: "read_file",
    status: "running",
    arguments: { file_path: "/test.py" },
  };

  test("TOOL_STATE_UPDATED adds a new tool card, tracks order, and adds timeline entry", () => {
    const s = reduce({ type: "TOOL_STATE_UPDATED", data: toolData });
    expect(s.toolCards["call-1"]).toEqual(toolData);
    expect(s.toolOrder).toEqual(["call-1"]);
    // Timeline entry for main-agent tool
    const toolEntry = s.timeline.find((e) => e.type === "tool");
    expect(toolEntry).toBeDefined();
  });

  test("TOOL_STATE_UPDATED updates existing card without duplicating order or timeline", () => {
    const base = reduce({ type: "TOOL_STATE_UPDATED", data: toolData });
    const timelineLen = base.timeline.length;
    const updated = { ...toolData, status: "success" as const, duration_ms: 120 };
    const s = reduce({ type: "TOOL_STATE_UPDATED", data: updated }, base);
    expect(s.toolCards["call-1"].status).toBe("success");
    expect(s.toolCards["call-1"].duration_ms).toBe(120);
    expect(s.toolOrder).toEqual(["call-1"]); // no duplicate
    expect(s.timeline).toHaveLength(timelineLen); // no new entry
  });

  test("TOOL_STATE_UPDATED merges metadata, preserving tool_name and arguments (GAP 2)", () => {
    // First update has full metadata
    const base = reduce({
      type: "TOOL_STATE_UPDATED",
      data: { call_id: "c1", tool_name: "edit_file", status: "running", arguments: { file_path: "/a.py" } },
    });
    // Second update has only status (no tool_name or arguments)
    const s = reduce({
      type: "TOOL_STATE_UPDATED",
      data: { call_id: "c1", status: "success", duration_ms: 100 },
    }, base);
    // tool_name and arguments should be preserved from the first update
    expect(s.toolCards["c1"].tool_name).toBe("edit_file");
    expect(s.toolCards["c1"].arguments).toEqual({ file_path: "/a.py" });
    expect(s.toolCards["c1"].status).toBe("success");
    expect(s.toolCards["c1"].duration_ms).toBe(100);
  });

  test("TOOL_STATE_UPDATED flushes markdown buffer before adding tool (GAP 3)", () => {
    let s: AppState = { ...initialState, markdownBuffer: "Text before tool" };
    s = reduce({ type: "TOOL_STATE_UPDATED", data: toolData }, s);
    expect(s.markdownBuffer).toBe("");
    // Should have text entry then tool entry
    expect(s.timeline).toHaveLength(2);
    expect(s.timeline[0].type).toBe("assistant_text");
    expect(s.timeline[1].type).toBe("tool");
  });

  test("multiple tools maintain insertion order", () => {
    let s = reduce({ type: "TOOL_STATE_UPDATED", data: { ...toolData, call_id: "a" } });
    s = reduce({ type: "TOOL_STATE_UPDATED", data: { ...toolData, call_id: "b" } }, s);
    s = reduce({ type: "TOOL_STATE_UPDATED", data: { ...toolData, call_id: "c" } }, s);
    expect(s.toolOrder).toEqual(["a", "b", "c"]);
  });

  test("TOOL_STATE_UPDATED for subagent tool does not add main timeline entry", () => {
    const saInfo = {
      subagentId: "sa-1",
      parentToolCallId: "call-parent",
      modelName: "gpt-4o-mini",
      subagentName: "researcher",
      startTime: 1000,
      toolCount: 0,
      active: true,
      messages: [],
      timeline: [],
      totalTokens: 0,
      contextTokens: 0,
      contextWindow: 0,
    };
    let s = reduce({ type: "SUBAGENT_REGISTERED", data: saInfo });
    const timelineLen = s.timeline.length;
    s = reduce({
      type: "TOOL_STATE_UPDATED",
      data: { call_id: "sa-tool-1", status: "running", tool_name: "read_file" },
      subagentId: "sa-1",
    }, s);
    // No new main timeline entry (subagent tools render inside SubagentCard)
    expect(s.timeline.length).toBe(timelineLen);
  });
});

// ============================================================================
// Subagents
// ============================================================================

describe("appReducer — Subagents", () => {
  const saInfo = {
    subagentId: "sa-1",
    parentToolCallId: "call-parent",
    modelName: "gpt-4o-mini",
    subagentName: "researcher",
    startTime: 1000,
    toolCount: 0,
    active: true,
    messages: [],
    timeline: [],
    totalTokens: 0,
    contextTokens: 0,
    contextWindow: 0,
  };

  test("SUBAGENT_REGISTERED adds subagent info with messages[] and timeline entry (GAP 6)", () => {
    const s = reduce({ type: "SUBAGENT_REGISTERED", data: saInfo });
    expect(s.subagents["sa-1"]).toEqual(saInfo);
    expect(s.subagents["sa-1"].messages).toEqual([]);
    // Timeline entry
    const saEntry = s.timeline.find((e) => e.type === "subagent");
    expect(saEntry).toBeDefined();
  });

  test("SUBAGENT_REGISTERED flushes markdown buffer (GAP 6)", () => {
    let s: AppState = { ...initialState, markdownBuffer: "Text before subagent" };
    s = reduce({ type: "SUBAGENT_REGISTERED", data: saInfo }, s);
    expect(s.markdownBuffer).toBe("");
    expect(s.timeline[0].type).toBe("assistant_text");
    expect(s.timeline[1].type).toBe("subagent");
  });

  test("SUBAGENT_UNREGISTERED marks subagent inactive with elapsed time", () => {
    const base = reduce({ type: "SUBAGENT_REGISTERED", data: saInfo });
    const s = reduce({ type: "SUBAGENT_UNREGISTERED", subagentId: "sa-1" }, base);
    expect(s.subagents["sa-1"].active).toBe(false);
    expect(s.subagents["sa-1"].finalElapsedMs).toBeDefined();
  });

  test("SUBAGENT_UNREGISTERED is safe for unknown id", () => {
    const s = reduce({ type: "SUBAGENT_UNREGISTERED", subagentId: "unknown" });
    expect(s.subagents).toEqual({});
  });

  test("TOOL_STATE_UPDATED with subagentId tracks ownership", () => {
    const base = reduce({ type: "SUBAGENT_REGISTERED", data: saInfo });
    const s = reduce({
      type: "TOOL_STATE_UPDATED",
      data: { call_id: "tc-1", status: "running", tool_name: "read_file" },
      subagentId: "sa-1",
    }, base);
    expect(s.toolCardOwners["tc-1"]).toBe("sa-1");
    expect(s.subagents["sa-1"].toolCount).toBe(1);
  });

  test("TOOL_STATE_UPDATED promotes subagent approval to top level", () => {
    const base = reduce({ type: "SUBAGENT_REGISTERED", data: saInfo });
    const s = reduce({
      type: "TOOL_STATE_UPDATED",
      data: { call_id: "tc-2", status: "awaiting_approval", tool_name: "write_file" },
      subagentId: "sa-1",
    }, base);
    expect(s.promotedApprovals["tc-2"]).toBeDefined();
    expect(s.promotedApprovals["tc-2"].subagentId).toBe("sa-1");
  });

  test("TOOL_STATE_UPDATED dismisses promoted approval when status changes", () => {
    const base = reduce({ type: "SUBAGENT_REGISTERED", data: saInfo });
    const withApproval = reduce({
      type: "TOOL_STATE_UPDATED",
      data: { call_id: "tc-2", status: "awaiting_approval", tool_name: "write_file" },
      subagentId: "sa-1",
    }, base);
    expect(withApproval.promotedApprovals["tc-2"]).toBeDefined();
    const s = reduce({
      type: "TOOL_STATE_UPDATED",
      data: { call_id: "tc-2", status: "approved", tool_name: "write_file" },
      subagentId: "sa-1",
    }, withApproval);
    expect(s.promotedApprovals["tc-2"]).toBeUndefined();
  });

  test("DISMISS_SUBAGENT_APPROVAL removes promoted approval", () => {
    const base = reduce({ type: "SUBAGENT_REGISTERED", data: saInfo });
    const withApproval = reduce({
      type: "TOOL_STATE_UPDATED",
      data: { call_id: "tc-3", status: "awaiting_approval", tool_name: "edit_file" },
      subagentId: "sa-1",
    }, base);
    const s = reduce({ type: "DISMISS_SUBAGENT_APPROVAL", callId: "tc-3" }, withApproval);
    expect(s.promotedApprovals["tc-3"]).toBeUndefined();
  });
});

// ============================================================================
// Interactive
// ============================================================================

describe("appReducer — Interactive", () => {
  test("PAUSE_PROMPT_START sets pause state", () => {
    const s = reduce({
      type: "PAUSE_PROMPT_START",
      reason: "Max iterations reached",
      reasonCode: "max_iterations",
      stats: { iterations: 10, tokens: 5000 },
      pendingTodos: ["Fix tests", "Update docs"],
    });
    expect(s.pausePrompt).toEqual({
      reason: "Max iterations reached",
      reasonCode: "max_iterations",
      stats: { iterations: 10, tokens: 5000 },
      pendingTodos: ["Fix tests", "Update docs"],
    });
  });

  test("PAUSE_PROMPT_END clears pause state", () => {
    const base = reduce({
      type: "PAUSE_PROMPT_START",
      reason: "r",
      reasonCode: "rc",
      stats: {},
    });
    const s = reduce({ type: "PAUSE_PROMPT_END" }, base);
    expect(s.pausePrompt).toBeNull();
  });

  test("CLARIFY_REQUEST sets clarify state", () => {
    const s = reduce({
      type: "CLARIFY_REQUEST",
      callId: "c1",
      questions: [{ id: "q1", label: "Which?" }],
      context: "Need more info",
    });
    expect(s.clarifyRequest).toEqual({
      callId: "c1",
      questions: [{ id: "q1", label: "Which?" }],
      context: "Need more info",
    });
  });

  test("CLARIFY_DISMISS clears clarify state", () => {
    const base = reduce({
      type: "CLARIFY_REQUEST",
      callId: "c1",
      questions: [],
    });
    const s = reduce({ type: "CLARIFY_DISMISS" }, base);
    expect(s.clarifyRequest).toBeNull();
  });

  test("PLAN_APPROVAL sets plan approval state", () => {
    const s = reduce({
      type: "PLAN_APPROVAL",
      callId: "p1",
      planHash: "hash123",
      excerpt: "## Plan\n- Step 1",
      truncated: true,
      planPath: "/tmp/plan.md",
    });
    expect(s.planApproval).toEqual({
      callId: "p1",
      planHash: "hash123",
      excerpt: "## Plan\n- Step 1",
      truncated: true,
      planPath: "/tmp/plan.md",
    });
  });

  test("PLAN_APPROVAL_DISMISS clears plan state", () => {
    const base = reduce({
      type: "PLAN_APPROVAL",
      callId: "p1",
      planHash: "h",
      excerpt: "x",
      truncated: false,
    });
    const s = reduce({ type: "PLAN_APPROVAL_DISMISS" }, base);
    expect(s.planApproval).toBeNull();
  });

  test("PERMISSION_MODE_CHANGED updates mode", () => {
    const s = reduce({ type: "PERMISSION_MODE_CHANGED", mode: "plan" });
    expect(s.permissionMode).toBe("plan");
  });
});

// ============================================================================
// Context
// ============================================================================

describe("appReducer — Context", () => {
  test("CONTEXT_UPDATED sets used and limit", () => {
    const s = reduce({ type: "CONTEXT_UPDATED", used: 50000, limit: 128000 });
    expect(s.contextUsed).toBe(50000);
    expect(s.contextLimit).toBe(128000);
  });

  test("CONTEXT_COMPACTING sets isCompacting to true", () => {
    const s = reduce({ type: "CONTEXT_COMPACTING" });
    expect(s.isCompacting).toBe(true);
  });

  test("CONTEXT_COMPACTED clears isCompacting", () => {
    // Start compacting then complete
    const s1 = reduce({ type: "CONTEXT_COMPACTING" });
    const s2 = appReducer(s1, { type: "CONTEXT_COMPACTED" });
    expect(s2.isCompacting).toBe(false);
  });

  test("STREAM_END clears isCompacting even if CONTEXT_COMPACTED was missed", () => {
    // Simulate compaction starting but context_compacted never arriving (agent crash)
    const s1 = reduce({ type: "CONTEXT_COMPACTING" });
    expect(s1.isCompacting).toBe(true);
    const s2 = appReducer(s1, { type: "STREAM_END" });
    expect(s2.isCompacting).toBe(false);
  });

  test("MESSAGE_ADDED with is_compact_summary adds compaction_summary timeline entry", () => {
    const s = reduce({
      type: "MESSAGE_ADDED",
      data: {
        uuid: "summary-uuid-1",
        role: "user",
        content: "[Conversation summary - earlier messages were compacted to free context space]\n\nThe user asked about X.",
        is_compact_summary: true,
      },
    });
    const entry = s.timeline.find((e) => e.type === "compaction_summary");
    expect(entry).toBeDefined();
    expect(entry?.type).toBe("compaction_summary");
    if (entry?.type === "compaction_summary") {
      expect(entry.id).toBe("summary-uuid-1");
      expect(entry.content).toContain("Conversation summary");
    }
  });

  test("MESSAGE_ADDED with is_compact_summary does NOT add to messages array", () => {
    const s = reduce({
      type: "MESSAGE_ADDED",
      data: {
        uuid: "summary-uuid-2",
        role: "user",
        content: "[Conversation summary...]\n\nSummary text.",
        is_compact_summary: true,
      },
    });
    expect(s.messages.find((m) => m.id === "summary-uuid-2")).toBeUndefined();
  });
});

// ============================================================================
// Panels
// ============================================================================

describe("appReducer — Panels", () => {
  test("SET_ACTIVE_PANEL changes active panel", () => {
    const s = reduce({ type: "SET_ACTIVE_PANEL", panel: "sessions" });
    expect(s.activePanel).toBe("sessions");
  });

  test("SET_SESSIONS stores session list", () => {
    const sessions = [
      { session_id: "s1", first_message: "Hi", message_count: 3, updated_at: "2026-01-01" },
    ];
    const s = reduce({ type: "SET_SESSIONS", sessions });
    expect(s.sessions).toEqual(sessions);
  });

  test("REPLAY_MESSAGES filters system messages and builds timeline (GAPs 7, 8)", () => {
    const messages = [
      { role: "system", content: "System prompt" },
      { role: "user", content: "Hello" },
      { role: "assistant", content: "Hi there" },
    ];
    const s = reduce({ type: "REPLAY_MESSAGES", messages });
    // System messages filtered from ChatMessage array
    expect(s.messages.every((m) => m.role !== "system")).toBe(true);
    // Timeline built
    expect(s.timeline.length).toBeGreaterThan(0);
    const userEntry = s.timeline.find((e) => e.type === "user_message");
    expect(userEntry).toBeDefined();
    const textEntry = s.timeline.find((e) => e.type === "assistant_text");
    expect(textEntry).toBeDefined();
  });

  test("REPLAY_MESSAGES reconstructs tool cards from tool_calls (GAP 8)", () => {
    const messages = [
      { role: "user", content: "Read the file" },
      {
        role: "assistant",
        content: "",
        tool_calls: [{
          id: "tc-replay-1",
          function: { name: "read_file", arguments: '{"file_path":"/a.py"}' },
        }],
      },
      {
        role: "tool",
        content: "file contents here",
        tool_call_id: "tc-replay-1",
        meta: { status: "success", duration_ms: 50, tool_name: "read_file" },
      },
    ];
    const s = reduce({ type: "REPLAY_MESSAGES", messages });
    // Tool card reconstructed
    expect(s.toolCards["tc-replay-1"]).toBeDefined();
    expect(s.toolCards["tc-replay-1"].tool_name).toBe("read_file");
    expect(s.toolCards["tc-replay-1"].status).toBe("success");
    expect(s.toolCards["tc-replay-1"].arguments).toEqual({ file_path: "/a.py" });
    // Timeline has tool entry
    const toolEntry = s.timeline.find((e) => e.type === "tool");
    expect(toolEntry).toBeDefined();
  });

  test("REPLAY_MESSAGES replaces existing messages", () => {
    const base = reduce({ type: "ADD_USER_MESSAGE", content: "old" });
    const s = reduce({ type: "REPLAY_MESSAGES", messages: [{ role: "user", content: "new" }] }, base);
    expect(s.messages).toHaveLength(1);
    expect(s.messages[0].content).toBe("new");
  });
});

// ============================================================================
// Auto-approve
// ============================================================================

describe("appReducer — Auto-approve", () => {
  test("AUTO_APPROVE_CHANGED updates categories", () => {
    const s = reduce({
      type: "AUTO_APPROVE_CHANGED",
      categories: { read: true, edit: true, execute: false, browser: true },
    });
    expect(s.autoApprove).toEqual({ read: true, edit: true, execute: false, browser: true, knowledge_update: false, subagent: false });
  });

  test("AUTO_APPROVE_CHANGED coerces falsy values to false", () => {
    const s = reduce({
      type: "AUTO_APPROVE_CHANGED",
      categories: {},
    });
    expect(s.autoApprove).toEqual({ read: false, edit: false, execute: false, browser: false, knowledge_update: false, subagent: false });
  });
});

// ============================================================================
// Todos
// ============================================================================

describe("appReducer — Todos", () => {
  test("TODOS_UPDATED replaces todo list", () => {
    const todos = [
      { id: "t1", subject: "Fix bug", status: "in_progress" },
      { id: "t2", subject: "Write tests", status: "pending" },
    ];
    const s = reduce({ type: "TODOS_UPDATED", todos });
    expect(s.todos).toEqual(todos);
  });
});

// ============================================================================
// Input
// ============================================================================

describe("appReducer — Input", () => {
  test("ADD_ATTACHMENT appends to attachments", () => {
    const s1 = reduce({ type: "ADD_ATTACHMENT", attachment: { path: "/a.py", name: "a.py" } });
    const s2 = reduce({ type: "ADD_ATTACHMENT", attachment: { path: "/b.py", name: "b.py" } }, s1);
    expect(s2.attachments).toHaveLength(2);
    expect(s2.attachments[1].name).toBe("b.py");
  });

  test("REMOVE_ATTACHMENT removes by index", () => {
    let s = reduce({ type: "ADD_ATTACHMENT", attachment: { path: "/a.py", name: "a.py" } });
    s = reduce({ type: "ADD_ATTACHMENT", attachment: { path: "/b.py", name: "b.py" } }, s);
    s = reduce({ type: "REMOVE_ATTACHMENT", index: 0 }, s);
    expect(s.attachments).toHaveLength(1);
    expect(s.attachments[0].name).toBe("b.py");
  });

  test("ADD_IMAGE appends to images", () => {
    const s = reduce({ type: "ADD_IMAGE", image: { data: "data:img", mimeType: "image/png" } });
    expect(s.images).toHaveLength(1);
  });

  test("REMOVE_IMAGE removes by index", () => {
    let s = reduce({ type: "ADD_IMAGE", image: { data: "d1", mimeType: "image/png" } });
    s = reduce({ type: "ADD_IMAGE", image: { data: "d2", mimeType: "image/jpeg" } }, s);
    s = reduce({ type: "REMOVE_IMAGE", index: 0 }, s);
    expect(s.images).toHaveLength(1);
    expect(s.images[0].mimeType).toBe("image/jpeg");
  });

  test("CLEAR_INPUT clears attachments, images, and mention results", () => {
    let s = reduce({ type: "ADD_ATTACHMENT", attachment: { path: "/a", name: "a" } });
    s = reduce({ type: "ADD_IMAGE", image: { data: "d", mimeType: "image/png" } }, s);
    s = reduce({ type: "SET_MENTION_RESULTS", files: [{ path: "/x", name: "x", relativePath: "x" }] }, s);
    s = reduce({ type: "CLEAR_INPUT" }, s);
    expect(s.attachments).toEqual([]);
    expect(s.images).toEqual([]);
    expect(s.mentionResults).toEqual([]);
  });

  test("SET_MENTION_RESULTS sets file suggestions", () => {
    const files = [
      { path: "/src/a.ts", name: "a.ts", relativePath: "src/a.ts" },
      { path: "/src/b.ts", name: "b.ts", relativePath: "src/b.ts" },
    ];
    const s = reduce({ type: "SET_MENTION_RESULTS", files });
    expect(s.mentionResults).toEqual(files);
  });
});

// ============================================================================
// Undo
// ============================================================================

describe("appReducer — Undo", () => {
  test("UNDO_AVAILABLE sets undo info and resets undoCompleted", () => {
    const s = reduce({ type: "UNDO_AVAILABLE", turnId: "t1", files: ["/a.py", "/b.py"] });
    expect(s.undoAvailable).toEqual({ turnId: "t1", files: ["/a.py", "/b.py"] });
    expect(s.undoCompleted).toBe(false);
  });

  test("UNDO_COMPLETE sets undoCompleted without clearing undoAvailable", () => {
    const base = reduce({ type: "UNDO_AVAILABLE", turnId: "t1", files: ["/a.py"] });
    const s = reduce({ type: "UNDO_COMPLETE", turnId: "t1" }, base);
    expect(s.undoAvailable).toEqual({ turnId: "t1", files: ["/a.py"] });
    expect(s.undoCompleted).toBe(true);
  });
});

// ============================================================================
// Error
// ============================================================================

describe("appReducer — Error", () => {
  test("ERROR adds error to timeline (GAP 15)", () => {
    const s = reduce({ type: "ERROR", errorType: "fatal", message: "boom" });
    expect(s.timeline).toHaveLength(1);
    expect(s.timeline[0].type).toBe("error");
    if (s.timeline[0].type === "error") {
      expect(s.timeline[0].message).toBe("boom");
    }
  });

  test("ERROR flushes markdown buffer before adding error", () => {
    let s: AppState = { ...initialState, markdownBuffer: "Some text" };
    s = reduce({ type: "ERROR", errorType: "api_error", message: "Failed" }, s);
    expect(s.markdownBuffer).toBe("");
    expect(s.timeline).toHaveLength(2);
    expect(s.timeline[0].type).toBe("assistant_text");
    expect(s.timeline[1].type).toBe("error");
  });
});

// ============================================================================
// Timeline ordering
// ============================================================================

describe("appReducer — Timeline ordering", () => {
  test("text -> tool -> text produces correct timeline order", () => {
    let s: AppState = { ...initialState, markdownBuffer: "First text" };
    // Tool arrives — flushes text
    s = reduce({
      type: "TOOL_STATE_UPDATED",
      data: { call_id: "c1", status: "running", tool_name: "read_file" },
    }, s);
    // More text
    s = reduce({ type: "TEXT_DELTA", content: "Second text" }, s);
    // Stream ends — flushes remaining text
    s = reduce({ type: "STREAM_END", tokens: 100 }, s);

    expect(s.timeline).toHaveLength(3);
    expect(s.timeline[0].type).toBe("assistant_text"); // "First text"
    expect(s.timeline[1].type).toBe("tool");            // read_file
    expect(s.timeline[2].type).toBe("assistant_text"); // "Second text"
  });

  test("text -> thinking -> text -> tool produces correct order", () => {
    let s: AppState = { ...initialState, markdownBuffer: "Intro" };
    // Thinking starts — flushes text
    s = reduce({ type: "THINKING_START" }, s);
    s = reduce({ type: "THINKING_DELTA", content: "Let me think" }, s);
    s = reduce({ type: "THINKING_END" }, s);
    // More text
    s = reduce({ type: "TEXT_DELTA", content: "After thinking" }, s);
    // Tool arrives — flushes text
    s = reduce({
      type: "TOOL_STATE_UPDATED",
      data: { call_id: "c1", status: "running", tool_name: "write_file" },
    }, s);

    expect(s.timeline).toHaveLength(4);
    expect(s.timeline[0].type).toBe("assistant_text"); // "Intro"
    expect(s.timeline[1].type).toBe("thinking");
    expect(s.timeline[2].type).toBe("assistant_text"); // "After thinking"
    expect(s.timeline[3].type).toBe("tool");
  });
});

// ============================================================================
// Default case
// ============================================================================

describe("appReducer — default", () => {
  test("unknown action returns state unchanged", () => {
    // @ts-expect-error - intentionally testing unknown action type
    const s = reduce({ type: "UNKNOWN_ACTION" });
    expect(s).toBe(initialState);
  });
});

// ============================================================================
// dispatchServerMessage
// ============================================================================

describe("dispatchServerMessage", () => {
  let dispatch: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    dispatch = vi.fn();
  });

  // Helper
  function dispatchMsg(msg: ServerMessage) {
    dispatchServerMessage(dispatch, msg);
  }

  // ── Streaming ──

  test("stream_start dispatches STREAM_START", () => {
    dispatchMsg({ type: "stream_start" });
    expect(dispatch).toHaveBeenCalledWith({ type: "STREAM_START" });
  });

  test("stream_end dispatches STREAM_END with tokens and duration", () => {
    dispatchMsg({ type: "stream_end", total_tokens: 500, duration_ms: 2000 });
    expect(dispatch).toHaveBeenCalledWith({ type: "STREAM_END", tokens: 500, durationMs: 2000 });
  });

  test("text_delta dispatches TEXT_DELTA", () => {
    dispatchMsg({ type: "text_delta", content: "hello" });
    expect(dispatch).toHaveBeenCalledWith({ type: "TEXT_DELTA", content: "hello" });
  });

  // ── Code blocks ──

  test("code_block_start dispatches CODE_BLOCK_START", () => {
    dispatchMsg({ type: "code_block_start", language: "python" });
    expect(dispatch).toHaveBeenCalledWith({ type: "CODE_BLOCK_START", language: "python" });
  });

  test("code_block_delta dispatches CODE_BLOCK_DELTA", () => {
    dispatchMsg({ type: "code_block_delta", content: "x = 1" });
    expect(dispatch).toHaveBeenCalledWith({ type: "CODE_BLOCK_DELTA", content: "x = 1" });
  });

  test("code_block_end dispatches CODE_BLOCK_END", () => {
    dispatchMsg({ type: "code_block_end" });
    expect(dispatch).toHaveBeenCalledWith({ type: "CODE_BLOCK_END" });
  });

  // ── Thinking ──

  test("thinking_start dispatches THINKING_START", () => {
    dispatchMsg({ type: "thinking_start" });
    expect(dispatch).toHaveBeenCalledWith({ type: "THINKING_START" });
  });

  test("thinking_delta dispatches THINKING_DELTA", () => {
    dispatchMsg({ type: "thinking_delta", content: "Let me think..." });
    expect(dispatch).toHaveBeenCalledWith({ type: "THINKING_DELTA", content: "Let me think..." });
  });

  test("thinking_end dispatches THINKING_END", () => {
    dispatchMsg({ type: "thinking_end" });
    expect(dispatch).toHaveBeenCalledWith({ type: "THINKING_END" });
  });

  // ── Context ──

  test("context_updated dispatches CONTEXT_UPDATED", () => {
    dispatchMsg({ type: "context_updated", used: 40000, limit: 128000 });
    expect(dispatch).toHaveBeenCalledWith({ type: "CONTEXT_UPDATED", used: 40000, limit: 128000 });
  });

  // ── Pause ──

  test("pause_prompt_start dispatches PAUSE_PROMPT_START", () => {
    dispatchMsg({
      type: "pause_prompt_start",
      reason: "Max iterations",
      reason_code: "max_iterations",
      stats: { iterations: 10 },
      pending_todos: ["Task A"],
    });
    expect(dispatch).toHaveBeenCalledWith({
      type: "PAUSE_PROMPT_START",
      reason: "Max iterations",
      reasonCode: "max_iterations",
      stats: { iterations: 10 },
      pendingTodos: ["Task A"],
    });
  });

  test("pause_prompt_end dispatches PAUSE_PROMPT_END", () => {
    dispatchMsg({ type: "pause_prompt_end", continue_work: true });
    expect(dispatch).toHaveBeenCalledWith({ type: "PAUSE_PROMPT_END" });
  });

  // ── Error ──

  test("error dispatches ERROR", () => {
    dispatchMsg({ type: "error", error_type: "api_error", user_message: "Failed", recoverable: true });
    expect(dispatch).toHaveBeenCalledWith({ type: "ERROR", errorType: "api_error", message: "Failed" });
  });

  // ── Todos ──

  test("todos_updated dispatches TODOS_UPDATED", () => {
    const todos = [{ id: "1", subject: "Test" }];
    dispatchMsg({ type: "todos_updated", todos });
    expect(dispatch).toHaveBeenCalledWith({ type: "TODOS_UPDATED", todos });
  });

  // ── Auto-approve ──

  test("auto_approve_changed dispatches AUTO_APPROVE_CHANGED", () => {
    dispatchMsg({ type: "auto_approve_changed", categories: { edit: true, execute: false, browser: false } });
    expect(dispatch).toHaveBeenCalledWith({
      type: "AUTO_APPROVE_CHANGED",
      categories: { edit: true, execute: false, browser: false },
    });
  });

  // ── Sessions ──

  test("sessions_list dispatches SET_SESSIONS", () => {
    const sessions = [{ session_id: "s1", first_message: "Hi", message_count: 1, updated_at: "now" }];
    dispatchMsg({ type: "sessions_list", sessions });
    expect(dispatch).toHaveBeenCalledWith({ type: "SET_SESSIONS", sessions });
  });

  test("session_history dispatches REPLAY_MESSAGES", () => {
    const messages = [{ role: "user", content: "Hello" }];
    dispatchMsg({ type: "session_history", messages });
    expect(dispatch).toHaveBeenCalledWith({ type: "REPLAY_MESSAGES", messages });
  });

  // ── Store events ──

  test("store tool_state_updated dispatches TOOL_STATE_UPDATED", () => {
    const data: ToolStateData = { call_id: "c1", status: "running", tool_name: "read_file" };
    dispatchMsg({ type: "store", event: "tool_state_updated", data });
    expect(dispatch).toHaveBeenCalledWith({ type: "TOOL_STATE_UPDATED", data });
  });

  test("store message_added dispatches MESSAGE_ADDED with subagentId (GAP 1, 5)", () => {
    const data = { uuid: "m1", role: "assistant", content: "Hi" };
    dispatchMsg({ type: "store", event: "message_added", data, subagent_id: "sa-1" });
    expect(dispatch).toHaveBeenCalledWith({ type: "MESSAGE_ADDED", data, subagentId: "sa-1" });
  });

  test("store message_added dispatches without subagentId when not present", () => {
    const data = { uuid: "m1", role: "assistant", content: "Hi" };
    dispatchMsg({ type: "store", event: "message_added", data });
    expect(dispatch).toHaveBeenCalledWith({ type: "MESSAGE_ADDED", data, subagentId: undefined });
  });

  test("store message_updated dispatches MESSAGE_UPDATED with subagentId (GAP 5)", () => {
    const data = { uuid: "m1", role: "assistant", content: "Updated" };
    dispatchMsg({ type: "store", event: "message_updated", data, subagent_id: "sa-1" });
    expect(dispatch).toHaveBeenCalledWith({ type: "MESSAGE_UPDATED", data, subagentId: "sa-1" });
  });

  test("store message_finalized dispatches MESSAGE_FINALIZED", () => {
    dispatchMsg({ type: "store", event: "message_finalized", data: { stream_id: "s1" } as any });
    expect(dispatch).toHaveBeenCalledWith({ type: "MESSAGE_FINALIZED", streamId: "s1" });
  });

  // ── Interactive events ──

  test("interactive clarify_request dispatches CLARIFY_REQUEST", () => {
    dispatchMsg({
      type: "interactive",
      event: "clarify_request",
      data: { uuid: "u1", call_id: "c1", questions: [{ id: "q1" }], context: "ctx" },
    });
    expect(dispatch).toHaveBeenCalledWith({
      type: "CLARIFY_REQUEST",
      callId: "c1",
      questions: [{ id: "q1" }],
      context: "ctx",
    });
  });

  test("interactive plan_submitted dispatches PLAN_APPROVAL", () => {
    dispatchMsg({
      type: "interactive",
      event: "plan_submitted",
      data: { uuid: "u1", call_id: "c1", plan_hash: "h1", excerpt: "Plan text", truncated: false },
    });
    expect(dispatch).toHaveBeenCalledWith({
      type: "PLAN_APPROVAL",
      callId: "c1",
      planHash: "h1",
      excerpt: "Plan text",
      truncated: false,
      planPath: undefined,
      isDirector: false,
    });
  });

  test("interactive director_plan_submitted dispatches PLAN_APPROVAL", () => {
    dispatchMsg({
      type: "interactive",
      event: "director_plan_submitted",
      data: { uuid: "u2", call_id: "c2", plan_hash: "h2", excerpt: "Dir plan", truncated: true, plan_path: "/p" },
    });
    expect(dispatch).toHaveBeenCalledWith({
      type: "PLAN_APPROVAL",
      callId: "c2",
      planHash: "h2",
      excerpt: "Dir plan",
      truncated: true,
      planPath: "/p",
      isDirector: true,
    });
  });

  test("interactive permission_mode_changed dispatches PERMISSION_MODE_CHANGED", () => {
    dispatchMsg({
      type: "interactive",
      event: "permission_mode_changed",
      data: { new_mode: "plan" },
    });
    expect(dispatch).toHaveBeenCalledWith({ type: "PERMISSION_MODE_CHANGED", mode: "plan" });
  });

  // ── Subagent events ──

  test("subagent registered dispatches SUBAGENT_REGISTERED with messages[]", () => {
    dispatchMsg({
      type: "subagent",
      event: "registered",
      data: {
        subagent_id: "sa1",
        parent_tool_call_id: "ptc1",
        model_name: "gpt-4o-mini",
        subagent_name: "researcher",
        transcript_path: "/path",
      },
    });
    expect(dispatch).toHaveBeenCalledWith({
      type: "SUBAGENT_REGISTERED",
      data: expect.objectContaining({
        subagentId: "sa1",
        parentToolCallId: "ptc1",
        modelName: "gpt-4o-mini",
        subagentName: "researcher",
        messages: [],
      }),
    });
  });

  test("subagent unregistered dispatches SUBAGENT_UNREGISTERED", () => {
    dispatchMsg({
      type: "subagent",
      event: "unregistered",
      data: { subagent_id: "sa1" },
    });
    expect(dispatch).toHaveBeenCalledWith({ type: "SUBAGENT_UNREGISTERED", subagentId: "sa1" });
  });

  // ── No-op messages (should not dispatch anything) ──

  test("session_info does not dispatch (handled at App level)", () => {
    dispatchMsg({
      type: "session_info",
      session_id: "s1",
      model_name: "m",
      permission_mode: "p",
      working_directory: "/w",
    });
    expect(dispatch).not.toHaveBeenCalled();
  });

  test("config_loaded dispatches CONFIG_LOADED", () => {
    dispatchMsg({ type: "config_loaded", config: { model: "gpt-4o" }, subagent_names: ["code-reviewer"] });
    expect(dispatch).toHaveBeenCalledWith({
      type: "CONFIG_LOADED",
      config: { model: "gpt-4o" },
      subagentNames: ["code-reviewer"],
    });
  });

  test("context_compacting dispatches CONTEXT_COMPACTING", () => {
    dispatchMsg({ type: "context_compacting", tokens_before: 100000 });
    expect(dispatch).toHaveBeenCalledWith({ type: "CONTEXT_COMPACTING" });
  });

  test("context_compacted dispatches CONTEXT_COMPACTED", () => {
    dispatchMsg({ type: "context_compacted", messages_removed: 10, tokens_before: 100000, tokens_after: 50000 });
    expect(dispatch).toHaveBeenCalledWith({ type: "CONTEXT_COMPACTED" });
  });

  test("file_read does not dispatch", () => {
    dispatchMsg({ type: "file_read", file_path: "/test.py" });
    expect(dispatch).not.toHaveBeenCalled();
  });

  test("execute_in_terminal does not dispatch", () => {
    dispatchMsg({ type: "execute_in_terminal", task_id: "t1", command: "ls" });
    expect(dispatch).not.toHaveBeenCalled();
  });
});

// ============================================================================
// Bug fixes — session-scoped IDs, replay status, MESSAGE_FINALIZED flush
// ============================================================================

describe("appReducer — Session-scoped timeline IDs (Fix 1)", () => {
  test("timeline IDs include session nonce", () => {
    const s = reduce({ type: "ERROR", errorType: "test", message: "err" });
    expect(s.timeline[0].id).toMatch(/^error-\d+-0$/); // nonce 0 on first session
  });

  test("session switch increments nonce, preventing key collision", () => {
    // Session A: add an error entry
    let s = reduce({
      type: "SET_SESSION_INFO",
      sessionId: "sess-A",
      model: "m",
      permissionMode: "p",
    });
    s = reduce({ type: "ERROR", errorType: "test", message: "err-A" }, s);
    const sessionAId = s.timeline[0].id;

    // Switch to session B: counter resets but nonce increments
    s = reduce({
      type: "SET_SESSION_INFO",
      sessionId: "sess-B",
      model: "m",
      permissionMode: "p",
    }, s);
    s = reduce({ type: "ERROR", errorType: "test", message: "err-B" }, s);
    const sessionBId = s.timeline[0].id;

    // IDs must be different even though counter reset to same value
    expect(sessionAId).not.toBe(sessionBId);
    expect(sessionBId).toMatch(/-1$/); // nonce 1
  });

  test("all timeline entry types use session-scoped IDs", () => {
    let s: AppState = { ...initialState, markdownBuffer: "text" };

    // Flush text → assistant_text entry
    s = reduce({ type: "STREAM_END" }, s);
    expect(s.timeline[0].id).toMatch(/^text-\d+-0$/);

    // Code block
    s = reduce({ type: "CODE_BLOCK_START", language: "ts" }, s);
    s = reduce({ type: "CODE_BLOCK_DELTA", content: "x" }, s);
    s = reduce({ type: "CODE_BLOCK_END" }, s);
    const codeEntry = s.timeline.find((e) => e.type === "code");
    expect(codeEntry?.id).toMatch(/^code-\d+-0$/);

    // Thinking
    s = reduce({ type: "THINKING_START" }, s);
    s = reduce({ type: "THINKING_DELTA", content: "hmm" }, s);
    s = reduce({ type: "THINKING_END" }, s);
    const thinkingEntry = s.timeline.find((e) => e.type === "thinking");
    expect(thinkingEntry?.id).toMatch(/^thinking-\d+-0$/);

    // Tool
    s = reduce({
      type: "TOOL_STATE_UPDATED",
      data: { call_id: "c1", status: "running", tool_name: "read_file" },
    }, s);
    const toolEntry = s.timeline.find((e) => e.type === "tool");
    expect(toolEntry?.id).toMatch(/^tool-\d+-0$/);
  });
});

describe("appReducer — Replay tool status (Fix 3)", () => {
  test("replay creates tool cards with pending status initially", () => {
    const s = reduce({
      type: "REPLAY_MESSAGES",
      messages: [
        {
          role: "assistant",
          content: "",
          tool_calls: [{ id: "tc1", function: { name: "read_file", arguments: '{"path":"test.py"}' } }],
        },
      ],
    });
    expect(s.toolCards["tc1"].status).toBe("pending");
  });

  test("replay updates tool status from result meta", () => {
    const s = reduce({
      type: "REPLAY_MESSAGES",
      messages: [
        {
          role: "assistant",
          content: "",
          tool_calls: [{ id: "tc1", function: { name: "read_file", arguments: '{}' } }],
        },
        {
          role: "tool",
          content: "file contents",
          tool_call_id: "tc1",
          meta: { status: "success", duration_ms: 50 },
        },
      ],
    });
    expect(s.toolCards["tc1"].status).toBe("success");
    expect(s.toolCards["tc1"].result).toBe("file contents");
  });

  test("replay marks errored tools correctly", () => {
    const s = reduce({
      type: "REPLAY_MESSAGES",
      messages: [
        {
          role: "assistant",
          content: "",
          tool_calls: [{ id: "tc1", function: { name: "write_file", arguments: '{}' } }],
        },
        {
          role: "tool",
          content: "Permission denied",
          tool_call_id: "tc1",
          meta: { status: "error" },
        },
      ],
    });
    expect(s.toolCards["tc1"].status).toBe("error");
  });
});

describe("appReducer — MESSAGE_FINALIZED flushes buffer (Fix 5)", () => {
  test("MESSAGE_FINALIZED flushes markdown buffer to timeline", () => {
    let s: AppState = {
      ...initialState,
      markdownBuffer: "Trailing text",
      messages: [{ id: "m1", role: "assistant", content: "", streamId: "stream-1", finalized: false }],
    };
    s = reduce({ type: "MESSAGE_FINALIZED", streamId: "stream-1" }, s);

    expect(s.markdownBuffer).toBe("");
    expect(s.timeline).toHaveLength(1);
    expect(s.timeline[0].type).toBe("assistant_text");
    if (s.timeline[0].type === "assistant_text") {
      expect(s.timeline[0].content).toBe("Trailing text");
    }
    expect(s.messages[0].finalized).toBe(true);
  });

  test("MESSAGE_FINALIZED with empty buffer just finalizes", () => {
    let s: AppState = {
      ...initialState,
      messages: [{ id: "m1", role: "assistant", content: "", streamId: "stream-1", finalized: false }],
    };
    s = reduce({ type: "MESSAGE_FINALIZED", streamId: "stream-1" }, s);

    expect(s.timeline).toHaveLength(0);
    expect(s.messages[0].finalized).toBe(true);
  });
});
