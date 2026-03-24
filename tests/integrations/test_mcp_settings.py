"""Tests for MCP settings manager - file-based config with per-tool visibility."""

import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from src.integrations.mcp.settings import (
    McpSettingsManager,
    McpServerSettings,
    McpToolOverride,
)
from src.integrations.mcp.config import McpServerConfig


# ---------------------------------------------------------------------------
# McpToolOverride
# ---------------------------------------------------------------------------

class TestToolOverride:
    def test_defaults_to_enabled(self):
        override = McpToolOverride()
        assert override.enabled is True

    def test_to_dict(self):
        override = McpToolOverride(enabled=False)
        assert override.to_dict() == {"enabled": False}

    def test_from_dict(self):
        override = McpToolOverride.from_dict({"enabled": False})
        assert override.enabled is False

    def test_from_dict_missing_enabled_defaults_true(self):
        override = McpToolOverride.from_dict({})
        assert override.enabled is True


# ---------------------------------------------------------------------------
# McpServerSettings
# ---------------------------------------------------------------------------

class TestServerSettings:
    def test_from_dict_stdio(self):
        data = {
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-github"],
            "env": {"GITHUB_TOKEN": "ghp_xxx"},
            "enabled": True,
            "toolPrefix": "github",
            "tools": {
                "create_issue": {"enabled": True},
                "delete_repo": {"enabled": False},
            },
        }
        settings = McpServerSettings.from_dict("github", data)

        assert settings.name == "github"
        assert settings.transport == "stdio"
        assert settings.command == "npx"
        assert settings.args == ["-y", "@modelcontextprotocol/server-github"]
        assert settings.env == {"GITHUB_TOKEN": "ghp_xxx"}
        assert settings.enabled is True
        assert settings.tool_prefix == "github"
        assert "create_issue" in settings.tools
        assert settings.tools["create_issue"].enabled is True
        assert settings.tools["delete_repo"].enabled is False

    def test_from_dict_sse(self):
        data = {
            "transport": "sse",
            "serverUrl": "http://localhost:8080/mcp",
            "enabled": True,
        }
        settings = McpServerSettings.from_dict("local", data)
        assert settings.transport == "sse"
        assert settings.server_url == "http://localhost:8080/mcp"

    def test_from_dict_defaults(self):
        settings = McpServerSettings.from_dict("test", {})
        assert settings.transport == "stdio"
        assert settings.enabled is True
        assert settings.tool_prefix == "test"  # defaults to name
        assert settings.tools == {}

    def test_to_dict_roundtrip(self):
        original = McpServerSettings(
            name="github",
            transport="stdio",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-github"],
            env={"TOKEN": "xxx"},
            enabled=True,
            tool_prefix="gh",
            tools={"search": McpToolOverride(enabled=True), "delete": McpToolOverride(enabled=False)},
        )
        data = original.to_dict()
        restored = McpServerSettings.from_dict("github", data)

        assert restored.name == original.name
        assert restored.command == original.command
        assert restored.args == original.args
        assert restored.env == original.env
        assert restored.tool_prefix == original.tool_prefix
        assert restored.tools["search"].enabled is True
        assert restored.tools["delete"].enabled is False

    def test_to_dict_minimal(self):
        """Only includes non-default fields."""
        settings = McpServerSettings(name="test")
        data = settings.to_dict()
        assert "command" not in data
        assert "args" not in data
        assert "env" not in data
        assert "tools" not in data
        assert data["enabled"] is True

    def test_to_runtime_config_stdio(self):
        settings = McpServerSettings(
            name="github",
            transport="stdio",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-github"],
            env={"TOKEN": "xxx"},
            tool_prefix="gh",
            invoke_timeout=120.0,
        )
        config = settings.to_runtime_config()

        assert isinstance(config, McpServerConfig)
        assert config.name == "github"
        assert "npx" in config.command
        assert "@modelcontextprotocol/server-github" in config.command
        assert config.extra_env == {"TOKEN": "xxx"}
        assert config.tool_prefix == "gh"
        assert config.invoke_timeout == 120.0

    def test_to_runtime_config_sse(self):
        settings = McpServerSettings(
            name="remote",
            transport="sse",
            server_url="http://localhost:8080/mcp",
        )
        config = settings.to_runtime_config()
        assert config.server_url == "http://localhost:8080/mcp"


# ---------------------------------------------------------------------------
# Tool visibility
# ---------------------------------------------------------------------------

class TestToolVisibility:
    def test_is_tool_enabled_default(self):
        settings = McpServerSettings(name="test")
        # Unknown tools default to enabled
        assert settings.is_tool_enabled("new_tool") is True

    def test_is_tool_enabled_explicit(self):
        settings = McpServerSettings(
            name="test",
            tools={"search": McpToolOverride(enabled=True), "delete": McpToolOverride(enabled=False)},
        )
        assert settings.is_tool_enabled("search") is True
        assert settings.is_tool_enabled("delete") is False
        assert settings.is_tool_enabled("unknown") is True

    def test_get_disabled_tools(self):
        settings = McpServerSettings(
            name="test",
            tools={
                "search": McpToolOverride(enabled=True),
                "delete": McpToolOverride(enabled=False),
                "admin": McpToolOverride(enabled=False),
            },
        )
        disabled = settings.get_disabled_tools()
        assert disabled == {"delete", "admin"}

    def test_merge_discovered_tools_new(self):
        settings = McpServerSettings(name="test")
        new = settings.merge_discovered_tools(["search", "create", "delete"])
        assert new == ["search", "create", "delete"]
        assert len(settings.tools) == 3
        assert all(t.enabled for t in settings.tools.values())

    def test_merge_discovered_tools_preserves_existing(self):
        settings = McpServerSettings(
            name="test",
            tools={"search": McpToolOverride(enabled=False)},
        )
        new = settings.merge_discovered_tools(["search", "create"])
        assert new == ["create"]
        assert settings.tools["search"].enabled is False  # preserved
        assert settings.tools["create"].enabled is True  # new = enabled

    def test_merge_discovered_tools_keeps_stale(self):
        """Tools in config but not in discovery are kept (server may be down)."""
        settings = McpServerSettings(
            name="test",
            tools={"old_tool": McpToolOverride(enabled=True)},
        )
        settings.merge_discovered_tools(["new_tool"])
        assert "old_tool" in settings.tools
        assert "new_tool" in settings.tools


# ---------------------------------------------------------------------------
# McpSettingsManager
# ---------------------------------------------------------------------------

class TestSettingsManager:
    def test_load_missing_file(self, tmp_path):
        mgr = McpSettingsManager(tmp_path / "nonexistent.json")
        mgr.load()  # Should not raise
        assert mgr.servers == {}

    def test_load_valid_file(self, tmp_path):
        settings_file = tmp_path / "mcp_settings.json"
        settings_file.write_text(json.dumps({
            "mcpServers": {
                "github": {
                    "transport": "stdio",
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-github"],
                    "enabled": True,
                    "toolPrefix": "gh",
                    "tools": {
                        "search_code": {"enabled": True},
                        "delete_repo": {"enabled": False},
                    },
                },
                "disabled_server": {
                    "transport": "stdio",
                    "command": "echo",
                    "enabled": False,
                },
            }
        }), encoding="utf-8")

        mgr = McpSettingsManager(settings_file)
        mgr.load()

        assert len(mgr.servers) == 2
        assert mgr.servers["github"].tool_prefix == "gh"
        assert mgr.servers["github"].tools["delete_repo"].enabled is False
        assert mgr.servers["disabled_server"].enabled is False

    def test_load_invalid_json(self, tmp_path):
        settings_file = tmp_path / "bad.json"
        settings_file.write_text("not json", encoding="utf-8")

        mgr = McpSettingsManager(settings_file)
        mgr.load()  # Should not raise
        assert mgr.servers == {}

    def test_save_creates_file(self, tmp_path):
        settings_file = tmp_path / "sub" / "mcp_settings.json"
        mgr = McpSettingsManager(settings_file)

        mgr.add_server(McpServerSettings(
            name="test",
            command="echo",
            tool_prefix="t",
        ))
        mgr.save()

        assert settings_file.exists()
        data = json.loads(settings_file.read_text(encoding="utf-8"))
        assert "test" in data["mcpServers"]

    def test_save_load_roundtrip(self, tmp_path):
        settings_file = tmp_path / "mcp_settings.json"
        mgr = McpSettingsManager(settings_file)

        mgr.add_server(McpServerSettings(
            name="github",
            transport="stdio",
            command="npx",
            args=["-y", "server-github"],
            env={"TOKEN": "xxx"},
            tool_prefix="gh",
            tools={"search": McpToolOverride(enabled=True), "delete": McpToolOverride(enabled=False)},
        ))
        mgr.save()

        mgr2 = McpSettingsManager(settings_file)
        mgr2.load()

        gh = mgr2.get_server("github")
        assert gh is not None
        assert gh.command == "npx"
        assert gh.args == ["-y", "server-github"]
        assert gh.tools["search"].enabled is True
        assert gh.tools["delete"].enabled is False

    def test_add_and_remove_server(self, tmp_path):
        mgr = McpSettingsManager(tmp_path / "test.json")
        mgr.add_server(McpServerSettings(name="s1"))
        mgr.add_server(McpServerSettings(name="s2"))
        assert len(mgr.servers) == 2

        removed = mgr.remove_server("s1")
        assert removed is not None
        assert removed.name == "s1"
        assert len(mgr.servers) == 1

        assert mgr.remove_server("nonexistent") is None

    def test_get_enabled_servers(self, tmp_path):
        mgr = McpSettingsManager(tmp_path / "test.json")
        mgr.add_server(McpServerSettings(name="active", enabled=True))
        mgr.add_server(McpServerSettings(name="inactive", enabled=False))
        mgr.add_server(McpServerSettings(name="also_active", enabled=True))

        enabled = mgr.get_enabled_servers()
        names = [s.name for s in enabled]
        assert "active" in names
        assert "also_active" in names
        assert "inactive" not in names

    def test_update_tool_visibility(self, tmp_path):
        mgr = McpSettingsManager(tmp_path / "test.json")
        mgr.add_server(McpServerSettings(name="s1"))

        assert mgr.update_tool_visibility("s1", "search", False) is True
        assert mgr.servers["s1"].tools["search"].enabled is False

        assert mgr.update_tool_visibility("s1", "search", True) is True
        assert mgr.servers["s1"].tools["search"].enabled is True

        # Non-existent server
        assert mgr.update_tool_visibility("nope", "search", False) is False

    def test_update_server_enabled(self, tmp_path):
        mgr = McpSettingsManager(tmp_path / "test.json")
        mgr.add_server(McpServerSettings(name="s1", enabled=True))

        assert mgr.update_server_enabled("s1", False) is True
        assert mgr.servers["s1"].enabled is False

        assert mgr.update_server_enabled("nope", False) is False

    def test_merge_discovered_tools(self, tmp_path):
        mgr = McpSettingsManager(tmp_path / "test.json")
        mgr.add_server(McpServerSettings(
            name="s1",
            tools={"existing": McpToolOverride(enabled=False)},
        ))

        new = mgr.merge_discovered_tools("s1", ["existing", "brand_new"])
        assert new == ["brand_new"]
        assert mgr.servers["s1"].tools["existing"].enabled is False  # preserved
        assert mgr.servers["s1"].tools["brand_new"].enabled is True

    def test_merge_nonexistent_server(self, tmp_path):
        mgr = McpSettingsManager(tmp_path / "test.json")
        assert mgr.merge_discovered_tools("nope", ["tool"]) == []

    def test_get_tool_filter(self, tmp_path):
        mgr = McpSettingsManager(tmp_path / "test.json")
        mgr.add_server(McpServerSettings(
            name="s1",
            tools={
                "search": McpToolOverride(enabled=True),
                "delete": McpToolOverride(enabled=False),
                "admin": McpToolOverride(enabled=False),
            },
        ))

        disabled = mgr.get_tool_filter("s1")
        assert disabled == {"delete", "admin"}

        # Non-existent server returns empty set
        assert mgr.get_tool_filter("nope") == set()


# ---------------------------------------------------------------------------
# Integration: settings -> registry with per-tool filtering
# ---------------------------------------------------------------------------

class TestSettingsRegistryIntegration:
    """Test that per-tool disabled config flows through to registry."""

    @pytest.mark.asyncio
    async def test_disabled_tools_not_registered(self, tmp_path):
        from src.integrations.mcp.client import McpClient, McpTransport
        from src.integrations.mcp.policy import McpPolicyGate
        from src.integrations.mcp.registry import McpToolRegistry
        from src.tools.base import ToolExecutor

        # Mock transport
        transport = AsyncMock(spec=McpTransport)
        transport.is_connected.return_value = True
        transport.close_sync = MagicMock()

        tools = [
            {
                "name": "search",
                "description": "Search",
                "inputSchema": {"type": "object", "properties": {}},
                "annotations": {"readOnlyHint": True},
            },
            {
                "name": "delete",
                "description": "Delete stuff",
                "inputSchema": {"type": "object", "properties": {}},
                "annotations": {"readOnlyHint": False, "destructiveHint": True},
            },
            {
                "name": "create",
                "description": "Create stuff",
                "inputSchema": {"type": "object", "properties": {}},
                "annotations": {"readOnlyHint": False},
            },
        ]

        async def mock_send(method, params=None):
            if method == "tools/list":
                return {"tools": tools}
            return {}

        transport.send.side_effect = mock_send

        config = McpServerConfig(name="test", tool_prefix="t", cache_ttl_seconds=3600.0)
        client = McpClient(config, transport)
        await client.connect()

        registry = McpToolRegistry(config, McpPolicyGate())
        executor = ToolExecutor()

        # Disable "delete" tool via user config
        count, discovered = await registry.discover_and_register(
            client, executor, disabled_tools={"delete"}
        )

        assert count == 2  # search + create, NOT delete
        assert len(discovered) == 3  # all 3 were discovered
        assert registry.is_mcp_tool("t_search")
        assert registry.is_mcp_tool("t_create")
        assert not registry.is_mcp_tool("t_delete")

    @pytest.mark.asyncio
    async def test_connect_from_settings(self, tmp_path):
        """Test full flow: settings file -> connect -> filtered tools."""
        from src.integrations.mcp.manager import McpConnectionManager
        from src.tools.base import ToolExecutor

        # Write settings file
        settings_file = tmp_path / "mcp_settings.json"
        settings_file.write_text(json.dumps({
            "mcpServers": {
                "mock": {
                    "transport": "stdio",
                    "command": "echo",
                    "enabled": True,
                    "toolPrefix": "m",
                    "tools": {
                        "safe_tool": {"enabled": True},
                        "dangerous_tool": {"enabled": False},
                    },
                },
            },
        }), encoding="utf-8")

        settings = McpSettingsManager(settings_file)
        settings.load()

        # We can't actually connect (no real server), but we can verify
        # the settings layer produces the correct filter
        server = settings.get_server("mock")
        assert server is not None
        assert server.get_disabled_tools() == {"dangerous_tool"}
        assert server.is_tool_enabled("safe_tool") is True
        assert server.is_tool_enabled("dangerous_tool") is False
        assert server.is_tool_enabled("undiscovered_tool") is True  # new = enabled
