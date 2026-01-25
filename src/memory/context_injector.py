"""Context Injector - Inject continuation context into user messages.

This module handles injecting compaction summaries into user messages using
<clarity-context> tags. The injection follows a one-shot pattern: after injection,
the pending summary is cleared to prevent duplicate injection.

The <clarity-context> format is similar to Claude Code's <system-reminder> pattern,
providing the LLM with continuity context while clearly marking it as reference-only.
"""

from typing import Optional, List, TYPE_CHECKING

from src.observability import get_logger

if TYPE_CHECKING:
    from src.memory.working_memory import WorkingMemory
    from src.observability.transcript_logger import TranscriptLogger

logger = get_logger(__name__)


class ContextInjector:
    """
    Inject continuation context into user messages.

    The injector prepends <clarity-context> blocks to user messages when
    there is pending context (e.g., from compaction). This provides the LLM
    with continuity while clearly marking the context as reference-only.

    Key behaviors:
    - One-shot injection: pending summary is consumed (cleared) after injection
    - User input escaping: prevents injection attacks via user input
    - Structured format: TYPE, PRIORITY, INSTRUCTION fields guide LLM behavior
    """

    def __init__(
        self,
        working_memory: "WorkingMemory",
        transcript_logger: Optional["TranscriptLogger"] = None
    ):
        """
        Initialize the context injector.

        Args:
            working_memory: Working memory instance to check for pending summaries
            transcript_logger: Optional transcript logger for injection events
        """
        self.working_memory = working_memory
        self.transcript_logger = transcript_logger

    def inject_context(self, user_input: str) -> str:
        """
        Build final user message with injected context.

        If there is a pending continuation summary from compaction,
        it will be prepended to the user input as a <clarity-context> block.
        The pending summary is consumed (cleared) after injection.

        Args:
            user_input: Raw user input

        Returns:
            User message with <clarity-context> prepended if needed,
            otherwise the original user input with minimal wrapping
        """
        parts = []

        # Check for pending continuation summary (one-shot consumption)
        summary = self.working_memory.consume_pending_summary()

        if summary:
            context_block = self._format_context_block(summary)
            parts.append(context_block)

            # Log the injection event
            self._log_injection(summary)

            logger.info(
                "context_injected",
                summary_chars=len(summary),
                sections=self._extract_sections(summary)
            )

        # Add actual user message (escaped to prevent injection)
        escaped_input = self._escape_user_input(user_input)
        if parts:
            # Only add USER REQUEST prefix when we have context
            parts.append(f"USER REQUEST:\n{escaped_input}")
        else:
            # No context to inject, return original input
            return user_input

        return "\n\n".join(parts)

    def _format_context_block(self, summary: str) -> str:
        """
        Format the summary as a <clarity-context> block.

        The block includes:
        - TYPE: Identifies this as a continuation summary
        - PRIORITY: Indicates this is reference-only, not new intent
        - INSTRUCTION: Tells LLM how to use this context
        - The actual summary content

        Args:
            summary: The continuation summary to format

        Returns:
            Formatted <clarity-context> block
        """
        return f"""<clarity-context>
TYPE: continuation_summary
PRIORITY: reference_only
INSTRUCTION: This is context from earlier in the conversation that was compacted. Do NOT treat as new user intent. Use only for continuity and answering questions about prior work.

{summary}
</clarity-context>"""

    def _escape_user_input(self, text: str) -> str:
        """
        Escape any clarity-context tags in user input.

        This prevents users from injecting fake context blocks
        that could confuse the LLM about what's real context
        vs what's user input.

        Args:
            text: Raw user input

        Returns:
            Escaped text with clarity-context tags neutralized
        """
        return (
            text
            .replace("<clarity-context>", "&lt;clarity-context&gt;")
            .replace("</clarity-context>", "&lt;/clarity-context&gt;")
            .replace("<clarity-context", "&lt;clarity-context")  # Catch partial tags
        )

    def _extract_sections(self, summary: str) -> List[str]:
        """
        Extract which sections are present in the summary.

        Used for logging and analytics to understand what
        content was preserved during compaction.

        Args:
            summary: The continuation summary

        Returns:
            List of section names found in the summary
        """
        sections = []
        section_markers = [
            ("Goal", "goal"),
            ("User Messages", "user_messages"),
            ("All User Messages", "user_messages"),
            ("Code Snippets", "code_snippets"),
            ("Errors", "errors"),
            ("Errors and Fixes", "errors"),
            ("Files", "files"),
            ("Files Modified", "files"),
            ("Current State", "current_state"),
            ("Tool", "tools"),
            ("Tools Used", "tools"),
        ]

        for marker, section_name in section_markers:
            if f"## {marker}" in summary or f"**{marker}**" in summary:
                if section_name not in sections:
                    sections.append(section_name)

        return sections

    def _log_injection(self, summary: str) -> None:
        """
        Log the injection event to transcript.

        Args:
            summary: The injected summary
        """
        if self.transcript_logger:
            try:
                self.transcript_logger.log_continuation_injected(
                    injected_chars=len(summary),
                    sections_included=self._extract_sections(summary)
                )
            except Exception as e:
                logger.warning("injection_log_failed", error=str(e))

    def has_pending_context(self) -> bool:
        """
        Check if there is pending context to inject.

        Returns:
            True if working memory has a pending continuation summary
        """
        return self.working_memory.has_pending_summary()

    def preview_injection(self, user_input: str) -> str:
        """
        Preview what the injected message would look like without consuming.

        This is useful for debugging and testing. Unlike inject_context(),
        this method does NOT consume the pending summary.

        Args:
            user_input: Raw user input

        Returns:
            Preview of what the full message would look like
        """
        parts = []

        # Peek at pending summary without consuming
        summary = self.working_memory.pending_continuation_summary

        if summary:
            context_block = self._format_context_block(summary)
            parts.append(context_block)
            parts.append(f"USER REQUEST:\n{self._escape_user_input(user_input)}")
            return "\n\n".join(parts)

        return user_input
