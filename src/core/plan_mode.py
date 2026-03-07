"""
Plan Mode - Claude Code-style planning workflow.

This module implements a plan-then-execute workflow:
1. Enter plan mode -> creates plan file
2. Read-only restriction -> only read tools + writing to plan file allowed
3. Exit plan mode -> compute hash, await approval
4. After approval -> full tools available

Design Principles:
- Store-driven lifecycle (events persisted via MessageStore)
- Single writer rule (UI never writes directly)
- Bounded excerpt injection (avoid context bloat)
"""

from pathlib import Path
from datetime import datetime
from hashlib import sha256
from enum import Enum
from typing import Optional, Dict, Any
import uuid
import os

from src.observability import get_logger

logger = get_logger(__name__)

# Try to import capability metadata; fall back to frozenset if unavailable
try:
    from src.tools.tool_schemas import TOOL_CAPABILITIES as _TOOL_CAPS
except ImportError:
    _TOOL_CAPS = None


def _is_read_only(tool_name: str) -> bool:
    """Check if a tool is read-only using capability metadata with fallback."""
    if _TOOL_CAPS is not None:
        caps = _TOOL_CAPS.get(tool_name)
        if caps is not None:
            return "read_only" in caps
    # Fallback to static frozenset
    return tool_name in READ_ONLY_TOOLS


class PlanGateDecision(Enum):
    """Decision from tool gating in plan mode."""
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


# Read-only tools that are always allowed in plan mode
READ_ONLY_TOOLS = frozenset({
    # File reading
    "read_file",
    "list_directory",

    # Search tools
    "search_code",
    "grep",
    "glob",

    # Analysis tools (read-only)
    "analyze_code",
    "get_file_outline",
    "get_symbol_context",

    # Web tools (read-only)
    "web_fetch",
    "web_search",

    # Task/todo tools (read-only queries)
    "get_todos",
    "get_next_task",

    # Architecture query tools (read-only)
    "query_component",
    "query_dependencies",
    "query_decisions",
    "query_flows",
    "query_architecture_summary",
    "search_components",
    "get_implementation_spec",

    # Git read-only
    "git_status",
    "git_diff",
})

# Plan mode control tools
PLAN_MODE_TOOLS = frozenset({
    "enter_plan_mode",
    "request_plan_approval",
})

# Agent workspace directory — files under this path are agent-internal
# (plan files, session logs, metrics) and bypass approval in all modes.
AGENT_WORKSPACE_DIR = ".clarity"


def is_agent_internal_write(tool_name: str, tool_args: Dict[str, Any]) -> bool:
    """
    Check if a tool call is an agent-internal file operation.

    Writes targeting .clarity/ (plan files, sessions, logs) are internal
    to the agent's operation -- like MemoryManager writing session JSONL.
    These bypass approval in all permission modes.

    SECURITY: Uses resolved paths to prevent path traversal bypass.
    Only allows writes to safe subdirectories (sessions, plans, logs).
    Config files (.clarity/config.yaml) always require approval.

    Args:
        tool_name: Name of the tool being called
        tool_args: Tool arguments dict (expects file_path or path key)

    Returns:
        True if this is an agent-internal write that should bypass approval
    """
    if tool_name not in ("write_file", "edit_file", "append_to_file"):
        return False

    target = tool_args.get("file_path") or tool_args.get("path") or ""
    if not target:
        return False

    try:
        # Resolve to absolute path to prevent traversal tricks
        resolved = Path(target).resolve()
        clarity_dir = (Path.cwd() / AGENT_WORKSPACE_DIR).resolve()

        # Must be under .clarity/ directory
        if not resolved.is_relative_to(clarity_dir):
            return False

        # Only allow writes to safe subdirectories (not config.yaml)
        relative = resolved.relative_to(clarity_dir)
        SAFE_SUBDIRS = {"sessions", "plans", "logs", "transcripts"}
        first_part = relative.parts[0] if relative.parts else ""
        return first_part in SAFE_SUBDIRS
    except (ValueError, OSError):
        return False


class PlanModeState:
    """
    Manages plan mode lifecycle and tool gating.

    Usage:
        plan_state = PlanModeState()

        # Enter plan mode
        result = plan_state.enter(session_id)
        # result = {"plan_path": ".clarity/plans/<session_id>.md"}

        # Check if tool is allowed
        decision = plan_state.gate_tool("write_file", "/some/path.py")
        # decision = PlanGateDecision.DENY (unless writing to plan file)

        # Exit for approval
        result = plan_state.exit_for_approval()
        # result = {"plan_hash": "abc123...", "excerpt": "...", "truncated": False}

        # Approve
        plan_state.approve(plan_hash)
    """

    def __init__(self, clarity_dir: Path = Path(".clarity")):
        """
        Initialize plan mode state.

        Args:
            clarity_dir: Base directory for clarity data (default: .clarity)
        """
        self.clarity_dir = clarity_dir
        self.plans_dir = clarity_dir / "plans"

        # Current state
        self.is_active = False
        self._awaiting_approval = False
        self.plan_file_path: Optional[Path] = None
        self.session_id: Optional[str] = None

        # Hash tracking for approval
        self.plan_hash: Optional[str] = None
        self.approved_hash: Optional[str] = None

        # Clear context flag (stubbed for Phase 2)
        self.clear_context_on_exit = False

    def enter(self, session_id: str) -> Dict[str, Any]:
        """
        Enter plan mode and create plan file.

        Args:
            session_id: Current session ID (used for plan file name)

        Returns:
            Dict with plan_path and status
        """
        # Create plans directory if needed
        self.plans_dir.mkdir(parents=True, exist_ok=True)

        self.session_id = session_id
        self.plan_file_path = self.plans_dir / f"{session_id}.md"

        # Create template if file doesn't exist
        if not self.plan_file_path.exists():
            template = self._get_plan_template(session_id)
            self.plan_file_path.write_text(template, encoding="utf-8")

        self.is_active = True
        self.plan_hash = None
        self.approved_hash = None

        return {
            "status": "entered",
            "plan_path": str(self.plan_file_path),
        }

    def exit_for_approval(self) -> Dict[str, Any]:
        """
        Exit plan mode and prepare for approval.

        Computes hash of plan content for approval verification.
        Returns truncated excerpt to avoid context bloat.

        Returns:
            Dict with plan_hash, excerpt, truncated flag, or error
        """
        if not self.is_active or not self.plan_file_path:
            return {"error": "Not in plan mode"}

        if not self.plan_file_path.exists():
            return {"error": f"Plan file not found: {self.plan_file_path}"}

        try:
            content = self.plan_file_path.read_text(encoding="utf-8")
        except Exception as e:
            return {"error": f"Failed to read plan file: {e}"}

        # Compute full SHA256 hash
        self.plan_hash = sha256(content.encode()).hexdigest()
        self.is_active = False
        self._awaiting_approval = True

        # Truncate for context injection (8000 chars max)
        max_excerpt_len = 8000
        truncated = len(content) > max_excerpt_len
        excerpt = content[:max_excerpt_len] + ("..." if truncated else "")

        return {
            "status": "awaiting_approval",
            "plan_hash": self.plan_hash,
            "excerpt": excerpt,
            "truncated": truncated,
            "plan_path": str(self.plan_file_path),
        }

    def approve(self, plan_hash: str) -> bool:
        """
        Approve plan with given hash.

        Args:
            plan_hash: Hash to verify matches current plan

        Returns:
            True if approved (hash matches), False otherwise
        """
        if plan_hash == self.plan_hash:
            self.approved_hash = plan_hash
            self.is_active = False
            self._awaiting_approval = False
            return True
        return False

    def reject(self) -> None:
        """
        Reject plan. Return to plan mode for revisions.

        The plan file remains, and the agent can continue editing it.
        Resets hash state so the agent must re-submit for approval.
        """
        self.plan_hash = None
        self._awaiting_approval = False
        self.is_active = True

    def gate_tool(
        self,
        tool_name: str,
        target_path: Optional[str] = None
    ) -> PlanGateDecision:
        """
        Check if tool is allowed in current plan mode state.

        Args:
            tool_name: Name of the tool being called
            target_path: Target file path for write operations (optional)

        Returns:
            PlanGateDecision indicating whether tool is allowed
        """
        # Awaiting approval - mutation tools require approval, read-only allowed
        if self._awaiting_approval:
            if _is_read_only(tool_name) or tool_name in PLAN_MODE_TOOLS:
                return PlanGateDecision.ALLOW
            return PlanGateDecision.REQUIRE_APPROVAL

        # Not in plan mode - all tools allowed
        if not self.is_active:
            return PlanGateDecision.ALLOW

        # Plan mode control tools always allowed
        if tool_name in PLAN_MODE_TOOLS:
            return PlanGateDecision.ALLOW

        # Read-only tools always allowed
        if _is_read_only(tool_name):
            return PlanGateDecision.ALLOW

        # Write to plan file is allowed
        if tool_name in ("write_file", "edit_file", "append_to_file") and target_path:
            try:
                target = Path(target_path).resolve()
                plan_path = self.plan_file_path.resolve() if self.plan_file_path else None
                if plan_path:
                    # Use os.path.samefile for robust comparison (handles symlinks, case sensitivity)
                    # This requires both files to exist, so also check path equality as fallback
                    try:
                        if os.path.samefile(target, plan_path):
                            return PlanGateDecision.ALLOW
                    except (OSError, FileNotFoundError):
                        # Files may not exist yet, fall back to normalized path comparison
                        # Normalize for case-insensitive comparison on Windows
                        if os.name == 'nt':
                            if str(target).lower() == str(plan_path).lower():
                                return PlanGateDecision.ALLOW
                        elif target == plan_path:
                            return PlanGateDecision.ALLOW
            except Exception as e:
                logger.debug(f"Path resolution failed for {target_path}: {e}")
                pass  # Path resolution failed - deny

        # All other tools denied in plan mode
        return PlanGateDecision.DENY

    def _get_plan_template(self, session_id: str) -> str:
        """Generate initial plan file template."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return f"""# Plan: {session_id}

Created: {timestamp}

## Summary

[Brief description of what this plan accomplishes]

## Context

[Key files, components, or concepts involved]

## Implementation Steps

1. [ ] Step 1
2. [ ] Step 2
3. [ ] Step 3

## Verification

- [ ] Tests pass
- [ ] Code review complete
- [ ] No regressions

## Notes

[Any additional context, alternatives considered, or trade-offs]
"""

    def get_plan_content(self) -> Optional[str]:
        """
        Get current plan file content.

        Returns:
            Plan content if file exists, None otherwise
        """
        if self.plan_file_path and self.plan_file_path.exists():
            try:
                return self.plan_file_path.read_text(encoding="utf-8")
            except Exception as e:
                logger.warning(f"Failed to read plan file {self.plan_file_path}: {e}")
                return None
        return None

    def is_awaiting_approval(self) -> bool:
        """Check if plan is awaiting user approval."""
        return self._awaiting_approval

    def reset(self) -> None:
        """Reset plan mode state (for new sessions)."""
        self.is_active = False
        self._awaiting_approval = False
        self.plan_file_path = None
        self.session_id = None
        self.plan_hash = None
        self.approved_hash = None
        self.clear_context_on_exit = False


# Export all types
__all__ = [
    'PlanGateDecision',
    'PlanModeState',
    'READ_ONLY_TOOLS',
    'PLAN_MODE_TOOLS',
]
