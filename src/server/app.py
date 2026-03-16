"""HTTP + WebSocket server wrapping CodingAgent.

Responsibilities:
- Start/stop aiohttp server on configurable port
- Health check endpoint (GET /health)
- WebSocket endpoint (GET /ws)
- Agent lifecycle management (create, configure, shutdown)
- Graceful shutdown on SIGINT/SIGTERM
"""

import asyncio
import hmac
import json
import os
import secrets
import uuid
from typing import Optional

from aiohttp import WSMsgType, web

from src.core.agent import CodingAgent
from src.core.events import StreamEnd, StreamStart
from src.observability import get_logger
from src.server.ws_protocol import WebSocketProtocol
from src.session.store.memory_store import MessageStore

logger = get_logger("server.app")


class AgentServer:
    """HTTP + WebSocket server wrapping CodingAgent.

    Creates a CodingAgent instance and exposes it over WebSocket.
    Only one active WebSocket connection at a time (Phase 1).
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 9120,
        working_directory: str | None = None,
        config_path: str | None = None,
        permission_mode: str = "auto",
        api_key: str | None = None,
        # Legacy: still accepted for backward compatibility
        agent_kwargs: dict | None = None,
    ):
        self._host = host
        self._port = port
        self._working_directory = working_directory or os.getcwd()
        self._permission_mode = permission_mode
        self._api_key = api_key
        self._agent_kwargs = agent_kwargs  # Legacy fallback
        from src.llm.config_loader import SYSTEM_CONFIG_PATH

        self._config_path = config_path or SYSTEM_CONFIG_PATH

        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._agent: CodingAgent | None = None
        self._active_ws: WebSocketProtocol | None = None
        self._session_id: str | None = None
        self._auth_token: str = secrets.token_urlsafe(32)

    async def start(self) -> None:
        """Start the HTTP/WS server."""
        from src.llm.config_loader import load_llm_config

        if self._agent_kwargs is not None:
            # Legacy path: caller passed raw kwargs (e.g. old __main__.py)
            self._agent = CodingAgent(**self._agent_kwargs)
            self._session_id = str(uuid.uuid4())
            llm_config = load_llm_config(self._config_path)
            if llm_config.subagents and hasattr(self._agent, "subagent_manager"):
                self._agent.subagent_manager.config_loader.apply_llm_overrides(llm_config)
            self._message_store = MessageStore()
            self._agent.set_session_id(self._session_id, is_new_session=True)
            self._agent.memory.set_message_store(self._message_store, self._session_id)
        else:
            # New path: load config and use from_config() factory
            llm_config = load_llm_config(self._config_path)
            self._agent = CodingAgent.from_config(
                llm_config,
                working_directory=self._working_directory,
                permission_mode=self._permission_mode,
                api_key=self._api_key,
            )
            self._session_id = self._agent.session_id
            self._message_store = self._agent.message_store

        logger.info(
            f"[SERVER] Agent created, session_id={self._session_id}, "
            f"working_directory={self._working_directory}"
        )

        # Set up aiohttp app
        self._app = web.Application()
        self._app.router.add_get("/health", self._handle_health)
        self._app.router.add_get("/ws", self._handle_websocket)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()

        site = web.TCPSite(self._runner, self._host, self._port)
        await site.start()

        logger.info(f"[SERVER] Listening on http://{self._host}:{self._port}")
        print(f"ClarAIty server listening on http://{self._host}:{self._port}")
        print(f"  WebSocket: ws://{self._host}:{self._port}/ws")
        print(f"  Health:    http://{self._host}:{self._port}/health")
        print(f"  Session:   {self._session_id}")
        print(f"  Auth Token: {self._auth_token}", flush=True)

        if self._host != "127.0.0.1":
            print("\n  [WARNING] Server bound to non-localhost address!")
            print(
                "  This exposes the agent to the network. Ensure authentication is enforced.",
                flush=True,
            )

        # Prime the HTTP connection pool (TCP+TLS) to the LLM API
        # so the first user message doesn't pay connection setup cost.
        # No tokens consumed — just establishes the transport.
        await self._warmup_connection()

    async def _warmup_connection(self) -> None:
        """Establish TCP+TLS connection to LLM API without consuming tokens.

        Opens a raw HTTPS connection to the provider's base URL via httpx,
        which primes the async_client's connection pool. The first real
        LLM call then skips the TCP handshake + TLS negotiation.
        """
        client = getattr(self._agent.llm, "async_client", None)
        if client is None:
            return

        try:
            # Access the underlying httpx client to prime its connection pool.
            # Both OpenAI and Anthropic SDKs expose ._client (httpx.AsyncClient).
            http_client = getattr(client, "_client", None)
            if http_client is None:
                return

            base_url = str(getattr(http_client, "base_url", ""))
            if not base_url:
                return

            # HEAD request to the base URL establishes TCP+TLS without
            # consuming any API tokens. We don't care about the response.
            resp = await http_client.head(base_url, timeout=5.0)
            resp.close()
            logger.info("[SERVER] LLM connection pool primed (TCP+TLS)")
        except Exception as e:
            # Non-critical: first message will just have ~200ms extra latency
            logger.debug(f"[SERVER] Connection warmup skipped: {e}")

    async def stop(self) -> None:
        """Graceful shutdown: close WebSocket connections, stop agent."""
        logger.info("[SERVER] Shutting down...")

        if self._agent:
            try:
                self._agent.shutdown()
            except Exception as e:
                logger.warning(f"[SERVER] Agent shutdown error: {e}")

        if self._runner:
            await self._runner.cleanup()

        logger.info("[SERVER] Shutdown complete")

    async def _handle_health(self, request: web.Request) -> web.Response:
        """GET /health -- returns server status."""
        return web.json_response(
            {
                "status": "ok",
                "has_active_connection": self._active_ws is not None,
            }
        )

    async def _handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        """Handle a new WebSocket connection.

        Creates a WebSocketProtocol and runs the agent event loop.
        Only one active connection at a time in Phase 1.

        Auth flow: client connects, then sends {"type":"auth","token":"..."}
        as its first message. Token is validated with hmac.compare_digest
        to prevent timing attacks. On success, server responds with
        session_info. On failure, server sends error and closes.
        """
        # --- ORIGIN CHECK ---
        origin = request.headers.get("Origin", "")
        ALLOWED_ORIGINS = {"vscode-webview://"}
        if origin and not any(origin.startswith(ao) for ao in ALLOWED_ORIGINS):
            logger.warning(f"[SERVER] Rejected WebSocket from disallowed origin: {origin}")
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            await ws.send_json(
                {
                    "type": "error",
                    "error_type": "origin_rejected",
                    "user_message": "Connection from this origin is not allowed.",
                    "recoverable": False,
                }
            )
            await ws.close()
            return ws

        # Reject if another client is already connected (and still alive)
        if self._active_ws is not None:
            # Check if the existing connection is actually still open
            old_ws = self._active_ws._ws
            if old_ws.closed:
                # Stale connection — clean it up and accept the new one
                logger.info("[SERVER] Cleaning up stale WebSocket connection")
                self._active_ws.unsubscribe_from_store()
                self._active_ws = None
            else:
                ws = web.WebSocketResponse()
                await ws.prepare(request)
                await ws.send_json(
                    {
                        "type": "error",
                        "error_type": "connection_limit",
                        "user_message": "Another client is already connected",
                        "recoverable": False,
                    }
                )
                await ws.close()
                return ws

        ws = web.WebSocketResponse(
            heartbeat=30.0, max_msg_size=20 * 1024 * 1024
        )  # 20MB for image attachments
        await ws.prepare(request)

        # --- FIRST-MESSAGE AUTH HANDSHAKE ---
        # Wait for the client to send {"type": "auth", "token": "..."}
        try:
            auth_msg = await ws.receive(timeout=10.0)
        except asyncio.TimeoutError:
            logger.warning(f"[SERVER] Auth handshake timed out from {request.remote}")
            await ws.send_json(
                {
                    "type": "error",
                    "error_type": "auth_failed",
                    "user_message": "Authentication timed out.",
                    "recoverable": False,
                }
            )
            await ws.close()
            return ws

        if auth_msg.type != WSMsgType.TEXT:
            logger.warning(f"[SERVER] Expected text auth message, got {auth_msg.type}")
            if not ws.closed:
                try:
                    await ws.send_json(
                        {
                            "type": "error",
                            "error_type": "auth_failed",
                            "user_message": "Authentication failed.",
                            "recoverable": False,
                        }
                    )
                except Exception:
                    pass
                await ws.close()
            return ws

        try:
            auth_data = json.loads(auth_msg.data)
        except (json.JSONDecodeError, TypeError):
            auth_data = {}

        client_token = auth_data.get("token", "") if isinstance(auth_data, dict) else ""
        auth_type = auth_data.get("type", "") if isinstance(auth_data, dict) else ""

        if auth_type != "auth" or not hmac.compare_digest(str(client_token), self._auth_token):
            logger.warning(f"[SERVER] Rejected unauthenticated WebSocket from {request.remote}")
            await ws.send_json(
                {
                    "type": "error",
                    "error_type": "auth_failed",
                    "user_message": "Authentication failed.",
                    "recoverable": False,
                }
            )
            await ws.close()
            return ws

        logger.info(f"[SERVER] WebSocket client authenticated from {request.remote}")

        # Create protocol instance
        protocol = WebSocketProtocol(
            ws=ws,
            message_store=self._message_store,
            agent=self._agent,
            config_path=self._config_path,
        )
        self._active_ws = protocol

        # Subscribe to store notifications
        protocol.subscribe_to_store()

        # Wire subagent delegation tool with bridge + protocol
        self._wire_delegation_tool(protocol)

        # Wire new_session callback
        protocol._on_new_session = lambda: self._reset_session(protocol)

        # Wire session history callbacks
        protocol._on_list_sessions = lambda: self._list_sessions(protocol)
        protocol._on_resume_session = lambda sid: self._resume_session(protocol, sid)

        try:
            # Send session info (also serves as auth_ok acknowledgment)
            model_name = getattr(self._agent, "model_name", "unknown")

            permission_mode = self._agent.get_permission_mode() if self._agent else "normal"
            auto_approve_categories = (
                self._agent.get_auto_approve_categories() if self._agent else None
            )

            await protocol.send_session_info(
                session_id=self._session_id,
                model_name=model_name,
                permission_mode=permission_mode,
                working_directory=self._working_directory,
                auto_approve_categories=auto_approve_categories,
            )

            # Run the main loop: receive messages and process them
            await self._connection_loop(protocol)

        except Exception as e:
            logger.error(f"[SERVER] Connection error: {e}")

        finally:
            protocol.unsubscribe_from_store()
            self._active_ws = None
            if not ws.closed:
                await ws.close()
            logger.info("[SERVER] WebSocket client disconnected")

        return ws

    async def _connection_loop(self, protocol: WebSocketProtocol) -> None:
        """Main connection loop: receive chat messages, stream responses.

        Runs the receive_loop (for UserActions) concurrently with
        processing chat messages (which trigger stream_response).
        """
        # Start the receive loop in the background
        receive_task = asyncio.create_task(protocol.receive_loop())

        try:
            while not protocol._ws.closed:
                # Wait for a chat message from the client
                try:
                    chat_msg = await asyncio.wait_for(
                        protocol.wait_for_chat_message(),
                        timeout=1.0,
                    )
                except asyncio.TimeoutError:
                    # No chat message yet, check if connection is still alive
                    if receive_task.done():
                        break
                    continue

                # Reset protocol state for new turn
                protocol.reset()

                # Extract content and images from the chat message dict
                chat_content = (
                    chat_msg.get("content", "") if isinstance(chat_msg, dict) else str(chat_msg)
                )
                raw_images = chat_msg.get("images", []) if isinstance(chat_msg, dict) else []

                # Build Attachment objects from images
                attachments = None
                if raw_images:
                    import base64 as b64

                    from src.core.attachment import Attachment

                    attachments = []
                    for img in raw_images:
                        data_url = img.get("data_url", "")
                        # Decode base64 from data URL (data:image/png;base64,AAAA...)
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

                # Stream the response
                logger.info("ws_chat_received", content_preview=chat_content[:80])
                try:
                    async for event in self._agent.stream_response(
                        user_input=chat_content,
                        ui=protocol,
                        attachments=attachments,
                    ):
                        await protocol.send_event(event)
                except asyncio.CancelledError:
                    logger.info("ws_stream_cancelled")
                except Exception as e:
                    logger.error("ws_stream_error", error=str(e))
                    await protocol._send_json(
                        {
                            "type": "error",
                            "error_type": "api_error",
                            "user_message": "An internal error occurred. Check server logs for details.",
                            "recoverable": True,
                        }
                    )

        finally:
            receive_task.cancel()
            try:
                await receive_task
            except asyncio.CancelledError:
                pass

    async def _reset_session(self, protocol: WebSocketProtocol) -> None:
        """Reset agent to a fresh session (New Chat).

        Creates a new MessageStore, resets agent state, and re-subscribes
        the protocol to the new store. Sends session_info so the client
        clears its chat UI.
        """
        new_session_id = str(uuid.uuid4())

        # 1. Reset core agent state
        self._agent.reset_session(new_session_id)

        # 2. Create new MessageStore and wire it
        new_store = MessageStore()
        self._agent.memory.set_message_store(new_store, new_session_id)

        # 3. Re-subscribe protocol to new store
        protocol.unsubscribe_from_store()
        protocol._store = new_store
        protocol.subscribe_to_store()

        # 3b. Re-wire delegation tool with fresh bridge for new session
        self._wire_delegation_tool(protocol)

        # 4. Update server-level references
        self._message_store = new_store
        self._session_id = new_session_id

        # 5. Send session_info so client clears chat and shows new session
        model_name = getattr(self._agent, "model_name", "unknown")
        permission_mode = self._agent.get_permission_mode()
        auto_approve_categories = self._agent.get_auto_approve_categories()
        await protocol.send_session_info(
            session_id=new_session_id,
            model_name=model_name,
            permission_mode=permission_mode,
            working_directory=self._working_directory,
            auto_approve_categories=auto_approve_categories,
        )

        logger.info(f"[SERVER] Session reset to {new_session_id}")

    async def _list_sessions(self, protocol: WebSocketProtocol) -> None:
        """List available sessions for the history panel.

        Reuses scan_sessions() from session_picker to find and extract
        metadata from JSONL session files.
        """
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

            await protocol._send_json(
                {
                    "type": "sessions_list",
                    "sessions": sessions_data,
                }
            )
        except Exception as e:
            logger.error(f"[SERVER] Error listing sessions: {e}")
            await protocol._send_json(
                {
                    "type": "error",
                    "error_type": "session_list_error",
                    "user_message": f"Failed to list sessions: {e}",
                    "recoverable": True,
                }
            )

    async def _resume_session(self, protocol: WebSocketProtocol, session_id: str) -> None:
        """Resume a previous session by session_id.

        Finds the JSONL file, hydrates via agent.resume_session_from_jsonl(),
        re-wires the store and protocol, then sends the full session history
        as a single batch message for the WebView to render at once.
        """
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
            await protocol._send_json(
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

            # Re-wire protocol to new store (same pattern as _reset_session)
            protocol.unsubscribe_from_store()
            protocol._store = new_store
            protocol.subscribe_to_store()

            # Re-wire delegation tool with fresh bridge
            self._wire_delegation_tool(protocol)

            # Update server-level references
            self._message_store = new_store
            self._session_id = session_id

            # Build session_history payload from store's transcript view
            messages = new_store.get_transcript_view(include_pre_compaction=True)
            replay_messages = []
            for msg in messages:
                # Content can be str or list (multimodal) — extract text
                content = msg.content
                if isinstance(content, list):
                    # Multimodal: extract text parts only
                    content = " ".join(
                        p.get("text", "")
                        for p in content
                        if isinstance(p, dict) and p.get("type") == "text"
                    )
                replay_msg = {
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
                    meta = {}
                    if hasattr(msg.meta, "stop_reason") and msg.meta.stop_reason:
                        meta["status"] = msg.meta.stop_reason
                    if meta:
                        replay_msg["meta"] = meta
                replay_messages.append(replay_msg)

            # Send session_info FIRST so client clears old chat state
            # and updates currentSessionId before history arrives
            model_name = getattr(self._agent, "model_name", "unknown")
            permission_mode = self._agent.get_permission_mode()
            auto_approve_categories = self._agent.get_auto_approve_categories()
            await protocol.send_session_info(
                session_id=session_id,
                model_name=model_name,
                permission_mode=permission_mode,
                working_directory=self._working_directory,
                auto_approve_categories=auto_approve_categories,
            )

            # Then send batch history for the client to render
            await protocol._send_json(
                {
                    "type": "session_history",
                    "messages": replay_messages,
                }
            )

            logger.info(f"[SERVER] Session resumed: {session_id} ({len(replay_messages)} messages)")

        except Exception as e:
            logger.error(f"[SERVER] Error resuming session {session_id}: {e}")
            await protocol._send_json(
                {
                    "type": "error",
                    "error_type": "session_resume_error",
                    "user_message": f"Failed to resume session: {e}",
                    "recoverable": True,
                }
            )

    def _wire_delegation_tool(self, protocol: WebSocketProtocol) -> None:
        """Wire the delegation tool with a ServerSubagentBridge + protocol.

        Gives the delegation tool two things it needs for subagent visibility:
        1. A bridge (duck-typed registry) that forwards events over WebSocket
        2. The WebSocket protocol for interactive requests (approval/clarify/pause)
        """
        if not self._agent:
            return
        delegation_tool = self._agent.tool_executor.tools.get("delegate_to_subagent")
        if not delegation_tool:
            return

        from src.server.subagent_bridge import ServerSubagentBridge

        bridge = ServerSubagentBridge(protocol)
        delegation_tool.set_registry(bridge)
        delegation_tool.set_ui_protocol(protocol)
        logger.info("[SERVER] Wired delegation tool with subagent bridge")
