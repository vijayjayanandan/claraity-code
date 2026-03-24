"""MCP schema adaptation layer.

Translates between MCP tool schemas and our internal ToolDefinition format,
and normalizes MCP tool results into ToolResult objects.

Truncation limits come from McpServerConfig (not hardcoded constants).

NOTE: imports of ToolDefinition (src.llm.base) and ToolResult (src.tools.base)
are deferred to method bodies to avoid the circular import chain:
  adapter -> llm.base -> llm.__init__ -> session -> core -> llm
"""

import json
import logging
from typing import Any, Optional

from .config import McpServerConfig

try:
    from src.observability import get_logger

    logger = get_logger("integrations.mcp.adapter")
except ImportError:
    logger = logging.getLogger(__name__)


class McpToolAdapter:
    """Adapts MCP tool schemas and results to our internal format.

    Schema translation: MCP inputSchema -> ToolDefinition (OpenAI function format)
    Result normalization: MCP content blocks -> structured ToolResult
    """

    def __init__(self, config: McpServerConfig):
        self._config = config
        self._prefix = config.tool_prefix

    def adapt_schema(self, mcp_tool: dict[str, Any]):
        """Convert an MCP tool schema to a ToolDefinition.

        MCP schema format:
            {
                "name": "search_issues",
                "description": "Search for issues using JQL",
                "inputSchema": {
                    "type": "object",
                    "properties": {...},
                    "required": [...]
                }
            }

        Args:
            mcp_tool: Raw MCP tool schema dict.

        Returns:
            ToolDefinition suitable for passing to the LLM.
        """
        from src.llm.base import ToolDefinition

        raw_name = mcp_tool.get("name", "unknown")
        prefixed_name = f"{self._prefix}_{raw_name}" if self._prefix else raw_name
        # Sanitize: LLM APIs require tool names matching ^[a-zA-Z0-9_-]{1,128}$
        import re
        prefixed_name = re.sub(r"[^a-zA-Z0-9_-]", "_", prefixed_name)[:128]

        description = mcp_tool.get("description", "")

        # MCP uses inputSchema (JSON Schema); OpenAI function calling uses parameters.
        # Pass through the full schema to preserve enum, items, additionalProperties, etc.
        input_schema = mcp_tool.get("inputSchema", {})
        parameters = dict(input_schema) if input_schema else {"type": "object", "properties": {}}

        return ToolDefinition(
            name=prefixed_name,
            description=description,
            parameters=parameters,
        )

    def adapt_schemas(self, mcp_tools: list[dict[str, Any]]) -> list:
        """Batch-convert MCP tool schemas."""
        return [self.adapt_schema(t) for t in mcp_tools]

    def adapt_result(
        self,
        tool_name: str,
        mcp_result: dict[str, Any],
    ):
        """Normalize an MCP tool result into a ToolResult.

        MCP result format:
            {
                "content": [
                    {"type": "text", "text": "..."},
                    {"type": "resource", "resource": {...}}
                ],
                "isError": false
            }

        Truncation is config-driven via max_result_chars / max_result_items.

        Args:
            tool_name: Prefixed tool name.
            mcp_result: Raw MCP result dict.

        Returns:
            Normalized ToolResult.
        """
        from src.tools.base import ToolResult, ToolStatus

        is_error = mcp_result.get("isError", False)
        content_blocks = mcp_result.get("content", [])

        # Extract text content from MCP content blocks
        parts: list[str] = []
        for block in content_blocks:
            block_type = block.get("type", "text")
            if block_type == "text":
                parts.append(block.get("text", ""))
            elif block_type == "resource":
                resource = block.get("resource", {})
                # Include resource URI and text content if available
                uri = resource.get("uri", "")
                text = resource.get("text", "")
                if text:
                    parts.append(text)
                elif uri:
                    parts.append(f"[resource: {uri}]")
            else:
                # Unknown block type - include as JSON for transparency
                parts.append(json.dumps(block))

        output_text = "\n".join(parts)

        # Config-driven truncation
        max_chars = self._config.max_result_chars
        if len(output_text) > max_chars:
            total = len(output_text)
            output_text = output_text[:max_chars] + f"\n[truncated, {total} chars total]"
            logger.info(
                "mcp_result_truncated",
                tool_name=tool_name,
                original_chars=total,
                max_chars=max_chars,
            )

        if is_error:
            return ToolResult(
                tool_name=tool_name,
                status=ToolStatus.ERROR,
                output=None,
                error=output_text or "MCP tool returned an error",
                metadata={"source": "mcp", "provider": self._prefix},
            )

        return ToolResult(
            tool_name=tool_name,
            status=ToolStatus.SUCCESS,
            output=output_text,
            metadata={"source": "mcp", "provider": self._prefix},
        )

    def strip_prefix(self, prefixed_name: str) -> str:
        """Remove the provider prefix from a tool name.

        e.g. "jira_searchJiraIssuesUsingJql" -> "searchJiraIssuesUsingJql"
        """
        if self._prefix and prefixed_name.startswith(f"{self._prefix}_"):
            return prefixed_name[len(self._prefix) + 1 :]
        return prefixed_name
