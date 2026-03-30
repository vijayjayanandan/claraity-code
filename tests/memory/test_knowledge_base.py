"""Tests for knowledge DB brief injection into agent context."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from src.core.context_builder import ContextBuilder
from src.memory.memory_manager import MemoryManager


_MM_KWARGS = {"load_file_memories": False}


class TestKnowledgeBriefLoading:
    """Test _load_knowledge_brief in ContextBuilder."""

    def test_returns_empty_when_no_db(self, tmp_path, monkeypatch):
        """No .claraity/claraity_knowledge.db -> empty string."""
        monkeypatch.chdir(tmp_path)
        mm = MemoryManager(**_MM_KWARGS)
        cb = ContextBuilder(mm)
        assert cb._load_knowledge_brief() == ""

    def test_returns_brief_when_db_exists(self, monkeypatch):
        """When DB exists, returns non-empty brief with expected sections."""
        # Use the real project DB
        monkeypatch.chdir(Path(__file__).resolve().parents[2])
        db_path = Path(".claraity/claraity_knowledge.db")
        if not db_path.exists():
            pytest.skip("No knowledge DB in this project")

        mm = MemoryManager(**_MM_KWARGS)
        cb = ContextBuilder(mm)
        brief = cb._load_knowledge_brief()

        assert len(brief) > 0
        assert "## Modules" in brief
        assert "## Decisions" in brief

    def test_handles_corrupt_db_gracefully(self, tmp_path, monkeypatch):
        """Corrupt DB file -> empty string, no exception."""
        monkeypatch.chdir(tmp_path)
        db_dir = tmp_path / ".claraity"
        db_dir.mkdir()
        (db_dir / "claraity_knowledge.db").write_bytes(b"not a sqlite db")

        mm = MemoryManager(**_MM_KWARGS)
        cb = ContextBuilder(mm)
        # Should not raise
        assert cb._load_knowledge_brief() == ""

    def test_brief_injected_into_system_prompt(self, monkeypatch):
        """Brief content appears in the system prompt message."""
        monkeypatch.chdir(Path(__file__).resolve().parents[2])
        db_path = Path(".claraity/claraity_knowledge.db")
        if not db_path.exists():
            pytest.skip("No knowledge DB in this project")

        mm = MemoryManager(**_MM_KWARGS)
        # Agent passes context_window (typically 128K+); default 4096 is unrealistic
        cb = ContextBuilder(mm, max_context_tokens=128000)
        context = cb.build_context(user_query="hello", log_report=False)

        system_msg = context[0]
        assert system_msg["role"] == "system"
        assert "Project Architecture" in system_msg["content"]
        assert "## Modules" in system_msg["content"]


class TestKnowledgeNotInMemoryManager:
    """Verify the old md-file loader was removed from MemoryManager."""

    def test_no_get_knowledge_base(self):
        """MemoryManager should no longer have get_knowledge_base()."""
        assert not hasattr(MemoryManager, "get_knowledge_base")

    def test_no_reload_knowledge_base(self):
        """MemoryManager should no longer have reload_knowledge_base()."""
        assert not hasattr(MemoryManager, "reload_knowledge_base")

    def test_knowledge_not_in_get_context_for_llm(self, tmp_path, monkeypatch):
        """Knowledge is NOT injected by get_context_for_llm (context builder handles it)."""
        monkeypatch.chdir(tmp_path)
        mm = MemoryManager(**_MM_KWARGS)
        context = mm.get_context_for_llm(
            system_prompt="Test system prompt",
            include_file_memories=False,
            include_episodic=False,
        )

        for msg in context:
            assert "project knowledge base" not in msg.get("content", "").lower()
            assert "Project Architecture" not in msg.get("content", "")
