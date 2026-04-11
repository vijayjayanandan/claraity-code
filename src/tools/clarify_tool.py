"""
Clarify Tool - Ask user clarifying questions before proceeding with ambiguous tasks.

In TUI mode, the SpecialToolHandlers + ClarifyWidget handle the interactive UI.
The execute() method is only called in non-interactive contexts (subagents, tests).
"""

from typing import Any

from .base import Tool, ToolResult


class ClarifyTool(Tool):
    """
    Tool for asking structured clarifying questions.

    In TUI mode: Agent persists clarify_request, waits on UIProtocol,
    and the ClarifyWidget handles interaction via SpecialToolHandlers.
    """

    _SCHEMA_NAME = "clarify"

    def __init__(self):
        from src.tools.tool_schemas import _SCHEMA_REGISTRY
        _def = _SCHEMA_REGISTRY["clarify"]
        super().__init__(name=_def.name, description=_def.description)

    def execute(self, **kwargs) -> ToolResult:
        """
        Execute clarify tool (non-interactive fallback).

        In TUI mode this is never called directly - SpecialToolHandlers
        intercepts it. This path only runs in tests or subagent contexts.

        Returns:
            ToolResult indicating that interactive clarification is required
        """
        questions = kwargs.get("questions", [])

        # Validate
        if not questions:
            return ToolResult(success=False, output="", error="clarify.questions is empty")

        if len(questions) > 4:
            return ToolResult(
                success=False,
                output="",
                error="clarify.questions has more than 4 questions (max: 4)",
            )

        # Non-interactive: return questions as-is for the caller to handle
        return ToolResult(
            success=True, output=str({"questions": questions, "needs_interactive_response": True})
        )


# Export
__all__ = ["ClarifyTool"]
