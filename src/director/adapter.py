"""Director Adapter -- the stage manager.

Thin wrapper around DirectorProtocol that adds:
1. Tool gating -- controls what the LLM can do per phase
2. Prompt injection -- controls what the LLM is told per phase

Follows the same architecture as PlanModeState in plan_mode.py.
"""

from enum import Enum
from typing import Any, Dict, Optional

from src.observability import get_logger

from .models import (
    ContextDocument,
    DirectorPhase,
    DirectorPlan,
    PhaseResult,
)
from .prompts import (
    PHASE_ALLOWED_TOOLS,
    get_director_phase_prompt,
)
from .protocol import DirectorProtocol

logger = get_logger(__name__)


class DirectorGateDecision(Enum):
    """Decision from tool gating in director mode."""
    ALLOW = "allow"
    DENY = "deny"


class DirectorAdapter:
    """Bridges the Director Protocol state machine to the agent.

    Usage:
        adapter = DirectorAdapter()

        adapter.start("Add user authentication")
        # Now in UNDERSTAND phase -- read-only tools allowed

        adapter.gate_tool("write_file")   # -> DENY
        adapter.gate_tool("read_file")    # -> ALLOW
        adapter.get_prompt_injection()    # -> "You are in UNDERSTAND mode..."
    """

    def __init__(self) -> None:
        self._protocol = DirectorProtocol()
        self._current_slice_id: Optional[int] = None

    # -- Properties (proxied from protocol) --

    @property
    def is_active(self) -> bool:
        return self._protocol.is_active

    @property
    def phase(self) -> DirectorPhase:
        return self._protocol.phase

    # -- Activation --

    def start(self, task_description: str) -> None:
        """Activate director mode for a task."""
        self._protocol.start(task_description)
        self._current_slice_id = None
        logger.info(
            "director_adapter_started",
            task=task_description,
        )

    # -- Tool Gating --

    def gate_tool(
        self, tool_name: str, tool_args: Optional[Dict[str, Any]] = None,
    ) -> DirectorGateDecision:
        """Check if a tool is allowed in the current phase.

        When director is inactive (IDLE/COMPLETE/FAILED), all tools
        are allowed -- zero impact on normal agent behavior.

        Special case: write_file is allowed in PLAN phase ONLY for
        .clarity/plans/ paths (so the LLM can write its plan document).

        Args:
            tool_name: Name of the tool being called
            tool_args: Tool arguments (used for path-based gating)

        Returns:
            ALLOW or DENY
        """
        if not self.is_active:
            return DirectorGateDecision.ALLOW

        allowed = PHASE_ALLOWED_TOOLS.get(self._protocol.phase)
        if allowed is None:
            # Phase has no allowlist (shouldn't happen for active phases)
            return DirectorGateDecision.ALLOW

        if tool_name in allowed:
            return DirectorGateDecision.ALLOW

        # Path-based exception: write_file allowed in PLAN for plan docs
        if (
            tool_name == "write_file"
            and self._protocol.phase == DirectorPhase.PLAN
            and tool_args
        ):
            file_path = tool_args.get("file_path", "")
            # Normalize path separators for cross-platform
            normalized = file_path.replace("\\", "/")
            if ".clarity/plans/" in normalized:
                logger.debug(
                    "director_write_allowed_for_plan_doc",
                    path=file_path,
                )
                return DirectorGateDecision.ALLOW

        logger.debug(
            "director_tool_gated",
            tool=tool_name,
            phase=self._protocol.phase.name,
        )
        return DirectorGateDecision.DENY

    # -- Prompt Injection --

    def get_prompt_injection(self) -> Optional[str]:
        """Get the system prompt injection for the current phase.

        Returns None when director is inactive.
        """
        if not self.is_active:
            return None

        return get_director_phase_prompt(
            phase=self._protocol.phase,
            task_description=self._protocol.task_description or "",
            context=self._protocol.context,
            plan=self._protocol.plan,
            current_slice_id=self._current_slice_id,
        )

    # -- Phase Transitions (proxied to protocol) --

    def complete_understand(self, context: ContextDocument) -> PhaseResult:
        """UNDERSTAND -> PLAN."""
        return self._protocol.complete_understand(context)

    def complete_plan(self, plan: DirectorPlan) -> PhaseResult:
        """PLAN -> AWAITING_APPROVAL."""
        return self._protocol.complete_plan(plan)

    def approve_plan(self) -> None:
        """AWAITING_APPROVAL -> EXECUTE."""
        self._protocol.approve_plan()
        # Set first slice as current
        if self._protocol.plan and self._protocol.plan.slices:
            self._current_slice_id = self._protocol.plan.slices[0].id

    def reject_plan(self, feedback: Optional[str] = None) -> None:
        """AWAITING_APPROVAL -> PLAN (revision cycle)."""
        self._protocol.reject_plan(feedback)

    def complete_slice(self, slice_id: int) -> None:
        """Mark a slice as completed and advance to next slice or INTEGRATE."""
        if self._protocol.plan:
            # Mark slice done
            for s in self._protocol.plan.slices:
                if s.id == slice_id:
                    from .models import SliceStatus
                    s.status = SliceStatus.COMPLETED
                    break

            # Find next pending slice
            next_slice = None
            for s in self._protocol.plan.slices:
                if s.status.name == "PENDING":
                    next_slice = s
                    break

            if next_slice:
                self._current_slice_id = next_slice.id
            else:
                # All slices done -- transition to INTEGRATE
                self._current_slice_id = None
                self._protocol._transition(DirectorPhase.INTEGRATE)

    def complete_integration(self) -> PhaseResult:
        """INTEGRATE -> COMPLETE. The final curtain."""
        result = self._protocol.complete_integration()
        logger.info("director_integration_complete")
        return result

    def reset(self) -> None:
        """Emergency stop -- return to IDLE."""
        self._protocol.reset()
        self._current_slice_id = None
        logger.info("director_adapter_reset")

    # -- Status --

    def get_status(self) -> Dict[str, Any]:
        """Dashboard readout."""
        status = self._protocol.get_status()
        status["current_slice_id"] = self._current_slice_id
        return status
