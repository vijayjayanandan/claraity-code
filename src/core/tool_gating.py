"""
Tool Gating Service - Centralized tool call gating logic.

Consolidates the five gating checks used by stream_response():

1. Repeat detection: blocks calls that failed with identical args before
2. Plan mode gate: restricts writes when plan mode is active
3. Director gate: restricts writes based on director phase
4. Command safety gate: blocks/escalates dangerous shell commands
5. Approval check: determines if user approval is needed

The command safety gate (check 4) is a safety floor that cannot be bypassed
by auto-approve settings. It runs before the category-based approval check.

Usage:
    gating = ToolGatingService(plan_mode_state, director_adapter,
                               permission_manager, error_tracker, mcp_manager)
    result = gating.evaluate(tool_name, tool_args)
    # result.action tells you what to do: ALLOW, DENY, NEEDS_APPROVAL, BLOCKED_REPEAT
"""

import json
from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING, Any, Optional

from src.observability import get_logger

if TYPE_CHECKING:
    from src.core.error_recovery import ErrorRecoveryTracker
    from src.core.permission_mode import PermissionManager
    from src.core.plan_mode import PlanModeState
    from src.director.adapter import DirectorAdapter
    from src.mcp.connection_manager import McpConnectionManager

logger = get_logger(__name__)


class GateAction(Enum):
    """What the caller should do with this tool call."""

    ALLOW = auto()
    DENY = auto()
    NEEDS_APPROVAL = auto()
    BLOCKED_REPEAT = auto()


@dataclass
class GateResult:
    """Result of evaluating all gating checks for a tool call.

    Attributes:
        action: What the caller should do (ALLOW, DENY, NEEDS_APPROVAL, BLOCKED_REPEAT).
        message: Human-readable explanation (set for DENY/BLOCKED_REPEAT).
        gate_response: Full gated response dict for LLM feedback (set for DENY gates).
        call_summary: Summary of the blocked call (set for BLOCKED_REPEAT).
        safety_reason: If set, this NEEDS_APPROVAL was triggered by the command
            safety floor. The approval UI should show a warning and must NOT
            allow "Yes, allow all" (auto-approve bypass).
    """

    action: GateAction
    message: str | None = None
    gate_response: dict[str, Any] | None = None
    call_summary: str | None = None
    safety_reason: str | None = None


class ToolGatingService:
    """Centralized gating for tool calls.

    Evaluates whether a tool call should be allowed, denied, or
    require user approval. Used by stream_response().
    """

    # Tools that require user approval in NORMAL permission mode
    RISKY_TOOLS = frozenset(
        {
            "write_file",
            "edit_file",
            "append_to_file",
            "run_command",
        }
    )

    # Tool -> category mapping for granular auto-approve
    TOOL_CATEGORIES = {
        "read_file": "read",
        "list_directory": "read",
        "search_code": "read",
        "grep": "read",
        "glob": "read",
        "write_file": "edit",
        "edit_file": "edit",
        "append_to_file": "edit",
        "run_command": "execute",
        "web_search": "browser",
        "web_fetch": "browser",
        "knowledge_update": "knowledge_update",
        "knowledge_scan_files": "knowledge_update",
        "knowledge_set_metadata": "knowledge_update",
        "knowledge_auto_layout": "knowledge_update",
        "knowledge_export": "knowledge_update",
        "delegate_to_subagent": "subagent",
    }

    # Valid category names (for input validation)
    VALID_CATEGORIES = frozenset(
        {"read", "edit", "execute", "browser", "knowledge_update", "subagent"}
    )

    def __init__(
        self,
        plan_mode_state: "PlanModeState",
        director_adapter: "DirectorAdapter",
        permission_manager: Optional["PermissionManager"],
        error_tracker: "ErrorRecoveryTracker",
        mcp_manager: "McpConnectionManager",
    ):
        self._plan_mode_state = plan_mode_state
        self._director_adapter = director_adapter
        self._permission_manager = permission_manager
        self._error_tracker = error_tracker
        self._mcp_manager = mcp_manager
        self._auto_approve_categories: set = {"read"}  # read is safe by default

    # ------------------------------------------------------------------
    # Category auto-approve
    # ------------------------------------------------------------------

    def set_auto_approve_categories(self, categories: dict[str, bool]) -> dict[str, bool]:
        """Set category auto-approve flags. Returns confirmed state."""
        for cat, enabled in categories.items():
            if cat in self.VALID_CATEGORIES:
                if enabled:
                    self._auto_approve_categories.add(cat)
                else:
                    self._auto_approve_categories.discard(cat)
        return self.get_auto_approve_categories()

    def get_auto_approve_categories(self) -> dict[str, bool]:
        """Return all categories with their current auto-approve state."""
        return {cat: cat in self._auto_approve_categories for cat in sorted(self.VALID_CATEGORIES)}

    def is_category_auto_approved(self, tool_name: str) -> bool:
        """Check if a tool's category is auto-approved."""
        cat = self.TOOL_CATEGORIES.get(tool_name)
        return cat is not None and cat in self._auto_approve_categories

    # ------------------------------------------------------------------
    # Individual checks (can be called standalone)
    # ------------------------------------------------------------------

    def check_repeat(self, tool_name: str, tool_args: dict[str, Any]) -> GateResult | None:
        """Check if this exact call has failed before.

        Returns GateResult with BLOCKED_REPEAT if repeated, else None.
        """
        is_repeat, call_summary = self._error_tracker.is_repeated_failed_call(tool_name, tool_args)
        if is_repeat:
            return GateResult(
                action=GateAction.BLOCKED_REPEAT,
                message=(
                    "[BLOCKED] This exact call failed previously. "
                    "You must try a different approach or different arguments."
                ),
                call_summary=call_summary,
            )
        return None

    def check_plan_mode_gate(self, tool_name: str, tool_args: dict[str, Any]) -> GateResult | None:
        """Check if tool is restricted by plan mode.

        Returns GateResult with DENY if gated, else None.
        """
        from src.core.plan_mode import PlanGateDecision

        target_path = tool_args.get("file_path") or tool_args.get("path")
        decision = self._plan_mode_state.gate_tool(tool_name, target_path)

        if decision == PlanGateDecision.DENY:
            response = {
                "status": "denied",
                "error_code": "PLAN_MODE_GATED",
                "message": (
                    f"Tool '{tool_name}' is not allowed in plan mode. "
                    f"Only read-only tools and writing to the plan file are permitted."
                ),
                "plan_path": (
                    str(self._plan_mode_state.plan_file_path)
                    if self._plan_mode_state.plan_file_path
                    else None
                ),
                "allowed_actions": [
                    "Use read-only tools (read_file, grep, glob, etc.)",
                    f"Write to plan file: {self._plan_mode_state.plan_file_path}",
                    "Call request_plan_approval when ready for approval",
                ],
            }
            return GateResult(
                action=GateAction.DENY,
                message=response["message"],
                gate_response=response,
            )

        if decision == PlanGateDecision.REQUIRE_APPROVAL:
            response = {
                "status": "denied",
                "error_code": "PLAN_APPROVAL_REQUIRED",
                "message": (
                    f"Tool '{tool_name}' cannot run until the plan is approved. "
                    f"The plan is awaiting user approval."
                ),
                "plan_path": (
                    str(self._plan_mode_state.plan_file_path)
                    if self._plan_mode_state.plan_file_path
                    else None
                ),
                "allowed_actions": [
                    "Wait for user to approve or reject the plan",
                    "Use read-only tools while waiting",
                ],
            }
            return GateResult(
                action=GateAction.DENY,
                message=response["message"],
                gate_response=response,
            )

        return None  # Allowed

    def check_director_gate(self, tool_name: str, tool_args: dict[str, Any]) -> GateResult | None:
        """Check if tool is restricted by director phase.

        Returns GateResult with DENY if gated, else None.
        """
        if not self._director_adapter.is_active:
            return None

        from src.director.adapter import DirectorGateDecision

        decision = self._director_adapter.gate_tool(tool_name, tool_args)

        if decision == DirectorGateDecision.DENY:
            phase = self._director_adapter.phase.name
            response = {
                "status": "denied",
                "error_code": "DIRECTOR_MODE_GATED",
                "message": (
                    f"Tool '{tool_name}' is not allowed in Director "
                    f"{phase} phase. Use read-only tools or the "
                    f"appropriate director checkpoint tool."
                ),
                "phase": phase,
            }
            return GateResult(
                action=GateAction.DENY,
                message=response["message"],
                gate_response=response,
            )

        return None  # Allowed

    def check_command_safety_gate(
        self, tool_name: str, tool_args: dict[str, Any]
    ) -> GateResult | None:
        """Check command safety for run_command tool calls.

        This is the safety floor that auto-approve cannot bypass.
        Only applies to run_command (other tools have no shell commands).

        Returns:
            GateResult with DENY for BLOCK, NEEDS_APPROVAL (with safety_reason)
            for escalation, or None if safe/not applicable.
        """
        if tool_name != "run_command":
            return None

        command = tool_args.get("command", "")
        if not command:
            # Empty/missing command is caught by execute() validation downstream.
            return None

        from src.tools.command_safety import CommandSafety, check_command_safety

        result = check_command_safety(command)

        if result.safety == CommandSafety.BLOCK:
            return GateResult(
                action=GateAction.DENY,
                message=(
                    f"[BLOCKED] Command rejected by safety controls: {result.reason}\n"
                    "This command cannot be overridden."
                ),
                gate_response={
                    "status": "denied",
                    "error_code": "COMMAND_SAFETY_BLOCK",
                    "message": result.reason,
                    "severity": "block",
                    "pattern": result.pattern_name,
                },
            )

        if result.safety == CommandSafety.NEEDS_APPROVAL:
            return GateResult(
                action=GateAction.NEEDS_APPROVAL,
                message=result.reason,
                safety_reason=result.reason,
            )

        return None

    def needs_approval(self, tool_name: str, tool_args: dict[str, Any] | None = None) -> bool:
        """Determine if a tool call requires user approval.

        Logic depends on the current permission mode:
        - AUTO: never ask
        - PLAN: only MCP write tools
        - NORMAL: risky built-in tools and MCP write tools
        """
        from src.core.permission_mode import PermissionMode
        from src.core.plan_mode import is_agent_internal_write

        mode = (
            self._permission_manager.get_mode()
            if self._permission_manager
            else PermissionMode.NORMAL
        )

        # AUTO mode: never ask
        if mode == PermissionMode.AUTO:
            return False

        # PLAN mode: gating handles built-in tools; only MCP writes need approval
        if mode == PermissionMode.PLAN:
            if self._mcp_manager.is_mcp_tool(tool_name):
                return self._mcp_manager.requires_approval(tool_name)
            return False

        # Agent-internal writes bypass approval (plan files, sessions, logs)
        if tool_args and is_agent_internal_write(tool_name, tool_args):
            return False

        # MCP tools: delegate to policy gate
        if self._mcp_manager.is_mcp_tool(tool_name):
            return self._mcp_manager.requires_approval(tool_name)

        # NORMAL mode: check category auto-approve
        # A tool needs approval if it has a category and that category is not auto-approved,
        # OR if it's in RISKY_TOOLS (legacy fallback for uncategorized risky tools).
        cat = self.TOOL_CATEGORIES.get(tool_name)
        if cat is not None:
            return cat not in self._auto_approve_categories
        if tool_name in self.RISKY_TOOLS:
            return True
        return False

    # ------------------------------------------------------------------
    # Combined evaluation
    # ------------------------------------------------------------------

    def evaluate(self, tool_name: str, tool_args: dict[str, Any]) -> GateResult:
        """Run all gating checks in priority order.

        Order: repeat -> plan mode -> director -> command safety -> approval -> allow.

        The command safety gate (check 4) is a safety floor that fires even
        when auto-approve is enabled for the "execute" category.

        Returns a GateResult indicating what the caller should do.
        """
        # 1. Repeat detection (highest priority)
        result = self.check_repeat(tool_name, tool_args)
        if result:
            return result

        # 2. Plan mode gate
        result = self.check_plan_mode_gate(tool_name, tool_args)
        if result:
            return result

        # 3. Director gate
        result = self.check_director_gate(tool_name, tool_args)
        if result:
            return result

        # 4. Command safety gate (safety floor - cannot be bypassed by auto-approve)
        result = self.check_command_safety_gate(tool_name, tool_args)
        if result:
            return result

        # 5. Category-based approval check
        if self.needs_approval(tool_name, tool_args):
            return GateResult(action=GateAction.NEEDS_APPROVAL)

        # 6. Allowed
        return GateResult(action=GateAction.ALLOW)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def format_gate_response(self, gate_response: dict[str, Any]) -> str:
        """Format a gate response dict as JSON string for LLM feedback."""
        return json.dumps(gate_response, indent=2)
