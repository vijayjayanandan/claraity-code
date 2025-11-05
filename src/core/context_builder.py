"""Context builder for assembling LLM context."""

from typing import List, Dict, Any, Optional
from src.memory import MemoryManager
from src.rag import HybridRetriever, CodeChunk
from src.prompts import EnhancedSystemPrompts, PromptOptimizer
from src.core.file_reference_parser import FileReference


class ContextBuilder:
    """Builds optimized context for LLM from multiple sources."""

    def __init__(
        self,
        memory_manager: MemoryManager,
        retriever: Optional[HybridRetriever] = None,
        max_context_tokens: int = 4096,
    ):
        """
        Initialize context builder.

        Args:
            memory_manager: Memory manager instance
            retriever: Optional RAG retriever
            max_context_tokens: Maximum context window size
        """
        self.memory = memory_manager
        self.retriever = retriever
        self.max_context_tokens = max_context_tokens
        self.optimizer = PromptOptimizer()

    def build_context(
        self,
        user_query: str,
        task_type: str = "implement",
        language: str = "python",
        use_rag: bool = True,
        available_chunks: Optional[List[CodeChunk]] = None,
        file_references: Optional[List[FileReference]] = None,
    ) -> List[Dict[str, str]]:
        """
        Build complete context for LLM.

        Args:
            user_query: User's query/request
            task_type: Type of task
            language: Programming language
            use_rag: Whether to use RAG retrieval
            available_chunks: Optional pre-loaded chunks for RAG
            file_references: Optional list of file references to inject

        Returns:
            List of message dictionaries
        """
        # Calculate token budget
        system_prompt_tokens = int(self.max_context_tokens * 0.15)  # 15%
        task_tokens = int(self.max_context_tokens * 0.20)  # 20%
        rag_tokens = int(self.max_context_tokens * 0.30)  # 30%
        memory_tokens = int(self.max_context_tokens * 0.35)  # 35%

        # 1. Build system prompt using FULL enhanced prompts (production-grade)
        # Use full prompts for comprehensive instructions like modern coding agents
        system_prompt = EnhancedSystemPrompts.get_system_prompt(
            language=language,
            task_type=task_type,
            context_size=self.max_context_tokens
        )

        # Compress if needed
        if self.optimizer.count_tokens(system_prompt) > system_prompt_tokens:
            system_prompt = self.optimizer.compress_prompt(
                system_prompt,
                target_tokens=system_prompt_tokens,
            )

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
                if self.optimizer.count_tokens(rag_context) > rag_tokens:
                    rag_context = self.optimizer.compress_prompt(
                        rag_context,
                        target_tokens=rag_tokens,
                    )

        # 3. Get memory context
        memory_context = self.memory.get_context_for_llm(
            system_prompt="",  # We'll add system prompt separately
            include_episodic=True,
            include_semantic_query=user_query if not use_rag else None,
        )

        # 4. Assemble final context
        context = []

        # Add system prompt
        context.append({
            "role": "system",
            "content": system_prompt
        })

        # Add file references if provided (after system prompt, before RAG)
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

                file_context = "\n".join(file_parts)
                context.append({
                    "role": "system",
                    "content": f"<referenced_files>\nThe user has referenced these files:\n\n{file_context}\n</referenced_files>"
                })

        # Add RAG context if available
        if rag_context:
            context.append({
                "role": "system",
                "content": f"<relevant_code>\n{rag_context}\n</relevant_code>"
            })

        # Add memory context (skip system messages from memory as we have our own)
        for msg in memory_context:
            if msg["role"] != "system":
                context.append(msg)

        return context

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
