"""WebSocket-based UIProtocol implementation.

Extends UIProtocol to:
- Serialize UIEvents to JSON and send over WebSocket
- Subscribe to MessageStore for tool state and message lifecycle
- Receive JSON from WebSocket and convert to UserAction
- Manage the send/receive pumps

This is the functional equivalent of what AgentApp does
for the Textual TUI, but for WebSocket clients.

CONCURRENCY MODEL:
- UIEvents arrive on the asyncio event loop (from stream_response iterator)
- StoreNotifications may arrive from the tool executor thread pool
- Both paths write to the same WebSocket
- An asyncio.Lock protects all WebSocket sends to prevent interleaved frames
- StoreNotification callbacks use loop.call_soon_threadsafe() to schedule
  sends on the event loop before acquiring the lock
"""

import asyncio
from collections.abc import Callable
from typing import Any, Optional

from aiohttp import WSMsgType, web

from src.core.events import PausePromptStart, UIEvent
from src.core.protocol import PauseResult, UIProtocol
from src.observability import get_logger
from src.server.serializers import (
    deserialize_action,
    serialize_event,
    serialize_store_notification,
)
from src.session.store.memory_store import MessageStore, StoreNotification

logger = get_logger("server.ws_protocol")


class WebSocketProtocol(UIProtocol):
    """WebSocket transport for the CodingAgent UIProtocol.

    Dual subscription model:
    1. UIEvent async iterator from stream_response() -> JSON over WebSocket
    2. MessageStore.subscribe() for store notifications -> JSON over WebSocket
    """

    def __init__(
        self,
        ws: web.WebSocketResponse,
        message_store: MessageStore,
        agent=None,
        config_path: str = "",
    ):
        super().__init__()
        self._ws = ws
        self._store = message_store
        self._agent = agent
        self._config_path = config_path
        self._send_lock = asyncio.Lock()
        self._loop = asyncio.get_event_loop()
        self._unsubscribe: Callable[[], None] | None = None
        self._on_new_session: Callable[[], Any] | None = None
        self._on_list_sessions: Callable[[], Any] | None = None
        self._on_resume_session: Callable[[str], Any] | None = None

    async def _safe_background_send(self, coro) -> None:
        """Run a coroutine in the background with error logging."""
        try:
            await coro
        except Exception as e:
            logger.warning(f"[WS] Background send failed: {e}")

    # -----------------------------------------------------------------
    # Dual Subscription Setup
    # -----------------------------------------------------------------

    def subscribe_to_store(self) -> None:
        """Subscribe to MessageStore for tool state and message events.

        The callback may be invoked from a thread pool thread (tool execution),
        so it uses loop.call_soon_threadsafe() to schedule the async send
        on the event loop.
        """

        def on_notification(notification: StoreNotification) -> None:
            self._loop.call_soon_threadsafe(
                asyncio.ensure_future,
                self._safe_background_send(self._send_store_notification(notification)),
            )

        self._unsubscribe = self._store.subscribe(on_notification)
        logger.info("[WS] Subscribed to MessageStore notifications")

    def unsubscribe_from_store(self) -> None:
        """Unsubscribe from MessageStore."""
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None
            logger.info("[WS] Unsubscribed from MessageStore notifications")

    # -----------------------------------------------------------------
    # Todo Notifications (Agent -> Client)
    # -----------------------------------------------------------------

    def notify_todos_updated(self, todos: list) -> None:
        """Send todo list to WebSocket client."""
        asyncio.ensure_future(
            self._safe_background_send(
                self._send_json(
                    {
                        "type": "todos_updated",
                        "todos": todos,
                    }
                )
            )
        )

    # -----------------------------------------------------------------
    # Sending (Agent -> Client)
    # -----------------------------------------------------------------

    async def send_event(self, event: UIEvent) -> None:
        """Serialize a UIEvent to JSON and send over WebSocket.

        Acquires _send_lock to prevent interleaved frames with store notifications.
        """
        data = serialize_event(event)
        if data is not None:
            await self._send_json(data)

    async def _send_store_notification(self, notification: StoreNotification) -> None:
        """Serialize a StoreNotification to JSON and send over WebSocket.

        Acquires _send_lock to prevent interleaved frames with UIEvent sends.
        """
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
        """Send synthetic session_info message on connection."""
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

    async def _send_json(self, data: dict) -> None:
        """Send JSON over WebSocket with lock protection."""
        if self._ws.closed:
            return
        try:
            async with self._send_lock:
                await self._ws.send_json(data)
        except ConnectionResetError:
            logger.warning("[WS] Connection reset during send")
        except Exception as e:
            logger.warning(f"[WS] Send error: {e}")

    # -----------------------------------------------------------------
    # Subagent Interactive Overrides
    # -----------------------------------------------------------------

    async def request_pause(self, reason, reason_code, stats, pending_todos=None):
        """Override base to send PausePromptStart directly over WebSocket.

        The base implementation calls ``_on_pause_requested`` callback (which
        is None in the server context) then waits. Here we serialize a
        ``PausePromptStart`` event so the VS Code client shows its pause
        widget, then await the user's response via the existing future.
        """
        event = PausePromptStart(
            reason=reason,
            reason_code=reason_code,
            pending_todos=pending_todos or [],
            stats=stats,
        )
        await self.send_event(event)
        return await self.wait_for_pause_response()

    async def send_clarify_request(self, call_id, questions, context):
        """Send clarify form data to WebSocket client.

        Called by the delegation tool when a subagent emits a clarify
        APPROVAL_REQUEST.  The TUI uses SubAgentCard for this; the server
        needs an explicit JSON message so the VS Code sidebar can render
        the clarify form.
        """
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

    # -----------------------------------------------------------------
    # Receiving (Client -> Agent)
    # -----------------------------------------------------------------

    async def receive_loop(self) -> None:
        """Read JSON messages from WebSocket and dispatch.

        Runs concurrently with the agent event loop.
        Converts JSON to UserAction and calls submit_action().
        Chat messages are handled separately via a queue.
        """
        async for ws_msg in self._ws:
            if ws_msg.type == WSMsgType.TEXT:
                try:
                    data = ws_msg.json()
                    msg_type = data.get("type")

                    if msg_type == "chat_message":
                        # Chat messages go to a separate queue for the server
                        # to pick up and feed to agent.stream_response()
                        content = data.get("content", "")
                        images = data.get("images", [])
                        if len(content) > 100_000:
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
                            await self._chat_queue.put(
                                {
                                    "content": content,
                                    "images": images,
                                }
                            )
                    elif msg_type == "set_mode":
                        mode = data.get("mode", "")
                        VALID_MODES = {"plan", "normal", "auto"}
                        if mode not in VALID_MODES:
                            logger.warning(f"[WS] Invalid mode rejected: {mode!r}")
                            await self._send_json(
                                {
                                    "type": "error",
                                    "error_type": "invalid_mode",
                                    "user_message": f"Invalid mode: {mode}. Valid modes: {', '.join(sorted(VALID_MODES))}",
                                    "recoverable": True,
                                }
                            )
                            continue
                        if mode and self._agent:
                            try:
                                self._agent.set_permission_mode(mode)
                                # Confirm with the agent's actual mode
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
                    elif msg_type == "set_auto_approve":
                        categories = data.get("categories", {})
                        if self._agent:
                            confirmed = self._agent.set_auto_approve_categories(categories)
                            await self._send_json(
                                {
                                    "type": "auto_approve_changed",
                                    "categories": confirmed,
                                }
                            )

                    elif msg_type == "get_auto_approve":
                        if self._agent:
                            await self._send_json(
                                {
                                    "type": "auto_approve_changed",
                                    "categories": self._agent.get_auto_approve_categories(),
                                }
                            )

                    elif msg_type == "get_config":
                        from src.server.config_handler import get_config_response

                        response = get_config_response(self._config_path)
                        await self._send_json(response)

                    elif msg_type == "save_config":
                        from src.server.config_handler import save_config_from_request

                        response = save_config_from_request(data, self._config_path)

                        # Hot-swap the LLM backend if agent is available
                        cfg = response.pop("_config", None)
                        api_key = response.pop("_api_key", None)
                        if response.get("success") and cfg and self._agent:
                            try:
                                import os

                                resolved_key = api_key or os.environ.get(
                                    cfg.api_key_env, ""
                                )
                                summary = self._agent.reconfigure_llm(
                                    cfg, api_key=resolved_key
                                )
                                response["message"] = f"LLM config applied: {summary}"
                            except Exception as exc:
                                logger.warning(f"LLM reconfigure failed: {exc}")
                                response["message"] = (
                                    f"Config saved but apply failed: {exc}. "
                                    "Restart server to apply changes."
                                )

                        await self._send_json(response)

                    elif msg_type == "list_models":
                        from src.server.config_handler import list_models_from_request

                        loop = asyncio.get_event_loop()
                        response = await loop.run_in_executor(None, list_models_from_request, data)
                        await self._send_json(response)

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

                    elif msg_type == "new_session":
                        if self._on_new_session:
                            await self._on_new_session()

                    elif msg_type == "list_sessions":
                        if self._on_list_sessions:
                            await self._on_list_sessions()

                    elif msg_type == "resume_session":
                        session_id = data.get("session_id", "")
                        if session_id and self._on_resume_session:
                            await self._on_resume_session(session_id)

                    else:
                        # All other messages are UserActions
                        action = deserialize_action(data)
                        if action is not None:
                            self.submit_action(action)
                        else:
                            logger.warning(f"[WS] Unknown message type: {msg_type}")

                except Exception as e:
                    logger.warning(f"[WS] Error processing message: {e}")

            elif ws_msg.type == WSMsgType.ERROR:
                logger.warning(f"[WS] WebSocket error: {self._ws.exception()}")
                break

            elif ws_msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED):
                break

        logger.info("[WS] Receive loop ended")

    async def wait_for_chat_message(self) -> dict:
        """Wait for the next chat message from the client.

        Returns:
            dict with 'content' (str) and 'images' (list of image dicts).
        """
        return await self._chat_queue.get()

    @property
    def _chat_queue(self) -> asyncio.Queue:
        """Lazy-init chat message queue."""
        if not hasattr(self, "_chat_queue_impl"):
            self._chat_queue_impl: asyncio.Queue[dict] = asyncio.Queue()
        return self._chat_queue_impl

    # -----------------------------------------------------------------
    # Jira Integration Handlers
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
                    # Extract profile from config name "mcp-atlassian-<profile>"
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
            logger.warning(f"[WS] Failed to list Jira profiles: {e}")
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
                # Update config fields only
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
            logger.warning(f"[WS] Failed to save Jira config: {e}")
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
            logger.warning(f"[WS] Jira connect failed: {e}")
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
            logger.warning(f"[WS] Jira disconnect failed: {e}")
            await self._send_json(
                {
                    "type": "jira_disconnect_result",
                    "success": False,
                    "message": f"Disconnect failed: {e}",
                }
            )
