"""Tests for MCP schema adaptation and result normalization."""

import pytest

from src.integrations.mcp.adapter import McpToolAdapter
from src.integrations.mcp.config import McpServerConfig


@pytest.fixture
def config():
    return McpServerConfig(
        name="test-server",
        tool_prefix="jira",
        max_result_chars=200,
        max_result_items=10,
    )


@pytest.fixture
def adapter(config):
    return McpToolAdapter(config)


# ---------------------------------------------------------------------------
# Schema translation
# ---------------------------------------------------------------------------

class TestAdaptSchema:
    def test_basic_schema_translation(self, adapter):
        mcp_tool = {
            "name": "search_issues",
            "description": "Search issues via JQL",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "jql": {"type": "string", "description": "JQL query"},
                    "max_results": {"type": "integer", "default": 25},
                },
                "required": ["jql"],
            },
        }

        tool_def = adapter.adapt_schema(mcp_tool)

        assert tool_def.name == "jira_search_issues"
        assert tool_def.description == "Search issues via JQL"
        assert tool_def.parameters["type"] == "object"
        assert "jql" in tool_def.parameters["properties"]
        assert tool_def.parameters["required"] == ["jql"]

    def test_prefix_applied(self, adapter):
        tool_def = adapter.adapt_schema({"name": "get_issue", "description": "d"})
        assert tool_def.name == "jira_get_issue"

    def test_no_prefix_when_empty(self):
        cfg = McpServerConfig(name="x", tool_prefix="")
        a = McpToolAdapter(cfg)
        tool_def = a.adapt_schema({"name": "foo", "description": "d"})
        assert tool_def.name == "foo"

    def test_missing_input_schema_gets_default(self, adapter):
        tool_def = adapter.adapt_schema({"name": "x", "description": "d"})
        assert tool_def.parameters == {"type": "object", "properties": {}}

    def test_full_json_schema_preserved(self, adapter):
        """Verify enum, items, additionalProperties etc. are passed through."""
        mcp_tool = {
            "name": "create_issue",
            "description": "Create issue",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "priority": {
                        "type": "string",
                        "enum": ["High", "Medium", "Low"],
                    },
                    "labels": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["priority"],
                "additionalProperties": False,
            },
        }

        tool_def = adapter.adapt_schema(mcp_tool)

        assert tool_def.parameters["additionalProperties"] is False
        assert tool_def.parameters["properties"]["priority"]["enum"] == ["High", "Medium", "Low"]
        assert tool_def.parameters["properties"]["labels"]["items"] == {"type": "string"}

    def test_batch_adapt_schemas(self, adapter):
        raw = [
            {"name": "a", "description": "da"},
            {"name": "b", "description": "db"},
        ]
        defs = adapter.adapt_schemas(raw)
        assert len(defs) == 2
        assert defs[0].name == "jira_a"
        assert defs[1].name == "jira_b"


# ---------------------------------------------------------------------------
# Result normalization
# ---------------------------------------------------------------------------

class TestAdaptResult:
    def test_success_text_content(self, adapter):
        mcp_result = {
            "content": [
                {"type": "text", "text": "Found 3 issues"},
            ],
            "isError": False,
        }

        result = adapter.adapt_result("jira_search_issues", mcp_result)

        assert result.is_success()
        assert result.output == "Found 3 issues"
        assert result.tool_name == "jira_search_issues"
        assert result.metadata["source"] == "mcp"
        assert result.metadata["provider"] == "jira"

    def test_error_result(self, adapter):
        mcp_result = {
            "content": [{"type": "text", "text": "Permission denied"}],
            "isError": True,
        }

        result = adapter.adapt_result("jira_get_issue", mcp_result)

        assert not result.is_success()
        assert "Permission denied" in result.error

    def test_resource_content_block(self, adapter):
        mcp_result = {
            "content": [
                {"type": "resource", "resource": {"uri": "jira://PROJ-123", "text": "Issue details"}},
            ],
        }

        result = adapter.adapt_result("jira_get_issue", mcp_result)
        assert "Issue details" in result.output

    def test_resource_uri_only(self, adapter):
        mcp_result = {
            "content": [
                {"type": "resource", "resource": {"uri": "jira://PROJ-456"}},
            ],
        }

        result = adapter.adapt_result("jira_get_issue", mcp_result)
        assert "[resource: jira://PROJ-456]" in result.output

    def test_unknown_block_type_serialized(self, adapter):
        mcp_result = {
            "content": [
                {"type": "image", "data": "base64..."},
            ],
        }

        result = adapter.adapt_result("jira_x", mcp_result)
        assert "image" in result.output

    def test_truncation_at_config_limit(self, adapter):
        """Config says max_result_chars=200, verify truncation."""
        long_text = "x" * 500
        mcp_result = {
            "content": [{"type": "text", "text": long_text}],
        }

        result = adapter.adapt_result("jira_search_issues", mcp_result)

        assert len(result.output) < 500
        assert "[truncated, 500 chars total]" in result.output

    def test_empty_content(self, adapter):
        result = adapter.adapt_result("jira_x", {"content": []})
        assert result.is_success()
        assert result.output == ""

    def test_missing_content_key(self, adapter):
        result = adapter.adapt_result("jira_x", {})
        assert result.is_success()


# ---------------------------------------------------------------------------
# Prefix stripping
# ---------------------------------------------------------------------------

class TestStripPrefix:
    def test_strips_prefix(self, adapter):
        assert adapter.strip_prefix("jira_search_issues") == "search_issues"

    def test_no_prefix_passthrough(self, adapter):
        assert adapter.strip_prefix("search_issues") == "search_issues"

    def test_different_prefix_passthrough(self, adapter):
        assert adapter.strip_prefix("github.search") == "github.search"
