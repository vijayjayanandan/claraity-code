"""
Prioritized Summarizer for Conversation Compaction

Generates rich continuation summaries with priority-based content inclusion.
Preserves what matters most for LLM continuation quality.

Priority Order:
1. Goal and key decisions (always include)
2. ALL user messages (they're short, preserve completely)
3. Code snippets (critical for coding agent)
4. Errors and fixes (prevent repeating mistakes)
5. Files modified (context)
6. Current state (where we are now)

Features:
- LLM-first summarization with deterministic fallback
- Soft token budget (quality over strict limits)
- Extracts code blocks, errors, file paths automatically
"""

import re
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable
import tiktoken

from src.observability import get_logger

logger = get_logger(__name__)


# Configuration
SUMMARY_TOKEN_BUDGET = 6000  # Soft cap - quality prioritized

SUMMARY_PRIORITIES = [
    ("goal_and_decisions", 800),       # Priority 1: What we're doing
    ("user_messages", 2000),           # Priority 2: ALL user messages (they're short!)
    ("code_snippets", 1500),           # Priority 3: Actual code
    ("errors_and_fixes", 600),         # Priority 4: Mistakes to avoid
    ("files_modified", 400),           # Priority 5: File context
    ("current_state", 400),            # Priority 6: Where we are now
    ("tool_summary", 300),             # Priority 7: Tools used
]


@dataclass
class SummarySection:
    """
    A section of the generated summary.

    Attributes:
        name: Section identifier (e.g., "goal_and_decisions")
        title: Display title (e.g., "## Goal and Key Decisions")
        content: Section content
        priority: Priority rank (lower = more important)
        token_count: Tokens used by this section
    """
    name: str
    title: str
    content: str
    priority: int
    token_count: int = 0


class PrioritizedSummarizer:
    """
    Generate rich continuation summaries with prioritized content.

    Uses priority-based inclusion to fit within token budget while
    preserving the most important information for continuation.

    Usage:
        summarizer = PrioritizedSummarizer(token_budget=6000)
        summary = summarizer.generate_summary(messages, use_llm=True)
    """

    def __init__(
        self,
        token_budget: int = SUMMARY_TOKEN_BUDGET,
        encoding_name: str = "cl100k_base",
        llm_caller: Optional[Callable[[str], str]] = None
    ):
        """
        Initialize summarizer.

        Args:
            token_budget: Soft token budget for summary
            encoding_name: Tokenizer encoding name
            llm_caller: Optional function to call LLM for summarization
                       Signature: (prompt: str) -> str
        """
        self.token_budget = token_budget
        self.encoding = tiktoken.get_encoding(encoding_name)
        self.llm_caller = llm_caller

    def count_tokens(self, text: str) -> int:
        """Count tokens in text."""
        if not text:
            return 0
        return len(self.encoding.encode(text))

    def generate_summary(
        self,
        messages: List[Dict[str, Any]],
        use_llm: bool = True
    ) -> str:
        """
        Generate prioritized summary from messages.

        Args:
            messages: Messages to summarize (evicted from working memory)
            use_llm: Whether to try LLM summarization first

        Returns:
            Rich continuation summary in markdown format
        """
        if not messages:
            return "No prior context available."

        # Try LLM summarization first if enabled and available
        if use_llm and self.llm_caller:
            try:
                llm_summary = self._generate_llm_summary(messages)
                if llm_summary and self.count_tokens(llm_summary) <= self.token_budget * 1.2:
                    return llm_summary
                logger.warning("LLM summary exceeded budget, using fallback")
            except Exception as e:
                logger.warning(f"LLM summarization failed: {e}, using fallback")

        # Fallback to deterministic summarization
        return self._generate_deterministic_summary(messages)

    def _generate_llm_summary(self, messages: List[Dict[str, Any]]) -> str:
        """
        Use LLM to generate high-quality summary.

        Args:
            messages: Messages to summarize

        Returns:
            LLM-generated summary
        """
        if not self.llm_caller:
            raise ValueError("LLM caller not configured")

        formatted_messages = self._format_messages_for_llm(messages)

        prompt = f"""Analyze this conversation history and create a continuation summary for an AI coding agent.

CONVERSATION HISTORY:
{formatted_messages}

Generate a summary with these sections IN ORDER OF IMPORTANCE:

## Goal and Key Decisions
What is the user trying to accomplish? What important decisions were made?
Be specific about technical choices.

## All User Messages
Include ALL user messages in chronological order. These are critical for understanding intent.
Format: numbered list with full text of each message.

## Code Snippets
Include actual code that was written or discussed. For a coding agent, this is essential.
Format as markdown code blocks with language annotation.

## Errors and Fixes
What went wrong and how was it fixed? This prevents repeating mistakes.
Be specific about the error and the solution.

## Files Modified
Which files were created/modified and why?

## Current State
What was just completed? What's the logical next step?

IMPORTANT GUIDELINES:
- Preserve user messages VERBATIM - they are the ground truth of intent
- Include actual code snippets, not just "modified file.py"
- Be specific about errors and their fixes
- Keep the summary focused and actionable
- Target approximately {self.token_budget} tokens

Output the summary in clean markdown format."""

        return self.llm_caller(prompt)

    def _generate_deterministic_summary(self, messages: List[Dict[str, Any]]) -> str:
        """
        Fallback deterministic summarizer - always works, never fails.

        Args:
            messages: Messages to summarize

        Returns:
            Deterministic summary
        """
        sections: List[SummarySection] = []
        remaining_budget = self.token_budget

        # Priority 1: Goal and decisions
        goal_section = self._extract_goal_section(messages)
        if goal_section:
            sections.append(goal_section)
            remaining_budget -= goal_section.token_count

        # Priority 2: ALL user messages (critical!)
        user_section = self._extract_user_messages_section(messages, remaining_budget)
        if user_section:
            sections.append(user_section)
            remaining_budget -= user_section.token_count

        # Priority 3: Code snippets
        code_section = self._extract_code_section(messages, remaining_budget)
        if code_section and remaining_budget > 0:
            sections.append(code_section)
            remaining_budget -= code_section.token_count

        # Priority 4: Errors and fixes
        error_section = self._extract_error_section(messages, remaining_budget)
        if error_section and remaining_budget > 0:
            sections.append(error_section)
            remaining_budget -= error_section.token_count

        # Priority 5: Files modified
        files_section = self._extract_files_section(messages, remaining_budget)
        if files_section and remaining_budget > 0:
            sections.append(files_section)
            remaining_budget -= files_section.token_count

        # Priority 6: Current state
        state_section = self._extract_current_state_section(messages, remaining_budget)
        if state_section and remaining_budget > 0:
            sections.append(state_section)
            remaining_budget -= state_section.token_count

        # Priority 7: Tool summary
        tool_section = self._extract_tool_summary_section(messages, remaining_budget)
        if tool_section and remaining_budget > 0:
            sections.append(tool_section)

        # Combine sections
        summary_parts = [s.content for s in sections if s.content]
        return "\n\n".join(summary_parts) if summary_parts else "Conversation history compacted."

    # ==================== Section Extractors ====================

    def _extract_goal_section(self, messages: List[Dict[str, Any]]) -> Optional[SummarySection]:
        """Extract goal and key decisions."""
        # Find first user message as initial goal
        goal = None
        for msg in messages:
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if content:
                    goal = content[:300] + "..." if len(content) > 300 else content
                    break

        if not goal:
            return None

        # Extract decisions from assistant messages
        decisions = []
        decision_patterns = [
            r"(?:I'll|I will|Let's|We should|I'm going to)\s+(.+?)(?:\.|$)",
            r"(?:decided to|choosing|using)\s+(.+?)(?:\.|$)",
        ]

        for msg in messages:
            if msg.get("role") == "assistant":
                content = msg.get("content", "")
                for pattern in decision_patterns:
                    matches = re.findall(pattern, content, re.IGNORECASE)
                    decisions.extend(matches[:2])  # Limit per message

        # Build section
        content = f"## Goal and Key Decisions\n\n**Goal:** {goal}"
        if decisions:
            unique_decisions = list(dict.fromkeys(decisions))[:5]  # Dedupe, limit to 5
            content += "\n\n**Key Decisions:**\n"
            for d in unique_decisions:
                content += f"- {d.strip()[:150]}\n"

        return SummarySection(
            name="goal_and_decisions",
            title="## Goal and Key Decisions",
            content=content,
            priority=1,
            token_count=self.count_tokens(content)
        )

    def _extract_user_messages_section(
        self,
        messages: List[Dict[str, Any]],
        budget: int
    ) -> Optional[SummarySection]:
        """Extract ALL user messages."""
        user_messages = []
        for msg in messages:
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if content:
                    user_messages.append(content)

        if not user_messages:
            return None

        # Build section with all messages
        content = "## All User Messages\n\n"
        for i, msg in enumerate(user_messages, 1):
            content += f"{i}. \"{msg}\"\n\n"

        token_count = self.count_tokens(content)

        # If over budget, truncate individual messages but keep ALL
        if token_count > budget:
            content = "## All User Messages\n\n"
            for i, msg in enumerate(user_messages, 1):
                truncated = msg[:200] + "..." if len(msg) > 200 else msg
                content += f"{i}. \"{truncated}\"\n\n"
            token_count = self.count_tokens(content)

        return SummarySection(
            name="user_messages",
            title="## All User Messages",
            content=content.strip(),
            priority=2,
            token_count=token_count
        )

    def _extract_code_section(
        self,
        messages: List[Dict[str, Any]],
        budget: int
    ) -> Optional[SummarySection]:
        """Extract code snippets from messages."""
        code_blocks = []

        # Pattern for markdown code blocks
        code_pattern = re.compile(r'```(\w*)\n(.*?)```', re.DOTALL)

        for msg in messages:
            content = msg.get("content", "")
            matches = code_pattern.findall(content)
            for lang, code in matches:
                if len(code.strip()) > 20:  # Ignore trivial snippets
                    code_blocks.append((lang or "python", code.strip()))

        if not code_blocks:
            return None

        # Build section with top code blocks
        content = "## Code Snippets\n\n"
        current_tokens = self.count_tokens(content)

        for lang, code in code_blocks[:5]:  # Limit to 5 snippets
            # Truncate long code blocks
            if len(code) > 500:
                code = code[:500] + "\n# ... truncated ..."

            snippet = f"```{lang}\n{code}\n```\n\n"
            snippet_tokens = self.count_tokens(snippet)

            if current_tokens + snippet_tokens > budget:
                break

            content += snippet
            current_tokens += snippet_tokens

        return SummarySection(
            name="code_snippets",
            title="## Code Snippets",
            content=content.strip(),
            priority=3,
            token_count=current_tokens
        )

    def _extract_error_section(
        self,
        messages: List[Dict[str, Any]],
        budget: int
    ) -> Optional[SummarySection]:
        """Extract error mentions and fixes."""
        errors = []
        error_keywords = ["error", "failed", "wrong", "incorrect", "bug", "fix", "issue", "problem"]

        for msg in messages:
            content = msg.get("content", "")
            content_lower = content.lower()

            if any(kw in content_lower for kw in error_keywords):
                # Extract relevant sentences
                sentences = re.split(r'(?<=[.!?])\s+', content)
                for sentence in sentences:
                    if any(kw in sentence.lower() for kw in error_keywords):
                        errors.append(sentence[:250])
                        if len(errors) >= 5:
                            break
            if len(errors) >= 5:
                break

        if not errors:
            return None

        content = "## Errors and Fixes\n\n"
        for error in errors:
            content += f"- {error}\n"

        return SummarySection(
            name="errors_and_fixes",
            title="## Errors and Fixes",
            content=content.strip(),
            priority=4,
            token_count=self.count_tokens(content)
        )

    def _extract_files_section(
        self,
        messages: List[Dict[str, Any]],
        budget: int
    ) -> Optional[SummarySection]:
        """Extract file paths mentioned."""
        files = set()

        # Patterns for file paths
        file_patterns = [
            r'`([a-zA-Z0-9_/\\.-]+\.[a-zA-Z]{1,4})`',  # `file.py`
            r'"([a-zA-Z0-9_/\\.-]+\.[a-zA-Z]{1,4})"',  # "file.py"
            r"'([a-zA-Z0-9_/\\.-]+\.[a-zA-Z]{1,4})'",  # 'file.py'
            r'(?:src|tests|lib|app)/[a-zA-Z0-9_/\\.-]+\.[a-zA-Z]{1,4}',  # src/file.py
        ]

        for msg in messages:
            content = msg.get("content", "")
            for pattern in file_patterns:
                matches = re.findall(pattern, content)
                if isinstance(matches, list) and matches:
                    if isinstance(matches[0], tuple):
                        files.update(m[0] for m in matches)
                    else:
                        files.update(matches)

            # Check tool calls for file operations
            tool_calls = msg.get("tool_calls", [])
            for tc in tool_calls:
                func = tc.get("function", {})
                args_str = func.get("arguments", "{}")
                try:
                    if isinstance(args_str, str):
                        import json
                        args = json.loads(args_str)
                    else:
                        args = args_str
                    if isinstance(args, dict):
                        if "file_path" in args:
                            files.add(args["file_path"])
                        if "path" in args:
                            files.add(args["path"])
                except (json.JSONDecodeError, TypeError):
                    pass

        if not files:
            return None

        # Filter out non-file strings
        valid_files = [f for f in files if '.' in f and len(f) > 3][:15]

        if not valid_files:
            return None

        content = "## Files Modified\n\n"
        for f in sorted(valid_files):
            content += f"- `{f}`\n"

        return SummarySection(
            name="files_modified",
            title="## Files Modified",
            content=content.strip(),
            priority=5,
            token_count=self.count_tokens(content)
        )

    def _extract_current_state_section(
        self,
        messages: List[Dict[str, Any]],
        budget: int
    ) -> Optional[SummarySection]:
        """Extract current state from recent messages."""
        # Get last assistant message
        last_assistant = None
        for msg in reversed(messages):
            if msg.get("role") == "assistant":
                last_assistant = msg.get("content", "")
                break

        if not last_assistant:
            return None

        # Truncate if needed
        if len(last_assistant) > 400:
            last_assistant = "..." + last_assistant[-400:]

        content = f"## Current State\n\n{last_assistant}"

        return SummarySection(
            name="current_state",
            title="## Current State",
            content=content,
            priority=6,
            token_count=self.count_tokens(content)
        )

    def _extract_tool_summary_section(
        self,
        messages: List[Dict[str, Any]],
        budget: int
    ) -> Optional[SummarySection]:
        """Extract summary of tools used."""
        tool_counts: Dict[str, int] = {}

        for msg in messages:
            tool_calls = msg.get("tool_calls", [])
            for tc in tool_calls:
                func = tc.get("function", {})
                name = func.get("name", tc.get("name", "unknown"))
                tool_counts[name] = tool_counts.get(name, 0) + 1

        if not tool_counts:
            return None

        # Sort by count
        sorted_tools = sorted(tool_counts.items(), key=lambda x: x[1], reverse=True)

        content = "## Tools Used\n\n"
        for tool, count in sorted_tools[:10]:
            content += f"- {tool}: {count}x\n"

        return SummarySection(
            name="tool_summary",
            title="## Tools Used",
            content=content.strip(),
            priority=7,
            token_count=self.count_tokens(content)
        )

    # ==================== Helpers ====================

    def _format_messages_for_llm(self, messages: List[Dict[str, Any]]) -> str:
        """Format messages for LLM prompt."""
        formatted = []
        for i, msg in enumerate(messages):
            role = msg.get("role", "unknown").upper()
            content = msg.get("content", "")

            # Truncate very long content
            if len(content) > 1000:
                content = content[:500] + "\n...[truncated]...\n" + content[-300:]

            formatted.append(f"[{i+1}] {role}: {content}")

            # Include tool calls info
            tool_calls = msg.get("tool_calls", [])
            if tool_calls:
                tool_names = [tc.get("function", {}).get("name", "unknown") for tc in tool_calls]
                formatted.append(f"    [Tools called: {', '.join(tool_names)}]")

        return "\n\n".join(formatted)

    def get_section_stats(self, summary: str) -> Dict[str, Any]:
        """
        Get statistics about a generated summary.

        Args:
            summary: Generated summary

        Returns:
            Dict with token count, section counts, etc.
        """
        sections_found = []
        section_headers = [
            "Goal and Key Decisions",
            "All User Messages",
            "Code Snippets",
            "Errors and Fixes",
            "Files Modified",
            "Current State",
            "Tools Used"
        ]

        for header in section_headers:
            if header in summary:
                sections_found.append(header)

        return {
            "total_tokens": self.count_tokens(summary),
            "sections_included": sections_found,
            "section_count": len(sections_found),
            "char_count": len(summary)
        }
