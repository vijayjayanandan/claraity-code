"""Permission mode management for tool execution gating."""

from enum import Enum


class PermissionMode(Enum):
    """Controls whether the agent asks for user approval before executing tools."""
    NORMAL = "normal"   # Asks approval for risky tools
    AUTO = "auto"       # No approval needed
    PLAN = "plan"       # Read-only, write tools gated


class PermissionManager:
    """
    In-memory permission mode state.

    The source of truth is MessageStore (via permission_mode_changed events).
    This class is the fast in-memory cache that the tool execution loop checks
    on every tool call. Synced from store at the start of each turn by
    CodingAgent._sync_mode_from_store().
    """

    MODE_DESCRIPTIONS = {
        PermissionMode.NORMAL: "Normal - asks approval for risky operations (write, edit, run)",
        PermissionMode.AUTO: "Auto - executes all tools without asking",
        PermissionMode.PLAN: "Plan - read-only mode, write operations are blocked",
    }

    def __init__(self, mode: PermissionMode = PermissionMode.NORMAL):
        self.mode = mode

    def get_mode(self) -> PermissionMode:
        return self.mode

    def set_mode(self, mode: PermissionMode) -> None:
        self.mode = mode

    def format_mode_description(self) -> str:
        return self.MODE_DESCRIPTIONS.get(self.mode, f"Unknown mode: {self.mode}")

    @staticmethod
    def from_string(mode_str: str) -> PermissionMode:
        """Parse a string into a PermissionMode enum.

        Args:
            mode_str: One of 'normal', 'auto', 'plan' (case-insensitive)

        Returns:
            PermissionMode enum value

        Raises:
            ValueError: If the string doesn't match any mode
        """
        normalized = mode_str.strip().lower()
        for member in PermissionMode:
            if member.value == normalized:
                return member
        valid = ", ".join(m.value for m in PermissionMode)
        raise ValueError(f"Invalid permission mode '{mode_str}'. Valid modes: {valid}")
