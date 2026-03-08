"""Tests for UnderstandPhaseHandler.

Slice 4: Quality inspector at checkpoint 1 — validates task input,
transforms raw exploration data into a ContextDocument.
"""

import pytest

from src.director.models import DirectorPhase, ContextDocument, FileMapping


class TestPhaseProperty:
    """Inspector knows which checkpoint it guards."""

    def test_phase_is_understand(self):
        from src.director.phases.understand import UnderstandPhaseHandler
        handler = UnderstandPhaseHandler()
        assert handler.phase == DirectorPhase.UNDERSTAND


class TestValidateInput:
    """Gate check: is the incoming task description usable?"""

    def test_valid_string_returns_none(self):
        from src.director.phases.understand import UnderstandPhaseHandler
        handler = UnderstandPhaseHandler()
        assert handler.validate_input("Add health endpoint") is None

    def test_empty_string_returns_error(self):
        from src.director.phases.understand import UnderstandPhaseHandler
        handler = UnderstandPhaseHandler()
        result = handler.validate_input("")
        assert result is not None
        assert isinstance(result, str)

    def test_whitespace_only_returns_error(self):
        from src.director.phases.understand import UnderstandPhaseHandler
        handler = UnderstandPhaseHandler()
        result = handler.validate_input("   ")
        assert result is not None

    def test_wrong_type_returns_error(self):
        from src.director.phases.understand import UnderstandPhaseHandler
        handler = UnderstandPhaseHandler()
        result = handler.validate_input(42)
        assert result is not None


class TestFormatOutput:
    """Shape raw exploration results into a ContextDocument."""

    def test_passthrough_context_document(self):
        """Already structured — return as-is."""
        from src.director.phases.understand import UnderstandPhaseHandler
        handler = UnderstandPhaseHandler()
        ctx = ContextDocument(task_description="task")
        result = handler.format_output(ctx)
        assert result is ctx

    def test_dict_to_context_document(self):
        """Raw dict from exploration -> structured ContextDocument."""
        from src.director.phases.understand import UnderstandPhaseHandler
        handler = UnderstandPhaseHandler()
        raw = {
            "task_description": "Add health endpoint",
            "affected_files": [
                {"path": "routes.py", "role": "modify", "description": "API routes"}
            ],
            "existing_patterns": ["blueprint pattern"],
            "dependencies": ["flask"],
            "constraints": ["no emojis"],
            "risks": ["breaking routes"],
        }
        result = handler.format_output(raw)
        assert isinstance(result, ContextDocument)
        assert result.task_description == "Add health endpoint"
        assert len(result.affected_files) == 1
        assert result.affected_files[0].path == "routes.py"
        assert result.affected_files[0].role == "modify"
        assert result.existing_patterns == ["blueprint pattern"]
        assert result.dependencies == ["flask"]
        assert result.constraints == ["no emojis"]
        assert result.risks == ["breaking routes"]

    def test_dict_with_missing_optional_fields(self):
        """Missing fields get defaults."""
        from src.director.phases.understand import UnderstandPhaseHandler
        handler = UnderstandPhaseHandler()
        raw = {"task_description": "task"}
        result = handler.format_output(raw)
        assert result.affected_files == []
        assert result.existing_patterns == []
        assert result.dependencies == []

    def test_dict_file_patterns_preserved(self):
        from src.director.phases.understand import UnderstandPhaseHandler
        handler = UnderstandPhaseHandler()
        raw = {
            "task_description": "task",
            "affected_files": [
                {"path": "x.py", "role": "ref", "description": "d", "patterns": ["singleton"]}
            ],
        }
        result = handler.format_output(raw)
        assert result.affected_files[0].patterns == ["singleton"]

    def test_sets_created_at(self):
        from src.director.phases.understand import UnderstandPhaseHandler
        handler = UnderstandPhaseHandler()
        raw = {"task_description": "task"}
        result = handler.format_output(raw)
        assert result.created_at is not None

    def test_invalid_type_raises(self):
        from src.director.phases.understand import UnderstandPhaseHandler
        handler = UnderstandPhaseHandler()
        with pytest.raises(ValueError):
            handler.format_output(42)
