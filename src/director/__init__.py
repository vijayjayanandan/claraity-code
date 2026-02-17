"""
Director Protocol - Disciplined software development workflow.

UNDERSTAND -> PLAN -> EXECUTE -> INTEGRATE -> COMPLETE

Usage:
    from src.director import DirectorProtocol, ContextDocument, DirectorPlan

    protocol = DirectorProtocol()
    protocol.start("Add user authentication")
"""

from .models import (
    DirectorPhase,
    SliceStatus,
    FileMapping,
    ContextDocument,
    VerticalSlice,
    DirectorPlan,
    PhaseResult,
)
from .protocol import DirectorProtocol, VALID_TRANSITIONS
from .errors import DirectorError, InvalidTransitionError, PhaseError
from .phases.base import PhaseHandler
from .phases.understand import UnderstandPhaseHandler
from .phases.plan import PlanPhaseHandler
from .adapter import DirectorAdapter, DirectorGateDecision
from .prompts import PHASE_PROMPTS, PHASE_ALLOWED_TOOLS, get_director_phase_prompt
from .tools import (
    DirectorCompleteUnderstandTool,
    DirectorCompletePlanTool,
    DirectorCompleteSliceTool,
    DirectorCompleteIntegrationTool,
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
