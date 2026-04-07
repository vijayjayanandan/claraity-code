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
from pathlib import Path
from typing import Any

from src.core.events import PausePromptEnd, PausePromptStart, StreamEnd, UIEvent
from src.core.protocol import InterruptSignal, UIProtocol, UserAction
from src.observability import get_logger
from src.server.jsonrpc import is_jsonrpc, unwrap, wrap_notification
from src.server.serializers import (
    deserialize_action,
    serialize_event,
    serialize_store_notification,
)
from src.session.persistence.writer import SessionWriter
from src.session.scanner import SESSION_ID_RE as _SESSION_ID_RE, generate_session_id as _generate_session_id
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
    """Build session_history payload from a store's transcript view.

    For multimodal user messages (with images/files), extracts attachment
    metadata so the webview can render chips on replayed sessions.
    """
    messages = store.get_transcript_view(include_pre_compaction=True)
    replay = []
    for msg in messages:
        content = msg.content
        images: list[dict[str, Any]] = []
        attachments: list[dict[str, Any]] = []

        if isinstance(content, list):
            text_parts = []
            for part in content:
                if not isinstance(part, dict):
                    continue
                ptype = part.get("type")
                if ptype == "text":
                    text_parts.append(part.get("text", ""))
                elif ptype == "image_url":
                    image_url = part.get("image_url", {})
                    images.append(
                        {
                            "data": image_url.get("url", ""),
                            "mimeType": part.get("mime", "image/png"),
                            "name": part.get("filename", "image"),
                        }
                    )
            content = " ".join(text_parts)

        # Extract file attachment metadata + content from <attached_file> XML blocks
        if isinstance(content, str):
            for match in re.finditer(
                r'<attached_file\s+path="([^"]*)"\s+name="([^"]*)">\n([\s\S]*?)\n</attached_file>',
                content,
            ):
                attachments.append(
                    {
                        "path": match.group(1),
                        "name": match.group(2),
                        "content": match.group(3),
                    }
                )

        entry: dict[str, Any] = {"role": msg.role, "content": content or ""}
        if images:
            entry["images"] = images
        if attachments:
            entry["attachments"] = attachments
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
        "get_limits": "_handle_get_limits",
        "save_limits": "_handle_save_limits",
        "set_trace_enabled": "_handle_set_trace_enabled",
        "get_trace_enabled": "_handle_get_trace_enabled",
        "new_session": "_handle_new_session",
        "list_sessions": "_handle_list_sessions",
        "resume_session": "_handle_resume_session",
        "delete_session": "_handle_delete_session",
        "get_jira_profiles": "_handle_jira_profiles",
        "save_jira_config": "_handle_jira_save",
        "connect_jira": "_handle_jira_connect_dispatch",
        "disconnect_jira": "_handle_jira_disconnect",
        "webview_error": "_handle_webview_error",
        # MCP
        "get_mcp_servers": "_handle_mcp_servers",
        "mcp_marketplace_search": "_handle_mcp_marketplace_search",
        "mcp_install": "_handle_mcp_install",
        "mcp_uninstall": "_handle_mcp_uninstall",
        "mcp_toggle_server": "_handle_mcp_toggle_server",
        "mcp_save_tools": "_handle_mcp_save_tools",
        "mcp_reconnect": "_handle_mcp_reconnect",
        "mcp_reload": "_handle_mcp_reload",
        # ClarAIty Knowledge & Beads
        "get_beads": "_handle_get_beads",
        "get_architecture": "_handle_get_architecture",
        "approve_knowledge": "_handle_approve_knowledge",
        "export_knowledge": "_handle_export_knowledge",
        "import_knowledge": "_handle_import_knowledge",
        # Subagent management
        "list_subagents": "_handle_list_subagents",
        "save_subagent": "_handle_save_subagent",
        "delete_subagent": "_handle_delete_subagent",
        "reload_subagents": "_handle_reload_subagents",
        # Prompt Enrichment
        "enrich_prompt": "_handle_enrich_prompt",
        # Background tasks
        "cancel_background_task": "_handle_cancel_background_task",
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
        # Save to project-level config if it exists (keeps project overrides
        # self-contained), otherwise fall back to system-level so new folders
        # share settings without creating per-project files.
        from src.llm.config_loader import SYSTEM_CONFIG_PATH
        project_config = os.path.join(working_directory, ".claraity", "config.yaml") if working_directory else ""
        self._save_config_path = project_config if project_config and os.path.isfile(project_config) else SYSTEM_CONFIG_PATH
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

        sessions_dir = Path(self._working_directory) / ".claraity" / "sessions"
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
        limits: dict | None = None,
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
        if limits is not None:
            payload["limits"] = limits
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

    def notify_beads_updated(self) -> None:
        """Push a fresh beads snapshot to the VS Code client.

        Called after task_create/update/block so the beads panel auto-refreshes
        without the user having to click the refresh button.
        May be called from a thread-pool executor.
        """
        coro = self._safe_background_send(self._handle_get_beads({}))
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
        result = await self.wait_for_pause_response()
        # Dismiss the pause widget — main agent does this by yielding
        # PausePromptEnd in stream_response(), but the delegation tool
        # calls request_pause() outside the streaming pipeline.
        await self.send_event(PausePromptEnd(
            continue_work=result.continue_work,
            feedback=result.feedback,
        ))
        return result

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
        if hasattr(self._agent, "_trace"):
            delegation_tool.set_trace(self._agent._trace)
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

        response = save_config_from_request(data, self._save_config_path)

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
            # Persist to config.yaml so settings survive restart
            self._persist_auto_approve(confirmed)
            await self._send_json(
                {
                    "type": "auto_approve_changed",
                    "categories": confirmed,
                }
            )

    def _persist_auto_approve(self, categories: dict[str, bool]) -> None:
        """Save auto-approve categories to config.yaml."""
        try:
            from src.llm.config_loader import load_llm_config, save_llm_config

            cfg = load_llm_config(self._save_config_path)
            cfg.auto_approve.read = categories.get("read", cfg.auto_approve.read)
            cfg.auto_approve.edit = categories.get("edit", cfg.auto_approve.edit)
            cfg.auto_approve.execute = categories.get("execute", cfg.auto_approve.execute)
            cfg.auto_approve.browser = categories.get("browser", cfg.auto_approve.browser)
            save_llm_config(cfg, self._save_config_path)
        except Exception as e:
            logger.warning("auto_approve_persist_error", error=str(e))

    async def _handle_get_auto_approve(self, data: dict) -> None:
        if self._agent:
            await self._send_json(
                {
                    "type": "auto_approve_changed",
                    "categories": self._agent.get_auto_approve_categories(),
                }
            )

    # -----------------------------------------------------------------
    # Limits handlers
    # -----------------------------------------------------------------

    async def _handle_get_limits(self, data: dict) -> None:
        from src.server.config_handler import get_limits_response

        response = get_limits_response(self._config_path)
        # Overlay runtime state from agent if available
        if self._agent:
            response["limits"] = self._agent.get_limits()
        await self._send_json(response)

    async def _handle_save_limits(self, data: dict) -> None:
        from src.server.config_handler import save_limits_from_request

        response = save_limits_from_request(data, self._save_config_path)
        # Apply to running agent immediately (hot-swap)
        if response.get("success") and self._agent and response.get("limits"):
            confirmed = self._agent.set_limits(response["limits"])
            response["limits"] = confirmed
        await self._send_json(response)

    # -----------------------------------------------------------------
    # Trace capture toggle
    # -----------------------------------------------------------------

    async def _handle_get_trace_enabled(self, data: dict) -> None:
        enabled = self._agent._trace.enabled if self._agent else False
        await self._send_json({"type": "trace_enabled", "enabled": enabled})

    async def _handle_set_trace_enabled(self, data: dict) -> None:
        from src.llm.config_loader import save_trace_enabled

        enabled = bool(data.get("enabled", False))
        if self._agent:
            self._agent._trace.set_enabled(enabled)
            # If enabling mid-session and no emitter yet, init now
            if enabled and self._agent._trace._emitter is None and self._agent._session_id:
                sessions_dir = Path(self._working_directory) / ".claraity" / "sessions"
                self._agent._trace.init_session(self._agent._session_id, sessions_dir)
        # Persist to config.yaml
        save_trace_enabled(enabled, self._save_config_path)
        await self._send_json({"type": "trace_enabled", "enabled": enabled})

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
        limits = self._agent.get_limits() if hasattr(self._agent, "get_limits") else None
        await self.send_session_info(
            session_id=session_id,
            model_name=model_name,
            permission_mode=permission_mode,
            working_directory=self._working_directory,
            auto_approve_categories=auto_approve,
            limits=limits,
        )

    async def _handle_new_session(self, data: dict) -> None:
        """Reset agent to a fresh session (New Chat)."""
        from src.session.store.memory_store import MessageStore

        new_session_id = _generate_session_id()

        self._agent.reset_session(new_session_id)
        new_store = MessageStore()
        self._agent.memory.set_message_store(new_store, new_session_id)

        sessions_dir = Path(self._working_directory) / ".claraity" / "sessions"
        await self._switch_session(
            new_session_id, new_store, sessions_dir / new_session_id / "session.jsonl"
        )

        logger.info("stdio_session_reset", session_id=new_session_id)

    async def _handle_list_sessions(self, data: dict) -> None:
        """List available sessions for the history panel."""
        from src.session.scanner import scan_sessions

        sessions_dir = Path(self._working_directory) / ".claraity" / "sessions"
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

        Validates session_id against SESSION_ID_RE to prevent path traversal attacks.
        Checks both directory-based (session_id/session.jsonl) and flat (session_id.jsonl) layouts.
        """
        if not _SESSION_ID_RE.match(session_id):
            logger.warning("stdio_invalid_session_id", session_id=session_id[:50])
            return None

        sessions_dir = Path(self._working_directory) / ".claraity" / "sessions"
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

    async def _handle_delete_session(self, data: dict) -> None:
        """Delete a session by session_id."""
        from src.core.session_manager import SessionManager
        from src.session.scanner import scan_sessions

        session_id = data.get("session_id", "")
        if not session_id:
            await self._send_json({"type": "session_deleted", "session_id": "", "success": False, "message": "session_id is required"})
            return

        # Refuse to delete the currently active session
        if session_id == self._session_id:
            await self._send_json({"type": "session_deleted", "session_id": session_id, "success": False, "message": "Cannot delete the active session"})
            return

        sessions_dir = Path(self._working_directory) / ".claraity" / "sessions"
        try:
            manager = SessionManager(sessions_dir=sessions_dir)
            deleted = manager.delete_session(session_id)
            if not deleted:
                await self._send_json({"type": "session_deleted", "session_id": session_id, "success": False, "message": f"Session not found: {session_id}"})
                return

            await self._send_json({"type": "session_deleted", "session_id": session_id, "success": True})

            # Send refreshed session list so UI updates immediately
            sessions = scan_sessions(sessions_dir, limit=50)
            sessions_data = [
                {
                    "session_id": s.session_id,
                    "first_message": s.display_title,
                    "message_count": s.message_count,
                    "updated_at": s.updated_at.isoformat(),
                    "git_branch": s.git_branch,
                }
                for s in sessions
                if s.session_id != self._session_id
            ]
            await self._send_json({"type": "sessions_list", "sessions": sessions_data})

            logger.info("stdio_session_deleted", session_id=session_id)

        except Exception as e:
            logger.error("stdio_delete_session_error", error=str(e))
            await self._send_json({"type": "session_deleted", "session_id": session_id, "success": False, "message": "Failed to delete session. Check server logs."})

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
    # MCP
    # -----------------------------------------------------------------

    async def _handle_mcp_servers(self, data: dict) -> None:
        """List configured MCP servers with per-tool details."""
        try:
            from src.integrations.mcp.settings import McpSettingsManager

            settings = getattr(self._agent, "_mcp_settings", None)
            if settings is None:
                settings = McpSettingsManager()
                settings.load()

            servers = []
            for name, server in settings.servers.items():
                conn = self._agent._mcp_manager.get_connection(name) if self._agent else None

                # Get ALL tool descriptions from registry (includes disabled tools)
                tool_descriptions = (
                    conn.registry._all_tool_descriptions if conn and conn.registry else {}
                )

                tools = [
                    {
                        "name": tool_name,
                        "enabled": override.enabled,
                        "description": tool_descriptions.get(tool_name, ""),
                    }
                    for tool_name, override in server.tools.items()
                ]
                # Get connection error if not connected
                error = (
                    self._agent._mcp_manager.get_connection_error(name)
                    if self._agent and conn is None
                    else None
                )

                # Generate docs URL from package name or server URL
                docs_url = ""
                if server.args:
                    for arg in server.args:
                        if arg.startswith("@") and "/" in arg:
                            # Scoped npm package: @scope/name -> npmjs.com/package/@scope/name
                            docs_url = f"https://www.npmjs.com/package/{arg}"
                            break
                if not docs_url and server.server_url:
                    docs_url = server.server_url

                servers.append(
                    {
                        "name": name,
                        "transport": server.transport,
                        "enabled": server.enabled,
                        "connected": conn is not None,
                        "toolCount": len([t for t in tools if t["enabled"]]),
                        "tools": tools,
                        "command": server.command,
                        "args": server.args,
                        "serverUrl": server.server_url,
                        "error": error,
                        "docsUrl": docs_url,
                        "scope": settings.get_scope(name),
                    }
                )

            # Include pending notification if any (set by reload handler)
            msg: dict = {"type": "mcp_servers_list", "servers": servers}
            notification = getattr(self, "_pending_mcp_notification", None)
            if notification:
                msg["notification"] = notification
                self._pending_mcp_notification = None
            await self._send_json(msg)
        except Exception as e:
            logger.warning("stdio_mcp_servers_error", error=str(e))
            await self._send_json({"type": "mcp_servers_list", "servers": []})

    async def _handle_mcp_marketplace_search(self, data: dict) -> None:
        """Search the MCP marketplace."""
        try:
            result = await self._agent.mcp_marketplace_search(
                query=data.get("query", ""),
                page=data.get("page", 1),
            )
            await self._send_json({"type": "mcp_marketplace_results", **result})
        except Exception as e:
            logger.warning("stdio_mcp_marketplace_error", error=str(e))
            await self._send_json(
                {
                    "type": "mcp_marketplace_results",
                    "entries": [],
                    "totalCount": 0,
                    "page": 1,
                    "pageSize": 20,
                    "hasNext": False,
                }
            )

    async def _handle_mcp_install(self, data: dict) -> None:
        """Install an MCP server from the marketplace."""
        try:
            result = await self._agent.mcp_marketplace_install(
                server_id=data.get("server_id", ""),
                display_name=data.get("name"),
                env_values=data.get("env_values"),
                scope=data.get("scope", "project"),
            )
            await self._send_json({"type": "mcp_install_result", **result})
            # Refresh server list after install
            await self._handle_mcp_servers({})
        except Exception as e:
            logger.warning("stdio_mcp_install_error", error=str(e))
            await self._send_json(
                {
                    "type": "mcp_install_result",
                    "status": "error",
                    "message": str(e),
                }
            )

    async def _handle_mcp_uninstall(self, data: dict) -> None:
        """Uninstall an MCP server."""
        try:
            result = await self._agent.mcp_marketplace_uninstall(
                server_name=data.get("server_name", ""),
            )
            await self._send_json({"type": "mcp_uninstall_result", **result})
            # Refresh server list after uninstall
            await self._handle_mcp_servers({})
        except Exception as e:
            logger.warning("stdio_mcp_uninstall_error", error=str(e))
            await self._send_json(
                {
                    "type": "mcp_uninstall_result",
                    "status": "error",
                    "message": str(e),
                }
            )

    async def _handle_mcp_toggle_server(self, data: dict) -> None:
        """Toggle an MCP server's enabled state and connect/disconnect."""
        try:
            from src.integrations.mcp.settings import McpSettingsManager

            server_name = data.get("server_name", "")
            enabled = data.get("enabled", True)

            settings = getattr(self._agent, "_mcp_settings", None)
            if settings is None:
                settings = McpSettingsManager()
                settings.load()
                self._agent._mcp_settings = settings

            settings.update_server_enabled(server_name, enabled)
            settings.save()

            if not enabled:
                # Disconnect if currently connected
                if self._agent._mcp_manager.get_connection(server_name):
                    await self._agent._mcp_manager.disconnect(
                        server_name, self._agent.tool_executor
                    )
                    self._agent._invalidate_tools_cache()
            else:
                # Connect if not already connected
                if not self._agent._mcp_manager.get_connection(server_name):
                    server_settings = settings.get_server(server_name)
                    if server_settings:
                        from src.integrations.mcp.client import (
                            McpClient,
                            SseTransport,
                            StdioTransport,
                        )
                        from src.integrations.mcp.policy import McpPolicyGate
                        from src.integrations.mcp.registry import McpToolRegistry

                        runtime_config = server_settings.to_runtime_config()
                        transport = (
                            SseTransport()
                            if server_settings.transport == "sse"
                            else StdioTransport()
                        )
                        client = McpClient(runtime_config, transport)
                        registry = McpToolRegistry(runtime_config, McpPolicyGate())

                        await self._agent._mcp_manager.connect(
                            name=server_name,
                            config=runtime_config,
                            client=client,
                            registry=registry,
                            tool_executor=self._agent.tool_executor,
                            disabled_tools=settings.get_tool_filter(server_name),
                            settings_manager=settings,
                        )
                        self._agent._invalidate_tools_cache()

            # Refresh server list
            await self._handle_mcp_servers({})
        except Exception as e:
            logger.warning("stdio_mcp_toggle_server_error", error=str(e))
            try:
                await self._handle_mcp_servers({})
            except Exception:
                pass

    async def _handle_mcp_save_tools(self, data: dict) -> None:
        """Batch-save tool visibility for a server (single write + reconnect)."""
        try:
            from src.integrations.mcp.settings import McpSettingsManager

            server_name = data.get("server_name", "")
            tool_states = data.get("tools", {})  # { "toolName": true/false }

            settings = getattr(self._agent, "_mcp_settings", None)
            if settings is None:
                settings = McpSettingsManager()
                settings.load()
                self._agent._mcp_settings = settings

            # Apply all toggles at once
            for tool_name, enabled in tool_states.items():
                settings.update_tool_visibility(server_name, tool_name, enabled)

            settings.save()

            # Reconnect to apply changes
            if self._agent._mcp_manager.get_connection(server_name):
                await self._agent._mcp_manager.disconnect(server_name, self._agent.tool_executor)

                server_settings = settings.get_server(server_name)
                if server_settings and server_settings.enabled:
                    from src.integrations.mcp.client import McpClient, SseTransport, StdioTransport
                    from src.integrations.mcp.policy import McpPolicyGate
                    from src.integrations.mcp.registry import McpToolRegistry

                    runtime_config = server_settings.to_runtime_config()
                    transport = (
                        SseTransport() if server_settings.transport == "sse" else StdioTransport()
                    )
                    client = McpClient(runtime_config, transport)
                    registry = McpToolRegistry(runtime_config, McpPolicyGate())

                    await self._agent._mcp_manager.connect(
                        name=server_name,
                        config=runtime_config,
                        client=client,
                        registry=registry,
                        tool_executor=self._agent.tool_executor,
                        disabled_tools=settings.get_tool_filter(server_name),
                        settings_manager=settings,
                    )
                    self._agent._invalidate_tools_cache()

            # Refresh server list
            await self._handle_mcp_servers({})
        except Exception as e:
            logger.warning("stdio_mcp_save_tools_error", error=str(e))
            try:
                await self._handle_mcp_servers({})
            except Exception:
                pass

    async def _handle_mcp_reconnect(self, data: dict) -> None:
        """Disconnect and reconnect an MCP server."""
        server_name = data.get("server_name", "")
        try:
            from src.integrations.mcp.settings import McpSettingsManager

            settings = getattr(self._agent, "_mcp_settings", None)
            if settings is None:
                settings = McpSettingsManager()
                settings.load()
                self._agent._mcp_settings = settings

            # Disconnect if connected
            if self._agent._mcp_manager.get_connection(server_name):
                await self._agent._mcp_manager.disconnect(server_name, self._agent.tool_executor)

            # Clear previous error
            self._agent._mcp_manager._connection_errors.pop(server_name, None)

            # Reconnect
            server_settings = settings.get_server(server_name)
            if server_settings and server_settings.enabled:
                from src.integrations.mcp.client import McpClient, SseTransport, StdioTransport
                from src.integrations.mcp.policy import McpPolicyGate
                from src.integrations.mcp.registry import McpToolRegistry

                runtime_config = server_settings.to_runtime_config()
                transport = (
                    SseTransport() if server_settings.transport == "sse" else StdioTransport()
                )
                client = McpClient(runtime_config, transport)
                registry = McpToolRegistry(runtime_config, McpPolicyGate())

                try:
                    await self._agent._mcp_manager.connect(
                        name=server_name,
                        config=runtime_config,
                        client=client,
                        registry=registry,
                        tool_executor=self._agent.tool_executor,
                        disabled_tools=settings.get_tool_filter(server_name),
                        settings_manager=settings,
                    )
                    self._agent._invalidate_tools_cache()
                except Exception as e:
                    self._agent._mcp_manager._connection_errors[server_name] = str(e)

            # Refresh server list
            await self._handle_mcp_servers({})
        except Exception as e:
            logger.warning("stdio_mcp_reconnect_error", error=str(e))
            try:
                await self._handle_mcp_servers({})
            except Exception:
                pass

    async def _handle_mcp_reload(self, data: dict) -> None:
        """Reload settings from disk and sync connections."""
        try:
            from src.integrations.mcp.settings import McpSettingsManager

            # Reload settings from disk
            settings = McpSettingsManager()
            settings.load()
            self._agent._mcp_settings = settings

            enabled_names = {s.name for s in settings.get_enabled_servers()}
            current_names = set(self._agent._mcp_manager.connection_names)

            # Disconnect servers that were removed or disabled
            for name in current_names - enabled_names:
                try:
                    await self._agent._mcp_manager.disconnect(name, self._agent.tool_executor)
                except Exception:
                    pass

            # Connect new/re-enabled servers
            results = await self._agent._mcp_manager.connect_from_settings(
                settings_manager=settings,
                tool_executor=self._agent.tool_executor,
            )
            self._agent._invalidate_tools_cache()

            total = sum(results.values())

            # Refresh server list with notification (single message, no flicker)
            self._pending_mcp_notification = {
                "message": f"Reloaded ({total} tools from {len(results)} servers)",
                "success": True,
            }
            await self._handle_mcp_servers({})
        except Exception as e:
            logger.warning("stdio_mcp_reload_error", error=str(e))
            await self._send_json(
                {
                    "type": "mcp_servers_list",
                    "servers": [],
                    "notification": {"message": f"Reload failed: {e}", "success": False},
                }
            )

    # -----------------------------------------------------------------
    # ClarAIty Knowledge & Beads handlers
    # -----------------------------------------------------------------

    async def _handle_get_beads(self, data: dict) -> None:
        """Query the beads DB and send grouped task data to the client.

        Groups beads into: in_progress, ready, blocked, deferred, pinned, closed.
        Includes new schema fields: issue_type, assignee, notes, external_ref, etc.
        """
        try:
            from src.claraity.claraity_beads import BeadStore

            db_path = os.path.join(self._working_directory, ".claraity", "claraity_beads.db")
            if not os.path.exists(db_path):
                await self._send_json(
                    {
                        "type": "beads_data",
                        "data": {
                            "ready": [],
                            "in_progress": [],
                            "blocked": [],
                            "deferred": [],
                            "pinned": [],
                            "closed": [],
                            "stats": {
                                "total": 0,
                                "open": 0,
                                "in_progress": 0,
                                "blocked": 0,
                                "deferred": 0,
                                "closed": 0,
                                "dependencies": 0,
                            },
                        },
                    }
                )
                return

            store = BeadStore(db_path)
            try:
                all_beads = store.get_all_beads()
                ready_ids = {b["id"] for b in store.get_ready()}
                stats = store.get_stats()
                all_blockers = store.get_all_blockers()

                # Pre-fetch notes for in-progress beads (avoid N+1)
                ip_ids = {b["id"] for b in all_beads if b["status"] == "in_progress"}
                notes_by_bead = {}
                for bid in ip_ids:
                    notes = store.get_notes(bid)
                    if notes:
                        # Send latest 3 notes
                        notes_by_bead[bid] = [
                            {
                                "content": n["content"],
                                "author": n.get("author", "agent"),
                                "created_at": n.get("created_at", ""),
                            }
                            for n in notes[-3:]
                        ]

                import json as _json

                ready, in_progress, blocked, deferred, pinned, closed = (
                    [], [], [], [], [], [],
                )
                for bead in all_beads:
                    tags = []
                    if bead.get("tags"):
                        try:
                            tags = _json.loads(bead["tags"])
                        except (ValueError, TypeError):
                            pass

                    blockers = all_blockers.get(bead["id"], [])

                    item = {
                        "id": bead["id"],
                        "title": bead["title"],
                        "description": bead.get("description"),
                        "status": bead["status"],
                        "priority": bead.get("priority", 3),
                        "tags": tags,
                        "parent_id": bead.get("parent_id"),
                        "created_at": bead.get("created_at", ""),
                        "closed_at": bead.get("closed_at"),
                        "summary": bead.get("summary"),
                        "blockers": blockers,
                        # New fields
                        "issue_type": bead.get("issue_type", "task"),
                        "assignee": bead.get("assignee"),
                        "notes": notes_by_bead.get(bead["id"], []),
                        "external_ref": bead.get("external_ref"),
                        "due_at": bead.get("due_at"),
                        "defer_until": bead.get("defer_until"),
                        "estimated_minutes": bead.get("estimated_minutes"),
                        "close_reason": bead.get("close_reason"),
                        "last_activity": bead.get("last_activity"),
                        "design": bead.get("design"),
                        "acceptance_criteria": bead.get("acceptance_criteria"),
                    }

                    status = bead["status"]
                    if status == "closed":
                        closed.append(item)
                    elif status == "deferred":
                        deferred.append(item)
                    elif status == "pinned" or bead.get("pinned"):
                        pinned.append(item)
                    elif status == "in_progress":
                        in_progress.append(item)
                    elif bead["id"] in ready_ids:
                        ready.append(item)
                    else:
                        blocked.append(item)

                by_status = stats.get("by_status", {})
                await self._send_json(
                    {
                        "type": "beads_data",
                        "data": {
                            "ready": ready,
                            "in_progress": in_progress,
                            "blocked": blocked,
                            "deferred": deferred,
                            "pinned": pinned,
                            "closed": closed,
                            "stats": {
                                "total": stats.get("total", 0),
                                "open": by_status.get("open", 0),
                                "in_progress": by_status.get("in_progress", 0),
                                "blocked": by_status.get("blocked", 0),
                                "deferred": by_status.get("deferred", 0),
                                "closed": by_status.get("closed", 0),
                                "dependencies": stats.get("dependencies", 0),
                            },
                        },
                    }
                )
            finally:
                store.close()
        except Exception as e:
            logger.warning("stdio_get_beads_error", error=str(e))
            await self._send_error("beads_error", f"Failed to load beads: {e}")

    async def _handle_get_architecture(self, data: dict) -> None:
        """Query the knowledge DB and send architecture graph data to the client."""
        try:
            from src.claraity.claraity_db import ClaraityStore

            db_path = os.path.join(self._working_directory, ".claraity", "claraity_knowledge.db")
            if not os.path.exists(db_path):
                await self._send_json(
                    {
                        "type": "architecture_data",
                        "data": {
                            "nodes": [],
                            "edges": [],
                            "stats": {"node_count": 0, "edge_count": 0, "module_count": 0},
                        },
                    }
                )
                return

            store = ClaraityStore(db_path)
            try:
                raw_nodes = store.get_all_nodes()
                raw_edges = store.get_all_edges()

                nodes = []
                for n in raw_nodes:
                    props = n.get("properties", {})
                    if isinstance(props, str):
                        import json as _json

                        try:
                            props = _json.loads(props)
                        except (ValueError, TypeError):
                            props = {}
                    nodes.append(
                        {
                            "id": n["id"],
                            "type": n.get("type", ""),
                            "layer": n.get("layer", ""),
                            "name": n.get("name", ""),
                            "description": n.get("description"),
                            "file_path": n.get("file_path"),
                            "properties": props,
                        }
                    )

                edges = []
                for e in raw_edges:
                    edges.append(
                        {
                            "id": e.get("id", ""),
                            "from_id": e["from_id"],
                            "to_id": e["to_id"],
                            "type": e.get("type", ""),
                            "label": e.get("label"),
                        }
                    )

                stats_data = store.get_stats()
                module_count = sum(1 for n in nodes if n["type"] == "module")
                metadata = store.get_metadata()
                overview = metadata.get("architecture_overview", "")

                await self._send_json(
                    {
                        "type": "architecture_data",
                        "data": {
                            "nodes": nodes,
                            "edges": edges,
                            "overview": overview,
                            "stats": {
                                "node_count": stats_data.get("nodes", len(nodes)),
                                "edge_count": stats_data.get("edges", len(edges)),
                                "module_count": module_count,
                            },
                            "approval": {
                                "status": metadata.get("knowledge_status", "draft"),
                                "approved_at": metadata.get("knowledge_approved_at"),
                                "approved_by": metadata.get("knowledge_approved_by"),
                                "version": int(metadata.get("knowledge_version", "0")),
                                "comments": metadata.get("knowledge_review_comments"),
                            },
                            "scan": {
                                "scanned_at": metadata.get("scanned_at"),
                                "scanned_by": metadata.get("scanned_by"),
                                "repo_name": metadata.get("repo_name"),
                                "total_files": int(metadata.get("total_files", "0"))
                                if metadata.get("total_files")
                                else None,
                            },
                        },
                    }
                )
            finally:
                store.close()
        except Exception as e:
            logger.warning("stdio_get_architecture_error", error=str(e))
            await self._send_error("architecture_error", f"Failed to load architecture: {e}")

    async def _handle_approve_knowledge(self, data: dict) -> None:
        """Review the knowledge DB - approve or reject with comments."""
        try:
            from src.claraity.claraity_db import ClaraityStore
            from datetime import datetime, timezone

            approved_by = data.get("approved_by", "unknown")
            status = data.get("status", "approved")
            comments = data.get("comments", "")
            db_path = os.path.join(self._working_directory, ".claraity", "claraity_knowledge.db")
            if not os.path.exists(db_path):
                await self._send_error("approve_error", "Knowledge DB not found")
                return

            store = ClaraityStore(db_path)
            try:
                metadata = store.get_metadata()
                version = int(metadata.get("knowledge_version", "0")) + 1
                now = datetime.now(timezone.utc).isoformat()

                store.set_metadata("knowledge_status", status)
                store.set_metadata("knowledge_approved_at", now)
                store.set_metadata("knowledge_approved_by", approved_by)
                store.set_metadata("knowledge_version", str(version))
                store.set_metadata("knowledge_review_comments", comments)

                await self._send_json(
                    {
                        "type": "knowledge_approved",
                        "data": {
                            "status": status,
                            "approved_at": now,
                            "approved_by": approved_by,
                            "version": version,
                        },
                    }
                )
            finally:
                store.close()
        except Exception as e:
            logger.warning("stdio_approve_knowledge_error", error=str(e))
            await self._send_error("approve_error", f"Failed to approve: {e}")

    # -----------------------------------------------------------------
    # Subagent management handlers
    # -----------------------------------------------------------------

    def _reload_subagents_and_refresh_tool(self) -> None:
        """Reload subagent configs on the running agent and refresh the delegation tool.

        Called after any save or delete so the LLM immediately sees the change
        on the next API call without requiring a server restart.
        """
        if not (self._agent and hasattr(self._agent, "subagent_manager")):
            return

        self._agent.subagent_manager.reload_subagents()

        tool_exec = getattr(self._agent, "tool_executor", None)
        if not tool_exec:
            return

        delegation_tool = tool_exec.get_tool("delegate_to_subagent")
        if delegation_tool and hasattr(delegation_tool, "refresh_description"):
            delegation_tool.refresh_description()

    # Static tool names available to subagents (matches runner.py all_tools list)
    _SUBAGENT_STATIC_TOOLS = [
        "read_file",
        "write_file",
        "edit_file",
        "append_to_file",
        "list_directory",
        "grep",
        "glob",
        "run_command",
        "clarify",
    ]

    async def _handle_list_subagents(self, data: dict) -> None:
        """Return all discovered subagents with source metadata and available tools."""
        try:
            from src.subagents.config import SubAgentConfigLoader

            working_dir = Path(self._working_directory) if self._working_directory else Path.cwd()
            loader = SubAgentConfigLoader(working_directory=working_dir)
            configs = loader.discover_all()

            subagents = sorted(
                [
                    {
                        "name": config.name,
                        "description": config.description,
                        "system_prompt": config.system_prompt,
                        "tools": config.tools,
                        "source": config.metadata.get("source", "builtin"),
                        "config_path": str(config.config_path) if config.config_path else None,
                    }
                    for config in configs.values()
                ],
                key=lambda a: (a["source"] != "project", a["name"]),
            )

            await self._send_json({
                "type": "subagents_list",
                "subagents": subagents,
                "available_tools": self._SUBAGENT_STATIC_TOOLS,
            })
        except Exception as e:
            logger.warning("stdio_list_subagents_error", error=str(e))
            await self._send_json({
                "type": "subagents_list",
                "subagents": [],
                "available_tools": self._SUBAGENT_STATIC_TOOLS,
            })

    async def _handle_save_subagent(self, data: dict) -> None:
        """Save or update a custom subagent config to .claraity/agents/<name>.md."""
        import re as _re

        name = str(data.get("name", "")).strip()
        description = str(data.get("description", "")).strip()
        system_prompt = str(data.get("system_prompt", "")).strip()
        tools = data.get("tools")  # list[str] | None

        # Validate name
        if not _re.match(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", name):
            await self._send_json(
                {
                    "type": "subagent_saved",
                    "success": False,
                    "name": name,
                    "message": "Invalid name: use lowercase letters, numbers, and hyphens only.",
                }
            )
            return

        if not description:
            await self._send_json(
                {
                    "type": "subagent_saved",
                    "success": False,
                    "name": name,
                    "message": "Description is required.",
                }
            )
            return

        if not system_prompt:
            await self._send_json(
                {
                    "type": "subagent_saved",
                    "success": False,
                    "name": name,
                    "message": "System prompt is required.",
                }
            )
            return

        try:
            working_dir = Path(self._working_directory) if self._working_directory else Path.cwd()
            agents_dir = working_dir / ".claraity" / "agents"
            agents_dir.mkdir(parents=True, exist_ok=True)

            # Build .md content with properly escaped YAML frontmatter
            import yaml as _yaml
            frontmatter: dict = {"name": name, "description": description}
            if tools:
                frontmatter["tools"] = tools  # written as a proper YAML list
            md_content = f"---\n{_yaml.safe_dump(frontmatter, default_flow_style=False, allow_unicode=True)}---\n\n{system_prompt}\n"

            target = agents_dir / f"{name}.md"
            target.write_text(md_content, encoding="utf-8")

            self._reload_subagents_and_refresh_tool()

            await self._send_json(
                {
                    "type": "subagent_saved",
                    "success": True,
                    "name": name,
                    "message": f"Subagent '{name}' saved.",
                }
            )
        except Exception as e:
            logger.warning("stdio_save_subagent_error", error=str(e))
            await self._send_json(
                {
                    "type": "subagent_saved",
                    "success": False,
                    "name": name,
                    "message": f"Failed to save subagent: {e}",
                }
            )

    async def _handle_delete_subagent(self, data: dict) -> None:
        """Delete a project-level subagent .md file. Built-ins cannot be deleted."""
        import re as _re

        name = str(data.get("name", "")).strip()

        if not name or not _re.match(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", name):
            await self._send_json(
                {
                    "type": "subagent_deleted",
                    "success": False,
                    "name": name,
                    "message": "Invalid subagent name.",
                }
            )
            return

        try:
            working_dir = Path(self._working_directory) if self._working_directory else Path.cwd()
            agents_dir = working_dir / ".claraity" / "agents"
            target = agents_dir / f"{name}.md"

            if not target.exists():
                await self._send_json(
                    {
                        "type": "subagent_deleted",
                        "success": False,
                        "name": name,
                        "message": f"No project-level config found for '{name}'. Built-in subagents cannot be deleted.",
                    }
                )
                return

            # Resolve symlinks and verify the real path stays inside agents_dir
            try:
                resolved = target.resolve()
                if not resolved.is_relative_to(agents_dir.resolve()):
                    raise ValueError("Path escapes agents directory")
            except (OSError, ValueError):
                await self._send_json(
                    {
                        "type": "subagent_deleted",
                        "success": False,
                        "name": name,
                        "message": "Cannot delete: file path is outside the agents directory.",
                    }
                )
                return

            target.unlink()

            self._reload_subagents_and_refresh_tool()

            await self._send_json(
                {
                    "type": "subagent_deleted",
                    "success": True,
                    "name": name,
                    "message": f"Subagent '{name}' deleted.",
                }
            )
        except Exception as e:
            logger.warning("stdio_delete_subagent_error", error=str(e))
            await self._send_json(
                {
                    "type": "subagent_deleted",
                    "success": False,
                    "name": name,
                    "message": f"Failed to delete subagent: {e}",
                }
            )

    async def _handle_reload_subagents(self, data: dict) -> None:
        """Force reload all subagent configs and refresh the delegation tool."""
        try:
            self._reload_subagents_and_refresh_tool()
            await self._handle_list_subagents(data)
        except Exception as e:
            logger.warning("stdio_reload_subagents_error", error=str(e))
            await self._send_json({"type": "subagents_list", "subagents": []})

    async def _handle_export_knowledge(self, data: dict) -> None:
        """Export knowledge DB to JSONL. Accepts optional 'path' for Save As."""
        try:
            from src.claraity.claraity_db import ClaraityStore

            kb_path = os.path.join(
                self._working_directory, ".claraity", "claraity_knowledge.db"
            )
            if not os.path.exists(kb_path):
                await self._send_error("export_error", "No knowledge database to export")
                return

            export_path = data.get("path") or os.path.join(
                self._working_directory, ".claraity", "claraity_knowledge.jsonl"
            )

            store = ClaraityStore(kb_path)
            try:
                count = store.export_jsonl(export_path)
            finally:
                store.close()

            await self._send_json(
                {
                    "type": "export_complete",
                    "data": {"message": f"Exported {count} records to {export_path}"},
                }
            )
        except Exception as e:
            logger.warning("stdio_export_knowledge_error", error=str(e))
            await self._send_error("export_error", f"Failed to export: {e}")

    async def _handle_import_knowledge(self, data: dict) -> None:
        """Import knowledge DB from JSONL content and send back architecture data."""
        import tempfile

        content = data.get("content", "")
        if not content:
            await self._send_error("import_error", "No JSONL content provided")
            return

        try:
            from src.claraity.claraity_db import ClaraityStore

            db_path = os.path.join(
                self._working_directory, ".claraity", "claraity_knowledge.db"
            )

            # Write content to a temp file for import_jsonl
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".jsonl", encoding="utf-8", delete=False
            ) as tmp:
                tmp.write(content)
                tmp_path = tmp.name

            try:
                store = ClaraityStore.import_jsonl(tmp_path, db_path)
                store.close()
            finally:
                os.unlink(tmp_path)

            # Send back refreshed architecture data
            await self._handle_get_architecture({})

        except Exception as e:
            logger.warning("stdio_import_knowledge_error", error=str(e))
            await self._send_error("import_error", f"Failed to import: {e}")

    # -----------------------------------------------------------------
    # Prompt Enrichment
    # -----------------------------------------------------------------

    def _build_enrichment_backend(self, pe, cfg):
        """Return the LLM backend to use for prompt enrichment.

        Falls back to the main agent's backend when no enrichment model is
        configured or it matches the main model.
        """
        if not pe.model or pe.model == self._agent.llm.config.model_name:
            return self._agent.llm

        from src.llm import LLMBackendType, LLMConfig, OpenAIBackend

        llm_config = LLMConfig(
            backend_type=LLMBackendType(cfg.backend_type),
            model_name=pe.model,
            base_url=cfg.base_url,
            temperature=0.2,
            max_tokens=200,
            top_p=0.95,
            context_window=8192,
        )
        if cfg.backend_type == "anthropic":
            from src.llm.anthropic_backend import AnthropicBackend
            return AnthropicBackend(llm_config, api_key=cfg.api_key)

        else:
            return OpenAIBackend(llm_config, api_key=cfg.api_key)

    async def _handle_enrich_prompt(self, data: dict) -> None:
        """Rewrite a short user prompt into a clear, precise instruction using streaming LLM."""
        content = data.get("content", "").strip()
        if not content:
            await self._send_json(
                {"type": "enrichment_error", "message": "Empty prompt"}
            )
            return

        try:
            from src.llm.config_loader import load_llm_config

            cfg = load_llm_config(self._config_path)
            pe = cfg.prompt_enrichment
            backend = self._build_enrichment_backend(pe, cfg)
            from src.prompts.enrichment import ENRICHMENT_SYSTEM_PROMPT
            system_prompt = pe.system_prompt or ENRICHMENT_SYSTEM_PROMPT

            # Build conversation history context from the last few chat turns.
            # Each entry is {"role": "user"|"assistant", "content": str}.
            raw_history = data.get("history") or []
            history_text = ""
            if raw_history and isinstance(raw_history, list):
                lines = []
                for entry in raw_history:
                    if not isinstance(entry, dict):
                        continue
                    role = str(entry.get("role", "")).strip()
                    text = str(entry.get("content", "")).strip()
                    if role in ("user", "assistant") and text:
                        label = "User" if role == "user" else "Assistant"
                        lines.append(f"{label}: {text}")
                if lines:
                    history_text = "Recent conversation:\n" + "\n".join(lines) + "\n\n"

            user_message = f'{history_text}User request: "{content}"'

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ]

            accumulated = []
            async for delta in backend.generate_provider_deltas_async(
                messages, max_tokens=200
            ):
                if delta.text_delta:
                    accumulated.append(delta.text_delta)
                    await self._send_json(
                        {"type": "enrichment_delta", "delta": delta.text_delta}
                    )

            enriched = "".join(accumulated) or content
            await self._send_json(
                {
                    "type": "enrichment_complete",
                    "original": content,
                    "enriched": enriched,
                }
            )
            logger.info(
                "enrich_prompt_success",
                original_len=len(content),
                enriched_len=len(enriched),
            )

        except Exception as e:
            logger.warning("enrich_prompt_error", error=str(e))
            await self._send_json(
                {"type": "enrichment_error", "message": str(e)}
            )

    # -----------------------------------------------------------------
    # Background tasks
    # -----------------------------------------------------------------

    async def _handle_cancel_background_task(self, data: dict) -> None:
        task_id = data.get("task_id", "")
        if not task_id:
            return
        registry = self._agent._bg_registry
        success, message = await registry.cancel(task_id)
        logger.info("stdio_bg_task_cancel", task_id=task_id, success=success, message=message)
        # Send updated task list so the panel refreshes
        await self._send_background_tasks_update()

    async def _send_background_tasks_update(self) -> None:
        """Send current background task list to the client."""
        import time

        MAX_OUTPUT_PREVIEW = 8192  # 8 KB preview for panel display

        registry = self._agent._bg_registry
        tasks = []
        for info in registry.all_tasks():
            elapsed = (info.end_time or time.monotonic()) - info.start_time
            entry: dict = {
                "task_id": info.task_id,
                "command": info.command,
                "description": info.description or info.command[:80],
                "status": info.status.value,
                "elapsed_seconds": round(elapsed, 1),
                "exit_code": info.exit_code,
            }
            # Include output for finished tasks
            if info.status.value != "running":
                stdout = (info.stdout or "").strip()
                stderr = (info.stderr or "").strip()
                if stdout:
                    entry["stdout"] = stdout[:MAX_OUTPUT_PREVIEW]
                if stderr:
                    entry["stderr"] = stderr[:MAX_OUTPUT_PREVIEW]
            tasks.append(entry)
        await self._send_json({"type": "background_tasks_updated", "tasks": tasks})

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
    from src.llm.config_loader import load_trace_enabled
    llm_config = load_llm_config(config_path)
    sys.stderr.write(f"[STDIO] Model: {llm_config.model}\n")
    sys.stderr.flush()

    agent = CodingAgent.from_config(
        llm_config,
        working_directory=working_directory,
        permission_mode=permission_mode,
        api_key=api_key,
    )
    # Apply trace capture setting from config (default: off)
    agent._trace.set_enabled(load_trace_enabled(config_path))
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

    # Register auto-approve change callback so VS Code panel stays in sync
    # when plan approval enables categories (e.g. "edit" on auto-accept edits).
    def _on_auto_approve_changed(categories: dict) -> None:
        asyncio.ensure_future(
            protocol._send_json({"type": "auto_approve_changed", "categories": categories})
        )

    agent._on_auto_approve_changed = _on_auto_approve_changed

    # Register background task completion callback.
    # Completions are debounced over a 1.5s window so tasks that finish in quick
    # succession are batched into a single <task-notification> turn instead of
    # triggering one LLM call per task.
    # remove_from_completed() prevents drain_completed() in the tool loop
    # (agent.py:2761) from re-delivering tasks already queued here.
    MAX_INLINE_OUTPUT = 4096
    BG_DEBOUNCE_SECS = 2.0

    # Pending completions accumulate here until the debounce timer fires.
    _bg_pending: list = []
    _bg_debounce_handle: list = [None]  # mutable container so closure can reassign
    # Idempotency: track task_ids already delivered so double-fire (cancel()+finally) is a no-op.
    _bg_delivered: set = set()

    def _flush_bg_pending() -> None:
        """Build one batched notification from all pending completions and enqueue it."""
        _bg_debounce_handle[0] = None
        tasks = list(_bg_pending)
        _bg_pending.clear()
        if not tasks:
            return

        task_blocks = []
        for completed_task in tasks:
            desc = completed_task.description or completed_task.command[:80]
            exit_info = f" (exit code {completed_task.exit_code})" if completed_task.exit_code is not None else ""
            summary = f'Background command "{desc}" {completed_task.status.value}{exit_info}'

            stdout = (completed_task.stdout or "").strip()
            stderr = (completed_task.stderr or "").strip()
            if len(stdout) > MAX_INLINE_OUTPUT:
                stdout = stdout[:MAX_INLINE_OUTPUT] + "\n... (truncated)"
            if len(stderr) > MAX_INLINE_OUTPUT:
                stderr = stderr[:MAX_INLINE_OUTPUT] + "\n... (truncated)"

            output_section = ""
            if stdout:
                output_section += f"<stdout>\n{stdout}\n</stdout>\n"
            if stderr:
                output_section += f"<stderr>\n{stderr}\n</stderr>\n"

            task_blocks.append(
                "<task>\n"
                f"<task-id>{completed_task.task_id}</task-id>\n"
                f"<status>{completed_task.status.value}</status>\n"
                f"<exit-code>{completed_task.exit_code}</exit-code>\n"
                f"<summary>{summary}</summary>\n"
                f"{output_section}"
                "</task>"
            )

        notification = "<task-notification>\n" + "\n".join(task_blocks) + "\n</task-notification>"

        try:
            protocol._chat_queue.put_nowait({"content": notification})
        except asyncio.QueueFull:
            logger.warning("stdio_bg_notification_dropped_queue_full",
                           task_ids=[t.task_id for t in tasks])

    def _on_bg_task_update(active_count: int, completed_task=None) -> None:
        # Always refresh the panel
        asyncio.ensure_future(
            protocol._safe_background_send(protocol._send_background_tasks_update())
        )

        if completed_task is None:
            return  # Launch event, not a completion

        # Guard: never notify for a task that is still running (defensive against
        # premature callback fires — the finally block in _run_command should prevent
        # this, but this is a second line of defence).
        from src.core.background_tasks import BackgroundTaskStatus
        if completed_task.status == BackgroundTaskStatus.RUNNING:
            logger.warning(
                "stdio_bg_notification_skipped_still_running",
                task_id=completed_task.task_id,
            )
            return

        # Idempotency: drop duplicate deliveries (e.g. cancel() fires callback then
        # _run_command's finally block fires it again for the same task).
        if completed_task.task_id in _bg_delivered:
            return
        _bg_delivered.add(completed_task.task_id)

        # Accumulate and remove from completed queue immediately (not in
        # flush) so drain_completed() in the tool loop can't re-deliver
        # during the debounce window.
        _bg_pending.append(completed_task)
        agent._bg_registry.remove_from_completed(completed_task.task_id)
        if _bg_debounce_handle[0] is not None:
            _bg_debounce_handle[0].cancel()
        try:
            loop = asyncio.get_running_loop()
            _bg_debounce_handle[0] = loop.call_later(BG_DEBOUNCE_SECS, _flush_bg_pending)
        except RuntimeError:
            # No running loop (e.g. during shutdown) -- flush immediately
            _flush_bg_pending()

    agent._bg_registry.set_completion_callback(_on_bg_task_update)

    # Send session_info as first message = ready signal
    model_name = getattr(agent, "model_name", "unknown")
    limits = agent.get_limits() if hasattr(agent, "get_limits") else None
    await protocol.send_session_info(
        session_id=session_id,
        model_name=model_name,
        permission_mode=agent.get_permission_mode(),
        working_directory=working_directory,
        auto_approve_categories=agent.get_auto_approve_categories(),
        limits=limits,
    )
    logger.info("stdio_server_ready", session_id=session_id)

    # Auto-connect MCP servers in background (mirrors TUI's _connect_mcp_servers)
    async def _auto_connect_mcp():
        try:
            mcp_results = await agent.connect_mcp_from_settings()
            if mcp_results:
                total = sum(mcp_results.values())
                servers = ", ".join(f"{k}({v})" for k, v in mcp_results.items())
                logger.info("stdio_mcp_auto_connect_done", servers=servers, total_tools=total)
        except Exception as e:
            logger.error("stdio_mcp_auto_connect_error", error=str(e))

    asyncio.create_task(_auto_connect_mcp())

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
