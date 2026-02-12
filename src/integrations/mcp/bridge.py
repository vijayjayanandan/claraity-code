"""MCP bridge tool - makes MCP tools executable through ToolExecutor.

McpBridgeTool extends the native Tool base class so it registers in
ToolExecutor identically to native tools. When execute() is called,
it proxies to the McpClient and normalizes the result via McpToolAdapter.

The LLM sees no difference between native and MCP tools.

Event loop strategy:
  The MCP client is async (httpx). ToolExecutor.execute_tool_async() runs
  sync Tool.execute() in a ThreadPoolExecutor worker thread. We use
  asyncio.run_coroutine_threadsafe() to dispatch the async invoke back to
  the ORIGINAL event loop where the transport was connected. This avoids
  the httpx loop-mismatch pitfall (httpx connection pool is bound to the
  loop it was created on).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.llm.base import ToolDefinition

from src.tools.base import Tool, ToolResult, ToolStatus
from .adapter import McpToolAdapter
from .client import McpClient, McpError

try:
    from src.observability import get_logger
    logger = get_logger("integrations.mcp.bridge")
except ImportError:
    logger = logging.getLogger(__name__)


class McpBridgeTool(Tool):
    """Tool subclass that proxies execution to an MCP server.

    Registered in ToolExecutor like any native tool. The execute() method
    dispatches async work back to the event loop that the transport was
    connected on, avoiding loop-mismatch issues with httpx.
    """

    def __init__(
        self,
        client: McpClient,
        adapter: McpToolAdapter,
        tool_definition: ToolDefinition,
        mcp_tool_name: str,
        event_loop: Optional[asyncio.AbstractEventLoop] = None,
    ):
        """Initialize bridge tool.

        Args:
            client: Connected McpClient instance.
            adapter: Adapter for result normalization.
            tool_definition: Adapted ToolDefinition (with prefix).
            mcp_tool_name: Original MCP tool name (without prefix).
            event_loop: The event loop the transport was connected on.
                       If None, falls back to creating a new loop (for testing).
        """
        super().__init__(
            name=tool_definition.name,
            description=tool_definition.description,
        )
        self._client = client
        self._adapter = adapter
        self._tool_def = tool_definition
        self._mcp_tool_name = mcp_tool_name
        self._event_loop = event_loop

    def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the MCP tool via the client.

        When called from ToolExecutor.execute_tool_async() (TUI path), this
        runs in a ThreadPoolExecutor worker thread. We dispatch the async
        invoke back to the original event loop via run_coroutine_threadsafe.
        """
        try:
            return self._invoke_on_loop(kwargs)
        except McpError as e:
            logger.error(
                "mcp_tool_invoke_error",
                tool_name=self.name,
                mcp_error_code=e.code,
                mcp_error_message=e.message,
            )
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"MCP error: {e.message}",
                metadata={"source": "mcp"},
            )
        except Exception as e:
            logger.error(
                "mcp_tool_invoke_exception",
                tool_name=self.name,
                error=str(e),
            )
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"MCP tool execution failed: {str(e)}",
                metadata={"source": "mcp"},
            )

    def _invoke_on_loop(self, kwargs: Dict[str, Any]) -> ToolResult:
        """Dispatch the async invoke to the correct event loop.

        If we have a reference to the original loop (normal TUI path),
        use run_coroutine_threadsafe to keep httpx on its own loop.
        Otherwise fall back to a new loop (testing / sync contexts).

        IMPORTANT: On timeout, the orphaned coroutine MUST be cancelled.
        Otherwise it remains blocked on stdout.readline(), and the next
        tool call gets 'readuntil() called while another coroutine is
        already waiting'.
        """
        import concurrent.futures

        coro = self._async_invoke(kwargs)

        if self._event_loop is not None and self._event_loop.is_running():
            # Dispatch to the original loop and block this worker thread
            future = asyncio.run_coroutine_threadsafe(coro, self._event_loop)
            try:
                return future.result(timeout=self._client.config.invoke_timeout)
            except concurrent.futures.TimeoutError:
                # Cancel the orphaned coroutine so it releases stdout.readline()
                future.cancel()
                raise TimeoutError(
                    f"MCP tool '{self.name}' timed out after "
                    f"{self._client.config.invoke_timeout}s"
                )

        # Fallback: no original loop (testing or pure-sync context)
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    async def _async_invoke(self, kwargs: Dict[str, Any]) -> ToolResult:
        """Async core: invoke MCP tool and normalize result."""
        raw_result = await self._client.invoke(self._mcp_tool_name, kwargs)
        return self._adapter.adapt_result(self.name, raw_result)

    def _get_parameters(self) -> Dict[str, Any]:
        """Return the adapted parameter schema."""
        return self._tool_def.parameters

    def get_schema(self) -> Dict[str, Any]:
        """Return schema matching ToolDefinition format."""
        return {
            "name": self._tool_def.name,
            "description": self._tool_def.description,
            "parameters": self._tool_def.parameters,
        }
