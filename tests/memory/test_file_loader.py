"""
Comprehensive tests for MemoryFileLoader.

Tests cover:
- Hierarchical file loading (Enterprise → User → Project)
- Import processing (@syntax)
- Circular import detection
- Quick add functionality
- Project initialization
- Platform-specific paths
"""

import pytest
import platform
from pathlib import Path
from unittest.mock import patch
from src.memory.file_loader import MemoryFileLoader


class TestMemoryFileLoader:
    """Tests for MemoryFileLoader class."""

    @pytest.fixture
    def loader(self):
        """Create a fresh MemoryFileLoader instance."""
        return MemoryFileLoader()

    @pytest.fixture
    def temp_memory_dir(self, tmp_path):
        """Create temporary .opencodeagent directory."""
        memory_dir = tmp_path / ".opencodeagent"
        memory_dir.mkdir()
        return memory_dir

    @pytest.fixture
    def temp_memory_file(self, temp_memory_dir):
        """Create temporary memory.md file."""
        memory_file = temp_memory_dir / "memory.md"
        memory_file.write_text("# Test Memory\n\nSome content\n", encoding="utf-8")
        return memory_file

    # ===== Basic File Loading =====

    def test_load_single_file(self, loader, temp_memory_file):
        """Test loading a single memory file."""
        content = loader._load_file(temp_memory_file)

        assert content != ""
        assert "# Memory from" in content
        assert "Some content" in content
        assert temp_memory_file in loader.loaded_files

    def test_load_file_not_found(self, loader):
        """Test loading non-existent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            loader._load_file(Path("/nonexistent/memory.md"))

    def test_load_file_already_loaded(self, loader, temp_memory_file):
        """Test loading same file twice returns empty on second load."""
        # Load first time
        content1 = loader._load_file(temp_memory_file)
        assert content1 != ""

        # Load second time (should be empty)
        content2 = loader._load_file(temp_memory_file)
        assert content2 == ""

    # ===== Hierarchy Loading =====

    def test_load_hierarchy_project_only(self, loader, tmp_path):
        """Test loading from project directory only."""
        # Create project memory
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        memory_dir = project_dir / ".opencodeagent"
        memory_dir.mkdir()
        memory_file = memory_dir / "memory.md"
        memory_file.write_text("# Project Memory\n\nProject content\n", encoding="utf-8")

        content = loader.load_hierarchy(starting_dir=project_dir)

        assert "Project content" in content
        assert len(loader.loaded_files) == 1

    def test_load_hierarchy_user_and_project(self, loader, tmp_path, monkeypatch):
        """Test loading from user + project hierarchy."""
        # Create user memory
        user_dir = tmp_path / "user"
        user_dir.mkdir()
        user_memory_dir = user_dir / ".opencodeagent"
        user_memory_dir.mkdir()
        user_memory_file = user_memory_dir / "memory.md"
        user_memory_file.write_text("# User Memory\n\nUser content\n", encoding="utf-8")

        # Mock home directory
        monkeypatch.setattr(Path, "home", lambda: user_dir)

        # Create project memory
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        project_memory_dir = project_dir / ".opencodeagent"
        project_memory_dir.mkdir()
        project_memory_file = project_memory_dir / "memory.md"
        project_memory_file.write_text("# Project Memory\n\nProject content\n", encoding="utf-8")

        content = loader.load_hierarchy(starting_dir=project_dir)

        assert "User content" in content
        assert "Project content" in content
        assert len(loader.loaded_files) == 2

    def test_load_hierarchy_empty(self, loader, tmp_path):
        """Test loading with no memory files returns empty string."""
        content = loader.load_hierarchy(starting_dir=tmp_path)
        assert content == ""

    def test_project_hierarchy_traversal(self, loader, tmp_path):
        """Test upward traversal to find project memory."""
        # Create nested structure: root/.opencodeagent/memory.md
        # and start from root/subdir/subsubdir
        root = tmp_path / "root"
        root.mkdir()
        memory_dir = root / ".opencodeagent"
        memory_dir.mkdir()
        memory_file = memory_dir / "memory.md"
        memory_file.write_text("# Root Memory\n\nFound me!\n", encoding="utf-8")

        # Create nested subdirectories
        subsubdir = root / "subdir" / "subsubdir"
        subsubdir.mkdir(parents=True)

        content = loader.load_hierarchy(starting_dir=subsubdir)

        assert "Found me!" in content
        assert memory_file in loader.loaded_files

    # ===== Import Processing =====

    def test_import_relative(self, loader, tmp_path):
        """Test relative import (@./docs/file.md)."""
        # Create main file with relative import
        main_dir = tmp_path / "main"
        main_dir.mkdir()
        main_file = main_dir / "memory.md"
        main_file.write_text("@./docs/imported.md\n# Main Content\n", encoding="utf-8")

        # Create imported file
        docs_dir = main_dir / "docs"
        docs_dir.mkdir()
        imported_file = docs_dir / "imported.md"
        imported_file.write_text("# Imported Content\n\nImported!\n", encoding="utf-8")

        content = loader._load_file(main_file)

        assert "Imported!" in content
        assert "Main Content" in content
        assert imported_file in loader.loaded_files

    def test_import_home(self, loader, tmp_path, monkeypatch):
        """Test home directory import (@~/file.md)."""
        # Mock home directory
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        monkeypatch.setattr(Path, "home", lambda: home_dir)

        # Create main file with home import
        main_dir = tmp_path / "main"
        main_dir.mkdir()
        main_file = main_dir / "memory.md"
        main_file.write_text("@~/preferences.md\n# Main Content\n", encoding="utf-8")

        # Create home file
        home_file = home_dir / "preferences.md"
        home_file.write_text("# My Preferences\n\nHome content!\n", encoding="utf-8")

        content = loader._load_file(main_file)

        assert "Home content!" in content
        assert home_file in loader.loaded_files

    def test_import_absolute(self, loader, tmp_path):
        """Test absolute path import (@/full/path/file.md)."""
        # Create main file with absolute import
        main_dir = tmp_path / "main"
        main_dir.mkdir()
        main_file = main_dir / "memory.md"

        # Create absolute path file
        abs_file = tmp_path / "absolute" / "imported.md"
        abs_file.parent.mkdir()
        abs_file.write_text("# Absolute Content\n\nAbsolute!\n", encoding="utf-8")

        # Use absolute path in import
        main_file.write_text(f"@{abs_file}\n# Main Content\n", encoding="utf-8")

        content = loader._load_file(main_file)

        assert "Absolute!" in content
        assert abs_file in loader.loaded_files

    def test_import_not_found(self, loader, tmp_path):
        """Test import of non-existent file adds comment."""
        main_dir = tmp_path / "main"
        main_dir.mkdir()
        main_file = main_dir / "memory.md"
        main_file.write_text("@./nonexistent.md\n# Main Content\n", encoding="utf-8")

        content = loader._load_file(main_file)

        assert "<!-- Import not found: ./nonexistent.md -->" in content
        assert "Main Content" in content

    def test_circular_import_detection(self, loader, tmp_path):
        """Test circular import detection prevents infinite loop."""
        # Create file A that imports B
        file_a = tmp_path / "a.md"
        file_a.write_text("@./b.md\n# File A\n", encoding="utf-8")

        # Create file B that imports A (circular!)
        file_b = tmp_path / "b.md"
        file_b.write_text("@./a.md\n# File B\n", encoding="utf-8")

        content = loader._load_file(file_a)

        # Should detect circular import (caught as "already loaded" since A is in loaded_files)
        assert "<!-- Import already loaded:" in content
        assert "File A" in content
        assert "File B" in content

    def test_import_already_loaded(self, loader, tmp_path):
        """Test importing already loaded file adds comment."""
        # Create imported file
        imported_file = tmp_path / "imported.md"
        imported_file.write_text("# Imported\n\nContent\n", encoding="utf-8")

        # Load it first
        loader._load_file(imported_file)

        # Create main file that tries to import it
        main_file = tmp_path / "main.md"
        main_file.write_text(f"@{imported_file}\n# Main\n", encoding="utf-8")

        content = loader._load_file(main_file)

        assert "<!-- Import already loaded:" in content

    def test_max_import_depth(self, loader, tmp_path):
        """Test max import depth protection."""
        # Create chain of 10 files (exceeds MAX_IMPORT_DEPTH=5)
        for i in range(10):
            file = tmp_path / f"file{i}.md"
            if i < 9:
                next_file = f"./file{i+1}.md"
                file.write_text(f"@{next_file}\n# File {i}\n", encoding="utf-8")
            else:
                file.write_text(f"# File {i} (deepest)\n", encoding="utf-8")

        # Load first file
        content = loader._load_file(tmp_path / "file0.md")

        # Should stop at max depth
        assert "File 0" in content
        assert "File 4" in content or "File 5" in content
        # Should NOT reach file 9
        assert "File 9" not in content or "deepest" not in content

    # ===== Quick Add =====

    def test_quick_add_new_project_file(self, loader, tmp_path, monkeypatch):
        """Test quick add creates new project memory file."""
        # Change to temp directory
        monkeypatch.chdir(tmp_path)

        text = "Always use 2-space indentation"
        path = loader.quick_add(text, location="project")

        assert path.exists()
        assert path.name == "memory.md"
        assert ".opencodeagent" in str(path)

        content = path.read_text(encoding="utf-8")
        assert "Project Memory" in content
        assert text in content

    def test_quick_add_new_user_file(self, loader, tmp_path, monkeypatch):
        """Test quick add creates new user memory file."""
        # Mock home directory
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        monkeypatch.setattr(Path, "home", lambda: home_dir)

        text = "Prefer descriptive variable names"
        path = loader.quick_add(text, location="user")

        assert path.exists()
        assert path.name == "memory.md"
        assert ".opencodeagent" in str(path)

        content = path.read_text(encoding="utf-8")
        assert "User Memory" in content
        assert text in content

    def test_quick_add_existing_file_with_quick_notes(self, loader, tmp_path, monkeypatch):
        """Test quick add appends to Quick Notes section."""
        monkeypatch.chdir(tmp_path)

        # Create existing file with Quick Notes section
        memory_dir = tmp_path / ".opencodeagent"
        memory_dir.mkdir()
        memory_file = memory_dir / "memory.md"
        memory_file.write_text(
            "# Project Memory\n\n## Quick Notes\nExisting note\n\n## Other Section\nOther content\n",
            encoding="utf-8"
        )

        text = "New quick note"
        loader.quick_add(text, location="project")

        content = memory_file.read_text(encoding="utf-8")
        assert "Existing note" in content
        assert text in content
        # New note should be in Quick Notes section, before Other Section
        quick_notes_idx = content.index("## Quick Notes")
        new_note_idx = content.index(text)
        other_section_idx = content.index("## Other Section")
        assert quick_notes_idx < new_note_idx < other_section_idx

    def test_quick_add_existing_file_without_quick_notes(self, loader, tmp_path, monkeypatch):
        """Test quick add appends to end if no Quick Notes section."""
        monkeypatch.chdir(tmp_path)

        # Create existing file without Quick Notes
        memory_dir = tmp_path / ".opencodeagent"
        memory_dir.mkdir()
        memory_file = memory_dir / "memory.md"
        memory_file.write_text("# Project Memory\n\nExisting content\n", encoding="utf-8")

        text = "Appended note"
        loader.quick_add(text, location="project")

        content = memory_file.read_text(encoding="utf-8")
        assert "Existing content" in content
        assert text in content
        # Should be at the end
        assert content.strip().endswith(text)

    def test_quick_add_invalid_location(self, loader):
        """Test quick add with invalid location raises ValueError."""
        with pytest.raises(ValueError, match="Invalid location"):
            loader.quick_add("text", location="invalid")

    # ===== Project Initialization =====

    def test_init_project_memory(self, loader, tmp_path, monkeypatch):
        """Test initializing project memory with template."""
        monkeypatch.chdir(tmp_path)

        path = loader.init_project_memory()

        assert path.exists()
        assert path.name == "memory.md"
        assert ".opencodeagent" in str(path)

        content = path.read_text(encoding="utf-8")
        assert "# OpenCode Project Memory" in content
        assert "## Project Context" in content
        assert "## Code Standards" in content
        assert "## Development Workflow" in content
        assert "## Architecture" in content

    def test_init_project_memory_custom_path(self, loader, tmp_path):
        """Test initializing project memory at custom path."""
        custom_path = tmp_path / "custom" / ".opencodeagent" / "memory.md"

        path = loader.init_project_memory(path=custom_path)

        assert path.exists()
        assert path == custom_path

    def test_init_project_memory_existing_raises_error(self, loader, tmp_path, monkeypatch):
        """Test initializing existing file raises FileExistsError."""
        monkeypatch.chdir(tmp_path)

        # Create file first
        loader.init_project_memory()

        # Try to create again
        with pytest.raises(FileExistsError):
            loader.init_project_memory()

    # ===== Platform-Specific Paths =====

    @patch('platform.system')
    def test_enterprise_path_linux(self, mock_system, loader):
        """Test enterprise path on Linux."""
        mock_system.return_value = "Linux"
        path = loader._get_enterprise_path()
        assert path == Path("/etc/opencodeagent/memory.md")

    @patch('platform.system')
    def test_enterprise_path_darwin(self, mock_system, loader):
        """Test enterprise path on macOS."""
        mock_system.return_value = "Darwin"
        path = loader._get_enterprise_path()
        assert path == Path("/etc/opencodeagent/memory.md")

    @patch('platform.system')
    def test_enterprise_path_windows(self, mock_system, loader):
        """Test enterprise path on Windows."""
        mock_system.return_value = "Windows"
        path = loader._get_enterprise_path()
        assert path == Path("C:/ProgramData/opencodeagent/memory.md")

    @patch('platform.system')
    def test_enterprise_path_unknown(self, mock_system, loader):
        """Test enterprise path on unknown OS returns None."""
        mock_system.return_value = "Unknown"
        path = loader._get_enterprise_path()
        assert path is None

    # ===== Import Path Resolution =====

    def test_resolve_import_path_relative_current(self, loader, tmp_path):
        """Test resolving ./path import."""
        base_dir = tmp_path / "base"
        base_dir.mkdir()

        resolved = loader._resolve_import_path("./docs/file.md", base_dir)
        expected = (base_dir / "docs" / "file.md").resolve()

        assert resolved == expected

    def test_resolve_import_path_relative_parent(self, loader, tmp_path):
        """Test resolving ../path import."""
        base_dir = tmp_path / "base" / "subdir"
        base_dir.mkdir(parents=True)

        resolved = loader._resolve_import_path("../other/file.md", base_dir)
        expected = (base_dir / ".." / "other" / "file.md").resolve()

        assert resolved == expected

    def test_resolve_import_path_home(self, loader, tmp_path, monkeypatch):
        """Test resolving ~/path import."""
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        monkeypatch.setattr(Path, "home", lambda: home_dir)

        resolved = loader._resolve_import_path("~/docs/file.md", tmp_path)
        expected = (home_dir / "docs" / "file.md").resolve()

        assert resolved == expected

    def test_resolve_import_path_absolute(self, loader, tmp_path):
        """Test resolving /absolute/path import."""
        resolved = loader._resolve_import_path("/etc/config/file.md", tmp_path)
        expected = Path("/etc/config/file.md")

        assert resolved == expected

    def test_resolve_import_path_default_relative(self, loader, tmp_path):
        """Test resolving bare path defaults to relative."""
        base_dir = tmp_path / "base"
        base_dir.mkdir()

        resolved = loader._resolve_import_path("docs/file.md", base_dir)
        expected = (base_dir / "docs" / "file.md").resolve()

        assert resolved == expected

    # ===== Edge Cases =====

    def test_load_file_empty(self, loader, tmp_path):
        """Test loading empty file."""
        empty_file = tmp_path / "empty.md"
        empty_file.write_text("", encoding="utf-8")

        content = loader._load_file(empty_file)

        # Should have header even if file is empty
        assert "# Memory from" in content
        assert empty_file in loader.loaded_files

    def test_process_imports_no_imports(self, loader):
        """Test processing content with no imports."""
        content = "# Regular Content\n\nNo imports here\n"

        processed = loader._process_imports(content, Path("."))

        assert processed == content

    def test_process_imports_mixed_content(self, loader, tmp_path):
        """Test processing content with imports mixed with regular content."""
        # Create imported file
        imported_file = tmp_path / "imported.md"
        imported_file.write_text("# Imported\n\nImported content\n", encoding="utf-8")

        # Create content with import in the middle
        content = f"# Before\n\nBefore import\n\n@{imported_file}\n\n# After\n\nAfter import\n"

        processed = loader._process_imports(content, tmp_path)

        assert "Before import" in processed
        assert "Imported content" in processed
        assert "After import" in processed


class TestMemoryFileLoaderIntegration:
    """Integration tests for complete workflows."""

    def test_full_hierarchy_with_imports(self, tmp_path, monkeypatch):
        """Test complete hierarchy with imports at each level."""
        # Set up home directory
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        monkeypatch.setattr(Path, "home", lambda: home_dir)

        # Create user memory with import
        user_prefs = home_dir / "preferences.md"
        user_prefs.write_text("# User Preferences\n\nI like tabs\n", encoding="utf-8")

        user_memory_dir = home_dir / ".opencodeagent"
        user_memory_dir.mkdir()
        user_memory = user_memory_dir / "memory.md"
        user_memory.write_text(
            f"@{user_prefs}\n# User Memory\n\nUser level\n",
            encoding="utf-8"
        )

        # Create project memory with import
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        project_docs = project_dir / "docs.md"
        project_docs.write_text("# Project Docs\n\nProject info\n", encoding="utf-8")

        project_memory_dir = project_dir / ".opencodeagent"
        project_memory_dir.mkdir()
        project_memory = project_memory_dir / "memory.md"
        # Use @../docs.md to go up from .opencodeagent to project dir
        project_memory.write_text(
            "@../docs.md\n# Project Memory\n\nProject level\n",
            encoding="utf-8"
        )

        # Load hierarchy
        loader = MemoryFileLoader()
        content = loader.load_hierarchy(starting_dir=project_dir)

        # Should have content from all levels and all imports
        assert "User level" in content
        assert "I like tabs" in content
        assert "Project level" in content
        assert "Project info" in content
        assert len(loader.loaded_files) == 4  # user_memory, user_prefs, project_memory, project_docs

    def test_quick_add_then_load(self, tmp_path, monkeypatch):
        """Test quick adding memory then loading it."""
        monkeypatch.chdir(tmp_path)

        loader = MemoryFileLoader()

        # Quick add some memories
        loader.quick_add("Use 2-space indent", location="project")
        loader.quick_add("Test all features", location="project")

        # Load hierarchy
        loader2 = MemoryFileLoader()
        content = loader2.load_hierarchy(starting_dir=tmp_path)

        assert "Use 2-space indent" in content
        assert "Test all features" in content

    def test_init_then_quick_add(self, tmp_path, monkeypatch):
        """Test initializing project then quick adding."""
        monkeypatch.chdir(tmp_path)

        loader = MemoryFileLoader()

        # Initialize
        loader.init_project_memory()

        # Quick add
        loader.quick_add("New quick note", location="project")

        # Load and verify
        loader2 = MemoryFileLoader()
        content = loader2.load_hierarchy(starting_dir=tmp_path)

        assert "OpenCode Project Memory" in content
        assert "New quick note" in content
