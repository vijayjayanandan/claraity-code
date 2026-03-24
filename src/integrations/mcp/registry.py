"""MCP tool registry - merges native and MCP tools.

Session-scoped: one registry per agent instance. Handles discovery,
caching, and provides the merged tool list for LLM requests.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any, Optional

from src.tools.base import ToolExecutor

if TYPE_CHECKING:
    from src.llm.base import ToolDefinition

from .adapter import McpToolAdapter
from .bridge import McpBridgeTool
from .client import McpClient
from .config import McpServerConfig
from .policy import McpPolicyGate

try:
    from src.observability import get_logger

    logger = get_logger("integrations.mcp.registry")
except ImportError:
    logger = logging.getLogger(__name__)


class McpToolRegistry:
    """Manages MCP tool discovery, caching, and registration.

    Lifecycle:
    1. discover() - fetch tools from MCP server, filter through policy gate
    2. register() - create McpBridgeTools and register in ToolExecutor
    3. get_tool_definitions() - return adapted schemas for LLM

    Discovery results are cached with a configurable TTL.
    """

    def __init__(self, config: McpServerConfig, policy_gate: McpPolicyGate):
        self._config = config
        self._policy_gate = policy_gate
        self._adapter = McpToolAdapter(config)
        self._tool_definitions: list[ToolDefinition] = []
        self._mcp_tool_names: set = set()
        self._all_tool_descriptions: dict[str, str] = {}  # raw_name -> description (ALL tools, including disabled)
        self._last_discovery: float = 0.0
        self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    @property
    def policy_gate(self) -> McpPolicyGate:
        return self._policy_gate

    def is_mcp_tool(self, tool_name: str) -> bool:
        """Check if a tool name belongs to MCP (vs native)."""
        return tool_name in self._mcp_tool_names

    def get_tool_definitions(self) -> list[ToolDefinition]:
        """Return adapted MCP tool schemas for LLM requests.

        Only returns tools when the integration is enabled.
        """
        if not self._enabled:
            return []
        return list(self._tool_definitions)

    def _is_cache_valid(self) -> bool:
        """Check if the discovery cache is still fresh."""
        if self._last_discovery == 0.0:
            return False
        elapsed = time.time() - self._last_discovery
        return elapsed < self._config.cache_ttl_seconds

    async def discover_and_register(
        self,
        client: McpClient,
        tool_executor: ToolExecutor,
        disabled_tools: set[str] | None = None,
    ) -> tuple[int, list[str]]:
        """Discover MCP tools and register allowed ones in ToolExecutor.

        Skips discovery if cache is still valid.

        Args:
            client: Connected McpClient.
            tool_executor: ToolExecutor to register bridge tools into.
            disabled_tools: Set of raw MCP tool names to skip (from user config).

        Returns:
            Tuple of (number of tools registered, list of all discovered raw tool names).
        """
        if self._is_cache_valid():
            logger.info(
                "mcp_discovery_cache_hit",
                server=self._config.name,
                cached_tools=len(self._tool_definitions),
            )
            return len(self._tool_definitions), []

        disabled = disabled_tools or set()

        # Fetch raw MCP tool schemas
        raw_tools = await client.list_tools()

        # Collect all discovered tool names and descriptions for settings merge + UI
        all_discovered_names = [t.get("name", "unknown") for t in raw_tools]
        self._all_tool_descriptions = {
            t.get("name", "unknown"): t.get("description", "")
            for t in raw_tools
        }

        # Adapt schemas (adds prefix)
        adapted = self._adapter.adapt_schemas(raw_tools)

        # Filter through policy gate + user visibility config
        registered_count = 0
        self._tool_definitions.clear()
        self._mcp_tool_names.clear()

        for raw_tool, tool_def in zip(raw_tools, adapted, strict=False):
            mcp_name = raw_tool.get("name", "unknown")

            # Check user-level tool visibility first
            if mcp_name in disabled:
                logger.debug("mcp_tool_disabled_by_user", tool_name=tool_def.name, mcp_name=mcp_name)
                continue

            # Register tool in policy gate using MCP annotations
            annotations = raw_tool.get("annotations", {})
            policy = self._policy_gate.register_tool(tool_def.name, annotations)

            if not policy.allowed:
                logger.debug("mcp_tool_filtered", tool_name=tool_def.name)
                continue

            # Create bridge tool and register.
            # Pass the current event loop so the bridge can dispatch async
            # invokes back to the loop the transport was connected on.
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            bridge = McpBridgeTool(
                client=client,
                adapter=self._adapter,
                tool_definition=tool_def,
                mcp_tool_name=mcp_name,
                event_loop=loop,
            )
            tool_executor.register_tool(bridge)

            self._tool_definitions.append(tool_def)
            self._mcp_tool_names.add(tool_def.name)
            registered_count += 1

        self._last_discovery = time.time()
        self._enabled = True

        logger.info(
            "mcp_tools_registered",
            server=self._config.name,
            discovered=len(raw_tools),
            allowed=registered_count,
            blocked=len(raw_tools) - registered_count,
            user_disabled=len(disabled),
        )

        return registered_count, all_discovered_names

    def invalidate_cache(self) -> None:
        """Force re-discovery on next call."""
        self._last_discovery = 0.0

    def clear(self) -> None:
        """Remove all MCP tools (e.g. on disconnect)."""
        self._tool_definitions.clear()
        self._mcp_tool_names.clear()
        self._all_tool_descriptions.clear()
        self._last_discovery = 0.0
        self._enabled = False
