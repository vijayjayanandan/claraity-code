"""Stdio+TCP transport for the ClarAIty agent.

Commands (client -> agent): read from stdin as JSON lines.
Events (agent -> client): sent over a TCP socket to the extension's data port.

Why TCP instead of stdout pipes?
On Windows, the VS Code Extension Host has a libuv issue where stdout pipe
data events never fire. Data sits in the OS pipe buffer until stdin activity
triggers a read. TCP sockets use a different libuv code path and work reliably.

Usage:
    python -m src.server --stdio --data-port 12345

Wire Protocol:
    All messages are JSON-RPC 2.0 notifications over newline-delimited TCP.
    Client -> Agent (stdin): JSON lines with {"type": "<msg_type>", ...}
    Agent -> Client (TCP):   JSON-RPC wrapped notifications

    Inbound message types:
        chat_message      {"content": str, "images": list}
        get_config        {}
        save_config       {"config": dict}
        list_models       {"backend": str, "base_url": str, "api_key": str}
        set_mode          {"mode": "plan"|"normal"|"auto"}
        set_auto_approve  {"categories": dict}
        get_auto_approve  {}
        new_session       {}
        list_sessions     {}
        resume_session    {"session_id": str}  (UUID format)
        get_jira_profiles {}
        save_jira_config  {"profile": str, "jira_url": str, "username": str, "api_token": str}
        connect_jira      {"profile": str}
        disconnect_jira   {}
        (UserAction types: approval_result, interrupt, retry, pause_result, etc.)

    Outbound message types:
        session_info, error, stream_start, stream_end, text_delta,
        code_block_start, code_block_delta, code_block_end,
        thinking_start, thinking_delta, thinking_end,
        config_loaded, config_saved, models_list,
        interactive (clarify_request, permission_mode_changed, plan_submitted),
        auto_approve_changed, sessions_list, session_history,
        store (tool_state_updated, message_added, message_finalized),
        jira_profiles, jira_config_saved, jira_connect_result, jira_disconnect_result,
        todos_updated, pause_prompt_start, pause_prompt_end
"""

import asyncio
import json
import os
import re
import sys
import threading
import uuid
from pathlib import Path
from typing import Any

from src.core.events import PausePromptStart, StreamEnd, UIEvent
from src.core.protocol import InterruptSignal, UIProtocol, UserAction
from src.observability import get_logger
from src.server.jsonrpc import is_jsonrpc, unwrap, wrap_notification
from src.server.serializers import (
    deserialize_action,
    serialize_event,
    serialize_store_notification,
)
from src.session.persistence.writer import SessionWriter
from src.session.store.memory_store import StoreNotification

logger = get_logger("server.stdio")

# ---------------------------------------------------------------------------
# Tunables -- override via environment variables
# ---------------------------------------------------------------------------

_MAX_CHAT_MESSAGE_LEN = int(os.environ.get("CLARAITY_MAX_MESSAGE_LEN", "100000"))
_MAX_LINE_BYTES = int(os.environ.get("CLARAITY_MAX_LINE_BYTES", str(10 * 1024 * 1024)))  # 10 MB
_MAX_STDIN_QUEUE = int(os.environ.get("CLARAITY_MAX_STDIN_QUEUE", "200"))
_MAX_CHAT_QUEUE = int(os.environ.get("CLARAITY_MAX_CHAT_QUEUE", "10"))
_TCP_CONNECT_TIMEOUT = float(os.environ.get("CLARAITY_TCP_CONNECT_TIMEOUT", "10"))
_TCP_DRAIN_TIMEOUT = float(os.environ.get("CLARAITY_TCP_DRAIN_TIMEOUT", "5"))
_CHAT_POLL_INTERVAL = float(os.environ.get("CLARAITY_CHAT_POLL_INTERVAL", "1"))
_JIRA_CONNECT_TIMEOUT = float(os.environ.get("CLARAITY_JIRA_TIMEOUT", "120"))

# Valid permission modes
_VALID_MODES = frozenset({"plan", "normal", "auto"})

# Session ID validation (prevents path traversal).
# Accepts two formats:
#   UUID:       xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx  (stdio server)
#   Date-based: session-YYYYMMDD-HHMMSS-xxxxxxxx      (TUI)
_SESSION_ID_RE = re.compile(
    r"^(?:"
    r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}"  # UUID
    r"|session-\d{8}-\d{6}-[a-f0-9]{8}"  # TUI date-based
    r")$",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _error_response(
    error_type: str,
    user_message: str,
    recoverable: bool = True,
) -> dict:
    """Build a standardized error response dict for the wire protocol."""
    return {
        "type": "error",
        "error_type": error_type,
        "user_message": user_message,
        "recoverable": recoverable,
    }


def _build_replay_messages(store) -> list[dict[str, Any]]:
    """Build session_history payload from a store's transcript view."""
    messages = store.get_transcript_view(include_pre_compaction=True)
    replay = []
    for msg in messages:
        content = msg.content
        if isinstance(content, list):
            content = " ".join(
                p.get("text", "")
                for p in content
                if isinstance(p, dict) and p.get("type") == "text"
            )
        entry: dict[str, Any] = {"role": msg.role, "content": content or ""}
        if msg.tool_calls:
            entry["tool_calls"] = [
                {
                    "id": tc.id,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]
        if msg.tool_call_id:
            entry["tool_call_id"] = msg.tool_call_id
        if msg.meta:
            meta: dict[str, Any] = {}
            if hasattr(msg.meta, "stop_reason") and msg.meta.stop_reason:
                meta["status"] = msg.meta.stop_reason
            if meta:
                entry["meta"] = meta
        replay.append(entry)
    return replay


# ---------------------------------------------------------------------------
# Stdin reader thread
# ---------------------------------------------------------------------------


def _stdin_reader_thread(
    loop: asyncio.AbstractEventLoop,
    queue: asyncio.Queue,
    max_line_bytes: int,
    shutdown_event: threading.Event | None = None,
):
    """Read lines from stdin in a background thread, push to asyncio queue.

    Lines exceeding *max_line_bytes* are silently dropped to prevent OOM
    from oversized payloads (e.g. a multi-GB base64 image on a single line).

    If *shutdown_event* is set, the thread exits cleanly on the next iteration
    to avoid the "could not acquire lock for stdin at interpreter shutdown"
    fatal error (0xC0000005 on Windows).
    """
    try:
        for line in sys.stdin.buffer:
            if shutdown_event and shutdown_event.is_set():
                break
            stripped = line.strip()
            if not stripped:
                continue
            if len(stripped) > max_line_bytes:
                sys.stderr.write(f"[STDIO] Dropped oversized stdin line ({len(stripped)} bytes)\n")
                sys.stderr.flush()
                continue
            try:
                loop.call_soon_threadsafe(queue.put_nowait, stripped)
            except (asyncio.QueueFull, RuntimeError):
                # RuntimeError: event loop closed — shutting down
                break
    except (EOFError, OSError, ValueError):
        pass
    finally:
        try:
            loop.call_soon_threadsafe(queue.put_nowait, None)
        except RuntimeError:
            pass  # Event loop already closed


# ---------------------------------------------------------------------------
# StdioProtocol
# ---------------------------------------------------------------------------


class StdioProtocol(UIProtocol):
    """UIProtocol that reads commands from stdin and sends events over TCP."""

    # Message type -> handler method name. Handlers accept (self, data).
    _HANDLERS: dict[str, str] = {
        "chat_message": "_handle_chat_message",
        "get_config": "_handle_get_config",
        "save_config": "_handle_save_config",
        "list_models": "_handle_list_models",
        "set_mode": "_handle_set_mode",
        "set_auto_approve": "_handle_set_auto_approve",
        "get_auto_approve": "_handle_get_auto_approve",
        "new_session": "_handle_new_session",
        "list_sessions": "_handle_list_sessions",
        "resume_session": "_handle_resume_session",
        "get_jira_profiles": "_handle_jira_profiles",
        "save_jira_config": "_handle_jira_save",
        "connect_jira": "_handle_jira_connect_dispatch",
        "disconnect_jira": "_handle_jira_disconnect",
        "webview_error": "_handle_webview_error",
    }

    def __init__(
        self,
        message_store,
        agent,
        data_port: int,
        config_path: str = "",
        working_directory: str = "",
    ):
        super().__init__()
        self._store = message_store
        self._agent = agent
        self._config_path = config_path
        self._data_port = data_port
        self._working_directory = working_directory
        self._send_lock = asyncio.Lock()
        self._loop = asyncio.get_running_loop()
        self._unsubscribe = None
        self._chat_queue: asyncio.Queue[dict | None] = asyncio.Queue(maxsize=_MAX_CHAT_QUEUE)
        self._stdin_queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=_MAX_STDIN_QUEUE)
        self._closed = False
        self._tcp_writer: asyncio.StreamWriter | None = None
        # Tracked by run_stdio_server for session management
        self._session_id: str = ""
        self._session_writer: SessionWriter | None = None
        # Streaming task -- cancelled on InterruptSignal for immediate stop
        self._streaming_task: asyncio.Task | None = None

    def set_streaming_task(self, task: asyncio.Task | None) -> None:
        """Register the current streaming task so it can be cancelled on interrupt."""
        self._streaming_task = task

    def submit_action(self, action: UserAction) -> None:
        """Override to cancel the streaming task on InterruptSignal.

        In TUI mode, the Textual worker cancels the asyncio task directly.
        Here we replicate that: setting the flag + cancelling the task gives
        immediate interruption instead of waiting for the next poll checkpoint.
        """
        super().submit_action(action)
        if isinstance(action, InterruptSignal):
            if self._streaming_task and not self._streaming_task.done():
                self._streaming_task.cancel()
                logger.info("stdio_streaming_task_cancelled")

    # -- Session writer lifecycle -------------------------------------------

    async def _open_session_writer(self, session_id: str) -> None:
        """Create, open, and bind a SessionWriter for the given session."""
        if self._session_writer:
            try:
                await self._session_writer.close()
            except Exception as e:
                logger.warning("stdio_session_writer_close_error", error=str(e))
            self._session_writer = None

        sessions_dir = Path(self._working_directory) / ".clarity" / "sessions"
        jsonl_path = sessions_dir / session_id / "session.jsonl"
        writer = SessionWriter(file_path=jsonl_path)
        await writer.open()
        writer.bind_to_store(self._store)
        self._session_writer = writer
        logger.info("stdio_session_writer_opened", session_id=session_id)

    async def _close_session_writer(self) -> None:
        """Close the session writer if open."""
        if self._session_writer:
            try:
                await self._session_writer.close()
                logger.info("stdio_session_writer_closed")
            except Exception as e:
                logger.warning("stdio_session_writer_close_error", error=str(e))
            self._session_writer = None

    # -- TCP data channel ---------------------------------------------------

    async def connect_data_channel(self) -> None:
        """Connect to the extension's TCP data port."""
        logger.debug("stdio_tcp_connecting", data_port=self._data_port)
        sys.stderr.write(f"[STDIO] Connecting to data port {self._data_port}...\n")
        sys.stderr.flush()
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", self._data_port),
            timeout=_TCP_CONNECT_TIMEOUT,
        )
        self._tcp_writer = writer
        logger.debug("stdio_tcp_connected", data_port=self._data_port)
        sys.stderr.write("[STDIO] Data channel connected\n")
        sys.stderr.flush()

    def start_stdin_reader(self):
        """Start the background stdin reader thread."""
        self._stdin_shutdown = threading.Event()
        t = threading.Thread(
            target=_stdin_reader_thread,
            args=(self._loop, self._stdin_queue, _MAX_LINE_BYTES, self._stdin_shutdown),
            daemon=True,
        )
        t.start()

    def stop_stdin_reader(self):
        """Signal the stdin reader thread to exit cleanly."""
        if hasattr(self, "_stdin_shutdown"):
            self._stdin_shutdown.set()

    # -- Sending (Agent -> Client) via TCP ----------------------------------

    async def _send_json(self, data: dict) -> None:
        """Write JSON-RPC 2.0 notification + newline to TCP data channel."""
        if self._closed or self._tcp_writer is None:
            return
        msg_type = data.get("type", "?")
        event = data.get("event", "")
        tag = f"{msg_type}/{event}" if event else msg_type
        logger.debug("stdio_send_json", msg_type=tag)
        try:
            wire_data = wrap_notification(data)
            async with self._send_lock:
                line = json.dumps(wire_data, separators=(",", ":")) + "\n"
                self._tcp_writer.write(line.encode("utf-8"))
                await asyncio.wait_for(self._tcp_writer.drain(), timeout=_TCP_DRAIN_TIMEOUT)
        except (OSError, ValueError, ConnectionError, asyncio.TimeoutError) as e:
            logger.warning("stdio_send_error", msg_type=tag, error=str(e))
            self._closed = True

    async def _send_error(self, error_type: str, message: str, recoverable: bool = True) -> None:
        """Send a standardized error response to the client."""
        await self._send_json(_error_response(error_type, message, recoverable))

    async def send_event(self, event: UIEvent) -> None:
        """Serialize a UIEvent and send to TCP."""
        data = serialize_event(event)
        if data is not None:
            await self._send_json(data)

    async def _send_store_notification(self, notification: StoreNotification) -> None:
        """Serialize a StoreNotification and send to TCP."""
        data = serialize_store_notification(notification)
        if data is not None:
            await self._send_json(data)

    async def send_session_info(
        self,
        session_id: str,
        model_name: str,
        permission_mode: str,
        working_directory: str,
        auto_approve_categories: dict[str, bool] | None = None,
    ) -> None:
        """Send session_info message (also serves as ready signal)."""
        payload = {
            "type": "session_info",
            "session_id": session_id,
            "model_name": model_name,
            "permission_mode": permission_mode,
            "working_directory": working_directory,
        }
        if auto_approve_categories is not None:
            payload["auto_approve_categories"] = auto_approve_categories
        await self._send_json(payload)

    # -- Store subscription -------------------------------------------------

    def subscribe_to_store(self) -> None:
        """Subscribe to MessageStore notifications, forward to TCP.

        Serialization is performed eagerly in the calling thread to avoid
        races where the store mutates the notification object before the
        event loop processes the coroutine.
        """

        def on_notification(notification: StoreNotification) -> None:
            data = serialize_store_notification(notification)
            if data is None:
                return
            self._loop.call_soon_threadsafe(
                asyncio.ensure_future,
                self._safe_background_send(self._send_json(data)),
            )

        self._unsubscribe = self._store.subscribe(on_notification)

    def unsubscribe_from_store(self) -> None:
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None

    async def _safe_background_send(self, coro) -> None:
        try:
            await coro
        except Exception as e:
            logger.warning("stdio_background_send_failed", error=str(e))

    # -- Todo notifications -------------------------------------------------

    def notify_todos_updated(self, todos: list) -> None:
        """Forward todo updates to the client.

        May be called from a thread-pool executor, so we use
        call_soon_threadsafe instead of bare ensure_future.
        """
        coro = self._safe_background_send(
            self._send_json({"type": "todos_updated", "todos": todos})
        )
        self._loop.call_soon_threadsafe(asyncio.ensure_future, coro)

    # -- Interactive overrides (pause, clarify) -----------------------------

    async def request_pause(
        self,
        reason: str,
        reason_code: str,
        stats: dict[str, Any],
        pending_todos: list[dict[str, Any]] | None = None,
    ):
        event = PausePromptStart(
            reason=reason,
            reason_code=reason_code,
            pending_todos=pending_todos or [],
            stats=stats,
        )
        await self.send_event(event)
        return await self.wait_for_pause_response()

    async def send_clarify_request(self, call_id, questions, context):
        await self._send_json(
            {
                "type": "interactive",
                "event": "clarify_request",
                "data": {
                    "call_id": call_id,
                    "questions": questions or [],
                    "context": context,
                },
            }
        )

    # -- Subagent delegation wiring -----------------------------------------

    def wire_delegation_tool(self) -> None:
        """Wire the delegation tool with a ServerSubagentBridge + this protocol.

        Gives the delegation tool two things it needs for subagent visibility:
        1. A bridge (duck-typed registry) that forwards events over TCP
        2. This protocol for interactive requests (approval/clarify/pause)
        """
        if not self._agent:
            return
        delegation_tool = self._agent.tool_executor.tools.get("delegate_to_subagent")
        if not delegation_tool:
            return

        from src.server.subagent_bridge import ServerSubagentBridge

        bridge = ServerSubagentBridge(self)
        delegation_tool.set_registry(bridge)
        delegation_tool.set_ui_protocol(self)
        logger.info("stdio_delegation_tool_wired")

    # -- Receiving (Client -> Agent) via stdin ------------------------------

    async def receive_loop(self) -> None:
        """Read JSON messages from stdin queue and dispatch."""
        while True:
            raw = await self._stdin_queue.get()
            if raw is None:
                logger.info("stdio_stdin_closed")
                break

            try:
                data = json.loads(raw)

                # Unwrap JSON-RPC envelope if present (backward compat)
                if is_jsonrpc(data):
                    data = unwrap(data)

                msg_type = data.get("type")
                handler_name = self._HANDLERS.get(msg_type)

                if handler_name:
                    handler = getattr(self, handler_name)
                    await handler(data)
                else:
                    action = deserialize_action(data)
                    if action is not None:
                        self.submit_action(action)
                    else:
                        logger.warning("stdio_unknown_message_type", msg_type=msg_type)

            except json.JSONDecodeError as e:
                logger.warning("stdio_invalid_json", error=str(e))
            except Exception as e:
                logger.warning("stdio_message_processing_error", error=str(e))

    async def wait_for_chat_message(self) -> dict:
        """Wait for the next chat message from stdin."""
        return await self._chat_queue.get()

    # -----------------------------------------------------------------
    # Webview error handler
    # -----------------------------------------------------------------

    async def _handle_webview_error(self, data: dict) -> None:
        # session_id is passed explicitly from the webview because this handler
        # runs in the receive-loop task, outside the stream_response async context
        # where bind_context() set session_id. Logging it as a named field preserves
        # correlation with the Python-side logs for that session.
        logger.error(
            "webview_error",
            error=data.get("error", ""),
            stack=data.get("stack", ""),
            component_stack=data.get("component_stack", ""),
            session_id=data.get("session_id", ""),
        )

    # -----------------------------------------------------------------
    # Chat message handler
    # -----------------------------------------------------------------

    async def _handle_chat_message(self, data: dict) -> None:
        content = data.get("content", "")
        images = data.get("images", [])
        if len(content) > _MAX_CHAT_MESSAGE_LEN:
            await self._send_error(
                "message_too_large", "Message too large. Maximum 100,000 characters."
            )
            return
        if content.strip() or images:
            await self._chat_queue.put({"content": content, "images": images})

    # -----------------------------------------------------------------
    # Config handlers
    # -----------------------------------------------------------------

    async def _handle_get_config(self, data: dict) -> None:
        from src.server.config_handler import get_config_response

        response = get_config_response(self._config_path)
        await self._send_json(response)

    async def _handle_save_config(self, data: dict) -> None:
        from src.server.config_handler import save_config_from_request

        response = save_config_from_request(data, self._config_path)

        # Hot-swap the LLM backend if agent is available
        cfg = response.pop("_config", None)
        api_key = response.pop("_api_key", None)
        if response.get("success") and cfg and self._agent:
            try:
                # Resolve API key: message > env var > credential store.
                # The VS Code extension stores the key in SecretStorage and
                # strips it from save_config, so it's usually empty here.
                # Fall back to CLARAITY_API_KEY (set at spawn) or keyring.
                resolved_key = api_key or ""
                if not resolved_key:
                    resolved_key = os.environ.get("CLARAITY_API_KEY", "")
                if not resolved_key:
                    from src.llm.credential_store import load_api_key

                    resolved_key = load_api_key()
                summary = self._agent.reconfigure_llm(cfg, api_key=resolved_key)
                response["message"] = f"LLM config applied: {summary}"
            except Exception as exc:
                logger.warning("stdio_llm_reconfigure_failed", error=str(exc))
                response["message"] = (
                    "Config saved but LLM reconfiguration failed. Restart server to apply changes."
                )

        await self._send_json(response)

    async def _handle_list_models(self, data: dict) -> None:
        from src.server.config_handler import list_models_from_request

        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, list_models_from_request, data)
        await self._send_json(response)

    # -----------------------------------------------------------------
    # Mode / auto-approve handlers
    # -----------------------------------------------------------------

    async def _handle_set_mode(self, data: dict) -> None:
        mode = data.get("mode", "")
        if mode not in _VALID_MODES:
            logger.warning("stdio_invalid_mode", mode=mode)
            await self._send_error(
                "invalid_mode",
                f"Invalid mode: {mode}. Valid modes: {', '.join(sorted(_VALID_MODES))}",
            )
            return
        if mode and self._agent:
            try:
                self._agent.set_permission_mode(mode)
                actual = self._agent.get_permission_mode()
                await self._send_json(
                    {
                        "type": "interactive",
                        "event": "permission_mode_changed",
                        "data": {"new_mode": actual},
                    }
                )
            except ValueError:
                await self._send_error("invalid_mode", f"Invalid mode: {mode}")

    async def _handle_set_auto_approve(self, data: dict) -> None:
        categories = data.get("categories", {})
        if self._agent:
            confirmed = self._agent.set_auto_approve_categories(categories)
            await self._send_json(
                {
                    "type": "auto_approve_changed",
                    "categories": confirmed,
                }
            )

    async def _handle_get_auto_approve(self, data: dict) -> None:
        if self._agent:
            await self._send_json(
                {
                    "type": "auto_approve_changed",
                    "categories": self._agent.get_auto_approve_categories(),
                }
            )

    # -----------------------------------------------------------------
    # Session management handlers
    # -----------------------------------------------------------------

    async def _switch_session(self, session_id: str, store, jsonl_path: Path) -> None:
        """Wire a new or resumed session: store, writer, delegation, subscriptions."""
        await self._close_session_writer()

        self.unsubscribe_from_store()
        self._store = store
        self.subscribe_to_store()
        self.wire_delegation_tool()
        self._session_id = session_id

        writer = SessionWriter(file_path=jsonl_path)
        await writer.open()
        writer.bind_to_store(store)
        self._session_writer = writer

        model_name = getattr(self._agent, "model_name", "unknown")
        permission_mode = self._agent.get_permission_mode()
        auto_approve = self._agent.get_auto_approve_categories()
        await self.send_session_info(
            session_id=session_id,
            model_name=model_name,
            permission_mode=permission_mode,
            working_directory=self._working_directory,
            auto_approve_categories=auto_approve,
        )

    async def _handle_new_session(self, data: dict) -> None:
        """Reset agent to a fresh session (New Chat)."""
        from datetime import datetime

        from src.session.store.memory_store import MessageStore

        new_session_id = (
            f"session-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        )

        self._agent.reset_session(new_session_id)
        new_store = MessageStore()
        self._agent.memory.set_message_store(new_store, new_session_id)

        sessions_dir = Path(self._working_directory) / ".clarity" / "sessions"
        await self._switch_session(
            new_session_id, new_store, sessions_dir / new_session_id / "session.jsonl"
        )

        logger.info("stdio_session_reset", session_id=new_session_id)

    async def _handle_list_sessions(self, data: dict) -> None:
        """List available sessions for the history panel."""
        from src.session.scanner import scan_sessions

        sessions_dir = Path(self._working_directory) / ".clarity" / "sessions"
        try:
            sessions = scan_sessions(sessions_dir, limit=50)

            sessions_data = []
            for s in sessions:
                if s.session_id == self._session_id:
                    continue
                sessions_data.append(
                    {
                        "session_id": s.session_id,
                        "first_message": s.display_title,
                        "message_count": s.message_count,
                        "updated_at": s.updated_at.isoformat(),
                        "git_branch": s.git_branch,
                    }
                )

            await self._send_json(
                {
                    "type": "sessions_list",
                    "sessions": sessions_data,
                }
            )
        except Exception as e:
            logger.error("stdio_list_sessions_error", error=str(e))
            await self._send_error(
                "session_list_error", "Failed to list sessions. Check server logs."
            )

    def _find_session_file(self, session_id: str) -> Path | None:
        """Locate the JSONL file for a session (directory or flat structure).

        Validates session_id as a UUID to prevent path traversal attacks.
        """
        if not _SESSION_ID_RE.match(session_id):
            logger.warning("stdio_invalid_session_id", session_id=session_id[:50])
            return None

        sessions_dir = Path(self._working_directory) / ".clarity" / "sessions"
        for candidate in (
            sessions_dir / session_id / "session.jsonl",
            sessions_dir / f"{session_id}.jsonl",
        ):
            try:
                resolved = candidate.resolve()
                if resolved.is_relative_to(sessions_dir.resolve()) and candidate.exists():
                    return candidate
            except (OSError, ValueError):
                continue
        return None

    async def _handle_resume_session(self, data: dict) -> None:
        """Resume a previous session by session_id."""
        session_id = data.get("session_id", "")
        if not session_id:
            return

        jsonl_path = self._find_session_file(session_id)
        if not jsonl_path:
            await self._send_error("session_not_found", f"Session not found: {session_id}")
            return

        try:
            result = self._agent.resume_session_from_jsonl(jsonl_path)
            self._agent.set_session_id(session_id, is_new_session=False)

            await self._switch_session(session_id, result.store, jsonl_path)

            replay = _build_replay_messages(result.store)
            await self._send_json(
                {
                    "type": "session_history",
                    "messages": replay,
                }
            )

            logger.info(
                "stdio_session_resumed",
                session_id=session_id,
                message_count=len(replay),
            )

        except Exception as e:
            logger.error("stdio_resume_session_error", error=str(e))
            await self._send_error(
                "session_resume_error", "Failed to resume session. Check server logs."
            )

    # -----------------------------------------------------------------
    # Jira integration handlers
    # -----------------------------------------------------------------

    async def _handle_jira_profiles(self, data: dict) -> None:
        """List Jira profiles and their connection status."""
        try:
            from src.integrations.jira.connection import JiraConnection

            profiles = JiraConnection.list_profiles()
            profile_data = []
            for name in profiles:
                conn = JiraConnection(profile=name)
                profile_data.append(
                    {
                        "name": name,
                        "jira_url": conn.jira_url or "",
                        "username": conn.username or "",
                        "enabled": conn.enabled,
                        "has_token": conn.has_api_token(),
                        "is_configured": conn.is_configured(),
                    }
                )

            connected_profile = None
            if self._agent:
                mcp_conn = self._agent._mcp_manager.get_connection("jira")
                if mcp_conn:
                    config_name = mcp_conn.config.name
                    if config_name.startswith("mcp-atlassian-"):
                        connected_profile = config_name[len("mcp-atlassian-") :]

            await self._send_json(
                {
                    "type": "jira_profiles",
                    "profiles": profile_data,
                    "connected_profile": connected_profile,
                }
            )
        except Exception as e:
            logger.warning("stdio_jira_profiles_error", error=str(e))
            await self._send_json(
                {
                    "type": "jira_profiles",
                    "profiles": [],
                    "connected_profile": None,
                    "error": "Failed to load Jira profiles. Check server logs.",
                }
            )

    async def _handle_jira_save(self, data: dict) -> None:
        """Save Jira profile configuration."""
        try:
            from src.integrations.jira.connection import JiraConnection

            profile = data.get("profile", "").strip()
            jira_url = data.get("jira_url", "").strip()
            username = data.get("username", "").strip()
            api_token = data.get("api_token", "").strip()

            if not profile:
                await self._send_json(
                    {
                        "type": "jira_config_saved",
                        "success": False,
                        "message": "Profile name is required.",
                    }
                )
                return

            # Validate profile name to prevent path traversal
            if not re.match(r"^[a-zA-Z0-9_-]+$", profile):
                await self._send_json(
                    {
                        "type": "jira_config_saved",
                        "success": False,
                        "message": "Invalid profile name. Use letters, numbers, hyphens, or underscores only.",
                    }
                )
                return

            conn = JiraConnection(profile=profile)

            # If no new token provided, keep existing (update URL/username only)
            if not api_token and conn.has_api_token():
                conn._jira_url = jira_url or conn._jira_url
                conn._username = username or conn._username
                conn._enabled = True
                conn._save_config()
            else:
                conn.configure(
                    jira_url=jira_url,
                    username=username,
                    api_token=api_token,
                )

            await self._send_json(
                {
                    "type": "jira_config_saved",
                    "success": True,
                    "message": f"Profile '{profile}' saved.",
                    "profile": profile,
                }
            )
        except ValueError as e:
            await self._send_json(
                {
                    "type": "jira_config_saved",
                    "success": False,
                    "message": str(e),
                }
            )
        except Exception as e:
            logger.warning("stdio_jira_save_error", error=str(e))
            await self._send_json(
                {
                    "type": "jira_config_saved",
                    "success": False,
                    "message": "Save failed. Check server logs.",
                }
            )

    async def _handle_jira_connect_dispatch(self, data: dict) -> None:
        """Dispatch connect_jira with profile validation."""
        profile = data.get("profile", "")
        if profile:
            await self._handle_jira_connect(profile)
        else:
            await self._send_json(
                {
                    "type": "jira_connect_result",
                    "success": False,
                    "message": "Profile name is required.",
                }
            )

    async def _handle_jira_connect(self, profile: str) -> None:
        """Connect to Jira via MCP server for the given profile."""
        if not self._agent:
            await self._send_json(
                {
                    "type": "jira_connect_result",
                    "success": False,
                    "message": "No agent available.",
                }
            )
            return

        try:
            from src.integrations.jira.connection import JiraConnection
            from src.integrations.jira.tools import create_jira_policy_gate
            from src.integrations.mcp.client import McpClient, StdioTransport
            from src.integrations.mcp.registry import McpToolRegistry

            conn = JiraConnection(profile=profile)
            if not conn.is_configured():
                await self._send_json(
                    {
                        "type": "jira_connect_result",
                        "success": False,
                        "message": f"Profile '{profile}' is not fully configured.",
                    }
                )
                return

            # Disconnect existing connection first
            existing = self._agent._mcp_manager.get_connection("jira")
            if existing:
                await self._agent.disable_mcp_integration("jira")

            config = conn.get_mcp_config()
            transport = StdioTransport()
            client = McpClient(config, transport)
            policy_gate = create_jira_policy_gate()
            registry = McpToolRegistry(config, policy_gate)

            count = await asyncio.wait_for(
                self._agent.enable_mcp_integration("jira", registry, client),
                timeout=_JIRA_CONNECT_TIMEOUT,
            )

            await self._send_json(
                {
                    "type": "jira_connect_result",
                    "success": True,
                    "message": f"Connected to Jira ({profile}): {count} tools available.",
                    "profile": profile,
                    "tool_count": count,
                }
            )
        except (asyncio.TimeoutError, TimeoutError):
            await self._send_json(
                {
                    "type": "jira_connect_result",
                    "success": False,
                    "message": f"Connection timed out ({int(_JIRA_CONNECT_TIMEOUT)}s). Is mcp-atlassian installed?",
                }
            )
        except Exception as e:
            logger.warning("stdio_jira_connect_error", error=str(e))
            await self._send_json(
                {
                    "type": "jira_connect_result",
                    "success": False,
                    "message": "Connection failed. Check server logs.",
                }
            )

    async def _handle_jira_disconnect(self, data: dict) -> None:
        """Disconnect from Jira MCP server."""
        if not self._agent:
            await self._send_json(
                {
                    "type": "jira_disconnect_result",
                    "success": False,
                    "message": "No agent available.",
                }
            )
            return

        try:
            await self._agent.disable_mcp_integration("jira")
            await self._send_json(
                {
                    "type": "jira_disconnect_result",
                    "success": True,
                    "message": "Jira disconnected.",
                }
            )
        except KeyError:
            await self._send_json(
                {
                    "type": "jira_disconnect_result",
                    "success": True,
                    "message": "Jira was not connected.",
                }
            )
        except Exception as e:
            logger.warning("stdio_jira_disconnect_error", error=str(e))
            await self._send_json(
                {
                    "type": "jira_disconnect_result",
                    "success": False,
                    "message": "Disconnect failed. Check server logs.",
                }
            )

    # -----------------------------------------------------------------
    # Streaming
    # -----------------------------------------------------------------

    async def _stream_and_send(self, agent, chat_content: str, attachments=None) -> int:
        """Stream agent response and send each event to the client.

        Checks for TCP disconnect to avoid burning tokens when the client
        is gone.
        """
        count = 0
        async for event in agent.stream_response(
            user_input=chat_content, ui=self, attachments=attachments
        ):
            if self._closed:
                logger.warning("stdio_tcp_disconnected_during_stream")
                self.submit_action(InterruptSignal())
                break
            count += 1
            if count == 1 or count % 10 == 0:
                logger.debug(
                    "stdio_stream_event",
                    event_num=count,
                    event_type=type(event).__name__,
                )
            await self.send_event(event)
        logger.info("stdio_stream_complete", total_events=count)
        return count

    # -----------------------------------------------------------------

    async def shutdown(self) -> None:
        """Close TCP connection."""
        if self._tcp_writer:
            try:
                self._tcp_writer.close()
                await self._tcp_writer.wait_closed()
            except Exception:
                pass
            self._tcp_writer = None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def run_stdio_server(
    working_directory: str,
    config_path: str,
    permission_mode: str = "auto",
    api_key: str | None = None,
    data_port: int = 0,
) -> None:
    """Run the agent over stdio+TCP."""
    from src.core.agent import CodingAgent
    from src.llm.config_loader import load_llm_config

    logger.info("stdio_server_starting", working_directory=working_directory, data_port=data_port)
    sys.stderr.write(f"[STDIO] Working directory: {working_directory}\n")
    sys.stderr.flush()

    # Load config and create agent
    llm_config = load_llm_config(config_path)
    sys.stderr.write(f"[STDIO] Model: {llm_config.model}\n")
    sys.stderr.flush()

    agent = CodingAgent.from_config(
        llm_config,
        working_directory=working_directory,
        permission_mode=permission_mode,
        api_key=api_key,
    )
    session_id = agent.session_id
    message_store = agent.message_store

    # Create protocol and connect data channel
    protocol = StdioProtocol(
        message_store,
        agent,
        data_port,
        config_path,
        working_directory=working_directory,
    )
    protocol._session_id = session_id

    if data_port > 0:
        await protocol.connect_data_channel()
    else:
        sys.stderr.write("[STDIO] WARNING: No --data-port specified, events will not be sent\n")
        sys.stderr.flush()

    protocol.subscribe_to_store()
    protocol.start_stdin_reader()

    # Create and bind SessionWriter for JSONL persistence
    await protocol._open_session_writer(session_id)

    # Set todos callback
    protocol.set_todos_callback(protocol.notify_todos_updated)

    # Wire subagent delegation tool
    protocol.wire_delegation_tool()

    # Send session_info as first message = ready signal
    model_name = getattr(agent, "model_name", "unknown")
    await protocol.send_session_info(
        session_id=session_id,
        model_name=model_name,
        permission_mode=agent.get_permission_mode(),
        working_directory=working_directory,
        auto_approve_categories=agent.get_auto_approve_categories(),
    )
    logger.info("stdio_server_ready", session_id=session_id)

    # Start receive loop in background
    receive_task = asyncio.create_task(protocol.receive_loop())

    try:
        while True:
            try:
                chat_msg = await asyncio.wait_for(
                    protocol.wait_for_chat_message(), timeout=_CHAT_POLL_INTERVAL
                )
            except asyncio.TimeoutError:
                if receive_task.done():
                    break
                # TCP dropped while idle -- shut down gracefully
                if protocol._closed:
                    logger.info("stdio_tcp_closed_shutting_down")
                    break
                continue

            try:
                # Reset protocol state for new turn
                protocol.reset()

                # Extract content and images
                chat_content = (
                    chat_msg.get("content", "") if isinstance(chat_msg, dict) else str(chat_msg)
                )
                raw_images = chat_msg.get("images", []) if isinstance(chat_msg, dict) else []

                # Build attachments
                attachments = None
                if raw_images:
                    import base64 as b64

                    from src.core.attachment import Attachment

                    attachments = []
                    for img in raw_images:
                        data_url = img.get("data_url", "")
                        mime = img.get("mime", "")
                        # Extract MIME from data URL if not provided separately
                        if not mime and data_url.startswith("data:") and ";" in data_url:
                            mime = data_url.split(":", 1)[1].split(";", 1)[0]
                        mime = mime or "image/png"
                        logger.debug(
                            "stdio_image_received",
                            mime=mime,
                            data_url_length=len(data_url),
                        )
                        raw_bytes = b""
                        if ";base64," in data_url:
                            try:
                                payload = data_url.split(";base64,", 1)[1]
                                # Fix padding if missing (common with browser data URLs)
                                missing_padding = len(payload) % 4
                                if missing_padding:
                                    payload += "=" * (4 - missing_padding)
                                raw_bytes = b64.b64decode(payload)
                            except Exception as e:
                                logger.warning("image_decode_failed", error=str(e))
                                sys.stderr.write(
                                    f"[STDIO] Skipping image with invalid base64: {e}\n"
                                )
                                sys.stderr.flush()
                                continue
                        attachments.append(
                            Attachment(
                                kind="image",
                                data=raw_bytes,
                                mime=mime,
                                filename=img.get("filename", "screenshot.png"),
                            )
                        )

                # Stream response -- wrapped in a task so InterruptSignal can cancel it
                # immediately (mirrors TUI's _stream_worker.cancel() behaviour).
                logger.info("stdio_chat_received", content_preview=chat_content[:80])
                logger.debug("stdio_stream_start")

                streaming_task = asyncio.create_task(
                    protocol._stream_and_send(agent, chat_content, attachments)
                )
                protocol.set_streaming_task(streaming_task)
                try:
                    event_count = await streaming_task
                except asyncio.CancelledError:
                    logger.info("stdio_stream_cancelled")
                    # Send stream_end so the extension resets its UI state
                    await protocol.send_event(StreamEnd())
                except Exception as e:
                    logger.error("stdio_stream_error", error=str(e))
                    await protocol._send_error("api_error", "An internal error occurred.")
                finally:
                    protocol.set_streaming_task(None)
            except Exception as turn_err:
                # Catch-all for unexpected errors in turn processing (e.g. bad
                # base64, malformed message). Log and continue — don't kill server.
                logger.error(
                    "stdio_turn_error", error=str(turn_err), error_type=type(turn_err).__name__
                )
                sys.stderr.write(f"[FATAL] {turn_err}\n")
                sys.stderr.flush()
                try:
                    await protocol._send_error(
                        "internal_error", f"Turn processing error: {turn_err}"
                    )
                except Exception:
                    pass

    finally:
        # Signal stdin reader thread to exit before we tear down the event loop.
        # This prevents the "could not acquire lock for stdin at interpreter
        # shutdown" fatal error (0xC0000005 on Windows).
        protocol.stop_stdin_reader()

        receive_task.cancel()
        try:
            await receive_task
        except asyncio.CancelledError:
            pass
        await protocol._close_session_writer()
        protocol.unsubscribe_from_store()
        await protocol.shutdown()
        agent.shutdown()
        logger.info("stdio_server_stopped")
