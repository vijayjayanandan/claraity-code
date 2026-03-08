"""
Slash command dispatcher for the TUI.

Routes slash commands (e.g. /resume, /config-llm, /connect-jira) to their
handler functions. The actual handler implementations stay on CodingAgentApp
since they need access to Textual widget state.
"""

from typing import Callable, Awaitable, Optional

from src.observability import get_logger

logger = get_logger(__name__)


class SlashCommandDispatcher:
    """Routes slash commands to their async handlers.

    Each command maps to an async callable. The dispatcher handles case
    normalization and prefix matching for commands with arguments
    (e.g. "/connect-jira corporate").

    Usage:
        dispatcher = SlashCommandDispatcher({
            "/resume": show_session_picker,
            "/config-llm": configure_llm,
        })
        handled = await dispatcher.dispatch("/resume")
    """

    def __init__(
        self,
        commands: dict[str, Callable[..., Awaitable[None]]],
        prefix_commands: Optional[dict[str, Callable[..., Awaitable[None]]]] = None,
    ):
        """
        Args:
            commands: Map of exact command strings to async handlers.
                      Keys should be lowercase (e.g. "/resume").
            prefix_commands: Map of command prefixes to handlers that accept
                            the full command string (e.g. "/connect-jira" matches
                            "/connect-jira corporate"). Handler receives the
                            original (un-lowered) command string.
        """
        self._commands = commands
        self._prefix_commands = prefix_commands or {}

    async def dispatch(self, command: str) -> bool:
        """
        Route a slash command to its handler.

        Args:
            command: The full command string (e.g. "/resume", "/connect-jira corporate")

        Returns:
            True if command was handled, False if unknown
        """
        cmd = command.lower().strip()

        # Exact match first
        handler = self._commands.get(cmd)
        if handler:
            await handler()
            return True

        # Prefix match (for commands with arguments)
        for prefix, handler in self._prefix_commands.items():
            if cmd == prefix or cmd.startswith(prefix + " "):
                await handler(command)
                return True

        # Unknown command - let it pass through to agent
        return False
