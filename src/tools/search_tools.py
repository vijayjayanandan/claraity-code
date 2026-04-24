"""
Production-grade search tools matching industry standards (ripgrep/glob).

Provides:
- GrepTool: Advanced regex search with file type filters, context lines, multiple output modes
- GlobTool: Fast recursive file pattern matching with brace expansion

These tools provide Anthropic-grade search capabilities for code discovery and analysis.
"""

import bisect
import re
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from .base import Tool, ToolResult, ToolStatus
from .claraityignore import filter_paths


class OutputMode(Enum):
    """Grep output modes."""

    CONTENT = "content"  # Show matching lines
    FILES_WITH_MATCHES = "files_with_matches"  # Show only file paths
    COUNT = "count"  # Show match counts per file


# Language file extensions mapping (like ripgrep's --type)
FILE_TYPE_MAP = {
    "python": ["*.py", "*.pyw"],
    "py": ["*.py", "*.pyw"],
    "javascript": ["*.js", "*.jsx", "*.mjs"],
    "js": ["*.js", "*.jsx", "*.mjs"],
    "typescript": ["*.ts", "*.tsx"],
    "ts": ["*.ts", "*.tsx"],
    "java": ["*.java"],
    "cpp": ["*.cpp", "*.cc", "*.cxx", "*.h", "*.hpp"],
    "c": ["*.c", "*.h"],
    "csharp": ["*.cs"],
    "cs": ["*.cs"],
    "go": ["*.go"],
    "rust": ["*.rs"],
    "ruby": ["*.rb"],
    "rb": ["*.rb"],
    "php": ["*.php"],
    "html": ["*.html", "*.htm"],
    "css": ["*.css", "*.scss", "*.sass"],
    "json": ["*.json"],
    "yaml": ["*.yaml", "*.yml"],
    "xml": ["*.xml"],
    "markdown": ["*.md", "*.markdown"],
    "md": ["*.md", "*.markdown"],
    "shell": ["*.sh", "*.bash"],
    "sql": ["*.sql"],
}


def validate_path_security(
    path_str: str, workspace_root: Path | None = None, allow_files_outside_workspace: bool = False
) -> Path:
    """
    Validate path for security (prevent path traversal attacks).

    Args:
        path_str: User-provided path string
        workspace_root: Allowed workspace directory (default: current working directory)
        allow_files_outside_workspace: If True, allows paths outside workspace (use with caution)

    Returns:
        Validated resolved Path object

    Raises:
        ValueError: If path is outside workspace or invalid

    Security:
        - Resolves symlinks and relative paths to absolute paths
        - Checks if path is within workspace boundary
        - Prevents directory traversal attacks (../../../etc/passwd)
    """
    if workspace_root is None:
        workspace_root = Path.cwd()
    else:
        workspace_root = workspace_root.resolve()

    try:
        # Resolve to absolute path (follows symlinks, resolves ..)
        resolved_path = Path(path_str).resolve()

        # Check if path is within workspace (prevent path traversal)
        if not allow_files_outside_workspace:
            try:
                resolved_path.relative_to(workspace_root)
            except ValueError:
                raise ValueError(
                    f"[SECURITY] Path traversal blocked: '{path_str}' resolves to '{resolved_path}' "
                    f"which is outside workspace '{workspace_root}'"
                )

        return resolved_path

    except (OSError, RuntimeError) as e:
        raise ValueError(f"Invalid path: '{path_str}' - {e}")


def validate_regex_safety(pattern: str, max_length: int = 500) -> None:
    """
    Validate regex pattern for potential ReDoS (Regular Expression Denial of Service) attacks.

    Args:
        pattern: Regex pattern to validate
        max_length: Maximum allowed pattern length

    Raises:
        ValueError: If pattern is potentially dangerous or too complex

    Security:
        - Prevents catastrophic backtracking patterns (e.g., (a+)+, (x+x+)+)
        - Limits pattern length to prevent complexity attacks
        - Detects nested quantifiers that can cause exponential time complexity
    """
    if len(pattern) > max_length:
        raise ValueError(
            f"[SECURITY] Regex pattern too long: {len(pattern)} characters (max: {max_length}). "
            "Long patterns can cause performance issues."
        )

    # Dangerous patterns that can cause catastrophic backtracking
    # These patterns have exponential time complexity: O(2^n)
    # NOTE: These checks only catch single-char groups like (.+)+ or (a+)+.
    # Multi-char groups like (\d+)+ or ([a-z]+)+ are NOT detected.
    # Low practical risk since the LLM generates patterns, not adversaries.
    dangerous_patterns = [
        (r"\(\.\*\+", "(.* followed by +"),  # (.*+  - possessive quantifier misuse
        (r"\+\+", "Consecutive ++"),  # ++
        (r"\*\*", "Consecutive **"),  # **
        (r"\(\w+\)\+", "Nested quantifier (word+)+"),  # (x+)+
        (r"\(\.\+\)\*", "Nested quantifier (.+)*"),  # (.+)*
        (r"\(\[\^.\]\+\)\+", "Nested negated class"),  # ([^x]+)+
        (r"\(\w+\)\*", "Greedy nested quantifier (word+)*"),  # (x+)*
        (r"\(.\*\)\+", "Greedy nested wildcard (.*)+"),  # (.*)+
        (r"\(.\+\)\+", "Nested greedy plus (.+)+"),  # (.+)+
    ]

    for danger_pattern, description in dangerous_patterns:
        if re.search(danger_pattern, pattern):
            raise ValueError(
                f"[SECURITY] Potentially dangerous regex pattern detected: {description}. "
                f"This pattern can cause catastrophic backtracking (ReDoS). "
                f"Pattern: '{pattern}'"
            )

    # Check for excessive repetition nesting depth
    # Count nested parentheses with quantifiers
    nesting_depth = 0
    max_nesting = 3  # Allow max 3 levels of nesting
    i = 0
    while i < len(pattern):
        if pattern[i] == "(":
            # Check if this group has a quantifier after closing paren
            depth = 1
            j = i + 1
            while j < len(pattern) and depth > 0:
                if pattern[j] == "(":
                    depth += 1
                elif pattern[j] == ")":
                    depth -= 1
                    if depth == 0 and j + 1 < len(pattern) and pattern[j + 1] in "+*?{":
                        nesting_depth += 1
                j += 1
        i += 1

    if nesting_depth > max_nesting:
        raise ValueError(
            f"[SECURITY] Regex has too many nested quantifiers ({nesting_depth} levels, max: {max_nesting}). "
            "Deep nesting can cause exponential time complexity."
        )


class GrepTool(Tool):
    """
    Production-grade regex search tool (ripgrep-like).

    Features:
    - Full regex support (Python re module)
    - File type filters (--type py, --type js)
    - Glob patterns for file filtering
    - Context lines (-A, -B, -C)
    - Multiple output modes (content, files_with_matches, count)
    - Case sensitivity control
    - Multiline matching support
    - Line number display
    - Result limiting

    Matches Claude Code's Grep tool capabilities.
    """

    _SCHEMA_NAME = "grep"

    # Skip files larger than 10 MB to prevent OOM from readlines()
    MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024
    # Per-line character cap: prevents single-line bombs (minified JS, one-line JSON, binary-as-text)
    MAX_LINE_CHARS = 2_000
    # Total output character budget for CONTENT mode — stops collection before context window damage
    MAX_OUTPUT_CHARS = 100_000

    def __init__(self):
        super().__init__(
            name="grep", description="Search for regex patterns in files with advanced filtering"
        )

    def execute(
        self,
        pattern: str,
        file_path: str | None = None,
        file_type: str | None = None,
        glob: str | None = None,
        output_mode: str | None = None,
        context_before: int = 0,
        context_after: int = 0,
        context: int = 0,
        case_insensitive: bool = False,
        line_numbers: bool = True,
        multiline: bool = False,
        head_limit: int | None = None,
        offset: int = 0,
        **kwargs: Any,
    ) -> ToolResult:
        """
        Search for pattern in files.

        Note: the path parameter was renamed to file_path. If 'path' is passed
        it is caught here to prevent silent misbehaviour.

        Args:
            pattern: Regex pattern to search for
            file_path: File or directory to search (default: current directory)
            file_type: File type filter (e.g., 'py', 'js', 'ts')
            glob: Glob pattern (e.g., '*.py', 'src/**/*.ts')
            output_mode: Output mode - 'content', 'files_with_matches', 'count'
            context_before: Lines before match (like -B)
            context_after: Lines after match (like -A)
            context: Lines before AND after match (like -C)
            case_insensitive: Ignore case (like -i)
            line_numbers: Show line numbers (default: True for content mode)
            multiline: Enable multiline matching (pattern can span lines)
            head_limit: Limit output to first N results
            offset: Skip first N results

        Returns:
            ToolResult with matches
        """
        try:
            # Catch renamed parameter to prevent silent misbehaviour
            if "path" in kwargs:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error="Unknown argument 'path'. Use 'file_path' instead.",
                )

            # Default path
            if file_path is None:
                file_path = "."

            # Validate path for security (prevent path traversal)
            try:
                search_path = validate_path_security(file_path)
            except ValueError as e:
                return ToolResult(
                    tool_name=self.name, status=ToolStatus.ERROR, output=None, error=str(e)
                )

            if not search_path.exists():
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Path not found: {file_path}",
                )

            # Auto-detect output_mode based on whether target is a file or directory.
            # File  -> content:           you already know which file, you want the lines.
            # Dir   -> files_with_matches: narrow down first; also prevents 7MB+ explosions
            #          when the LLM forgets file_path and searches ".".
            if output_mode is None:
                output_mode = "content" if search_path.is_file() else "files_with_matches"

            # Validate output mode
            try:
                mode = OutputMode(output_mode)
            except ValueError:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Invalid output_mode: {output_mode}. Must be 'content', 'files_with_matches', or 'count'",
                )

            # Determine context lines
            context_b = context if context > 0 else context_before
            context_a = context if context > 0 else context_after

            # Default head_limit to prevent context window flooding
            if head_limit is None:
                head_limit = 250

            # Validate regex pattern for security (prevent ReDoS)
            try:
                validate_regex_safety(pattern)
            except ValueError as e:
                return ToolResult(
                    tool_name=self.name, status=ToolStatus.ERROR, output=None, error=str(e)
                )

            # Compile regex pattern
            flags = re.IGNORECASE if case_insensitive else 0
            if multiline:
                flags |= re.MULTILINE | re.DOTALL

            try:
                regex = re.compile(pattern, flags)
            except re.error as e:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Invalid regex pattern: {e}",
                )

            # Find files to search
            files = self._find_files(search_path, file_type, glob)

            if not files:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.SUCCESS,
                    output="No files found matching criteria",
                    metadata={"pattern": pattern, "files_searched": 0, "matches": 0},
                )

            # Search files
            all_matches = []
            file_match_counts = {}
            skipped_files: list[str] = []  # Track files that couldn't be read

            output_truncated = False
            total_output_chars = 0

            for fp in files:
                # For FILES_WITH_MATCHES, use COUNT mode internally to get the real
                # per-file match count so output is "path (N matches)" not just "path".
                search_mode = OutputMode.COUNT if mode == OutputMode.FILES_WITH_MATCHES else mode
                matches = self._search_file(
                    fp, regex, search_mode, context_b, context_a, line_numbers,
                    skipped_files, multiline,
                )

                if matches:
                    if mode == OutputMode.FILES_WITH_MATCHES:
                        count = len(matches)
                        label = "match" if count == 1 else "matches"
                        all_matches.append(f"{fp} ({count} {label})")
                    elif mode == OutputMode.COUNT:
                        file_match_counts[str(fp)] = len(matches)
                    else:  # CONTENT
                        for m in matches:
                            if total_output_chars + len(m) > self.MAX_OUTPUT_CHARS:
                                output_truncated = True
                                break
                            total_output_chars += len(m)
                            all_matches.append(m)
                        if output_truncated:
                            break

            # Apply offset and head_limit
            if mode == OutputMode.FILES_WITH_MATCHES:
                all_matches = all_matches[offset:]
                if head_limit > 0:
                    all_matches = all_matches[:head_limit]
            elif mode == OutputMode.CONTENT:
                all_matches = all_matches[offset:]
                if head_limit > 0:
                    all_matches = all_matches[:head_limit]
            elif mode == OutputMode.COUNT:
                # For count mode, offset/limit applies to number of files
                items = list(file_match_counts.items())[offset:]
                if head_limit > 0:
                    items = items[:head_limit]
                file_match_counts = dict(items)

            # Format output
            if not all_matches and not file_match_counts:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.SUCCESS,
                    output="No matches found",
                    metadata={
                        "pattern": pattern,
                        "files_searched": len(files),
                        "files_skipped": len(skipped_files),
                        "skipped_details": skipped_files[:10],  # First 10 for debugging
                        "matches": 0,
                    },
                )

            # Build output based on mode
            if mode == OutputMode.FILES_WITH_MATCHES:
                output = "\n".join(all_matches)
                total_matches = len(all_matches)
            elif mode == OutputMode.COUNT:
                output_lines = [f"{file}:{count}" for file, count in file_match_counts.items()]
                output = "\n".join(output_lines)
                total_matches = sum(file_match_counts.values())
            else:  # CONTENT
                output = "\n".join(all_matches)
                if output_truncated:
                    output += f"\n[Stopped: {self.MAX_OUTPUT_CHARS:,}-char output budget reached. Use file_path or glob to narrow scope.]"
                total_matches = len(all_matches)

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=output,
                metadata={
                    "pattern": pattern,
                    "files_searched": len(files),
                    "files_skipped": len(skipped_files),
                    "skipped_details": skipped_files[:10],  # First 10 for debugging
                    "matches": total_matches,
                    "output_mode": output_mode,
                    "output_truncated": output_truncated,
                },
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Grep search failed: {str(e)}",
            )

    def _find_files(
        self, search_path: Path, file_type: str | None, glob_pattern: str | None
    ) -> list[Path]:
        """Find files matching criteria."""
        files = []

        if search_path.is_file():
            # Single file
            return [search_path]

        # Directory search — all branches apply _should_skip to exclude node_modules,
        # hidden dirs, build artifacts, and known binary extensions.
        if glob_pattern:
            files = [f for f in search_path.glob(glob_pattern) if f.is_file() and not self._should_skip(f)]
        elif file_type:
            if file_type in FILE_TYPE_MAP:
                patterns = FILE_TYPE_MAP[file_type]
                for pattern in patterns:
                    files.extend(f for f in search_path.rglob(pattern) if f.is_file() and not self._should_skip(f))
            else:
                # Unknown file type - try as extension
                files = [f for f in search_path.rglob(f"*.{file_type}") if f.is_file() and not self._should_skip(f)]
        else:
            files = [f for f in search_path.rglob("*") if f.is_file() and not self._should_skip(f)]

        # Remove duplicates, filter .claraityignore, and sort
        unique_files = sorted(set(files))
        unique_files = filter_paths(unique_files)
        return unique_files

    def _should_skip(self, file_path: Path) -> bool:
        """Check if file should be skipped."""
        # Skip known noisy/build/vcs directories by explicit name.
        # Generic dot-dirs (e.g. .claraity) are NOT skipped here --
        # filter_paths() applies .gitignore/.claraityignore for broad searches.
        skip_dirs = {
            "node_modules", "__pycache__", ".git", ".venv", "venv",
            "dist", "build",
            ".next", ".nuxt", ".svelte-kit", ".turbo", ".yarn",
            ".idea", ".vscode",
            ".pytest_cache", ".mypy_cache", ".ruff_cache",
        }
        if any(part in skip_dirs for part in file_path.parts):
            return True

        # Skip binary file extensions
        skip_exts = {
            ".pyc",
            ".pyo",
            ".so",
            ".dll",
            ".exe",
            ".bin",
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".pdf",
            ".zip",
            ".tar",
            ".gz",
        }
        if file_path.suffix.lower() in skip_exts:
            return True

        return False

    def _search_file(
        self,
        file_path: Path,
        regex: re.Pattern,
        mode: OutputMode,
        context_before: int,
        context_after: int,
        show_line_numbers: bool,
        skipped_files: list[str] | None = None,
        multiline: bool = False,
    ) -> list[str]:
        """
        Search single file for pattern.

        Args:
            file_path: Path to file to search
            regex: Compiled regex pattern
            mode: Output mode (content, files_with_matches, count)
            context_before: Lines of context before match
            context_after: Lines of context after match
            show_line_numbers: Whether to show line numbers
            skipped_files: Optional list to track files that couldn't be read
            multiline: If True, search full file content for cross-line patterns

        Returns:
            list of matching lines or indicators
        """
        # Skip oversized files to prevent OOM
        try:
            size_bytes = file_path.stat().st_size
            if size_bytes > self.MAX_FILE_SIZE_BYTES:
                if skipped_files is not None:
                    skipped_files.append(f"{file_path} (Too large: {size_bytes / (1024 * 1024):.1f} MB)")
                return []
        except OSError:
            pass  # stat failed, try to open anyway

        # Detect binary files: null bytes in first 512 bytes reliably identify non-text content.
        # Extension-based filtering misses extensionless binaries (compiled artifacts, DB dumps).
        # errors="ignore" would silently garble binary content into arbitrarily long lines.
        try:
            with open(file_path, "rb") as f:
                sample = f.read(512)
            if b"\x00" in sample:
                if skipped_files is not None:
                    skipped_files.append(f"{file_path} (Binary file, skipped)")
                return []
        except OSError:
            pass  # Fall through to text-open below

        try:
            with open(file_path, encoding="utf-8", errors="ignore") as f:
                if multiline:
                    content = f.read()
                    lines = content.splitlines(keepends=True)
                else:
                    lines = f.readlines()
        except PermissionError:
            if skipped_files is not None:
                skipped_files.append(f"{file_path} (Permission denied)")
            return []
        except UnicodeDecodeError:
            if skipped_files is not None:
                skipped_files.append(f"{file_path} (Binary file/encoding error)")
            return []
        except FileNotFoundError:
            if skipped_files is not None:
                skipped_files.append(f"{file_path} (File not found)")
            return []
        except Exception as e:
            if skipped_files is not None:
                skipped_files.append(f"{file_path} (Error: {type(e).__name__}: {str(e)})")
            return []

        matched_lines: set[int] = set()  # 0-indexed line numbers that matched

        if multiline:
            # Search full content for cross-line matches, map positions to lines
            if not content:
                return []

            # Build a cumulative offset table for O(1) position->line lookup
            line_offsets = []  # line_offsets[i] = start offset of line i
            offset = 0
            for line in lines:
                line_offsets.append(offset)
                offset += len(line)

            for m in regex.finditer(content):
                start_pos = m.start()
                end_pos = max(m.end() - 1, start_pos)  # inclusive end
                # Binary search for start line
                start_line = self._offset_to_line(line_offsets, start_pos)
                end_line = self._offset_to_line(line_offsets, end_pos)
                for ln in range(start_line, end_line + 1):
                    matched_lines.add(ln)
        else:
            # Standard line-by-line search
            for line_num, line in enumerate(lines):
                if regex.search(line):
                    matched_lines.add(line_num)

        if not matched_lines:
            return []

        # For FILES_WITH_MATCHES, just return indicator
        if mode == OutputMode.FILES_WITH_MATCHES:
            return ["match"]  # Indicator that file has matches

        # For COUNT, return one entry per match so len() gives real count
        if mode == OutputMode.COUNT:
            return list(matched_lines)

        # For CONTENT mode, build output with context
        output_lines: set[int] = set()

        for line_num in matched_lines:
            # Add context lines
            start = max(0, line_num - context_before)
            end = min(len(lines), line_num + context_after + 1)
            output_lines.update(range(start, end))

        # Build formatted output
        matches = []
        for line_num in sorted(output_lines):
            line_content = lines[line_num].rstrip("\n")
            if len(line_content) > self.MAX_LINE_CHARS:
                overflow = len(line_content) - self.MAX_LINE_CHARS
                line_content = line_content[: self.MAX_LINE_CHARS] + f" [...+{overflow} chars]"

            if show_line_numbers:
                # Format: file:line_num: content
                matches.append(f"{file_path}:{line_num + 1}: {line_content}")
            else:
                # Format: file: content
                matches.append(f"{file_path}: {line_content}")

        return matches

    @staticmethod
    def _offset_to_line(line_offsets: list[int], pos: int) -> int:
        """Map a character offset to a 0-indexed line number using binary search."""
        # bisect_right returns the insertion point; subtract 1 for the line containing pos
        return bisect.bisect_right(line_offsets, pos) - 1


class GlobTool(Tool):
    """
    Fast file pattern matching tool.

    Features:
    - Recursive pattern matching (** for any depth)
    - Multiple extension support (e.g., *.{py,js,ts})
    - Fast (doesn't read file contents)
    - Returns sorted by modification time
    - Filters out common non-text files/directories

    Matches Claude Code's Glob tool capabilities.
    """

    _SCHEMA_NAME = "glob"

    def __init__(self):
        super().__init__(
            name="glob",
            description="Find files matching glob patterns (e.g., **/*.py, src/**/*.{ts,tsx})",
        )

    def execute(
        self, pattern: str, file_path: str | None = None, sort_by_mtime: bool = True, **kwargs: Any
    ) -> ToolResult:
        """
        Find files matching glob pattern.

        Args:
            pattern: Glob pattern (e.g., '*.py', '**/*.js', 'src/**/*.{ts,tsx}')
            file_path: Directory to search in (default: current directory)
            sort_by_mtime: Sort results by modification time (newest first)

        Returns:
            ToolResult with matched file paths
        """
        try:
            # Catch renamed parameter to prevent silent misbehaviour
            if "path" in kwargs:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error="Unknown argument 'path'. Use 'file_path' instead.",
                )

            # Default path
            if file_path is None:
                file_path = "."

            # Validate path for security (prevent path traversal)
            try:
                search_path = validate_path_security(file_path)
            except ValueError as e:
                return ToolResult(
                    tool_name=self.name, status=ToolStatus.ERROR, output=None, error=str(e)
                )

            if not search_path.exists():
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Path not found: {file_path}",
                )

            # Handle brace expansion (e.g., *.{py,js,ts})
            patterns = self._expand_braces(pattern)

            # Find matching files
            all_files: set[Path] = set()

            for pat in patterns:
                # Use glob for pattern matching
                matches = search_path.glob(pat)

                # Filter out directories and unwanted files
                files = [f for f in matches if f.is_file() and not self._should_skip(f)]
                all_files.update(files)

            # Filter .claraityignore-blocked files
            all_files = set(filter_paths(list(all_files)))

            if not all_files:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.SUCCESS,
                    output="No files found matching pattern",
                    metadata={"pattern": pattern, "matches": 0},
                )

            # Sort files
            if sort_by_mtime:
                # Sort by modification time (newest first)
                sorted_files = sorted(all_files, key=lambda f: f.stat().st_mtime, reverse=True)
            else:
                # Sort alphabetically
                sorted_files = sorted(all_files)

            # Format output
            output_lines = [str(f) for f in sorted_files]
            output = "\n".join(output_lines)

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=output,
                metadata={"pattern": pattern, "matches": len(sorted_files)},
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Glob search failed: {str(e)}",
            )

    def _expand_braces(self, pattern: str) -> list[str]:
        """
        Expand brace patterns (e.g., *.{py,js,ts} -> [*.py, *.js, *.ts]).
        """
        # Simple brace expansion
        if "{" not in pattern or "}" not in pattern:
            return [pattern]

        # Find brace group
        start = pattern.find("{")
        end = pattern.find("}", start)

        if start == -1 or end == -1:
            return [pattern]

        prefix = pattern[:start]
        suffix = pattern[end + 1 :]
        options = pattern[start + 1 : end].split(",")

        # Generate all combinations
        expanded = [f"{prefix}{opt.strip()}{suffix}" for opt in options]

        # Recursively expand if there are more braces
        final_expanded = []
        for exp in expanded:
            final_expanded.extend(self._expand_braces(exp))

        return final_expanded

    def _should_skip(self, file_path: Path) -> bool:
        """Check if file should be skipped.

        Glob finds files by name pattern — never reads content — so binary
        extensions are NOT filtered here. Only noisy dependency/build dirs
        are excluded, same as GrepTool's directory skip list.
        """
        # Skip known noisy/build/vcs directories by explicit name.
        # Generic dot-dirs (e.g. .claraity) are NOT skipped here.
        skip_dirs = {
            "node_modules", "__pycache__", ".git", ".venv", "venv",
            "dist", "build",
            ".next", ".nuxt", ".svelte-kit", ".turbo", ".yarn",
            ".idea", ".vscode",
            ".pytest_cache", ".mypy_cache", ".ruff_cache",
        }
        if any(part in skip_dirs for part in file_path.parts):
            return True

        return False


