"""
Tests for persistent memory (agent-managed, cross-session).

Tests verify:
- Directory and MEMORY.md auto-creation
- Loading MEMORY.md content at startup
- Injection into LLM context
- Reload after agent writes new memories
- Missing/empty directory handling
"""

import pytest
from pathlib import Path
from src.memory.memory_manager import MemoryManager


class TestPersistentMemoryLoading:
    """Tests for persistent memory load/creation."""

    @pytest.fixture
    def project_dir(self, tmp_path):
        """Create a temporary project directory with .claraity."""
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        claraity_dir = project_dir / ".claraity"
        claraity_dir.mkdir()
        return project_dir

    @pytest.fixture
    def project_with_memories(self, project_dir):
        """Create a project with existing persistent memories."""
        memory_dir = project_dir / ".claraity" / "memory"
        memory_dir.mkdir()

        # Write MEMORY.md index
        index = (
            "# ClarAIty Agent Memory\n\n"
            "- [User Role](user-role.md) -- Senior engineer, prefers plan-first\n"
            "- [No Emojis](feedback-no-emojis.md) -- Windows cp1252 crashes on emoji\n"
        )
        (memory_dir / "MEMORY.md").write_text(index, encoding="utf-8")

        # Write individual memory files
        (memory_dir / "user-role.md").write_text(
            "---\n"
            "name: User Role\n"
            "description: Senior engineer who prefers plan before implementation\n"
            "type: user\n"
            "---\n\n"
            "User is a senior engineer. Always explain plan before writing code.\n",
            encoding="utf-8",
        )
        (memory_dir / "feedback-no-emojis.md").write_text(
            "---\n"
            "name: No Emojis\n"
            "description: Windows cp1252 encoding crashes on emoji characters\n"
            "type: feedback\n"
            "---\n\n"
            "Never use emojis in Python code or log messages.\n"
            "**Why:** Windows console uses cp1252 encoding.\n"
            "**How to apply:** Use [OK], [WARN], [FAIL] text markers.\n",
            encoding="utf-8",
        )
        return project_dir

    def test_auto_creates_directory_and_index(self, project_dir):
        """Startup creates .claraity/memory/ and empty MEMORY.md."""
        manager = MemoryManager(
            load_file_memories=False,
            starting_directory=project_dir,
        )

        memory_dir = project_dir / ".claraity" / "memory"
        index_path = memory_dir / "MEMORY.md"

        assert memory_dir.is_dir()
        assert index_path.is_file()
        assert index_path.read_text(encoding="utf-8").strip() == "# ClarAIty Agent Memory"

    def test_loads_existing_index(self, project_with_memories):
        """Loads MEMORY.md content when it already exists."""
        manager = MemoryManager(
            load_file_memories=False,
            starting_directory=project_with_memories,
        )

        assert "User Role" in manager.persistent_memory_content
        assert "No Emojis" in manager.persistent_memory_content
        assert "Senior engineer" in manager.persistent_memory_content

    def test_empty_index_returns_header_only(self, project_dir):
        """Freshly created MEMORY.md has just the header."""
        manager = MemoryManager(
            load_file_memories=False,
            starting_directory=project_dir,
        )

        assert manager.persistent_memory_content == "# ClarAIty Agent Memory"

    def test_reload_picks_up_changes(self, project_dir):
        """reload_persistent_memory() picks up new content."""
        manager = MemoryManager(
            load_file_memories=False,
            starting_directory=project_dir,
        )

        # Simulate agent writing a new memory
        index_path = project_dir / ".claraity" / "memory" / "MEMORY.md"
        index_path.write_text(
            "# ClarAIty Agent Memory\n\n"
            "- [New Memory](new-memory.md) -- Something learned\n",
            encoding="utf-8",
        )

        # Reload should pick it up
        manager.reload_persistent_memory()
        assert "New Memory" in manager.persistent_memory_content

    def test_persistent_memory_dir_property(self, project_dir):
        """persistent_memory_dir returns correct path."""
        manager = MemoryManager(
            load_file_memories=False,
            starting_directory=project_dir,
        )

        expected = project_dir / ".claraity" / "memory"
        assert manager.persistent_memory_dir == expected


class TestPersistentMemoryContext:
    """Tests for persistent memory injection into LLM context via ContextBuilder."""

    @pytest.fixture
    def project_with_memories(self, tmp_path):
        """Create a project dir with persistent memories."""
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        claraity_dir = project_dir / ".claraity"
        claraity_dir.mkdir()
        memory_dir = claraity_dir / "memory"
        memory_dir.mkdir()

        index = (
            "# ClarAIty Agent Memory\n\n"
            "- [User Role](user-role.md) -- Senior engineer\n"
        )
        (memory_dir / "MEMORY.md").write_text(index, encoding="utf-8")
        return project_dir

    @pytest.fixture
    def builder_with_memories(self, project_with_memories):
        """Create a ContextBuilder with persistent memories loaded."""
        from src.core.context_builder import ContextBuilder
        from src.session.store.memory_store import MessageStore

        manager = MemoryManager(
            load_file_memories=False,
            starting_directory=project_with_memories,
        )
        store = MessageStore()
        manager.set_message_store(store, "test-session")

        builder = ContextBuilder(
            memory_manager=manager,
            max_context_tokens=200000,
            project_root=project_with_memories,
        )
        return builder

    def test_memory_content_reaches_llm_via_build_context(self, builder_with_memories):
        """Persistent memory content is in the system prompt after build_context."""
        context = builder_with_memories.build_context(
            user_query="test", log_report=False,
        )

        # The system prompt (first message) should contain the memory content
        system_prompt = context[0]["content"]
        assert "Senior engineer" in system_prompt

    def test_memory_instructions_in_system_prompt(self, builder_with_memories):
        """Persistent memory management instructions are in the system prompt."""
        context = builder_with_memories.build_context(
            user_query="test", log_report=False,
        )

        system_prompt = context[0]["content"]
        assert "Persistent Memory" in system_prompt
        assert "write_file" in system_prompt
        assert "MEMORY.md" in system_prompt

    def test_memory_dir_path_in_system_prompt(self, builder_with_memories):
        """Memory directory path is included in the system prompt."""
        context = builder_with_memories.build_context(
            user_query="test", log_report=False,
        )

        system_prompt = context[0]["content"]
        assert "memory" in system_prompt.lower()
        assert ".claraity" in system_prompt


class TestPersistentMemoryEdgeCases:
    """Edge case tests."""

    def test_no_claraity_dir(self, tmp_path):
        """Handles missing .claraity directory gracefully."""
        project_dir = tmp_path / "bare_project"
        project_dir.mkdir()

        manager = MemoryManager(
            load_file_memories=False,
            starting_directory=project_dir,
        )

        # Should create .claraity/memory/ even if .claraity didn't exist
        memory_dir = project_dir / ".claraity" / "memory"
        assert memory_dir.is_dir()

    def test_corrupt_index_file(self, tmp_path):
        """Handles unreadable MEMORY.md gracefully."""
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        memory_dir = project_dir / ".claraity" / "memory"
        memory_dir.mkdir(parents=True)

        # Write binary garbage
        (memory_dir / "MEMORY.md").write_bytes(b"\x80\x81\x82\x83")

        manager = MemoryManager(
            load_file_memories=False,
            starting_directory=project_dir,
        )

        # Should not crash, content should be empty
        assert manager.persistent_memory_content == ""

    def test_session_restore_reloads_from_disk(self, tmp_path):
        """On session restore, persistent memory is reloaded from disk (not from saved state)."""
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        memory_dir = project_dir / ".claraity" / "memory"
        memory_dir.mkdir(parents=True)

        # Write initial index
        (memory_dir / "MEMORY.md").write_text(
            "# ClarAIty Agent Memory\n\n- [Old](old.md) -- Old memory\n",
            encoding="utf-8",
        )

        manager = MemoryManager(
            load_file_memories=False,
            starting_directory=project_dir,
        )
        assert "Old" in manager.persistent_memory_content

        # Simulate time passing — memory was updated between sessions
        (memory_dir / "MEMORY.md").write_text(
            "# ClarAIty Agent Memory\n\n- [New](new.md) -- New memory\n",
            encoding="utf-8",
        )

        # Reload (as would happen on session restore)
        manager.reload_persistent_memory()
        assert "New" in manager.persistent_memory_content
        assert "Old" not in manager.persistent_memory_content
