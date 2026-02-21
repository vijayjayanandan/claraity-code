"""Tests for MCP connection lifecycle manager."""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.integrations.mcp.client import McpClient, McpTransport
from src.integrations.mcp.config import McpServerConfig
from src.integrations.mcp.manager import McpConnectionManager, McpConnection
from src.integrations.mcp.policy import McpPolicyGate
from src.integrations.mcp.registry import McpToolRegistry
from src.tools.base import ToolExecutor, ToolStatus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_mock_transport(tool_schemas=None):
    """Create a mock transport that returns predefined tool schemas."""
    transport = AsyncMock(spec=McpTransport)
    transport.is_connected.return_value = True
    transport.close_sync = MagicMock()  # sync method, not async

    tools = tool_schemas or [
        {
            "name": "search_issues",
            "description": "Search via JQL",
            "inputSchema": {
                "type": "object",
                "properties": {"jql": {"type": "string"}},
                "required": ["jql"],
            },
            "annotations": {"readOnlyHint": True, "destructiveHint": False},
        },
        {
            "name": "create_issue",
            "description": "Create a new issue",
            "inputSchema": {
                "type": "object",
                "properties": {"summary": {"type": "string"}},
                "required": ["summary"],
            },
            "annotations": {"readOnlyHint": False, "destructiveHint": False},
        },
    ]

    async def mock_send(method, params=None):
        if method == "tools/list":
            return {"tools": tools}
        elif method == "tools/call":
            return {
                "content": [{"type": "text", "text": "ok"}],
                "isError": False,
            }
        return {}

    transport.send.side_effect = mock_send
    return transport


@pytest.fixture
def config():
    return McpServerConfig(
        name="test-server",
        tool_prefix="jira",
        cache_ttl_seconds=3600.0,
    )


@pytest.fixture
def manager():
    return McpConnectionManager()


@pytest.fixture
def tool_executor():
    return ToolExecutor()


async def _connect_jira(manager, config, tool_executor, transport=None):
    """Helper to connect a 'jira' MCP server to the manager."""
    transport = transport or _make_mock_transport()
    client = McpClient(config, transport)
    policy_gate = McpPolicyGate()
    registry = McpToolRegistry(config, policy_gate)
    count = await manager.connect(
        name="jira",
        config=config,
        client=client,
        registry=registry,
        tool_executor=tool_executor,
    )
    return count, client, registry


# ---------------------------------------------------------------------------
# Connect / disconnect
# ---------------------------------------------------------------------------

class TestConnect:
    @pytest.mark.asyncio
    async def test_connect_registers_tools(self, manager, config, tool_executor):
        count, _, _ = await _connect_jira(manager, config, tool_executor)
        assert count == 2
        assert manager.has_connections
        assert "jira" in manager.connection_names

    @pytest.mark.asyncio
    async def test_connect_stores_tool_names(self, manager, config, tool_executor):
        await _connect_jira(manager, config, tool_executor)
        conn = manager.get_connection("jira")
        assert "jira_search_issues" in conn.tool_names
        assert "jira_create_issue" in conn.tool_names

    @pytest.mark.asyncio
    async def test_duplicate_connection_raises(self, manager, config, tool_executor):
        await _connect_jira(manager, config, tool_executor)
        with pytest.raises(ValueError, match="already exists"):
            await _connect_jira(manager, config, tool_executor)

    @pytest.mark.asyncio
    async def test_disconnect_clears_tools(self, manager, config, tool_executor):
        await _connect_jira(manager, config, tool_executor)
        assert "jira_search_issues" in tool_executor.tools

        await manager.disconnect("jira", tool_executor)

        assert not manager.has_connections
        assert "jira_search_issues" not in tool_executor.tools
        assert "jira_create_issue" not in tool_executor.tools

    @pytest.mark.asyncio
    async def test_disconnect_unknown_raises(self, manager):
        with pytest.raises(KeyError):
            await manager.disconnect("nonexistent")

    @pytest.mark.asyncio
    async def test_reconnect_after_disconnect(self, manager, config, tool_executor):
        await _connect_jira(manager, config, tool_executor)
        await manager.disconnect("jira", tool_executor)
        count, _, _ = await _connect_jira(manager, config, tool_executor)
        assert count == 2
        assert manager.has_connections


# ---------------------------------------------------------------------------
# Shutdown
# ---------------------------------------------------------------------------

class TestShutdown:
    @pytest.mark.asyncio
    async def test_shutdown_disconnects_all(self, manager, config, tool_executor):
        await _connect_jira(manager, config, tool_executor)

        # Add a second connection
        config2 = McpServerConfig(name="github-server", tool_prefix="gh", cache_ttl_seconds=3600.0)
        transport2 = _make_mock_transport([
            {
                "name": "list_repos",
                "description": "List repos",
                "inputSchema": {"type": "object", "properties": {}},
                "annotations": {"readOnlyHint": True, "destructiveHint": False},
            },
        ])
        client2 = McpClient(config2, transport2)
        registry2 = McpToolRegistry(config2, McpPolicyGate())
        await manager.connect("github", config2, client2, registry2, tool_executor)

        assert len(manager.connection_names) == 2
        await manager.shutdown(tool_executor)
        assert not manager.has_connections
        assert "jira_search_issues" not in tool_executor.tools
        assert "gh_list_repos" not in tool_executor.tools

    @pytest.mark.asyncio
    async def test_shutdown_sync_kills_process(self, manager, config, tool_executor):
        transport = _make_mock_transport()
        await _connect_jira(manager, config, tool_executor, transport=transport)

        manager.shutdown_sync()

        assert not manager.has_connections
        transport.close_sync.assert_called_once()


class TestStdioCloseSyncNeutralizesTransports:
    """Verify StdioTransport.close_sync() neutralizes asyncio internals.

    On Windows, asyncio transport __del__ methods try to use the event loop.
    If the loop is closed, this raises RuntimeError. close_sync() must set
    internal flags to prevent these __del__ errors.
    """

    def test_neutralizes_subprocess_transport(self):
        """BaseSubprocessTransport._closed should be set True."""
        from src.integrations.mcp.client import StdioTransport

        # Build a mock that mirrors asyncio internal structure:
        # process._transport._pipes = {0: proto} where proto.pipe = pipe_transport
        pipe_sock = MagicMock()
        pipe_transport = MagicMock()
        pipe_transport._sock = pipe_sock
        pipe_transport._closing = False

        proto = MagicMock()
        proto.pipe = pipe_transport

        subprocess_transport = MagicMock()
        subprocess_transport._closed = False
        subprocess_transport._pipes = {0: proto}

        mock_process = MagicMock()
        mock_process._transport = subprocess_transport

        transport = StdioTransport()
        transport._process = mock_process
        transport._connected = True

        transport.close_sync()

        # BaseSubprocessTransport neutralized
        assert subprocess_transport._closed is True
        # Pipe transport neutralized
        assert pipe_transport._closing is True
        assert pipe_transport._sock is None
        # OS handle closed
        pipe_sock.close.assert_called_once()
        # Process killed
        mock_process.kill.assert_called_once()
        assert transport._process is None
        assert transport._connected is False

    def test_handles_missing_transport_gracefully(self):
        """close_sync() works even if _transport attr is missing."""
        from src.integrations.mcp.client import StdioTransport

        mock_process = MagicMock(spec=[])  # no _transport attr
        mock_process.kill = MagicMock()

        transport = StdioTransport()
        transport._process = mock_process
        transport._connected = True

        # Should not raise
        transport.close_sync()
        assert transport._process is None
        assert transport._connected is False


# ---------------------------------------------------------------------------
# Tool routing
# ---------------------------------------------------------------------------

class TestToolRouting:
    @pytest.mark.asyncio
    async def test_is_mcp_tool(self, manager, config, tool_executor):
        await _connect_jira(manager, config, tool_executor)
        assert manager.is_mcp_tool("jira_search_issues") is True
        assert manager.is_mcp_tool("jira_create_issue") is True
        assert manager.is_mcp_tool("read_file") is False

    @pytest.mark.asyncio
    async def test_requires_approval_read_tool(self, manager, config, tool_executor):
        await _connect_jira(manager, config, tool_executor)
        # search_issues has readOnlyHint=True -> no approval
        assert manager.requires_approval("jira_search_issues") is False

    @pytest.mark.asyncio
    async def test_requires_approval_write_tool(self, manager, config, tool_executor):
        await _connect_jira(manager, config, tool_executor)
        # create_issue has readOnlyHint=False -> approval required
        assert manager.requires_approval("jira_create_issue") is True

    @pytest.mark.asyncio
    async def test_requires_approval_unknown_tool(self, manager):
        # Unknown tool -> True (safety default)
        assert manager.requires_approval("unknown_tool") is True

    @pytest.mark.asyncio
    async def test_get_all_tool_definitions(self, manager, config, tool_executor):
        await _connect_jira(manager, config, tool_executor)
        defs = manager.get_all_tool_definitions()
        names = [d.name for d in defs]
        assert "jira_search_issues" in names
        assert "jira_create_issue" in names

    @pytest.mark.asyncio
    async def test_aggregates_across_connections(self, manager, config, tool_executor):
        await _connect_jira(manager, config, tool_executor)

        # Add second connection
        config2 = McpServerConfig(name="gh-server", tool_prefix="gh", cache_ttl_seconds=3600.0)
        transport2 = _make_mock_transport([
            {
                "name": "list_prs",
                "description": "List PRs",
                "inputSchema": {"type": "object", "properties": {}},
                "annotations": {"readOnlyHint": True, "destructiveHint": False},
            },
        ])
        client2 = McpClient(config2, transport2)
        registry2 = McpToolRegistry(config2, McpPolicyGate())
        await manager.connect("github", config2, client2, registry2, tool_executor)

        defs = manager.get_all_tool_definitions()
        names = [d.name for d in defs]
        assert "jira_search_issues" in names
        assert "gh_list_prs" in names

        assert manager.is_mcp_tool("jira_search_issues")
        assert manager.is_mcp_tool("gh_list_prs")
        assert not manager.is_mcp_tool("read_file")


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------

class TestProperties:
    def test_empty_manager(self, manager):
        assert not manager.has_connections
        assert manager.connection_names == []
        assert manager.get_all_tool_definitions() == []
        assert not manager.is_mcp_tool("anything")

    @pytest.mark.asyncio
    async def test_get_connection(self, manager, config, tool_executor):
        await _connect_jira(manager, config, tool_executor)
        conn = manager.get_connection("jira")
        assert conn is not None
        assert conn.name == "jira"
        assert manager.get_connection("nonexistent") is None


# ---------------------------------------------------------------------------
# Regression: _get_tools() must not produce duplicate tool names
# ---------------------------------------------------------------------------

class TestGetToolsNoDuplicates:
    """Regression test for duplicate MCP tool names sent to LLM API.

    MCP bridge tools are registered in ToolExecutor (for execution) AND
    returned by McpConnectionManager.get_all_tool_definitions() (for schemas).
    CodingAgent._get_tools() must not include them twice.

    Bug introduced in 1a9a0b3 when _get_tools() switched from static
    ALL_TOOLS to tool_executor.tools.values() without filtering bridge tools.
    """

    @pytest.mark.asyncio
    async def test_no_duplicate_tool_names_with_mcp(self):
        """_get_tools() returns unique tool names when MCP is connected."""
        import os
        from src.core.agent import CodingAgent

        agent = CodingAgent(
            backend="openai",
            model_name="test-model",
            base_url="http://localhost:1234",
            api_key="sk-test",
            context_window=8000,
            embedding_api_key="sk-test",
            embedding_base_url="http://localhost:1234",
            load_file_memories=False,
        )

        # Connect a mock MCP server (reuse existing helpers)
        config = McpServerConfig(
            name="test-jira", tool_prefix="jira", cache_ttl_seconds=3600.0,
        )
        transport = _make_mock_transport()
        client = McpClient(config, transport)
        policy_gate = McpPolicyGate()
        registry = McpToolRegistry(config, policy_gate)

        await agent._mcp_manager.connect(
            name="jira",
            config=config,
            client=client,
            registry=registry,
            tool_executor=agent.tool_executor,
        )

        tools = agent._get_tools()
        names = [t.name for t in tools]

        # Core assertion: no duplicates
        assert len(names) == len(set(names)), (
            f"Duplicate tool names sent to LLM API: "
            f"{[n for n in names if names.count(n) > 1]}"
        )

        # MCP tools should be present exactly once
        assert names.count("jira_search_issues") == 1
        assert names.count("jira_create_issue") == 1

    @pytest.mark.asyncio
    async def test_no_duplicates_with_multiple_mcp_connections(self):
        """_get_tools() stays unique with multiple MCP servers connected."""
        from src.core.agent import CodingAgent

        agent = CodingAgent(
            backend="openai",
            model_name="test-model",
            base_url="http://localhost:1234",
            api_key="sk-test",
            context_window=8000,
            embedding_api_key="sk-test",
            embedding_base_url="http://localhost:1234",
            load_file_memories=False,
        )

        # Connect first MCP server (jira)
        config1 = McpServerConfig(
            name="jira-server", tool_prefix="jira", cache_ttl_seconds=3600.0,
        )
        client1 = McpClient(config1, _make_mock_transport())
        registry1 = McpToolRegistry(config1, McpPolicyGate())
        await agent._mcp_manager.connect(
            "jira", config1, client1, registry1, agent.tool_executor,
        )

        # Connect second MCP server (github)
        config2 = McpServerConfig(
            name="gh-server", tool_prefix="gh", cache_ttl_seconds=3600.0,
        )
        transport2 = _make_mock_transport([
            {
                "name": "list_prs",
                "description": "List PRs",
                "inputSchema": {"type": "object", "properties": {}},
                "annotations": {"readOnlyHint": True, "destructiveHint": False},
            },
        ])
        client2 = McpClient(config2, transport2)
        registry2 = McpToolRegistry(config2, McpPolicyGate())
        await agent._mcp_manager.connect(
            "github", config2, client2, registry2, agent.tool_executor,
        )

        tools = agent._get_tools()
        names = [t.name for t in tools]

        assert len(names) == len(set(names)), (
            f"Duplicate tool names: {[n for n in names if names.count(n) > 1]}"
        )
        assert "jira_search_issues" in names
        assert "gh_list_prs" in names
