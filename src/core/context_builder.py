"""Context builder for assembling LLM context."""

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from xml.sax.saxutils import escape as xml_escape

from src.memory import MemoryManager
from src.rag import HybridRetriever, CodeChunk
from src.prompts import PromptOptimizer
from src.prompts.system_prompts import get_system_prompt, get_plan_mode_injection
from src.core.file_reference_parser import FileReference

logger = logging.getLogger(__name__)


@dataclass
class ContextAssemblyReport:
    """
    Report of actual token usage in assembled context.

    This is the single source of truth for context pressure decisions.
    All token counts are measured from the actual assembled payload.
    """
    # Configuration
    total_limit: int
    reserved_output_tokens: int
    safety_buffer_tokens: int

    # Token counts by bucket (measured, not estimated)
    system_prompt_tokens: int = 0
    tools_schema_tokens: int = 0  # Tool definitions sent to LLM
    file_references_tokens: int = 0
    rag_tokens: int = 0
    agent_state_tokens: int = 0
    working_memory_tokens: int = 0
    episodic_memory_tokens: int = 0

    # Computed fields
    total_input_tokens: int = field(init=False)
    available_for_input: int = field(init=False)
    utilization_percent: float = field(init=False)
    headroom_tokens: int = field(init=False)

    def __post_init__(self):
        """Calculate derived fields after initialization."""
        self.total_input_tokens = (
            self.system_prompt_tokens +
            self.tools_schema_tokens +
            self.file_references_tokens +
            self.rag_tokens +
            self.agent_state_tokens +
            self.working_memory_tokens +
            self.episodic_memory_tokens
        )

        # Available budget for input (excluding output reservation and safety buffer)
        self.available_for_input = (
            self.total_limit -
            self.reserved_output_tokens -
            self.safety_buffer_tokens
        )

        # Utilization as percentage of available input budget
        if self.available_for_input > 0:
            self.utilization_percent = (
                self.total_input_tokens / self.available_for_input
            ) * 100
        else:
            self.utilization_percent = 100.0

        # Headroom = how many tokens we can still add
        self.headroom_tokens = self.available_for_input - self.total_input_tokens

    def is_over_budget(self) -> bool:
        """Check if we've exceeded the available input budget."""
        return self.total_input_tokens > self.available_for_input

    def get_pressure_level(self) -> str:
        """
        Get pressure level based on utilization.

        Returns:
            'green' (< 60%), 'yellow' (60-80%), 'orange' (80-90%), 'red' (> 90%)
        """
        if self.utilization_percent >= 90:
            return 'red'
        elif self.utilization_percent >= 80:
            return 'orange'
        elif self.utilization_percent >= 60:
            return 'yellow'
        else:
            return 'green'

    def format_summary(self) -> str:
        """Format a one-line summary for logging."""
        return (
            f"CTX: {self.total_input_tokens:,}/{self.available_for_input:,} "
            f"({self.utilization_percent:.1f}%) [{self.get_pressure_level().upper()}] | "
            f"sys={self.system_prompt_tokens:,} tools={self.tools_schema_tokens:,} "
            f"refs={self.file_references_tokens:,} rag={self.rag_tokens:,} "
            f"state={self.agent_state_tokens:,} work={self.working_memory_tokens:,} "
            f"epi={self.episodic_memory_tokens:,} | "
            f"reserve_out={self.reserved_output_tokens:,} headroom={self.headroom_tokens:,}"
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'total_limit': self.total_limit,
            'reserved_output_tokens': self.reserved_output_tokens,
            'safety_buffer_tokens': self.safety_buffer_tokens,
            'system_prompt_tokens': self.system_prompt_tokens,
            'tools_schema_tokens': self.tools_schema_tokens,
            'file_references_tokens': self.file_references_tokens,
            'rag_tokens': self.rag_tokens,
            'agent_state_tokens': self.agent_state_tokens,
            'working_memory_tokens': self.working_memory_tokens,
            'episodic_memory_tokens': self.episodic_memory_tokens,
            'total_input_tokens': self.total_input_tokens,
            'available_for_input': self.available_for_input,
            'utilization_percent': self.utilization_percent,
            'headroom_tokens': self.headroom_tokens,
            'pressure_level': self.get_pressure_level(),
        }


class ContextBuilder:
    """Builds optimized context for LLM from multiple sources."""

    def __init__(
        self,
        memory_manager: MemoryManager,
        retriever: Optional[HybridRetriever] = None,
        max_context_tokens: int = 4096,
        reserved_output_tokens: Optional[int] = None,
        safety_buffer_tokens: Optional[int] = None,
        tools_schema_tokens: Optional[int] = None,
        project_root: Optional[Path] = None,
    ):
        """
        Initialize context builder.

        Args:
            memory_manager: Memory manager instance
            retriever: Optional RAG retriever
            max_context_tokens: Maximum context window size
            reserved_output_tokens: Tokens reserved for LLM output (default from env or 12000)
            safety_buffer_tokens: Safety buffer tokens (default from env or 2000)
            tools_schema_tokens: Estimated tokens for tool schemas (default from env or 3000)
            project_root: Project root directory (for file reference resolution)
        """
        self.memory = memory_manager
        self.retriever = retriever
        self.max_context_tokens = max_context_tokens
        self.project_root = project_root
        self.optimizer = PromptOptimizer()

        # Load from environment with sensible defaults
        self.reserved_output_tokens = reserved_output_tokens or int(
            os.getenv("RESERVED_OUTPUT_TOKENS", "12000")
        )
        self.safety_buffer_tokens = safety_buffer_tokens or int(
            os.getenv("SAFETY_BUFFER_TOKENS", "2000")
        )
        self.tools_schema_tokens = tools_schema_tokens or int(
            os.getenv("RESERVED_TOOL_SCHEMA_TOKENS", "3000")
        )

        # Store last assembly report for inspection
        self.last_report: Optional[ContextAssemblyReport] = None

    def build_context(
        self,
        user_query: str,
        task_type: str = "implement",
        language: str = "python",
        use_rag: bool = True,
        available_chunks: Optional[List[CodeChunk]] = None,
        file_references: Optional[List[FileReference]] = None,
        agent_state: Optional[Dict[str, Any]] = None,
        plan_mode_state: Optional[Any] = None,
        log_report: bool = True,
    ) -> List[Dict[str, str]]:
        """
        Build complete context for LLM.

        Conversation history is obtained from MemoryManager.get_context_for_llm(),
        which uses MessageStore when configured (Option A: Single Source of Truth).
        This provides unified handling for both new and resumed sessions.

        Args:
            user_query: User's query/request
            task_type: Type of task
            language: Programming language
            use_rag: Whether to use RAG retrieval
            available_chunks: Optional pre-loaded chunks for RAG
            file_references: Optional list of file references to inject
            agent_state: Optional agent state (todos, current_todo_id, last_stop_reason)
                        for task continuation support
            plan_mode_state: Optional PlanModeState instance for plan mode injection
            log_report: Whether to log the context assembly report (default True)

        Returns:
            List of message dictionaries
        """
        # Token tracking for each bucket
        tokens = {
            'system_prompt': 0,
            'file_references': 0,
            'rag': 0,
            'agent_state': 0,
            'working_memory': 0,
            'episodic_memory': 0,
        }

        # Calculate token budgets (percentages for compression decisions)
        system_prompt_budget = int(self.max_context_tokens * 0.15)  # 15%
        rag_budget = int(self.max_context_tokens * 0.30)  # 30%

        # 1. Build system prompt using gold-standard prompts (based on Claude Code)
        system_prompt = get_system_prompt(
            language=language,
            task_type=task_type,
            context_size=self.max_context_tokens
        )

        # Inject plan mode context if active
        if plan_mode_state and plan_mode_state.is_active:
            plan_injection = get_plan_mode_injection(
                plan_path=str(plan_mode_state.plan_file_path),
                plan_hash=plan_mode_state.plan_hash,
                is_awaiting_approval=plan_mode_state.is_awaiting_approval()
            )
            system_prompt = system_prompt + "\n\n" + plan_injection

        # Compress if needed
        if self.optimizer.count_tokens(system_prompt) > system_prompt_budget:
            system_prompt = self.optimizer.compress_prompt(
                system_prompt,
                target_tokens=system_prompt_budget,
            )

        tokens['system_prompt'] = self.optimizer.count_tokens(system_prompt)

        # 2. Retrieve relevant code (if RAG enabled)
        rag_context = ""
        if use_rag and self.retriever and available_chunks:
            results = self.retriever.search(
                query=user_query,
                chunks=available_chunks,
                top_k=3,
            )

            if results:
                rag_parts = []
                for i, result in enumerate(results, 1):
                    rag_parts.append(
                        f"## Relevant Code {i} (score: {result.score:.2f})\n"
                        f"File: {result.chunk.file_path}\n"
                        f"```{result.chunk.language}\n"
                        f"{result.chunk.content}\n"
                        f"```"
                    )
                rag_context = "\n\n".join(rag_parts)

                # Compress if needed
                if self.optimizer.count_tokens(rag_context) > rag_budget:
                    rag_context = self.optimizer.compress_prompt(
                        rag_context,
                        target_tokens=rag_budget,
                    )

        if rag_context:
            tokens['rag'] = self.optimizer.count_tokens(rag_context)

        # 3. Get memory context from MemoryManager
        # MemoryManager uses MessageStore when configured (Option A: Single Source of Truth)
        # This provides unified handling for both new and resumed sessions
        memory_context = self.memory.get_context_for_llm(
            system_prompt="",  # We'll add system prompt separately
            include_episodic=True,
            include_semantic_query=user_query if not use_rag else None,
        )

        # Count memory tokens by type
        for msg in memory_context:
            if msg.get("role") == "system":
                # System messages from memory are episodic summaries
                content = msg.get("content", "")
                if isinstance(content, str):
                    tokens['episodic_memory'] += self.optimizer.count_tokens(content)
            else:
                # User/assistant/tool messages are working memory
                content = msg.get("content", "")
                if isinstance(content, str):
                    tokens['working_memory'] += self.optimizer.count_tokens(content)

        # 4. Assemble final context
        context = []

        # Add system prompt
        context.append({
            "role": "system",
            "content": system_prompt
        })

        # Add file references if provided (after system prompt, before RAG)
        file_context_content = ""
        if file_references:
            loaded_refs = [ref for ref in file_references if ref.is_loaded]
            if loaded_refs:
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

                file_context_content = "\n".join(file_parts)
                full_file_content = f"<referenced_files>\nThe user has referenced these files:\n\n{file_context_content}\n</referenced_files>"
                context.append({
                    "role": "system",
                    "content": full_file_content
                })
                tokens['file_references'] = self.optimizer.count_tokens(full_file_content)

        # Add RAG context if available
        if rag_context:
            context.append({
                "role": "system",
                "content": f"<relevant_code>\n{rag_context}\n</relevant_code>"
            })

        # Add agent state if incomplete work exists (task continuation support)
        if agent_state:
            state_block = self._format_agent_state(agent_state)
            if state_block:
                context.append({
                    "role": "system",
                    "content": state_block
                })
                tokens['agent_state'] = self.optimizer.count_tokens(state_block)

        # Add memory context (skip system messages from memory as we have our own)
        for msg in memory_context:
            if msg["role"] != "system":
                context.append(msg)

        # 5. Build and store the assembly report
        self.last_report = ContextAssemblyReport(
            total_limit=self.max_context_tokens,
            reserved_output_tokens=self.reserved_output_tokens,
            safety_buffer_tokens=self.safety_buffer_tokens,
            system_prompt_tokens=tokens['system_prompt'],
            tools_schema_tokens=self.tools_schema_tokens,  # Estimated, actual counted at LLM call
            file_references_tokens=tokens['file_references'],
            rag_tokens=tokens['rag'],
            agent_state_tokens=tokens['agent_state'],
            working_memory_tokens=tokens['working_memory'],
            episodic_memory_tokens=tokens['episodic_memory'],
        )

        # Log the report if enabled
        if log_report:
            self._log_context_report(self.last_report)

        return context

    def _log_context_report(self, report: ContextAssemblyReport) -> None:
        """
        Log context assembly report.

        Uses DEBUG level by default, WARNING for orange/red pressure.
        """
        summary = report.format_summary()
        pressure = report.get_pressure_level()

        if pressure == 'red':
            logger.warning(f"[CONTEXT PRESSURE RED] {summary}")
        elif pressure == 'orange':
            logger.warning(f"[CONTEXT PRESSURE ORANGE] {summary}")
        elif pressure == 'yellow':
            logger.info(f"[CONTEXT PRESSURE YELLOW] {summary}")
        else:
            logger.debug(summary)

    def build_context_with_report(
        self,
        user_query: str,
        task_type: str = "implement",
        language: str = "python",
        use_rag: bool = True,
        available_chunks: Optional[List[CodeChunk]] = None,
        file_references: Optional[List[FileReference]] = None,
        agent_state: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[Dict[str, str]], ContextAssemblyReport]:
        """
        Build context and return both messages and assembly report.

        This is the preferred method when you need to inspect the report.

        Returns:
            Tuple of (messages, ContextAssemblyReport)
        """
        context = self.build_context(
            user_query=user_query,
            task_type=task_type,
            language=language,
            use_rag=use_rag,
            available_chunks=available_chunks,
            file_references=file_references,
            agent_state=agent_state,
            log_report=True,
        )

        # last_report is guaranteed to be set after build_context
        return context, self.last_report  # type: ignore

    def estimate_tokens(self, context: List[Dict[str, str]]) -> int:
        """
        Estimate total tokens in context.

        Args:
            context: List of messages

        Returns:
            Estimated token count
        """
        total = 0
        for msg in context:
            total += self.optimizer.count_tokens(msg["content"])
        return total

    def _format_agent_state(self, agent_state: Dict[str, Any]) -> Optional[str]:
        """
        Format agent state as compact, XML-safe block for LLM context.

        Design:
        - ONLY inject in_progress + pending todos (not full completed list)
        - Include completed_count as summary
        - XML-escape all content to prevent markup breakage
        - Truncate long content (200 chars max)
        - NO RULES in this block - facts only (rules stay in system prompt)

        Args:
            agent_state: Dict containing todos, current_todo_id, last_stop_reason

        Returns:
            Formatted XML-like string for LLM context, or None if no incomplete work
        """
        todos = agent_state.get('todos', [])
        if not todos:
            return None

        # Separate by status
        completed = [t for t in todos if t.get('status') == 'completed']
        incomplete = [t for t in todos if t.get('status') in ('in_progress', 'pending')]

        if not incomplete:
            return None  # All complete, no need to inject

        def safe_content(text: str, max_len: int = 200) -> str:
            """XML-escape and truncate content."""
            if not text:
                return ""
            # Normalize whitespace (collapse newlines)
            text = re.sub(r'\s+', ' ', text.strip())
            # Truncate
            if len(text) > max_len:
                text = text[:max_len] + "..."
            # XML escape: & < > (critical for valid markup)
            return xml_escape(text)

        lines = ["<agent_state>", "  <todos>"]

        # Only include incomplete todos (compact)
        for t in incomplete:
            tid = t.get('id', 'T?')
            status = t.get('status', 'pending')
            content = safe_content(t.get('content', ''))
            lines.append(f'    <todo id="{tid}" status="{status}">{content}</todo>')

        lines.append("  </todos>")
        lines.append(f"  <completed_count>{len(completed)}</completed_count>")

        current_id = agent_state.get('current_todo_id')
        if current_id:
            lines.append(f"  <current_todo_id>{current_id}</current_todo_id>")

        stop_reason = agent_state.get('last_stop_reason')
        if stop_reason:
            lines.append(f"  <stop_reason>{stop_reason}</stop_reason>")

        lines.append("</agent_state>")
        return "\n".join(lines)

    def build_context_with_headroom_guard(
        self,
        user_query: str,
        task_type: str = "implement",
        language: str = "python",
        use_rag: bool = True,
        available_chunks: Optional[List[CodeChunk]] = None,
        file_references: Optional[List[FileReference]] = None,
        agent_state: Optional[Dict[str, Any]] = None,
        max_compaction_attempts: int = 2,
    ) -> Tuple[List[Dict[str, str]], ContextAssemblyReport]:
        """
        Build context with automatic headroom enforcement.

        This is the PREFERRED method for production use. It:
        1. Builds context and measures token usage
        2. If over budget, triggers memory compaction
        3. Rebuilds and re-measures
        4. Logs warnings if still over budget after compaction

        Conversation history is obtained from MemoryManager.get_context_for_llm(),
        which uses MessageStore when configured (Option A: Single Source of Truth).

        Args:
            user_query: User's query/request
            task_type: Type of task
            language: Programming language
            use_rag: Whether to use RAG retrieval
            available_chunks: Optional pre-loaded chunks for RAG
            file_references: Optional list of file references to inject
            agent_state: Optional agent state for task continuation
            max_compaction_attempts: Maximum compaction attempts before giving up

        Returns:
            Tuple of (messages, ContextAssemblyReport)

        Raises:
            ContextBudgetExceededError: If over budget after all compaction attempts
                                        (only if strict mode enabled via env)
        """
        # Build initial context
        context = self.build_context(
            user_query=user_query,
            task_type=task_type,
            language=language,
            use_rag=use_rag,
            available_chunks=available_chunks,
            file_references=file_references,
            agent_state=agent_state,
            log_report=False,  # We'll log after potential compaction
        )

        report = self.last_report
        if report is None:
            raise RuntimeError("build_context did not produce a report")

        # Check if we need to compact
        attempts = 0
        while report.is_over_budget() and attempts < max_compaction_attempts:
            attempts += 1
            logger.warning(
                f"[HEADROOM GUARD] Over budget ({report.utilization_percent:.1f}%), "
                f"triggering compaction (attempt {attempts}/{max_compaction_attempts})"
            )

            # Trigger memory compaction
            self._trigger_compaction(report)

            # Rebuild context
            context = self.build_context(
                user_query=user_query,
                task_type=task_type,
                language=language,
                use_rag=use_rag,
                available_chunks=available_chunks,
                file_references=file_references,
                agent_state=agent_state,
                log_report=False,
            )
            report = self.last_report  # type: ignore

        # Log the final report
        self._log_context_report(report)

        # Final check - warn but don't block (blocking is opt-in via env)
        if report.is_over_budget():
            strict_mode = os.getenv("CONTEXT_STRICT_MODE", "false").lower() == "true"
            if strict_mode:
                raise ContextBudgetExceededError(
                    f"Context budget exceeded after {max_compaction_attempts} compaction attempts. "
                    f"Used {report.total_input_tokens:,} tokens, "
                    f"available {report.available_for_input:,} tokens."
                )
            else:
                logger.error(
                    f"[HEADROOM GUARD] Still over budget after {attempts} compaction attempts! "
                    f"Used: {report.total_input_tokens:,}, Available: {report.available_for_input:,}. "
                    f"Request will proceed but may fail or truncate."
                )

        return context, report

    def _trigger_compaction(self, report: ContextAssemblyReport) -> None:
        """
        Trigger memory compaction based on current pressure.

        Compaction strategy based on pressure level:
        - ORANGE (80-90%): Light compaction - compress episodic memory
        - RED (90%+): Aggressive compaction - compress everything

        Args:
            report: Current context assembly report
        """
        pressure = report.get_pressure_level()

        if pressure == 'red':
            # Aggressive compaction
            logger.info("[COMPACTION] RED pressure - aggressive compaction")

            # 1. Compress episodic memory
            self.memory.episodic_memory._compress_old_turns()

            # 2. Compact working memory
            self.memory.working_memory._compact()

            # 3. Use optimize_context with tight target
            target = int(report.available_for_input * 0.85)  # Target 85% of available
            self.memory.optimize_context(target_tokens=target)

        elif pressure == 'orange':
            # Light compaction
            logger.info("[COMPACTION] ORANGE pressure - light compaction")

            # Just compress episodic memory
            self.memory.episodic_memory._compress_old_turns()

        else:
            # Yellow or green - shouldn't normally reach here
            logger.debug(f"[COMPACTION] {pressure} pressure - minimal compaction")
            self.memory.episodic_memory._compress_old_turns()

    def get_headroom_status(self) -> Dict[str, Any]:
        """
        Get current headroom status without building full context.

        Useful for quick checks before expensive operations.

        Returns:
            Dict with headroom information
        """
        # Get current memory token counts
        working_tokens = self.memory.working_memory.get_current_token_count()
        episodic_tokens = self.memory.episodic_memory.current_token_count

        # Estimate total (without system prompt, which varies)
        estimated_total = (
            working_tokens +
            episodic_tokens +
            self.tools_schema_tokens +
            5000  # Rough estimate for system prompt
        )

        available = (
            self.max_context_tokens -
            self.reserved_output_tokens -
            self.safety_buffer_tokens
        )

        utilization = (estimated_total / available) * 100 if available > 0 else 100

        return {
            "working_memory_tokens": working_tokens,
            "episodic_memory_tokens": episodic_tokens,
            "estimated_total_tokens": estimated_total,
            "available_for_input": available,
            "estimated_utilization_percent": utilization,
            "estimated_headroom_tokens": available - estimated_total,
            "needs_compaction": utilization >= 80,
        }


class ContextBudgetExceededError(Exception):
    """Raised when context budget is exceeded and strict mode is enabled."""
    pass
