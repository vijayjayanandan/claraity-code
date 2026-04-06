"""
Trace integration for the ClarAIty agent pipeline.

Thin facade between agent.py / context_builder.py and TraceEmitter.
All formatting, section building, and emit logic lives here so callers
only need one-liner calls.

Actors:
  user, agent, context_builder, llm, gating, tools, store

Instrumentation points:
  From agent.py:
    1.  on_request(user_input)                       -- user -> agent
    2.  on_context_ready(context, iteration)          -- agent -> context_builder (per-iteration summary)
    3.  on_llm_call(context, tools, iteration)        -- context_builder -> llm
    4.  on_llm_response(tc, text, think, iteration)   -- llm -> agent
    5.  on_gate_check(tool_calls, iteration)          -- agent -> gating
    6.  on_tools_dispatch(tool_calls, iteration)       -- gating -> tools
    7.  on_tools_complete(tool_messages, iteration)    -- tools -> agent
    8.  on_persist(session_id)                         -- agent -> store
    9.  on_response_sent()                             -- agent -> user
  From context_builder.py (during build_context):
    10. on_context_source(name, content, found)        -- context_builder internal
    11. on_context_store_fetch(count, roles)            -- context_builder -> store
    12. on_context_store_return(count, tokens)          -- store -> context_builder
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from src.observability import get_logger

logger = get_logger(__name__)


class TraceIntegration:
    """Lightweight wrapper -- all methods are safe no-ops when uninitialised or disabled."""

    def __init__(self, enabled: bool = False) -> None:
        self._emitter: Any | None = None  # TraceEmitter, set by init_session
        self._enabled = enabled  # Must be explicitly enabled (default off)
        self._llm_call_n = 0
        self._context_build_n = 0  # Track builds for first-turn detail vs condensed
        self._tools_t0: float = 0.0
        self._llm_t0: float = 0.0
        self._approval_t0: float = 0.0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def init_session(self, session_id: str, sessions_dir: Path) -> None:
        """Create the underlying TraceEmitter for this session.

        Only creates the emitter if trace capture is enabled.
        """
        if not self._enabled:
            logger.debug("trace_session_init_skipped", reason="trace disabled")
            return
        try:
            from src.observability.trace_emitter import TraceEmitter
            self._emitter = TraceEmitter(session_id, sessions_dir)
            self._llm_call_n = 0
            self._context_build_n = 0
            logger.debug("trace_session_init", session_id=session_id)
        except Exception as exc:
            logger.warning("trace_init_failed", error=str(exc))
            self._emitter = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, value: bool) -> None:
        """Enable or disable trace capture.

        When enabling mid-session, the emitter will be created on the
        next init_session call (i.e., next request).
        When disabling, the emitter is dropped immediately.
        """
        self._enabled = value
        if not value:
            self._emitter = None
        logger.debug("trace_enabled_changed", enabled=value)

    @property
    def _ok(self) -> bool:
        return self._enabled and self._emitter is not None

    @property
    def is_first_build(self) -> bool:
        """True if no build_context has emitted source events yet."""
        return self._context_build_n == 0

    def mark_build_complete(self) -> None:
        """Called by ContextBuilder after emitting source events."""
        self._context_build_n += 1

    # ------------------------------------------------------------------
    # 1. user -> agent
    # ------------------------------------------------------------------

    def on_request(self, user_input: str) -> None:
        if not self._ok:
            return
        try:
            self._emitter.emit(
                "user", "agent",
                "Request received",
                "request",
                data=user_input,
            )
        except Exception as exc:
            logger.warning("trace_on_request_error", error=str(exc))

    # ------------------------------------------------------------------
    # 2a. Context source events (emitted from context_builder.py)
    # ------------------------------------------------------------------

    def on_context_source(
        self,
        source_name: str,
        content: str,
        found: bool,
        iteration: int = 0,
    ) -> None:
        """Per-source event during context assembly.

        Emitted by ContextBuilder for each source as it is loaded.
        from/to are both context_builder (self-referencing -- node pulses).
        """
        if not self._ok:
            return
        try:
            status = "loaded" if found else "not found"
            iter_tag = f" (iter {iteration})" if iteration else ""
            self._emitter.emit(
                "context_builder", "context_builder",
                f"{source_name}: {status}{iter_tag}",
                "context_source",
                data=content if content else f"({source_name} not available)",
                sections={source_name: content} if content else None,
            )
        except Exception as exc:
            logger.warning("trace_on_context_source_error", error=str(exc))

    def on_context_store_fetch(
        self,
        msg_count: int,
        roles: dict[str, int],
        iteration: int = 0,
    ) -> None:
        """Emitted when ContextBuilder fetches conversation from MessageStore."""
        if not self._ok:
            return
        try:
            breakdown = ", ".join(f"{v} {k}" for k, v in roles.items())
            iter_tag = f" (iter {iteration})" if iteration else ""
            self._emitter.emit(
                "context_builder", "store",
                f"Fetch conversation ({msg_count} msgs){iter_tag}",
                "context_source",
                data=(
                    f"Reading from MessageStore (in-memory):\n\n"
                    f"{breakdown}\n\n"
                    f"Total messages: {msg_count}"
                ),
            )
        except Exception as exc:
            logger.warning("trace_on_context_store_fetch_error", error=str(exc))

    def on_context_store_return(
        self,
        msg_count: int,
        token_estimate: int,
        iteration: int = 0,
    ) -> None:
        """Emitted when MessageStore returns conversation history."""
        if not self._ok:
            return
        try:
            iter_tag = f" (iter {iteration})" if iteration else ""
            self._emitter.emit(
                "store", "context_builder",
                f"Returned {msg_count} messages{iter_tag}",
                "context_source",
                data=(
                    f"Conversation history returned from in-memory store.\n\n"
                    f"Messages: {msg_count}\n"
                    f"Estimated tokens: {token_estimate:,}"
                ),
            )
        except Exception as exc:
            logger.warning("trace_on_context_store_return_error", error=str(exc))

    # ------------------------------------------------------------------
    # 2b. agent -> context_builder (per-iteration context summary)
    # ------------------------------------------------------------------

    def on_context_ready(self, context: list[dict], iteration: int = 0) -> None:
        """Lightweight summary before each LLM call.

        On iterations where build_context was NOT called (i.e. agent just
        appended tool results to current_context), this is the only
        context_builder event.
        """
        if not self._ok:
            return
        try:
            n_msgs = len(context)
            roles: dict[str, int] = {}
            for msg in context:
                r = msg.get("role", "?") if isinstance(msg, dict) else getattr(msg, "role", "?")
                roles[r] = roles.get(r, 0) + 1
            breakdown = ", ".join(f"{v} {k}" for k, v in roles.items())
            iter_tag = f" (iter {iteration})" if iteration else ""
            self._emitter.emit(
                "agent", "context_builder",
                f"Context ready ({n_msgs} msgs){iter_tag}",
                "context_assembly",
                data=f"Sending to LLM:\n\n{breakdown}\n\nTotal messages: {n_msgs}",
            )
        except Exception as exc:
            logger.warning("trace_on_context_ready_error", error=str(exc))

    # ------------------------------------------------------------------
    # 2b. context_builder -> llm (assembled context forwarded)
    # ------------------------------------------------------------------

    def on_llm_call(self, context: list[dict], tools: list | None, iteration: int = 0) -> None:
        if not self._ok:
            return
        self._llm_call_n += 1
        self._llm_t0 = time.monotonic()
        try:
            # Extract system prompt from first message
            sys_prompt = ""
            for msg in context:
                role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", "")
                if role == "system":
                    c = msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")
                    sys_prompt = c if isinstance(c, str) else str(c)[:5000]
                    break

            n_tools = len(tools) if tools else 0
            iter_tag = f" (iter {iteration})" if iteration else ""
            self._emitter.emit(
                "context_builder", "llm",
                f"LLM call #{self._llm_call_n}{iter_tag}",
                "llm_call",
                data=f"[System Prompt] + [{n_tools} Tools] + [{len(context)} Messages]",
                sections={
                    "System Prompt": sys_prompt,
                    "Tools": self._emitter.format_tools(tools),
                    "Messages": self._emitter.format_messages(context, max_per_msg=0),
                },
            )
        except Exception as exc:
            logger.warning("trace_on_llm_call_error", error=str(exc))

    # ------------------------------------------------------------------
    # 3. llm -> agent
    # ------------------------------------------------------------------

    def on_llm_response(
        self,
        tool_calls: list | None,
        response_content: str,
        thinking: str | None,
        iteration: int = 0,
    ) -> None:
        if not self._ok:
            return
        try:
            duration_ms = int((time.monotonic() - self._llm_t0) * 1000) if self._llm_t0 else 0

            if tool_calls:
                tc_names = ", ".join(
                    tc.function.name for tc in tool_calls if hasattr(tc, "function")
                )
                label = f"Tool call: {tc_names}"
                response_text = self._emitter.format_tool_calls(tool_calls)
            else:
                label = "Final text response"
                response_text = response_content if response_content else "(empty)"

            sections: dict[str, str] = {}
            if thinking:
                sections["Thinking"] = thinking
            sections["Response"] = response_text

            self._emitter.emit(
                "llm", "agent",
                label,
                "llm_response",
                data=label,
                sections=sections if sections else None,
                thinking=thinking if thinking else None,
                duration_ms=duration_ms,
            )
        except Exception as exc:
            logger.warning("trace_on_llm_response_error", error=str(exc))

    # ------------------------------------------------------------------
    # 4a. agent -> gating (per-tool gate evaluation)
    # ------------------------------------------------------------------

    def on_gate_check(self, tool_name: str, gate_action: str, gate_message: str | None = None, iteration: int = 0) -> None:
        """Emitted per-tool at the point gating.evaluate() returns."""
        if not self._ok:
            return
        try:
            iter_tag = f" (iter {iteration})" if iteration else ""
            detail = f"Tool: {tool_name}\nResult: {gate_action}"
            if gate_message:
                detail += f"\n{gate_message}"
            detail += "\n\nChecks: repeat -> plan_mode -> director -> approval"
            self._emitter.emit(
                "agent", "gating",
                f"Gate: {tool_name} -> {gate_action}{iter_tag}",
                "gate_check",
                data=detail,
            )
        except Exception as exc:
            logger.warning("trace_on_gate_check_error", error=str(exc))

    # ------------------------------------------------------------------
    # 4b. gating -> tools (per-tool dispatch after approval)
    # ------------------------------------------------------------------

    def on_tool_dispatch(self, tool_name: str, tool_args: dict, iteration: int = 0) -> None:
        """Emitted per-tool when a tool is actually dispatched for execution."""
        if not self._ok:
            return
        self._tools_t0 = time.monotonic()
        try:
            args_str = json.dumps(tool_args, ensure_ascii=False)
            if len(args_str) > 400:
                args_str = args_str[:400] + "..."
            iter_tag = f" (iter {iteration})" if iteration else ""
            self._emitter.emit(
                "gating", "tools",
                f"Execute: {tool_name}{iter_tag}",
                "tool_execute",
                data=f"{tool_name}({args_str})",
            )
        except Exception as exc:
            logger.warning("trace_on_tool_dispatch_error", error=str(exc))

    # ------------------------------------------------------------------
    # 5. tools -> agent
    # ------------------------------------------------------------------

    def on_tools_complete(self, tool_messages: list[dict], iteration: int = 0) -> None:
        if not self._ok:
            return
        try:
            duration_ms = int((time.monotonic() - self._tools_t0) * 1000) if self._tools_t0 else 0

            n = len(tool_messages)
            names = [msg.get("name", "?") for msg in tool_messages]
            iter_tag = f" (iter {iteration})" if iteration else ""
            label = (f"Results: {', '.join(names)}{iter_tag}" if n <= 3
                     else f"{n} tool results{iter_tag}")

            self._emitter.emit(
                "tools", "agent",
                label,
                "tool_result",
                data=self._emitter.format_tool_results(tool_messages),
                duration_ms=duration_ms,
            )
        except Exception as exc:
            logger.warning("trace_on_tools_complete_error", error=str(exc))

    # ------------------------------------------------------------------
    # 6. agent -> store (persist)
    # ------------------------------------------------------------------

    def on_persist(self, session_id: str | None) -> None:
        if not self._ok:
            return
        try:
            sid = session_id or "?"
            self._emitter.emit(
                "agent", "store",
                "Session persisted",
                "persist",
                data=f"MessageStore updated (in-memory) + appended to:\n.claraity/sessions/{sid}.jsonl",
            )
        except Exception as exc:
            logger.warning("trace_on_persist_error", error=str(exc))

    # ------------------------------------------------------------------
    # 7. agent -> user (response delivered)
    # ------------------------------------------------------------------

    def on_response_sent(self) -> None:
        if not self._ok:
            return
        try:
            self._emitter.emit(
                "agent", "user",
                "Response delivered",
                "request",
                data="Response sent back to user in VS Code.",
            )
        except Exception as exc:
            logger.warning("trace_on_response_sent_error", error=str(exc))

    # ------------------------------------------------------------------
    # 8. Approval flow (gating <-> user)
    # ------------------------------------------------------------------

    def on_approval_request(
        self,
        tool_name: str,
        tool_args: dict,
        safety_reason: str | None,
        iteration: int = 0,
    ) -> None:
        """Emitted when a tool requires user approval (NEEDS_APPROVAL)."""
        if not self._ok:
            return
        self._approval_t0 = time.monotonic()
        try:
            iter_tag = f" (iter {iteration})" if iteration else ""
            args_str = json.dumps(tool_args, ensure_ascii=False)
            if len(args_str) > 400:
                args_str = args_str[:400] + "..."

            reason = safety_reason or "Category-based approval required"
            self._emitter.emit(
                "gating", "user",
                f"Approval required: {tool_name}{iter_tag}",
                "approval",
                data=(
                    f"Tool: {tool_name}\n"
                    f"Reason: {reason}\n\n"
                    f"Waiting for user decision..."
                ),
                sections={
                    "Tool": tool_name,
                    "Arguments": args_str,
                    "Reason": reason,
                },
            )
        except Exception as exc:
            logger.warning("trace_on_approval_request_error", error=str(exc))

    def on_approval_result(
        self,
        tool_name: str,
        approved: bool,
        feedback: str | None,
        iteration: int = 0,
    ) -> None:
        """Emitted after user approves or rejects a tool call."""
        if not self._ok:
            return
        try:
            wait_ms = int((time.monotonic() - getattr(self, "_approval_t0", 0)) * 1000)
            decision = "APPROVED" if approved else "REJECTED"
            iter_tag = f" (iter {iteration})" if iteration else ""

            data_lines = [
                f"Decision: {decision}",
                f"Wait time: {wait_ms / 1000:.1f}s",
            ]
            if feedback:
                data_lines.append(f"Feedback: {feedback}")
            if approved:
                data_lines.append("\nTool execution will proceed.")
            elif feedback:
                data_lines.append("\nFeedback sent to LLM as tool result (loop continues).")
            else:
                data_lines.append("\nTool rejected. Turn will end.")

            self._emitter.emit(
                "user", "gating",
                f"User {decision.lower()}: {tool_name}{iter_tag}",
                "approval",
                data="\n".join(data_lines),
            )
        except Exception as exc:
            logger.warning("trace_on_approval_result_error", error=str(exc))

    # ------------------------------------------------------------------
    # 9. Store writes (agent -> store)
    # ------------------------------------------------------------------

    def on_store_write(
        self,
        write_type: str,
        detail: str,
        iteration: int = 0,
    ) -> None:
        """Emitted when agent writes to MessageStore + JSONL.

        write_type: "user_message", "assistant_message", "tool_result"
        """
        if not self._ok:
            return
        try:
            iter_tag = f" (iter {iteration})" if iteration else ""
            self._emitter.emit(
                "agent", "store",
                f"Store: {write_type}{iter_tag}",
                "persist",
                data=detail,
            )
        except Exception as exc:
            logger.warning("trace_on_store_write_error", error=str(exc))

    # ------------------------------------------------------------------
    # 10. Subagent lifecycle (agent -> agent bookends)
    # ------------------------------------------------------------------

    def on_subagent_start(
        self,
        subagent_name: str,
        task: str,
        trace_path: str,
        iteration: int = 0,
    ) -> None:
        """Emitted when agent delegates to a subagent.

        The trace_path tells the VS Code panel where to load the
        subagent's own .trace.jsonl for the scene-swap visualization.
        """
        if not self._ok:
            return
        try:
            iter_tag = f" (iter {iteration})" if iteration else ""
            task_preview = task[:200] + "..." if len(task) > 200 else task
            self._emitter.emit(
                "agent", "agent",
                f"SubAgent: {subagent_name}{iter_tag}",
                "subagent_start",
                data=f"Delegating to subagent '{subagent_name}':\n\n{task_preview}",
                sections={
                    "trace_path": trace_path,
                    "subagent_name": subagent_name,
                    "task": task_preview,
                },
            )
        except Exception as exc:
            logger.warning("trace_on_subagent_start_error", error=str(exc))

    def on_subagent_end(
        self,
        subagent_name: str,
        trace_path: str,
        success: bool,
        execution_time: float,
        iteration: int = 0,
    ) -> None:
        """Emitted when a subagent finishes (success or failure)."""
        if not self._ok:
            return
        try:
            status = "[OK] Success" if success else "[FAIL] Failed"
            iter_tag = f" (iter {iteration})" if iteration else ""
            self._emitter.emit(
                "agent", "agent",
                f"SubAgent done: {subagent_name} {status}{iter_tag}",
                "subagent_end",
                data=(
                    f"SubAgent '{subagent_name}' finished.\n\n"
                    f"Status: {status}\n"
                    f"Execution time: {execution_time:.1f}s"
                ),
                sections={
                    "trace_path": trace_path,
                    "subagent_name": subagent_name,
                    "success": str(success),
                },
            )
        except Exception as exc:
            logger.warning("trace_on_subagent_end_error", error=str(exc))
