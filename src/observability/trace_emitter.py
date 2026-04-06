"""
Trace emitter for the ClarAIty agent pipeline.

Writes structured trace events to a per-session .trace.jsonl file for
playback in the VS Code TracePanel animation.  Each event represents a
node-to-node data flow (user -> agent -> llm -> tools -> jsonl).

Usage in agent.py::

    self.trace = TraceEmitter(session_id, sessions_dir)
    self.trace.emit("user", "agent", "Request received", "request",
                    data=user_input)
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path
from typing import Any

from src.observability import get_logger

logger = get_logger(__name__)


class TraceEmitter:
    """Append-only trace writer.  One instance per session."""

    def __init__(self, session_id: str, sessions_dir: Path) -> None:
        self._session_id = session_id
        self._trace_path = sessions_dir / f"{session_id}.trace.jsonl"
        self._step_counter = 0
        self._llm_call_counter = 0
        self._write_lock = threading.Lock()
        # Ensure parent dir exists once
        self._trace_path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def next_llm_call_number(self) -> int:
        """Increment and return the LLM call counter (1-based)."""
        self._llm_call_counter += 1
        return self._llm_call_counter

    def emit(
        self,
        from_node: str,
        to_node: str,
        label: str,
        step_type: str,
        data: str,
        *,
        sections: dict[str, str] | None = None,
        thinking: str | None = None,
        duration_ms: int = 0,
    ) -> None:
        """Emit a trace event (fire-and-forget async write)."""
        self._step_counter += 1
        event: dict[str, Any] = {
            "id": self._step_counter,
            "from": from_node,
            "to": to_node,
            "label": label,
            "type": step_type,
            "data": data,
            "durationMs": max(duration_ms, 800),  # min 800ms for animation
            "timestamp": time.time(),
        }
        if sections:
            event["sections"] = sections
        if thinking:
            event["thinking"] = thinking

        # Fire-and-forget: try async first, fall back to sync
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._write_async(event))
        except RuntimeError:
            self._write_sync(event)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _write_async(self, event: dict[str, Any]) -> None:
        try:
            line = json.dumps(event, ensure_ascii=False) + "\n"
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._append, line)
        except Exception as exc:
            logger.warning("trace_write_error", error=str(exc))

    def _write_sync(self, event: dict[str, Any]) -> None:
        try:
            self._append(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.warning("trace_write_sync_error", error=str(exc))

    def _append(self, line: str) -> None:
        with self._write_lock:
            with open(self._trace_path, "a", encoding="utf-8") as fh:
                fh.write(line)

    # ------------------------------------------------------------------
    # Formatting helpers (call from agent.py)
    # ------------------------------------------------------------------

    @staticmethod
    def format_messages(messages: list[dict[str, Any]], max_per_msg: int = 1500) -> str:
        """Render a message list into a human-readable string for the trace."""
        parts: list[str] = []
        for msg in messages:
            role = msg.get("role", "?")
            content = msg.get("content", "")
            # Handle content-block lists (Anthropic format)
            if isinstance(content, list):
                text_parts = []
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        elif block.get("type") == "tool_use":
                            text_parts.append(f'<tool_call: {block.get("name", "?")}(...)>')
                        elif block.get("type") == "tool_result":
                            text_parts.append(f'<tool_result: {str(block.get("content", ""))[:200]}>')
                content = "\n".join(text_parts) if text_parts else str(content)
            else:
                content = str(content) if content else ""

            # Handle tool_calls in assistant messages (may be dicts or Pydantic objects)
            tool_calls = msg.get("tool_calls") if isinstance(msg, dict) else getattr(msg, "tool_calls", None)
            if tool_calls:
                tc_strs = []
                for tc in tool_calls:
                    if isinstance(tc, dict):
                        func = tc.get("function", tc)
                        name = func.get("name", "?") if isinstance(func, dict) else getattr(func, "name", "?")
                        args = str(func.get("arguments", "") if isinstance(func, dict) else getattr(func, "arguments", ""))
                    else:
                        func = getattr(tc, "function", tc)
                        name = getattr(func, "name", "?")
                        args = str(getattr(func, "arguments", ""))
                    tc_strs.append(f"<tool_call: {name}({args[:200]})>")
                content = (content + "\n" + "\n".join(tc_strs)).strip()

            if max_per_msg and len(content) > max_per_msg:
                content = content[:max_per_msg] + "..."
            parts.append(f"[{role}]\n{content}")
        return "\n\n".join(parts)

    @staticmethod
    def format_tools(tools: list | None) -> str:
        """Render tool schemas to a compact string.  Handles both dicts and Pydantic objects."""
        if not tools:
            return "(no tools)"
        lines: list[str] = []
        for t in tools:
            if isinstance(t, dict):
                func = t.get("function", t)
                name = func.get("name", "?") if isinstance(func, dict) else getattr(func, "name", "?")
                desc = func.get("description", "") if isinstance(func, dict) else getattr(func, "description", "")
            else:
                # Pydantic ToolDefinition: t.function.name / t.function.description
                func = getattr(t, "function", t)
                name = getattr(func, "name", "?")
                desc = getattr(func, "description", "") or ""
            lines.append(f"{name}\n  {desc}")
        return "\n\n".join(lines)

    @staticmethod
    def format_tool_calls(tool_calls: list) -> str:
        """Render tool calls into a readable string."""
        parts: list[str] = []
        for tc in tool_calls:
            name = tc.function.name if hasattr(tc, "function") else "?"
            try:
                args = tc.function.get_parsed_arguments()
                args_str = json.dumps(args, indent=2, ensure_ascii=False)
            except Exception:
                args_str = getattr(tc.function, "arguments", "{}")
            parts.append(f'{{"tool": "{name}",\n "parameters": {args_str}}}')
        return "\n\n".join(parts)

    @staticmethod
    def format_tool_results(tool_messages: list[dict[str, Any]]) -> str:
        """Render tool result messages."""
        parts: list[str] = []
        for msg in tool_messages:
            name = msg.get("name", "?")
            content = str(msg.get("content", ""))
            parts.append(f"[{name}]\n{content}")
        return "\n\n".join(parts)
