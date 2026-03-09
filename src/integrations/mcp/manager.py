"""MCP connection lifecycle manager.

Centralized manager for all MCP server connections. Tracks connections
by name, provides async graceful shutdown and sync emergency shutdown,
and aggregates tool definitions across all connections.

Replaces ad-hoc _mcp_client / _mcp_registry attributes on the agent.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

from .client import McpClient
from .config import McpServerConfig
from .registry import McpToolRegistry

if TYPE_CHECKING:
    from src.tools.base import ToolExecutor

try:
    from src.observability import get_logger
    logger = get_logger("integrations.mcp.manager")
except ImportError:
    logger = logging.getLogger(__name__)


@dataclass
class McpConnection:
    """Bundle of objects for a single MCP server connection.

    Attributes:
        name: Connection identifier (e.g. "jira", "github").
        config: Server configuration.
        client: Connected MCP client (owns the transport).
        registry: Tool registry (discovers and caches tool schemas).
        tool_names: Snapshot of prefixed tool names registered in ToolExecutor
                    by this connection. Used for cleanup on disconnect.
    """
    name: str
    config: McpServerConfig
    client: McpClient
    registry: McpToolRegistry
    tool_names: set[str] = field(default_factory=set)


class McpConnectionManager:
    """Manages lifecycle of all MCP server connections.

    Supports multiple named connections with:
    - Async graceful shutdown (await shutdown())
    - Sync emergency shutdown (shutdown_sync()) for on_unmount()
    - Tool approval routing across all connections
    - Aggregated tool definitions for LLM requests
    """

    def __init__(self) -> None:
        self._connections: dict[str, McpConnection] = {}

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(
        self,
        name: str,
        config: McpServerConfig,
        client: McpClient,
        registry: McpToolRegistry,
        tool_executor: ToolExecutor,
        secret_store: Any | None = None,
    ) -> int:
        """Connect to a named MCP server, discover tools, register them.

        Args:
            name: Connection identifier (e.g. "jira").
            config: Server configuration.
            client: McpClient (transport configured but not connected).
            registry: McpToolRegistry (policy gate configured).
            tool_executor: Agent's ToolExecutor to register bridge tools into.
            secret_store: Optional SecretStore for auth token resolution.

        Returns:
            Number of MCP tools registered.

        Raises:
            ValueError: If a connection with this name already exists.
        """
        if name in self._connections:
            raise ValueError(
                f"MCP connection '{name}' already exists. "
                "Disconnect first before reconnecting."
            )

        await client.connect(secret_store=secret_store)
        count = await registry.discover_and_register(client, tool_executor)

        # Snapshot tool names for cleanup on disconnect
        tool_names = set(registry._mcp_tool_names)

        conn = McpConnection(
            name=name,
            config=config,
            client=client,
            registry=registry,
            tool_names=tool_names,
        )
        self._connections[name] = conn

        logger.info(
            "mcp_connection_added",
            connection=name,
            tools_registered=count,
        )
        return count

    async def disconnect(
        self,
        name: str,
        tool_executor: ToolExecutor | None = None,
    ) -> None:
        """Gracefully disconnect a single named connection.

        Args:
            name: Connection identifier.
            tool_executor: If provided, unregisters bridge tools from it.

        Raises:
            KeyError: If connection name not found.
        """
        conn = self._connections.pop(name)

        # Unregister bridge tools from ToolExecutor
        if tool_executor:
            for tool_name in conn.tool_names:
                tool_executor.unregister_tool(tool_name)

        conn.registry.clear()
        await conn.client.disconnect()

        logger.info("mcp_connection_removed", connection=name)

    async def shutdown(
        self,
        tool_executor: ToolExecutor | None = None,
    ) -> None:
        """Gracefully disconnect ALL connections (async).

        Use when the event loop is still running.
        """
        names = list(self._connections.keys())
        for name in names:
            try:
                await self.disconnect(name, tool_executor)
            except Exception as e:
                logger.error(
                    "mcp_shutdown_error",
                    connection=name,
                    error=str(e),
                )

    def shutdown_sync(self) -> None:
        """Emergency synchronous shutdown -- kills subprocesses directly.

        For use in on_unmount() when the event loop may already be closed.
        Directly closes pipes and kills processes without awaiting.
        """
        for name, conn in self._connections.items():
            try:
                conn.client.close_sync()
                conn.registry.clear()
            except Exception as e:
                logger.error(
                    "mcp_sync_shutdown_error",
                    connection=name,
                    error=str(e),
                )

        self._connections.clear()

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    def get_connection(self, name: str) -> McpConnection | None:
        """Get a connection by name, or None."""
        return self._connections.get(name)

    def get_all_tool_definitions(self) -> list:
        """Aggregate tool definitions from all active connections."""
        defs = []
        for conn in self._connections.values():
            defs.extend(conn.registry.get_tool_definitions())
        return defs

    def is_mcp_tool(self, tool_name: str) -> bool:
        """Check if a tool belongs to any MCP connection."""
        return any(
            conn.registry.is_mcp_tool(tool_name)
            for conn in self._connections.values()
        )

    def requires_approval(self, tool_name: str) -> bool:
        """Check if an MCP tool requires user approval.

        Routes to the policy gate of the connection that owns the tool.
        Returns True for unknown tools (safety default).
        """
        for conn in self._connections.values():
            if conn.registry.is_mcp_tool(tool_name):
                return conn.registry.policy_gate.requires_approval(tool_name)
        return True

    @property
    def has_connections(self) -> bool:
        """True if any MCP connections are active."""
        return bool(self._connections)

    @property
    def connection_names(self) -> list[str]:
        """Names of all active connections."""
        return list(self._connections.keys())
