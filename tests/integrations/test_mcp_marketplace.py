"""Tests for MCP marketplace - official registry search and install."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.integrations.mcp.marketplace import (
    McpMarketplace,
    McpMarketplaceEntry,
    McpMarketplaceSearchResult,
    _parse_official_entry,
)


# ---------------------------------------------------------------------------
# Official registry response fixtures
# ---------------------------------------------------------------------------

OFFICIAL_LIST_RESPONSE = {
    "servers": [
        {
            "server": {
                "name": "io.github.modelcontextprotocol/server-filesystem",
                "description": "Filesystem operations",
                "version": "1.0.0",
                "repository": {
                    "url": "https://github.com/modelcontextprotocol/servers",
                    "source": "github",
                },
                "packages": [
                    {
                        "registryType": "npm",
                        "identifier": "@modelcontextprotocol/server-filesystem",
                        "version": "1.0.0",
                        "transport": {"type": "stdio"},
                        "environmentVariables": [],
                    }
                ],
            },
            "_meta": {
                "io.modelcontextprotocol.registry/official": {
                    "status": "active",
                    "publishedAt": "2025-01-01",
                    "isLatest": True,
                }
            },
        },
        {
            "server": {
                "name": "io.github.sentry/mcp-server",
                "description": "Sentry error tracking",
                "version": "0.5.0",
                "repository": {
                    "url": "https://github.com/getsentry/sentry-mcp",
                    "source": "github",
                },
                "packages": [
                    {
                        "registryType": "npm",
                        "identifier": "@sentry/mcp-server",
                        "version": "0.5.0",
                        "transport": {"type": "stdio"},
                        "environmentVariables": [
                            {"name": "SENTRY_AUTH_TOKEN", "description": "API token"},
                        ],
                    }
                ],
                "remotes": [{"type": "streamable-http", "url": "https://mcp.sentry.io"}],
            }
        },
    ],
    "metadata": {"nextCursor": "abc123", "count": 2},
}


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------

class TestOfficialParser:
    def test_parse_npm_package(self):
        entry = _parse_official_entry(OFFICIAL_LIST_RESPONSE["servers"][0])
        assert entry.name == "Server Filesystem"
        assert entry.author == "modelcontextprotocol"
        assert entry.command == "npx"
        assert entry.args == ["-y", "@modelcontextprotocol/server-filesystem"]
        assert entry.source == "official"

    def test_parse_with_env_vars(self):
        entry = _parse_official_entry(OFFICIAL_LIST_RESPONSE["servers"][1])
        assert entry.env_vars == ["SENTRY_AUTH_TOKEN"]
        assert entry.command == "npx"
        assert entry.args == ["-y", "@sentry/mcp-server"]

    def test_parse_verified_from_meta(self):
        entry = _parse_official_entry(OFFICIAL_LIST_RESPONSE["servers"][0])
        assert entry.verified is True

    def test_parse_not_verified_without_meta(self):
        entry = _parse_official_entry(OFFICIAL_LIST_RESPONSE["servers"][1])
        assert entry.verified is False

    def test_parse_remote(self):
        entry = _parse_official_entry(OFFICIAL_LIST_RESPONSE["servers"][1])
        assert entry.is_remote is True

    def test_parse_no_remote(self):
        entry = _parse_official_entry(OFFICIAL_LIST_RESPONSE["servers"][0])
        assert entry.is_remote is False

    def test_parse_no_packages(self):
        raw = {"server": {"name": "test/server", "description": "No packages", "repository": {"url": ""}}}
        entry = _parse_official_entry(raw)
        assert entry.command is None
        assert entry.args == []

    def test_parse_author_from_github_url(self):
        raw = {"server": {"name": "x", "description": "", "repository": {"url": "https://github.com/myorg/myrepo"}}}
        entry = _parse_official_entry(raw)
        assert entry.author == "myorg"


# ---------------------------------------------------------------------------
# Data model tests
# ---------------------------------------------------------------------------

class TestMarketplaceEntry:
    def test_to_dict(self):
        entry = McpMarketplaceEntry(
            id="test",
            name="Test Server",
            author="tester",
            description="A test server",
            command="npx",
            args=["-y", "test-server"],
            env_vars=["API_KEY"],
            tags=["testing"],
            use_count=42,
            verified=True,
        )
        d = entry.to_dict()
        assert d["id"] == "test"
        assert d["name"] == "Test Server"
        assert d["command"] == "npx"
        assert d["args"] == ["-y", "test-server"]
        assert d["envVars"] == ["API_KEY"]
        assert d["useCount"] == 42
        assert d["verified"] is True
        assert d["source"] == "official"

    def test_defaults(self):
        entry = McpMarketplaceEntry(id="x", name="X", author="a", description="d")
        assert entry.source == "official"
        assert entry.transport == "stdio"
        assert entry.command is None
        assert entry.env_vars == []


class TestSearchResult:
    def test_to_dict(self):
        result = McpMarketplaceSearchResult(
            entries=[
                McpMarketplaceEntry(id="a", name="A", author="x", description="desc"),
            ],
            total_count=50,
            page=2,
            page_size=10,
            has_next=True,
        )
        d = result.to_dict()
        assert d["totalCount"] == 50
        assert d["page"] == 2
        assert d["hasNext"] is True
        assert len(d["entries"]) == 1


# ---------------------------------------------------------------------------
# Marketplace client tests (mocked HTTP)
# ---------------------------------------------------------------------------

class TestMarketplaceSearch:
    @pytest.mark.asyncio
    async def test_search_includes_official_npm_package(self):
        """When searching, a direct npm lookup for @modelcontextprotocol/server-{query} is done."""
        marketplace = McpMarketplace()

        # npm direct lookup returns a package
        npm_response = MagicMock()
        npm_response.status_code = 200
        npm_response.json.return_value = {
            "name": "@modelcontextprotocol/server-puppeteer",
            "description": "MCP server for browser automation",
            "dist-tags": {"latest": "2025.5.12"},
            "repository": {"url": "https://github.com/modelcontextprotocol/servers"},
        }
        npm_response.raise_for_status = MagicMock()

        # Official registry returns unrelated results
        official_response = MagicMock()
        official_response.status_code = 200
        official_response.json.return_value = OFFICIAL_LIST_RESPONSE
        official_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[official_response, npm_response])
        marketplace._http_client = mock_client

        result = await marketplace.search("puppeteer", page=1, page_size=20)

        # Official npm package should be first
        assert result.entries[0].name == "@modelcontextprotocol/server-puppeteer"
        assert result.entries[0].source == "npm"
        assert result.entries[0].verified is True
        assert result.entries[0].command == "npx"
        assert result.entries[0].args == ["-y", "@modelcontextprotocol/server-puppeteer"]

    @pytest.mark.asyncio
    async def test_search_npm_404_skipped(self):
        """If @modelcontextprotocol/server-{query} doesn't exist, only registry results shown."""
        marketplace = McpMarketplace()

        npm_response = MagicMock()
        npm_response.status_code = 404

        official_response = MagicMock()
        official_response.status_code = 200
        official_response.json.return_value = OFFICIAL_LIST_RESPONSE
        official_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[official_response, npm_response])
        marketplace._http_client = mock_client

        result = await marketplace.search("nonexistent", page=1, page_size=20)

        # Only official results
        assert all(e.source == "official" for e in result.entries)

    @pytest.mark.asyncio
    async def test_search_failure_returns_empty(self):
        marketplace = McpMarketplace()

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("Down")

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        marketplace._http_client = mock_client

        result = await marketplace.search("anything")

        assert result.entries == []
        assert result.total_count == 0

    @pytest.mark.asyncio
    async def test_search_empty_query_browses_all(self):
        marketplace = McpMarketplace()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = OFFICIAL_LIST_RESPONSE
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        marketplace._http_client = mock_client

        await marketplace.search("", page=1, page_size=10)

        # No "search" param when query is empty
        mock_client.get.assert_called_once_with(
            "https://registry.modelcontextprotocol.io/v0/servers",
            params={"limit": 10},
        )

    @pytest.mark.asyncio
    async def test_search_has_next_from_cursor(self):
        marketplace = McpMarketplace()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "servers": [],
            "metadata": {"nextCursor": None, "count": 0},
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        marketplace._http_client = mock_client

        result = await marketplace.search("test")
        assert result.has_next is False


class TestMarketplaceDetail:
    @pytest.mark.asyncio
    async def test_get_detail_exact_match(self):
        marketplace = McpMarketplace()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = OFFICIAL_LIST_RESPONSE
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        marketplace._http_client = mock_client

        entry = await marketplace.get_server_detail("io.github.modelcontextprotocol/server-filesystem")

        assert entry is not None
        assert entry.name == "Server Filesystem"

    @pytest.mark.asyncio
    async def test_get_detail_fallback_first_result(self):
        marketplace = McpMarketplace()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = OFFICIAL_LIST_RESPONSE
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        marketplace._http_client = mock_client

        # Search for something that won't exact match but returns results
        entry = await marketplace.get_server_detail("filesystem")
        assert entry is not None  # Falls back to first result

    @pytest.mark.asyncio
    async def test_get_detail_no_results(self):
        marketplace = McpMarketplace()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"servers": [], "metadata": {}}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        marketplace._http_client = mock_client

        entry = await marketplace.get_server_detail("nonexistent")
        assert entry is None

    @pytest.mark.asyncio
    async def test_get_detail_error_returns_none(self):
        marketplace = McpMarketplace()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("Network error"))
        marketplace._http_client = mock_client

        entry = await marketplace.get_server_detail("anything")
        assert entry is None


# ---------------------------------------------------------------------------
# Install config generation
# ---------------------------------------------------------------------------

class TestInstallConfig:
    def test_create_config_stdio_with_env(self):
        marketplace = McpMarketplace()
        entry = McpMarketplaceEntry(
            id="github",
            name="GitHub",
            author="modelcontextprotocol",
            description="GitHub tools",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-github"],
            env_vars=["GITHUB_TOKEN"],
        )
        config = marketplace.create_install_config(
            entry, env_values={"GITHUB_TOKEN": "ghp_xxx"}
        )

        assert config is not None
        assert config["command"] == "npx"
        assert config["args"] == ["-y", "@modelcontextprotocol/server-github"]
        assert config["env"] == {"GITHUB_TOKEN": "ghp_xxx"}
        assert config["enabled"] is True
        assert "url" not in config

    def test_create_config_remote_uses_mcp_remote(self):
        marketplace = McpMarketplace()
        entry = McpMarketplaceEntry(
            id="atlassian",
            name="Atlassian",
            author="atlassian",
            description="Atlassian Rovo",
            remote_url="https://mcp.atlassian.com/v1/mcp",
        )
        config = marketplace.create_install_config(entry)

        assert config is not None
        assert config["command"] == "npx"
        assert config["args"] == ["-y", "mcp-remote@latest", "https://mcp.atlassian.com/v1/mcp"]
        assert "url" not in config

    def test_create_config_no_install_info(self):
        marketplace = McpMarketplace()
        entry = McpMarketplaceEntry(
            id="mystery",
            name="Mystery",
            author="unknown",
            description="No install info",
        )
        config = marketplace.create_install_config(entry)
        assert config is None

    def test_create_config_without_env(self):
        marketplace = McpMarketplace()
        entry = McpMarketplaceEntry(
            id="sequential-thinking",
            name="Sequential Thinking",
            author="modelcontextprotocol",
            description="Structured reasoning",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-sequential-thinking"],
        )
        config = marketplace.create_install_config(entry)

        assert config["command"] == "npx"
        assert "env" not in config

    def test_tool_prefix_sanitization(self):
        marketplace = McpMarketplace()
        entry = McpMarketplaceEntry(
            id="owner/my-cool-server",
            name="Cool Server",
            author="owner",
            description="Cool server",
            command="npx",
            args=["-y", "my-cool-server"],
        )
        config = marketplace.create_install_config(entry)
        assert config is not None
        assert config["toolPrefix"] == "owner_my-cool-server"
