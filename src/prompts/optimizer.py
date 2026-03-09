"""Prompt optimizer for token efficiency and effectiveness."""

import re
from typing import Any, Optional

import tiktoken


class PromptOptimizer:
    """
    Optimizes prompts for small LLM context windows.
    Implements compression and deduplication techniques.
    """

    def __init__(self, encoding_name: str = "cl100k_base"):
        """
        Initialize prompt optimizer.

        Args:
            encoding_name: Tokenizer encoding name
        """
        self.encoding = tiktoken.get_encoding(encoding_name)

    def count_tokens(self, text: str) -> int:
        """Count tokens in text."""
        return len(self.encoding.encode(text))

    def compress_prompt(
        self,
        prompt: str,
        target_tokens: int | None = None,
        preserve_structure: bool = True,
    ) -> str:
        """
        Compress prompt to fit within token budget.

        Args:
            prompt: Prompt to compress
            target_tokens: Target token count
            preserve_structure: Whether to preserve XML/markdown structure

        Returns:
            Compressed prompt
        """
        if not target_tokens:
            return prompt

        current_tokens = self.count_tokens(prompt)

        if current_tokens <= target_tokens:
            return prompt

        # Calculate compression ratio needed
        ratio = target_tokens / current_tokens

        # Apply compression techniques
        compressed = prompt

        # 1. Remove redundant whitespace
        compressed = self._remove_redundant_whitespace(compressed)

        # 2. Abbreviate common terms (with legend)
        if ratio < 0.8:
            compressed = self._abbreviate_terms(compressed)

        # 3. Compress code blocks
        if ratio < 0.6:
            compressed = self._compress_code_blocks(compressed)

        # 4. Truncate if still too long
        if self.count_tokens(compressed) > target_tokens:
            compressed = self._truncate_to_tokens(compressed, target_tokens, preserve_structure)

        return compressed

    def _remove_redundant_whitespace(self, text: str) -> str:
        """Remove redundant whitespace while preserving structure."""
        # Remove multiple blank lines
        text = re.sub(r'\n{3,}', '\n\n', text)

        # Remove trailing whitespace
        lines = [line.rstrip() for line in text.split('\n')]

        return '\n'.join(lines)

    def _abbreviate_terms(self, text: str) -> str:
        """Abbreviate common programming terms."""
        abbreviations = {
            "function": "fn",
            "parameter": "param",
            "argument": "arg",
            "variable": "var",
            "constant": "const",
            "implementation": "impl",
            "definition": "def",
            "declaration": "decl",
            "initialize": "init",
            "configuration": "config",
            "application": "app",
            "database": "db",
            "repository": "repo",
        }

        # Add legend at the top
        legend_items = [f"{abbr}={full}" for full, abbr in abbreviations.items()]
        legend = f"<abbr>{', '.join(legend_items)}</abbr>\n\n"

        # Apply abbreviations (case-insensitive in code comments)
        for full, abbr in abbreviations.items():
            # Only abbreviate in comments and documentation
            text = re.sub(
                rf'\b{full}\b(?=[^<]*(?:<code>|$))',
                abbr,
                text,
                flags=re.IGNORECASE,
            )

        return legend + text

    def _compress_code_blocks(self, text: str) -> str:
        """Compress code blocks by removing comments and docstrings."""
        # Pattern to find code blocks
        code_pattern = r'```[\w]*\n(.*?)\n```'

        def compress_code(match: re.Match) -> str:
            code = match.group(1)

            # Remove single-line comments
            code = re.sub(r'^\s*#.*$', '', code, flags=re.MULTILINE)
            code = re.sub(r'^\s*//.*$', '', code, flags=re.MULTILINE)

            # Remove docstrings
            code = re.sub(r'""".*?"""', '', code, flags=re.DOTALL)
            code = re.sub(r"'''.*?'''", '', code, flags=re.DOTALL)

            # Remove blank lines
            lines = [line for line in code.split('\n') if line.strip()]

            return f'```\n{chr(10).join(lines)}\n```'

        return re.sub(code_pattern, compress_code, text, flags=re.DOTALL)

    def _truncate_to_tokens(
        self, text: str, max_tokens: int, preserve_structure: bool
    ) -> str:
        """Truncate text to fit within token budget."""
        tokens = self.encoding.encode(text)

        if len(tokens) <= max_tokens:
            return text

        # Truncate tokens
        truncated_tokens = tokens[:max_tokens]
        truncated_text = self.encoding.decode(truncated_tokens)

        if preserve_structure:
            # Try to end at a complete tag or line
            # Find last complete line
            lines = truncated_text.split('\n')
            if len(lines) > 1:
                # Remove potentially incomplete last line
                truncated_text = '\n'.join(lines[:-1])

        return truncated_text + "\n[...]"

    def deduplicate_context(self, context_items: list[str]) -> list[str]:
        """Remove duplicate information from context items."""
        seen = set()
        deduplicated = []

        for item in context_items:
            # Create a simple hash of content
            content_hash = hash(item.strip().lower())

            if content_hash not in seen:
                seen.add(content_hash)
                deduplicated.append(item)

        return deduplicated

    def optimize_for_attention(self, text: str, key_info: list[str]) -> str:
        """
        Optimize text to guide LLM attention.
        Places important info at start and end (primacy/recency effect).

        Args:
            text: Text to optimize
            key_info: list of key information pieces

        Returns:
            Optimized text
        """
        # Add key info at the start
        header = "<key_info>\n" + "\n".join(f"- {info}" for info in key_info) + "\n</key_info>\n\n"

        # Add reminder at the end
        footer = f"\n\n<reminder>Focus on: {', '.join(key_info)}</reminder>"

        return header + text + footer

    def create_compressed_context(
        self,
        system_prompt: str,
        task_description: str,
        code_context: str,
        conversation_history: str,
        max_tokens: int,
    ) -> str:
        """
        Create optimally compressed context from multiple sources.

        Args:
            system_prompt: System prompt
            task_description: Current task
            code_context: Relevant code
            conversation_history: Recent conversation
            max_tokens: Maximum total tokens

        Returns:
            Compressed, optimized context
        """
        # Reserve token budget
        system_tokens = int(max_tokens * 0.2)  # 20% for system
        task_tokens = int(max_tokens * 0.3)  # 30% for task
        code_tokens = int(max_tokens * 0.35)  # 35% for code
        history_tokens = int(max_tokens * 0.15)  # 15% for history

        # Compress each section
        compressed_system = self.compress_prompt(
            system_prompt, system_tokens, preserve_structure=True
        )

        compressed_task = self.compress_prompt(
            task_description, task_tokens, preserve_structure=True
        )

        compressed_code = self.compress_prompt(
            code_context, code_tokens, preserve_structure=True
        )

        compressed_history = self.compress_prompt(
            conversation_history, history_tokens, preserve_structure=False
        )

        # Combine
        context = f"""{compressed_system}

<task>
{compressed_task}
</task>

<code_context>
{compressed_code}
</code_context>

<history>
{compressed_history}
</history>"""

        return context
