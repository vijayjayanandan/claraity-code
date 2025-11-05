"""
ClarAIty - Real-time Clarity Layer for AI Code Generation

Provides visual clarity during AI code generation and documentation through:
- Architecture visualization (Generate Mode - show plans BEFORE code generation)
- Design decision tracking
- Code artifact mapping
- Relationship management
"""

from .core.blueprint import (
    Blueprint,
    Component,
    DesignDecision,
    FileAction,
    Relationship,
    ComponentType,
    FileActionType,
    RelationType,
)
from .core.generator import ClarityGenerator, ClarityGeneratorError
from .ui.approval import ApprovalServer, ApprovalDecision

__version__ = "0.1.0"

__all__ = [
    # Blueprint data structures
    'Blueprint',
    'Component',
    'DesignDecision',
    'FileAction',
    'Relationship',
    'ComponentType',
    'FileActionType',
    'RelationType',
    # Generator
    'ClarityGenerator',
    'ClarityGeneratorError',
    # UI
    'ApprovalServer',
    'ApprovalDecision',
]
