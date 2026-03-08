"""Shared metadata builder for update_tool_state() calls.

Both agent.py and subagent.py emit tool state updates to the MessageStore.
The VS Code serializer (serializers.py) expects specific keys in the metadata
dict — especially "arguments" for file path display in tool cards.

Using this shared builder prevents the two paths from diverging.

PARITY RULE: If you add a new key here, both agent.py and subagent.py
will automatically pick it up. If you need a key only in one path,
pass it via **extra.
"""

from typing import Any, Dict, Optional


def build_tool_metadata(
    tool_name: str,
    tool_args: Dict[str, Any],
    args_summary: str = "",
    requires_approval: bool = False,
    **extra: Any,
) -> Dict[str, Any]:
    """Build a standard extra_metadata dict for MessageStore.update_tool_state().

    Args:
        tool_name: Canonical tool name (e.g. "read_file", "write_file")
        tool_args: Full arguments dict — serialized to VS Code for file path display
        args_summary: Short human-readable summary (used by TUI SubAgentCard)
        requires_approval: Whether the tool call needs user approval
        **extra: Additional keys merged into the dict

    Returns:
        Dict suitable for the ``extra_metadata`` parameter of ``update_tool_state()``.
        Always contains "arguments" so the serializer can extract file paths.
    """
    metadata: Dict[str, Any] = {
        "arguments": tool_args,
        "args_summary": args_summary,
        "requires_approval": requires_approval,
    }
    metadata.update(extra)
    return metadata
