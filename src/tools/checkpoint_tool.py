"""Checkpoint tool for long-running agent sessions."""

from typing import Any, Optional

from .base import Tool, ToolResult, ToolStatus


class CreateCheckpointTool(Tool):
    """Tool for creating checkpoints (save points) in long-running sessions.

    This tool allows the LLM to save the current execution state at logical
    stopping points, enabling:
    - Multi-session workflows (pause and resume work)
    - Crash recovery (restore after failures)
    - Experiment tracking (save different approaches)

    The LLM decides when to checkpoint based on task context (e.g., after
    completing a module, passing tests, or before risky changes).
    """

    _SCHEMA_NAME = "create_checkpoint"

    def __init__(self, controller: Any | None = None):
        """Initialize checkpoint tool.

        Args:
            controller: LongRunningController instance (optional, can be set later)
        """
        from src.tools.tool_schemas import _SCHEMA_REGISTRY
        _def = _SCHEMA_REGISTRY["create_checkpoint"]
        super().__init__(name=_def.name, description=_def.description)
        self.controller = controller

    def set_controller(self, controller: Any) -> None:
        """Set the controller instance.

        Args:
            controller: LongRunningController instance
        """
        self.controller = controller

    def execute(
        self,
        description: str,
        current_phase: str | None = None,
        pending_tasks: list[str] | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        """Create a checkpoint of the current agent state.

        Args:
            description: What was accomplished (e.g., 'Completed auth module')
            current_phase: Optional current development phase (e.g., 'Phase 1')
            pending_tasks: Optional list of tasks remaining to complete
            **kwargs: Additional arguments (ignored)

        Returns:
            ToolResult containing checkpoint ID or error
        """
        try:
            # Validation
            if not description or not description.strip():
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error="description cannot be empty",
                )

            if not self.controller:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error="Controller not initialized. Cannot create checkpoint.",
                )

            # Create checkpoint using controller
            checkpoint_id = self.controller.create_checkpoint(
                description=description, current_phase=current_phase, pending_tasks=pending_tasks
            )

            if checkpoint_id:
                # Success
                output = f"Checkpoint created: {checkpoint_id}\nDescription: {description}"
                if current_phase:
                    output += f"\nPhase: {current_phase}"
                if pending_tasks:
                    output += f"\nPending tasks: {len(pending_tasks)}"

                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.SUCCESS,
                    output=output,
                    metadata={
                        "checkpoint_id": checkpoint_id,
                        "description": description,
                        "current_phase": current_phase,
                        "pending_tasks_count": len(pending_tasks) if pending_tasks else 0,
                    },
                )
            else:
                # Checkpoint creation failed
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error="Failed to create checkpoint (controller returned None)",
                )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Checkpoint creation failed: {str(e)}",
            )


