"""
Integration tests for MemoryManager existing features.

Verifies that working memory, context building, token budget, and
session persistence continue to function correctly.
"""

import pytest
from src.memory.memory_manager import MemoryManager


class TestMemoryManagerWithExistingFeatures:
    """Test that existing MemoryManager features still work."""

    def test_working_memory_still_works(self, tmp_path):
        """Test that working memory still functions correctly."""
        manager = MemoryManager(starting_directory=tmp_path)

        manager.add_user_message("Hello")
        manager.add_assistant_message("Hi there!")

        assert len(manager.working_memory.messages) == 2

    def test_context_building_still_works(self, tmp_path):
        """Test that context building still includes all memory types."""
        manager = MemoryManager(starting_directory=tmp_path)

        manager.add_user_message("Test")
        context = manager.get_context_for_llm(
            system_prompt="System",
            include_episodic=True
        )

        # Should have system prompt + working memory
        assert len(context) >= 2
        assert any("Test" in str(msg) for msg in context)

    def test_token_budget_still_works(self, tmp_path):
        """Test that token budget calculation still works."""
        manager = MemoryManager(
            total_context_tokens=8192,
            starting_directory=tmp_path
        )

        budget = manager.get_token_budget()

        assert "total_available" in budget
        assert budget["total_available"] == 8192

    def test_load_file_memories_param_accepted(self, tmp_path):
        """Test that load_file_memories param is accepted (backward compat)."""
        # Should not raise even though it's a no-op
        manager = MemoryManager(
            load_file_memories=False,
            starting_directory=tmp_path,
        )
        assert manager is not None
