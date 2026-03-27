# Claude Code Integration Roadmap

**Project:** AI Coding Agent - Claude Code Architecture Integration
**Timeline:** 10-12 weeks
**Start Date:** 2025-10-17
**Status:** Planning Phase
**Approach:** Hybrid architecture (keep our advantages, add Claude Code UX innovations)

---

## 📊 OVERVIEW

### Vision
Create a market-leading open-source AI coding agent that combines:
- **Our Strengths:** Direct tool execution (10x faster), RAG system, 3-tier verification
- **Claude Code UX:** File-based memory, permission modes, hooks, subagents

### Success Criteria
- ✅ All 143 existing tests still passing
- ✅ 50+ new tests for new features
- ✅ Zero performance regressions
- ✅ Feature parity with Claude Code on UX
- ✅ Maintain competitive advantages (speed, verification, RAG)

### Timeline Summary
- **Phase 1 (Weeks 1-3):** Foundation & Quick Wins (5 features)
- **Phase 2 (Weeks 4-7):** Advanced Architecture (2 features)
- **Phase 3 (Weeks 8-10):** Strategic Features (3 features)
- **Phase 4 (Weeks 11-12):** Rollback System (original Week 3 priority)

---

## 🎯 PHASE 1: FOUNDATION & QUICK WINS (Weeks 1-3)

### Week 1: File-Based Memory + Permission Modes

#### **Feature 1.1: File-Based Hierarchical Memory (CLAUDE.md)**
**Days:** 1-3 (3 days)
**Priority:** HIGHEST
**Complexity:** LOW-MEDIUM

**Day 1: Core Implementation**

**File:** `src/memory/file_loader.py` (NEW - ~250 lines)

```python
"""
File-based hierarchical memory loader for CLAUDE.md files.

Supports 4-level hierarchy:
1. Enterprise: /etc/claude/CLAUDE.md
2. User: ~/.claude/CLAUDE.md
3. Project: ./CLAUDE.md or ./.claude/CLAUDE.md
4. Imports: @path/to/file.md (recursive, max 5 levels)
"""

from pathlib import Path
from typing import List, Dict, Optional, Set
import re
import logging

logger = logging.getLogger(__name__)


class MemoryFileLoader:
    """Loads and processes CLAUDE.md files from hierarchical locations."""

    # Filenames to search for
    FILENAMES = ["CLAUDE.md", ".claude/CLAUDE.md"]

    # Maximum import depth (prevent infinite recursion)
    MAX_IMPORT_DEPTH = 5

    def __init__(self):
        self.loaded_files: Set[Path] = set()
        self.import_chain: List[Path] = []

    def load_hierarchy(self, starting_dir: Optional[Path] = None) -> str:
        """
        Load memory files from all hierarchy levels.

        Hierarchy (lowest to highest priority):
        1. Enterprise: /etc/claude/CLAUDE.md (Linux/Mac)
        2. User: ~/.claude/CLAUDE.md
        3. Project: Traverse upward from starting_dir

        Args:
            starting_dir: Directory to start search (default: cwd)

        Returns:
            Combined memory content from all levels

        Example:
            >>> loader = MemoryFileLoader()
            >>> content = loader.load_hierarchy()
            >>> "# Memory from /home/user/.claude/CLAUDE.md" in content
            True
        """
        if starting_dir is None:
            starting_dir = Path.cwd()

        memories = []
        self.loaded_files.clear()

        # Level 1: Enterprise (if exists)
        enterprise_path = self._get_enterprise_path()
        if enterprise_path and enterprise_path.exists():
            try:
                content = self._load_file(enterprise_path)
                memories.append(content)
                logger.info(f"Loaded enterprise memory: {enterprise_path}")
            except Exception as e:
                logger.warning(f"Failed to load enterprise memory: {e}")

        # Level 2: User
        user_path = Path.home() / ".claude" / "CLAUDE.md"
        if user_path.exists():
            try:
                content = self._load_file(user_path)
                memories.append(content)
                logger.info(f"Loaded user memory: {user_path}")
            except Exception as e:
                logger.warning(f"Failed to load user memory: {e}")

        # Level 3: Project (traverse upward)
        project_memories = self._load_project_hierarchy(starting_dir)
        memories.extend(project_memories)

        # Combine with clear delimiters
        if not memories:
            return ""

        combined = "\n\n" + "="*80 + "\n\n".join(memories) + "\n" + "="*80 + "\n\n"
        logger.info(f"Loaded {len(self.loaded_files)} memory files")
        return combined

    def _get_enterprise_path(self) -> Optional[Path]:
        """Get platform-specific enterprise memory path."""
        import platform
        system = platform.system()

        if system == "Linux" or system == "Darwin":  # macOS
            return Path("/etc/claude/CLAUDE.md")
        elif system == "Windows":
            return Path("C:/ProgramData/claude/CLAUDE.md")
        return None

    def _load_project_hierarchy(self, starting_dir: Path) -> List[str]:
        """
        Traverse upward from starting_dir to find project memories.

        Stops at filesystem root.
        """
        memories = []
        current = starting_dir.resolve()

        while current != current.parent:
            for filename in self.FILENAMES:
                filepath = current / filename
                if filepath.exists() and filepath not in self.loaded_files:
                    try:
                        content = self._load_file(filepath)
                        memories.append(content)
                        logger.info(f"Loaded project memory: {filepath}")
                    except Exception as e:
                        logger.warning(f"Failed to load {filepath}: {e}")

            current = current.parent

        return memories

    def _load_file(self, path: Path) -> str:
        """
        Load a single memory file with import processing.

        Args:
            path: Path to memory file

        Returns:
            File content with imports resolved

        Raises:
            FileNotFoundError: If file doesn't exist
            RecursionError: If import depth exceeds MAX_IMPORT_DEPTH
        """
        if not path.exists():
            raise FileNotFoundError(f"Memory file not found: {path}")

        if path in self.loaded_files:
            logger.debug(f"Skipping already loaded file: {path}")
            return ""

        self.loaded_files.add(path)
        self.import_chain.append(path)

        try:
            # Read content
            content = path.read_text(encoding="utf-8")

            # Process imports (@path/to/file.md)
            content = self._process_imports(content, path.parent)

            # Add header
            header = f"# Memory from {path}\n\n"
            return header + content

        finally:
            self.import_chain.pop()

    def _process_imports(
        self,
        content: str,
        base_dir: Path,
    ) -> str:
        """
        Process @import syntax recursively.

        Supports:
        - Relative: @./docs/architecture.md
        - Home: @~/personal/preferences.md
        - Absolute: @/full/path/to/file.md

        Args:
            content: File content to process
            base_dir: Base directory for relative imports

        Returns:
            Content with imports resolved

        Example:
            >>> content = "@./docs/setup.md\\n# My Project"
            >>> processed = loader._process_imports(content, Path("."))
        """
        if len(self.import_chain) >= self.MAX_IMPORT_DEPTH:
            logger.warning(f"Import depth exceeded {self.MAX_IMPORT_DEPTH}")
            return content

        # Pattern: @path/to/file.md at start of line
        pattern = r'^@(.+\.md)\s*$'
        lines = content.split('\n')
        processed = []

        for line in lines:
            match = re.match(pattern, line.strip())
            if match:
                import_path = match.group(1)
                resolved = self._resolve_import_path(import_path, base_dir)

                if resolved and resolved.exists():
                    if resolved in self.loaded_files:
                        processed.append(f"<!-- Import already loaded: {import_path} -->")
                    elif resolved in self.import_chain:
                        processed.append(f"<!-- Circular import detected: {import_path} -->")
                        logger.warning(f"Circular import: {import_path}")
                    else:
                        try:
                            imported_content = self._load_file(resolved)
                            processed.append(imported_content)
                            logger.debug(f"Imported: {import_path}")
                        except Exception as e:
                            processed.append(f"<!-- Import failed: {import_path} ({e}) -->")
                            logger.error(f"Import failed {import_path}: {e}")
                else:
                    processed.append(f"<!-- Import not found: {import_path} -->")
                    logger.warning(f"Import not found: {import_path}")
            else:
                processed.append(line)

        return '\n'.join(processed)

    def _resolve_import_path(self, import_path: str, base_dir: Path) -> Optional[Path]:
        """
        Resolve import path to absolute path.

        Args:
            import_path: Import path from @syntax
            base_dir: Base directory for relative paths

        Returns:
            Resolved absolute path or None
        """
        # Home directory: @~/path/to/file.md
        if import_path.startswith('~/'):
            return (Path.home() / import_path[2:]).resolve()

        # Relative: @./path or @../path
        elif import_path.startswith('./') or import_path.startswith('../'):
            return (base_dir / import_path).resolve()

        # Absolute: @/full/path
        elif import_path.startswith('/'):
            return Path(import_path)

        # Default: treat as relative
        else:
            return (base_dir / import_path).resolve()

    def quick_add(self, text: str, location: str = "project") -> Path:
        """
        Quick add memory (# syntax from user input).

        Args:
            text: Memory text to add
            location: 'project' or 'user'

        Returns:
            Path to file that was updated

        Example:
            >>> loader.quick_add("Always use 2-space indent", "project")
            PosixPath('/path/to/project/CLAUDE.md')
        """
        if location == "project":
            path = Path.cwd() / "CLAUDE.md"
        elif location == "user":
            path = Path.home() / ".claude" / "CLAUDE.md"
        else:
            raise ValueError(f"Invalid location: {location}. Use 'project' or 'user'")

        # Create if doesn't exist
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            initial_content = f"""# {'Project' if location == 'project' else 'User'} Memory

## Quick Notes
{text}
"""
            path.write_text(initial_content, encoding='utf-8')
            logger.info(f"Created new memory file: {path}")
        else:
            # Append to Quick Notes section or end of file
            content = path.read_text(encoding='utf-8')

            # Try to find Quick Notes section
            if "## Quick Notes" in content:
                # Append after Quick Notes header
                parts = content.split("## Quick Notes", 1)
                # Find next ## section or end
                remainder = parts[1]
                next_section = re.search(r'\n## ', remainder)
                if next_section:
                    idx = next_section.start()
                    new_content = (
                        parts[0] +
                        "## Quick Notes" +
                        remainder[:idx] +
                        f"\n{text}\n" +
                        remainder[idx:]
                    )
                else:
                    new_content = content + f"\n{text}\n"
            else:
                # Append to end
                new_content = content.rstrip() + f"\n\n{text}\n"

            path.write_text(new_content, encoding='utf-8')
            logger.info(f"Added to {path}")

        return path

    def init_project_memory(self, path: Optional[Path] = None) -> Path:
        """
        Initialize a new CLAUDE.md file with template.

        Args:
            path: Path to create file (default: ./CLAUDE.md)

        Returns:
            Path to created file
        """
        if path is None:
            path = Path.cwd() / "CLAUDE.md"

        if path.exists():
            raise FileExistsError(f"Memory file already exists: {path}")

        template = """# Project Memory

## Project Context
[Describe your project, its purpose, and key information]

## Code Standards
### Style Guide
- [Your coding style preferences]
- [Formatting rules]
- [Naming conventions]

### Best Practices
- [Project-specific best practices]
- [Common patterns to follow]
- [Anti-patterns to avoid]

## Development Workflow
### Before Committing
- [ ] Run tests
- [ ] Run linter
- [ ] Update documentation
- [ ] Review changes

### Testing Strategy
- [Your testing approach]
- [Coverage requirements]

## Architecture
### Key Components
- [Main components and their responsibilities]

### Design Decisions
- [Important architectural decisions and rationale]

## Common Tasks
### Adding a New Feature
1. [Your feature development process]

### Debugging
1. [Your debugging workflow]

## Important Notes
- [Any critical context the agent should always remember]
- [Project-specific quirks or gotchas]

## External Resources
@./docs/architecture.md
@./docs/setup.md
"""

        path.write_text(template, encoding='utf-8')
        logger.info(f"Created project memory template: {path}")
        return path
```

**Day 1: Testing** (`tests/memory/test_file_loader.py` - NEW - ~200 lines)

```python
import pytest
from pathlib import Path
import tempfile
import shutil

from src.memory.file_loader import MemoryFileLoader


class TestMemoryFileLoader:
    """Test file-based memory loading."""

    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for tests."""
        temp = Path(tempfile.mkdtemp())
        yield temp
        shutil.rmtree(temp)

    @pytest.fixture
    def loader(self):
        """Create file loader instance."""
        return MemoryFileLoader()

    def test_load_single_file(self, loader, temp_dir):
        """Test loading a single memory file."""
        # Create test file
        mem_file = temp_dir / "CLAUDE.md"
        mem_file.write_text("# Test Memory\nContent here")

        # Load
        content = loader.load_hierarchy(temp_dir)

        assert "Test Memory" in content
        assert "Content here" in content
        assert len(loader.loaded_files) == 1

    def test_load_hierarchy(self, loader, temp_dir):
        """Test loading hierarchical memory files."""
        # Create hierarchy
        # User level
        user_dir = temp_dir / ".claude"
        user_dir.mkdir()
        (user_dir / "CLAUDE.md").write_text("# User Memory\nUser content")

        # Project level
        project_dir = temp_dir / "project"
        project_dir.mkdir()
        (project_dir / "CLAUDE.md").write_text("# Project Memory\nProject content")

        # Load from project
        content = loader.load_hierarchy(project_dir)

        assert "User Memory" in content
        assert "Project Memory" in content
        assert len(loader.loaded_files) == 2

    def test_import_relative(self, loader, temp_dir):
        """Test @./relative/path imports."""
        # Create imported file
        docs_dir = temp_dir / "docs"
        docs_dir.mkdir()
        (docs_dir / "setup.md").write_text("# Setup Instructions\nInstall dependencies")

        # Create main file with import
        main_file = temp_dir / "CLAUDE.md"
        main_file.write_text("@./docs/setup.md\n\n# Main Content")

        # Load
        content = loader.load_hierarchy(temp_dir)

        assert "Setup Instructions" in content
        assert "Install dependencies" in content

    def test_import_home(self, loader, temp_dir):
        """Test @~/home/path imports."""
        # Create file in home
        home_claude = Path.home() / ".claude"
        home_claude.mkdir(exist_ok=True)
        home_file = home_claude / "personal.md"
        home_file.write_text("# Personal Preferences\nUse 2-space indent")

        try:
            # Create main file with home import
            main_file = temp_dir / "CLAUDE.md"
            main_file.write_text("@~/.claude/personal.md")

            # Load
            content = loader.load_hierarchy(temp_dir)

            assert "Personal Preferences" in content
            assert "2-space indent" in content

        finally:
            # Cleanup
            if home_file.exists():
                home_file.unlink()

    def test_circular_import_detection(self, loader, temp_dir):
        """Test circular import detection."""
        # Create circular imports
        file_a = temp_dir / "a.md"
        file_b = temp_dir / "b.md"

        file_a.write_text("# File A\n@./b.md")
        file_b.write_text("# File B\n@./a.md")

        main = temp_dir / "CLAUDE.md"
        main.write_text("@./a.md")

        # Should not crash, should detect circular import
        content = loader.load_hierarchy(temp_dir)

        assert "Circular import" in content or content  # Should complete without error

    def test_max_import_depth(self, loader, temp_dir):
        """Test maximum import depth limit."""
        # Create deep import chain
        for i in range(10):
            file = temp_dir / f"level{i}.md"
            if i < 9:
                file.write_text(f"# Level {i}\n@./level{i+1}.md")
            else:
                file.write_text(f"# Level {i}")

        main = temp_dir / "CLAUDE.md"
        main.write_text("@./level0.md")

        # Should stop at max depth
        content = loader.load_hierarchy(temp_dir)

        # Should have some levels but not all 10
        assert "Level 0" in content
        # Might not reach Level 9 due to depth limit

    def test_quick_add_new_file(self, loader, temp_dir):
        """Test quick add to non-existent file."""
        import os
        os.chdir(temp_dir)

        path = loader.quick_add("Always run tests", "project")

        assert path.exists()
        content = path.read_text()
        assert "Always run tests" in content

    def test_quick_add_existing_file(self, loader, temp_dir):
        """Test quick add to existing file."""
        import os
        os.chdir(temp_dir)

        # Create initial file
        mem_file = temp_dir / "CLAUDE.md"
        mem_file.write_text("# Project Memory\n\n## Quick Notes\nExisting note")

        # Add new note
        loader.quick_add("New note", "project")

        content = mem_file.read_text()
        assert "Existing note" in content
        assert "New note" in content

    def test_init_project_memory(self, loader, temp_dir):
        """Test project memory initialization."""
        path = temp_dir / "CLAUDE.md"
        result = loader.init_project_memory(path)

        assert result == path
        assert path.exists()

        content = path.read_text()
        assert "Project Memory" in content
        assert "Code Standards" in content
        assert "Development Workflow" in content

    def test_init_existing_file_raises_error(self, loader, temp_dir):
        """Test that init raises error if file exists."""
        path = temp_dir / "CLAUDE.md"
        path.write_text("Existing content")

        with pytest.raises(FileExistsError):
            loader.init_project_memory(path)
```

**Day 2: Integration with MemoryManager**

**File:** `src/memory/manager.py` (MODIFY - add ~50 lines)

```python
# Add to imports
from src.memory.file_loader import MemoryFileLoader

class MemoryManager:
    def __init__(
        self,
        max_total_tokens: int = 32768,
        working_memory_ratio: float = 0.4,
        episodic_memory_ratio: float = 0.2,
        semantic_memory_ratio: float = 0.4,
    ):
        # ... existing code ...

        # Add file-based memory loader
        self.file_loader = MemoryFileLoader()
        self.file_memories = ""
        self.file_memories_loaded = False

    def load_file_memories(self, starting_dir: Optional[Path] = None):
        """
        Load CLAUDE.md hierarchy into memory.

        This should be called once at agent initialization or when
        explicitly requested by the user.

        Args:
            starting_dir: Directory to start search (default: cwd)
        """
        self.file_memories = self.file_loader.load_hierarchy(starting_dir)
        self.file_memories_loaded = True

        logger.info(f"Loaded {len(self.file_loader.loaded_files)} memory files")

    def get_file_memories(self) -> str:
        """
        Get all loaded file memories.

        Returns:
            Combined file memory content
        """
        if not self.file_memories_loaded:
            self.load_file_memories()

        return self.file_memories

    def quick_add_memory(self, text: str, location: str = "project"):
        """
        Quick add memory via # syntax.

        Args:
            text: Memory text to add
            location: 'project' or 'user'
        """
        path = self.file_loader.quick_add(text, location)

        # Reload to update context
        self.load_file_memories()

        logger.info(f"Added memory to {path}")
        return path

    def init_project_memory(self, path: Optional[Path] = None) -> Path:
        """Initialize new CLAUDE.md file."""
        return self.file_loader.init_project_memory(path)

    def get_statistics(self) -> Dict[str, Any]:
        """Get memory usage statistics."""
        stats = {
            # ... existing stats ...

            # Add file memory stats
            "file_memories": {
                "loaded": self.file_memories_loaded,
                "files_count": len(self.file_loader.loaded_files),
                "files": [str(f) for f in self.file_loader.loaded_files],
                "total_chars": len(self.file_memories),
                "total_tokens": self._estimate_tokens(self.file_memories),
            }
        }

        return stats
```

**Day 3: Agent Integration + CLI**

**File:** `src/core/agent.py` (MODIFY - add ~20 lines)

```python
class CodingAgent:
    def __init__(self, ...):
        # ... existing code ...

        # Load file memories on initialization
        self.memory.load_file_memories()

        logger.info("Loaded file-based memories (CLAUDE.md hierarchy)")

# Add methods for file memory management
def quick_add_memory(self, text: str, location: str = "project"):
    """Quick add memory to CLAUDE.md."""
    return self.memory.quick_add_memory(text, location)

def init_project_memory(self, path: Optional[Path] = None):
    """Initialize CLAUDE.md with template."""
    return self.memory.init_project_memory(path)

def reload_memories(self):
    """Reload file-based memories."""
    self.memory.load_file_memories()
```

**File:** `src/core/context_builder.py` (MODIFY - add file memories to context)

```python
def build_context(self, ...):
    """Build LLM context with file memories."""

    # ... existing code ...

    # Add file memories to system message (high priority)
    file_memories = self.memory.get_file_memories()
    if file_memories:
        system_message = f"""{base_system_prompt}

## Project Memory (from CLAUDE.md files)
{file_memories}

{rest_of_system_message}
"""

    # ... rest of existing code ...
```

**File:** `src/cli.py` (ADD commands - ~40 lines)

```python
@click.command()
def memory():
    """Open CLAUDE.md in your editor."""
    import subprocess
    import os

    # Find CLAUDE.md (project or user)
    project_path = Path.cwd() / "CLAUDE.md"
    user_path = Path.home() / ".claude" / "CLAUDE.md"

    if project_path.exists():
        path = project_path
    elif user_path.exists():
        path = user_path
    else:
        click.echo("No CLAUDE.md found. Use /init to create one.")
        return

    # Open in editor
    editor = os.environ.get('EDITOR', 'nano')  # Default to nano
    try:
        subprocess.run([editor, str(path)])
    except Exception as e:
        click.echo(f"Failed to open editor: {e}")


@click.command()
@click.option('--path', type=click.Path(), help='Custom path for CLAUDE.md')
def init(path):
    """Initialize CLAUDE.md with template."""
    from src.memory.file_loader import MemoryFileLoader

    loader = MemoryFileLoader()

    try:
        if path:
            created_path = loader.init_project_memory(Path(path))
        else:
            created_path = loader.init_project_memory()

        click.echo(f"Created {created_path}")
        click.echo("Edit it with: /memory")
    except FileExistsError:
        click.echo("CLAUDE.md already exists. Use /memory to edit.")
    except Exception as e:
        click.echo(f"Error: {e}")


# Update chat command to support # syntax
@click.command()
def chat():
    """Interactive chat with memory support."""
    # ... existing code ...

    while True:
        user_input = input("> ")

        # Check for # syntax (quick add)
        if user_input.strip().startswith('#'):
            text = user_input.strip()[1:].strip()
            try:
                path = agent.quick_add_memory(text, "project")
                print(f"✓ Added to {path}")
                continue
            except Exception as e:
                print(f"✗ Error adding memory: {e}")
                continue

        # ... rest of chat logic ...
```

**Day 3: Documentation**

Update `README.md`:

```markdown
## File-Based Memory (CLAUDE.md)

The agent supports hierarchical file-based memory through `CLAUDE.md` files.

### Hierarchy (lowest to highest priority)

1. **Enterprise:** `/etc/claude/CLAUDE.md` - Organization-wide policies
2. **User:** `~/.claude/CLAUDE.md` - Your personal preferences
3. **Project:** `./CLAUDE.md` or `./.claude/CLAUDE.md` - Project-specific instructions

### Quick Start

```bash
# Create a new CLAUDE.md
python -m src.cli init

# Edit it
python -m src.cli memory

# Or just create it manually
cat > CLAUDE.md <<EOF
# My Project Memory

## Code Standards
- Use 2-space indentation for JavaScript
- Use 4-space for Python
- Always write tests

## Workflow
- Run tests before committing
- Update documentation with code changes
EOF
```

### Import Syntax

Import other files into your memory:

```markdown
# My Project Memory

@./docs/architecture.md
@./docs/coding-standards.md
@~/.claude/personal-preferences.md

## Project-Specific Notes
...
```

### Quick Add (# syntax)

In chat mode, start your message with `#` to quickly add to project memory:

```
> # Always use async/await for database calls
✓ Added to /path/to/project/CLAUDE.md

> What's the best way to handle errors?
[Agent response includes your memory about async/await]
```

### Features

- ✅ Version controllable (commit `CLAUDE.md` to git)
- ✅ Team shareable (everyone uses same project memory)
- ✅ Import modularity (split into multiple files)
- ✅ Recursive imports (up to 5 levels)
- ✅ Automatic loading on agent start
```

---

#### **Feature 1.2: Permission Modes (Plan/Normal/Auto)**
**Days:** 4-5 (2 days)
**Priority:** HIGHEST
**Complexity:** LOW

**Day 4: Core Implementation**

**File:** `src/workflow/permission.py` (NEW - ~150 lines)

```python
"""
Permission modes for safe and flexible agent operation.

Three modes:
- PLAN: Read-only exploration (safe for unfamiliar codebases)
- NORMAL: Approval required for write operations (default)
- AUTO: Auto-accept all operations (rapid iteration)
"""

from enum import Enum
from typing import List, Optional, Set
import logging

logger = logging.getLogger(__name__)


class PermissionMode(Enum):
    """Permission modes for agent execution."""

    PLAN = "plan"        # Read-only, no write operations
    NORMAL = "normal"    # Ask approval for write operations (default)
    AUTO = "auto"        # Auto-accept all operations


class PermissionManager:
    """Manages permission mode and tool authorization."""

    # Read-only tools (allowed in ALL modes including Plan)
    READ_ONLY_TOOLS = {
        "read_file",
        "ReadFileTool",
        "list_directory",
        "ListDirectoryTool",
        "search_code",
        "SearchCodeTool",
        "git_status",
        "GitStatusTool",
        "git_diff",
        "GitDiffTool",
        "analyze_code",
        "AnalyzeCodeTool",
    }

    # Write tools (blocked in Plan mode, require approval in Normal mode)
    WRITE_TOOLS = {
        "write_file",
        "WriteFileTool",
        "edit_file",
        "EditFileTool",
    }

    # Dangerous tools (always require approval, even in Auto mode)
    DANGEROUS_TOOLS = {
        "run_command",
        "RunCommandTool",
        "delete_file",
        "DeleteFileTool",
    }

    def __init__(self, mode: PermissionMode = PermissionMode.NORMAL):
        self.mode = mode
        self.allowed_tools: Optional[Set[str]] = None
        self.disallowed_tools: Optional[Set[str]] = None

    def set_mode(self, mode: PermissionMode):
        """Change permission mode."""
        old_mode = self.mode
        self.mode = mode
        logger.info(f"Permission mode changed: {old_mode.value} → {mode.value}")

    def cycle_mode(self):
        """Cycle through modes: Normal → Plan → Auto → Normal."""
        modes = [PermissionMode.NORMAL, PermissionMode.PLAN, PermissionMode.AUTO]
        current_idx = modes.index(self.mode)
        next_mode = modes[(current_idx + 1) % len(modes)]
        self.set_mode(next_mode)
        return next_mode

    def is_tool_allowed(self, tool_name: str) -> tuple[bool, Optional[str]]:
        """
        Check if tool is allowed in current mode.

        Returns:
            (allowed: bool, reason: Optional[str])

        Example:
            >>> manager = PermissionManager(PermissionMode.PLAN)
            >>> manager.is_tool_allowed("ReadFileTool")
            (True, None)
            >>> manager.is_tool_allowed("WriteFileTool")
            (False, "Write operations not allowed in PLAN mode")
        """
        # Normalize tool name (handle both "read_file" and "ReadFileTool")
        normalized = tool_name.lower().replace("tool", "")

        # Check explicit allow/disallow lists (if configured)
        if self.disallowed_tools and tool_name in self.disallowed_tools:
            return False, f"Tool '{tool_name}' is explicitly disallowed"

        if self.allowed_tools and tool_name not in self.allowed_tools:
            return False, f"Tool '{tool_name}' is not in allowed tools list"

        # Plan mode: Only read-only tools
        if self.mode == PermissionMode.PLAN:
            if tool_name in self.READ_ONLY_TOOLS or normalized in [t.lower().replace("tool", "") for t in self.READ_ONLY_TOOLS]:
                return True, None
            else:
                return False, f"Write operations not allowed in PLAN mode"

        # Normal and Auto modes: All tools allowed (approval checked separately)
        return True, None

    def requires_approval(self, tool_name: str) -> tuple[bool, str]:
        """
        Check if tool requires user approval.

        Returns:
            (requires: bool, reason: str)

        Example:
            >>> manager = PermissionManager(PermissionMode.NORMAL)
            >>> manager.requires_approval("WriteFileTool")
            (True, "Write operation requires approval in NORMAL mode")
            >>> manager.requires_approval("ReadFileTool")
            (False, "Read operation, no approval needed")
        """
        # Dangerous tools ALWAYS require approval (even in Auto mode)
        if tool_name in self.DANGEROUS_TOOLS:
            return True, "Dangerous operation requires approval"

        # Plan mode: No approval needed (tools already filtered)
        if self.mode == PermissionMode.PLAN:
            return False, "PLAN mode, no approval needed"

        # Normal mode: Approval for write tools
        if self.mode == PermissionMode.NORMAL:
            if tool_name in self.WRITE_TOOLS or tool_name in self.DANGEROUS_TOOLS:
                return True, f"Write operation requires approval in NORMAL mode"
            else:
                return False, "Read operation, no approval needed"

        # Auto mode: No approval (except dangerous tools, handled above)
        if self.mode == PermissionMode.AUTO:
            return False, "AUTO mode, no approval needed"

        return False, "Unknown mode"

    def get_mode_indicator(self) -> str:
        """
        Get mode indicator for prompt display.

        Returns:
            String like "[PLAN]", "[NORMAL]", "[AUTO]"
        """
        return f"[{self.mode.value.upper()}]"

    def get_mode_description(self) -> str:
        """Get human-readable mode description."""
        descriptions = {
            PermissionMode.PLAN: "Read-only mode - Safe exploration without modifications",
            PermissionMode.NORMAL: "Normal mode - Approval required for write operations",
            PermissionMode.AUTO: "Auto mode - All operations auto-accepted",
        }
        return descriptions[self.mode]

    def set_allowed_tools(self, tools: List[str]):
        """Set explicit whitelist of allowed tools."""
        self.allowed_tools = set(tools)
        logger.info(f"Allowed tools set: {tools}")

    def set_disallowed_tools(self, tools: List[str]):
        """Set explicit blacklist of disallowed tools."""
        self.disallowed_tools = set(tools)
        logger.info(f"Disallowed tools set: {tools}")

    def get_allowed_tools_for_mode(self) -> List[str]:
        """Get list of tools allowed in current mode."""
        if self.mode == PermissionMode.PLAN:
            return list(self.READ_ONLY_TOOLS)
        else:
            # All tools allowed (approval checked separately)
            all_tools = self.READ_ONLY_TOOLS | self.WRITE_TOOLS | self.DANGEROUS_TOOLS
            if self.allowed_tools:
                return list(all_tools & self.allowed_tools)
            if self.disallowed_tools:
                return list(all_tools - self.disallowed_tools)
            return list(all_tools)
```

**Day 4: Testing** (`tests/workflow/test_permission.py` - NEW - ~150 lines)

```python
import pytest
from src.workflow.permission import PermissionMode, PermissionManager


class TestPermissionManager:
    """Test permission management."""

    def test_plan_mode_allows_read_only(self):
        """Plan mode should only allow read tools."""
        manager = PermissionManager(PermissionMode.PLAN)

        # Read tools allowed
        allowed, reason = manager.is_tool_allowed("ReadFileTool")
        assert allowed is True
        assert reason is None

        allowed, reason = manager.is_tool_allowed("ListDirectoryTool")
        assert allowed is True

        # Write tools blocked
        allowed, reason = manager.is_tool_allowed("WriteFileTool")
        assert allowed is False
        assert "PLAN mode" in reason

        allowed, reason = manager.is_tool_allowed("EditFileTool")
        assert allowed is False

    def test_normal_mode_allows_all_tools(self):
        """Normal mode should allow all tools (approval separate)."""
        manager = PermissionManager(PermissionMode.NORMAL)

        # All tools allowed
        allowed, _ = manager.is_tool_allowed("ReadFileTool")
        assert allowed is True

        allowed, _ = manager.is_tool_allowed("WriteFileTool")
        assert allowed is True

    def test_normal_mode_requires_approval_for_writes(self):
        """Normal mode should require approval for write tools."""
        manager = PermissionManager(PermissionMode.NORMAL)

        # Read tools no approval
        requires, reason = manager.requires_approval("ReadFileTool")
        assert requires is False

        # Write tools require approval
        requires, reason = manager.requires_approval("WriteFileTool")
        assert requires is True
        assert "approval" in reason.lower()

    def test_auto_mode_no_approval(self):
        """Auto mode should not require approval."""
        manager = PermissionManager(PermissionMode.AUTO)

        # Write tools no approval
        requires, _ = manager.requires_approval("WriteFileTool")
        assert requires is False

    def test_dangerous_tools_always_require_approval(self):
        """Dangerous tools should require approval even in Auto mode."""
        manager = PermissionManager(PermissionMode.AUTO)

        requires, reason = manager.requires_approval("RunCommandTool")
        assert requires is True
        assert "Dangerous" in reason

    def test_cycle_mode(self):
        """Test mode cycling."""
        manager = PermissionManager(PermissionMode.NORMAL)

        # Normal → Plan
        next_mode = manager.cycle_mode()
        assert next_mode == PermissionMode.PLAN
        assert manager.mode == PermissionMode.PLAN

        # Plan → Auto
        next_mode = manager.cycle_mode()
        assert next_mode == PermissionMode.AUTO

        # Auto → Normal
        next_mode = manager.cycle_mode()
        assert next_mode == PermissionMode.NORMAL

    def test_mode_indicator(self):
        """Test mode indicator strings."""
        manager = PermissionManager(PermissionMode.PLAN)
        assert manager.get_mode_indicator() == "[PLAN]"

        manager.set_mode(PermissionMode.NORMAL)
        assert manager.get_mode_indicator() == "[NORMAL]"

        manager.set_mode(PermissionMode.AUTO)
        assert manager.get_mode_indicator() == "[AUTO]"

    def test_allowed_tools_whitelist(self):
        """Test explicit allowed tools list."""
        manager = PermissionManager(PermissionMode.NORMAL)
        manager.set_allowed_tools(["ReadFileTool", "WriteFileTool"])

        allowed, _ = manager.is_tool_allowed("ReadFileTool")
        assert allowed is True

        allowed, reason = manager.is_tool_allowed("RunCommandTool")
        assert allowed is False
        assert "not in allowed" in reason

    def test_disallowed_tools_blacklist(self):
        """Test explicit disallowed tools list."""
        manager = PermissionManager(PermissionMode.NORMAL)
        manager.set_disallowed_tools(["RunCommandTool"])

        allowed, _ = manager.is_tool_allowed("WriteFileTool")
        assert allowed is True

        allowed, reason = manager.is_tool_allowed("RunCommandTool")
        assert allowed is False
        assert "explicitly disallowed" in reason
```

**Day 5: Integration + CLI**

**File:** `src/workflow/execution_engine.py` (MODIFY - add permission checks - ~30 lines)

```python
from src.workflow.permission import PermissionManager, PermissionMode

class ExecutionEngine:
    def __init__(
        self,
        tool_executor,
        llm=None,
        progress_callback=None,
        permission_manager: Optional[PermissionManager] = None,
    ):
        # ... existing code ...

        self.permission_manager = permission_manager or PermissionManager()

    def execute_plan(self, plan: ExecutionPlan) -> ExecutionResult:
        """Execute plan respecting permission mode."""

        # Notify user of mode
        if self.progress_callback:
            mode_desc = self.permission_manager.get_mode_description()
            self.progress_callback(
                0, "info",
                f"🔐 {mode_desc}"
            )

        # Filter steps if in Plan mode
        original_step_count = len(plan.steps)
        if self.permission_manager.mode == PermissionMode.PLAN:
            # Only keep read-only steps
            plan.steps = [
                step for step in plan.steps
                if self.permission_manager.is_tool_allowed(step.tool)[0]
            ]

            blocked_count = original_step_count - len(plan.steps)
            if self.progress_callback and blocked_count > 0:
                self.progress_callback(
                    0, "info",
                    f"ℹ️  Blocked {blocked_count} write operations in PLAN mode"
                )

        # ... existing execution logic ...

    def _execute_step(self, step: PlanStep) -> StepResult:
        """Execute single step with permission check."""
        start_time = time.time()

        # Check if tool is allowed in current mode
        allowed, reason = self.permission_manager.is_tool_allowed(step.tool)
        if not allowed:
            return StepResult(
                step_id=step.id,
                success=False,
                error=f"🚫 {reason}",
                duration=time.time() - start_time
            )

        # Check if approval required
        requires_approval, approval_reason = self.permission_manager.requires_approval(step.tool)
        if requires_approval:
            # Ask for approval
            if self.progress_callback:
                self.progress_callback(
                    step.id, "approval_required",
                    f"⏸️  Step {step.id} requires approval: {step.description}"
                )

            approved = self._get_user_approval(step, approval_reason)
            if not approved:
                return StepResult(
                    step_id=step.id,
                    success=False,
                    error="❌ User rejected operation",
                    duration=time.time() - start_time
                )

        # Execute tool
        # ... existing execution logic ...
```

**File:** `src/cli.py` (MODIFY - add permission mode support - ~50 lines)

```python
@click.option('--permission-mode',
              type=click.Choice(['plan', 'normal', 'auto']),
              default='normal',
              help='Permission mode (plan=read-only, normal=ask approval, auto=auto-accept)')
def chat(permission_mode):
    """Interactive chat with permission modes."""
    from src.workflow.permission import PermissionMode, PermissionManager

    # Create permission manager
    mode = PermissionMode(permission_mode)
    permission_manager = PermissionManager(mode)

    # Create agent with permission manager
    agent = CodingAgent(
        permission_manager=permission_manager,
        ...
    )

    click.echo(f"🔐 Permission mode: {permission_manager.get_mode_description()}")
    click.echo("💡 Type /mode to cycle modes, /help for more commands")

    # Main chat loop
    while True:
        # Show mode indicator in prompt
        mode_indicator = permission_manager.get_mode_indicator()
        user_input = input(f"{mode_indicator} > ")

        # Handle commands
        if user_input.strip() == "/mode":
            next_mode = permission_manager.cycle_mode()
            click.echo(f"🔄 Switched to {next_mode.value.upper()} mode")
            click.echo(f"   {permission_manager.get_mode_description()}")
            continue

        if user_input.strip() == "/help":
            click.echo("""
Commands:
  /mode     - Cycle permission modes (Normal → Plan → Auto)
  /memory   - Open CLAUDE.md in editor
  /init     - Initialize CLAUDE.md template
  /exit     - Exit chat
  #text     - Quick add to project memory

Permission Modes:
  [PLAN]   - Read-only, safe exploration
  [NORMAL] - Approval required for writes (default)
  [AUTO]   - Auto-accept all operations
""")
            continue

        if user_input.strip() == "/exit":
            break

        # ... existing chat logic ...
```

---

### Week 2: File References + Session Persistence

#### **Feature 2.1: File Reference Syntax (@file.py)**
**Days:** 1-2 (2 days)
**Priority:** HIGH
**Complexity:** LOW

*(Detailed implementation omitted for brevity - similar pattern to above)*

**Key Components:**
- `FileReferenceParser` in `src/utils/file_reference.py`
- Integration with `CodingAgent.execute_task()`
- Support for `@file.py`, `@src/**/*.py` (glob patterns)
- Auto-injection into context before LLM call

---

#### **Feature 2.2: Session Persistence**
**Days:** 3-6 (4 days)
**Priority:** HIGH
**Complexity:** MEDIUM

*(Detailed implementation omitted for brevity)*

**Key Components:**
- `SessionManager` in `src/session/manager.py`
- Save/resume with session IDs
- State serialization (memory, RAG, context)
- CLI commands: `--save`, `--resume <id>`, `/sessions`

---

### Week 3: Parallel Tool Execution

#### **Feature 3.1: Parallel Tool Execution**
**Days:** 1-5 (5 days)
**Priority:** MEDIUM
**Complexity:** MEDIUM

*(Detailed implementation omitted for brevity)*

**Key Components:**
- Modify `ExecutionEngine` for async execution
- `asyncio.gather()` for parallel steps
- Dependency validation (can't parallelize dependent steps)
- `parallel: true` flag in plan steps

---

## 🎯 PHASE 2: ADVANCED ARCHITECTURE (Weeks 4-7)

### Weeks 4-5: Event-Driven Hooks System

*(Detailed 2-week implementation plan with daily breakdown - omitted for brevity)*

**Deliverables:**
- 9 hook events implemented
- JSON I/O via stdin/stdout
- Exit code control
- Configuration system (.claude/settings.json)
- Integration with ToolExecutor and ExecutionEngine

---

### Weeks 6-7: Subagent Architecture

*(Detailed 2-week implementation plan - omitted for brevity)*

**Deliverables:**
- SubAgent class with independent context
- Markdown-based configuration
- Auto + explicit delegation
- 3+ built-in subagents (code-reviewer, test-writer, doc-writer)

---

## 🔵 PHASE 3: STRATEGIC FEATURES (Weeks 8-10)

### Week 8: Context Compaction + Output Styles
### Weeks 9-10: MCP Integration (Optional)

*(Implementation plans omitted for brevity)*

---

## 🔧 PHASE 4: ROLLBACK SYSTEM (Weeks 11-12)

**Original Week 3 priority - now pushed to accommodate Claude Code features**

*(Implementation from existing plan)*

---

## 📈 SUCCESS METRICS & TESTING

### Test Coverage Goals
- **Phase 1:** 80+ new tests, 90%+ coverage on new code
- **Phase 2:** 60+ new tests, 85%+ coverage
- **Phase 3:** 40+ new tests

### Performance Benchmarks
- **File Memory Loading:** < 100ms for typical projects
- **Permission Checks:** < 1ms per tool call
- **Parallel Execution:** 2-5x faster for independent operations
- **Hook Execution:** < 500ms overhead per hook

### Integration Tests
- **End-to-End:** 20+ scenarios covering all new features
- **Regression:** All 143 existing tests must pass
- **Performance:** No regression in existing features

---

## 📅 TIMELINE SUMMARY

| Week | Focus | Features | Tests | Docs |
|------|-------|----------|-------|------|
| 1 | Foundation | File Memory, Permissions | 15+ | 200+ lines |
| 2 | UX | File Refs, Sessions | 20+ | 150+ lines |
| 3 | Performance | Parallel Execution | 10+ | 100+ lines |
| 4-5 | Extensibility | Hooks System | 25+ | 300+ lines |
| 6-7 | Specialization | Subagents | 30+ | 250+ lines |
| 8 | Polish | Compaction, Styles | 15+ | 150+ lines |
| 9-10 | Strategic | MCP Integration | 25+ | 200+ lines |
| 11-12 | Safety | Rollback System | 20+ | 150+ lines |

**Total:** 160+ new tests, 1,500+ lines of documentation

---

## 🎯 NEXT STEPS

1. **Review this roadmap** with team/stakeholders
2. **Prioritize features** if timeline needs compression
3. **Set up development branch** for integration work
4. **Start Week 1 Day 1:** File-based memory implementation
5. **Iterate and gather feedback** after each phase

---

**Document Version:** 1.0
**Last Updated:** 2025-10-17
**Estimated Total Effort:** 12 engineer-weeks (solo) or 3-4 weeks (team of 3-4)
**Confidence Level:** High (well-defined, proven patterns)
