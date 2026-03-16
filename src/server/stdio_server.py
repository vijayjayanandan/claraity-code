"""Stdio+TCP transport for the ClarAIty agent.

Commands (client -> agent): read from stdin as JSON lines.
Events (agent -> client): sent over a TCP socket to the extension's data port.

Why TCP instead of stdout pipes?
On Windows, the VS Code Extension Host has a libuv issue where stdout pipe
data events never fire. Data sits in the OS pipe buffer until stdin activity
triggers a read. TCP sockets use a different libuv code path and work reliably.

Usage:
    python -m src.server --stdio --data-port 12345
"""

import asyncio
import json
import os
import sys
import threading
import uuid
from typing import Any

from src.core.events import PausePromptStart, UIEvent
from src.core.protocol import UIProtocol
from src.observability import get_logger
from src.server.serializers import (
    deserialize_action,
    serialize_event,
    serialize_store_notification,
)
from src.session.store.memory_store import StoreNotification

logger = get_logger("server.stdio")

# Maximum chat message size (characters) — matches WebSocket behaviour
_MAX_CHAT_MESSAGE_LEN = 100_000

# Valid permission modes
_VALID_MODES = frozenset({"plan", "normal", "auto"})


# ---------------------------------------------------------------------------
# Stdin reader thread
# ---------------------------------------------------------------------------


def _stdin_reader_thread(loop: asyncio.AbstractEventLoop, queue: asyncio.Queue):
    """Read lines from stdin in a background thread, push to asyncio queue."""
    try:
        for line in sys.stdin.buffer:
            stripped = line.strip()
            if stripped:
                loop.call_soon_threadsafe(queue.put_nowait, stripped)
    except (EOFError, OSError, ValueError):
        pass
    finally:
        loop.call_soon_threadsafe(queue.put_nowait, None)


# ---------------------------------------------------------------------------
# StdioProtocol
# ---------------------------------------------------------------------------


class StdioProtocol(UIProtocol):
    """UIProtocol that reads commands from stdin and sends events over TCP."""

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
        self._loop = asyncio.get_event_loop()
        self._unsubscribe = None
        self._chat_queue: asyncio.Queue[dict | None] = asyncio.Queue()
        self._stdin_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._closed = False
        self._tcp_writer: asyncio.StreamWriter | None = None
        # Tracked by run_stdio_server for session management
        self._session_id: str = ""

    async def connect_data_channel(self) -> None:
        """Connect to the extension's TCP data port."""
        logger.debug("stdio_tcp_connecting", data_port=self._data_port)
        sys.stderr.write(f"[STDIO] Connecting to data port {self._data_port}...\n")
        sys.stderr.flush()
        _reader, writer = await asyncio.open_connection("127.0.0.1", self._data_port)
        self._tcp_writer = writer
        logger.debug("stdio_tcp_connected", data_port=self._data_port)
        sys.stderr.write("[STDIO] Data channel connected\n")
        sys.stderr.flush()

    def start_stdin_reader(self):
        """Start the background stdin reader thread."""
        t = threading.Thread(
            target=_stdin_reader_thread,
            args=(self._loop, self._stdin_queue),
            daemon=True,
        )
        t.start()

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
            from src.server.jsonrpc import wrap_notification

            wire_data = wrap_notification(data)
            async with self._send_lock:
                line = json.dumps(wire_data, separators=(",", ":")) + "\n"
                self._tcp_writer.write(line.encode("utf-8"))
                await self._tcp_writer.drain()
        except (OSError, ValueError, ConnectionError) as e:
            logger.warning("stdio_send_error", msg_type=tag, error=str(e))
            self._closed = True

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
        auto_approve_categories=None,
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
        """Subscribe to MessageStore notifications, forward to TCP."""

        def on_notification(notification: StoreNotification) -> None:
            self._loop.call_soon_threadsafe(
                asyncio.ensure_future,
                self._safe_background_send(self._send_store_notification(notification)),
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
        asyncio.ensure_future(
            self._safe_background_send(self._send_json({"type": "todos_updated", "todos": todos}))
        )

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

    async def receive_loop(self) -> None:  # noqa: C901
        """Read JSON messages from stdin queue and dispatch."""
        while True:
            raw = await self._stdin_queue.get()
            if raw is None:
                logger.info("stdio_stdin_closed")
                break

            try:
                data = json.loads(raw)

                # Unwrap JSON-RPC envelope if present (backward compat)
                from src.server.jsonrpc import is_jsonrpc, unwrap

                if is_jsonrpc(data):
                    data = unwrap(data)

                msg_type = data.get("type")

                # -- Chat messages -----------------------------------------
                if msg_type == "chat_message":
                    content = data.get("content", "")
                    images = data.get("images", [])
                    if len(content) > _MAX_CHAT_MESSAGE_LEN:
                        await self._send_json(
                            {
                                "type": "error",
                                "error_type": "message_too_large",
                                "user_message": "Message too large. Maximum 100,000 characters.",
                                "recoverable": True,
                            }
                        )
                        continue
                    if content.strip() or images:
                        await self._chat_queue.put({"content": content, "images": images})

                # -- Config handlers ---------------------------------------
                elif msg_type == "get_config":
                    await self._handle_get_config()

                elif msg_type == "save_config":
                    await self._handle_save_config(data)

                elif msg_type == "list_models":
                    await self._handle_list_models(data)

                # -- Mode / auto-approve -----------------------------------
                elif msg_type == "set_mode":
                    await self._handle_set_mode(data)

                elif msg_type == "set_auto_approve":
                    await self._handle_set_auto_approve(data)

                elif msg_type == "get_auto_approve":
                    await self._handle_get_auto_approve()

                # -- Session management ------------------------------------
                elif msg_type == "new_session":
                    await self._handle_new_session()

                elif msg_type == "list_sessions":
                    await self._handle_list_sessions()

                elif msg_type == "resume_session":
                    session_id = data.get("session_id", "")
                    if session_id:
                        await self._handle_resume_session(session_id)

                # -- Jira integration --------------------------------------
                elif msg_type == "get_jira_profiles":
                    await self._handle_jira_profiles()

                elif msg_type == "save_jira_config":
                    await self._handle_jira_save(data)

                elif msg_type == "connect_jira":
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

                elif msg_type == "disconnect_jira":
                    await self._handle_jira_disconnect()

                # -- UserActions (approve, reject, continue, etc.) ---------
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
    # Config handlers
    # -----------------------------------------------------------------

    async def _handle_get_config(self) -> None:
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
                    f"Config saved but apply failed: {exc}. Restart server to apply changes."
                )

        await self._send_json(response)

    async def _handle_list_models(self, data: dict) -> None:
        from src.server.config_handler import list_models_from_request

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, list_models_from_request, data)
        await self._send_json(response)

    # -----------------------------------------------------------------
    # Mode / auto-approve handlers
    # -----------------------------------------------------------------

    async def _handle_set_mode(self, data: dict) -> None:
        mode = data.get("mode", "")
        if mode not in _VALID_MODES:
            logger.warning("stdio_invalid_mode", mode=mode)
            await self._send_json(
                {
                    "type": "error",
                    "error_type": "invalid_mode",
                    "user_message": f"Invalid mode: {mode}. Valid modes: {', '.join(sorted(_VALID_MODES))}",
                    "recoverable": True,
                }
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
                await self._send_json(
                    {
                        "type": "error",
                        "error_type": "invalid_mode",
                        "user_message": f"Invalid mode: {mode}",
                        "recoverable": True,
                    }
                )

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

    async def _handle_get_auto_approve(self) -> None:
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

    async def _handle_new_session(self) -> None:
        """Reset agent to a fresh session (New Chat)."""
        from src.session.store.memory_store import MessageStore

        new_session_id = str(uuid.uuid4())

        # 1. Reset core agent state
        self._agent.reset_session(new_session_id)

        # 2. Create new MessageStore and wire it
        new_store = MessageStore()
        self._agent.memory.set_message_store(new_store, new_session_id)

        # 3. Re-subscribe protocol to new store
        self.unsubscribe_from_store()
        self._store = new_store
        self.subscribe_to_store()

        # 3b. Re-wire delegation tool with fresh bridge for new session
        self.wire_delegation_tool()

        # 4. Update session tracking
        self._session_id = new_session_id

        # 5. Send session_info so client clears chat and shows new session
        model_name = getattr(self._agent, "model_name", "unknown")
        permission_mode = self._agent.get_permission_mode()
        auto_approve_categories = self._agent.get_auto_approve_categories()
        await self.send_session_info(
            session_id=new_session_id,
            model_name=model_name,
            permission_mode=permission_mode,
            working_directory=self._working_directory,
            auto_approve_categories=auto_approve_categories,
        )

        logger.info("stdio_session_reset", session_id=new_session_id)

    async def _handle_list_sessions(self) -> None:
        """List available sessions for the history panel."""
        from pathlib import Path

        from src.session.scanner import scan_sessions

        sessions_dir = Path(self._working_directory) / ".clarity" / "sessions"
        try:
            sessions = scan_sessions(sessions_dir, limit=50)

            sessions_data = []
            for s in sessions:
                # Skip the currently active session
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
            await self._send_json(
                {
                    "type": "error",
                    "error_type": "session_list_error",
                    "user_message": f"Failed to list sessions: {e}",
                    "recoverable": True,
                }
            )

    async def _handle_resume_session(self, session_id: str) -> None:
        """Resume a previous session by session_id."""
        from pathlib import Path

        sessions_dir = Path(self._working_directory) / ".clarity" / "sessions"

        # Find session JSONL file (both flat and directory structures)
        jsonl_path = None
        dir_path = sessions_dir / session_id / "session.jsonl"
        flat_path = sessions_dir / f"{session_id}.jsonl"

        if dir_path.exists():
            jsonl_path = dir_path
        elif flat_path.exists():
            jsonl_path = flat_path

        if not jsonl_path:
            await self._send_json(
                {
                    "type": "error",
                    "error_type": "session_not_found",
                    "user_message": f"Session not found: {session_id}",
                    "recoverable": True,
                }
            )
            return

        try:
            # Hydrate session from JSONL
            result = self._agent.resume_session_from_jsonl(jsonl_path)

            # Set session ID (is_new_session=False to preserve state)
            self._agent.set_session_id(session_id, is_new_session=False)

            # Get the hydrated store
            new_store = result.store

            # Re-wire protocol to new store
            self.unsubscribe_from_store()
            self._store = new_store
            self.subscribe_to_store()

            # Re-wire delegation tool with fresh bridge
            self.wire_delegation_tool()

            # Update session tracking
            self._session_id = session_id

            # Build session_history payload from store's transcript view
            messages = new_store.get_transcript_view(include_pre_compaction=True)
            replay_messages = []
            for msg in messages:
                # Content can be str or list (multimodal) -- extract text
                content = msg.content
                if isinstance(content, list):
                    content = " ".join(
                        p.get("text", "")
                        for p in content
                        if isinstance(p, dict) and p.get("type") == "text"
                    )
                replay_msg: dict[str, Any] = {
                    "role": msg.role,
                    "content": content or "",
                }
                if msg.tool_calls:
                    replay_msg["tool_calls"] = [
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
                    replay_msg["tool_call_id"] = msg.tool_call_id
                if msg.meta:
                    meta: dict[str, Any] = {}
                    if hasattr(msg.meta, "stop_reason") and msg.meta.stop_reason:
                        meta["status"] = msg.meta.stop_reason
                    if meta:
                        replay_msg["meta"] = meta
                replay_messages.append(replay_msg)

            # Send session_info FIRST so client clears old chat state
            model_name = getattr(self._agent, "model_name", "unknown")
            permission_mode = self._agent.get_permission_mode()
            auto_approve_categories = self._agent.get_auto_approve_categories()
            await self.send_session_info(
                session_id=session_id,
                model_name=model_name,
                permission_mode=permission_mode,
                working_directory=self._working_directory,
                auto_approve_categories=auto_approve_categories,
            )

            # Then send batch history for the client to render
            await self._send_json(
                {
                    "type": "session_history",
                    "messages": replay_messages,
                }
            )

            logger.info(
                "stdio_session_resumed",
                session_id=session_id,
                message_count=len(replay_messages),
            )

        except Exception as e:
            logger.error("stdio_resume_session_error", error=str(e))
            await self._send_json(
                {
                    "type": "error",
                    "error_type": "session_resume_error",
                    "user_message": f"Failed to resume session: {e}",
                    "recoverable": True,
                }
            )

    # -----------------------------------------------------------------
    # Jira integration handlers
    # -----------------------------------------------------------------

    async def _handle_jira_profiles(self) -> None:
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

            # Check if any profile is currently connected
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
                    "error": str(e),
                }
            )

    async def _handle_jira_save(self, data: dict) -> None:
        """Save Jira profile configuration."""
        try:
            import re

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
                    "message": f"Save failed: {e}",
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
                timeout=120,
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
                    "message": "Connection timed out (120s). Is mcp-atlassian installed?",
                }
            )
        except Exception as e:
            logger.warning("stdio_jira_connect_error", error=str(e))
            await self._send_json(
                {
                    "type": "jira_connect_result",
                    "success": False,
                    "message": f"Connection failed: {e}",
                }
            )

    async def _handle_jira_disconnect(self) -> None:
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
                    "message": f"Disconnect failed: {e}",
                }
            )

    # -----------------------------------------------------------------

    async def shutdown(self) -> None:
        """Close TCP connection."""
        if self._tcp_writer:
            try:
                self._tcp_writer.close()
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
    from src.session.store.memory_store import MessageStore

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
                chat_msg = await asyncio.wait_for(protocol.wait_for_chat_message(), timeout=1.0)
            except asyncio.TimeoutError:
                if receive_task.done():
                    break
                continue

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
                    raw_bytes = b""
                    if ";base64," in data_url:
                        raw_bytes = b64.b64decode(data_url.split(";base64,", 1)[1])
                    attachments.append(
                        Attachment(
                            kind="image",
                            data=raw_bytes,
                            mime=img.get("mime", "image/png"),
                            filename=img.get("filename", "screenshot.png"),
                        )
                    )

            # Stream response
            logger.info("stdio_chat_received", content_preview=chat_content[:80])
            logger.debug("stdio_stream_start")
            event_count = 0
            try:
                async for event in agent.stream_response(
                    user_input=chat_content,
                    ui=protocol,
                    attachments=attachments,
                ):
                    event_count += 1
                    etype = type(event).__name__
                    if event_count == 1 or event_count % 10 == 0:
                        logger.debug("stdio_stream_event", event_num=event_count, event_type=etype)
                    await protocol.send_event(event)
            except asyncio.CancelledError:
                logger.info("stdio_stream_cancelled", event_count=event_count)
            except Exception as e:
                logger.error("stdio_stream_error", error=str(e))
                await protocol._send_json(
                    {
                        "type": "error",
                        "error_type": "api_error",
                        "user_message": "An internal error occurred.",
                        "recoverable": True,
                    }
                )

    finally:
        receive_task.cancel()
        try:
            await receive_task
        except asyncio.CancelledError:
            pass
        protocol.unsubscribe_from_store()
        await protocol.shutdown()
        agent.shutdown()
        logger.info("stdio_server_stopped")
