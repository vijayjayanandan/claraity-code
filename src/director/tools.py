"""Director checkpoint tools -- LLM-callable phase transitions.

The checkpoint stations on a movie set: the actor (LLM) walks up,
shows their work, and the stage manager (adapter) validates and
either advances to the next scene or returns an error.

Each tool follows the same pattern as DelegateToSubagentTool:
- __init__(adapter) -- takes adapter reference
- execute(**kwargs) -> ToolResult -- validates, calls adapter, returns result
- _get_parameters() -> dict -- JSON schema the LLM sees
"""

from typing import TYPE_CHECKING, Any, Optional

from src.observability import get_logger
from src.tools.base import Tool, ToolResult, ToolStatus

from .models import (
    ContextDocument,
    DirectorPhase,
    DirectorPlan,
    FileMapping,
    VerticalSlice,
)

if TYPE_CHECKING:
    from .adapter import DirectorAdapter

logger = get_logger(__name__)


class DirectorCompleteUnderstandTool(Tool):
    """Checkpoint for the UNDERSTAND phase.

    Called by the LLM when it has explored the codebase enough to
    describe the task context. Transitions UNDERSTAND -> PLAN.
    """

    def __init__(self, adapter: "DirectorAdapter"):
        self._adapter = adapter
        super().__init__(
            name="director_complete_understand",
            description=(
                "Signal that the UNDERSTAND phase is complete. "
                "Provide your findings: task description, affected files, "
                "existing patterns, and constraints discovered."
            ),
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        """Build ContextDocument from LLM findings and transition to PLAN."""
        # Validate phase
        if self._adapter.phase != DirectorPhase.UNDERSTAND:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=(
                    f"Cannot complete UNDERSTAND: currently in "
                    f"{self._adapter.phase.name} phase. "
                    f"This tool can only be called during UNDERSTAND."
                ),
            )

        # Validate required fields
        task_description = kwargs.get("task_description")
        if not task_description:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error="task_description is required.",
            )

        # Build ContextDocument from LLM-provided data
        affected_files_raw = kwargs.get("affected_files", [])
        affected_files = []
        for f in affected_files_raw:
            if isinstance(f, str):
                affected_files.append(FileMapping(path=f, role="unknown", description=""))
            elif isinstance(f, dict):
                affected_files.append(
                    FileMapping(
                        path=f.get("path", ""),
                        role=f.get("role", "unknown"),
                        description=f.get("description", ""),
                    )
                )

        context = ContextDocument(
            task_description=task_description,
            affected_files=affected_files,
            existing_patterns=kwargs.get("existing_patterns", []),
            constraints=kwargs.get("constraints", []),
            risks=kwargs.get("risks", []),
            dependencies=kwargs.get("dependencies", []),
        )

        try:
            result = self._adapter.complete_understand(context)
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=(
                    f"UNDERSTAND phase complete. "
                    f"Found {len(affected_files)} affected files, "
                    f"{len(context.existing_patterns)} patterns.\n\n"
                    f"You are now in PLAN phase. Your next step:\n"
                    f"- Design the implementation as vertical slices "
                    f"(thin, independently testable increments)\n"
                    f"- Each slice should have a title, files to create/modify, "
                    f"and test criteria\n"
                    f"- Do NOT write code yet\n"
                    f"- When your plan is ready, call `director_complete_plan` "
                    f"with a summary and the list of slices"
                ),
            )
        except Exception as e:
            logger.error(f"director_complete_understand failed: {e}")
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=str(e),
            )

    def _get_parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_description": {
                    "type": "string",
                    "description": "Summary of the task being worked on",
                },
                "affected_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "File paths that will be affected by this task",
                },
                "existing_patterns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Patterns found in the codebase relevant to this task",
                },
                "constraints": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Constraints to respect during implementation",
                },
                "risks": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Risks or potential issues identified",
                },
                "dependencies": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Dependencies relevant to this task",
                },
            },
            "required": ["task_description"],
        }


class DirectorCompletePlanTool(Tool):
    """Checkpoint for the PLAN phase.

    Called by the LLM after it writes a plan document to .clarity/plans/.
    Transitions PLAN -> AWAITING_APPROVAL.
    """

    def __init__(self, adapter: "DirectorAdapter"):
        self._adapter = adapter
        super().__init__(
            name="director_complete_plan",
            description=(
                "Signal that the PLAN phase is complete. "
                "BEFORE calling this, write your full plan (with rationale, "
                "decisions, trade-offs) to .clarity/plans/director_plan.md "
                "using write_file. Then call this with the file path and "
                "a list of slice titles for execution tracking."
            ),
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        """Accept plan document path + slice titles, transition to AWAITING_APPROVAL."""
        logger.info(
            "director_complete_plan called with keys: %s",
            list(kwargs.keys()),
        )

        # Validate phase
        if self._adapter.phase != DirectorPhase.PLAN:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=(
                    f"Cannot complete PLAN: currently in "
                    f"{self._adapter.phase.name} phase. "
                    f"This tool can only be called during PLAN."
                ),
            )

        # Validate plan_document
        plan_document = kwargs.get("plan_document", "")
        if not plan_document:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=(
                    "plan_document is required. First write your full plan to "
                    ".clarity/plans/director_plan.md using write_file, then "
                    "call this tool with the file path."
                ),
            )

        # Verify the plan file exists
        import os

        if not os.path.isfile(plan_document):
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=(
                    f"Plan file not found: {plan_document}. "
                    f"Write the plan file first using write_file, then call this tool."
                ),
            )

        # Validate slices (accept 'slice' as alias)
        slices_raw = kwargs.get("slices") or kwargs.get("slice")
        if not slices_raw:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=(
                    "slices is required. Provide a list of slice titles, "
                    'e.g.: {"slices": [{"title": "Slice 1"}, {"title": "Slice 2"}]}'
                ),
            )

        # Handle string input (LLM may send JSON string)
        if isinstance(slices_raw, str):
            import json as _json

            try:
                slices_raw = _json.loads(slices_raw)
            except (ValueError, TypeError):
                logger.error(
                    "director_complete_plan: slices is unparseable string: %s",
                    slices_raw[:200],
                )

        if not isinstance(slices_raw, list) or len(slices_raw) == 0:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=(
                    "slices must be a non-empty list. "
                    'Example: {"slices": [{"title": "Foundation"}, {"title": "Auth"}]}'
                ),
            )

        # Build VerticalSlices (minimal -- just id + title for tracking)
        slices = []
        for i, s in enumerate(slices_raw, start=1):
            if isinstance(s, dict):
                slices.append(
                    VerticalSlice(
                        id=s.get("id", i),
                        title=s.get("title", f"Slice {i}"),
                        description=s.get("description", ""),
                        files_to_create=s.get("files_to_create", []),
                        files_to_modify=s.get("files_to_modify", []),
                        test_criteria=s.get("test_criteria", []),
                        depends_on=s.get("depends_on", []),
                    )
                )
            elif isinstance(s, str):
                slices.append(VerticalSlice(id=i, title=s))
            else:
                logger.warning(
                    "director_complete_plan: skipping slice %d, type: %s",
                    i,
                    type(s).__name__,
                )

        if not slices:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error="No valid slices found.",
            )

        summary = kwargs.get("summary", "")
        plan = DirectorPlan(
            slices=slices,
            summary=summary,
            plan_document=plan_document,
        )

        try:
            self._adapter.complete_plan(plan)
            slice_summary = ", ".join(f"Slice {s.id}: {s.title}" for s in slices)
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=(
                    f"PLAN phase complete. {len(slices)} vertical slices "
                    f"submitted for approval.\n"
                    f"Plan document: {plan_document}\n"
                    f"Slices: {slice_summary}\n\n"
                    f"You are now in AWAITING_APPROVAL phase.\n"
                    f"- The user will review your plan document and either "
                    f"approve or reject with feedback\n"
                    f"- Do NOT proceed with any code changes\n"
                    f"- If rejected, update the plan document and resubmit"
                ),
            )
        except Exception as e:
            logger.error(f"director_complete_plan failed: {e}")
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=str(e),
            )

    def _get_parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "plan_document": {
                    "type": "string",
                    "description": "Path to the markdown plan file (e.g. .clarity/plans/director_plan.md)",
                },
                "summary": {
                    "type": "string",
                    "description": "Brief one-line summary of the plan",
                },
                "slices": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                        },
                        "required": ["title"],
                    },
                    "description": "list of vertical slices for execution tracking",
                },
            },
            "required": ["plan_document", "slices"],
        }


class DirectorCompleteSliceTool(Tool):
    """Checkpoint for completing a slice during EXECUTE phase.

    Called by the LLM after a slice passes all tests.
    Stays in EXECUTE if more slices remain, transitions to INTEGRATE when all done.
    """

    def __init__(self, adapter: "DirectorAdapter"):
        self._adapter = adapter
        super().__init__(
            name="director_complete_slice",
            description=(
                "Signal that a vertical slice is complete and all tests pass. "
                "Provide the slice ID and a summary of test results."
            ),
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        """Mark slice complete and advance."""
        # Validate phase
        if self._adapter.phase != DirectorPhase.EXECUTE:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=(
                    f"Cannot complete slice: currently in "
                    f"{self._adapter.phase.name} phase. "
                    f"This tool can only be called during EXECUTE."
                ),
            )

        # Validate required fields
        slice_id = kwargs.get("slice_id")
        if slice_id is None:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error="slice_id is required.",
            )

        test_results = kwargs.get("test_results_summary", "")

        try:
            self._adapter.complete_slice(slice_id)

            if self._adapter.phase == DirectorPhase.INTEGRATE:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.SUCCESS,
                    output=(
                        f"Slice {slice_id} complete. All slices done!\n\n"
                        f"You are now in INTEGRATE phase. Your next steps:\n"
                        f"- Run the full test suite to verify no regressions\n"
                        f"- Review cross-slice coherence -- do the pieces "
                        f"fit together correctly?\n"
                        f"- If everything passes, signal completion\n"
                        f"- If there are issues, document them clearly"
                    ),
                )
            else:
                # Determine next slice info
                status = self._adapter.get_status()
                next_id = status.get("current_slice_id", "unknown")
                completed = status.get("completed_slices", 0)
                total = status.get("total_slices", 0)
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.SUCCESS,
                    output=(
                        f"Slice {slice_id} complete ({completed}/{total} done). "
                        f"Tests: {test_results}\n\n"
                        f"Proceeding to slice {next_id}. Your next steps:\n"
                        f"- Follow RED-GREEN-REFACTOR for this slice\n"
                        f"- RED: Write a failing test\n"
                        f"- GREEN: Write minimum code to pass\n"
                        f"- REVIEW: Verify code follows existing patterns\n"
                        f"- When done, call `director_complete_slice` with "
                        f"slice_id={next_id} and test results"
                    ),
                )
        except Exception as e:
            logger.error(f"director_complete_slice failed: {e}")
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=str(e),
            )

    def _get_parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "slice_id": {
                    "type": "integer",
                    "description": "ID of the completed slice",
                },
                "test_results_summary": {
                    "type": "string",
                    "description": "Summary of test results for this slice",
                },
            },
            "required": ["slice_id"],
        }


class DirectorCompleteIntegrationTool(Tool):
    """Checkpoint for the INTEGRATE phase.

    Called by the LLM after running the full test suite and verifying
    cross-slice coherence. Transitions INTEGRATE -> COMPLETE.
    """

    def __init__(self, adapter: "DirectorAdapter"):
        self._adapter = adapter
        super().__init__(
            name="director_complete_integration",
            description=(
                "Signal that integration is complete -- all tests pass "
                "and all slices work together correctly. This finishes "
                "Director mode."
            ),
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        """Mark integration complete and finish Director mode."""
        # Validate phase
        if self._adapter.phase != DirectorPhase.INTEGRATE:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=(
                    f"Cannot complete integration: currently in "
                    f"{self._adapter.phase.name} phase. "
                    f"This tool can only be called during INTEGRATE."
                ),
            )

        test_results = kwargs.get("test_results_summary", "")
        issues = kwargs.get("issues", "")

        try:
            self._adapter.complete_integration()

            output_parts = [
                "Integration complete! Director mode finished.",
                f"Task: {self._adapter._protocol.task_description}",
            ]
            if test_results:
                output_parts.append(f"Final test results: {test_results}")
            if issues:
                output_parts.append(f"Known issues: {issues}")

            plan = self._adapter._protocol.plan
            if plan:
                output_parts.append(
                    f"Slices delivered: {plan.completed_slices}/{plan.total_slices}"
                )

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output="\n".join(output_parts),
            )
        except Exception as e:
            logger.error(f"director_complete_integration failed: {e}")
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=str(e),
            )

    def _get_parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "test_results_summary": {
                    "type": "string",
                    "description": "Summary of the full test suite results",
                },
                "issues": {
                    "type": "string",
                    "description": "Any known issues or notes (empty if none)",
                },
            },
            "required": [],
        }
