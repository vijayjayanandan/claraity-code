"""Workflow management for the coding agent.

This module provides intelligent workflow orchestration including:
- Task analysis and classification
- Execution planning with LLM
- Step-by-step execution with progress tracking
- Verification and validation
- Error recovery strategies
"""

from .task_analyzer import (
    TaskAnalyzer,
    TaskAnalysis,
    TaskType,
    TaskComplexity,
)
from .task_planner import (
    TaskPlanner,
    ExecutionPlan,
    PlanStep,
    ActionType,
)
from .execution_engine import (
    ExecutionEngine,
    ExecutionResult,
    StepResult,
)
from .verification_layer import (
    VerificationLayer,
    VerificationResult,
    VerificationError,
    VerificationSeverity,
)
from .permission_manager import (
    PermissionManager,
    PermissionMode,
    ApprovalDecision,
)

__all__ = [
    "TaskAnalyzer",
    "TaskAnalysis",
    "TaskType",
    "TaskComplexity",
    "TaskPlanner",
    "ExecutionPlan",
    "PlanStep",
    "ActionType",
    "ExecutionEngine",
    "ExecutionResult",
    "StepResult",
    "VerificationLayer",
    "VerificationResult",
    "VerificationError",
    "VerificationSeverity",
    "PermissionManager",
    "PermissionMode",
    "ApprovalDecision",
]

__version__ = "0.1.0"
