"""Tests for SdkTransport and KeyringTokenStorage."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from src.integrations.mcp.client import SdkTransport
from src.integrations.mcp.config import McpServerConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(name="test-server", url=None, command=None):
    return McpServerConfig(
        name=name,
        server_url=url,
        command=command,
        connect_timeout=5.0,
        invoke_timeout=10.0,
        tool_prefix=name,
        use_sdk=True,
    )


def _make_mock_session(tools=None):
    """Build a mock SDK ClientSession."""
    from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool

    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    tool_list = tools or [
        Tool(
            name="search_issues",
            description="Search via JQL",
            inputSchema={"type": "object", "properties": {"jql": {"type": "string"}}},
        )
    ]
    session.initialize = AsyncMock(return_value=MagicMock(
        serverInfo=MagicMock(name="test-server", version="1.0"),
        protocolVersion="2025-11-25",
    ))
    session.list_tools = AsyncMock(return_value=ListToolsResult(tools=tool_list))
    session.call_tool = AsyncMock(return_value=CallToolResult(
        content=[TextContent(type="text", text="result ok")],
        isError=False,
    ))
    return session


# ---------------------------------------------------------------------------
# SdkTransport -- remote (SSE URL)
# ---------------------------------------------------------------------------

class TestSdkTransportRemoteSse:

    @pytest.mark.asyncio
    async def test_connect_and_list_tools(self):
        """connect() initialises the SDK session; send('tools/list') returns tools."""
        config = _make_config(url="https://mcp.example.com/v1/sse")
        session = _make_mock_session()
        transport = SdkTransport()

        async def fake_sse_client(url, **kwargs):
            # Simulate async context manager yielding (read, write) streams
            yield (AsyncMock(), AsyncMock())

        with patch("src.integrations.mcp.client.SdkTransport._run_remote_session",
                   new_callable=AsyncMock) as mock_run:
            # Simulate _run_session signalling ready immediately
            async def fake_run(cfg, auth_headers, ready, shutdown):
                transport._session = session
                ready.set()
                await shutdown.wait()
                transport._session = None

            mock_run.side_effect = fake_run

            await transport.connect(config, auth_headers={})
            assert transport.is_connected()

            result = await transport.send("tools/list")
            assert "tools" in result
            assert result["tools"][0]["name"] == "search_issues"

            await transport.disconnect()
            assert not transport.is_connected()

    @pytest.mark.asyncio
    async def test_call_tool(self):
        """send('tools/call') invokes the correct SDK method."""
        config = _make_config(url="https://mcp.example.com/v1/sse")
        session = _make_mock_session()
        transport = SdkTransport()

        with patch("src.integrations.mcp.client.SdkTransport._run_remote_session",
                   new_callable=AsyncMock) as mock_run:
            async def fake_run(cfg, auth_headers, ready, shutdown):
                transport._session = session
                ready.set()
                await shutdown.wait()
                transport._session = None

            mock_run.side_effect = fake_run
            await transport.connect(config, auth_headers={})

            result = await transport.send(
                "tools/call",
                params={"name": "search_issues", "arguments": {"jql": "project=TEST"}},
            )

            session.call_tool.assert_called_once_with(
                name="search_issues",
                arguments={"jql": "project=TEST"},
            )
            assert result["isError"] is False
            assert result["content"][0]["text"] == "result ok"

            await transport.disconnect()

    @pytest.mark.asyncio
    async def test_initialize_is_noop(self):
        """send('initialize') is a no-op -- SDK handles it internally."""
        config = _make_config(url="https://mcp.example.com/v1/sse")
        session = _make_mock_session()
        transport = SdkTransport()

        with patch("src.integrations.mcp.client.SdkTransport._run_remote_session",
                   new_callable=AsyncMock) as mock_run:
            async def fake_run(cfg, auth_headers, ready, shutdown):
                transport._session = session
                ready.set()
                await shutdown.wait()
                transport._session = None

            mock_run.side_effect = fake_run
            await transport.connect(config, auth_headers={})

            result = await transport.send("initialize")
            assert result == {}

            await transport.disconnect()

    @pytest.mark.asyncio
    async def test_connect_timeout(self):
        """connect() raises TimeoutError if session never becomes ready."""
        config = _make_config(url="https://mcp.example.com/v1/sse")
        config.connect_timeout = 0.05  # very short
        transport = SdkTransport()

        with patch("src.integrations.mcp.client.SdkTransport._run_remote_session",
                   new_callable=AsyncMock) as mock_run:
            async def fake_run(cfg, auth_headers, ready, shutdown):
                # Never signals ready
                await asyncio.sleep(10)

            mock_run.side_effect = fake_run

            with pytest.raises(TimeoutError, match="timed out"):
                await transport.connect(config, auth_headers={})

    @pytest.mark.asyncio
    async def test_connect_propagates_session_error(self):
        """If _run_session raises, connect() surfaces the error."""
        config = _make_config(url="https://mcp.example.com/v1/sse")
        transport = SdkTransport()

        with patch("src.integrations.mcp.client.SdkTransport._run_remote_session",
                   new_callable=AsyncMock) as mock_run:
            async def fake_run(cfg, auth_headers, ready, shutdown):
                transport._error = ConnectionError("server refused")
                ready.set()

            mock_run.side_effect = fake_run

            with pytest.raises(ConnectionError, match="server refused"):
                await transport.connect(config, auth_headers={})


# ---------------------------------------------------------------------------
# SdkTransport -- disconnect and close_sync
# ---------------------------------------------------------------------------

class TestSdkTransportLifecycle:

    @pytest.mark.asyncio
    async def test_disconnect_sets_shutdown_event(self):
        """disconnect() signals the background task to exit."""
        config = _make_config(url="https://mcp.example.com/v1/sse")
        session = _make_mock_session()
        transport = SdkTransport()

        shutdown_was_set = False

        with patch("src.integrations.mcp.client.SdkTransport._run_remote_session",
                   new_callable=AsyncMock) as mock_run:
            async def fake_run(cfg, auth_headers, ready, shutdown):
                nonlocal shutdown_was_set
                transport._session = session
                ready.set()
                await shutdown.wait()
                shutdown_was_set = True
                transport._session = None

            mock_run.side_effect = fake_run
            await transport.connect(config, auth_headers={})
            await transport.disconnect()

        assert shutdown_was_set
        assert not transport.is_connected()

    def test_close_sync_cancels_task(self):
        """close_sync() cancels the background task without awaiting."""
        transport = SdkTransport()
        mock_task = MagicMock()
        mock_task.done.return_value = False
        transport._task = mock_task
        transport._session = MagicMock()

        transport.close_sync()

        mock_task.cancel.assert_called_once()
        assert transport._session is None
        assert transport._task is None

    def test_close_sync_handles_no_task(self):
        """close_sync() is safe when called before connect()."""
        transport = SdkTransport()
        transport.close_sync()  # must not raise

    @pytest.mark.asyncio
    async def test_send_raises_when_not_connected(self):
        """send() raises ConnectionError if not connected."""
        transport = SdkTransport()
        with pytest.raises(ConnectionError):
            await transport.send("tools/list")

    @pytest.mark.asyncio
    async def test_send_notification_is_noop(self):
        """send_notification() never raises -- SDK handles notifications internally."""
        transport = SdkTransport()
        await transport.send_notification("notifications/initialized")  # must not raise


# ---------------------------------------------------------------------------
# Manager -- transport selection
# ---------------------------------------------------------------------------

class TestManagerTransportSelection:
    """Verify connect_from_settings() picks the right transport based on use_sdk."""

    @pytest.mark.asyncio
    async def test_use_sdk_true_creates_sdk_transport(self):
        """use_sdk=True -> SdkTransport instantiated."""
        from src.integrations.mcp.manager import McpConnectionManager
        from src.integrations.mcp.settings import McpServerSettings, McpSettingsManager

        settings = McpServerSettings(
            name="rovo",
            server_url="https://mcp.example.com/v1/sse",
            transport="sse",
            use_sdk=True,
            enabled=True,
        )

        manager = McpConnectionManager()

        with patch("src.integrations.mcp.manager.SdkTransport") as MockSdk, \
             patch("src.integrations.mcp.manager.SseTransport") as MockSse, \
             patch("src.integrations.mcp.manager.StdioTransport") as MockStdio, \
             patch("src.integrations.mcp.manager.McpClient") as MockClient, \
             patch("src.integrations.mcp.manager.McpPolicyGate"), \
             patch("src.integrations.mcp.manager.McpToolRegistry"):

            mock_settings_mgr = MagicMock()
            mock_settings_mgr.get_enabled_servers.return_value = [settings]
            mock_settings_mgr.get_tool_filter.return_value = set()
            mock_settings_mgr.merge_discovered_tools.return_value = []

            mock_client_instance = AsyncMock()
            mock_client_instance.is_connected.return_value = True
            MockClient.return_value = mock_client_instance

            mock_registry = AsyncMock()
            mock_registry.discover_and_register = AsyncMock(return_value=(0, []))
            mock_registry._mcp_tool_names = []
            patch("src.integrations.mcp.manager.McpToolRegistry",
                  return_value=mock_registry).start()

            tool_executor = MagicMock()

            await manager.connect_from_settings(mock_settings_mgr, tool_executor)

            MockSdk.assert_called_once()
            MockSse.assert_not_called()
            MockStdio.assert_not_called()

    @pytest.mark.asyncio
    async def test_use_sdk_false_sse_creates_sse_transport(self):
        """use_sdk=False with sse transport -> SseTransport instantiated."""
        from src.integrations.mcp.manager import McpConnectionManager
        from src.integrations.mcp.settings import McpServerSettings

        settings = McpServerSettings(
            name="rovo",
            server_url="https://mcp.example.com/v1/sse",
            transport="sse",
            use_sdk=False,
            enabled=True,
        )

        manager = McpConnectionManager()

        with patch("src.integrations.mcp.manager.SdkTransport") as MockSdk, \
             patch("src.integrations.mcp.manager.SseTransport") as MockSse, \
             patch("src.integrations.mcp.manager.StdioTransport") as MockStdio, \
             patch("src.integrations.mcp.manager.McpClient") as MockClient, \
             patch("src.integrations.mcp.manager.McpPolicyGate"), \
             patch("src.integrations.mcp.manager.McpToolRegistry"):

            mock_settings_mgr = MagicMock()
            mock_settings_mgr.get_enabled_servers.return_value = [settings]
            mock_settings_mgr.get_tool_filter.return_value = set()
            mock_settings_mgr.merge_discovered_tools.return_value = []

            mock_client_instance = AsyncMock()
            MockClient.return_value = mock_client_instance

            mock_registry = AsyncMock()
            mock_registry.discover_and_register = AsyncMock(return_value=(0, []))
            mock_registry._mcp_tool_names = []
            patch("src.integrations.mcp.manager.McpToolRegistry",
                  return_value=mock_registry).start()

            tool_executor = MagicMock()
            await manager.connect_from_settings(mock_settings_mgr, tool_executor)

            MockSdk.assert_not_called()
            MockSse.assert_called_once()
            MockStdio.assert_not_called()


# ---------------------------------------------------------------------------
# Settings -- use_sdk roundtrip
# ---------------------------------------------------------------------------

class TestSettingsUseSdk:

    def test_use_sdk_defaults_true(self):
        """True is the new default -- servers without useSdk in config use the SDK."""
        from src.integrations.mcp.settings import McpServerSettings
        s = McpServerSettings.from_dict("test", {"command": "npx"})
        assert s.use_sdk is True

    def test_use_sdk_false_roundtrip(self):
        """Explicit useSdk=False must survive a to_dict/from_dict round-trip."""
        from src.integrations.mcp.settings import McpServerSettings
        s = McpServerSettings.from_dict("test", {
            "url": "https://mcp.example.com/v1/sse",
            "useSdk": False,
        })
        assert s.use_sdk is False
        d = s.to_dict()
        assert d["useSdk"] is False

    def test_use_sdk_true_not_written_to_dict(self):
        """True is the default -- should not bloat existing config files."""
        from src.integrations.mcp.settings import McpServerSettings
        s = McpServerSettings.from_dict("test", {"command": "npx"})
        d = s.to_dict()
        assert "useSdk" not in d

    def test_use_sdk_false_written_to_dict(self):
        """False is non-default -- must be written so opt-out is preserved."""
        from src.integrations.mcp.settings import McpServerSettings
        s = McpServerSettings.from_dict("test", {"command": "npx", "useSdk": False})
        d = s.to_dict()
        assert d["useSdk"] is False

    def test_use_sdk_passed_to_runtime_config(self):
        from src.integrations.mcp.settings import McpServerSettings
        s = McpServerSettings.from_dict("test", {
            "url": "https://mcp.example.com/v1",
            "useSdk": True,
        })
        config = s.to_runtime_config()
        assert config.use_sdk is True


# ---------------------------------------------------------------------------
# KeyringTokenStorage
# ---------------------------------------------------------------------------

class TestKeyringTokenStorage:

    def _make_storage(self, use_keyring=True):
        from src.integrations.mcp.token_storage import KeyringTokenStorage
        storage = KeyringTokenStorage.__new__(KeyringTokenStorage)
        storage.server_id = "test-server"
        storage._use_keyring = use_keyring
        from src.integrations.mcp.token_storage import _AUTH_DIR
        storage._file_dir = _AUTH_DIR / "test-server"
        return storage

    @pytest.mark.asyncio
    async def test_get_tokens_returns_none_when_empty(self):
        storage = self._make_storage(use_keyring=False)
        with patch.object(storage, "_file_read", return_value=None):
            result = await storage.get_tokens()
        assert result is None

    @pytest.mark.asyncio
    async def test_set_and_get_tokens_file(self):
        from mcp.shared.auth import OAuthToken
        storage = self._make_storage(use_keyring=False)
        token = OAuthToken(access_token="abc123", token_type="Bearer", expires_in=3600)

        written = {}

        def fake_write(key, value):
            written[key] = value

        def fake_read(key):
            return written.get(key)

        with patch.object(storage, "_file_write", side_effect=fake_write), \
             patch.object(storage, "_file_read", side_effect=fake_read):
            await storage.set_tokens(token)
            result = await storage.get_tokens()

        assert result is not None
        assert result.access_token == "abc123"

    @pytest.mark.asyncio
    async def test_set_and_get_tokens_keyring(self):
        from mcp.shared.auth import OAuthToken
        storage = self._make_storage(use_keyring=True)
        token = OAuthToken(access_token="xyz789", token_type="Bearer", expires_in=3600)

        store = {}

        def fake_kr_set(key, value):
            store[key] = value

        def fake_kr_get(key):
            return store.get(key)

        with patch.object(storage, "_kr_set", side_effect=fake_kr_set), \
             patch.object(storage, "_kr_get", side_effect=fake_kr_get):
            await storage.set_tokens(token)
            result = await storage.get_tokens()

        assert result is not None
        assert result.access_token == "xyz789"

    def test_clear_removes_both_keyring_and_file(self):
        storage = self._make_storage(use_keyring=True)
        deleted_kr = []
        deleted_file = []

        with patch.object(storage, "_kr_delete", side_effect=deleted_kr.append), \
             patch.object(storage, "_file_delete", side_effect=deleted_file.append):
            storage.clear()

        assert "tokens" in deleted_kr
        assert "client" in deleted_kr
        assert "tokens" in deleted_file
        assert "client" in deleted_file

    @pytest.mark.asyncio
    async def test_corrupt_token_returns_none(self):
        storage = self._make_storage(use_keyring=False)
        with patch.object(storage, "_file_read", return_value="not valid json"):
            result = await storage.get_tokens()
        assert result is None


# ---------------------------------------------------------------------------
# Bug regression tests
# Each test is marked xfail (expected to fail) until the corresponding fix
# is in place. Once the fix lands the test goes green automatically.
# ---------------------------------------------------------------------------

import stat
import sys

# ---------------------------------------------------------------------------
# Critical 1: Reconnect lifecycle -- stale events after disconnect/reconnect
# ---------------------------------------------------------------------------

class TestReconnectLifecycle:
    """
    BUG: _ready and _shutdown are instance attributes set in connect().
    The background task reads them via self._ready / self._shutdown, so if
    connect() is called a second time it replaces those attributes.  The old
    task then picks up the NEW unset _shutdown event and hangs forever instead
    of exiting cleanly.

    Fix: capture events as locals and pass them into _run_session / _init_session.
    """

    @pytest.mark.asyncio
    async def test_reconnect_does_not_hang(self):
        """_init_session must use the shutdown event captured at start, not self._shutdown.

        The bug: _init_session does `await self._shutdown.wait()`.
        If connect() is called a second time it replaces self._shutdown with a
        new unset Event. Any task that is mid-way through _init_session will
        now await the new unset event and hang forever.

        This test reproduces the bug directly by:
        1. Starting _init_session in a task (it sets _ready then waits on _shutdown).
        2. Simulating a second connect() by replacing self._shutdown with a new Event.
        3. Setting the OLD shutdown event -- the task should exit, but it won't
           because it now waits on the NEW event.
        4. Asserting the task finishes within 0.2 s (it won't, exposing the bug).
        """
        config = _make_config(url="https://mcp.example.com/v1/sse")
        transport = SdkTransport()
        transport._ready = asyncio.Event()
        transport._shutdown = asyncio.Event()

        session = _make_mock_session()

        with patch("mcp.ClientSession", return_value=session):

            ready = asyncio.Event()
            shutdown = asyncio.Event()
            transport._ready = ready
            transport._shutdown = shutdown

            # Start _init_session in a background task using the new signature
            task = asyncio.ensure_future(
                transport._init_session(config, AsyncMock(), AsyncMock(), ready, shutdown)
            )
            # Wait for it to signal ready
            await asyncio.wait_for(ready.wait(), timeout=1.0)

            # Simulate a second connect() replacing self._shutdown with a new Event
            transport._shutdown = asyncio.Event()   # new unset event

            # Signal the ORIGINAL shutdown -- the task must exit because it holds
            # a local reference to the original event, not self._shutdown
            shutdown.set()

            # With the fix: task exits correctly
            try:
                await asyncio.wait_for(task, timeout=0.5)
            except asyncio.TimeoutError:
                task.cancel()
                raise AssertionError(
                    "_init_session hung: it read self._shutdown after connect() replaced it"
                )

    @pytest.mark.asyncio
    async def test_state_is_clean_after_disconnect(self):
        """After disconnect(), _ready/_shutdown/_error/_task should all be None/cleared."""
        config = _make_config(url="https://mcp.example.com/v1/sse")
        session = _make_mock_session()
        transport = SdkTransport()

        async def fake_run(cfg, auth_headers, ready, shutdown):
            transport._session = session
            ready.set()
            await shutdown.wait()
            transport._session = None

        with patch("src.integrations.mcp.client.SdkTransport._run_remote_session",
                   side_effect=fake_run):
            await transport.connect(config, auth_headers={})
            await transport.disconnect()

        # After a clean disconnect all coordination state should be reset
        assert transport._task is None
        assert transport._ready is None
        assert transport._shutdown is None
        assert transport._error is None


# ---------------------------------------------------------------------------
# Critical 1 (part b): connect() does not await task cancellation on timeout
# ---------------------------------------------------------------------------

class TestConnectTimeoutCleanup:
    """
    BUG: On timeout connect() calls self._task.cancel() but does not await it.
    The cancelled task is still referenced in self._task, leaving stale state.

    Fix: after cancel(), await the task (suppressing CancelledError) and clear
    _task, _ready, _shutdown.
    """

    @pytest.mark.asyncio
    async def test_timeout_leaves_no_stale_task(self):
        """After a connect timeout, _task must be None."""
        config = _make_config(url="https://mcp.example.com/v1/sse")
        config.connect_timeout = 0.05
        transport = SdkTransport()

        with patch("src.integrations.mcp.client.SdkTransport._run_remote_session",
                   new_callable=AsyncMock) as mock_run:
            async def fake_run(cfg, auth_headers, ready, shutdown):
                await asyncio.sleep(10)  # never signals ready

            mock_run.side_effect = fake_run

            with pytest.raises(TimeoutError):
                await transport.connect(config, auth_headers={})

        # Allow cancellation to propagate
        await asyncio.sleep(0.1)
        assert transport._task is None
        assert transport._ready is None
        assert transport._shutdown is None


# ---------------------------------------------------------------------------
# Critical 2: Windows stdio command parsing
# ---------------------------------------------------------------------------

class TestWindowsStdioCommandParsing:
    """
    BUG: _run_stdio_session() calls subprocess.list2cmdline([config.command]).split()
    on Windows. list2cmdline adds quoting; .split() does not understand Windows
    quoting semantics. A command with a space in the path (e.g. C:\\Program Files\\...)
    is split incorrectly.

    Fix: preserve command and args separately, pass directly to StdioServerParameters.
    """

    @pytest.mark.asyncio
    async def test_stdio_command_with_space_in_path(self):
        """A command path containing a space must be passed intact to StdioServerParameters."""
        config = _make_config(command=r"C:\Program Files\my server\mcp.exe")
        transport = SdkTransport()
        captured_params = []
        ready, shutdown = asyncio.Event(), asyncio.Event()

        # stdio_client is used as `async with stdio_client(params) as (r, w):`
        # so the mock must be a callable returning an async context manager.
        class _FakeCtx:
            def __init__(self_, params):
                captured_params.append(params)
            async def __aenter__(self_):
                return (AsyncMock(), AsyncMock())
            async def __aexit__(self_, *a):
                pass

        with patch("mcp.client.stdio.stdio_client", side_effect=_FakeCtx), \
             patch.object(transport, "_init_session", new_callable=AsyncMock):
            await transport._run_stdio_session(config, ready, shutdown)

        assert len(captured_params) == 1
        assert captured_params[0].command == r"C:\Program Files\my server\mcp.exe"
        assert captured_params[0].args == []

    @pytest.mark.asyncio
    async def test_stdio_args_preserved(self):
        """Args provided alongside a command must reach StdioServerParameters unchanged."""
        from src.integrations.mcp.config import McpServerConfig

        config = McpServerConfig(
            name="local",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-github"],
            connect_timeout=5.0,
            invoke_timeout=10.0,
            tool_prefix="local",
            use_sdk=True,
        )
        transport = SdkTransport()
        captured_params = []
        ready, shutdown = asyncio.Event(), asyncio.Event()

        class _FakeCtx:
            def __init__(self_, params):
                captured_params.append(params)
            async def __aenter__(self_):
                return (AsyncMock(), AsyncMock())
            async def __aexit__(self_, *a):
                pass

        with patch("mcp.client.stdio.stdio_client", side_effect=_FakeCtx), \
             patch.object(transport, "_init_session", new_callable=AsyncMock):
            await transport._run_stdio_session(config, ready, shutdown)

        assert len(captured_params) == 1
        assert captured_params[0].command == "npx"
        assert captured_params[0].args == ["-y", "@modelcontextprotocol/server-github"]


# ---------------------------------------------------------------------------
# Critical 3: File fallback directory permissions
# ---------------------------------------------------------------------------

class TestFileDirectoryPermissions:
    """
    BUG: _file_write() calls self._file_dir.mkdir() with default umask, then
    only restricts the *file* to 600. The directory itself is left with default
    permissions (typically 755), weaker than the claimed 'owner-only' protection.

    Fix: chmod the directory to 0o700 after mkdir() on non-Windows.
    """

    @pytest.mark.skipif(sys.platform == "win32", reason="chmod semantics are Unix-only")
    def test_file_directory_created_with_owner_only_permissions(self, tmp_path):
        """The mcp_auth/<server_id> directory must be created with mode 0o700."""
        from src.integrations.mcp.token_storage import KeyringTokenStorage

        storage = KeyringTokenStorage.__new__(KeyringTokenStorage)
        storage.server_id = "test-server"
        storage._use_keyring = False
        storage._file_dir = tmp_path / "mcp_auth" / "test-server"

        storage._file_write("tokens", '{"access_token": "x", "token_type": "Bearer"}')

        dir_mode = storage._file_dir.stat().st_mode & 0o777
        assert dir_mode == 0o700, (
            f"Expected directory mode 0o700, got 0o{dir_mode:03o}. "
            "Directory must be owner-only to protect token files."
        )

    @pytest.mark.skipif(sys.platform == "win32", reason="chmod semantics are Unix-only")
    def test_token_file_created_with_owner_only_permissions(self, tmp_path):
        """Token files must already be 0o600 -- this one should already pass."""
        from src.integrations.mcp.token_storage import KeyringTokenStorage

        storage = KeyringTokenStorage.__new__(KeyringTokenStorage)
        storage.server_id = "test-server"
        storage._use_keyring = False
        storage._file_dir = tmp_path / "mcp_auth" / "test-server"

        storage._file_write("tokens", '{"access_token": "x", "token_type": "Bearer"}')

        file_path = storage._file_dir / "tokens.json"
        file_mode = file_path.stat().st_mode & 0o777
        assert file_mode == 0o600, f"Expected file mode 0o600, got 0o{file_mode:03o}"


# ---------------------------------------------------------------------------
# Important 2: OAuth callback port conflict
# ---------------------------------------------------------------------------

class TestOAuthCallbackPortConflict:
    """
    BUG: _oauth_callback_handler() always binds to port 8765. If another
    process already holds that port the bind fails with OSError, but the
    error message gives no hint about the cause.

    Fix: catch OSError on bind and raise a descriptive error, or use port=0
    and construct the redirect URI dynamically.
    """

    @pytest.mark.asyncio
    async def test_port_conflict_raises_descriptive_error(self):
        """When asyncio.start_server fails, the error must mention MCP OAuth context."""
        transport = SdkTransport()

        with patch("asyncio.start_server", side_effect=OSError("address already in use")):
            with pytest.raises(OSError, match="(?i)oauth|callback"):
                await transport._start_oauth_callback_server()


# ---------------------------------------------------------------------------
# Important 3: writer.close() not awaited in OAuth callback handler
# ---------------------------------------------------------------------------

class TestOAuthCallbackWriterClose:
    """
    BUG: _oauth_callback_handler._handle() calls writer.close() but never
    awaits writer.wait_closed(). On some event loops this leaves transport
    cleanup pending.

    Fix: add `await writer.wait_closed()` in a suppressed block after close().
    """

    @pytest.mark.asyncio
    async def test_writer_wait_closed_is_called(self):
        """The callback _handle must await writer.wait_closed() after writer.close()."""
        transport = SdkTransport()

        writer = AsyncMock()
        writer.close = MagicMock()
        writer.wait_closed = AsyncMock()

        reader = AsyncMock()
        reader.readline = AsyncMock(
            return_value=b"GET /callback?code=abc123&state=xyz HTTP/1.1\r\n"
        )

        # Capture the _handle coroutine by intercepting start_server
        handle_fn_holder = {}

        async def fake_start_server(handler, host, port):
            handle_fn_holder["fn"] = handler
            server = MagicMock()
            server.sockets = [MagicMock()]
            server.sockets[0].getsockname.return_value = ("localhost", 12345)
            return server

        with patch("asyncio.start_server", side_effect=fake_start_server):
            _, _ = await transport._start_oauth_callback_server()

        assert "fn" in handle_fn_holder, "_start_oauth_callback_server did not register a handler"

        # Invoke the captured handler directly
        await handle_fn_holder["fn"](reader, writer)

        writer.close.assert_called_once()
        writer.wait_closed.assert_awaited_once()
