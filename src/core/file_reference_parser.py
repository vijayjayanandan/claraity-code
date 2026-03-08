"""File reference parser for @file.py syntax in user messages.

This module allows users to reference files using @filename syntax,
similar to Claude Code's file mention feature. When a user types something like:
    "Review @api.py and @utils/helpers.py for optimization"

The parser will:
1. Extract the file references (@api.py, @utils/helpers.py)
2. Read the file contents from disk
3. Inject them into the LLM context as system messages

Supported formats:
- @file.py - Relative to current directory
- @path/to/file.py - Relative path
- @/absolute/path/file.py - Absolute path
- @./src/main.py - Explicit relative path
"""

import re
import os
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional, Dict
import logging

logger = logging.getLogger(__name__)


@dataclass
class FileReference:
    """A file referenced in a user message.

    Attributes:
        original: Original reference string (e.g., "@api.py")
        path: Resolved absolute path to the file
        content: File content (None if not loaded yet)
        error: Error message if file couldn't be loaded
        line_start: Optional starting line number for range reference
        line_end: Optional ending line number for range reference
    """
    original: str
    path: Path
    content: Optional[str] = None
    error: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None

    @property
    def is_loaded(self) -> bool:
        """Check if file was loaded successfully."""
        return self.content is not None and self.error is None

    @property
    def lines_read(self) -> int:
        """Number of lines loaded from the file."""
        if self.content:
            return len(self.content.splitlines())
        return 0

    @property
    def truncated(self) -> bool:
        """Whether the content was truncated during loading."""
        return False

    @property
    def display_path(self) -> str:
        """Get display path (relative if possible)."""
        try:
            return str(self.path.relative_to(Path.cwd()))
        except ValueError:
            return str(self.path)

    def __str__(self) -> str:
        """Human-readable representation."""
        if self.error:
            return f"@{self.display_path} (ERROR: {self.error})"
        elif self.is_loaded:
            lines = len(self.content.splitlines()) if self.content else 0
            return f"@{self.display_path} ({lines} lines)"
        else:
            return f"@{self.display_path} (not loaded)"


class FileReferenceParser:
    """Parser for extracting and loading file references from user messages.

    Examples:
        >>> parser = FileReferenceParser()
        >>> message = "Review @api.py and @utils/helpers.py"
        >>> refs = parser.parse_references(message)
        >>> for ref in refs:
        ...     print(f"{ref.original} -> {ref.path}")

        >>> # Load file contents
        >>> loaded_refs = parser.load_files(refs)
        >>> for ref in loaded_refs:
        ...     if ref.is_loaded:
        ...         print(f"Loaded {ref.display_path}: {len(ref.content)} chars")
    """

    # Regex pattern for matching file references
    # Matches: @filename.ext, @path/to/file.ext, @./relative.py, @/absolute/path.py
    # Also supports line ranges: @file.py:10-20, @file.py:50
    # On Windows, supports drive letters: @C:\path\to\file.py
    FILE_REFERENCE_PATTERN = re.compile(
        r'@([A-Za-z]:[\\\/][A-Za-z0-9_.\\\/\-]+(?:\.[A-Za-z0-9]+)?(?::\d+(?:-\d+)?)?'
        r'|[A-Za-z0-9_./\-]+(?:\.[A-Za-z0-9]+)?(?::\d+(?:-\d+)?)?)'
    )

    def __init__(self, base_dir: Optional[Path] = None, max_file_size: int = 100_000):
        """Initialize file reference parser.

        Args:
            base_dir: Base directory for resolving relative paths (default: current directory)
            max_file_size: Maximum file size to load in characters (default: 100K chars)
        """
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()
        self.max_file_size = max_file_size
        logger.info(f"FileReferenceParser initialized (base_dir: {self.base_dir})")

    def parse_references(self, message: str) -> List[FileReference]:
        """Extract file references from a user message.

        Args:
            message: User message that may contain @file.py references

        Returns:
            List of FileReference objects (content not loaded yet)
        """
        references = []

        for match in self.FILE_REFERENCE_PATTERN.finditer(message):
            original = match.group(0)  # Includes the @ symbol
            file_spec = match.group(1)  # Just the path part

            # Parse line range if present (e.g., @file.py:10-20 or @file.py:50)
            line_start = None
            line_end = None

            # Check for line range suffix - but skip Windows drive letter colons
            # Windows paths like C:\path\file.py have a colon after drive letter
            # We only treat colons as line range separators when followed by digits
            if re.search(r':(\d+(?:-\d+)?)$', file_spec):
                file_path, line_spec = file_spec.rsplit(':', 1)
                try:
                    if '-' in line_spec:
                        # Range: @file.py:10-20
                        start_str, end_str = line_spec.split('-', 1)
                        line_start = int(start_str)
                        line_end = int(end_str)
                    else:
                        # Single line: @file.py:50
                        line_start = int(line_spec)
                        line_end = line_start
                except ValueError:
                    logger.warning(f"Invalid line range in {original}: {line_spec}")
                    file_path = file_spec  # Treat as regular file path
            else:
                file_path = file_spec

            # Resolve path
            try:
                resolved_path = self._resolve_path(file_path)
                references.append(FileReference(
                    original=original,
                    path=resolved_path,
                    line_start=line_start,
                    line_end=line_end
                ))
                logger.debug(f"Parsed reference: {original} -> {resolved_path}")
            except Exception as e:
                logger.warning(f"Failed to resolve path {original}: {e}")
                # Still add reference but with error
                references.append(FileReference(
                    original=original,
                    path=Path(file_path),
                    error=f"Failed to resolve path: {e}"
                ))

        logger.info(f"Parsed {len(references)} file references from message")
        return references

    def _resolve_path(self, file_path: str) -> Path:
        """Resolve a file path relative to base directory.

        Args:
            file_path: File path from reference (without @ symbol)

        Returns:
            Resolved absolute Path object
        """
        path = Path(file_path)

        # If absolute path, use as-is
        if path.is_absolute():
            return path.resolve()

        # Otherwise resolve relative to base_dir
        resolved = (self.base_dir / path).resolve()
        return resolved

    def load_files(self, references: List[FileReference]) -> List[FileReference]:
        """Load file contents for all references.

        Args:
            references: List of FileReference objects to load

        Returns:
            Same list with content populated (or errors set)
        """
        for ref in references:
            if ref.error:
                # Skip if already has an error
                continue

            try:
                ref.content = self._load_file_content(ref)
                logger.info(f"Loaded {ref.display_path}: {len(ref.content)} chars")
            except Exception as e:
                ref.error = str(e)
                logger.warning(f"Failed to load {ref.display_path}: {e}")

        return references

    def _load_file_content(self, ref: FileReference) -> str:
        """Load content for a single file reference.

        Args:
            ref: FileReference to load

        Returns:
            File content as string

        Raises:
            FileNotFoundError: If file doesn't exist
            PermissionError: If file can't be read
            ValueError: If file is too large
        """
        if not ref.path.exists():
            raise FileNotFoundError(f"File not found: {ref.display_path}")

        if not ref.path.is_file():
            raise ValueError(f"Not a file: {ref.display_path}")

        # Check file size
        file_size = ref.path.stat().st_size
        if file_size > self.max_file_size:
            raise ValueError(
                f"File too large: {file_size} chars "
                f"(max: {self.max_file_size})"
            )

        # Read file content
        try:
            with open(ref.path, 'r', encoding='utf-8') as f:
                content = f.read()
        except UnicodeDecodeError:
            # Try reading as binary and decoding with fallback
            with open(ref.path, 'rb') as f:
                content = f.read().decode('utf-8', errors='replace')

        # Apply line range if specified
        if ref.line_start is not None:
            lines = content.splitlines()
            start_idx = max(0, ref.line_start - 1)  # 1-indexed to 0-indexed
            end_idx = min(len(lines), ref.line_end) if ref.line_end else start_idx + 1

            selected_lines = lines[start_idx:end_idx]
            content = '\n'.join(selected_lines)

            logger.debug(
                f"Applied line range {ref.line_start}-{ref.line_end or ref.line_start} "
                f"to {ref.display_path}"
            )

        return content

    def parse_and_load(self, message: str) -> List[FileReference]:
        """Parse and load file references in one step.

        Args:
            message: User message with file references

        Returns:
            List of loaded FileReference objects
        """
        references = self.parse_references(message)
        return self.load_files(references)

    def inject_into_context(
        self,
        references: List[FileReference],
        context: List[Dict[str, str]]
    ) -> List[Dict[str, str]]:
        """Inject loaded file contents into LLM context.

        File contents are added as system messages after the main system prompt
        but before the user's messages. This allows the LLM to reference the files
        when responding.

        Args:
            references: List of loaded FileReference objects
            context: Existing LLM context (list of message dicts)

        Returns:
            Modified context with file contents injected
        """
        # Filter to successfully loaded files
        loaded_refs = [ref for ref in references if ref.is_loaded]

        if not loaded_refs:
            return context

        # Build file context message
        file_parts = []
        for ref in loaded_refs:
            file_parts.append(f"# File: {ref.display_path}")
            if ref.line_start is not None:
                if ref.line_start == ref.line_end:
                    file_parts.append(f"# Line: {ref.line_start}")
                else:
                    file_parts.append(f"# Lines: {ref.line_start}-{ref.line_end}")
            file_parts.append(f"```\n{ref.content}\n```")
            file_parts.append("")  # Blank line between files

        file_context = "\n".join(file_parts)

        # Insert after system prompt (if present)
        # Format: <referenced_files>...</referenced_files>
        file_message = {
            "role": "system",
            "content": f"<referenced_files>\nThe user has referenced these files:\n\n{file_context}\n</referenced_files>"
        }

        # Find insertion point (after first system message)
        insert_idx = 1 if context and context[0]["role"] == "system" else 0

        # Insert file context
        context.insert(insert_idx, file_message)

        logger.info(f"Injected {len(loaded_refs)} files into context at position {insert_idx}")
        return context

    def remove_references_from_message(self, message: str) -> str:
        """Remove file references from message (keep clean user query).

        This is useful if you want to remove @file.py references from the
        user's message after extracting them, so the LLM sees a clean query.

        Args:
            message: Original message with @file.py references

        Returns:
            Message with references removed
        """
        # Replace references with empty string, then clean up extra whitespace
        cleaned = self.FILE_REFERENCE_PATTERN.sub('', message)

        # Clean up extra whitespace
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()

        return cleaned

    def format_summary(self, references: List[FileReference]) -> str:
        """Format a summary of loaded files for display to user.

        Args:
            references: List of FileReference objects

        Returns:
            Human-readable summary string
        """
        if not references:
            return ""

        lines = ["📎 Referenced files:"]

        for ref in references:
            if ref.is_loaded:
                line_count = len(ref.content.splitlines()) if ref.content else 0
                if ref.line_start is not None:
                    if ref.line_start == ref.line_end:
                        lines.append(f"  ✓ {ref.display_path}:{ref.line_start} (1 line)")
                    else:
                        line_range = ref.line_end - ref.line_start + 1
                        lines.append(
                            f"  ✓ {ref.display_path}:{ref.line_start}-{ref.line_end} "
                            f"({line_range} lines)"
                        )
                else:
                    lines.append(f"  ✓ {ref.display_path} ({line_count} lines)")
            else:
                lines.append(f"  ✗ {ref.display_path} - {ref.error}")

        return "\n".join(lines)
