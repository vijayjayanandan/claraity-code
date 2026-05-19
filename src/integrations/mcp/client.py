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
from typing import Any, Optional

from .config import McpServerConfig

try:
    from src.observability import get_logger

    logger = get_logger("integrations.mcp.client")
except ImportError:
    logger = logging.getLogger(__name__)


class McpTransport(ABC):
    """Abstract transport for MCP JSON-RPC communication."""

    @abstractmethod
    async def connect(self, config: McpServerConfig, auth_headers: dict[str, str]) -> None:
        """Establish connection. auth_headers are ephemeral (not stored)."""

    @abstractmethod
    async def send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send a JSON-RPC request and return the result."""

    @abstractmethod
    async def send_notification(self, method: str, params: dict[str, Any] | None = None) -> None:
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
        return  # no-op default


class SseTransport(McpTransport):
    """SSE (Server-Sent Events) transport for remote MCP servers.

    Auth tokens are injected per-request (not stored on the client) to
    minimize the window where secrets live in memory.
    """

    def __init__(self):
        self._client = None
        self._base_url: str | None = None
        self._base_headers: dict[str, str] = {}  # Non-secret headers only
        self._auth_headers: dict[
            str, str
        ] = {}  # Per-request auth; set at connect, cleared at disconnect
        self._connected = False

    async def connect(self, config: McpServerConfig, auth_headers: dict[str, str]) -> None:
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

    async def send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._client or not self._base_url:
            raise ConnectionError("SSE transport not connected")

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or {},
        }

        # Inject auth per-request (not stored on httpx client)
        response = await self._client.post(self._base_url, json=payload, headers=self._auth_headers)
        response.raise_for_status()
        result = response.json()

        if "error" in result:
            error = result["error"]
            raise McpError(
                code=error.get("code", -1),
                message=error.get("message", "Unknown MCP error"),
            )

        return result.get("result", {})

    async def send_notification(self, method: str, params: dict[str, Any] | None = None) -> None:
        if not self._client or not self._base_url:
            raise ConnectionError("SSE transport not connected")

        payload = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params:
            payload["params"] = params

        await self._client.post(self._base_url, json=payload, headers=self._auth_headers)

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
        self._send_lock: asyncio.Lock | None = None  # created at connect time
        self._stderr_task: asyncio.Task | None = None  # drains stderr to prevent deadlock

    async def connect(self, config: McpServerConfig, auth_headers: dict[str, str]) -> None:
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
            import subprocess

            full_cmd = subprocess.list2cmdline([config.command] + (config.args or []))
            self._process = await asyncio.create_subprocess_shell(
                full_cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        else:
            self._process = await asyncio.create_subprocess_exec(
                config.command,
                *(config.args or []),
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

    async def send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
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

    async def send_notification(self, method: str, params: dict[str, Any] | None = None) -> None:
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
            subprocess_transport = getattr(self._process, "_transport", None)
            if subprocess_transport is not None:
                # Prevent BaseSubprocessTransport.__del__ -> close() -> loop.call_soon
                subprocess_transport._closed = True

                # Neutralize each pipe transport (_ProactorBasePipeTransport)
                for proto in getattr(subprocess_transport, "_pipes", {}).values():
                    pipe_transport = getattr(proto, "pipe", None)
                    if pipe_transport is not None:
                        # Close the OS-level pipe handle
                        sock = getattr(pipe_transport, "_sock", None)
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
        auth_headers: dict[str, str] = {}

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
        init_result = await self._transport.send(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"roots": {}, "sampling": {}},
                "clientInfo": {"name": "claraity-agent", "version": "1.0.0"},
            },
        )

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

    async def list_tools(self) -> list[dict[str, Any]]:
        """Discover tools from the MCP server.

        Returns:
            list of raw MCP tool schema dicts.
        """
        result = await self._transport.send("tools/list")
        tools = result.get("tools", [])
        logger.info("mcp_tools_discovered", server=self._config.name, count=len(tools))
        return tools

    async def invoke(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
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


class SdkTransport(McpTransport):
    """MCP transport using the official MCP Python SDK.

    Supports both remote (URL-based) and local (stdio/subprocess) servers.
    The mode is determined by which field is set on McpServerConfig:
        config.server_url set  -> streamablehttp_client (or sse_client for /sse URLs)
        config.command set     -> stdio_client

    Lifecycle:
        A background asyncio Task holds the SDK's async-with context manager open
        for the entire connection lifetime. Two asyncio.Events coordinate:
          _ready    -- set when session.initialize() completes (connect() unblocks)
          _shutdown -- set when disconnect() is called (task exits the with block)

    Auth (remote servers):
        OAuthClientProvider is constructed at connect() time using KeyringTokenStorage.
        Tokens are stored in the OS keyring (Windows Credential Manager / macOS
        Keychain) with a file fallback to ~/.claraity/mcp_auth/<server_name>/.
        On first connect, a browser flow opens for user login. Subsequent connects
        reuse the cached token silently.
    """

    def __init__(self):
        self._session = None
        self._task: asyncio.Task | None = None
        self._ready: asyncio.Event | None = None
        self._shutdown: asyncio.Event | None = None
        self._error: Exception | None = None

    async def connect(self, config: McpServerConfig, auth_headers: dict[str, str]) -> None:
        # Capture events as locals -- passed into the background task so it always
        # waits on the original events, not whatever is currently on self after a
        # reconnect replaces them.
        ready = asyncio.Event()
        shutdown = asyncio.Event()
        self._ready = ready
        self._shutdown = shutdown
        self._error = None

        self._task = asyncio.ensure_future(
            self._run_session(config, auth_headers, ready, shutdown)
        )

        # Wait until the session is initialised or an error occurs
        try:
            await asyncio.wait_for(ready.wait(), timeout=config.connect_timeout)
        except asyncio.TimeoutError:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
            self._ready = None
            self._shutdown = None
            raise TimeoutError(
                f"SDK transport: timed out connecting to '{config.name}' "
                f"after {config.connect_timeout}s"
            )

        if self._error:
            raise self._error

    async def _run_session(
        self,
        config: McpServerConfig,
        auth_headers: dict[str, str],
        ready: asyncio.Event,
        shutdown: asyncio.Event,
    ) -> None:
        """Background task: opens the SDK context and holds it open until disconnect()."""
        try:
            if config.server_url:
                await self._run_remote_session(config, auth_headers, ready, shutdown)
            else:
                await self._run_stdio_session(config, ready, shutdown)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self._error = e
            ready.set()  # unblock connect() so it can raise
        finally:
            self._session = None

    async def _run_remote_session(
        self,
        config: McpServerConfig,
        auth_headers: dict[str, str],
        ready: asyncio.Event,
        shutdown: asyncio.Event,
    ) -> None:
        """Open a remote SDK session (SSE or streamable HTTP)."""
        from mcp.client.auth import OAuthClientProvider
        from mcp.shared.auth import OAuthClientMetadata

        from .token_storage import KeyringTokenStorage

        # Build auth -- OAuth if no static headers provided, otherwise Bearer
        if auth_headers:
            # Static API key auth -- pass directly as headers
            auth = None
            headers = dict(auth_headers)
        else:
            # OAuth 2.1 -- SDK handles the full flow.
            # The redirect URI MUST match what was registered with the OAuth server.
            # Strategy:
            #   1. Read the previously registered port from stored client_info.
            #   2. Try to bind to that same port so the URI stays stable.
            #   3. If that port is busy, bind to a new port and clear stale
            #      client_info -- forces re-registration with the new URI.
            #   4. No prior registration -- bind to any available port.
            storage = KeyringTokenStorage(server_id=config.name)

            # Determine the preferred port from prior registration
            preferred_port = 0
            existing_client = await storage.get_client_info()
            if existing_client and existing_client.redirect_uris:
                from urllib.parse import urlparse as _urlparse
                parsed = _urlparse(str(existing_client.redirect_uris[0]))
                if parsed.port:
                    preferred_port = parsed.port

            callback_server, callback_future = await self._start_oauth_callback_server(
                preferred_port=preferred_port
            )
            actual_port = callback_server.sockets[0].getsockname()[1]
            redirect_uri = f"http://localhost:{actual_port}/callback"

            # If we got a different port than registered, the old client_id is now
            # invalid -- clear it so the SDK re-registers with the new URI.
            if preferred_port and actual_port != preferred_port:
                logger.info(
                    "mcp_oauth_port_changed_clearing_client",
                    server=config.name,
                    registered_port=preferred_port,
                    actual_port=actual_port,
                )
                storage.clear()

            oauth_metadata = OAuthClientMetadata(
                client_name="ClarAIty",
                redirect_uris=[redirect_uri],
                grant_types=["authorization_code", "refresh_token"],
                response_types=["code"],
                token_endpoint_auth_method="none",
            )
            auth = OAuthClientProvider(
                server_url=config.server_url,
                client_metadata=oauth_metadata,
                storage=storage,
                redirect_handler=self._oauth_redirect_handler,
                callback_handler=lambda: self._await_oauth_callback(callback_server, callback_future),
                timeout=300.0,
            )
            headers = dict(config.extra_headers)

        # SSE endpoint vs streamable HTTP -- detected from URL suffix
        if config.server_url.rstrip("/").endswith("/sse"):
            from mcp.client.sse import sse_client
            ctx = sse_client(
                url=config.server_url,
                auth=auth,
                headers=headers or None,
                timeout=config.connect_timeout,
            )
            async with ctx as (read_stream, write_stream):
                await self._init_session(config, read_stream, write_stream, ready, shutdown)
        else:
            from mcp.client.streamable_http import streamablehttp_client
            ctx = streamablehttp_client(
                url=config.server_url,
                auth=auth,
                headers=headers or None,
                timeout=config.connect_timeout,
            )
            async with ctx as (read_stream, write_stream, _):
                await self._init_session(config, read_stream, write_stream, ready, shutdown)

    async def _run_stdio_session(
        self, config: McpServerConfig, ready: asyncio.Event, shutdown: asyncio.Event
    ) -> None:
        """Open a local stdio SDK session."""
        from mcp.client.stdio import StdioServerParameters, stdio_client

        if not config.command:
            raise ValueError(f"SDK stdio: no command configured for server '{config.name}'")

        # Use command and args directly from config -- no string splitting.
        # Splitting is lossy on Windows (paths with spaces break).
        params = StdioServerParameters(
            command=config.command,
            args=config.args or [],
            env=config.extra_env if config.extra_env else None,
        )

        async with stdio_client(params) as (read_stream, write_stream):
            await self._init_session(config, read_stream, write_stream, ready, shutdown)

    async def _init_session(
        self,
        config,
        read_stream,
        write_stream,
        ready: asyncio.Event,
        shutdown: asyncio.Event,
    ) -> None:
        """Shared: initialise ClientSession, signal ready, wait for shutdown.

        Events are passed as parameters (not read from self) so that a reconnect
        that replaces self._ready / self._shutdown does not affect a running task.
        """
        from mcp import ClientSession as SdkClientSession

        async with SdkClientSession(read_stream, write_stream) as session:
            await session.initialize()
            self._session = session
            logger.info("sdk_transport_connected", server=config.name)
            ready.set()           # unblock connect() -- uses local, not self._ready
            await shutdown.wait() # hold open until disconnect() -- uses local
            self._session = None

    # -- OAuth browser flow callbacks --

    async def _oauth_redirect_handler(self, url: str) -> None:
        """Open browser for OAuth login."""
        import webbrowser
        logger.info("mcp_oauth_browser_open", url=url)
        try:
            webbrowser.open(url)
        except Exception:
            logger.warning("mcp_oauth_browser_open_failed", url=url)

    async def _start_oauth_callback_server(self, preferred_port: int = 0):
        """Start a local HTTP server for OAuth redirect.

        Tries preferred_port first (for URI stability across reconnects).
        Falls back to OS-assigned port (port=0) if preferred is in use.

        Returns (server, future) where:
          server -- asyncio.Server bound to the actual port
          future -- resolves to (code, state) when the browser redirect arrives

        The actual port is: server.sockets[0].getsockname()[1]
        """
        from urllib.parse import parse_qs, urlparse

        result_future: asyncio.Future = asyncio.get_event_loop().create_future()

        async def _handle(reader, writer):
            try:
                line = await asyncio.wait_for(reader.readline(), timeout=10.0)
                text = line.decode("utf-8", errors="replace").strip()
                parts = text.split(" ")
                path = parts[1] if len(parts) >= 2 else "/"
                params = parse_qs(urlparse(path).query)
                code = params.get("code", [None])[0]
                state = params.get("state", [None])[0]

                html = (
                    "<html><body style='font-family:sans-serif;padding:40px'>"
                    "<h2>Login successful!</h2>"
                    "<p>You can close this tab and return to ClarAIty.</p>"
                    "</body></html>"
                ) if code else (
                    "<html><body style='font-family:sans-serif;padding:40px'>"
                    "<h2>Something went wrong</h2>"
                    "<p>No authorization code received.</p>"
                    "</body></html>"
                )
                status = "200 OK" if code else "400 Bad Request"
                response = (
                    f"HTTP/1.1 {status}\r\nContent-Type: text/html\r\n"
                    f"Content-Length: {len(html)}\r\nConnection: close\r\n\r\n{html}"
                )
                writer.write(response.encode("utf-8"))
                await writer.drain()

                if not result_future.done():
                    if code:
                        result_future.set_result((code, state))
                    else:
                        result_future.set_exception(
                            ValueError("No authorization code in OAuth callback")
                        )
            except Exception as e:
                if not result_future.done():
                    result_future.set_exception(e)
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass

        # Try preferred port first for URI stability across reconnects.
        # If it is already in use by another process, fall back to OS-assigned (port=0).
        server = None
        for port in ([preferred_port] if preferred_port else []) + [0]:
            try:
                server = await asyncio.start_server(_handle, host="localhost", port=port)
                break
            except OSError:
                continue
        if server is None:
            raise OSError("MCP OAuth callback server failed to bind to any port.")

        return server, result_future

    async def _await_oauth_callback(self, server, result_future) -> tuple[str, str | None]:
        """Wait for the OAuth browser redirect to arrive and return (code, state)."""
        async with server:
            code, state = await asyncio.wait_for(result_future, timeout=300.0)
        logger.info("mcp_oauth_callback_received", server="sdk")
        return code, state

    # -- McpTransport interface --

    async def send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._session:
            raise ConnectionError("SDK transport not connected")

        if method == "initialize":
            # SDK handles initialize internally during connect -- no-op here
            return {}

        elif method == "tools/list":
            result = await self._session.list_tools()
            tools = [t.model_dump() for t in (result.tools or []) if t is not None]
            return {"tools": tools}

        elif method == "tools/call":
            if not params:
                raise ValueError("tools/call requires params")
            result = await self._session.call_tool(
                name=params["name"],
                arguments=params.get("arguments", {}),
            )
            return {
                "content": [c.model_dump() for c in result.content],
                "isError": result.isError or False,
            }

        else:
            raise NotImplementedError(f"SDK transport: unsupported method '{method}'")

    async def send_notification(self, method: str, params: dict[str, Any] | None = None) -> None:
        # SDK handles protocol notifications (initialized, etc.) internally
        pass

    async def disconnect(self) -> None:
        if self._shutdown:
            self._shutdown.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                pass
            self._task = None
        self._session = None
        self._ready = None
        self._shutdown = None
        self._error = None
        logger.info("sdk_transport_disconnected")

    def is_connected(self) -> bool:
        return self._session is not None

    def close_sync(self) -> None:
        """Best-effort emergency shutdown -- cancels background task."""
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None
        self._session = None
