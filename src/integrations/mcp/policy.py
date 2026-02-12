"""MCP tool policy gate.

Controls which MCP tools are exposed to the LLM and which require approval.

Two-layer security:
1. Blocklist: specific tools can be blocked (default-allow everything else)
2. Read/write classification: derived from MCP tool annotations
   (readOnlyHint, destructiveHint). Write tools require user approval.

Annotations are provided by the MCP server at discovery time. If a tool
has no annotations, it is conservatively treated as a write tool.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

try:
    from src.observability import get_logger
    logger = get_logger("integrations.mcp.policy")
except ImportError:
    logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolPolicy:
    """Policy for a single MCP tool, derived from server annotations.

    Attributes:
        allowed: Whether the tool is exposed to the LLM at all.
        requires_approval: Whether execution needs user confirmation.
        is_write: Whether this tool modifies external state.
        is_destructive: Whether this tool performs destructive operations.
        description_override: Optional override for MCP-provided description.
    """
    allowed: bool = True
    requires_approval: bool = False
    is_write: bool = False
    is_destructive: bool = False
    description_override: str = ""

    @classmethod
    def from_annotations(
        cls,
        annotations: Dict[str, Any],
        blocked: bool = False,
    ) -> "ToolPolicy":
        """Build a ToolPolicy from MCP tool annotations.

        MCP annotations schema:
            readOnlyHint: bool   - tool does not modify state
            destructiveHint: bool - tool may perform destructive operations
            idempotentHint: bool  - same args = same effect
            openWorldHint: bool   - interacts with external entities

        Conservative defaults: if annotations are missing, assume write.
        """
        read_only = annotations.get("readOnlyHint", False)
        destructive = annotations.get("destructiveHint", False)

        is_write = not read_only
        # Write tools require approval; destructive tools always require approval
        needs_approval = is_write or destructive

        return cls(
            allowed=not blocked,
            requires_approval=needs_approval,
            is_write=is_write,
            is_destructive=destructive,
        )


class McpPolicyGate:
    """Enforces policy on MCP tools using server-provided annotations.

    Default-allow: all discovered tools are allowed unless explicitly blocked.
    Read/write classification comes from MCP annotations, not hardcoded names.
    """

    def __init__(self, blocklist: Optional[Set[str]] = None):
        """Initialize with an optional blocklist.

        Args:
            blocklist: Set of prefixed tool names to block.
                      e.g. {"jira_admin_danger", "jira_delete_project"}
        """
        self._blocklist: Set[str] = set(blocklist) if blocklist else set()
        self._policies: Dict[str, ToolPolicy] = {}

    @property
    def policies(self) -> Dict[str, ToolPolicy]:
        return dict(self._policies)

    def register_tool(
        self,
        prefixed_name: str,
        annotations: Dict[str, Any],
    ) -> ToolPolicy:
        """Register a discovered tool and build its policy from annotations.

        Called during discovery for each tool returned by the MCP server.

        Args:
            prefixed_name: Namespaced tool name (e.g. "jira_searchJiraIssuesUsingJql")
            annotations: MCP annotations dict from the tool schema.

        Returns:
            The computed ToolPolicy for this tool.
        """
        blocked = prefixed_name in self._blocklist
        policy = ToolPolicy.from_annotations(annotations, blocked=blocked)
        self._policies[prefixed_name] = policy

        if blocked:
            logger.info("mcp_tool_blocked", tool_name=prefixed_name)
        elif policy.is_write:
            logger.debug(
                "mcp_tool_registered_write",
                tool_name=prefixed_name,
                requires_approval=policy.requires_approval,
            )
        else:
            logger.debug("mcp_tool_registered_read", tool_name=prefixed_name)

        return policy

    def is_allowed(self, tool_name: str) -> bool:
        """Check if a tool is allowed.

        Tools not yet registered (not discovered) are blocked.
        Registered tools are allowed unless explicitly blocklisted.
        """
        policy = self._policies.get(tool_name)
        if policy is None:
            logger.debug("mcp_tool_not_registered", tool_name=tool_name)
            return False
        return policy.allowed

    def requires_approval(self, tool_name: str) -> bool:
        """Check if a tool requires user approval before execution."""
        policy = self._policies.get(tool_name)
        if policy is None:
            # Unknown tools should never execute, but if they somehow do, require approval
            return True
        return policy.requires_approval

    def is_write_tool(self, tool_name: str) -> bool:
        """Check if a tool modifies external state."""
        policy = self._policies.get(tool_name)
        if policy is None:
            return True  # Assume write if unknown
        return policy.is_write

    def filter_allowed(self, tool_names: list) -> list:
        """Filter a list of tool names to only allowed ones."""
        return [name for name in tool_names if self.is_allowed(name)]

    def get_description_override(self, tool_name: str) -> str:
        """Get description override for a tool, if any."""
        policy = self._policies.get(tool_name)
        if policy:
            return policy.description_override
        return ""

    def clear(self) -> None:
        """Remove all registered policies (e.g. on disconnect)."""
        self._policies.clear()
