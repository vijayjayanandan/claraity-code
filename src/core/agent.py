"""Main coding agent orchestration."""

import uuid
from typing import Optional, List, Dict, Any, TYPE_CHECKING
from pathlib import Path

if TYPE_CHECKING:
    from src.hooks import HookManager, HookDecision

from src.memory import MemoryManager, TaskContext
from src.rag import CodeIndexer, Embedder, HybridRetriever, CodeChunk
from src.llm import LLMBackend, OllamaBackend, OpenAIBackend, LLMConfig, LLMBackendType
from src.tools import (
    ToolExecutor,
    ReadFileTool,
    WriteFileTool,
    EditFileTool,
    ListDirectoryTool,
    RunCommandTool,
    SearchCodeTool,
    AnalyzeCodeTool,
    GitStatusTool,
    GitDiffTool,
    GitCommitTool,
    DelegateToSubagentTool,
)
from src.tools.tool_parser import ToolCallParser, ParsedResponse
from src.prompts import PromptLibrary, TaskType
from .context_builder import ContextBuilder
from .file_reference_parser import FileReferenceParser

# Workflow components
from src.workflow import TaskAnalyzer, TaskPlanner, TaskAnalysis, ExecutionPlan, TaskType as WorkflowTaskType
from src.workflow.execution_engine import ExecutionEngine, ExecutionResult
from src.workflow.permission_manager import PermissionManager, PermissionMode

# Subagent components
from src.subagents import SubAgentManager, SubAgentResult

# ClarAIty integration
try:
    from src.clarity.integration import ClarityAgentHook
    CLARITY_AVAILABLE = True
except ImportError:
    CLARITY_AVAILABLE = False
    ClarityAgentHook = None


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
        api_key: Optional[str] = None,
        api_key_env: str = "OPENAI_API_KEY",
        load_file_memories: bool = True,
        permission_mode: str = "normal",
        hook_manager: Optional['HookManager'] = None,
        enable_clarity: bool = True,
    ):
        """
        Initialize coding agent.

        Args:
            model_name: Name of the LLM model
            backend: Backend type (ollama, openai, etc.)
            base_url: Base URL for LLM API
            context_window: Context window size
            working_directory: Working directory for file operations
            api_key: API key for OpenAI-compatible backends (optional)
            api_key_env: Environment variable name for API key (default: OPENAI_API_KEY)
            load_file_memories: Whether to load file-based memories on init (default: True)
            permission_mode: Permission mode (plan/normal/auto, default: normal)
            hook_manager: Optional hook manager for event hooks
            enable_clarity: Enable ClarAIty blueprint generation (default: True)
        """
        self.model_name = model_name
        self.context_window = context_window
        self.working_directory = Path(working_directory)
        self.hook_manager = hook_manager

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
        elif backend == "openai":
            self.llm: LLMBackend = OpenAIBackend(
                llm_config,
                api_key=api_key,
                api_key_env=api_key_env
            )
        else:
            raise ValueError(f"Unsupported backend: {backend}")

        # Initialize memory system with file-based memory loading
        self.memory = MemoryManager(
            total_context_tokens=context_window,
            working_memory_tokens=int(context_window * 0.4),
            episodic_memory_tokens=int(context_window * 0.2),
            load_file_memories=load_file_memories,
            starting_directory=self.working_directory,
        )

        # Initialize RAG components (lazy loading)
        self.indexer: Optional[CodeIndexer] = None
        self.embedder: Optional[Embedder] = None
        self.retriever: Optional[HybridRetriever] = None
        self.indexed_chunks: List[CodeChunk] = []

        # Initialize tools
        self.tool_executor = ToolExecutor(hook_manager=hook_manager)
        self._register_tools()

        # Initialize tool parser
        self.tool_parser = ToolCallParser()

        # Track tool execution history for testing/debugging
        self.tool_execution_history: List[Dict[str, Any]] = []

        # Initialize context builder
        self.context_builder = ContextBuilder(
            memory_manager=self.memory,
            retriever=self.retriever,
            max_context_tokens=context_window,
        )

        # Initialize file reference parser
        self.file_reference_parser = FileReferenceParser(
            base_dir=self.working_directory,
            max_file_size=100_000  # 100K chars max
        )

        # Initialize workflow components
        self.task_analyzer = TaskAnalyzer(self.llm)
        self.task_planner = TaskPlanner(self.llm)
        self.execution_engine = ExecutionEngine(
            tool_executor=self.tool_executor,
            llm_backend=self.llm,
            progress_callback=self._workflow_progress_callback
        )

        # Initialize permission manager
        try:
            mode = PermissionManager.from_string(permission_mode)
        except ValueError as e:
            print(f"Warning: {e}. Using NORMAL mode.")
            mode = PermissionMode.NORMAL
        self.permission_manager = PermissionManager(mode=mode)

        # Initialize subagent manager
        self.subagent_manager = SubAgentManager(
            main_agent=self,
            working_directory=self.working_directory,
            max_parallel_workers=4,
            enable_auto_delegation=True
        )

        # Discover available subagents
        self.subagent_manager.discover_subagents()

        # Register delegation tool (now that subagent_manager is initialized)
        self.tool_executor.register_tool(
            DelegateToSubagentTool(self.subagent_manager)
        )

        # Initialize ClarAIty hook (if available and enabled)
        self.clarity_hook = None
        if enable_clarity and CLARITY_AVAILABLE:
            try:
                self.clarity_hook = ClarityAgentHook()
                import logging
                logging.getLogger(__name__).info("ClarAIty integration enabled")
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"Failed to initialize ClarAIty: {e}")

        # SESSION START HOOK
        if self.hook_manager:
            try:
                self.hook_manager.emit_session_start(
                    working_directory=str(self.working_directory),
                    model_name=model_name,
                    config={
                        "backend": backend,
                        "context_window": context_window,
                        "permission_mode": permission_mode
                    }
                )

            except Exception as e:
                # SessionStart hooks don't block, just log errors
                import logging
                logging.getLogger(__name__).warning(f"SessionStart hook error: {e}")

    def delegate_to_subagent(
        self,
        subagent_name: str,
        task_description: str,
        context: Optional[Dict[str, Any]] = None,
        max_iterations: int = 5
    ) -> SubAgentResult:
        """Delegate a task to a specialized subagent.

        Subagents operate with independent context windows and specialized
        system prompts, preventing context pollution in the main conversation.

        Args:
            subagent_name: Name of the subagent (e.g., 'code-reviewer')
            task_description: Clear description of the task to delegate
            context: Optional additional context for the subagent
            max_iterations: Maximum tool-calling iterations for the subagent

        Returns:
            SubAgentResult with output, success status, and metadata

        Example:
            >>> result = agent.delegate_to_subagent(
            ...     'code-reviewer',
            ...     'Review src/api.py for security vulnerabilities'
            ... )
            >>> if result.success:
            ...     print(result.output)
        """
        import logging
        logger = logging.getLogger(__name__)

        logger.info(f"Delegating to subagent '{subagent_name}': {task_description[:100]}...")

        # Delegate to subagent
        result = self.subagent_manager.delegate(
            subagent_name=subagent_name,
            task_description=task_description,
            context=context,
            max_iterations=max_iterations
        )

        if not result:
            logger.error(f"Subagent '{subagent_name}' not found")
            # Return error result
            from src.subagents import SubAgentResult
            return SubAgentResult(
                success=False,
                subagent_name=subagent_name,
                output="",
                error=f"Subagent '{subagent_name}' not found. Available: {self.get_available_subagents()}"
            )

        # Emit SubagentStop hook if hook manager exists
        if self.hook_manager and result.success:
            try:
                self.hook_manager.emit_subagent_stop(
                    subagent_name=subagent_name,
                    result=result.output,
                    duration=result.execution_time
                )
            except Exception as e:
                logger.warning(f"SubagentStop hook error: {e}")

        logger.info(
            f"Subagent '{subagent_name}' completed: "
            f"{'✅ success' if result.success else '❌ failed'} "
            f"({result.execution_time:.2f}s)"
        )

        return result

    def get_available_subagents(self) -> List[str]:
        """Get list of all available subagent names.

        Returns:
            List of subagent names that can be used for delegation

        Example:
            >>> subagents = agent.get_available_subagents()
            >>> print(subagents)
            ['code-reviewer', 'test-writer', 'doc-writer']
        """
        return self.subagent_manager.get_available_subagents()

    def _register_tools(self) -> None:
        """Register available tools."""
        # File operations
        self.tool_executor.register_tool(ReadFileTool())
        self.tool_executor.register_tool(WriteFileTool())
        self.tool_executor.register_tool(EditFileTool())
        self.tool_executor.register_tool(ListDirectoryTool())

        # Code operations
        self.tool_executor.register_tool(SearchCodeTool())
        self.tool_executor.register_tool(AnalyzeCodeTool())

        # System operations
        self.tool_executor.register_tool(RunCommandTool())

        # Git operations
        self.tool_executor.register_tool(GitStatusTool())
        self.tool_executor.register_tool(GitDiffTool())
        self.tool_executor.register_tool(GitCommitTool())

        # Subagent delegation (requires subagent_manager to be initialized)
        # This is registered after subagent_manager is initialized in __init__
        # Will be registered separately via _register_delegation_tool()

    def _execute_with_tools(
        self,
        context: List[Dict[str, str]],
        max_iterations: int = 3,
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

                        tool_result = {
                            "tool": tool_call.tool,
                            "arguments": tool_call.arguments,
                            "success": True,
                            "result": output
                        }
                        tool_results.append(tool_result)

                        # Track in history for validation/testing
                        self.tool_execution_history.append(tool_result)

                        print(f"  ✓ Success: {str(output)[:100]}...")
                    else:
                        tool_result = {
                            "tool": tool_call.tool,
                            "arguments": tool_call.arguments,
                            "success": False,
                            "error": result.error
                        }
                        tool_results.append(tool_result)

                        # Track in history for validation/testing
                        self.tool_execution_history.append(tool_result)

                        print(f"  ✗ Error: {result.error}")

                except Exception as e:
                    tool_result = {
                        "tool": tool_call.tool,
                        "arguments": tool_call.arguments,
                        "success": False,
                        "error": str(e)
                    }
                    tool_results.append(tool_result)

                    # Track in history for validation/testing
                    self.tool_execution_history.append(tool_result)

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

        # Max iterations reached - generate final summary
        print(f"\n[Tool Loop] Max iterations ({max_iterations}) reached - generating final summary")

        # Ask LLM to summarize what was learned
        current_context.append({
            "role": "user",
            "content": "You've reached the maximum number of tool iterations. Based on the information you've gathered from the tools, please provide a clear, concise answer to the original user question."
        })

        # Generate final summary
        final_response = self.llm.generate(current_context)
        return final_response.content

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

    def _should_use_workflow(self, task_description: str, task_type: str) -> bool:
        """
        Decide whether to use full workflow or direct execution.

        Criteria for using workflow:
        - Task requires multiple steps (implement, refactor, bugfix, test)
        - Task is complex or high-risk
        - Task modifies code

        Direct execution for:
        - Simple queries (explain, search)
        - Single-step operations
        - Low-risk operations
        """
        # Use workflow for complex task types (check this first!)
        workflow_types = ["implement", "refactor", "debug", "test"]
        if task_type in workflow_types:
            return True

        # Keywords that indicate workflow needed
        workflow_keywords = [
            "implement", "create", "add", "build", "refactor",
            "fix", "debug", "modify", "change", "update",
            "test", "migrate", "restructure"
        ]

        # Keywords that indicate direct execution is fine
        direct_keywords = [
            "explain", "what", "how", "why", "show", "find",
            "search", "display", "read"
        ]

        task_lower = task_description.lower()

        # Check for workflow keywords first
        if any(keyword in task_lower for keyword in workflow_keywords):
            return True

        # Check for direct execution keywords
        if any(keyword in task_lower for keyword in direct_keywords):
            # But still use workflow if task is complex
            # Only override if it's an action on the "entire" codebase or "all" files
            if any(word in task_lower for word in ["entire", "refactor all", "change all", "update all"]):
                return True
            return False

        # Default to direct execution for simple queries
        return False

    def _display_analysis(self, analysis: TaskAnalysis) -> None:
        """Display task analysis to user."""
        print("\n" + "="*60)
        print("📊 TASK ANALYSIS")
        print("="*60)
        print(f"Task Type: {analysis.task_type.value}")
        print(f"Complexity: {analysis.complexity.name}")
        print(f"Risk Level: {analysis.risk_level.upper()}")
        print(f"Estimated Files: {analysis.estimated_files}")
        print(f"Estimated Iterations: {analysis.estimated_iterations}")
        print(f"Requires Planning: {analysis.requires_planning}")
        print(f"Requires Approval: {analysis.requires_approval}")
        print(f"Requires Git: {analysis.requires_git}")
        print(f"Requires Tests: {analysis.requires_tests}")
        if analysis.key_concepts:
            print(f"Key Concepts: {', '.join(analysis.key_concepts)}")
        if analysis.affected_systems:
            print(f"Affected Systems: {', '.join(analysis.affected_systems)}")
        print("="*60 + "\n")

    def _workflow_progress_callback(self, step_id: int, status: str, message: str) -> None:
        """
        Callback for workflow execution progress.

        Args:
            step_id: ID of the current step
            status: Status (starting, completed, failed)
            message: Progress message
        """
        status_emoji = {
            "starting": "▶️",
            "completed": "✅",
            "failed": "❌",
            "skipped": "⏭️"
        }

        emoji = status_emoji.get(status, "ℹ️")
        print(f"{emoji} Step {step_id}: {message}")

    def _execute_with_workflow(
        self,
        task_description: str,
        task_type: str,
        language: str,
        stream: bool = False,
    ) -> str:
        """
        Execute task using full workflow (Analyze → Plan → Execute).

        Args:
            task_description: Description of the task
            task_type: Type of task (implement, debug, etc.)
            language: Programming language
            stream: Whether to stream responses

        Returns:
            Final response content
        """
        print("\n" + "="*60)
        print("🔄 WORKFLOW MODE ACTIVATED")
        print("="*60)
        print(f"Task: {task_description}\n")

        # Step 1: Analyze the task
        print("▶️  Step 1/3: Analyzing task...")
        analysis = self.task_analyzer.analyze(task_description)
        self._display_analysis(analysis)

        # Step 2: Create execution plan
        print("▶️  Step 2/3: Creating execution plan...")
        plan = self.task_planner.create_plan(task_description, analysis)

        # Display plan to user
        print("\n" + "="*60)
        print("📋 EXECUTION PLAN")
        print("="*60)
        formatted_plan = self.task_planner.format_plan_for_user(plan)
        print(formatted_plan)
        print("\n")

        # Get user approval if required (via PermissionManager)
        approved = self.permission_manager.get_approval(plan, analysis)
        if not approved:
            return "Task cancelled by user - approval denied."

        # Step 3: Execute the plan
        print("▶️  Step 3/3: Executing plan...\n")
        print("="*60)
        print("🔨 EXECUTION IN PROGRESS")
        print("="*60 + "\n")

        result = self.execution_engine.execute_plan(plan)

        # Format final report
        print("\n" + "="*60)
        print("📊 EXECUTION SUMMARY")
        print("="*60)
        print(f"Status: {'✅ SUCCESS' if result.success else '❌ FAILED'}")
        print(f"Steps Completed: {len(result.completed_steps)}/{len(plan.steps)}")
        print(f"Total Time: ~{plan.total_estimated_time}")

        if result.completed_steps:
            print("\nCompleted Steps:")
            for step_id in result.completed_steps:
                step = plan.get_step_by_id(step_id)
                if step:
                    print(f"  ✅ Step {step_id}: {step.description}")

        if result.failed_steps:
            print("\nFailed Steps:")
            for step_id in result.failed_steps:
                step = plan.get_step_by_id(step_id)
                step_result = next((r for r in result.step_results if r.step_id == step_id), None)
                if step and step_result:
                    print(f"  ❌ Step {step_id}: {step.description}")
                    print(f"     Error: {step_result.error}")

        print("="*60 + "\n")

        # Generate final response based on results
        if result.success:
            response = self._generate_success_response(result, plan)
        else:
            response = self._generate_failure_response(result, plan)

        return response

    def _generate_success_response(self, result: ExecutionResult, plan: ExecutionPlan) -> str:
        """Generate success response from execution result."""
        parts = [
            f"✅ Task completed successfully!\n",
            f"\nI've completed the task: {plan.task_description}\n",
            f"\nSteps executed:",
        ]

        for step_id in result.completed_steps:
            step = plan.get_step_by_id(step_id)
            step_result = next((r for r in result.step_results if r.step_id == step_id), None)
            if step and step_result:
                parts.append(f"  • {step.description}")
                if step_result.output:
                    # Include brief output summary
                    output_preview = str(step_result.output)[:200]
                    if len(str(step_result.output)) > 200:
                        output_preview += "..."
                    parts.append(f"    → {output_preview}")

        if plan.success_criteria:
            parts.append(f"\n✓ Success criteria met:")
            for criterion in plan.success_criteria:
                parts.append(f"  • {criterion}")

        return "\n".join(parts)

    def _generate_failure_response(self, result: ExecutionResult, plan: ExecutionPlan) -> str:
        """Generate failure response from execution result."""
        parts = [
            f"❌ Task execution failed.\n",
            f"\nTask: {plan.task_description}\n",
            f"\nCompleted {len(result.completed_steps)} of {len(plan.steps)} steps.",
        ]

        if result.completed_steps:
            parts.append(f"\n✓ Completed steps:")
            for step_id in result.completed_steps:
                step = plan.get_step_by_id(step_id)
                if step:
                    parts.append(f"  • {step.description}")

        if result.failed_steps:
            parts.append(f"\n✗ Failed steps:")
            for step_id in result.failed_steps:
                step = plan.get_step_by_id(step_id)
                step_result = next((r for r in result.step_results if r.step_id == step_id), None)
                if step and step_result:
                    parts.append(f"  • {step.description}")
                    parts.append(f"    Error: {step_result.error}")

        if plan.rollback_strategy:
            parts.append(f"\n⚠️  Rollback available:")
            parts.append(f"  {plan.rollback_strategy}")

        return "\n".join(parts)

    def _execute_direct(
        self,
        task_description: str,
        task_type: str,
        language: str,
        use_rag: bool,
        stream: bool,
    ) -> str:
        """
        Execute task using direct LLM + tool calling (no workflow).

        This is the original execution path for simple queries.

        Args:
            task_description: Description of the task
            task_type: Type of task
            language: Programming language
            use_rag: Whether to use RAG retrieval
            stream: Whether to stream responses

        Returns:
            Final response content
        """
        # Parse and load file references from task description
        file_references = self.file_reference_parser.parse_and_load(task_description)

        # Display loaded files to user
        if file_references:
            summary = self.file_reference_parser.format_summary(file_references)
            print(f"\n{summary}\n")

        # Build context
        context = self.context_builder.build_context(
            user_query=task_description,
            task_type=task_type,
            language=language,
            use_rag=use_rag and len(self.indexed_chunks) > 0,
            available_chunks=self.indexed_chunks if use_rag else None,
            file_references=file_references if file_references else None,
        )

        # Execute with tool calling loop
        response_content = self._execute_with_tools(
            context=context,
            max_iterations=3,
            stream=stream
        )

        return response_content

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
        self.embedder = Embedder(model_name="text-embedding-v4")  # Alibaba Cloud API

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
        force_workflow: bool = False,
        force_direct: bool = False,
    ) -> AgentResponse:
        """
        Execute a coding task using workflow or direct execution.

        Args:
            task_description: Description of the task
            task_type: Type of task (implement, debug, refactor, etc.)
            language: Programming language
            use_rag: Whether to use RAG retrieval
            stream: Whether to stream response
            force_workflow: Force workflow mode (for testing)
            force_direct: Force direct mode (for testing)

        Returns:
            Agent response
        """
        # USER PROMPT SUBMIT HOOK
        if self.hook_manager:
            try:
                from src.hooks import HookContinue

                decision, modified_prompt = self.hook_manager.emit_user_prompt_submit(
                    prompt=task_description,
                    metadata={
                        "task_type": task_type,
                        "language": language,
                        "use_rag": use_rag,
                        "stream": stream
                    }
                )

                if decision == HookContinue.BLOCK:
                    return AgentResponse(
                        content="Prompt blocked by hook",
                        metadata={"blocked": True}
                    )

                # Use modified prompt if hook modified it
                task_description = modified_prompt

            except Exception as e:
                # Check if it's a HookBlockedError
                if e.__class__.__name__ == 'HookBlockedError':
                    return AgentResponse(
                        content=f"Prompt blocked by hook: {str(e)}",
                        metadata={"blocked": True}
                    )
                # Other errors, log and continue
                import logging
                logging.getLogger(__name__).warning(f"UserPromptSubmit hook error: {e}")

        # CLARAITY HOOK - Generate blueprint and get approval
        if self.clarity_hook:
            try:
                clarity_result = self.clarity_hook.intercept_task(
                    task_description=task_description,
                    task_type=task_type,
                    metadata={
                        "language": language,
                        "use_rag": use_rag,
                        "stream": stream
                    }
                )

                # Handle rejection
                if not clarity_result.should_proceed:
                    return AgentResponse(
                        content=f"Task rejected by user during blueprint review.\nFeedback: {clarity_result.feedback or 'None'}",
                        metadata={
                            "clarity_status": "rejected",
                            "clarity_feedback": clarity_result.feedback
                        }
                    )

                # Store blueprint in memory context if approved
                if clarity_result.blueprint:
                    self.memory.add_metadata("clarity_blueprint", clarity_result.blueprint.to_dict())
                    import logging
                    logging.getLogger(__name__).info(
                        f"Blueprint approved: {len(clarity_result.blueprint.components)} components"
                    )

            except Exception as e:
                # ClarAIty errors shouldn't break the agent
                import logging
                logging.getLogger(__name__).warning(f"ClarAIty hook error: {e}")

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

        # Decide execution mode
        use_workflow = False
        if force_workflow:
            use_workflow = True
        elif force_direct:
            use_workflow = False
        else:
            use_workflow = self._should_use_workflow(task_description, task_type)

        # Execute based on decision
        if use_workflow:
            response_content = self._execute_with_workflow(
                task_description=task_description,
                task_type=task_type,
                language=language,
                stream=stream,
            )
            execution_mode = "workflow"
        else:
            print("\n💬 DIRECT EXECUTION MODE\n")
            response_content = self._execute_direct(
                task_description=task_description,
                task_type=task_type,
                language=language,
                use_rag=use_rag,
                stream=stream,
            )
            execution_mode = "direct"

        # Add assistant response to memory
        self.memory.add_assistant_message(response_content)

        return AgentResponse(
            content=response_content,
            metadata={
                "task_type": task_type,
                "language": language,
                "used_rag": use_rag and len(self.indexed_chunks) > 0,
                "execution_mode": execution_mode,
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

    def set_permission_mode(self, mode: str) -> None:
        """Set permission mode.

        Args:
            mode: Permission mode string (plan/normal/auto)

        Raises:
            ValueError: If mode is invalid
        """
        permission_mode = PermissionManager.from_string(mode)
        self.permission_manager.set_mode(permission_mode)

    def get_permission_mode(self) -> str:
        """Get current permission mode.

        Returns:
            Permission mode string (plan/normal/auto)
        """
        return self.permission_manager.get_mode().value

    def get_permission_mode_description(self) -> str:
        """Get description of current permission mode.

        Returns:
            Human-readable description of current mode
        """
        return self.permission_manager.format_mode_description()

    def shutdown(self) -> None:
        """
        Shutdown agent and cleanup resources.

        Emits SessionEnd hook if hook_manager is configured.
        """
        # SESSION END HOOK
        if self.hook_manager:
            try:
                # Gather session stats
                stats = self.get_statistics()

                self.hook_manager.emit_session_end(
                    duration=0.0,  # Would need to track session start time
                    statistics=stats,
                    exit_reason="normal"
                )

            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"SessionEnd hook error: {e}")
