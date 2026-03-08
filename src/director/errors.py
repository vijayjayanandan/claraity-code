"""
Error hierarchy for the Director Protocol.

Pure data — no logging, no side effects.
The protocol (protocol.py) logs errors with full context.
"""


class DirectorError(Exception):
    """Base exception for all Director Protocol errors."""
    pass


class InvalidTransitionError(DirectorError):
    """Raised when attempting an invalid state transition."""

    def __init__(self, current, attempted):
        self.current = current
        self.attempted = attempted
        super().__init__(
            f"Invalid transition: {current.name} -> {attempted.name}"
        )


class PhaseError(DirectorError):
    """Raised when a phase fails to complete."""

    def __init__(self, phase, reason):
        self.phase = phase
        self.reason = reason
        super().__init__(f"Phase {phase.name} failed: {reason}")
