"""
PhaseHandler - the inspector badge.

Every phase checkpoint must implement validate_input() and format_output().
"""

from abc import ABC, abstractmethod
from typing import Any, Optional

from ..models import DirectorPhase


class PhaseHandler(ABC):
    """Abstract base for phase handlers."""

    @property
    @abstractmethod
    def phase(self) -> DirectorPhase:
        """Which checkpoint this inspector guards."""
        ...

    @abstractmethod
    def validate_input(self, input_data: Any) -> str | None:
        """Check if input is good enough. Returns None if valid, error string if not."""
        ...

    @abstractmethod
    def format_output(self, raw_output: Any) -> Any:
        """Shape raw data into the structured format for this phase."""
        ...
