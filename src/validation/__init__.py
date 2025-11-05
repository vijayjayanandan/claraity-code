"""
Autonomous Validation Framework

This module provides autonomous testing capabilities for the AI Coding Agent.
It spawns agent instances, monitors execution, and evaluates results using
automated checks + Claude-based code review.

Key Components:
- ValidationScenario: Test case definitions
- ValidationOrchestrator: Test execution engine
- ValidationJudge: Claude-based code evaluation
- ValidationRunner: CLI interface

Usage:
    python -m src.validation.run --all
    python -m src.validation.run --scenario easy_cli_weather
"""

from .scenario import (
    ValidationScenario,
    ValidationResult,
    DifficultyLevel,
    ValidationStep,
    SuccessCriteria
)
from .orchestrator import ValidationOrchestrator
from .judge import ValidationJudge
from .scenarios import VALIDATION_SCENARIOS

__all__ = [
    'ValidationScenario',
    'ValidationResult',
    'DifficultyLevel',
    'ValidationStep',
    'SuccessCriteria',
    'ValidationOrchestrator',
    'ValidationJudge',
    'VALIDATION_SCENARIOS',
]
