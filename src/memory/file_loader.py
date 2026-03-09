"""
File-based hierarchical memory loader for ClarAIty agent.

Supports 4-level hierarchy:
1. Enterprise: /etc/clarity/memory.md (Linux/Mac) or C:/ProgramData/clarity/memory.md (Windows)
2. User: ~/.clarity/memory.md
3. Project: ./.clarity/memory.md (traverses upward from cwd)
4. Imports: @path/to/file.md (recursive, max 5 levels)

Features:
- Automatic loading on initialization
- Import syntax with circular detection
- Quick add (#text syntax)
- Project template initialization
- Version controllable (git)
- Team shareable

Example:
    >>> loader = MemoryFileLoader()
    >>> content = loader.load_hierarchy()
    >>> # Loads from enterprise → user → project hierarchy
"""

import platform
import re
from pathlib import Path
from typing import Optional

from src.observability import get_logger

logger = get_logger(__name__)


class MemoryFileLoader:
    """Loads and processes memory.md files from hierarchical locations."""

    # Filename to search for
    MEMORY_FILENAME = "memory.md"

    # Directory name
    CONFIG_DIR = ".clarity"

    # Maximum import depth (prevent infinite recursion)
    MAX_IMPORT_DEPTH = 5

    def __init__(self):
        self.loaded_files: set[Path] = set()
        self.import_chain: list[Path] = []

    def load_hierarchy(self, starting_dir: Path | None = None) -> str:
        """
        Load memory files from all hierarchy levels.

        Hierarchy (lowest to highest priority):
        1. Enterprise: /etc/clarity/memory.md (Linux/Mac)
        2. User: ~/.clarity/memory.md
        3. Project: Traverse upward from starting_dir looking for .clarity/memory.md

        Args:
            starting_dir: Directory to start search (default: cwd)

        Returns:
            Combined memory content from all levels

        Example:
            >>> loader = MemoryFileLoader()
            >>> content = loader.load_hierarchy()
            >>> "# Memory from" in content
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
                if content:
                    memories.append(content)
                    logger.info(f"Loaded enterprise memory: {enterprise_path}")
            except Exception as e:
                logger.warning(f"Failed to load enterprise memory: {e}")

        # Level 2: User
        user_path = Path.home() / self.CONFIG_DIR / self.MEMORY_FILENAME
        if user_path.exists():
            try:
                content = self._load_file(user_path)
                if content:
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

        combined = "\n\n" + ("=" * 80 + "\n\n").join(memories) + "\n" + "=" * 80 + "\n\n"
        logger.info(f"Loaded {len(self.loaded_files)} memory files")
        return combined

    def _get_enterprise_path(self) -> Path | None:
        """Get platform-specific enterprise memory path."""
        system = platform.system()

        if system == "Linux" or system == "Darwin":  # macOS
            return Path("/etc/clarity") / self.MEMORY_FILENAME
        elif system == "Windows":
            return Path("C:/ProgramData/clarity") / self.MEMORY_FILENAME
        return None

    def _load_project_hierarchy(self, starting_dir: Path) -> list[str]:
        """
        Traverse upward from starting_dir to find project memories.

        Looks for .clarity/memory.md in each directory.
        Stops at filesystem root.
        """
        memories = []
        current = starting_dir.resolve()

        while current != current.parent:
            filepath = current / self.CONFIG_DIR / self.MEMORY_FILENAME
            if filepath.exists() and filepath not in self.loaded_files:
                try:
                    content = self._load_file(filepath)
                    if content:
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
        - Home: @~/.clarity/preferences.md (restricted to ~/.clarity/)
        Note: Absolute path imports are blocked for security.

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
        pattern = r"^@(.+\.md)\s*$"
        lines = content.split("\n")
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
                            if imported_content:
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

        return "\n".join(processed)

    def _resolve_import_path(self, import_path: str, base_dir: Path) -> Path | None:
        """
        Resolve import path to absolute path.

        Security: Only allows .md files within the project root or ~/.clarity/.
        Absolute path imports are blocked entirely.

        Args:
            import_path: Import path from @syntax
            base_dir: Base directory for relative paths

        Returns:
            Resolved absolute path or None
        """
        # Security: only allow .md file extension
        if not import_path.endswith(".md"):
            logger.warning(f"[SECURITY] Blocked non-.md import: {import_path}")
            return None

        # Security: block absolute path imports entirely
        if import_path.startswith("/") or (len(import_path) >= 3 and import_path[1] == ":"):
            logger.warning(f"[SECURITY] Absolute path imports are not allowed: {import_path}")
            return None

        # Home directory: @~/path/to/file.md
        if import_path.startswith("~/"):
            resolved = (Path.home() / import_path[2:]).resolve()

        # Relative: @./path or @../path
        elif import_path.startswith("./") or import_path.startswith("../"):
            resolved = (base_dir / import_path).resolve()

        # Default: treat as relative
        else:
            resolved = (base_dir / import_path).resolve()

        # Security: restrict imports to project root or user .clarity directory
        project_root = Path.cwd().resolve()
        user_clarity = Path.home().resolve() / ".clarity"

        is_safe = False
        try:
            resolved.relative_to(project_root)
            is_safe = True
        except ValueError:
            pass

        if not is_safe:
            try:
                resolved.relative_to(user_clarity)
                is_safe = True
            except ValueError:
                pass

        if not is_safe:
            logger.warning(f"[SECURITY] Blocked import outside allowed directories: {import_path}")
            return None

        return resolved

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
            PosixPath('/path/to/project/.clarity/memory.md')
        """
        if location == "project":
            path = Path.cwd() / self.CONFIG_DIR / self.MEMORY_FILENAME
        elif location == "user":
            path = Path.home() / self.CONFIG_DIR / self.MEMORY_FILENAME
        else:
            raise ValueError(f"Invalid location: {location}. Use 'project' or 'user'")

        # Create if doesn't exist
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            initial_content = f"""# {"Project" if location == "project" else "User"} Memory

## Quick Notes
{text}
"""
            path.write_text(initial_content, encoding="utf-8")
            logger.info(f"Created new memory file: {path}")
        else:
            # Append to Quick Notes section or end of file
            content = path.read_text(encoding="utf-8")

            # Try to find Quick Notes section
            if "## Quick Notes" in content:
                # Append after Quick Notes header
                parts = content.split("## Quick Notes", 1)
                # Find next ## section or end
                remainder = parts[1]
                next_section = re.search(r"\n## ", remainder)
                if next_section:
                    idx = next_section.start()
                    new_content = (
                        parts[0]
                        + "## Quick Notes"
                        + remainder[:idx]
                        + f"\n{text}\n"
                        + remainder[idx:]
                    )
                else:
                    new_content = content + f"\n{text}\n"
            else:
                # Append to end
                new_content = content.rstrip() + f"\n\n{text}\n"

            path.write_text(new_content, encoding="utf-8")
            logger.info(f"Added to {path}")

        return path

    def init_project_memory(self, path: Path | None = None) -> Path:
        """
        Initialize a new memory.md file with template.

        Args:
            path: Path to create file (default: ./.clarity/memory.md)

        Returns:
            Path to created file

        Raises:
            FileExistsError: If file already exists
        """
        if path is None:
            path = Path.cwd() / self.CONFIG_DIR / self.MEMORY_FILENAME

        if path.exists():
            raise FileExistsError(f"Memory file already exists: {path}")

        template = """# ClarAIty Project Memory

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

        # Create directory if it doesn't exist
        path.parent.mkdir(parents=True, exist_ok=True)

        path.write_text(template, encoding="utf-8")
        logger.info(f"Created project memory template: {path}")
        return path
