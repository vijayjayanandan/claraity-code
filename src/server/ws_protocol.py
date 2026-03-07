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
from typing import Any, Callable, Optional

from aiohttp import web, WSMsgType

from src.core.protocol import UIProtocol, PauseResult
from src.core.events import UIEvent, PausePromptStart
from src.session.store.memory_store import MessageStore, StoreNotification
from src.server.serializers import (
    serialize_event,
    serialize_store_notification,
    deserialize_action,
)
from src.observability import get_logger

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
        self._unsubscribe: Optional[Callable[[], None]] = None
        self._on_new_session: Optional[Callable[[], Any]] = None

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
        asyncio.ensure_future(self._safe_background_send(self._send_json({
            "type": "todos_updated",
            "todos": todos,
        })))

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

    async def request_pause(self, reason, reason_code, stats,
                            pending_todos=None):
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
        await self._send_json({
            "type": "interactive",
            "event": "clarify_request",
            "data": {
                "call_id": call_id,
                "questions": questions or [],
                "context": context,
            },
        })

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
                        if len(content) > 100_000:
                            await self._send_json({
                                "type": "error",
                                "error_type": "message_too_large",
                                "user_message": "Message too large. Maximum 100,000 characters.",
                                "recoverable": True,
                            })
                            continue
                        if content.strip():
                            await self._chat_queue.put(content)
                    elif msg_type == "set_mode":
                        mode = data.get("mode", "")
                        VALID_MODES = {"plan", "normal", "auto"}
                        if mode not in VALID_MODES:
                            logger.warning(f"[WS] Invalid mode rejected: {mode!r}")
                            await self._send_json({
                                "type": "error",
                                "error_type": "invalid_mode",
                                "user_message": f"Invalid mode: {mode}. Valid modes: {', '.join(sorted(VALID_MODES))}",
                                "recoverable": True,
                            })
                            continue
                        if mode and self._agent:
                            try:
                                self._agent.set_permission_mode(mode)
                                # Confirm with the agent's actual mode
                                actual = self._agent.get_permission_mode()
                                await self._send_json({
                                    "type": "interactive",
                                    "event": "permission_mode_changed",
                                    "data": {"new_mode": actual},
                                })
                            except ValueError:
                                await self._send_json({
                                    "type": "error",
                                    "error_type": "invalid_mode",
                                    "user_message": f"Invalid mode: {mode}",
                                    "recoverable": True,
                                })
                    elif msg_type == "set_auto_approve":
                        categories = data.get("categories", {})
                        if self._agent:
                            confirmed = self._agent.set_auto_approve_categories(categories)
                            await self._send_json({
                                "type": "auto_approve_changed",
                                "categories": confirmed,
                            })

                    elif msg_type == "get_auto_approve":
                        if self._agent:
                            await self._send_json({
                                "type": "auto_approve_changed",
                                "categories": self._agent.get_auto_approve_categories(),
                            })

                    elif msg_type == "get_config":
                        from src.server.config_handler import get_config_response
                        response = get_config_response(self._config_path)
                        await self._send_json(response)

                    elif msg_type == "save_config":
                        from src.server.config_handler import save_config_from_request
                        response = save_config_from_request(data, self._config_path)
                        await self._send_json(response)

                    elif msg_type == "list_models":
                        from src.server.config_handler import list_models_from_request
                        loop = asyncio.get_event_loop()
                        response = await loop.run_in_executor(
                            None, list_models_from_request, data
                        )
                        await self._send_json(response)

                    elif msg_type == "new_session":
                        if self._on_new_session:
                            await self._on_new_session()

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

    async def wait_for_chat_message(self) -> str:
        """Wait for the next chat message from the client."""
        return await self._chat_queue.get()

    @property
    def _chat_queue(self) -> asyncio.Queue:
        """Lazy-init chat message queue."""
        if not hasattr(self, "_chat_queue_impl"):
            self._chat_queue_impl: asyncio.Queue[str] = asyncio.Queue()
        return self._chat_queue_impl
