"""Tests for Director Protocol error hierarchy.

Slice 2: These errors are pure data — no logging, no side effects.
Logging happens in the protocol (Slice 3) which has richer context.
"""

import pytest


class TestDirectorError:
    """DirectorError is the family name for all Director errors."""

    def test_is_exception(self):
        from src.director.errors import DirectorError
        assert issubclass(DirectorError, Exception)

    def test_can_be_raised_and_caught(self):
        from src.director.errors import DirectorError
        with pytest.raises(DirectorError):
            raise DirectorError("something went wrong")

    def test_stores_message(self):
        from src.director.errors import DirectorError
        err = DirectorError("bad thing")
        assert str(err) == "bad thing"


class TestInvalidTransitionError:
    """InvalidTransitionError fires when you try a wrong turn in the state machine."""

    def test_is_director_error(self):
        from src.director.errors import InvalidTransitionError, DirectorError
        assert issubclass(InvalidTransitionError, DirectorError)

    def test_catchable_as_director_error(self):
        """A single 'except DirectorError' catches this too."""
        from src.director.errors import InvalidTransitionError, DirectorError
        from src.director.models import DirectorPhase
        with pytest.raises(DirectorError):
            raise InvalidTransitionError(DirectorPhase.IDLE, DirectorPhase.EXECUTE)

    def test_stores_current_and_attempted_phases(self):
        from src.director.errors import InvalidTransitionError
        from src.director.models import DirectorPhase
        err = InvalidTransitionError(DirectorPhase.IDLE, DirectorPhase.EXECUTE)
        assert err.current == DirectorPhase.IDLE
        assert err.attempted == DirectorPhase.EXECUTE

    def test_message_includes_phase_names(self):
        from src.director.errors import InvalidTransitionError
        from src.director.models import DirectorPhase
        err = InvalidTransitionError(DirectorPhase.PLAN, DirectorPhase.COMPLETE)
        msg = str(err)
        assert "PLAN" in msg
        assert "COMPLETE" in msg


class TestPhaseError:
    """PhaseError fires when a phase itself fails."""

    def test_is_director_error(self):
        from src.director.errors import PhaseError, DirectorError
        assert issubclass(PhaseError, DirectorError)

    def test_catchable_as_director_error(self):
        from src.director.errors import PhaseError, DirectorError
        from src.director.models import DirectorPhase
        with pytest.raises(DirectorError):
            raise PhaseError(DirectorPhase.UNDERSTAND, "codebase too large")

    def test_stores_phase_and_reason(self):
        from src.director.errors import PhaseError
        from src.director.models import DirectorPhase
        err = PhaseError(DirectorPhase.UNDERSTAND, "no files found")
        assert err.phase == DirectorPhase.UNDERSTAND
        assert err.reason == "no files found"

    def test_message_includes_phase_and_reason(self):
        from src.director.errors import PhaseError
        from src.director.models import DirectorPhase
        err = PhaseError(DirectorPhase.PLAN, "empty task")
        msg = str(err)
        assert "PLAN" in msg
        assert "empty task" in msg
