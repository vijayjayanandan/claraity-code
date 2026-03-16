"""Shared metadata builder for update_tool_state() calls.

Both agent.py and subagent.py emit tool state updates to the MessageStore.
The VS Code serializer (serializers.py) expects specific keys in the metadata
dict — especially "arguments" for file path display in tool cards.

Using this shared builder prevents the two paths from diverging.

PARITY RULE: If you add a new key here, both agent.py and subagent.py
will automatically pick it up. If you need a key only in one path,
pass it via **extra.
"""

from pathlib import Path
from typing import Any, Optional

# Tools whose file_path argument should be resolved to absolute for the
# VS Code extension (openDiffEditor needs an absolute path to read the file).
_FILE_PATH_TOOLS = frozenset(
    {
        "read_file",
        "write_file",
        "edit_file",
        "append_to_file",
    }
)


def _resolve_file_path(tool_name: str, tool_args: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy of *tool_args* with file_path resolved to absolute.

    The LLM often provides a relative path (e.g. ``test_demo.txt``).  The
    Python side resolves it via ``validate_path_security()`` during execution,
    but the metadata is built *before* execution.  The VS Code extension's
    ``openDiffEditor()`` calls ``vscode.Uri.file(filePath)`` — which fails on
    relative paths.  Resolving here ensures the extension always gets an
    absolute path it can open.
    """
    if tool_name not in _FILE_PATH_TOOLS:
        return tool_args

    raw_path = tool_args.get("file_path") or tool_args.get("path")
    if not raw_path:
        return tool_args

    # Only resolve genuinely relative paths.  Paths that start with "/" or a
    # Windows drive letter (e.g. "C:\") are already rooted / absolute and
    # should not be touched.  On Windows, Path("/foo").is_absolute() is False
    # (no drive letter) yet resolve() prepends the current drive, which would
    # break cross-platform test assertions — so we also skip leading-slash paths.
    p = Path(raw_path)
    if p.is_absolute() or raw_path.startswith("/"):
        return tool_args

    try:
        resolved = str(p.resolve())
    except (OSError, ValueError):
        return tool_args  # leave as-is on resolution failure

    # Shallow copy so we don't mutate the caller's dict
    patched = dict(tool_args)
    if "file_path" in patched:
        patched["file_path"] = resolved
    elif "path" in patched:
        patched["path"] = resolved
    return patched


def build_tool_metadata(
    tool_name: str,
    tool_args: dict[str, Any],
    args_summary: str = "",
    requires_approval: bool = False,
    **extra: Any,
) -> dict[str, Any]:
    """Build a standard extra_metadata dict for MessageStore.update_tool_state().

    Args:
        tool_name: Canonical tool name (e.g. "read_file", "write_file")
        tool_args: Full arguments dict — serialized to VS Code for file path display
        args_summary: Short human-readable summary (used by TUI SubAgentCard)
        requires_approval: Whether the tool call needs user approval
        **extra: Additional keys merged into the dict

    Returns:
        dict suitable for the ``extra_metadata`` parameter of ``update_tool_state()``.
        Always contains "arguments" so the serializer can extract file paths.
    """
    metadata: dict[str, Any] = {
        "arguments": _resolve_file_path(tool_name, tool_args),
        "args_summary": args_summary,
        "requires_approval": requires_approval,
    }
    metadata.update(extra)
    return metadata
