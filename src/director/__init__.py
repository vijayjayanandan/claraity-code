"""
Director Protocol - Disciplined software development workflow.

UNDERSTAND -> PLAN -> EXECUTE -> INTEGRATE -> COMPLETE

Usage:
    from src.director import DirectorProtocol, ContextDocument, DirectorPlan

    protocol = DirectorProtocol()
    protocol.start("Add user authentication")
"""

from .adapter import DirectorAdapter, DirectorGateDecision
from .errors import DirectorError, InvalidTransitionError, PhaseError
from .models import (
    ContextDocument,
    DirectorPhase,
    DirectorPlan,
    FileMapping,
    PhaseResult,
    SliceStatus,
    VerticalSlice,
)
from .phases.base import PhaseHandler
from .phases.plan import PlanPhaseHandler
from .phases.understand import UnderstandPhaseHandler
from .prompts import PHASE_ALLOWED_TOOLS, PHASE_PROMPTS, get_director_phase_prompt
from .protocol import VALID_TRANSITIONS, DirectorProtocol
from .tools import (
    DirectorCompleteIntegrationTool,
    DirectorCompletePlanTool,
    DirectorCompleteSliceTool,
    DirectorCompleteUnderstandTool,
)

__all__ = [
    # Core
    "DirectorProtocol",
    "VALID_TRANSITIONS",
    # Models
    "DirectorPhase",
    "SliceStatus",
    "FileMapping",
    "ContextDocument",
    "VerticalSlice",
    "DirectorPlan",
    "PhaseResult",
    # Errors
    "DirectorError",
    "InvalidTransitionError",
    "PhaseError",
    # Phase handlers
    "PhaseHandler",
    "UnderstandPhaseHandler",
    "PlanPhaseHandler",
    # Adapter (Phase 2)
    "DirectorAdapter",
    "DirectorGateDecision",
    # Prompts (Phase 2)
    "PHASE_PROMPTS",
    "PHASE_ALLOWED_TOOLS",
    "get_director_phase_prompt",
    # Tools (Phase 2)
    "DirectorCompleteUnderstandTool",
    "DirectorCompletePlanTool",
    "DirectorCompleteSliceTool",
    "DirectorCompleteIntegrationTool",
]
