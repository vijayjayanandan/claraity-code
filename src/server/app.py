"""HTTP + WebSocket server wrapping CodingAgent.

Responsibilities:
- Start/stop aiohttp server on configurable port
- Health check endpoint (GET /health)
- WebSocket endpoint (GET /ws)
- Agent lifecycle management (create, configure, shutdown)
- Graceful shutdown on SIGINT/SIGTERM
"""

import asyncio
import os
import uuid
from typing import Optional

from aiohttp import web, WSMsgType

from src.core.agent import CodingAgent
from src.core.events import StreamStart, StreamEnd
from src.session.store.memory_store import MessageStore
from src.server.ws_protocol import WebSocketProtocol
from src.observability import get_logger

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
        working_directory: Optional[str] = None,
        agent_kwargs: Optional[dict] = None,
        config_path: Optional[str] = None,
    ):
        self._host = host
        self._port = port
        self._working_directory = working_directory or os.getcwd()
        self._agent_kwargs = agent_kwargs or {}
        from src.llm.config_loader import SYSTEM_CONFIG_PATH
        self._config_path = config_path or SYSTEM_CONFIG_PATH

        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None
        self._agent: Optional[CodingAgent] = None
        self._active_ws: Optional[WebSocketProtocol] = None
        self._session_id: Optional[str] = None

    async def start(self) -> None:
        """Start the HTTP/WS server."""
        # Create the agent
        self._agent = CodingAgent(**self._agent_kwargs)
        self._session_id = str(uuid.uuid4())

        # Create and wire MessageStore (same as CLI does)
        self._message_store = MessageStore()
        self._agent.set_session_id(self._session_id, is_new_session=True)
        self._agent.memory.set_message_store(self._message_store, self._session_id)

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
        return web.json_response({
            "status": "ok",
            "session_id": self._session_id,
            "has_active_connection": self._active_ws is not None,
        })

    async def _handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        """Handle a new WebSocket connection.

        Creates a WebSocketProtocol and runs the agent event loop.
        Only one active connection at a time in Phase 1.
        """
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
                await ws.send_json({
                    "type": "error",
                    "error_type": "connection_limit",
                    "user_message": "Another client is already connected",
                    "recoverable": False,
                })
                await ws.close()
                return ws

        ws = web.WebSocketResponse(heartbeat=30.0)
        await ws.prepare(request)

        logger.info(f"[SERVER] WebSocket client connected from {request.remote}")

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

        try:
            # Send session info
            model_name = getattr(self._agent, 'model_name', 'unknown')

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
                    chat_content = await asyncio.wait_for(
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

                # Stream the response
                logger.info(f"[SERVER] Processing chat: {chat_content[:80]}...")
                try:
                    async for event in self._agent.stream_response(
                        user_input=chat_content,
                        ui=protocol,
                    ):
                        await protocol.send_event(event)
                except asyncio.CancelledError:
                    logger.info("[SERVER] Stream cancelled")
                except Exception as e:
                    logger.error(f"[SERVER] Stream error: {e}")
                    await protocol._send_json({
                        "type": "error",
                        "error_type": "api_error",
                        "user_message": f"Agent error: {e}",
                        "recoverable": True,
                    })

        finally:
            receive_task.cancel()
            try:
                await receive_task
            except asyncio.CancelledError:
                pass
