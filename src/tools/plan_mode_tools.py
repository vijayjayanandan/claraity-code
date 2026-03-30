"""
Plan Mode Tools - Enter/exit plan mode for structured planning workflow.

These tools allow the LLM to:
1. Enter plan mode (create plan file, restrict to read-only tools)
2. Exit plan mode (submit plan for user approval)

The tools interact with the agent's PlanModeState and persist events
to MessageStore for UI rendering and session resume.
"""

from typing import TYPE_CHECKING, Any

from .base import Tool, ToolResult, ToolStatus

if TYPE_CHECKING:
    from src.core.plan_mode import PlanModeState


class EnterPlanModeTool(Tool):
    """
    Tool for entering plan mode.

    When called, this tool:
    1. Creates a plan file at .claraity/plans/<session_id>.md
    2. Activates read-only restrictions (only read tools + plan file writes allowed)
    3. Returns the plan file path for the LLM to write to
    """

    def __init__(self, plan_mode_state: "PlanModeState" = None, session_id: str = None):
        """
        Initialize EnterPlanMode tool.

        Args:
            plan_mode_state: The PlanModeState instance to use
            session_id: Current session ID for plan file naming
        """
        super().__init__(
            name="enter_plan_mode",
            description=(
                "Enter plan mode to design an implementation approach before making changes. "
                "Creates a plan file where you write your implementation plan. "
                "While in plan mode, only read-only tools are available (plus writing to the plan file). "
                "Use this for complex tasks that benefit from upfront planning."
            ),
        )
        self.plan_mode_state = plan_mode_state
        self.session_id = session_id

    def execute(self, reason: str = "", **kwargs: Any) -> ToolResult:
        """
        Enter plan mode.

        Args:
            reason: Optional reason for entering plan mode (shown in UI)

        Returns:
            ToolResult with plan file path and instructions
        """
        if self.plan_mode_state is None:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error="Plan mode not initialized",
            )

        if self.session_id is None:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error="Session ID not set",
            )

        if self.plan_mode_state.is_active:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Already in plan mode. Plan file: {self.plan_mode_state.plan_file_path}",
            )

        try:
            result = self.plan_mode_state.enter(self.session_id)

            instructions = (
                "You are now in PLAN MODE.\n\n"
                "WORKFLOW:\n"
                "1. EXPLORE: Use read-only tools to understand the codebase\n"
                "2. DESIGN: Analyze patterns and consider approaches\n"
                "3. WRITE PLAN: Write your implementation plan to the plan file\n"
                "4. REQUEST APPROVAL: Call request_plan_approval when ready for user approval\n\n"
                "CONSTRAINTS:\n"
                "- Only read-only tools are allowed\n"
                "- You may only write to the plan file\n"
                "- Do NOT make code changes until plan is approved\n\n"
                f"PLAN FILE: {result['plan_path']}"
            )

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=instructions,
                metadata={
                    "plan_path": result["plan_path"],
                    "reason": reason,
                    "event_type": "plan_mode_entered",
                },
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to enter plan mode: {str(e)}",
            )

    def _get_parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Brief reason for entering plan mode (e.g., 'Complex refactoring with multiple dependencies')",
                }
            },
            "required": [],
        }


class RequestPlanApprovalTool(Tool):
    """
    Tool for requesting user approval of the implementation plan.

    When called, this tool:
    1. Computes a hash of the plan content (for approval verification)
    2. Prepares a truncated excerpt for context injection
    3. Shows the plan to the user and requests approval
    4. Returns the approval decision (approved/rejected with feedback)
    """

    def __init__(self, plan_mode_state: "PlanModeState" = None):
        """
        Initialize RequestPlanApproval tool.

        Args:
            plan_mode_state: The PlanModeState instance to use
        """
        super().__init__(
            name="request_plan_approval",
            description=(
                "Submit your implementation plan to the user for approval. "
                "Call this after writing your plan to the plan file. "
                "The user will review and either approve the plan, reject it, or provide feedback for revisions."
            ),
        )
        self.plan_mode_state = plan_mode_state

    def execute(self, **kwargs: Any) -> ToolResult:
        """
        Request plan approval from user.

        Returns:
            ToolResult with plan hash and approval instructions
        """
        if self.plan_mode_state is None:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error="Plan mode not initialized",
            )

        if not self.plan_mode_state.is_active:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error="Not currently in plan mode. Use enter_plan_mode first.",
            )

        try:
            result = self.plan_mode_state.exit_for_approval()

            if "error" in result:
                return ToolResult(
                    tool_name=self.name, status=ToolStatus.ERROR, output=None, error=result["error"]
                )

            output = (
                "Requesting user approval for implementation plan...\n\n"
                f"Plan file: {result['plan_path']}\n"
                f"Plan hash: {result['plan_hash'][:8]}...\n\n"
                "User will review the plan and either:\n"
                "1. Approve it (with manual or auto-accept edits)\n"
                "2. Reject it with feedback for revisions\n"
                "3. Cancel (reject without feedback)"
            )

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=output,
                metadata={
                    "plan_hash": result["plan_hash"],
                    "plan_path": result["plan_path"],
                    "excerpt": result["excerpt"],
                    "truncated": result["truncated"],
                    "event_type": "plan_submitted",
                    "requires_user_approval": True,
                },
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to request plan approval: {str(e)}",
            )

    def _get_parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}


# Export all
__all__ = [
    "EnterPlanModeTool",
    "RequestPlanApprovalTool",
]
