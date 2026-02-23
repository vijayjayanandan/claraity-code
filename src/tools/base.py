"""Base tool interface and executor."""

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from pydantic import BaseModel, Field
from enum import Enum
import time

if TYPE_CHECKING:
    from src.hooks import HookManager, HookDecision, HookBlockedError

# Try to import structured logging with get_logger
try:
    from src.observability import get_logger, ErrorCategory
    logger = get_logger("tools.base")
    STRUCTURED_LOGGING = True
except ImportError:
    # Fallback to stdlib logger
    logger = logging.getLogger(__name__)
    STRUCTURED_LOGGING = False
    class ErrorCategory:
        TOOL_TIMEOUT = 'tool_timeout'
        TOOL_ERROR = 'tool_error'

# =============================================================================
# Tool Timeout Configuration
# =============================================================================
# Global timeout prevents any tool from hanging forever (critical safety net)
# These values apply when wall-time limit is disabled (MAX_WALL_TIME_SECONDS=None)

DEFAULT_TOOL_TIMEOUT_S = 120  # 2 minutes default for most tools

# Per-tool timeout overrides (tools that need more/less time)
TOOL_TIMEOUT_OVERRIDES = {
    # Commands can run long (builds, tests, etc.)
    "run_command": 600,  # 10 minutes

    # Subagent delegation: None disables outer timeout (internal pause handles limits)
    "delegate_to_subagent": None,

    # LSP tools need extra time for server startup (jedi-language-server ~25s)
    "get_file_outline": 90,
    "get_symbol_context": 90,

    # File operations are usually fast, but large files need some buffer
    "write_file": 60,
    "read_file": 30,

    # Search tools can be slow on large codebases
    "search_code": 60,
    "glob_files": 30,

    # Web tools need network time
    "web_search": 45,  # API call + processing
    "web_fetch": 60,   # Large pages can be slow
}


# Tool Exceptions
class ToolNotFoundError(Exception):
    """Tool does not exist in registry."""
    pass


class ToolExecutionError(Exception):
    """Tool execution failed."""
    pass


class ToolStatus(str, Enum):
    """Tool execution status."""

    SUCCESS = "success"
    ERROR = "error"
    PARTIAL = "partial"


class ToolResult(BaseModel):
    """Result from tool execution."""

    tool_name: str
    status: ToolStatus
    output: Any
    error: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def is_success(self) -> bool:
        """Check if execution was successful."""
        return self.status == ToolStatus.SUCCESS


class Tool(ABC):
    """Abstract base class for tools."""

    def __init__(self, name: str, description: str):
        """
        Initialize tool.

        Args:
            name: Tool name
            description: Tool description
        """
        self.name = name
        self.description = description

    @abstractmethod
    def execute(self, **kwargs: Any) -> ToolResult:
        """
        Execute the tool.

        Args:
            **kwargs: Tool-specific parameters

        Returns:
            Tool result
        """
        pass

    def get_schema(self) -> Dict[str, Any]:
        """
        Get tool schema for LLM.

        Returns:
            Tool schema dict
        """
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self._get_parameters()
        }

    @abstractmethod
    def _get_parameters(self) -> Dict[str, Any]:
        """Get parameter schema."""
        pass


class ToolExecutor:
    """Executor for managing and running tools."""

    def __init__(self, hook_manager: Optional['HookManager'] = None, max_workers: int = 4):
        """
        Initialize tool executor.

        Args:
            hook_manager: Optional hook manager for event hooks
            max_workers: Max threads for async tool execution (default: 4)
        """
        self.tools: Dict[str, Tool] = {}
        self.hook_manager = hook_manager
        # ThreadPoolExecutor for running sync tools in async context
        self._executor = ThreadPoolExecutor(max_workers=max_workers)

    def register_tool(self, tool: Tool) -> None:
        """
        Register a tool.

        Args:
            tool: Tool to register
        """
        self.tools[tool.name] = tool

    def unregister_tool(self, tool_name: str) -> None:
        """Remove a tool by name. No-op if not registered."""
        self.tools.pop(tool_name, None)

    def execute_tool(self, tool_name: str, **kwargs: Any) -> ToolResult:
        """
        Execute a tool by name with optional hook integration.

        Performance:
        - Without hooks: 1-10ms (baseline)
        - With hooks: 2-11ms (<1ms hook overhead)

        Args:
            tool_name: Name of tool to execute
            **kwargs: Tool parameters

        Returns:
            Tool result
        """
        # PRE-TOOL-USE HOOK
        if self.hook_manager:
            try:
                from src.hooks import HookDecision, HookBlockedError

                decision, modified_kwargs = self.hook_manager.emit_pre_tool_use(
                    tool=tool_name,
                    arguments=kwargs
                )

                if decision == HookDecision.DENY:
                    return ToolResult(
                        tool_name=tool_name,
                        status=ToolStatus.ERROR,
                        output=None,
                        error="Operation denied by hook"
                    )

                # Use modified arguments if hook modified them
                kwargs = modified_kwargs

            except Exception as e:
                # Check if it's a HookBlockedError
                if e.__class__.__name__ == 'HookBlockedError':
                    return ToolResult(
                        tool_name=tool_name,
                        status=ToolStatus.ERROR,
                        output=None,
                        error=f"Operation blocked by hook: {str(e)}"
                    )
                # Other errors, log and continue
                import logging
                logging.getLogger(__name__).warning(f"PreToolUse hook error: {e}")

        # Check if tool exists
        if tool_name not in self.tools:
            return ToolResult(
                tool_name=tool_name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Tool '{tool_name}' not found"
            )

        tool = self.tools[tool_name]
        start_time = time.time()

        # EXECUTE TOOL
        try:
            result = tool.execute(**kwargs)
            success = result.is_success()
            error = result.error
        except Exception as e:
            result = ToolResult(
                tool_name=tool_name,
                status=ToolStatus.ERROR,
                output=None,
                error=str(e)
            )
            success = False
            error = str(e)

        duration = time.time() - start_time

        # POST-TOOL-USE HOOK
        if self.hook_manager:
            try:
                modified_result = self.hook_manager.emit_post_tool_use(
                    tool=tool_name,
                    arguments=kwargs,
                    result=result.output,
                    success=success,
                    duration=duration,
                    error=error
                )

                # If hook modified the result, use it
                if modified_result is not None:
                    result.output = modified_result

            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"PostToolUse hook error: {e}")

        return result

    async def execute_tool_async(self, tool_name: str, **kwargs: Any) -> ToolResult:
        """
        Execute a tool asynchronously with timeout protection.

        This allows tools to be executed without blocking the asyncio event loop,
        enabling the TUI to remain responsive during tool execution.

        Native async path: If a tool has an `execute_async` method, it is called
        directly on the event loop (no thread pool). This is used by the subprocess
        delegation tool to avoid blocking the event loop entirely.

        Default path: Sync tools are wrapped in run_in_executor (thread pool).

        Safety: Every tool has a timeout to prevent indefinite hangs. This is
        critical when MAX_WALL_TIME_SECONDS is disabled - without per-tool
        timeouts, a hanging tool would freeze the agent forever.

        Args:
            tool_name: Name of tool to execute
            **kwargs: Tool parameters

        Returns:
            Tool result

        Note:
            Timeout is determined by TOOL_TIMEOUT_OVERRIDES or DEFAULT_TOOL_TIMEOUT_S.
            On timeout, returns ToolResult with ERROR status (not exception).
        """
        # Determine timeout for this tool
        timeout_s = TOOL_TIMEOUT_OVERRIDES.get(tool_name, DEFAULT_TOOL_TIMEOUT_S)

        try:
            # Check for native async tool (subprocess delegation)
            tool = self.tools.get(tool_name)
            if tool and hasattr(tool, 'execute_async'):
                # Native async path - runs directly on event loop, no thread pool
                return await asyncio.wait_for(
                    tool.execute_async(**kwargs),
                    timeout=timeout_s,
                )

            # Default: sync tool in thread pool (existing behavior)
            loop = asyncio.get_running_loop()
            return await asyncio.wait_for(
                loop.run_in_executor(
                    self._executor,
                    lambda: self.execute_tool(tool_name, **kwargs)
                ),
                timeout=timeout_s
            )
        except asyncio.TimeoutError:
            # Calculate elapsed time (should be ~timeout_s)
            elapsed_ms = timeout_s * 1000  # Timeout means we hit the limit

            # Log with structlog key=value pattern
            logger.error(
                "tool_timeout",
                category=ErrorCategory.TOOL_TIMEOUT,
                error_type="TimeoutError",
                tool_name=tool_name,
                tool_timeout_s=timeout_s,
                elapsed_ms=elapsed_ms,
                tool_args_keys=json.dumps(list(kwargs.keys())),  # JSON list of arg keys
            )
            return ToolResult(
                tool_name=tool_name,
                status=ToolStatus.ERROR,
                output=None,
                error=(
                    f"Tool timed out after {timeout_s}s. "
                    "Try a simpler operation or break into smaller steps."
                )
            )
        except asyncio.CancelledError:
            # Propagate cancellation cleanly (user interrupt via Ctrl+C)
            logger.info(f"Tool '{tool_name}' was cancelled by user")
            raise
        except Exception as e:
            # Safety net: catch unexpected errors so they get logged and returned
            # as ToolResult rather than propagating unclassified to the agent loop.
            logger.error(
                "tool_unexpected_error",
                category=ErrorCategory.TOOL_ERROR,
                error_type=type(e).__name__,
                tool_name=tool_name,
                error_message=str(e),
            )
            return ToolResult(
                tool_name=tool_name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Unexpected error in tool '{tool_name}': {type(e).__name__}: {e}",
            )

    def shutdown(self) -> None:
        """Shutdown the thread pool executor."""
        self._executor.shutdown(wait=True)

    def get_available_tools(self) -> List[Dict[str, Any]]:
        """
        Get list of available tools with schemas.

        Returns:
            List of tool schemas
        """
        return [tool.get_schema() for tool in self.tools.values()]

    def get_tools_description(self) -> str:
        """
        Get formatted description of all tools.

        Returns:
            Formatted tool descriptions
        """
        descriptions = []
        for tool in self.tools.values():
            descriptions.append(f"- {tool.name}: {tool.description}")

        return "\n".join(descriptions)
