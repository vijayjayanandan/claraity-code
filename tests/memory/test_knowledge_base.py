"""Tests for knowledge base loading and integration."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from src.memory.memory_manager import MemoryManager


# Mock SemanticMemory to avoid needing real embedding API credentials
@pytest.fixture(autouse=True)
def mock_semantic_memory():
    """Patch SemanticMemory for all tests in this module."""
    with patch("src.memory.memory_manager.SemanticMemory") as mock_cls:
        mock_cls.return_value = MagicMock()
        yield mock_cls


_MM_KWARGS = {"load_file_memories": False}


@pytest.fixture
def knowledge_dir(tmp_path, monkeypatch):
    """Create temporary .clarity/knowledge directory."""
    monkeypatch.chdir(tmp_path)
    knowledge_path = tmp_path / ".clarity" / "knowledge"
    knowledge_path.mkdir(parents=True)
    return knowledge_path


class TestKnowledgeBaseLoading:
    """Test knowledge base file loading."""

    def test_load_with_core_only(self, knowledge_dir):
        """Test loading when only core.md exists."""
        core_file = knowledge_dir / "core.md"
        test_content = "# Test Knowledge\n\nThis is test content."
        core_file.write_text(test_content, encoding='utf-8')

        manager = MemoryManager(**_MM_KWARGS)
        knowledge = manager._load_knowledge_base()

        assert knowledge == test_content
        assert "Test Knowledge" in knowledge

    def test_load_all_six_files(self, knowledge_dir):
        """Test loading all 6 knowledge files into combined output."""
        (knowledge_dir / "core.md").write_text(
            "# Core\nProject overview", encoding='utf-8'
        )
        (knowledge_dir / "architecture.md").write_text(
            "# Architecture\nModule map", encoding='utf-8'
        )
        (knowledge_dir / "file-guide.md").write_text(
            "# File Guide\nEntry points", encoding='utf-8'
        )
        (knowledge_dir / "conventions.md").write_text(
            "# Conventions\nALWAYS use get_logger()", encoding='utf-8'
        )
        (knowledge_dir / "decisions.md").write_text(
            "# Decisions\nJSONL for sessions", encoding='utf-8'
        )
        (knowledge_dir / "lessons.md").write_text(
            "# Lessons\nLogging race condition", encoding='utf-8'
        )

        manager = MemoryManager(**_MM_KWARGS)
        knowledge = manager._load_knowledge_base()

        # All 6 files should be present
        assert "Project overview" in knowledge
        assert "Module map" in knowledge
        assert "Entry points" in knowledge
        assert "ALWAYS use get_logger()" in knowledge
        assert "JSONL for sessions" in knowledge
        assert "Logging race condition" in knowledge

        # Sections should be separated by ---
        assert "---" in knowledge

    def test_load_preserves_file_order(self, knowledge_dir):
        """Test that files are combined in the defined order."""
        (knowledge_dir / "core.md").write_text("CORE_MARKER", encoding='utf-8')
        (knowledge_dir / "architecture.md").write_text("ARCH_MARKER", encoding='utf-8')
        (knowledge_dir / "file-guide.md").write_text("FILEGUIDE_MARKER", encoding='utf-8')
        (knowledge_dir / "conventions.md").write_text("CONV_MARKER", encoding='utf-8')
        (knowledge_dir / "decisions.md").write_text("DEC_MARKER", encoding='utf-8')
        (knowledge_dir / "lessons.md").write_text("LES_MARKER", encoding='utf-8')

        manager = MemoryManager(**_MM_KWARGS)
        knowledge = manager._load_knowledge_base()

        # Verify order: core -> architecture -> file-guide -> conventions -> decisions -> lessons
        core_pos = knowledge.index("CORE_MARKER")
        arch_pos = knowledge.index("ARCH_MARKER")
        fg_pos = knowledge.index("FILEGUIDE_MARKER")
        conv_pos = knowledge.index("CONV_MARKER")
        dec_pos = knowledge.index("DEC_MARKER")
        les_pos = knowledge.index("LES_MARKER")

        assert core_pos < arch_pos < fg_pos < conv_pos < dec_pos < les_pos

    def test_load_skips_missing_files(self, knowledge_dir):
        """Test that missing files are skipped without error."""
        (knowledge_dir / "core.md").write_text("Core content", encoding='utf-8')
        # architecture.md, file-guide.md, conventions.md don't exist

        manager = MemoryManager(**_MM_KWARGS)
        knowledge = manager._load_knowledge_base()

        assert "Core content" in knowledge
        # No separator since only one file
        assert "---" not in knowledge

    def test_load_skips_empty_files(self, knowledge_dir):
        """Test that empty files are skipped."""
        (knowledge_dir / "core.md").write_text("Core content", encoding='utf-8')
        (knowledge_dir / "architecture.md").write_text("", encoding='utf-8')
        (knowledge_dir / "conventions.md").write_text("   \n\n  ", encoding='utf-8')

        manager = MemoryManager(**_MM_KWARGS)
        knowledge = manager._load_knowledge_base()

        assert "Core content" in knowledge
        # Empty/whitespace files should not appear
        assert knowledge.count("---") == 0  # Only one section, no separators

    def test_no_knowledge_dir(self, tmp_path, monkeypatch):
        """Test graceful degradation when .clarity/knowledge doesn't exist."""
        monkeypatch.chdir(tmp_path)

        manager = MemoryManager(**_MM_KWARGS)
        knowledge = manager._load_knowledge_base()

        assert knowledge == ""

    def test_large_file_not_truncated(self, knowledge_dir):
        """Test that large files are loaded in full (no truncation)."""
        lines = [f"Line {i}" for i in range(300)]
        (knowledge_dir / "core.md").write_text(
            '\n'.join(lines), encoding='utf-8'
        )

        manager = MemoryManager(**_MM_KWARGS)
        knowledge = manager._load_knowledge_base()

        assert "Line 0" in knowledge
        assert "Line 199" in knowledge
        assert "Line 299" in knowledge
        assert "truncated" not in knowledge

    def test_large_file_logs_warning(self, knowledge_dir):
        """Test that files exceeding _KNOWLEDGE_WARN_LINES trigger a warning log."""
        lines = [f"Line {i}" for i in range(250)]
        (knowledge_dir / "core.md").write_text(
            '\n'.join(lines), encoding='utf-8'
        )

        manager = MemoryManager(**_MM_KWARGS)
        with patch("src.memory.memory_manager.logger") as mock_logger:
            manager._load_knowledge_base()
            mock_logger.warning.assert_called_once_with(
                "Knowledge file exceeds recommended size",
                file="core.md",
                lines=250,
                recommended=MemoryManager._KNOWLEDGE_WARN_LINES,
            )

    def test_caching(self, knowledge_dir):
        """Test that knowledge is cached after first load."""
        (knowledge_dir / "core.md").write_text("Original", encoding='utf-8')

        manager = MemoryManager(**_MM_KWARGS)
        k1 = manager._load_knowledge_base()

        # Modify file on disk
        (knowledge_dir / "core.md").write_text("Modified", encoding='utf-8')

        # Should return cached version
        k2 = manager._load_knowledge_base()

        assert k1 == k2
        assert "Original" in k2

    def test_reload_bypasses_cache(self, knowledge_dir):
        """Test cache invalidation via reload."""
        (knowledge_dir / "core.md").write_text("Original", encoding='utf-8')

        manager = MemoryManager(**_MM_KWARGS)
        k1 = manager._load_knowledge_base()

        (knowledge_dir / "core.md").write_text("Modified", encoding='utf-8')

        k2 = manager.reload_knowledge_base()

        assert "Original" in k1
        assert "Modified" in k2

    def test_ignores_unlisted_files(self, knowledge_dir):
        """Test that files not in _KNOWLEDGE_FILES are not loaded."""
        (knowledge_dir / "core.md").write_text("Core", encoding='utf-8')
        (knowledge_dir / "decisions.md").write_text("Decisions", encoding='utf-8')
        (knowledge_dir / "lessons.md").write_text("Lessons", encoding='utf-8')
        (knowledge_dir / "roadmap.md").write_text("Roadmap", encoding='utf-8')
        (knowledge_dir / "random-notes.md").write_text("Random", encoding='utf-8')

        manager = MemoryManager(**_MM_KWARGS)
        knowledge = manager._load_knowledge_base()

        assert "Core" in knowledge
        assert "Decisions" in knowledge
        assert "Lessons" in knowledge
        # Unlisted files should NOT be loaded
        assert "Roadmap" not in knowledge
        assert "Random" not in knowledge


class TestKnowledgeBaseContextIntegration:
    """Test knowledge base integration with context building.

    Knowledge is now injected by ContextBuilder into the system prompt
    (not as a separate system message from MemoryManager). These tests
    verify get_knowledge_base() returns content for ContextBuilder to use.
    """

    def test_knowledge_available_via_public_api(self, knowledge_dir):
        """Test get_knowledge_base() returns content for context builder."""
        (knowledge_dir / "core.md").write_text(
            "# Project Knowledge\n\nKey constraint: No emojis", encoding='utf-8'
        )

        manager = MemoryManager(**_MM_KWARGS)
        knowledge = manager.get_knowledge_base()

        assert "No emojis" in knowledge

    def test_all_files_in_single_string(self, knowledge_dir):
        """Test all knowledge files combined into one string."""
        (knowledge_dir / "core.md").write_text("CORE", encoding='utf-8')
        (knowledge_dir / "architecture.md").write_text("ARCH", encoding='utf-8')
        (knowledge_dir / "conventions.md").write_text("CONV", encoding='utf-8')

        manager = MemoryManager(**_MM_KWARGS)
        knowledge = manager.get_knowledge_base()

        assert "CORE" in knowledge
        assert "ARCH" in knowledge
        assert "CONV" in knowledge

    def test_no_knowledge_when_no_files(self, tmp_path, monkeypatch):
        """Test empty string when no knowledge files exist."""
        monkeypatch.chdir(tmp_path)

        manager = MemoryManager(**_MM_KWARGS)
        knowledge = manager.get_knowledge_base()

        assert knowledge == ""

    def test_knowledge_not_in_get_context_for_llm(self, knowledge_dir):
        """Test knowledge is NOT injected by get_context_for_llm (context builder handles it)."""
        (knowledge_dir / "core.md").write_text("Project: Test", encoding='utf-8')

        manager = MemoryManager(**_MM_KWARGS)
        context = manager.get_context_for_llm(
            system_prompt="Test system prompt",
            include_file_memories=False,
            include_episodic=False,
        )

        # Knowledge should NOT appear as a separate system message
        for msg in context:
            assert "project knowledge base" not in msg.get("content", "").lower()

    def test_knowledge_uses_project_root_not_cwd(self, tmp_path, monkeypatch):
        """Test knowledge loads from _project_root, not Path.cwd()."""
        # Set cwd to a directory WITHOUT knowledge files
        other_dir = tmp_path / "other"
        other_dir.mkdir()
        monkeypatch.chdir(other_dir)

        # But pass starting_directory pointing to where files ARE
        project_dir = tmp_path / "project"
        kb_dir = project_dir / ".clarity" / "knowledge"
        kb_dir.mkdir(parents=True)
        (kb_dir / "core.md").write_text("FROM_PROJECT_ROOT", encoding='utf-8')

        manager = MemoryManager(
            load_file_memories=False,
            starting_directory=project_dir,
        )
        knowledge = manager.get_knowledge_base()

        assert "FROM_PROJECT_ROOT" in knowledge
