/**
 * Pre-built message sequences for the test harness.
 *
 * Each scenario returns an array of { msg, delayMs? } items
 * that can be fed to window.__clarityInjectSequence().
 *
 * Usage:
 *   import { bootstrap, basicChat } from './scenarios';
 *   await window.__clarityInjectSequence([...bootstrap(), ...basicChat()]);
 */
import type { ExtensionMessage, ServerMessage } from "../types";

// ── Helpers ──

type Step = { msg: ExtensionMessage; delayMs?: number };

/** Wrap a ServerMessage inside an ExtensionMessage envelope. */
function sm(payload: ServerMessage, delayMs?: number): Step {
  return { msg: { type: "serverMessage", payload }, delayMs };
}

/** Wrap a top-level ExtensionMessage. */
function ext(msg: ExtensionMessage, delayMs?: number): Step {
  return { msg, delayMs };
}

let callCounter = 0;
function nextCallId(): string {
  return `call_${++callCounter}`;
}

// Reset counter between scenario compositions
export function resetCounters(): void {
  callCounter = 0;
}

// ── Scenarios ──

/**
 * Session initialization — connectionStatus + sessionInfo.
 * Most other scenarios assume this has been injected first.
 */
export function bootstrap(): Step[] {
  return [
    ext({ type: "connectionStatus", status: "connected" }),
    ext({
      type: "sessionInfo",
      sessionId: "test-session-001",
      model: "gpt-4o",
      permissionMode: "normal",
    }),
  ];
}

/**
 * Simple text exchange: user sends "Hello", assistant replies.
 * Tests basic streaming lifecycle.
 */
export function basicChat(): Step[] {
  return [
    sm({ type: "stream_start" }),
    sm({ type: "text_delta", content: "Hello! " }, 30),
    sm({ type: "text_delta", content: "I'm ClarAIty, " }, 30),
    sm({ type: "text_delta", content: "your AI coding assistant." }, 30),
    sm({
      type: "stream_end",
      tool_calls: 0,
      elapsed_s: 1.2,
      total_tokens: 150,
      duration_ms: 1200,
    }),
  ];
}

/**
 * Text -> tool -> text ordering.
 * Verifies that assistant text, tool card, and follow-up text appear in correct order.
 */
export function toolExecution(): Step[] {
  const callId = nextCallId();
  return [
    sm({ type: "stream_start" }),
    sm({ type: "text_delta", content: "Let me read that file for you." }, 30),
    // Tool goes through pending -> running -> success
    sm({
      type: "store",
      event: "tool_state_updated",
      data: {
        call_id: callId,
        tool_name: "read_file",
        status: "pending",
        arguments: { file_path: "src/main.py" },
        args_summary: "src/main.py",
      },
    }),
    sm(
      {
        type: "store",
        event: "tool_state_updated",
        data: {
          call_id: callId,
          tool_name: "read_file",
          status: "running",
          arguments: { file_path: "src/main.py" },
          args_summary: "src/main.py",
        },
      },
      50,
    ),
    sm(
      {
        type: "store",
        event: "tool_state_updated",
        data: {
          call_id: callId,
          tool_name: "read_file",
          status: "success",
          arguments: { file_path: "src/main.py" },
          args_summary: "src/main.py",
          result: 'def main():\n    print("hello")',
          duration_ms: 42,
        },
      },
      100,
    ),
    // Follow-up text after tool
    sm(
      { type: "text_delta", content: "The file contains a simple main function." },
      50,
    ),
    sm({
      type: "stream_end",
      tool_calls: 1,
      elapsed_s: 2.5,
      total_tokens: 300,
      duration_ms: 2500,
    }),
  ];
}

/**
 * Multiple tools in sequence.
 * Text -> tool1 -> tool2 -> tool3 -> text.
 */
export function multipleTools(): Step[] {
  const call1 = nextCallId();
  const call2 = nextCallId();
  const call3 = nextCallId();
  return [
    sm({ type: "stream_start" }),
    sm({ type: "text_delta", content: "I'll check three files." }, 30),
    // Tool 1: read_file
    sm({
      type: "store",
      event: "tool_state_updated",
      data: {
        call_id: call1,
        tool_name: "read_file",
        status: "running",
        arguments: { file_path: "package.json" },
        args_summary: "package.json",
      },
    }),
    sm(
      {
        type: "store",
        event: "tool_state_updated",
        data: {
          call_id: call1,
          tool_name: "read_file",
          status: "success",
          arguments: { file_path: "package.json" },
          result: '{"name": "my-app"}',
          duration_ms: 15,
        },
      },
      80,
    ),
    // Tool 2: list_files
    sm({
      type: "store",
      event: "tool_state_updated",
      data: {
        call_id: call2,
        tool_name: "list_files",
        status: "running",
        arguments: { directory: "src/" },
        args_summary: "src/",
      },
    }),
    sm(
      {
        type: "store",
        event: "tool_state_updated",
        data: {
          call_id: call2,
          tool_name: "list_files",
          status: "success",
          arguments: { directory: "src/" },
          result: "main.py\nutils.py\nconfig.py",
          duration_ms: 20,
        },
      },
      80,
    ),
    // Tool 3: run_command
    sm({
      type: "store",
      event: "tool_state_updated",
      data: {
        call_id: call3,
        tool_name: "run_command",
        status: "running",
        arguments: { command: "python --version" },
        args_summary: "python --version",
      },
    }),
    sm(
      {
        type: "store",
        event: "tool_state_updated",
        data: {
          call_id: call3,
          tool_name: "run_command",
          status: "success",
          arguments: { command: "python --version" },
          result: "Python 3.12.0",
          duration_ms: 350,
        },
      },
      100,
    ),
    // Follow-up text
    sm({ type: "text_delta", content: "All three checks passed." }, 50),
    sm({
      type: "stream_end",
      tool_calls: 3,
      elapsed_s: 3.1,
      total_tokens: 500,
      duration_ms: 3100,
    }),
  ];
}

/**
 * Tool awaiting approval.
 * A write_file tool pauses at awaiting_approval status.
 */
export function toolApproval(): Step[] {
  const callId = nextCallId();
  return [
    sm({ type: "stream_start" }),
    sm({ type: "text_delta", content: "I'll create the config file." }, 30),
    sm({
      type: "store",
      event: "tool_state_updated",
      data: {
        call_id: callId,
        tool_name: "write_file",
        status: "pending",
        arguments: {
          file_path: "config.yaml",
          content: "debug: true\nport: 8080",
        },
        args_summary: "config.yaml",
        requires_approval: true,
      },
    }),
    sm(
      {
        type: "store",
        event: "tool_state_updated",
        data: {
          call_id: callId,
          tool_name: "write_file",
          status: "awaiting_approval",
          arguments: {
            file_path: "config.yaml",
            content: "debug: true\nport: 8080",
          },
          args_summary: "config.yaml",
          requires_approval: true,
        },
      },
      50,
    ),
  ];
}

/**
 * Session switch: switch to a different session.
 * Should clear timeline and reinitialize.
 */
export function sessionSwitch(): Step[] {
  return [
    ext({
      type: "sessionInfo",
      sessionId: "test-session-002",
      model: "gpt-4o-mini",
      permissionMode: "strict",
    }),
  ];
}

/**
 * Subagent delegation with nested tools.
 * A delegate_to_subagent tool spawns a subagent that runs its own tools.
 */
export function subagentDelegation(): Step[] {
  const delegateCallId = nextCallId();
  const subagentId = "sa-research-001";
  const childCall1 = nextCallId();
  const childCall2 = nextCallId();

  return [
    sm({ type: "stream_start" }),
    sm({
      type: "text_delta",
      content: "I'll delegate the research to a subagent.",
    }),
    // Delegation tool appears
    sm({
      type: "store",
      event: "tool_state_updated",
      data: {
        call_id: delegateCallId,
        tool_name: "delegate_to_subagent",
        status: "running",
        arguments: { task: "Research API design patterns" },
        args_summary: "Research API design patterns",
      },
    }),
    // Subagent registered
    sm(
      {
        type: "subagent",
        event: "registered",
        data: {
          subagent_id: subagentId,
          parent_tool_call_id: delegateCallId,
          model_name: "gpt-4o-mini",
          subagent_name: "research",
          transcript_path: ".clarity/sessions/subagents/research-sa-001.jsonl",
        },
      },
      50,
    ),
    // Subagent child tool 1
    sm(
      {
        type: "store",
        event: "tool_state_updated",
        subagent_id: subagentId,
        data: {
          call_id: childCall1,
          tool_name: "web_search",
          status: "running",
          arguments: { query: "REST API best practices" },
          args_summary: "REST API best practices",
        },
      },
      100,
    ),
    sm(
      {
        type: "store",
        event: "tool_state_updated",
        subagent_id: subagentId,
        data: {
          call_id: childCall1,
          tool_name: "web_search",
          status: "success",
          arguments: { query: "REST API best practices" },
          result: "Found 10 results",
          duration_ms: 800,
        },
      },
      200,
    ),
    // Subagent child tool 2
    sm({
      type: "store",
      event: "tool_state_updated",
      subagent_id: subagentId,
      data: {
        call_id: childCall2,
        tool_name: "read_file",
        status: "running",
        arguments: { file_path: "docs/api.md" },
        args_summary: "docs/api.md",
      },
    }),
    sm(
      {
        type: "store",
        event: "tool_state_updated",
        subagent_id: subagentId,
        data: {
          call_id: childCall2,
          tool_name: "read_file",
          status: "success",
          arguments: { file_path: "docs/api.md" },
          result: "# API Documentation\n...",
          duration_ms: 25,
        },
      },
      100,
    ),
    // Subagent unregistered
    sm(
      {
        type: "subagent",
        event: "unregistered",
        data: { subagent_id: subagentId },
      },
      50,
    ),
    // Delegation tool completes
    sm({
      type: "store",
      event: "tool_state_updated",
      data: {
        call_id: delegateCallId,
        tool_name: "delegate_to_subagent",
        status: "success",
        arguments: { task: "Research API design patterns" },
        result: "Research complete. Found best practices for RESTful API design.",
        duration_ms: 2100,
      },
    }),
    sm(
      {
        type: "text_delta",
        content: "The research subagent found several useful patterns.",
      },
      50,
    ),
    sm({
      type: "stream_end",
      tool_calls: 3,
      elapsed_s: 4.0,
      total_tokens: 800,
      duration_ms: 4000,
    }),
  ];
}

/**
 * Thinking + code blocks.
 * Tests thinking block rendering and code block rendering.
 */
export function thinkingAndCode(): Step[] {
  return [
    sm({ type: "stream_start" }),
    sm({ type: "thinking_start" }),
    sm({ type: "thinking_delta", content: "Let me analyze " }, 30),
    sm({ type: "thinking_delta", content: "this problem step by step..." }, 30),
    sm({ type: "thinking_end" }),
    sm(
      {
        type: "text_delta",
        content: "Here's a solution:\n\n",
      },
      50,
    ),
    sm({ type: "code_block_start", language: "python" }),
    sm({ type: "code_block_delta", content: "def fibonacci(n):\n" }, 30),
    sm({ type: "code_block_delta", content: '    """Return nth Fibonacci number."""\n' }, 30),
    sm({ type: "code_block_delta", content: "    if n <= 1:\n" }, 30),
    sm({ type: "code_block_delta", content: "        return n\n" }, 30),
    sm({
      type: "code_block_delta",
      content: "    return fibonacci(n - 1) + fibonacci(n - 2)\n",
    }, 30),
    sm({ type: "code_block_end" }),
    sm(
      {
        type: "text_delta",
        content: "This uses simple recursion.",
      },
      50,
    ),
    sm({
      type: "stream_end",
      tool_calls: 0,
      elapsed_s: 1.8,
      total_tokens: 200,
      duration_ms: 1800,
    }),
  ];
}

/**
 * Error recovery.
 * Stream starts, text arrives, then an error occurs.
 */
export function errorRecovery(): Step[] {
  return [
    sm({ type: "stream_start" }),
    sm({ type: "text_delta", content: "Let me try to " }, 30),
    sm(
      {
        type: "error",
        error_type: "api_error",
        user_message: "API rate limit exceeded. Please try again in 30 seconds.",
        recoverable: true,
      },
      100,
    ),
  ];
}

/**
 * Session replay from recorded history.
 * Tests the REPLAY_MESSAGES action with tool_calls and tool results.
 */
export function sessionReplay(): Step[] {
  return [
    ext({
      type: "sessionHistory",
      messages: [
        {
          role: "user",
          content: "Read the README file",
        },
        {
          role: "assistant",
          content: "I'll read that for you.",
          tool_calls: [
            {
              id: "replay_call_1",
              function: {
                name: "read_file",
                arguments: '{"file_path": "README.md"}',
              },
            },
          ],
        },
        {
          role: "tool",
          content: "# My Project\nA sample project.",
          tool_call_id: "replay_call_1",
          meta: {
            status: "success",
            duration_ms: 30,
            tool_name: "read_file",
          },
        },
        {
          role: "assistant",
          content: "The README describes a sample project.",
        },
      ],
    }),
  ];
}
