"""Main coding agent orchestration."""

import uuid
from typing import Optional, List, Dict, Any
from pathlib import Path

from src.memory import MemoryManager, TaskContext
from src.rag import CodeIndexer, Embedder, HybridRetriever, CodeChunk
from src.llm import LLMBackend, OllamaBackend, LLMConfig, LLMBackendType
from src.tools import ToolExecutor, ReadFileTool, WriteFileTool, EditFileTool, SearchCodeTool, AnalyzeCodeTool
from src.tools.tool_parser import ToolCallParser, ParsedResponse
from src.prompts import PromptLibrary, TaskType
from .context_builder import ContextBuilder


class AgentResponse:
    """Response from the coding agent."""

    def __init__(
        self,
        content: str,
        tool_calls: Optional[List[Dict]] = None,
        metadata: Optional[Dict] = None,
    ):
        self.content = content
        self.tool_calls = tool_calls or []
        self.metadata = metadata or {}


class CodingAgent:
    """
    Main AI coding agent that orchestrates all components.
    Optimized for small open-source LLMs.
    """

    def __init__(
        self,
        model_name: str = "qwen3-coder:30b",
        backend: str = "ollama",
        base_url: str = "http://localhost:11434",
        context_window: int = 131072,
        working_directory: str = ".",
    ):
        """
        Initialize coding agent.

        Args:
            model_name: Name of the LLM model
            backend: Backend type (ollama, vllm, etc.)
            base_url: Base URL for LLM API
            context_window: Context window size
            working_directory: Working directory for file operations
        """
        self.model_name = model_name
        self.context_window = context_window
        self.working_directory = Path(working_directory)

        # Initialize LLM backend
        llm_config = LLMConfig(
            backend_type=LLMBackendType(backend),
            model_name=model_name,
            base_url=base_url,
            context_window=context_window,
            num_ctx=context_window,
        )

        if backend == "ollama":
            self.llm: LLMBackend = OllamaBackend(llm_config)
        else:
            raise ValueError(f"Unsupported backend: {backend}")

        # Initialize memory system
        self.memory = MemoryManager(
            total_context_tokens=context_window,
            working_memory_tokens=int(context_window * 0.4),
            episodic_memory_tokens=int(context_window * 0.2),
        )

        # Initialize RAG components (lazy loading)
        self.indexer: Optional[CodeIndexer] = None
        self.embedder: Optional[Embedder] = None
        self.retriever: Optional[HybridRetriever] = None
        self.indexed_chunks: List[CodeChunk] = []

        # Initialize tools
        self.tool_executor = ToolExecutor()
        self._register_tools()

        # Initialize tool parser
        self.tool_parser = ToolCallParser()

        # Initialize context builder
        self.context_builder = ContextBuilder(
            memory_manager=self.memory,
            retriever=self.retriever,
            max_context_tokens=context_window,
        )

    def _register_tools(self) -> None:
        """Register available tools."""
        self.tool_executor.register_tool(ReadFileTool())
        self.tool_executor.register_tool(WriteFileTool())
        self.tool_executor.register_tool(EditFileTool())
        self.tool_executor.register_tool(SearchCodeTool())
        self.tool_executor.register_tool(AnalyzeCodeTool())

    def _execute_with_tools(
        self,
        context: List[Dict[str, str]],
        max_iterations: int = 5,
        stream: bool = False
    ) -> str:
        """
        Execute LLM with tool calling loop.

        Args:
            context: Initial conversation context
            max_iterations: Maximum tool calling iterations (prevent infinite loops)
            stream: Whether to stream responses

        Returns:
            Final response content
        """
        iteration = 0
        current_context = context.copy()

        while iteration < max_iterations:
            iteration += 1
            print(f"\n[Tool Loop - Iteration {iteration}/{max_iterations}]")

            # Generate LLM response
            if stream and iteration == 1:  # Only stream first response
                full_response = ""
                for chunk in self.llm.generate_stream(current_context):
                    print(chunk.content, end="", flush=True)
                    full_response += chunk.content
                print()  # New line after streaming
                response_content = full_response
            else:
                llm_response = self.llm.generate(current_context)
                response_content = llm_response.content
                if not stream:
                    print(f"LLM Response: {response_content[:200]}...")

            # Parse response for tool calls
            parsed = self.tool_parser.parse(response_content)

            if not parsed.has_tool_calls:
                # No tool calls - we're done
                print("[Tool Loop] No tool calls detected - finishing")
                return response_content

            # Execute tool calls
            print(f"[Tool Loop] Found {len(parsed.tool_calls)} tool call(s)")
            if parsed.thoughts:
                print(f"[Tool Loop] Thoughts: {parsed.thoughts}")

            tool_results = []
            for i, tool_call in enumerate(parsed.tool_calls, 1):
                print(f"\n[Tool {i}/{len(parsed.tool_calls)}] Executing: {tool_call.tool}")
                print(f"  Arguments: {tool_call.arguments}")

                try:
                    # Execute the tool
                    result = self.tool_executor.execute_tool(
                        tool_call.tool,
                        **tool_call.arguments
                    )

                    if result.is_success():
                        output = result.output
                        # Truncate large outputs
                        if isinstance(output, str) and len(output) > 2000:
                            output = output[:2000] + f"\n... (truncated {len(output) - 2000} characters)"

                        tool_results.append({
                            "tool": tool_call.tool,
                            "arguments": tool_call.arguments,
                            "success": True,
                            "result": output
                        })
                        print(f"  ✓ Success: {str(output)[:100]}...")
                    else:
                        tool_results.append({
                            "tool": tool_call.tool,
                            "arguments": tool_call.arguments,
                            "success": False,
                            "error": result.error
                        })
                        print(f"  ✗ Error: {result.error}")

                except Exception as e:
                    tool_results.append({
                        "tool": tool_call.tool,
                        "arguments": tool_call.arguments,
                        "success": False,
                        "error": str(e)
                    })
                    print(f"  ✗ Exception: {e}")

            # Format tool results for LLM
            tool_results_text = self._format_tool_results(tool_results)

            # Add assistant's tool request and tool results to context
            current_context.append({
                "role": "assistant",
                "content": response_content
            })
            current_context.append({
                "role": "user",
                "content": f"Tool execution results:\n\n{tool_results_text}\n\nPlease provide your response to the user based on these results."
            })

        # Max iterations reached
        print(f"\n[Tool Loop] Max iterations ({max_iterations}) reached")
        return "I've executed several tool operations but need to stop here. Please review the results above."

    def _format_tool_results(self, results: List[Dict[str, Any]]) -> str:
        """Format tool results for LLM consumption."""
        formatted = []

        for i, result in enumerate(results, 1):
            if result["success"]:
                formatted.append(
                    f"Tool {i}: {result['tool']}\n"
                    f"Arguments: {result['arguments']}\n"
                    f"Result:\n{result['result']}\n"
                )
            else:
                formatted.append(
                    f"Tool {i}: {result['tool']}\n"
                    f"Arguments: {result['arguments']}\n"
                    f"Error: {result['error']}\n"
                )

        return "\n".join(formatted)

    def index_codebase(
        self,
        directory: Optional[str] = None,
        file_patterns: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Index codebase for RAG retrieval.

        Args:
            directory: Directory to index (default: working directory)
            file_patterns: File patterns to include

        Returns:
            Indexing statistics
        """
        if not directory:
            directory = str(self.working_directory)

        print(f"Indexing codebase at: {directory}")

        # Initialize RAG components
        self.indexer = CodeIndexer(chunk_size=512, chunk_overlap=50)
        self.embedder = Embedder(model_name="sentence-transformers/all-MiniLM-L6-v2")

        # Index codebase
        chunks, index, dep_graph = self.indexer.index_codebase(
            root_path=directory,
            file_patterns=file_patterns,
        )

        print(f"Generated {len(chunks)} chunks from {index.total_files} files")

        # Generate embeddings
        print("Generating embeddings...")
        self.indexed_chunks = self.embedder.embed_chunks(chunks)

        # Setup retriever
        self.retriever = HybridRetriever(self.embedder, alpha=0.7)
        self.retriever.index_chunks(self.indexed_chunks)

        # Update context builder
        self.context_builder.retriever = self.retriever

        print("Indexing complete!")

        return {
            "total_files": index.total_files,
            "total_chunks": len(self.indexed_chunks),
            "languages": index.languages,
        }

    def execute_task(
        self,
        task_description: str,
        task_type: str = "implement",
        language: str = "python",
        use_rag: bool = True,
        stream: bool = False,
    ) -> AgentResponse:
        """
        Execute a coding task.

        Args:
            task_description: Description of the task
            task_type: Type of task (implement, debug, refactor, etc.)
            language: Programming language
            use_rag: Whether to use RAG retrieval
            stream: Whether to stream response

        Returns:
            Agent response
        """
        # Create task context
        task_context = TaskContext(
            task_id=str(uuid.uuid4()),
            description=task_description,
            task_type=task_type,
            key_concepts=[],
        )

        self.memory.set_task_context(task_context)

        # Add user message to memory
        self.memory.add_user_message(task_description)

        # Build context
        context = self.context_builder.build_context(
            user_query=task_description,
            task_type=task_type,
            language=language,
            use_rag=use_rag and len(self.indexed_chunks) > 0,
            available_chunks=self.indexed_chunks if use_rag else None,
        )

        # Execute with tool calling loop
        response_content = self._execute_with_tools(
            context=context,
            max_iterations=5,
            stream=stream
        )

        # Add assistant response to memory
        self.memory.add_assistant_message(response_content)

        return AgentResponse(
            content=response_content,
            metadata={
                "task_type": task_type,
                "language": language,
                "used_rag": use_rag and len(self.indexed_chunks) > 0,
            }
        )

    def chat(self, message: str, stream: bool = True) -> AgentResponse:
        """
        Interactive chat with the agent.

        Args:
            message: User message
            stream: Whether to stream response

        Returns:
            Agent response
        """
        # Determine task type from message
        task_type = self._infer_task_type(message)

        return self.execute_task(
            task_description=message,
            task_type=task_type,
            stream=stream,
        )

    def _infer_task_type(self, message: str) -> str:
        """Infer task type from message content."""
        message_lower = message.lower()

        if any(word in message_lower for word in ["debug", "fix", "error", "bug"]):
            return "debug"
        elif any(word in message_lower for word in ["refactor", "improve", "optimize"]):
            return "refactor"
        elif any(word in message_lower for word in ["explain", "what", "how", "why"]):
            return "explain"
        elif any(word in message_lower for word in ["test", "unittest"]):
            return "test"
        elif any(word in message_lower for word in ["document", "docstring"]):
            return "document"
        elif any(word in message_lower for word in ["review", "check"]):
            return "review"
        else:
            return "implement"

    def execute_tool(self, tool_name: str, **kwargs: Any) -> Any:
        """
        Execute a tool.

        Args:
            tool_name: Name of tool
            **kwargs: Tool parameters

        Returns:
            Tool result
        """
        result = self.tool_executor.execute_tool(tool_name, **kwargs)

        if result.is_success():
            return result.output
        else:
            raise RuntimeError(result.error)

    def get_available_tools(self) -> str:
        """Get description of available tools."""
        return self.tool_executor.get_tools_description()

    def save_session(self, session_name: Optional[str] = None) -> Path:
        """Save current session."""
        return self.memory.save_session(session_name)

    def load_session(self, session_path: Path) -> None:
        """Load a saved session."""
        self.memory.load_session(session_path)

    def get_statistics(self) -> Dict[str, Any]:
        """Get agent statistics."""
        stats = {
            "model": self.model_name,
            "context_window": self.context_window,
            "indexed_chunks": len(self.indexed_chunks),
            "memory": self.memory.get_statistics(),
        }

        return stats

    def clear_memory(self) -> None:
        """Clear all memory."""
        self.memory.clear_all()
