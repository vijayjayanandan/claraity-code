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
]
