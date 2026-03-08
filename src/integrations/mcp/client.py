"""MCP client with pluggable transport.

Transport is abstract so we can support:
- SSE (remote MCP servers like Atlassian Rovo)
- Stdio (local proxy processes)
- Mock (testing)

The client owns connection lifecycle and JSON-RPC framing.
Auth tokens are resolved from SecretStore at connect time and
NEVER stored on the client or included in logs.
"""

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from .config import McpServerConfig

try:
    from src.observability import get_logger
    logger = get_logger("integrations.mcp.client")
except ImportError:
    logger = logging.getLogger(__name__)


class McpTransport(ABC):
    """Abstract transport for MCP JSON-RPC communication."""

    @abstractmethod
    async def connect(self, config: McpServerConfig, auth_headers: Dict[str, str]) -> None:
        """Establish connection. auth_headers are ephemeral (not stored)."""

    @abstractmethod
    async def send(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Send a JSON-RPC request and return the result."""

    @abstractmethod
    async def send_notification(self, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        """Send a JSON-RPC notification (no id, no response expected)."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Close the connection and release resources."""

    @abstractmethod
    def is_connected(self) -> bool:
        """Check if transport is currently connected."""

    def close_sync(self) -> None:
        """Synchronous emergency cleanup for shutdown without an event loop.

        Override in subclasses that manage OS resources (subprocesses, pipes).
        Default is a no-op (safe for transports like SSE that only hold
        async resources).
        """


class SseTransport(McpTransport):
    """SSE (Server-Sent Events) transport for remote MCP servers.

    Auth tokens are injected per-request (not stored on the client) to
    minimize the window where secrets live in memory.
    """

    def __init__(self):
        self._client = None
        self._base_url: Optional[str] = None
        self._base_headers: Dict[str, str] = {}  # Non-secret headers only
        self._auth_headers: Dict[str, str] = {}  # Per-request auth; set at connect, cleared at disconnect
        self._connected = False

    async def connect(self, config: McpServerConfig, auth_headers: Dict[str, str]) -> None:
        import httpx

        self._base_url = config.server_url
        self._base_headers = {
            "Content-Type": "application/json",
            **config.extra_headers,
        }
        # Store auth headers separately; they are merged per-request, NOT
        # baked into the httpx client (which would copy them to internal state).
        self._auth_headers = dict(auth_headers)

        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=config.connect_timeout,
                read=config.invoke_timeout,
                write=30.0,
                pool=30.0,
            ),
            headers=self._base_headers,  # No secrets here
        )
        self._connected = True
        logger.info("sse_transport_connected", server=config.name)

    async def send(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self._client or not self._base_url:
            raise ConnectionError("SSE transport not connected")

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or {},
        }

        # Inject auth per-request (not stored on httpx client)
        response = await self._client.post(
            self._base_url, json=payload, headers=self._auth_headers
        )
        response.raise_for_status()
        result = response.json()

        if "error" in result:
            error = result["error"]
            raise McpError(
                code=error.get("code", -1),
                message=error.get("message", "Unknown MCP error"),
            )

        return result.get("result", {})

    async def send_notification(self, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        if not self._client or not self._base_url:
            raise ConnectionError("SSE transport not connected")

        payload = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params:
            payload["params"] = params

        await self._client.post(
            self._base_url, json=payload, headers=self._auth_headers
        )

    async def disconnect(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
        self._connected = False
        # Wipe auth from memory
        self._auth_headers.clear()

    def is_connected(self) -> bool:
        return self._connected


class StdioTransport(McpTransport):
    """Stdio transport for local MCP proxy processes.

    Launches a subprocess and communicates via stdin/stdout JSON-RPC.

    Stdio is inherently single-channel: only one request can be in-flight
    at a time (one stdin write + one stdout read). An asyncio.Lock serializes
    send() calls as a safety net against orphaned coroutines that may still
    hold stdout.readline() after a timeout.
    """

    def __init__(self):
        self._process = None
        self._connected = False
        self._request_id = 0
        self._send_lock: Optional[asyncio.Lock] = None  # created at connect time
        self._stderr_task: Optional[asyncio.Task] = None  # drains stderr to prevent deadlock

    async def connect(self, config: McpServerConfig, auth_headers: Dict[str, str]) -> None:
        import os
        import sys

        if not config.command:
            raise ValueError("StdioTransport requires config.command")

        # Pass auth via environment (not command-line args which appear in `ps`)
        env = os.environ.copy()
        if config.extra_env:
            env.update(config.extra_env)
        if auth_headers:
            env["MCP_AUTH_HEADERS"] = json.dumps(auth_headers)

        # On Windows, commands like `npx` are .CMD batch files that
        # create_subprocess_exec cannot run directly. Use shell mode.
        if sys.platform == "win32":
            self._process = await asyncio.create_subprocess_shell(
                config.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        else:
            import shlex
            cmd_parts = shlex.split(config.command)
            self._process = await asyncio.create_subprocess_exec(
                *cmd_parts,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

        self._send_lock = asyncio.Lock()
        self._connected = True

        # Drain stderr in background to prevent pipe buffer deadlock.
        # MCP servers may write logs/progress to stderr continuously.
        # If the 64KB OS pipe buffer fills, the subprocess blocks on
        # stderr write and can no longer respond on stdout.
        self._stderr_task = asyncio.ensure_future(self._drain_stderr())

        logger.info("stdio_transport_connected", command=config.command)

    async def _drain_stderr(self) -> None:
        """Read and discard stderr to prevent pipe buffer deadlock."""
        try:
            while self._process and self._process.stderr:
                chunk = await self._process.stderr.read(4096)
                if not chunk:
                    break
        except (asyncio.CancelledError, Exception):
            pass

    async def send(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self._process or not self._process.stdin or not self._process.stdout:
            raise ConnectionError("Stdio transport not connected")

        # Lock prevents concurrent reads on stdout (e.g. if a previous
        # coroutine was orphaned by a timeout and is still holding readline)
        async with self._send_lock:
            self._request_id += 1
            payload = {
                "jsonrpc": "2.0",
                "id": self._request_id,
                "method": method,
                "params": params or {},
            }

            line = json.dumps(payload) + "\n"
            self._process.stdin.write(line.encode())
            await self._process.stdin.drain()

            response_line = await self._process.stdout.readline()
            if not response_line:
                raise ConnectionError("Stdio transport: no response")

            result = json.loads(response_line)

        if "error" in result:
            error = result["error"]
            raise McpError(
                code=error.get("code", -1),
                message=error.get("message", "Unknown MCP error"),
            )

        return result.get("result", {})

    async def send_notification(self, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        if not self._process or not self._process.stdin:
            raise ConnectionError("Stdio transport not connected")

        # Notifications write to stdin; lock prevents interleaving with send()
        async with self._send_lock:
            payload = {
                "jsonrpc": "2.0",
                "method": method,
            }
            if params:
                payload["params"] = params

            line = json.dumps(payload) + "\n"
            self._process.stdin.write(line.encode())
            await self._process.stdin.drain()

    async def disconnect(self) -> None:
        # Cancel stderr drain task first
        if self._stderr_task and not self._stderr_task.done():
            self._stderr_task.cancel()
            self._stderr_task = None

        if self._process:
            # Close pipes before terminating to avoid ResourceWarning
            # on Windows (_ProactorBasePipeTransport.__del__)
            for pipe in (self._process.stdin, self._process.stdout, self._process.stderr):
                if pipe:
                    try:
                        pipe.close()
                    except Exception:
                        pass
            self._process.terminate()
            try:
                await self._process.wait()
            except Exception:
                pass
            self._process = None
        self._connected = False

    def close_sync(self) -> None:
        """Kill subprocess and close pipes without awaiting.

        For use when the event loop is closed or unavailable (e.g. on_unmount).

        The key challenge on Windows: asyncio subprocess/pipe transports have
        __del__ methods that call self.close(), which calls loop.call_soon().
        If the event loop is already closed, this raises RuntimeError.

        We neutralize the internal transport state so __del__ becomes a no-op:
        - BaseSubprocessTransport._closed = True  -> skips close() in __del__
        - _ProactorBasePipeTransport._closing = True, _sock = None -> skips
          both close() and the ResourceWarning in __del__
        """
        if self._stderr_task and not self._stderr_task.done():
            self._stderr_task.cancel()
            self._stderr_task = None

        if self._process:
            # -- Neutralize asyncio transport internals --
            # Access the underlying BaseSubprocessTransport via the
            # asyncio.subprocess.Process wrapper.
            subprocess_transport = getattr(self._process, '_transport', None)
            if subprocess_transport is not None:
                # Prevent BaseSubprocessTransport.__del__ -> close() -> loop.call_soon
                subprocess_transport._closed = True

                # Neutralize each pipe transport (_ProactorBasePipeTransport)
                for proto in getattr(subprocess_transport, '_pipes', {}).values():
                    pipe_transport = getattr(proto, 'pipe', None)
                    if pipe_transport is not None:
                        # Close the OS-level pipe handle
                        sock = getattr(pipe_transport, '_sock', None)
                        if sock is not None:
                            try:
                                sock.close()
                            except Exception:
                                pass
                        # Prevent __del__ from warning about unclosed transport
                        pipe_transport._sock = None
                        pipe_transport._closing = True

            # -- Kill the subprocess --
            try:
                self._process.kill()
            except Exception:
                pass
            self._process = None
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected


class McpError(Exception):
    """Error from MCP server."""

    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"MCP error {code}: {message}")


class McpClient:
    """MCP client that uses a pluggable transport.

    Handles JSON-RPC method dispatch for the MCP protocol:
    - tools/list -> discover available tools
    - tools/call -> invoke a tool

    Auth tokens are resolved fresh from SecretStore at connect time
    and passed to the transport. The token is NOT stored on the McpClient
    itself. The transport holds it for per-request injection and clears it
    on disconnect.
    """

    def __init__(self, config: McpServerConfig, transport: McpTransport):
        self._config = config
        self._transport = transport

    @property
    def config(self) -> McpServerConfig:
        return self._config

    def is_connected(self) -> bool:
        return self._transport.is_connected()

    async def connect(self, secret_store=None) -> None:
        """Connect to the MCP server and perform MCP initialization handshake.

        The MCP protocol requires an initialize/initialized exchange before
        any tool calls. This method:
        1. Opens the transport (subprocess or HTTP)
        2. Sends `initialize` with client capabilities
        3. Receives server capabilities
        4. Sends `notifications/initialized`

        Args:
            secret_store: Optional SecretStore to resolve auth tokens from.
                         If config.auth_secret_key is set, the token is fetched
                         and placed in auth_header_name. Token is NOT stored on
                         this McpClient; the transport holds it for per-request
                         injection and clears it on disconnect.
        """
        auth_headers: Dict[str, str] = {}

        if self._config.auth_secret_key and secret_store:
            token = secret_store.get(self._config.auth_secret_key)
            if token:
                auth_headers[self._config.auth_header_name] = token
            else:
                logger.warning(
                    "mcp_auth_token_missing",
                    secret_key=self._config.auth_secret_key,
                    server=self._config.name,
                )

        await self._transport.connect(self._config, auth_headers)

        # MCP initialization handshake
        init_result = await self._transport.send("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {"roots": {}, "sampling": {}},
            "clientInfo": {"name": "claraity-agent", "version": "1.0.0"},
        })

        server_info = init_result.get("serverInfo", {})
        logger.info(
            "mcp_server_initialized",
            server=self._config.name,
            server_name=server_info.get("name", "unknown"),
            server_version=server_info.get("version", "unknown"),
            protocol_version=init_result.get("protocolVersion", "unknown"),
        )

        # Send initialized notification (no id = notification, no response expected)
        await self._transport.send_notification("notifications/initialized")

    async def list_tools(self) -> List[Dict[str, Any]]:
        """Discover tools from the MCP server.

        Returns:
            List of raw MCP tool schema dicts.
        """
        result = await self._transport.send("tools/list")
        tools = result.get("tools", [])
        logger.info("mcp_tools_discovered", server=self._config.name, count=len(tools))
        return tools

    async def invoke(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Invoke an MCP tool.

        Args:
            tool_name: MCP tool name (without prefix).
            arguments: Tool arguments dict.

        Returns:
            Raw MCP tool result dict.
        """
        result = await self._transport.send(
            "tools/call",
            {"name": tool_name, "arguments": arguments},
        )
        return result

    async def disconnect(self) -> None:
        """Disconnect from the MCP server."""
        await self._transport.disconnect()
        logger.info("mcp_client_disconnected", server=self._config.name)

    def close_sync(self) -> None:
        """Synchronous emergency cleanup -- delegates to transport."""
        self._transport.close_sync()
