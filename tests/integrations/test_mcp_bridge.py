"""Tests for MCP bridge tool: invoke via mock client, result normalization, JSONL persistence."""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.integrations.mcp.adapter import McpToolAdapter
from src.integrations.mcp.bridge import McpBridgeTool
from src.integrations.mcp.client import McpClient, McpError, McpTransport
from src.integrations.mcp.config import McpServerConfig
from src.integrations.mcp.policy import McpPolicyGate
from src.integrations.mcp.registry import McpToolRegistry
from src.llm.base import ToolDefinition
from src.tools.base import ToolExecutor, ToolStatus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def config():
    return McpServerConfig(
        name="test-server",
        tool_prefix="jira",
        max_result_chars=4096,
        invoke_timeout=10.0,
        cache_ttl_seconds=3600.0,
    )


@pytest.fixture
def adapter(config):
    return McpToolAdapter(config)


@pytest.fixture
def mock_transport():
    """Mock transport that returns predefined tool schemas and results."""
    transport = AsyncMock(spec=McpTransport)
    transport.is_connected.return_value = True

    async def mock_send(method, params=None):
        if method == "tools/list":
            return {
                "tools": [
                    {
                        "name": "search_issues",
                        "description": "Search via JQL",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "jql": {"type": "string"},
                            },
                            "required": ["jql"],
                        },
                        "annotations": {
                            "readOnlyHint": True,
                            "destructiveHint": False,
                        },
                    },
                    {
                        "name": "get_issue",
                        "description": "Get issue by key",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "issue_key": {"type": "string"},
                            },
                            "required": ["issue_key"],
                        },
                        "annotations": {
                            "readOnlyHint": True,
                            "destructiveHint": False,
                        },
                    },
                    {
                        "name": "create_issue",
                        "description": "Create a new issue",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "project": {"type": "string"},
                                "summary": {"type": "string"},
                            },
                            "required": ["project", "summary"],
                        },
                        "annotations": {
                            "readOnlyHint": False,
                            "destructiveHint": False,
                        },
                    },
                    {
                        "name": "admin_danger",
                        "description": "Dangerous admin tool",
                        "inputSchema": {"type": "object", "properties": {}},
                        "annotations": {
                            "readOnlyHint": True,
                            "destructiveHint": False,
                        },
                    },
                ]
            }
        elif method == "tools/call":
            tool_name = params.get("name", "")
            if tool_name == "search_issues":
                return {
                    "content": [
                        {"type": "text", "text": json.dumps([
                            {"key": "PROJ-1", "summary": "Bug in login", "status": "Open"},
                            {"key": "PROJ-2", "summary": "Add feature X", "status": "In Progress"},
                        ])},
                    ],
                    "isError": False,
                }
            elif tool_name == "get_issue":
                return {
                    "content": [
                        {"type": "text", "text": json.dumps({
                            "key": "PROJ-1",
                            "summary": "Bug in login",
                            "description": "Login fails on mobile",
                        })},
                    ],
                    "isError": False,
                }
            elif tool_name == "create_issue":
                return {
                    "content": [
                        {"type": "text", "text": "Created PROJ-3"},
                    ],
                    "isError": False,
                }
            return {"content": [], "isError": True}
        return {}

    transport.send.side_effect = mock_send
    return transport


@pytest.fixture
def policy_gate():
    # admin_danger is blocklisted; all other tools allowed via annotations
    return McpPolicyGate(blocklist={"jira_admin_danger"})


@pytest.fixture
def client(config, mock_transport):
    return McpClient(config, mock_transport)


# ---------------------------------------------------------------------------
# McpBridgeTool invocation
# ---------------------------------------------------------------------------

class TestMcpBridgeTool:
    def test_execute_returns_success(self, client, adapter):
        tool_def = ToolDefinition(
            name="jira_search_issues",
            description="Search",
            parameters={"type": "object", "properties": {"jql": {"type": "string"}}},
        )
        bridge = McpBridgeTool(
            client=client,
            adapter=adapter,
            tool_definition=tool_def,
            mcp_tool_name="search_issues",
            event_loop=None,  # Test fallback path (new loop)
        )

        result = bridge.execute(jql="project = PROJ")

        assert result.status == ToolStatus.SUCCESS
        assert "PROJ-1" in result.output
        assert result.tool_name == "jira_search_issues"
        assert result.metadata["source"] == "mcp"

    def test_execute_mcp_error_handled(self, adapter, config):
        error_transport = AsyncMock(spec=McpTransport)
        error_transport.is_connected.return_value = True

        async def fail_send(method, params=None):
            raise McpError(code=403, message="Forbidden")

        error_transport.send.side_effect = fail_send
        error_client = McpClient(config, error_transport)

        tool_def = ToolDefinition(name="jira_x", description="d", parameters={})
        bridge = McpBridgeTool(
            client=error_client,
            adapter=adapter,
            tool_definition=tool_def,
            mcp_tool_name="x",
        )

        result = bridge.execute()
        assert result.status == ToolStatus.ERROR
        assert "Forbidden" in result.error

    def test_execute_generic_exception_handled(self, adapter, config):
        bad_transport = AsyncMock(spec=McpTransport)
        bad_transport.is_connected.return_value = True

        async def crash_send(method, params=None):
            raise RuntimeError("Connection lost")

        bad_transport.send.side_effect = crash_send
        bad_client = McpClient(config, bad_transport)

        tool_def = ToolDefinition(name="jira_x", description="d", parameters={})
        bridge = McpBridgeTool(
            client=bad_client, adapter=adapter,
            tool_definition=tool_def, mcp_tool_name="x",
        )

        result = bridge.execute()
        assert result.status == ToolStatus.ERROR
        assert "Connection lost" in result.error

    def test_get_schema(self, client, adapter):
        tool_def = ToolDefinition(
            name="jira_get_issue", description="Get issue",
            parameters={"type": "object", "properties": {"issue_key": {"type": "string"}}},
        )
        bridge = McpBridgeTool(
            client=client, adapter=adapter,
            tool_definition=tool_def, mcp_tool_name="get_issue",
        )
        schema = bridge.get_schema()
        assert schema["name"] == "jira_get_issue"
        assert "issue_key" in schema["parameters"]["properties"]


# ---------------------------------------------------------------------------
# Registry: discovery + registration
# ---------------------------------------------------------------------------

class TestMcpToolRegistry:
    @pytest.mark.asyncio
    async def test_discover_and_register(self, config, client, policy_gate):
        registry = McpToolRegistry(config, policy_gate)
        executor = ToolExecutor()

        # Must connect first
        await client.connect()

        count, discovered = await registry.discover_and_register(client, executor)

        # 3 allowed (search, get, create), 1 blocked (admin_danger)
        assert count == 3
        assert len(discovered) == 4
        assert registry.enabled is True

        # Check tool definitions
        defs = registry.get_tool_definitions()
        names = [d.name for d in defs]
        assert "jira_search_issues" in names
        assert "jira_get_issue" in names
        assert "jira_create_issue" in names
        assert "jira_admin_danger" not in names

    @pytest.mark.asyncio
    async def test_blocked_tool_not_registered(self, config, client, policy_gate):
        registry = McpToolRegistry(config, policy_gate)
        executor = ToolExecutor()
        await client.connect()
        await registry.discover_and_register(client, executor)

        assert not registry.is_mcp_tool("jira_admin_danger")
        assert "jira_admin_danger" not in executor.tools

    @pytest.mark.asyncio
    async def test_is_mcp_tool(self, config, client, policy_gate):
        registry = McpToolRegistry(config, policy_gate)
        executor = ToolExecutor()
        await client.connect()
        await registry.discover_and_register(client, executor)

        assert registry.is_mcp_tool("jira_search_issues") is True
        assert registry.is_mcp_tool("read_file") is False

    @pytest.mark.asyncio
    async def test_cache_prevents_rediscovery(self, config, client, policy_gate):
        registry = McpToolRegistry(config, policy_gate)
        executor = ToolExecutor()
        await client.connect()

        await registry.discover_and_register(client, executor)
        call_count_1 = client._transport.send.call_count

        await registry.discover_and_register(client, executor)
        call_count_2 = client._transport.send.call_count

        # Second call should hit cache, no new transport.send call
        assert call_count_2 == call_count_1

    @pytest.mark.asyncio
    async def test_invalidate_cache_forces_rediscovery(self, config, client, policy_gate):
        registry = McpToolRegistry(config, policy_gate)
        executor = ToolExecutor()
        await client.connect()

        await registry.discover_and_register(client, executor)
        call_count_1 = client._transport.send.call_count

        registry.invalidate_cache()
        await registry.discover_and_register(client, executor)
        call_count_2 = client._transport.send.call_count

        assert call_count_2 > call_count_1

    @pytest.mark.asyncio
    async def test_disabled_returns_no_tools(self, config, client, policy_gate):
        registry = McpToolRegistry(config, policy_gate)
        # Not discovered yet -> disabled
        assert registry.get_tool_definitions() == []

    @pytest.mark.asyncio
    async def test_clear_resets_state(self, config, client, policy_gate):
        registry = McpToolRegistry(config, policy_gate)
        executor = ToolExecutor()
        await client.connect()
        await registry.discover_and_register(client, executor)

        registry.clear()
        assert registry.enabled is False
        assert registry.get_tool_definitions() == []
        assert not registry.is_mcp_tool("jira_search_issues")

    @pytest.mark.asyncio
    async def test_registered_bridge_tool_executes(self, config, client, policy_gate):
        """End-to-end: register via registry, execute via ToolExecutor.

        Uses execute_tool_async because the bridge was registered with the
        running event loop (captured during discover_and_register). Calling
        sync execute_tool on the same thread would deadlock since
        run_coroutine_threadsafe + future.result() blocks the event loop.
        """
        registry = McpToolRegistry(config, policy_gate)
        executor = ToolExecutor()
        await client.connect()
        await registry.discover_and_register(client, executor)

        result = await executor.execute_tool_async("jira_search_issues", jql="project = TEST")
        assert result.status == ToolStatus.SUCCESS
        assert "PROJ-1" in result.output


# ---------------------------------------------------------------------------
# Tool result persistence format
# ---------------------------------------------------------------------------

class TestResultPersistence:
    def test_result_serializable_as_json(self, client, adapter):
        """ToolResult.output must be JSON-serializable for JSONL persistence."""
        tool_def = ToolDefinition(
            name="jira_search_issues", description="Search",
            parameters={"type": "object", "properties": {}},
        )
        bridge = McpBridgeTool(
            client=client, adapter=adapter,
            tool_definition=tool_def, mcp_tool_name="search_issues",
        )

        result = bridge.execute(jql="project = PROJ")

        # Simulate JSONL serialization
        jsonl_record = {
            "role": "tool",
            "tool_call_id": "test-123",
            "name": result.tool_name,
            "content": result.output,
        }
        serialized = json.dumps(jsonl_record)
        deserialized = json.loads(serialized)
        assert deserialized["name"] == "jira_search_issues"
        assert deserialized["content"] == result.output
