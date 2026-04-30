"""
File operation tools with security and streaming support.

Provides production-grade file operations matching Claude Code capabilities:
- ReadFileTool: Streaming line-range reading with bounded memory
- WriteFileTool: Safe file writing with parent directory creation
- EditFileTool: Find/replace editing
- AppendToFileTool: Safe file appending
- ListDirectoryTool: Directory listing
- RunCommandTool: Shell command execution

Security:
- Path traversal protection via validate_path_security
- Workspace boundary enforcement
"""

import asyncio
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.observability import get_logger
from src.tools.command_safety import check_command_safety, clamp_timeout
from src.tools.powershell_sanitize import sanitize_for_powershell

from .base import Tool, ToolResult, ToolStatus
from .claraityignore import check_command, filter_paths, is_blocked
from .search_tools import validate_path_security

logger = get_logger("tools.file_operations")


class FileOperationTool(Tool):
    """
    Base class for file operation tools with shared security validation.

    Provides:
    - Path validation with traversal protection
    - Configurable workspace root for testing
    """

    # Class-level workspace roots (multi-root workspace support).
    # First entry is the primary root; all entries are valid workspace boundaries.
    _workspace_roots: list[Path] | None = None

    def _validate_path(
        self, file_path: str, must_exist: bool = True, allow_outside_workspace: bool = False
    ) -> Path:
        """
        Validate file path with security checks.

        Args:
            file_path: Path to validate
            must_exist: If True, path must exist
            allow_outside_workspace: If True, allow paths outside workspace

        Returns:
            Validated Path object

        Raises:
            ValueError: If path fails security validation
            FileNotFoundError: If must_exist=True and path doesn't exist
        """
        # Use class-level workspace roots if set
        workspace = self._workspace_roots

        # Validate path security
        validated_path = validate_path_security(
            file_path,
            workspace_root=workspace,
            allow_files_outside_workspace=allow_outside_workspace,
        )

        # Check .claraityignore
        blocked, _pattern = is_blocked(validated_path)
        if blocked:
            raise ValueError("Access denied: file is blocked by user policy")

        # Check existence if required
        if must_exist and not validated_path.exists():
            raise FileNotFoundError(f"Path does not exist: {validated_path}")

        return validated_path


class ReadFileTool(FileOperationTool):
    """
    Tool for reading files with streaming line-range support.

    Features:
    - Streaming reads with bounded memory (never loads entire file)
    - Line range support (start_line, end_line, max_lines)
    - Line number formatting (cat -n style)
    - Long line truncation
    - Path traversal protection
    - PDF text and table extraction (via PyMuPDF)
    - Word (.docx) paragraph and table extraction (via python-docx)

    Matches Claude Code's Read tool capabilities.
    """

    _SCHEMA_NAME = "read_file"

    # Configuration constants
    MAX_LINES_DEFAULT = 1000  # Balanced default - read meaningful chunks
    MAX_LINES_LIMIT = 2000  # Hard cap per request
    MAX_LINE_LENGTH = 2000  # Truncate lines longer than this

    # Document parsing safety limits (configurable per-instance)
    MAX_DOCUMENT_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB - reject before parsing
    MAX_EXTRACTED_LINES = 10_000  # ~200 pages - cap memory during extraction
    MAX_ZIP_DECOMPRESSED_BYTES = 200 * 1024 * 1024  # 200 MB total decompressed
    MAX_ZIP_RATIO = 100  # Max compression ratio before flagging as zip bomb

    # Supported binary document formats
    _BINARY_FORMATS = {".pdf", ".docx"}

    def __init__(self):
        from src.tools.tool_schemas import _SCHEMA_REGISTRY

        _def = _SCHEMA_REGISTRY["read_file"]
        super().__init__(name=_def.name, description=_def.description)

    def _format_extracted_lines(
        self,
        all_lines: list[str],
        path: Path,
        start: int,
        end: int,
        effective_max: int,
    ) -> ToolResult:
        """
        Apply line-range selection and formatting to extracted document lines.

        Shared by PDF and DOCX paths. Takes raw lines from an extractor,
        applies start/end/max bounds, formats with line numbers, and returns
        a ToolResult matching the same structure as plain text reads.
        """
        total_lines = len(all_lines)
        collected_lines: list[str] = []

        for lineno in range(start, min(end, total_lines + 1)):
            if len(collected_lines) >= effective_max:
                break
            idx = lineno - 1  # Convert 1-indexed to 0-indexed
            if idx < 0 or idx >= total_lines:
                break
            line_content = all_lines[idx]
            # Truncate long lines
            if len(line_content) > self.MAX_LINE_LENGTH:
                line_content = line_content[: self.MAX_LINE_LENGTH] + "... [truncated]"
            collected_lines.append(f"{lineno:6}\t{line_content}")

        content = "\n".join(collected_lines)
        actual_start = start
        actual_end = start + len(collected_lines)
        has_more = actual_end <= total_lines

        if has_more and len(collected_lines) > 0:
            content += (
                f"\n\n[Lines {actual_start}-{actual_end - 1} of {total_lines}"
                f" | Continue: start_line={actual_end}, max_lines={self.MAX_LINES_LIMIT}]"
            )

        return ToolResult(
            tool_name=self.name,
            status=ToolStatus.SUCCESS,
            output=content,
            metadata={
                "file_path": str(path),
                "total_lines": total_lines,
                "lines_returned": len(collected_lines),
                "start_line": actual_start,
                "end_line": actual_end,
                "has_more": has_more,
            },
        )

    def _build_multimodal_result(
        self,
        text_result: ToolResult,
        images: list[dict],
    ) -> ToolResult:
        """Build a multimodal ToolResult with images interleaved at their document positions.

        The formatted text from _format_extracted_lines contains [IMAGE:N] markers
        at the positions where images should appear (with line number prefixes like
        "     7\\t[IMAGE:2]"). This method splits the text at those markers and
        interleaves image content blocks between the text segments.
        """
        import re

        text_output = str(text_result.output or "")
        if not text_output or not images:
            # No text or no images -- return text as-is
            return text_result

        # Split at image markers (line-numbered: "   7\t[IMAGE:2]")
        IMAGE_MARKER = re.compile(r"^\s*\d+\t\[IMAGE:(\d+)\]\s*$", re.MULTILINE)
        parts = IMAGE_MARKER.split(text_output)

        # parts alternates: [text, img_idx_str, text, img_idx_str, ...]
        content_blocks: list[dict[str, Any]] = []
        image_count = 0

        for i, part in enumerate(parts):
            if i % 2 == 0:
                # Text segment
                text = part.strip()
                if text:
                    content_blocks.append({"type": "text", "text": text})
            else:
                # Image index
                img_idx = int(part)
                if img_idx < len(images):
                    img = images[img_idx]
                    b64 = img.get("base64", "")
                    media_type = img.get("media_type", "image/png")
                    content_blocks.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{media_type};base64,{b64}"},
                        }
                    )
                    image_count += 1

        if image_count:
            content_blocks.append(
                {
                    "type": "text",
                    "text": f"[{image_count} embedded image(s) extracted from document]",
                }
            )

        metadata = dict(text_result.metadata)
        metadata["image_count"] = image_count

        return ToolResult(
            tool_name=self.name,
            status=text_result.status,
            output=content_blocks,
            metadata=metadata,
        )

    def execute(
        self,
        file_path: str,
        start_line: int | None = None,
        end_line: int | None = None,
        max_lines: int | None = None,
        extract_images: bool = False,
        pages: str | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        """
        Read file contents with streaming (bounded memory).

        Args:
            file_path: Path to file to read
            start_line: 1-indexed start line, inclusive (default: 1)
            end_line: 1-indexed end line, EXCLUSIVE (default: start + max_lines)
            max_lines: Maximum lines to return (default: 1000, max: 2000)
            extract_images: For PDF/DOCX only. When True, renders pages with images
                as full-page screenshots (PDF) or extracts inline images (DOCX).
                Default False returns text-only with image hints.
            pages: For PDF only. Page numbers/ranges to process, e.g. "3", "1-5", "3,7,9".
                When omitted, processes all pages.

        Returns:
            ToolResult with file contents and metadata

        Line Semantics:
            - start_line=100, end_line=200 returns lines 100-199 (100 lines)
            - start_line and end_line are 1-indexed to match editor line numbers
            - end_line is EXCLUSIVE (standard Python semantics)
        """
        try:
            # Validate path security.
            # Reads allow outside-workspace paths because the gating service
            # enforces an approval prompt before execution reaches here.
            try:
                path = self._validate_path(
                    file_path, must_exist=True, allow_outside_workspace=True
                )
            except ValueError as e:
                return ToolResult(
                    tool_name=self.name, status=ToolStatus.ERROR, output=None, error=str(e)
                )
            except FileNotFoundError:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"File not found: {file_path}",
                )

            if not path.is_file():
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Path is not a file: {file_path}",
                )

            # Determine bounds
            start = max(1, start_line or 1)  # 1-indexed, minimum 1
            effective_max = min(max_lines or self.MAX_LINES_DEFAULT, self.MAX_LINES_LIMIT)

            # Calculate end_line if not specified
            if end_line is not None:
                # User specified end_line - use it (exclusive)
                end = end_line
            else:
                # Default: start + max_lines
                end = start + effective_max

            # --- Binary document format handling ---
            suffix = path.suffix.lower()
            if suffix in self._BINARY_FORMATS:
                # Pre-flight: reject oversized files before parsing
                file_size = path.stat().st_size
                if file_size > self.MAX_DOCUMENT_SIZE_BYTES:
                    size_mb = file_size / (1024 * 1024)
                    limit_mb = self.MAX_DOCUMENT_SIZE_BYTES / (1024 * 1024)
                    return ToolResult(
                        tool_name=self.name,
                        status=ToolStatus.ERROR,
                        output=None,
                        error=(f"Document too large: {size_mb:.1f} MB (limit: {limit_mb:.0f} MB)."),
                    )

                # Run extraction in a subprocess for C-library crash isolation.
                # If PyMuPDF's MuPDF segfaults, only the child process dies.
                # Frozen binary: sys.executable is the .exe, use --extract-doc flag
                # Source mode: sys.executable is python, use -m src.server --extract-doc
                try:
                    if getattr(sys, "_MEIPASS", None):
                        cmd = [sys.executable, "--extract-doc"]
                    else:
                        cmd = [sys.executable, "-m", "src.server", "--extract-doc"]
                    cmd.extend(
                        [
                            str(path),
                            "--format",
                            suffix.lstrip("."),
                            "--max-lines",
                            str(self.MAX_EXTRACTED_LINES),
                            "--max-zip-size",
                            str(self.MAX_ZIP_DECOMPRESSED_BYTES),
                            "--max-zip-ratio",
                            str(self.MAX_ZIP_RATIO),
                        ]
                    )
                    if extract_images:
                        cmd.append("--extract-images")
                    if pages and suffix == ".pdf":
                        cmd.extend(["--pages", str(pages)])
                    proc = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        stdin=subprocess.DEVNULL,
                        timeout=30,
                    )

                    if proc.returncode != 0:
                        logger.warning(
                            "document_extractor_crashed",
                            path=str(path),
                            format=suffix,
                            returncode=proc.returncode,
                        )
                        return ToolResult(
                            tool_name=self.name,
                            status=ToolStatus.ERROR,
                            output=None,
                            error=f"Failed to extract text from {suffix} file. "
                            f"The file may be corrupt or unsupported.",
                        )

                    data = json.loads(proc.stdout)

                    if data.get("error"):
                        raw_error = data["error"]
                        # Pass through install instructions (safe, helpful).
                        # Sanitize everything else to avoid leaking paths.
                        if "pip install" in raw_error:
                            error_msg = raw_error
                        else:
                            logger.warning(
                                "document_extraction_error",
                                path=str(path),
                                format=suffix,
                                error=raw_error,
                            )
                            error_msg = (
                                f"Failed to extract text from {suffix} file. "
                                f"The file may be corrupt or unsupported."
                            )
                        return ToolResult(
                            tool_name=self.name,
                            status=ToolStatus.ERROR,
                            output=None,
                            error=error_msg,
                        )

                    all_lines = data["lines"]
                    images = data.get("images", [])
                    text_result = self._format_extracted_lines(
                        all_lines,
                        path,
                        start,
                        end,
                        effective_max,
                    )

                    # If images were extracted, build multimodal content
                    if images:
                        return self._build_multimodal_result(text_result, images)
                    return text_result

                except subprocess.TimeoutExpired:
                    return ToolResult(
                        tool_name=self.name,
                        status=ToolStatus.ERROR,
                        output=None,
                        error="Document extraction timed out after 30 seconds.",
                    )
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning(
                        "document_extractor_bad_output",
                        path=str(path),
                        format=suffix,
                        error=str(e),
                    )
                    return ToolResult(
                        tool_name=self.name,
                        status=ToolStatus.ERROR,
                        output=None,
                        error=f"Failed to extract text from {suffix} file. "
                        f"The file may be corrupt or unsupported.",
                    )
                except Exception as e:
                    logger.warning(
                        "document_extraction_failed",
                        path=str(path),
                        format=suffix,
                        error=str(e),
                    )
                    return ToolResult(
                        tool_name=self.name,
                        status=ToolStatus.ERROR,
                        output=None,
                        error=f"Failed to extract text from {suffix} file. "
                        f"The file may be corrupt or unsupported.",
                    )

            # STREAMING READ - bounded memory (plain text files)
            # Only stores lines we need, stops early
            collected_lines: list[str] = []
            total_lines = 0
            stopped_at_end = False

            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    for lineno, line in enumerate(f, start=1):
                        total_lines = lineno

                        # Skip lines before start
                        if lineno < start:
                            continue

                        # Stop if we hit end_line (exclusive)
                        if lineno >= end:
                            stopped_at_end = True
                            break

                        # Stop if we have enough lines
                        if len(collected_lines) >= effective_max:
                            break

                        # Format line with line number (cat -n style)
                        line_content = line.rstrip("\n\r")

                        # Truncate long lines
                        if len(line_content) > self.MAX_LINE_LENGTH:
                            line_content = line_content[: self.MAX_LINE_LENGTH] + "... [truncated]"

                        # Format: 6-digit line number + tab + content
                        collected_lines.append(f"{lineno:6}\t{line_content}")

            except PermissionError:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Permission denied reading file: {file_path}",
                )
            except UnicodeDecodeError as e:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Encoding error reading file: {file_path} - {str(e)}",
                )

            # If we stopped early (not at end_line), count remaining lines
            if not stopped_at_end and len(collected_lines) >= effective_max:
                # We stopped due to max_lines, need to count rest of file
                try:
                    with open(path, encoding="utf-8", errors="replace") as f:
                        total_lines = sum(1 for _ in f)
                except Exception:
                    pass  # Keep the count we had

            # Build output
            content = "\n".join(collected_lines)

            # Calculate actual end line returned
            actual_start = start
            actual_end = start + len(collected_lines)  # Exclusive
            has_more = actual_end <= total_lines

            # Add hint if there's more content
            if has_more and len(collected_lines) > 0:
                content += f"\n\n[Lines {actual_start}-{actual_end - 1} of {total_lines} | Continue: start_line={actual_end}, max_lines={self.MAX_LINES_LIMIT}]"

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=content,
                metadata={
                    "file_path": str(path),
                    "total_lines": total_lines,
                    "lines_returned": len(collected_lines),
                    "start_line": actual_start,
                    "end_line": actual_end,  # Exclusive
                    "has_more": has_more,
                },
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to read file: {str(e)}",
            )


class WriteFileTool(FileOperationTool):
    """Tool for writing files with security validation."""

    _SCHEMA_NAME = "write_file"

    def __init__(self):
        from src.tools.tool_schemas import _SCHEMA_REGISTRY

        _def = _SCHEMA_REGISTRY["write_file"]
        super().__init__(name=_def.name, description=_def.description)

    def execute(self, file_path: str, content: str, **kwargs: Any) -> ToolResult:
        """Write content to file."""
        try:
            # Validate path security (must_exist=False for new files).
            # Outside-workspace writes are allowed here because the gating
            # service enforces an approval prompt before execution.
            try:
                path = self._validate_path(
                    file_path, must_exist=False, allow_outside_workspace=True
                )
            except ValueError as e:
                return ToolResult(
                    tool_name=self.name, status=ToolStatus.ERROR, output=None, error=str(e)
                )

            # Create parent directories if needed
            path.parent.mkdir(parents=True, exist_ok=True)

            with open(path, "w", encoding="utf-8") as f:
                f.write(content)

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=f"Successfully wrote {len(content)} characters to {file_path}",
                metadata={"file_path": str(path), "size": len(content)},
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to write file: {str(e)}",
            )


class ListDirectoryTool(FileOperationTool):
    """Tool for listing directory contents with security validation."""

    _SCHEMA_NAME = "list_directory"

    def __init__(self):
        from src.tools.tool_schemas import _SCHEMA_REGISTRY

        _def = _SCHEMA_REGISTRY["list_directory"]
        super().__init__(name=_def.name, description=_def.description)

    def execute(self, directory_path: str, **kwargs: Any) -> ToolResult:
        """list directory contents."""
        try:
            # Validate path security.
            # Reads allow outside-workspace paths because the gating service
            # enforces an approval prompt before execution reaches here.
            try:
                path = self._validate_path(
                    directory_path, must_exist=True, allow_outside_workspace=True
                )
            except ValueError as e:
                return ToolResult(
                    tool_name=self.name, status=ToolStatus.ERROR, output=None, error=str(e)
                )
            except FileNotFoundError:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Directory not found: {directory_path}",
                )

            if not path.is_dir():
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Path is not a directory: {directory_path}",
                )

            entries = []
            # Only .claraityignore policy applies here -- gitignore is intentionally
            # not used. The user explicitly named this directory; gitignore should not
            # censor its contents.
            for entry in path.iterdir():
                blocked, _ = is_blocked(entry)
                if blocked:
                    continue
                stat = entry.stat()
                mtime_iso = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
                entry_info = {
                    "name": entry.name,
                    "type": "directory" if entry.is_dir() else "file",
                    "size": stat.st_size if entry.is_file() else None,
                    "mtime": mtime_iso,
                }
                entries.append(entry_info)

            # Sort entries: directories first, then files, both alphabetically
            entries.sort(key=lambda x: (x["type"] == "file", x["name"].lower()))

            # Format as human-readable text so str() in downstream
            # consumers (agent, subagent, VS Code serializer) is a no-op
            output_lines = []
            for e in entries:
                if e["type"] == "directory":
                    output_lines.append(f"[dir]  {e['name']}/")
                else:
                    size_str = f" ({e['size']} bytes)" if e["size"] is not None else ""
                    output_lines.append(f"[file] {e['name']}{size_str}")

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output="\n".join(output_lines),
                metadata={
                    "directory_path": str(path),
                    "entry_count": len(entries),
                    "entries": entries,
                },
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to list directory: {str(e)}",
            )


class EditFileTool(FileOperationTool):
    """Tool for editing files with find/replace and security validation."""

    _SCHEMA_NAME = "edit_file"

    def __init__(self):
        from src.tools.tool_schemas import _SCHEMA_REGISTRY

        _def = _SCHEMA_REGISTRY["edit_file"]
        super().__init__(name=_def.name, description=_def.description)

    def execute(
        self,
        file_path: str,
        old_text: str,
        new_text: str,
        replace_all: bool = False,
        **kwargs: Any,
    ) -> ToolResult:
        """Edit file with find/replace."""
        try:
            # Validate path security.
            # Outside-workspace edits are allowed here because the gating
            # service enforces an approval prompt before execution.
            try:
                path = self._validate_path(
                    file_path, must_exist=True, allow_outside_workspace=True
                )
            except ValueError as e:
                return ToolResult(
                    tool_name=self.name, status=ToolStatus.ERROR, output=None, error=str(e)
                )
            except FileNotFoundError:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"File not found: {file_path}",
                )

            # Read current content
            with open(path, encoding="utf-8") as f:
                content = f.read()

            # Check if old_text exists
            if old_text not in content:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error="Text to replace not found in file",
                )

            # Uniqueness check: require unique match unless replace_all=True
            occurrence_count = content.count(old_text)
            if occurrence_count > 1 and not replace_all:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=(
                        f"old_text matches {occurrence_count} locations in the file. "
                        f"Provide more surrounding context to make the match unique, "
                        f"or set replace_all=true to replace all occurrences."
                    ),
                )

            # Replace (single or all)
            if replace_all:
                new_content = content.replace(old_text, new_text)
            else:
                new_content = content.replace(old_text, new_text, 1)

            # Write back
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_content)

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=f"Successfully edited {file_path}",
                metadata={
                    "file_path": str(path),
                    "replacements": occurrence_count if replace_all else 1,
                },
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to edit file: {str(e)}",
            )


class AppendToFileTool(FileOperationTool):
    """Tool for appending content to files with security validation."""

    _SCHEMA_NAME = "append_to_file"

    def __init__(self):
        from src.tools.tool_schemas import _SCHEMA_REGISTRY

        _def = _SCHEMA_REGISTRY["append_to_file"]
        super().__init__(name=_def.name, description=_def.description)

    def execute(self, file_path: str, content: str, **kwargs: Any) -> ToolResult:
        """Append content to file."""
        try:
            # Validate path security (must_exist=False for new files).
            # Outside-workspace appends are allowed here because the gating
            # service enforces an approval prompt before execution.
            try:
                path = self._validate_path(
                    file_path, must_exist=False, allow_outside_workspace=True
                )
            except ValueError as e:
                return ToolResult(
                    tool_name=self.name, status=ToolStatus.ERROR, output=None, error=str(e)
                )

            # Create parent directories if needed
            path.parent.mkdir(parents=True, exist_ok=True)

            # Determine if we need a leading newline (efficient: seek to end)
            needs_newline = False
            if path.exists() and path.stat().st_size > 0:
                with open(path, "rb") as f:
                    f.seek(-1, 2)  # Seek to last byte
                    last_byte = f.read(1)
                    needs_newline = last_byte != b"\n"

            # Append content
            with open(path, "a", encoding="utf-8") as f:
                if needs_newline:
                    f.write("\n")
                f.write(content)

            # Get total file stats (efficient line count)
            total_size = path.stat().st_size
            with open(path, encoding="utf-8") as f:
                total_lines = sum(1 for _ in f)

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=f"Successfully appended {len(content)} characters to {file_path} (total: {total_lines} lines, {total_size} bytes)",
                metadata={
                    "file_path": str(path),
                    "appended_size": len(content),
                    "total_size": total_size,
                    "total_lines": total_lines,
                },
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to append to file: {str(e)}",
            )


class RunCommandTool(Tool):
    """
    Tool for running shell commands safely.

    Supports two execution modes:
    1. Background execution (background=True) - non-blocking with task registry
    2. Captured execution (default) - returns captured output

    Note: Does not inherit from FileOperationTool as it doesn't
    operate on files directly. Security handled via command validation.
    """

    _SCHEMA_NAME = "run_command"

    def __init__(self, registry=None):
        from src.tools.tool_schemas import _SCHEMA_REGISTRY

        _def = _SCHEMA_REGISTRY["run_command"]
        super().__init__(name=_def.name, description=_def.description)
        self._registry = registry
        self._ui_protocol = None

    def set_ui_protocol(self, protocol) -> None:
        """Wire UIProtocol for interrupt detection during foreground execution.

        Called post-registration by stdio_server.py (VS Code) and
        subagent_coordinator.py (TUI), mirroring DelegateToSubagentTool pattern.
        """
        self._ui_protocol = protocol
        logger.info("RunCommandTool: UIProtocol wired")

    async def _kill_process(self, process: asyncio.subprocess.Process) -> None:
        """Kill process and wait for exit. Kills entire process tree on both platforms."""
        if platform.system() == "Windows":
            # taskkill /F /T kills the shell and all its child processes.
            # process.kill() alone only kills the direct child, leaving
            # grandchildren running with pipe handles open.
            try:
                kill_proc = await asyncio.create_subprocess_exec(
                    "taskkill",
                    "/F",
                    "/T",
                    "/PID",
                    str(process.pid),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.wait_for(kill_proc.wait(), timeout=5.0)
            except Exception:
                pass
        else:
            # On Unix, kill the entire process group so grandchildren are also
            # terminated. The subprocess was launched with start_new_session=True,
            # making process.pid the process group leader -- os.killpg targets all
            # members of that group. process.kill() would only kill the shell.
            import os
            import signal

            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except Exception:
                pass
        try:
            await asyncio.wait_for(process.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            pass

    async def execute_async(
        self,
        command: str,
        working_directory: str | None = None,
        timeout: int = 120,
        background: bool = False,
        description: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        """Async execution path.

        Execution order:
        1. If background=True -> delegate to BackgroundTaskRegistry
        2. Otherwise -> run as interruptible asyncio subprocess
        """
        # --- FOREGROUND EXECUTION (interruptible async path) ---
        if not background:
            return await self._execute_foreground_async(
                command=command,
                working_directory=working_directory,
                timeout=timeout,
            )

        # --- Background path ---
        if self._registry is None:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error="Background execution not available (no task registry configured)",
            )

        if not command or not command.strip():
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error="Command cannot be empty",
            )

        # --- CLARAITYIGNORE CHECK ---
        cmd_blocked, cmd_reason = check_command(command)
        if cmd_blocked:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=cmd_reason,
            )

        # Validate working directory (same checks as sync path)
        work_dir = None
        if working_directory:
            cwd_path = Path(working_directory)
            if not cwd_path.exists():
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Working directory does not exist: {working_directory}",
                )
            if not cwd_path.is_dir():
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Working directory path is not a directory: {working_directory}",
                )
            work_dir = str(cwd_path.absolute())

        task_id, error = await self._registry.launch(
            command=command,
            description=description,
            working_dir=work_dir,
            timeout=timeout if timeout != 120 else None,  # let registry use its default
        )

        if error:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=error,
            )

        active = self._registry.active_count()
        return ToolResult(
            tool_name=self.name,
            status=ToolStatus.SUCCESS,
            output=(
                f"Background task launched: {task_id}\n"
                f"Command: {command}\n"
                f"Active background tasks: {active}\n"
                "You will receive a [BACKGROUND TASK UPDATE] notification with full output when done. "
                "Do NOT call check_background_task — continue with other work."
            ),
        )

    async def _execute_foreground_async(
        self,
        command: str,
        working_directory: str | None = None,
        timeout: int = 120,
    ) -> ToolResult:
        """Interruptible async foreground execution via asyncio subprocess.

        Mirrors DelegateToSubagentTool.execute_async() interrupt pattern:
        polls _ui_protocol.check_interrupted() while streaming output,
        terminates the process tree on user interrupt, returns partial output.
        """
        # --- INPUT VALIDATION (mirrors sync execute()) ---
        if not command or not command.strip():
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error="Command cannot be empty",
            )

        from src.tools.command_safety import CommandSafety

        safety_result = check_command_safety(command)
        if safety_result.safety == CommandSafety.BLOCK:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=(
                    f"[BLOCKED] Command rejected by safety controls: {safety_result.reason}\n"
                    "This command cannot be executed."
                ),
            )

        cmd_blocked, cmd_reason = check_command(command)
        if cmd_blocked:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=cmd_reason,
            )

        timeout = clamp_timeout(timeout)

        cwd = None
        if working_directory:
            cwd_path = Path(working_directory)
            if not cwd_path.exists():
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Working directory does not exist: {working_directory}",
                )
            if not cwd_path.is_dir():
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Working directory path is not a directory: {working_directory}",
                )
            cwd = str(cwd_path.absolute())

        # --- SHELL SELECTION (mirrors sync execute()) ---
        from src.platform import detect_preferred_shell, get_bash_env

        shell_info = detect_preferred_shell()
        if shell_info["syntax"] == "powershell":
            command = sanitize_for_powershell(command)

        def _ensure_pythonioencoding(env: dict | None) -> dict:
            e = env if env is not None else os.environ.copy()
            e.setdefault("PYTHONIOENCODING", "utf-8")
            return e

        # --- LAUNCH ASYNC SUBPROCESS ---
        process: asyncio.subprocess.Process
        try:
            if platform.system() == "Windows":
                import subprocess as _sp

                if shell_info["shell"] == "bash":
                    bash_env = get_bash_env(shell_info["path"])
                    bash_env = _ensure_pythonioencoding(bash_env)
                    process = await asyncio.create_subprocess_exec(
                        shell_info["path"],
                        "-c",
                        command,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        stdin=asyncio.subprocess.DEVNULL,
                        cwd=cwd,
                        creationflags=_sp.CREATE_NO_WINDOW,
                        env=bash_env,
                    )
                else:
                    ps_env = _ensure_pythonioencoding(None)
                    process = await asyncio.create_subprocess_exec(
                        "powershell",
                        "-NoProfile",
                        "-Command",
                        command,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        stdin=asyncio.subprocess.DEVNULL,
                        cwd=cwd,
                        creationflags=_sp.CREATE_NO_WINDOW,
                        env=ps_env,
                    )
            else:
                process = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    stdin=asyncio.subprocess.DEVNULL,
                    cwd=cwd,
                    start_new_session=True,
                )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to launch command: {e}",
            )

        # --- STREAM OUTPUT WITH INTERRUPT POLLING ---
        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []

        async def _read_stream(stream: asyncio.StreamReader, chunks: list[str]) -> None:
            while True:
                chunk = await stream.read(4096)
                if not chunk:
                    break
                chunks.append(chunk.decode("utf-8", errors="replace"))

        def _assemble_partial() -> str:
            parts = []
            if stdout_chunks:
                parts.append("STDOUT:\n" + "".join(stdout_chunks))
            if stderr_chunks:
                parts.append("STDERR:\n" + "".join(stderr_chunks))
            return "\n\n".join(parts) if parts else "(no output)"

        stdout_task = asyncio.create_task(_read_stream(process.stdout, stdout_chunks))
        stderr_task = asyncio.create_task(_read_stream(process.stderr, stderr_chunks))

        try:
            loop = asyncio.get_running_loop()
            deadline = loop.time() + timeout
            while True:
                # Check for user interrupt
                if self._ui_protocol and self._ui_protocol.check_interrupted():
                    logger.info("RunCommandTool: interrupt detected -- terminating subprocess")
                    await self._kill_process(process)
                    stdout_task.cancel()
                    stderr_task.cancel()
                    for t in (stdout_task, stderr_task):
                        try:
                            await t
                        except (asyncio.CancelledError, Exception):
                            pass
                    return ToolResult(
                        tool_name=self.name,
                        status=ToolStatus.ERROR,
                        output=_assemble_partial(),
                        error="Command cancelled by user interrupt",
                        metadata={
                            "command": command,
                            "working_directory": cwd or "current",
                            "interrupted": True,
                        },
                    )

                # Check for timeout
                if loop.time() >= deadline:
                    logger.warning("RunCommandTool: foreground command timed out")
                    await self._kill_process(process)
                    stdout_task.cancel()
                    stderr_task.cancel()
                    for t in (stdout_task, stderr_task):
                        try:
                            await t
                        except (asyncio.CancelledError, Exception):
                            pass
                    return ToolResult(
                        tool_name=self.name,
                        status=ToolStatus.ERROR,
                        output=_assemble_partial(),
                        error=f"Command timed out after {timeout} seconds. "
                        f"Use a longer timeout if the command needs more time (max 600s).",
                        metadata={
                            "command": command,
                            "timeout": timeout,
                            "working_directory": cwd or "current",
                            "partial_output": bool(stdout_chunks or stderr_chunks),
                        },
                    )

                # Poll: wait up to 0.2s for process to finish
                try:
                    await asyncio.wait_for(
                        asyncio.shield(asyncio.gather(stdout_task, stderr_task)), timeout=0.2
                    )
                    break  # Both stream readers finished -> process done
                except asyncio.TimeoutError:
                    pass  # Still running, loop again to check interrupt/timeout
                except asyncio.CancelledError:
                    raise

            # Wait for process exit code
            await process.wait()

        except asyncio.CancelledError:
            # Hard cancel from task.cancel() -- e.g. Stop button in VS Code cancels the
            # entire streaming task immediately, raising CancelledError here before the
            # interrupt-poll loop gets a chance to fire. Kill the subprocess and return
            # a ToolResult so _run_one can store it and the LLM sees the cancellation.
            # Do NOT re-raise: the caller (stream_response) checks check_interrupted()
            # on the next iteration and exits cleanly.
            logger.info("RunCommandTool: hard cancel -- terminating subprocess")
            await self._kill_process(process)
            stdout_task.cancel()
            stderr_task.cancel()
            for t in (stdout_task, stderr_task):
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=_assemble_partial(),
                error="Command cancelled by user (Stop pressed)",
                metadata={
                    "command": command,
                    "working_directory": cwd or "current",
                    "interrupted": True,
                },
            )

        # --- BUILD RESULT ---
        output = _assemble_partial()

        logger.info(
            f"[COMMAND_AUDIT] Executed: {command[:200]}, exit_code={process.returncode}, timeout={timeout}s"
        )

        if process.returncode == 0:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=output,
                metadata={
                    "command": command,
                    "exit_code": process.returncode,
                    "working_directory": cwd or "current",
                    "has_stdout": bool(stdout_chunks),
                    "has_stderr": bool(stderr_chunks),
                },
            )
        else:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=output,
                error=f"Command failed with exit code {process.returncode}",
                metadata={
                    "command": command,
                    "exit_code": process.returncode,
                    "working_directory": cwd or "current",
                },
            )

    def execute(
        self, command: str, working_directory: str | None = None, timeout: int = 120, **kwargs: Any
    ) -> ToolResult:
        """Execute a shell command."""
        try:
            # Validate inputs
            if not command or not command.strip():
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error="Command cannot be empty",
                )

            # --- COMMAND SAFETY CHECK (defense-in-depth) ---
            # Primary enforcement is in ToolGatingService.check_command_safety_gate().
            # This is a second barrier: only hard-blocks here (NEEDS_APPROVAL
            # was already handled at the gating layer before execute() is called).
            from src.tools.command_safety import CommandSafety

            safety_result = check_command_safety(command)
            if safety_result.safety == CommandSafety.BLOCK:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=(
                        f"[BLOCKED] Command rejected by safety controls: {safety_result.reason}\n"
                        "This command cannot be executed."
                    ),
                )

            # --- CLARAITYIGNORE CHECK ---
            cmd_blocked, cmd_reason = check_command(command)
            if cmd_blocked:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=cmd_reason,
                )

            # --- CLAMP TIMEOUT ---
            timeout = clamp_timeout(timeout)

            # Validate working directory if provided
            cwd = None
            if working_directory:
                cwd_path = Path(working_directory)
                if not cwd_path.exists():
                    return ToolResult(
                        tool_name=self.name,
                        status=ToolStatus.ERROR,
                        output=None,
                        error=f"Working directory does not exist: {working_directory}",
                    )
                if not cwd_path.is_dir():
                    return ToolResult(
                        tool_name=self.name,
                        status=ToolStatus.ERROR,
                        output=None,
                        error=f"Working directory path is not a directory: {working_directory}",
                    )
                cwd = str(cwd_path.absolute())

            # Detect preferred shell and execute accordingly.
            # On Windows, prefer bash (Git Bash) for reliable exit codes and
            # Unix syntax parity. Fall back to PowerShell if bash unavailable.
            from src.platform import detect_preferred_shell, get_bash_env

            shell_info = detect_preferred_shell()

            # Only sanitize for PowerShell; bash doesn't need it
            if shell_info["syntax"] == "powershell":
                command = sanitize_for_powershell(command)

            # Execute command
            # stdin=DEVNULL prevents subprocess from reading terminal input
            # CREATE_NO_WINDOW / start_new_session isolate subprocess from parent terminal,
            # preventing tools like npx from writing escape sequences directly to the TUI
            if platform.system() == "Windows":
                # PYTHONIOENCODING=utf-8 aligns child Python's stdout/stderr
                # encoding with how we read the pipe (encoding="utf-8" below).
                # Without this, child Python defaults to cp1252 on Windows and
                # crashes on any non-cp1252 character in print(). Only affects
                # stdin/stdout/stderr — does NOT change file I/O defaults.
                def _ensure_pythonioencoding(env: dict | None) -> dict:
                    e = env if env is not None else os.environ.copy()
                    e.setdefault("PYTHONIOENCODING", "utf-8")
                    return e

                if shell_info["shell"] == "bash":
                    # Git Bash: reliable exit codes, Unix syntax.
                    # get_bash_env() ensures Git tools (tail, grep, etc.) are on
                    # PATH even when spawned from VS Code's system PATH.
                    bash_env = get_bash_env(shell_info["path"])
                    bash_env = _ensure_pythonioencoding(bash_env)
                    result = subprocess.run(
                        [shell_info["path"], "-c", command],
                        cwd=cwd,
                        capture_output=True,
                        text=True,
                        timeout=timeout,
                        encoding="utf-8",
                        errors="replace",
                        stdin=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                        env=bash_env,
                    )
                else:
                    # PowerShell fallback
                    ps_env = _ensure_pythonioencoding(None)
                    result = subprocess.run(
                        ["powershell", "-NoProfile", "-Command", command],
                        cwd=cwd,
                        capture_output=True,
                        text=True,
                        timeout=timeout,
                        encoding="utf-8",
                        errors="replace",
                        stdin=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                        env=ps_env,
                    )
            else:
                # On Unix-like systems, use the default shell
                result = subprocess.run(
                    command,
                    shell=True,
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    encoding="utf-8",
                    errors="replace",
                    stdin=subprocess.DEVNULL,
                    start_new_session=True,
                )

            # Prepare output
            output_parts = []
            if result.stdout:
                output_parts.append(f"STDOUT:\n{result.stdout}")
            if result.stderr:
                output_parts.append(f"STDERR:\n{result.stderr}")

            output = "\n\n".join(output_parts) if output_parts else "(no output)"

            # Audit log the execution
            logger.info(
                f"[COMMAND_AUDIT] Executed: {command[:200]}, exit_code={result.returncode}, timeout={timeout}s"
            )

            # Determine success based on exit code
            if result.returncode == 0:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.SUCCESS,
                    output=output,
                    metadata={
                        "command": command,
                        "exit_code": result.returncode,
                        "working_directory": cwd or "current",
                        "has_stdout": bool(result.stdout),
                        "has_stderr": bool(result.stderr),
                    },
                )
            else:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=output,
                    error=f"Command failed with exit code {result.returncode}",
                    metadata={
                        "command": command,
                        "exit_code": result.returncode,
                        "working_directory": cwd or "current",
                    },
                )

        except subprocess.TimeoutExpired as e:
            # subprocess.run() kills the process and collects buffered output.
            # e.stdout/e.stderr may be str (text=True) or bytes (on some platforms),
            # or None/empty if PowerShell hadn't flushed its buffers before kill.
            output_parts = []
            stdout = e.stdout
            stderr = e.stderr
            # Handle bytes (can happen on some platforms despite text=True)
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", errors="replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", errors="replace")
            if stdout:
                output_parts.append(f"STDOUT:\n{stdout}")
            if stderr:
                output_parts.append(f"STDERR:\n{stderr}")
            partial_output = (
                "\n\n".join(output_parts)
                if output_parts
                else ("(no output captured - process was killed before producing output)")
            )

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=partial_output,
                error=f"Command timed out after {timeout} seconds. "
                f"Use a longer timeout if the command needs more time (max 600s).",
                metadata={
                    "command": command,
                    "timeout": timeout,
                    "working_directory": cwd or "current",
                    "partial_output": bool(output_parts),
                },
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to execute command: {str(e)}",
            )
