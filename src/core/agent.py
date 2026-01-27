"""Main coding agent orchestration."""

import asyncio
import os
import traceback
import uuid
from typing import Optional, List, Dict, Any, TYPE_CHECKING, Callable, Awaitable
from pathlib import Path

from src.observability import get_logger

if TYPE_CHECKING:
    from src.hooks import HookManager, HookDecision
    from src.core.protocol import UIProtocol

from src.memory import MemoryManager, TaskContext
from src.rag import CodeIndexer, Embedder, HybridRetriever, CodeChunk
from src.llm import LLMBackend, OllamaBackend, OpenAIBackend, LLMConfig, LLMBackendType
from src.llm.base import ProviderDelta
from src.llm.failure_handler import LLMError, RateLimitError, TimeoutError
from src.platform import safe_print, remove_emojis
from src.tools import (
    ToolExecutor,
    ToolNotFoundError,
    ToolExecutionError,
    ReadFileTool,
    WriteFileTool,
    EditFileTool,
    AppendToFileTool,
    ListDirectoryTool,
    RunCommandTool,
    SearchCodeTool,
    AnalyzeCodeTool,
    GrepTool,
    GlobTool,
    GetFileOutlineTool,
    GetSymbolContextTool,
    GitStatusTool,
    GitDiffTool,
    GitCommitTool,
    DelegateToSubagentTool,
    TodoWriteTool,
    CreateCheckpointTool,
    QueryComponentTool,
    QueryDependenciesTool,
    QueryDecisionsTool,
    QueryFlowsTool,
    QueryArchitectureSummaryTool,
    SearchComponentsTool,
    ClaritySetupTool,
    GetNextTaskTool,
    UpdateComponentStatusTool,
    AddArtifactTool,
    GetImplementationSpecTool,
    AddMethodTool,
    AddAcceptanceCriterionTool,
    UpdateMethodTool,
    UpdateAcceptanceCriterionTool,
    UpdateImplementationPatternTool,
    EnterPlanModeTool,
    ExitPlanModeTool,
)
from src.tools.tool_parser import ToolCallParser, ParsedResponse
from src.tools.tool_schemas import ALL_TOOLS
from src.prompts import PromptLibrary, TaskType
from .context_builder import ContextBuilder
from .file_reference_parser import FileReferenceParser
from .agent_interface import AgentInterface
from .error_recovery import ErrorRecoveryTracker
from .error_context import ErrorContext

# Permission mode (simplified - workflow system deprecated)
from src.core.permission_mode import PermissionManager, PermissionMode

# Plan mode (Claude Code-style planning workflow)
from src.core.plan_mode import PlanModeState, PlanGateDecision

# Subagent components
from src.subagents import SubAgentManager, SubAgentResult

# ClarAIty integration
try:
    from src.clarity.integration import ClarityAgentHook
    CLARITY_AVAILABLE = True
except ImportError:
    CLARITY_AVAILABLE = False
    ClarityAgentHook = None

# Observability integration (Langfuse v3 API + structured logging)
try:
    from src.observability import (
        observe_agent_method,
        observe_tool_execution,
        start_trace,
        update_trace,
        record_llm_latency,
        record_token_usage,
        record_tool_metric,
        # Structured logging
        bind_context,
        clear_context,
        new_request_id,
        get_logger,
        ErrorCategory,
    )
    OBSERVABILITY_AVAILABLE = True
except ImportError:
    OBSERVABILITY_AVAILABLE = False
    # No-op decorators if observability not available
    def observe_agent_method(name, **kwargs):
        def decorator(func):
            return func
        return decorator
    def observe_tool_execution(name, **kwargs):
        def decorator(func):
            return func
        return decorator
    def start_trace(*args, **kwargs):
        pass
    def update_trace(*args, **kwargs):
        pass
    def record_llm_latency(*args, **kwargs):
        pass
    def record_token_usage(*args, **kwargs):
        pass
    def record_tool_metric(*args, **kwargs):
        pass
    def bind_context(**kwargs):
        pass
    def clear_context():
        pass
    def new_request_id():
        return ''
    def get_logger(name=None):
        # Fallback when observability not available - use standard logging
        import logging
        return logging.getLogger(name or __name__)
    class ErrorCategory:
        PROVIDER_TIMEOUT = 'provider_timeout'
        PROVIDER_ERROR = 'provider_error'
        TOOL_TIMEOUT = 'tool_timeout'
        TOOL_ERROR = 'tool_error'
        UNEXPECTED = 'unexpected'


# Module-level logger for agent operations (use structlog if available)
logger = get_logger("core.agent")


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


class ToolExecutionResult:
    """
    Result from tool execution loop.

    Contains the exact ordered transcript of messages produced during the tool loop.
    This preserves:
    - Exact ordering (tool A before tool B)
    - Correct grouping (which tool result maps to which call)
    - Multi-iteration structure (assistant -> tool -> assistant -> tool -> ...)
    - Replay/debug determinism

    The turn_messages list contains OpenAI-format messages in exact order:
    - {"role": "assistant", "content": "...", "tool_calls": [...]}
    - {"role": "tool", "tool_call_id": "...", "name": "...", "content": "..."}
    - {"role": "assistant", "content": "final answer"}
    """

    def __init__(self, content: str, turn_messages: Optional[List[Dict[str, Any]]] = None):
        """
        Initialize tool execution result.

        Args:
            content: Final assistant content (convenience accessor)
            turn_messages: Exact ordered transcript of messages to persist
        """
        self.content = content
        self.turn_messages = turn_messages or []


class CodingAgent(AgentInterface):
    """
    Main AI coding agent that orchestrates all components.
    Optimized for small open-source LLMs.

    Implements AgentInterface to enable loose coupling with subsystems.
    """

    def __init__(
        self,
        model_name: str,
        backend: str,
        base_url: str,
        context_window: int,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        top_p: Optional[float] = None,
        working_directory: str = ".",
        api_key: Optional[str] = None,
        api_key_env: str = "OPENAI_API_KEY",
        embedding_model: Optional[str] = None,
        embedding_api_key: Optional[str] = None,
        embedding_api_key_env: str = "EMBEDDING_API_KEY",
        embedding_base_url: Optional[str] = None,
        load_file_memories: bool = True,
        permission_mode: str = "normal",
        hook_manager: Optional['HookManager'] = None,
        enable_clarity: bool = True,
    ):
        """
        Initialize coding agent.

        All configuration should come from .env file via CLI.

        Args:
            model_name: Name of the LLM model (required, from .env: LLM_MODEL)
            backend: Backend type (required, from .env: LLM_BACKEND)
            base_url: Base URL for LLM API (required, from .env: LLM_HOST)
            context_window: Context window size (required, from .env: MAX_CONTEXT_TOKENS)
            temperature: LLM temperature (from .env: LLM_TEMPERATURE)
            max_tokens: Max output tokens (from .env: LLM_MAX_TOKENS)
            top_p: Top-p sampling (from .env: LLM_TOP_P)
            working_directory: Working directory for file operations
            api_key: API key for OpenAI-compatible backends (optional)
            api_key_env: Environment variable name for API key (default: OPENAI_API_KEY)
            embedding_model: Name of the embedding model (from .env: EMBEDDING_MODEL)
            embedding_api_key: API key for embedding service (optional)
            embedding_api_key_env: Environment variable for embedding API key (default: EMBEDDING_API_KEY)
            embedding_base_url: Base URL for embedding API (from .env: EMBEDDING_BASE_URL)
            load_file_memories: Whether to load file-based memories on init (default: True)
            permission_mode: Permission mode (plan/normal/auto, default: normal)
            hook_manager: Optional hook manager for event hooks
            enable_clarity: Enable ClarAIty blueprint generation (default: True)
        """
        self.model_name = model_name
        self.backend_name = backend  # Store backend name for logging
        self.context_window = context_window
        self.working_directory = Path(working_directory)
        self.hook_manager = hook_manager

        # Store embedding configuration (no defaults, controlled by .env)
        self.embedding_model = embedding_model
        self.embedding_api_key = embedding_api_key
        self.embedding_api_key_env = embedding_api_key_env
        self.embedding_base_url = embedding_base_url

        # Initialize LLM backend
        # Read from .env if not provided
        import os
        llm_config = LLMConfig(
            backend_type=LLMBackendType(backend),
            model_name=model_name,
            base_url=base_url,
            context_window=context_window,
            num_ctx=context_window,
            temperature=temperature if temperature is not None else float(os.getenv("LLM_TEMPERATURE", "0.2")),
            max_tokens=max_tokens if max_tokens is not None else int(os.getenv("LLM_MAX_TOKENS", "16384")),
            top_p=top_p if top_p is not None else float(os.getenv("LLM_TOP_P", "0.95")),
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
            embedding_model=self.embedding_model,
            embedding_api_key=self.embedding_api_key,
            embedding_api_key_env=self.embedding_api_key_env,
            embedding_base_url=self.embedding_base_url,
            embedding_dimension=None,  # Will be read from .env inside SemanticMemory
            load_file_memories=load_file_memories,
            starting_directory=self.working_directory,
        )

        # Initialize RAG components (lazy loading)
        self.indexer: Optional[CodeIndexer] = None
        self.embedder: Optional[Embedder] = None
        self.retriever: Optional[HybridRetriever] = None
        self.indexed_chunks: List[CodeChunk] = []

        # Initialize todo state for task tracking (before tools registration)
        # Extended structure for task continuation support
        self.todo_state: Dict[str, Any] = {
            'todos': [],
            'current_todo_id': None,
            'last_stop_reason': None,
            '_next_id': 1,  # Internal counter for stable ID generation
        }

        # Per-turn flags (reset each user message)
        self._user_confirmed_reset = False
        self._pending_reset_confirmation = False

        # Initialize error recovery tracker (for intelligent retry behavior)
        # Uses defaults: max_same_tool_error_failures=4, max_total_failures=10
        self._error_tracker = ErrorRecoveryTracker()

        # Approval state tracking (for pause/approval precedence)
        self._awaiting_approval = False

        # Tool output size limit (parsed once, not on every tool call)
        self._max_tool_output_chars = int(os.getenv("TOOL_OUTPUT_MAX_CHARS", "100000"))

        # Initialize plan mode state (Claude Code-style planning workflow)
        # Must be initialized before tools registration since plan mode tools need it
        self.plan_mode_state = PlanModeState(
            clarity_dir=self.working_directory / ".clarity"
        )

        # Session ID for plan mode (will be set when session starts)
        self._session_id: Optional[str] = None

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
                logger.info("ClarAIty integration enabled")
            except Exception as e:
                logger.warning(f"Failed to initialize ClarAIty: {e}", exc_info=True)

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
                logger.warning(f"SessionStart hook error: {e}", exc_info=True)

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
            f"{'[OK] success' if result.success else '[FAIL] failed'} "
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

    def set_session_id(self, session_id: str, is_new_session: bool = True) -> None:
        """
        Set the session ID for plan mode and other session-scoped features.

        This should be called when a session is started or resumed.

        Args:
            session_id: The session ID
            is_new_session: If True, reset plan mode state (for new sessions).
                           If False, preserve existing state (for resumed sessions).
        """
        self._session_id = session_id

        # Reset plan mode state for new sessions to avoid stale state
        if is_new_session and hasattr(self, 'plan_mode_state'):
            self.plan_mode_state.reset()

        # Update the plan mode tool with the session ID
        if hasattr(self, '_enter_plan_mode_tool'):
            self._enter_plan_mode_tool.session_id = session_id

    def is_in_plan_mode(self) -> bool:
        """Check if currently in plan mode."""
        return self.plan_mode_state.is_active

    def _check_plan_mode_gate(
        self,
        tool_name: str,
        tool_args: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Check if a tool call is allowed under plan mode restrictions.

        Args:
            tool_name: Name of the tool being called
            tool_args: Arguments to the tool

        Returns:
            None if allowed, or a gated response dict if denied
        """
        # Extract target path from common argument names
        target_path = tool_args.get("file_path") or tool_args.get("path")

        decision = self.plan_mode_state.gate_tool(tool_name, target_path)

        if decision == PlanGateDecision.DENY:
            return {
                "status": "denied",
                "error_code": "PLAN_MODE_GATED",
                "message": f"Tool '{tool_name}' is not allowed in plan mode. Only read-only tools and writing to the plan file are permitted.",
                "plan_path": str(self.plan_mode_state.plan_file_path) if self.plan_mode_state.plan_file_path else None,
                "allowed_actions": [
                    "Use read-only tools (read_file, grep, glob, etc.)",
                    f"Write to plan file: {self.plan_mode_state.plan_file_path}",
                    "Call exit_plan_mode when ready for approval"
                ]
            }

        return None  # Allowed

    def _register_tools(self) -> None:
        """Register available tools."""
        # File operations
        self.tool_executor.register_tool(ReadFileTool())
        self.tool_executor.register_tool(WriteFileTool())
        self.tool_executor.register_tool(EditFileTool())
        self.tool_executor.register_tool(AppendToFileTool())
        self.tool_executor.register_tool(ListDirectoryTool())

        # Code operations
        self.tool_executor.register_tool(SearchCodeTool())
        self.tool_executor.register_tool(AnalyzeCodeTool())

        # Enhanced search tools (ripgrep-like)
        self.tool_executor.register_tool(GrepTool())
        self.tool_executor.register_tool(GlobTool())

        # LSP-based semantic code analysis
        self.tool_executor.register_tool(GetFileOutlineTool())
        self.tool_executor.register_tool(GetSymbolContextTool())

        # System operations
        self.tool_executor.register_tool(RunCommandTool())

        # Task management
        self.tool_executor.register_tool(TodoWriteTool(agent_state=self.todo_state))

        # Checkpoint tool (controller will be set later by CLI)
        self.tool_executor.register_tool(CreateCheckpointTool(controller=None))

        # Git operations
        self.tool_executor.register_tool(GitStatusTool())
        self.tool_executor.register_tool(GitDiffTool())
        self.tool_executor.register_tool(GitCommitTool())

        # ClarAIty architecture query tools
        self.tool_executor.register_tool(QueryComponentTool())
        self.tool_executor.register_tool(QueryDependenciesTool())
        self.tool_executor.register_tool(QueryDecisionsTool())
        self.tool_executor.register_tool(QueryFlowsTool())
        self.tool_executor.register_tool(QueryArchitectureSummaryTool())
        self.tool_executor.register_tool(SearchComponentsTool())
        self.tool_executor.register_tool(ClaritySetupTool())

        # ClarAIty workflow tools (task management)
        self.tool_executor.register_tool(GetNextTaskTool())
        self.tool_executor.register_tool(UpdateComponentStatusTool())
        self.tool_executor.register_tool(AddArtifactTool())

        # ClarAIty implementation spec tools
        self.tool_executor.register_tool(GetImplementationSpecTool())
        self.tool_executor.register_tool(AddMethodTool())
        self.tool_executor.register_tool(AddAcceptanceCriterionTool())
        self.tool_executor.register_tool(UpdateMethodTool())
        self.tool_executor.register_tool(UpdateAcceptanceCriterionTool())
        self.tool_executor.register_tool(UpdateImplementationPatternTool())

        # Testing & Validation tools
        from src.testing.validation_tool import RunTestsTool, DetectTestFrameworkTool
        self.tool_executor.register_tool(RunTestsTool())
        self.tool_executor.register_tool(DetectTestFrameworkTool())

        # Web tools (search and fetch)
        from src.tools.web_tools import WebSearchTool, WebFetchTool, RunBudget
        self._web_run_budget = RunBudget(max_searches=3, max_fetches=5)
        self._web_search_tool = WebSearchTool()
        self._web_fetch_tool = WebFetchTool()
        self._web_search_tool.set_run_budget(self._web_run_budget)
        self._web_fetch_tool.set_run_budget(self._web_run_budget)
        self.tool_executor.register_tool(self._web_search_tool)
        self.tool_executor.register_tool(self._web_fetch_tool)

        # Plan mode tools (Claude Code-style planning workflow)
        # Note: These tools need plan_mode_state and session_id set
        # They are registered here but the state is passed during execution
        self._enter_plan_mode_tool = EnterPlanModeTool(
            plan_mode_state=self.plan_mode_state,
            session_id=None  # Will be set when session starts
        )
        self._exit_plan_mode_tool = ExitPlanModeTool(
            plan_mode_state=self.plan_mode_state
        )
        self.tool_executor.register_tool(self._enter_plan_mode_tool)
        self.tool_executor.register_tool(self._exit_plan_mode_tool)

        # Subagent delegation (requires subagent_manager to be initialized)
        # This is registered after subagent_manager is initialized in __init__
        # Will be registered separately via _register_delegation_tool()

    @observe_agent_method("execute_with_tools", capture_input=False, capture_output=True)
    def _execute_with_tools(
        self,
        context: List[Dict[str, str]],
        max_iterations: int = 3,
        stream: bool = False,
        debug: bool = False,
        on_stream_start: Optional[Callable[[], None]] = None
    ) -> ToolExecutionResult:
        """
        Execute LLM with native function calling loop.

        Uses OpenAI-compatible function calling API for reliable tool execution.
        Tools are automatically synced from tool_schemas.py.

        Args:
            context: Initial conversation context
            max_iterations: Maximum tool calling iterations (prevent infinite loops)
            stream: Whether to stream responses
            debug: Whether to print debug information (default: False for production)
            on_stream_start: Optional callback invoked when streaming starts (for progress indicators)

        Returns:
            ToolExecutionResult with final content and ordered transcript of messages
        """
        iteration = 0
        current_context = context.copy()
        turn_messages = []  # Ordered transcript of messages to persist

        while iteration < max_iterations:
            iteration += 1
            if debug:
                print(f"\n[Tool Loop - Iteration {iteration}/{max_iterations}]")

            # Generate LLM response with native function calling
            if stream:
                # Use streaming mode - display chunks as they arrive
                response_content = ""
                tool_calls = None
                stream_started = False  # Track if callback was invoked

                for chunk, tc in self.llm.generate_with_tools_stream(
                    messages=current_context,
                    tools=ALL_TOOLS,
                    tool_choice="auto"
                ):
                    # Display content chunks as they arrive
                    if chunk.content and not chunk.done:
                        # Invoke on_stream_start callback once when first chunk arrives
                        if not stream_started and on_stream_start:
                            on_stream_start()
                            stream_started = True

                        # Strip emojis for Windows compatibility
                        from src.platform import remove_emojis
                        safe_content = remove_emojis(chunk.content)

                        # Print content to console
                        print(safe_content, end="", flush=True)
                        response_content += safe_content

                    # Stream complete - get tool calls
                    if chunk.done:
                        tool_calls = tc
                        if response_content:
                            print()  # New line after streaming completes

                # If only tool calls (no content), response_content may be empty
                if not response_content:
                    response_content = ""
            else:
                # Non-streaming mode - original behavior
                llm_response = self.llm.generate_with_tools(
                    messages=current_context,
                    tools=ALL_TOOLS,
                    tool_choice="auto"  # Let LLM decide whether to use tools
                )

                response_content = llm_response.content or ""  # May be None if tool-only response
                tool_calls = llm_response.tool_calls

                # AUTO-RECOVERY: Check for truncation (non-streaming only)
                if hasattr(llm_response, 'raw_response') and isinstance(llm_response.raw_response, dict):
                    truncation_info = llm_response.raw_response.get('truncation_info', {})
                    if truncation_info.get('truncated'):
                        if debug:
                            print(f"[AUTO-RECOVERY] Detected truncation, generating continuation...")

                        # Add continuation prompt
                        continuation_context = current_context.copy()
                        continuation_context.append({
                            "role": "assistant",
                            "content": response_content
                        })
                        continuation_context.append({
                            "role": "user",
                            "content": "Your previous response was truncated due to token limits. Please continue from where you left off. Use append_to_file if you were creating a large file."
                        })

                        # Generate continuation
                        continuation_response = self.llm.generate_with_tools(
                            messages=continuation_context,
                            tools=ALL_TOOLS,
                            tool_choice="auto"
                        )
                        response_content = response_content + "\n\n" + (continuation_response.content or "")
                        # Merge tool calls from continuation
                        if continuation_response.tool_calls:
                            tool_calls = (tool_calls or []) + continuation_response.tool_calls

                        if debug:
                            print(f"[AUTO-RECOVERY] Successfully generated continuation")

            if debug:
                print(f"LLM Response: {response_content[:200] if response_content else '(tool-only response)'}...")

            # Check if there are tool calls
            if not tool_calls:
                # No tool calls - we're done
                if debug:
                    print("[Tool Loop] No tool calls detected - finishing")
                # Add final assistant message to transcript (no tool_calls)
                final_content = response_content if response_content else "Task completed."
                turn_messages.append({
                    "role": "assistant",
                    "content": final_content
                })
                return ToolExecutionResult(content=final_content, turn_messages=turn_messages)

            # Execute tool calls
            if debug:
                print(f"[Tool Loop] Found {len(tool_calls)} tool call(s)")

            tool_results = []
            tool_messages = []  # For function calling API format

            for i, tool_call in enumerate(tool_calls, 1):
                tool_name = tool_call.function.name
                tool_args = tool_call.function.get_parsed_arguments()

                # Print tool announcement (clean format for CLI)
                self._print_tool_announcement(tool_name, tool_args)

                if debug:
                    print(f"  Arguments: {tool_args}")

                # Check plan mode gating BEFORE approval and execution
                plan_gate_result = self._check_plan_mode_gate(tool_name, tool_args)
                if plan_gate_result is not None:
                    # Tool is gated in plan mode
                    if debug:
                        print(f"  [GATED] {plan_gate_result['message']}")

                    # Return gated response to LLM
                    import json
                    gated_output = json.dumps(plan_gate_result, indent=2)
                    tool_result = {
                        "tool": tool_name,
                        "arguments": tool_args,
                        "success": False,
                        "error": plan_gate_result["message"]
                    }
                    tool_results.append(tool_result)
                    tool_messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_name,
                        "content": gated_output
                    })
                    self.tool_execution_history.append(tool_result)
                    continue  # Skip to next tool call

                # Check if approval is required (NORMAL mode only)
                if self.permission_manager and self.permission_manager.mode == PermissionMode.NORMAL:
                    # Only ask for risky operations
                    risky_tools = ['write_file', 'edit_file', 'append_to_file', 'run_command', 'git_commit']

                    if tool_name in risky_tools:
                        approved = self._prompt_tool_approval(tool_name, tool_args)

                        if not approved:
                            # User rejected - stop execution immediately (Claude Code behavior)
                            # Don't send to LLM, just return and wait for user's next message
                            if debug:
                                print(f"  [CANCEL] User rejected operation - stopping execution")

                            # Return immediately - conversation stops, waiting for user input
                            # Persist any messages accumulated so far (partial transcript)
                            return ToolExecutionResult(content="", turn_messages=turn_messages)

                try:
                    # Execute the tool
                    result = self.tool_executor.execute_tool(
                        tool_name,
                        **tool_args
                    )

                    if result.is_success():
                        output = result.output
                        # Check for oversized outputs - return error with guidance instead of silent truncation
                        if isinstance(output, str) and len(output) > self._max_tool_output_chars:
                            error_msg, tool_msg, history = self._format_oversized_output_error(
                                len(output), tool_name, tool_args, tool_call.id
                            )
                            tool_results.append(history)
                            tool_messages.append(tool_msg)
                            self.tool_execution_history.append(history)
                            if debug:
                                print(f"  [LIMIT] Output too large: {len(output):,} chars")
                            continue  # Skip to next tool call

                        tool_result = {
                            "tool": tool_name,
                            "arguments": tool_args,
                            "success": True,
                            "result": output
                        }
                        tool_results.append(tool_result)

                        # Format for function calling API
                        tool_messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_name,
                            "content": str(output)
                        })

                        # Track in history for validation/testing
                        self.tool_execution_history.append(tool_result)

                        if debug:
                            print(f"  [OK] Success: {str(output)[:100]}...")
                    else:
                        tool_result = {
                            "tool": tool_name,
                            "arguments": tool_args,
                            "success": False,
                            "error": result.error
                        }
                        tool_results.append(tool_result)

                        # Format error for function calling API
                        tool_messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_name,
                            "content": f"Error: {result.error}"
                        })

                        # Track in history for validation/testing
                        self.tool_execution_history.append(tool_result)

                        if debug:
                            print(f"  [FAIL] Error: {result.error}")

                except Exception as e:
                    tool_result = {
                        "tool": tool_name,
                        "arguments": tool_args,
                        "success": False,
                        "error": str(e)
                    }
                    tool_results.append(tool_result)

                    # Format exception for function calling API
                    tool_messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_name,
                        "content": f"Exception: {str(e)}"
                    })

                    # Track in history for validation/testing
                    self.tool_execution_history.append(tool_result)

                    if debug:
                        print(f"  [FAIL] Exception: {e}")

            # Build assistant message with tool_calls
            import json
            assistant_msg = {
                "role": "assistant",
                "content": response_content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments  # Already JSON string
                        }
                    }
                    for tc in tool_calls
                ]
            }

            # Add to transcript (for persistence) and context (for LLM)
            turn_messages.append(assistant_msg)
            current_context.append(assistant_msg)

            # Add tool results to transcript and context
            turn_messages.extend(tool_messages)
            current_context.extend(tool_messages)

        # Max iterations reached - generate final summary
        if debug:
            print(f"\n[Tool Loop] Max iterations ({max_iterations}) reached - generating final summary")

        # Ask LLM to summarize what was learned
        current_context.append({
            "role": "user",
            "content": "You've reached the maximum number of tool iterations. Based on the information you've gathered from the tools, please provide a clear, concise answer to the original user question."
        })

        # Generate final summary (no tools this time, just text)
        final_response = self.llm.generate_with_tools(
            messages=current_context,
            tools=ALL_TOOLS,
            tool_choice="none"  # Force text response only
        )
        final_content = final_response.content or "Task completed based on tool results."
        # Add final assistant message to transcript
        turn_messages.append({
            "role": "assistant",
            "content": final_content
        })
        return ToolExecutionResult(content=final_content, turn_messages=turn_messages)

    async def _execute_with_tools_async(
        self,
        context: List[Dict[str, str]],
        max_iterations: int = 3,
        on_chunk: Optional[Callable[[str], Awaitable[None]]] = None,
        request_approval: Optional[Callable[[str, Dict[str, Any]], Awaitable[bool]]] = None,
        ui_protocol: Optional['UIProtocol'] = None,
    ) -> ToolExecutionResult:
        """
        Execute LLM with native function calling loop (async version).

        This is the async version for use with the TUI, allowing non-blocking
        streaming and tool execution.

        Args:
            context: Initial conversation context
            max_iterations: Maximum tool calling iterations
            on_chunk: Async callback for each content chunk (for UI updates)
            request_approval: Async callback for requesting user approval (TUI-native)

        Returns:
            ToolExecutionResult with final content and ordered transcript of messages
        """
        import json

        iteration = 0
        current_context = context.copy()
        turn_messages = []  # Ordered transcript of messages to persist

        while iteration < max_iterations:
            iteration += 1

            # Generate LLM response with async streaming
            response_content = ""
            tool_calls = None

            async for chunk, tc in self.llm.generate_with_tools_stream_async(
                messages=current_context,
                tools=ALL_TOOLS,
                tool_choice="auto"
            ):
                # Handle content chunks
                if chunk.content and not chunk.done:
                    # Strip emojis for Windows compatibility
                    from src.platform import remove_emojis
                    safe_content = remove_emojis(chunk.content)

                    # Call the on_chunk callback if provided (for UI updates)
                    if on_chunk:
                        await on_chunk(safe_content)

                    response_content += safe_content

                # Stream complete - get tool calls
                if chunk.done:
                    tool_calls = tc

            # Check if there are tool calls
            if not tool_calls:
                # Add final assistant message to transcript (no tool_calls)
                final_content = response_content if response_content else "Task completed."
                turn_messages.append({
                    "role": "assistant",
                    "content": final_content
                })
                return ToolExecutionResult(content=final_content, turn_messages=turn_messages)

            # Execute tool calls asynchronously
            tool_messages = []

            for tool_call in tool_calls:
                tool_name = tool_call.function.name
                tool_args = tool_call.function.get_parsed_arguments()

                # Special handling for clarify tool (requires UI interaction)
                if tool_name == "clarify":
                    clarify_result = await self._handle_clarify_tool(
                        tool_call.id,
                        tool_args,
                        ui_protocol
                    )
                    tool_messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_name,
                        "content": json.dumps(clarify_result)
                    })
                    self.tool_execution_history.append({
                        "tool": tool_name,
                        "arguments": tool_args,
                        "success": True,
                        "result": clarify_result
                    })
                    continue  # Skip to next tool call

                # Check plan mode gating BEFORE approval and execution
                plan_gate_result = self._check_plan_mode_gate(tool_name, tool_args)
                if plan_gate_result is not None:
                    # Tool is gated in plan mode
                    gated_output = json.dumps(plan_gate_result, indent=2)
                    tool_messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_name,
                        "content": gated_output
                    })
                    self.tool_execution_history.append({
                        "tool": tool_name,
                        "arguments": tool_args,
                        "success": False,
                        "error": plan_gate_result["message"]
                    })
                    continue  # Skip to next tool call

                # Check if approval is required (NORMAL mode)
                if self.permission_manager and self.permission_manager.mode == PermissionMode.NORMAL:
                    risky_tools = ['write_file', 'edit_file', 'append_to_file', 'run_command', 'git_commit']

                    if tool_name in risky_tools:
                        if request_approval:
                            # Use TUI-native approval (non-blocking, UI stays responsive)
                            approved = await request_approval(tool_name, tool_args)
                        else:
                            # Fallback to sync approval (blocks UI - legacy)
                            approved = self._prompt_tool_approval(tool_name, tool_args)

                        if not approved:
                            # Persist any messages accumulated so far (partial transcript)
                            return ToolExecutionResult(content="", turn_messages=turn_messages)

                try:
                    # Execute tool asynchronously (doesn't block event loop)
                    result = await self.tool_executor.execute_tool_async(
                        tool_name,
                        **tool_args
                    )

                    if result.is_success():
                        output = result.output
                        # Check for oversized outputs - return error with guidance instead of silent truncation
                        if isinstance(output, str) and len(output) > self._max_tool_output_chars:
                            _, tool_msg, history = self._format_oversized_output_error(
                                len(output), tool_name, tool_args, tool_call.id
                            )
                            tool_messages.append(tool_msg)
                            self.tool_execution_history.append(history)
                            continue  # Skip to next tool call

                        tool_messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_name,
                            "content": str(output)
                        })

                        # Track in history
                        self.tool_execution_history.append({
                            "tool": tool_name,
                            "arguments": tool_args,
                            "success": True,
                            "result": output
                        })
                    else:
                        tool_messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_name,
                            "content": f"Error: {result.error}"
                        })

                        self.tool_execution_history.append({
                            "tool": tool_name,
                            "arguments": tool_args,
                            "success": False,
                            "error": result.error
                        })

                except Exception as e:
                    tool_messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_name,
                        "content": f"Exception: {str(e)}"
                    })

                    self.tool_execution_history.append({
                        "tool": tool_name,
                        "arguments": tool_args,
                        "success": False,
                        "error": str(e)
                    })

            # Build assistant message with tool_calls
            assistant_msg = {
                "role": "assistant",
                "content": response_content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments  # Already JSON string
                        }
                    }
                    for tc in tool_calls
                ]
            }

            # Add to transcript (for persistence) and context (for LLM)
            turn_messages.append(assistant_msg)
            current_context.append(assistant_msg)

            # Add tool results to transcript and context
            turn_messages.extend(tool_messages)
            current_context.extend(tool_messages)

        # Max iterations reached - generate final summary
        current_context.append({
            "role": "user",
            "content": "You've reached the maximum number of tool iterations. Please provide a clear, concise answer."
        })

        final_response = self.llm.generate_with_tools(
            messages=current_context,
            tools=ALL_TOOLS,
            tool_choice="none"
        )
        final_content = final_response.content or "Task completed based on tool results."
        # Add final assistant message to transcript
        turn_messages.append({
            "role": "assistant",
            "content": final_content
        })
        return ToolExecutionResult(content=final_content, turn_messages=turn_messages)

    def _fix_orphaned_tool_calls(self, context: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Fix tool_call/tool_result ordering to satisfy Claude API requirements.

        Claude API requires:
        1. Every tool_use must have a corresponding tool_result
        2. tool_result must come IMMEDIATELY AFTER the assistant message with tool_use

        This method:
        1. Detects orphaned tool_calls (missing tool_result) and creates synthetic ones
        2. Reorders ALL tool_results to be immediately after their assistant messages

        The reordering is critical because when context is rebuilt from MessageStore,
        tool_results may have later seq numbers and appear in wrong positions.

        Args:
            context: The conversation context (list of messages)

        Returns:
            The context with proper tool_call/tool_result ordering
        """
        from src.core.tool_status import ToolStatus as CoreToolStatus
        from src.observability import get_logger
        logger = get_logger("agent")

        logger.debug(f"[ORPHAN_CHECK] Scanning context with {len(context)} messages")

        # Collect all tool_call_ids from assistant messages
        tool_call_ids_needed = set()
        tool_call_info = {}  # tool_call_id -> (tool_name, index in context)

        for i, msg in enumerate(context):
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    tc_id = tc.get("id")
                    tc_name = tc.get("function", {}).get("name", "unknown")
                    if tc_id:
                        tool_call_ids_needed.add(tc_id)
                        tool_call_info[tc_id] = (tc_name, i)

        # Collect all existing tool_results (by tool_call_id -> message)
        existing_tool_results = {}
        for msg in context:
            if msg.get("role") == "tool":
                tc_id = msg.get("tool_call_id")
                if tc_id:
                    existing_tool_results[tc_id] = msg

        # Find orphans (tool_calls without tool_results)
        orphaned_ids = tool_call_ids_needed - set(existing_tool_results.keys())

        logger.debug(
            f"[ORPHAN_CHECK] tool_calls_needed: {list(tool_call_ids_needed)}, "
            f"tool_results_found: {list(existing_tool_results.keys())}, "
            f"orphans: {list(orphaned_ids)}"
        )

        # Create synthetic tool_results for orphans
        for tc_id in orphaned_ids:
            tc_name, _ = tool_call_info.get(tc_id, ("unknown", -1))
            synthetic_msg = {
                "role": "tool",
                "tool_call_id": tc_id,
                "name": tc_name,
                "content": "Tool call rejected by user."
            }
            existing_tool_results[tc_id] = synthetic_msg

            logger.debug(f"[ORPHAN_FIX] Created synthetic tool_result for orphan: {tc_id}")

            # Persist to MessageStore so this fix is permanent
            persisted_msg = self.memory.add_tool_result(
                tool_call_id=tc_id,
                content=synthetic_msg["content"],
                tool_name=tc_name,
                status="interrupted",
            )
            if persisted_msg:
                logger.debug(
                    f"[ORPHAN_FIX] Persisted synthetic tool_result: "
                    f"uuid={persisted_msg.uuid}, seq={persisted_msg.seq}, "
                    f"tool_call_id={tc_id}"
                )
            else:
                logger.error(
                    f"[ORPHAN_FIX] FAILED to persist synthetic tool_result for {tc_id}! "
                    "MessageStore may not be configured."
                )

            # Update tool_state if message_store exists
            if self.memory.message_store:
                self.memory.message_store.update_tool_state(
                    tc_id,
                    CoreToolStatus.ERROR  # Mark as error since it was interrupted
                )

        # CRITICAL: Rebuild context with tool_results in correct positions
        # Tool_results MUST come immediately after their assistant messages
        # This handles both orphans AND mispositioned existing tool_results
        result_context = []
        tool_results_placed = set()

        for msg in context:
            # Skip tool messages - we'll insert them in the correct position
            if msg.get("role") == "tool":
                continue

            result_context.append(msg)

            # After each assistant message with tool_calls, insert ALL its tool_results
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    tc_id = tc.get("id")
                    if tc_id and tc_id in existing_tool_results:
                        result_context.append(existing_tool_results[tc_id])
                        tool_results_placed.add(tc_id)

        # Log reordering
        if tool_call_ids_needed:
            logger.debug(
                f"[ORPHAN_FIX] Rebuilt context: {len(tool_results_placed)} tool_results "
                f"placed immediately after their assistant messages"
            )

        return result_context

    def _prompt_tool_approval(self, tool_name: str, tool_args: Dict[str, Any]) -> bool:
        """
        Prompt user for approval before executing a tool.

        This is called AFTER the diff has been displayed in streaming mode,
        so the user has already seen what will be changed.

        Args:
            tool_name: Name of the tool to execute
            tool_args: Tool arguments

        Returns:
            True if approved, False if rejected
        """
        from pathlib import Path

        # Create operation description
        if tool_name == 'write_file':
            file_path = tool_args.get('file_path', 'unknown')
            operation = f"Write file: {Path(file_path).name}"

        elif tool_name == 'edit_file':
            file_path = tool_args.get('file_path', 'unknown')
            operation = f"Edit file: {Path(file_path).name}"

        elif tool_name == 'append_to_file':
            file_path = tool_args.get('file_path', 'unknown')
            operation = f"Append to file: {Path(file_path).name}"

        elif tool_name == 'run_command':
            command = tool_args.get('command', 'unknown')
            if len(command) > 50:
                command = command[:50] + '...'
            operation = f"Run command: {command}"

        elif tool_name == 'git_commit':
            message = tool_args.get('message', 'unknown')
            if len(message) > 50:
                message = message[:50] + '...'
            operation = f"Git commit: {message}"

        else:
            operation = f"{tool_name} operation"

        # Show approval prompt (simple, Claude Code style)
        safe_print("\n" + "-" * 60)
        safe_print(f"[APPROVAL] {operation}")
        safe_print("-" * 60)
        safe_print("Approve this change? (yes/no): ", end="", flush=True)

        try:
            response = input().strip().lower()
            approved = response in ["yes", "y"]

            if approved:
                safe_print("[OK] Approved - executing...\n")
            else:
                safe_print("[CANCEL] Rejected - operation cancelled\n")

            return approved

        except (EOFError, KeyboardInterrupt):
            safe_print("\n[CANCEL] Interrupted - operation cancelled\n")
            return False

    async def _handle_clarify_tool(
        self,
        call_id: str,
        tool_args: Dict[str, Any],
        ui_protocol: Optional['UIProtocol'] = None,
    ) -> Dict[str, Any]:
        """
        Handle the clarify tool - ask structured questions before proceeding.

        Single-writer flow:
        1. Validate questions
        2. Persist clarify_request via MemoryManager (triggers TUI notification)
        3. Wait for user response via UIProtocol (or CLI fallback)
        4. Persist clarify_response via MemoryManager
        5. Return result to LLM

        Args:
            call_id: Tool call ID for correlation
            tool_args: Tool arguments (questions, context)
            ui_protocol: Optional UIProtocol for TUI mode

        Returns:
            Dict with user responses or error/cancellation status
        """
        questions = tool_args.get("questions", [])
        context = tool_args.get("context")

        # Validate questions
        if not questions:
            return {"error": "clarify.questions is empty"}

        if len(questions) > 4:
            return {"error": "clarify.questions has more than 4 questions (max: 4)"}

        # 1. Persist clarify_request via MemoryManager (SINGLE WRITER)
        if self.memory.has_message_store:
            self.memory.persist_system_event(
                event_type="clarify_request",
                content="[Clarification requested]",
                extra={
                    "call_id": call_id,
                    "questions": questions,
                    "context": context,
                },
                include_in_llm_context=False,
            )

        # 2. Wait for user response
        if ui_protocol:
            # TUI mode - use UIProtocol
            try:
                from src.core.protocol import ClarifyResult
                result = await ui_protocol.wait_for_clarify_response(call_id)

                # 3. Persist clarify_response via MemoryManager (SINGLE WRITER)
                if self.memory.has_message_store:
                    status = "submitted" if result.submitted else ("chat" if result.chat_instead else "cancelled")
                    self.memory.persist_system_event(
                        event_type="clarify_response",
                        content=f"[Clarification {status}]",
                        extra={
                            "call_id": call_id,
                            "submitted": result.submitted,
                            "responses": result.responses,
                            "chat_instead": result.chat_instead,
                            "chat_message": result.chat_message,
                        },
                        include_in_llm_context=False,
                    )

                # 4. Return result to LLM
                if result.submitted:
                    return {"submitted": True, "responses": result.responses}
                if result.chat_instead:
                    return {"mode": "chat", "message": result.chat_message}
                return {"cancelled": True}

            except asyncio.CancelledError:
                return {"cancelled": True, "reason": "interrupted"}

        else:
            # CLI fallback
            from src.tools.clarify_tool import ClarifyTool
            clarify_tool = ClarifyTool()
            result = clarify_tool._cli_prompt(questions, context)

            # Persist response via MemoryManager
            if self.memory.has_message_store:
                submitted = result.get("submitted", False)
                cancelled = result.get("cancelled", False)
                status = "submitted" if submitted else "cancelled"
                self.memory.persist_system_event(
                    event_type="clarify_response",
                    content=f"[Clarification {status}]",
                    extra={
                        "call_id": call_id,
                        "submitted": submitted,
                        "responses": result.get("responses"),
                        "chat_instead": False,
                        "chat_message": None,
                    },
                    include_in_llm_context=False,
                )

            return result

    def _print_tool_announcement(self, tool_name: str, tool_args: Dict[str, Any]) -> None:
        """
        Print a clean tool announcement for CLI output.

        Shows what tool is being called with key context (file path, command, etc.)
        without verbose JSON dumps.

        Args:
            tool_name: Name of the tool being called
            tool_args: Tool arguments dictionary
        """
        from pathlib import Path

        # Format based on tool type
        if tool_name == 'read_file':
            file_path = tool_args.get('file_path', '')
            safe_print(f"\n[READ] {Path(file_path).name}")

        elif tool_name == 'write_file':
            file_path = tool_args.get('file_path', '')
            safe_print(f"\n[WRITE] {Path(file_path).name}")

        elif tool_name == 'edit_file':
            file_path = tool_args.get('file_path', '')
            safe_print(f"\n[EDIT] {Path(file_path).name}")

        elif tool_name == 'append_to_file':
            file_path = tool_args.get('file_path', '')
            safe_print(f"\n[APPEND] {Path(file_path).name}")

        elif tool_name == 'list_directory':
            path = tool_args.get('path', '.')
            safe_print(f"\n[LIST] {path}")

        elif tool_name == 'run_command':
            command = tool_args.get('command', '')
            # Truncate long commands
            if len(command) > 60:
                command = command[:60] + '...'
            safe_print(f"\n[RUN] {command}")

        elif tool_name == 'search_code':
            pattern = tool_args.get('pattern', '')
            safe_print(f"\n[SEARCH] {pattern}")

        elif tool_name == 'git_status':
            safe_print("\n[GIT] status")

        elif tool_name == 'git_diff':
            safe_print("\n[GIT] diff")

        elif tool_name == 'git_commit':
            message = tool_args.get('message', '')
            if len(message) > 50:
                message = message[:50] + '...'
            safe_print(f"\n[GIT] commit: {message}")

        elif tool_name == 'todo_write':
            todos = tool_args.get('todos', [])
            safe_print(f"\n[TODO] Updating {len(todos)} items")

        elif tool_name == 'delegate_to_subagent':
            subagent = tool_args.get('subagent', 'unknown')
            safe_print(f"\n[DELEGATE] {subagent}")

        else:
            # Generic announcement for other tools
            safe_print(f"\n[TOOL] {tool_name}")

    @observe_agent_method("execute_direct", capture_input=True, capture_output=True)
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

        # Build context (with agent state for task continuation)
        # MemoryManager uses MessageStore when configured (Option A: Single Source of Truth)
        context = self.context_builder.build_context(
            user_query=task_description,
            task_type=task_type,
            language=language,
            use_rag=use_rag and len(self.indexed_chunks) > 0,
            available_chunks=self.indexed_chunks if use_rag else None,
            file_references=file_references if file_references else None,
            agent_state=self.todo_state if self.todo_state.get('todos') else None,
            plan_mode_state=self.plan_mode_state,
        )

        # Execute with tool calling loop
        execution_result = self._execute_with_tools(
            context=context,
            max_iterations=3,
            stream=stream,
            debug=False  # Production mode - hide debug output
        )

        # Persist the ordered transcript to working memory
        from src.memory.models import MessageRole
        for msg in execution_result.turn_messages:
            if msg["role"] == "assistant":
                self.memory.working_memory.add_message(
                    role=MessageRole.ASSISTANT,
                    content=msg.get("content", ""),
                    metadata={"tool_calls": msg.get("tool_calls")} if msg.get("tool_calls") else None
                )
            elif msg["role"] == "tool":
                self.memory.working_memory.add_message(
                    role=MessageRole.TOOL,
                    content=msg.get("content", ""),
                    metadata={
                        "tool_call_id": msg.get("tool_call_id"),
                        "name": msg.get("name")
                    }
                )

        return execution_result.content

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
        self.embedder = Embedder(
            model_name=self.embedding_model,
            api_key=self.embedding_api_key,
            api_key_env=self.embedding_api_key_env,
            base_url=self.embedding_base_url,
        )

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

    @observe_agent_method("execute_task", capture_input=True, capture_output=True)
    def execute_task(
        self,
        task_description: str,
        task_type: str = "implement",
        language: str = "python",
        use_rag: bool = True,
        stream: bool = False,
    ) -> AgentResponse:
        """
        Execute a coding task using direct LLM execution.

        Args:
            task_description: Description of the task
            task_type: Type of task (implement, debug, refactor, etc.)
            language: Programming language
            use_rag: Whether to use RAG retrieval
            stream: Whether to stream response

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
                logger.warning(f"UserPromptSubmit hook error: {e}", exc_info=True)

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
                    logger.info(
                        f"Blueprint approved: {len(clarity_result.blueprint.components)} components"
                    )

            except Exception as e:
                # ClarAIty errors shouldn't break the agent
                logger.warning(f"ClarAIty hook error: {e}", exc_info=True)

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

        # Execute using direct LLM-first approach (LLM decides tools vs conversation)
        print("\n[DIRECT EXECUTION MODE]\n")
        response_content = self._execute_direct(
            task_description=task_description,
            task_type=task_type,
            language=language,
            use_rag=use_rag,
            stream=stream,
        )

        # Add assistant response to memory
        self.memory.add_assistant_message(response_content)

        return AgentResponse(
            content=response_content,
            metadata={
                "task_type": task_type,
                "language": language,
                "used_rag": use_rag and len(self.indexed_chunks) > 0,
                "execution_mode": "direct",
            }
        )

    @observe_agent_method("chat", capture_input=True, capture_output=True)
    def chat(
        self,
        message: str,
        stream: bool = True,
        use_rag: bool = True,
        on_stream_start: Optional[Callable[[], None]] = None
    ) -> AgentResponse:
        """
        Interactive chat with the agent using LLM-first decision making.

        The LLM autonomously decides whether to:
        - Respond conversationally (greetings, acknowledgments)
        - Use tools directly (simple coding tasks)
        - Create an execution plan (complex multi-step tasks)

        This follows industry best practice (OpenAI tool_choice="auto", Claude Code pattern)
        where the LLM makes decisions, not application routing logic.

        Args:
            message: User message
            stream: Whether to stream response
            use_rag: Whether to use RAG retrieval (default: True)
            on_stream_start: Optional callback invoked when streaming starts (for progress indicators)

        Returns:
            Agent response
        """
        # USER PROMPT SUBMIT HOOK
        if self.hook_manager:
            try:
                from src.hooks import HookContinue

                decision, modified_prompt = self.hook_manager.emit_user_prompt_submit(
                    prompt=message,
                    metadata={
                        "stream": stream,
                        "use_rag": use_rag
                    }
                )

                if decision == HookContinue.BLOCK:
                    return AgentResponse(
                        content="Prompt blocked by hook",
                        metadata={"blocked": True}
                    )

                # Use modified prompt if hook modified it
                message = modified_prompt

            except Exception as e:
                # Check if it's a HookBlockedError
                if e.__class__.__name__ == 'HookBlockedError':
                    return AgentResponse(
                        content=f"Prompt blocked by hook: {str(e)}",
                        metadata={"blocked": True}
                    )
                # Other errors, log and continue
                logger.warning(f"UserPromptSubmit hook error: {e}", exc_info=True)

        # Reset web tools budget for new turn
        if hasattr(self, '_web_run_budget') and self._web_run_budget:
            self._web_run_budget.reset()

        # Create task context (generic for chat)
        task_context = TaskContext(
            task_id=str(uuid.uuid4()),
            description=message,
            task_type="chat",  # Generic type for chat messages
            key_concepts=[],
        )

        self.memory.set_task_context(task_context)

        # Add user message to memory
        self.memory.add_user_message(message)

        # Parse and load file references from message
        file_references = self.file_reference_parser.parse_and_load(message)

        # Display loaded files to user
        if file_references:
            summary = self.file_reference_parser.format_summary(file_references)
            print(f"\n{summary}\n")

        # Build context with enhanced system prompt for decision-making
        # Include agent state for task continuation support
        # MemoryManager uses MessageStore when configured (Option A: Single Source of Truth)
        context = self.context_builder.build_context(
            user_query=message,
            task_type="chat",
            language="python",  # Default, LLM can handle any language
            use_rag=use_rag and len(self.indexed_chunks) > 0,
            available_chunks=self.indexed_chunks if use_rag else None,
            file_references=file_references if file_references else None,
            agent_state=self.todo_state if self.todo_state.get('todos') else None,
            plan_mode_state=self.plan_mode_state,
        )

        # Execute with tool calling loop (LLM decides what to do)
        import os
        debug_mode = os.getenv("DEBUG_MODE", "false").lower() == "true"
        execution_result = self._execute_with_tools(
            context=context,
            max_iterations=10,  # Increased for complex tasks
            stream=stream,
            debug=debug_mode,  # Controlled by .env DEBUG_MODE
            on_stream_start=on_stream_start  # Progress indicator callback
        )

        # Persist the ordered transcript to working memory
        # This preserves: assistant(tool_calls) -> tool(result) -> assistant(final)
        from src.memory.models import MessageRole
        for msg in execution_result.turn_messages:
            if msg["role"] == "assistant":
                # Assistant message (may have tool_calls in metadata)
                self.memory.working_memory.add_message(
                    role=MessageRole.ASSISTANT,
                    content=msg.get("content", ""),
                    metadata={"tool_calls": msg.get("tool_calls")} if msg.get("tool_calls") else None
                )
            elif msg["role"] == "tool":
                # Tool result message
                self.memory.working_memory.add_message(
                    role=MessageRole.TOOL,
                    content=msg.get("content", ""),
                    metadata={
                        "tool_call_id": msg.get("tool_call_id"),
                        "name": msg.get("name")
                    }
                )

        response_content = execution_result.content
        return AgentResponse(
            content=response_content,
            metadata={
                "execution_mode": "llm_first",
                "used_rag": use_rag and len(self.indexed_chunks) > 0,
            }
        )

    async def stream_response(
        self,
        user_input: str,
        ui: 'UIProtocol',
        attachments: 'Optional[List]' = None,
    ) -> 'AsyncIterator[UIEvent]':
        """
        Stream response to UI as typed UIEvent objects.

        This is the main integration point between the agent and Textual TUI.
        Transforms LLM streaming output into typed events for the UI.

        Args:
            user_input: User message
            ui: UIProtocol for bidirectional communication (approvals, interrupts)
            attachments: Optional list of Attachment objects (images, text files)

        Yields:
            UIEvent instances (StreamStart, TextDelta, ToolCallStart, etc.)
        """
        from typing import AsyncIterator, Optional, List
        from src.core.events import (
            UIEvent, StreamStart, StreamEnd, TextDelta,
            PausePromptStart, PausePromptEnd, ContextUpdated, ContextCompacted,
        )
        from src.core.tool_status import ToolStatus as CoreToolStatus
        from src.core.render_meta import ToolApprovalMeta
        from src.tools.tool_schemas import ALL_TOOLS
        import json
        import time

        # Bind context for logging correlation
        stream_id = str(uuid.uuid4())[:8]
        bind_context(
            session=self.memory.session_id if hasattr(self.memory, 'session_id') else None,
            stream=stream_id,
            request=new_request_id(),
            comp='core.agent',
            op='stream_response',
        )

        # Yield StreamStart to signal beginning of response
        yield StreamStart()

        # Reset error tracker at start of each user request
        # (NOT in tool loop - that would reset mid-request)
        self._error_tracker.reset()

        # Check for reset intent at start of each user request
        is_reset, needs_confirm = self._check_reset_intent(user_input)
        if is_reset and needs_confirm and self._has_incomplete_todos():
            # Loose reset language - needs confirmation
            self._pending_reset_confirmation = True
            self._user_confirmed_reset = False
        else:
            self._user_confirmed_reset = is_reset
            self._pending_reset_confirmation = False

        # Track blocked calls for controller constraint injection
        blocked_calls: List[str] = []

        # Safety limit for iterations (emergency brake only)
        # Primary limits are: MAX_TOOL_CALLS (60) and MAX_WALL_TIME_SECONDS (90)
        # Definition: 1 iteration = 1 LLM call cycle (can produce 0-5+ tool calls)
        ABSOLUTE_MAX_ITERATIONS = 50

        # Helper to check if tool needs approval based on permission mode
        def needs_approval(tool_name: str) -> bool:
            # Get current permission mode
            mode = self.permission_manager.get_mode() if self.permission_manager else PermissionMode.NORMAL

            # In AUTO mode, never ask for approval
            if mode == PermissionMode.AUTO:
                return False

            # In PLAN mode, don't ask for approval - use gating instead
            # Read-only tools execute freely, write tools are blocked by plan_mode_state.gate_tool()
            if mode == PermissionMode.PLAN:
                return False

            # In NORMAL mode (default), ask only for risky tools
            risky_tools = {'write_file', 'edit_file', 'append_to_file', 'run_command', 'git_commit'}
            return tool_name in risky_tools

        try:
            # Create task context
            task_context = TaskContext(
                task_id=str(uuid.uuid4()),
                description=user_input,
                task_type="chat",
                key_concepts=[],
            )
            self.memory.set_task_context(task_context)

            # Add user message to memory with attachments
            # MemoryManager will build multimodal content and store it in MessageStore
            self.memory.add_user_message(user_input, attachments=attachments)

            # Parse and load file references
            file_references = self.file_reference_parser.parse_and_load(user_input)

            # Build initial context (with agent state for task continuation)
            # MemoryManager uses MessageStore when configured (Option A: Single Source of Truth)
            context = self.context_builder.build_context(
                user_query=user_input,
                task_type="chat",
                language="python",
                use_rag=len(self.indexed_chunks) > 0,
                available_chunks=self.indexed_chunks if self.indexed_chunks else None,
                file_references=file_references if file_references else None,
                agent_state=self.todo_state if self.todo_state.get('todos') else None,
                plan_mode_state=self.plan_mode_state,
            )

            # NOTE: Context usage is emitted after each LLM response with real token count
            # (see chunk.done handling below). We don't emit here to avoid overwriting
            # accurate LLM usage with tiktoken estimates on subsequent messages.

            # Multimodal content (attachments) is now properly stored in MessageStore
            # and will be included in context automatically via build_context()

            # Tool execution loop with realistic budgets
            # These limits are for real coding workflows (reading files, searching, etc.)
            MAX_TOOL_CALLS = 60  # Primary budget - generous for multi-file work
            MAX_WALL_TIME_SECONDS = None  # Disabled - tool_call limit is primary constraint
            MAX_PAUSE_CONTINUES = 3  # Safety cap - prevent infinite continuation
            MAX_ERROR_BUDGET_RESUMES = 2  # Cap on error budget "Continue" to prevent infinite loops

            tool_call_count = 0
            loop_start_time = time.monotonic()
            iteration = 0
            pause_continue_count = 0  # Track how many times user continued after pause
            current_context = context.copy()

            while True:  # Budgets checked inside loop
                iteration += 1

                # Budget checks: tool calls, wall time, and absolute safety limit
                elapsed_seconds = time.monotonic() - loop_start_time

                # Determine which limit was hit (if any)
                pause_reason = None
                pause_reason_code = None

                if tool_call_count >= MAX_TOOL_CALLS:
                    pause_reason = f"Tool limit reached ({tool_call_count}/{MAX_TOOL_CALLS})"
                    pause_reason_code = 'max_tool_calls'
                elif MAX_WALL_TIME_SECONDS and elapsed_seconds >= MAX_WALL_TIME_SECONDS:
                    pause_reason = f"Time limit reached ({elapsed_seconds:.0f}s/{MAX_WALL_TIME_SECONDS}s)"
                    pause_reason_code = 'max_wall_time'
                elif iteration >= ABSOLUTE_MAX_ITERATIONS:
                    pause_reason = f"Iteration limit reached ({iteration}/{ABSOLUTE_MAX_ITERATIONS})"
                    pause_reason_code = 'max_iterations'
                elif ui.check_interrupted():
                    pause_reason = "User interrupted"
                    pause_reason_code = 'user_interrupt'

                # Handle pause if limit was hit
                if pause_reason_code:
                    # Check if we've exceeded max continues (safety cap)
                    if pause_continue_count >= MAX_PAUSE_CONTINUES:
                        yield TextDelta(content=f"\n\n---\n**Stopped**: Maximum continues ({MAX_PAUSE_CONTINUES}) reached. Start a new message to continue.\n")
                        break

                    # Set state for potential resumption
                    self.todo_state['last_stop_reason'] = pause_reason_code

                    # Check if UI supports interactive pause
                    if hasattr(ui, 'has_pause_capability') and ui.has_pause_capability():
                        # TUI mode - use interactive widget
                        pending_todos = self._get_pending_todos_summary()
                        stats = {
                            'tool_calls': tool_call_count,
                            'elapsed_s': elapsed_seconds,
                            'iterations': iteration,
                        }

                        yield PausePromptStart(
                            reason=pause_reason,
                            reason_code=pause_reason_code,
                            pending_todos=pending_todos,
                            stats=stats,
                        )

                        try:
                            result = await ui.wait_for_pause_response(timeout=None)
                            yield PausePromptEnd(
                                continue_work=result.continue_work,
                                feedback=result.feedback,
                            )

                            if not result.continue_work:
                                break  # User chose to stop

                            # User chose to continue - reset budgets
                            pause_continue_count += 1
                            tool_call_count = 0
                            loop_start_time = time.monotonic()

                            # Inject feedback into context if provided
                            if result.feedback:
                                current_context.append({
                                    "role": "user",
                                    "content": f"[User guidance after pause: {result.feedback}]"
                                })

                            # Continue the loop instead of breaking
                            continue

                        except asyncio.CancelledError:
                            break
                    else:
                        # CLI mode - fall back to text-based pause
                        yield TextDelta(content=self._build_pause_message(pause_reason_code))
                        break

                # Clear blocked calls from previous iteration
                blocked_calls.clear()

                # Check for context compaction (only after iteration 1, when tool results accumulate)
                if iteration > 1 and self.memory.needs_compaction(threshold=0.85):
                    tokens_before = self.memory.working_memory.get_current_token_count()
                    messages_removed = self.memory.optimize_context()
                    tokens_after = self.memory.working_memory.get_current_token_count()

                    if messages_removed > 0:
                        yield ContextCompacted(
                            messages_removed=messages_removed,
                            tokens_before=tokens_before,
                            tokens_after=tokens_after,
                        )

                # Wrap LLM streaming in try/except to handle provider errors gracefully
                # (e.g., ReadTimeout, connection errors) without silent exit
                provider_error = None
                response_content = ""
                tool_calls = None

                try:
                    # === SAFETY NET: Fix any orphaned tool_calls before LLM call ===
                    # This handles Ctrl+C interrupts, crashes, and any edge cases
                    # where tool_use exists without tool_result
                    current_context = self._fix_orphaned_tool_calls(current_context)

                    # === UNIFIED ARCHITECTURE: Use ProviderDelta + StreamingPipeline ===
                    # 1. Start assistant stream through MemoryManager
                    self.memory.start_assistant_stream(
                        provider=self.backend_name,
                        model=self.model_name
                    )

                    # 2. Get LLM stream - yields ProviderDelta objects
                    llm_stream = self.llm.generate_provider_deltas_async(
                        messages=current_context,
                        tools=ALL_TOOLS,
                        tool_choice="auto"
                    )

                    # 3. Process ProviderDelta objects through MemoryManager
                    finalized_message = None
                    last_usage = None

                    async for delta in llm_stream:
                        # Feed delta to MemoryManager (uses StreamingPipeline internally)
                        finalized_message = self.memory.process_provider_delta(delta)

                        # Track usage for context update
                        if delta.usage:
                            last_usage = delta.usage

                        # Check for interrupt
                        if ui.check_interrupted():
                            break

                    # 4. Extract tool_calls and response_content from finalized message
                    if finalized_message and finalized_message.tool_calls:
                        tool_calls = finalized_message.tool_calls

                    # Derive response_content from pipeline (single source of truth)
                    response_content = (finalized_message.content or "") if finalized_message else self.memory.get_partial_text()

                    # Emit context usage update with real token count from LLM
                    if (last_usage and last_usage.get("input_tokens") is not None
                        and self.context_builder
                        and self.context_builder.max_context_tokens > 0):
                        yield ContextUpdated(
                            used=last_usage.get("input_tokens"),
                            limit=self.context_builder.max_context_tokens,
                            pressure_level=self._get_pressure_level(last_usage.get("input_tokens")),
                        )

                except Exception as e:
                    # Provider error (ReadTimeout, connection error, API error)
                    # Use structured logging with full context for debugging
                    error_type = type(e).__name__
                    error_msg = str(e).strip() or repr(e)

                    # Determine error category
                    is_timeout = 'timeout' in error_type.lower()
                    category = ErrorCategory.PROVIDER_TIMEOUT if is_timeout else ErrorCategory.PROVIDER_ERROR

                    # Find root cause in exception chain
                    root_cause = e
                    while root_cause.__cause__ is not None:
                        root_cause = root_cause.__cause__
                    root_cause_type = type(root_cause).__name__
                    root_cause_message = str(root_cause).strip()[:500]

                    # Calculate elapsed time since iteration start
                    elapsed_ms = int((time.monotonic() - loop_start_time) * 1000)

                    # Record error to SQLite store and get error_id for reference
                    from src.observability.error_store import get_error_store, ErrorCategory as StoreCategory
                    import traceback as tb
                    error_store = get_error_store()
                    error_id = error_store.record_from_dict(
                        level="ERROR",
                        category=category,
                        error_type=error_type,
                        message=error_msg,
                        traceback=tb.format_exc(),
                        component="core.agent",
                        operation="stream_response",
                        model=self.model_name,
                        backend=self.backend_name,
                        elapsed_ms=elapsed_ms,
                        root_cause_type=root_cause_type,
                        root_cause_message=root_cause_message,
                    )

                    # Log with structlog (JSONL) - includes error_id for correlation
                    logger.exception(
                        "llm_provider_error",
                        category=category,
                        error_type=error_type,
                        error_id=error_id,
                        model=self.model_name,
                        backend=self.backend_name,
                        iteration=iteration,
                        tool_call_count=tool_call_count,
                        elapsed_ms=elapsed_ms,
                        root_cause_type=root_cause_type,
                        root_cause_message=root_cause_message,
                    )

                    # Determine user-friendly message (no stack traces!)
                    is_timeout = "timeout" in root_cause_type.lower()
                    if is_timeout:
                        user_message = "Request timed out. The server took too long to respond."
                    else:
                        user_message = "Connection error. Please check your network."

                    # Emit ErrorEvent for TUI visibility (recoverable)
                    # Use root_cause_type (not error_type) to correctly classify wrapped exceptions
                    from src.core.events import ErrorEvent
                    yield ErrorEvent(
                        error_type="provider_timeout" if is_timeout else "network",
                        user_message=user_message,
                        error_id=error_id,
                        recoverable=True,
                        retry_after=None
                    )

                    # Set provider_error for pause flow (also user-friendly)
                    provider_error = user_message

                # Handle provider error by transitioning to pause state
                if provider_error:
                    pause_reason = provider_error  # Already user-friendly, no prefix needed
                    pause_reason_code = 'provider_error'

                    # Store any partial response
                    if response_content:
                        self.memory.add_assistant_message(response_content)

                    # Transition to pause state (same as other limits)
                    if hasattr(ui, 'has_pause_capability') and ui.has_pause_capability():
                        # TUI mode - emit PausePromptStart and wait
                        pending_todos = [
                            t.get('content', 'Unknown task')[:50]
                            for t in self.todo_state.get('todos', [])
                            if t.get('status') in ('in_progress', 'pending')
                        ]

                        yield PausePromptStart(
                            reason=pause_reason,
                            reason_code=pause_reason_code,
                            pending_todos=pending_todos,
                            stats={
                                'tool_calls': tool_call_count,
                                'elapsed_s': time.monotonic() - loop_start_time,
                                'iterations': iteration,
                                'error': provider_error
                            }
                        )

                        # Wait for user decision (with timeout to prevent deadlock)
                        try:
                            result = await ui.wait_for_pause_response(timeout=300.0)
                            yield PausePromptEnd(
                                continue_work=result.continue_work,
                                feedback=result.feedback
                            )
                            if not result.continue_work:
                                # Save partial response to memory so next message has context
                                if response_content and response_content.strip():
                                    # Truncate to avoid polluting memory with very long partials
                                    partial = response_content.strip()
                                    if len(partial) > 4000:
                                        partial = partial[:4000] + "..."
                                    # Tag as timed out for clarity in conversation history
                                    self.memory.add_assistant_message(
                                        partial + "\n\n[TIMED OUT: Response was cut off due to provider timeout. User chose to stop.]"
                                    )
                                break
                            # User chose to retry - add partial response context so LLM can continue
                            if response_content and response_content.strip():
                                # Truncate if very long (keep last 2000 chars for context)
                                partial = response_content.strip()
                                if len(partial) > 2000:
                                    partial = "..." + partial[-2000:]
                                # Add assistant's partial response with anchor delimiter
                                current_context.append({
                                    "role": "assistant",
                                    "content": partial + "\n\n[END OF PARTIAL RESPONSE]"
                                })
                                # Add continuation instruction (plain text, no fake system prefix)
                                current_context.append({
                                    "role": "user",
                                    "content": "Your previous response was cut off by a timeout. Continue AFTER [END OF PARTIAL RESPONSE]. Do not repeat anything above. If unsure where to resume, ask."
                                })
                                # Add visual separator in UI so continuation is clearly appended
                                yield TextDelta(content="\n\n")
                            continue
                        except asyncio.CancelledError:
                            # Treat cancellation as STOP (not interrupt semantics)
                            yield PausePromptEnd(continue_work=False, feedback="Pause cancelled")
                            break
                    else:
                        # CLI mode - yield pause message and break
                        yield TextDelta(content=self._build_pause_message(pause_reason_code))
                        break

                # If interrupted, stop processing
                if ui.check_interrupted():
                    break

                # If no tool calls, we're done
                # NOTE: Message already added to store by process_provider_delta() at line 2198
                # Do NOT call add_assistant_message() again - it would create duplicate
                if not tool_calls:
                    break

                # Process tool calls
                tool_messages = []
                user_rejected = False  # Track if user rejected any tool

                for tc in tool_calls:
                    call_id = tc.id or f"call_{uuid.uuid4().hex[:8]}"

                    # Check if this exact call has failed before (ENFORCEMENT IN CODE)
                    is_repeat, call_summary = self._error_tracker.is_repeated_failed_call(
                        tc.function.name, tc.function.get_parsed_arguments()
                    )
                    if is_repeat:
                        # Block this call - add to blocked_calls for controller constraint
                        blocked_calls.append(call_summary)

                        # Update tool state in store (skipped)
                        if self.memory.message_store:
                            self.memory.message_store.update_tool_state(
                                call_id,
                                CoreToolStatus.SKIPPED
                            )

                        # LLM feedback: Add tool message so LLM knows to try different approach
                        tool_messages.append({
                            "role": "tool",
                            "tool_call_id": call_id,
                            "name": tc.function.name,
                            "content": "[BLOCKED] This exact call failed previously. You must try a different approach or different arguments."
                        })
                        continue  # Move to next tool call

                    # Check plan mode gating BEFORE approval and execution
                    tool_args = tc.function.get_parsed_arguments()
                    plan_gate_result = self._check_plan_mode_gate(tc.function.name, tool_args)
                    if plan_gate_result is not None:
                        # Tool is gated in plan mode - update store
                        if self.memory.message_store:
                            self.memory.message_store.update_tool_state(
                                call_id,
                                CoreToolStatus.ERROR,
                                error=plan_gate_result["message"]
                            )

                        # Add gated response to tool messages for LLM feedback
                        import json
                        gated_output = json.dumps(plan_gate_result, indent=2)
                        tool_messages.append({
                            "role": "tool",
                            "tool_call_id": call_id,
                            "name": tc.function.name,
                            "content": gated_output
                        })

                        # Persist tool result to MessageStore for session replay
                        self.memory.add_tool_result(
                            tool_call_id=call_id,
                            content=gated_output,
                            tool_name=tc.function.name,
                            status="gated",
                        )
                        continue  # Skip to next tool call

                    requires_approval = needs_approval(tc.function.name)

                    # Freeze approval policy in render meta registry (store-driven UI)
                    # This captures the policy at tool-call creation time (freeze semantics)
                    mode = self.permission_manager.get_mode() if self.permission_manager else PermissionMode.NORMAL
                    self.memory.render_meta.set_approval_meta(
                        call_id,
                        ToolApprovalMeta(
                            requires_approval=requires_approval,
                            permission_mode=mode.value if hasattr(mode, 'value') else str(mode)
                        )
                    )

                    # Initialize tool state in message store (for TUI rendering)
                    if self.memory.message_store:
                        self.memory.message_store.update_tool_state(
                            call_id,
                            CoreToolStatus.PENDING
                        )

                    # Handle approval if required
                    if requires_approval:
                        # Set approval state to prevent pause prompts during approval wait
                        self._awaiting_approval = True

                        # Update tool state in message store
                        if self.memory.message_store:
                            self.memory.message_store.update_tool_state(
                                call_id,
                                CoreToolStatus.AWAITING_APPROVAL
                            )

                        try:
                            # Wait for user approval via UI (no timeout - user may be multitasking)
                            approval_result = await ui.wait_for_approval(call_id, tc.function.name, timeout=None)

                            if not approval_result.approved:
                                # Build rejection message with optional feedback
                                if approval_result.feedback:
                                    # User provided feedback - pass to LLM so it can try again
                                    rejection_msg = f"User rejected with feedback: {approval_result.feedback}"

                                    # Update tool_state in message store
                                    if self.memory.message_store:
                                        self.memory.message_store.update_tool_state(
                                            call_id,
                                            CoreToolStatus.REJECTED
                                        )

                                    # Add feedback to tool messages so LLM sees it
                                    tool_messages.append({
                                        "role": "tool",
                                        "tool_call_id": call_id,
                                        "name": tc.function.name,
                                        "content": rejection_msg
                                    })

                                    # Persist tool result to MessageStore for session replay
                                    self.memory.add_tool_result(
                                        tool_call_id=call_id,
                                        content=rejection_msg,
                                        tool_name=tc.function.name,
                                        status="rejected",
                                    )

                                    # Continue to next tool call (don't stop - LLM will see feedback)
                                    continue
                                else:
                                    # Pure rejection (Escape) - stop completely
                                    rejection_msg = "Tool call rejected by user"

                                    # CRITICAL: Update tool_state in message store
                                    if self.memory.message_store:
                                        self.memory.message_store.update_tool_state(
                                            call_id,
                                            CoreToolStatus.REJECTED
                                        )

                                    # CRITICAL: Add tool_result for rejected call
                                    # Claude API requires every tool_use to have a tool_result
                                    tool_messages.append({
                                        "role": "tool",
                                        "tool_call_id": call_id,
                                        "name": tc.function.name,
                                        "content": rejection_msg
                                    })

                                    # Persist tool result to MessageStore for session replay
                                    self.memory.add_tool_result(
                                        tool_call_id=call_id,
                                        content=rejection_msg,
                                        tool_name=tc.function.name,
                                        status="rejected",
                                    )

                                    # User rejected without feedback - stop execution immediately
                                    # Don't continue processing, let user decide next action
                                    user_rejected = True
                                    break  # Exit tool loop immediately

                            # Update tool state in message store
                            if self.memory.message_store:
                                self.memory.message_store.update_tool_state(
                                    call_id,
                                    CoreToolStatus.APPROVED
                                )

                        except asyncio.TimeoutError:
                            if self.memory.message_store:
                                self.memory.message_store.update_tool_state(
                                    call_id,
                                    CoreToolStatus.CANCELLED
                                )
                            tool_messages.append({
                                "role": "tool",
                                "tool_call_id": call_id,
                                "name": tc.function.name,
                                "content": "Tool call approval timed out"
                            })
                            continue

                        except asyncio.CancelledError:
                            cancelled_msg = "Tool call cancelled by user (stream interrupted)"

                            # CRITICAL: Update tool_state in message store
                            if self.memory.message_store:
                                self.memory.message_store.update_tool_state(
                                    call_id,
                                    CoreToolStatus.CANCELLED
                                )

                            # CRITICAL: Add tool_result for cancelled call
                            tool_messages.append({
                                "role": "tool",
                                "tool_call_id": call_id,
                                "name": tc.function.name,
                                "content": cancelled_msg
                            })

                            # Persist tool result to MessageStore for session replay
                            self.memory.add_tool_result(
                                tool_call_id=call_id,
                                content=cancelled_msg,
                                tool_name=tc.function.name,
                                status="cancelled",
                            )

                            # Mark as cancelled (similar to user_rejected)
                            user_rejected = True
                            break  # Exit tool loop, don't re-raise

                        finally:
                            # ALWAYS reset approval state, even on exception/cancel
                            self._awaiting_approval = False

                    # Execute tool
                    # Update tool state in message store
                    if self.memory.message_store:
                        self.memory.message_store.update_tool_state(
                            call_id,
                            CoreToolStatus.RUNNING
                        )

                    start_time = time.monotonic()

                    # OVERWRITE GUARD: Block destructive todo_write BEFORE execution.
                    # Rationale: TodoWriteTool mutates agent_state['todos'] during execution.
                    # If we validate after execution, the state may already be overwritten.
                    if tc.function.name == 'todo_write':
                        new_todos = tc.function.get_parsed_arguments().get('todos', [])
                        if self._is_destructive_todo_update(new_todos) and not self._user_confirmed_reset:
                            # Block the destructive update
                            incomplete = [t for t in self.todo_state.get('todos', [])
                                          if t.get('status') in ('in_progress', 'pending')]
                            task_ids = ", ".join(t.get('id', '?') for t in incomplete[:3])
                            if len(incomplete) > 3:
                                task_ids += f"... and {len(incomplete) - 3} more"

                            duration_ms = int((time.monotonic() - start_time) * 1000)
                            error_content = f"Cannot overwrite incomplete todos ({task_ids}). Complete them first, or say 'reset todos' to discard."

                            # Update tool state in message store
                            if self.memory.message_store:
                                self.memory.message_store.update_tool_state(
                                    call_id,
                                    CoreToolStatus.ERROR,
                                    error=error_content,
                                    duration_ms=duration_ms
                                )

                            # Persist tool result to MessageStore for session replay
                            self.memory.add_tool_result(
                                tool_call_id=call_id,
                                content=f"Error: {error_content}",
                                tool_name=tc.function.name,
                                status="error",
                                duration_ms=duration_ms,
                            )

                            tool_messages.append({
                                "role": "tool",
                                "tool_call_id": call_id,
                                "name": tc.function.name,
                                "content": f"Error: {error_content}"
                            })
                            continue  # Skip to next tool call

                    # Increment tool call counter for budget tracking
                    tool_call_count += 1

                    # Special handling for clarify tool (requires UI interaction)
                    if tc.function.name == "clarify":
                        clarify_result = await self._handle_clarify_tool(
                            call_id,
                            tc.function.get_parsed_arguments(),
                            ui
                        )

                        duration_ms = int((time.monotonic() - start_time) * 1000)

                        # Update tool state in message store
                        if self.memory.message_store:
                            self.memory.message_store.update_tool_state(
                                call_id,
                                CoreToolStatus.SUCCESS,
                                result=clarify_result,
                                duration_ms=duration_ms
                            )

                        # Persist tool result to MessageStore for session replay
                        self.memory.add_tool_result(
                            tool_call_id=call_id,
                            content=json.dumps(clarify_result),
                            tool_name=tc.function.name,
                            status="success",
                            duration_ms=duration_ms,
                        )

                        tool_messages.append({
                            "role": "tool",
                            "tool_call_id": call_id,
                            "name": tc.function.name,
                            "content": json.dumps(clarify_result)
                        })
                        continue  # Skip to next tool call

                    try:
                        result = await self.tool_executor.execute_tool_async(
                            tc.function.name,
                            **tc.function.get_parsed_arguments()
                        )

                        duration_ms = int((time.monotonic() - start_time) * 1000)

                        if result.is_success():
                            output = result.output

                            # Claude Code style: return ERROR with guidance for oversized output
                            if isinstance(output, str) and len(output) > self._max_tool_output_chars:
                                error_msg, tool_msg, history = self._format_oversized_output_error(
                                    len(output), tc.function.name,
                                    tc.function.get_parsed_arguments(), call_id
                                )

                                # Update tool state in message store
                                if self.memory.message_store:
                                    self.memory.message_store.update_tool_state(
                                        call_id, CoreToolStatus.ERROR,
                                        error=error_msg, duration_ms=duration_ms
                                    )

                                # Persist tool result to MessageStore for session replay
                                self.memory.add_tool_result(
                                    tool_call_id=call_id, content=error_msg,
                                    tool_name=tc.function.name, status="error",
                                    duration_ms=duration_ms,
                                )
                                tool_messages.append(tool_msg)
                                self.tool_execution_history.append(history)
                                continue  # Skip to next tool call

                            # Update tool state in message store
                            if self.memory.message_store:
                                self.memory.message_store.update_tool_state(
                                    call_id,
                                    CoreToolStatus.SUCCESS,
                                    result=output,
                                    duration_ms=duration_ms
                                )

                            # Persist tool result to MessageStore for session replay
                            self.memory.add_tool_result(
                                tool_call_id=call_id,
                                content=str(output),
                                tool_name=tc.function.name,
                                status="success",
                                duration_ms=duration_ms,
                            )

                            # Track successful tool since error budget resume (for progress detection)
                            if self.todo_state.get('error_budget_resume_count', 0) > 0:
                                self.todo_state['successful_tools_since_resume'] = \
                                    self.todo_state.get('successful_tools_since_resume', 0) + 1

                            # Handle todo_write success: apply stable IDs and notify UI
                            # NOTE: Always run merge, even on first write (empty existing list is handled)
                            if tc.function.name == 'todo_write':
                                # Apply stable ID merge (preserves IDs across updates)
                                raw_todos = tc.function.get_parsed_arguments().get('todos', [])
                                merged_todos = self._merge_todos_with_stable_ids(raw_todos)
                                self.todo_state['todos'] = merged_todos

                                # Enforce single active invariant
                                in_progress_todo = next(
                                    (t for t in merged_todos if t.get('status') == 'in_progress'),
                                    None
                                )
                                if in_progress_todo and in_progress_todo.get('id'):
                                    self._set_todo_in_progress(in_progress_todo['id'])

                                # Notify UI
                                ui.notify_todos_updated(self.todo_state['todos'])

                            tool_messages.append({
                                "role": "tool",
                                "tool_call_id": call_id,
                                "name": tc.function.name,
                                "content": str(output)
                            })
                        else:
                            # Update tool state in message store
                            if self.memory.message_store:
                                self.memory.message_store.update_tool_state(
                                    call_id,
                                    CoreToolStatus.ERROR,
                                    error=result.error,
                                    duration_ms=duration_ms
                                )

                            # Record failure for intelligent retry
                            error_type = self._classify_tool_error(result.error or "Unknown error")
                            error_context = self._error_tracker.record_failure(
                                error_type=error_type,
                                tool_name=tc.function.name,
                                tool_args=tc.function.get_parsed_arguments(),
                                error_message=result.error or "Unknown error",
                                exit_code=getattr(result, 'exit_code', None),
                                stdout=getattr(result, 'stdout', None),
                                stderr=getattr(result, 'stderr', None)
                            )

                            # Persist tool result to MessageStore for session replay
                            self.memory.add_tool_result(
                                tool_call_id=call_id,
                                content=error_context.to_prompt_block(),
                                tool_name=tc.function.name,
                                status="error",
                                duration_ms=duration_ms,
                            )

                            # Check if retry should be allowed
                            allowed, reason = self._error_tracker.should_allow_retry(tc.function.name, error_type)

                            if allowed:
                                # Inject structured error context for LLM
                                tool_messages.append({
                                    "role": "tool",
                                    "tool_call_id": call_id,
                                    "name": tc.function.name,
                                    "content": error_context.to_prompt_block()
                                })
                            else:
                                # Error budget exceeded - pause instead of hard stop
                                # Check approval precedence (don't show pause during approval wait)
                                if self._awaiting_approval:
                                    logger.debug("error budget exceeded but approval pending; deferring pause")
                                    tool_messages.append({
                                        "role": "tool",
                                        "tool_call_id": call_id,
                                        "name": tc.function.name,
                                        "content": error_context.to_prompt_block()
                                    })
                                    continue  # Let approval resolve first

                                # Set state for potential resumption
                                self.todo_state['last_stop_reason'] = 'error_budget'

                                # Check resume cap (prevent infinite Continue loops)
                                resume_count = self.todo_state.get('error_budget_resume_count', 0)
                                progress_since_resume = self.todo_state.get('successful_tools_since_resume', 0)

                                if resume_count >= MAX_ERROR_BUDGET_RESUMES:
                                    # Force stop - too many resumes
                                    yield TextDelta(content=(
                                        f"\n[ERROR] Reached maximum error recovery attempts "
                                        f"({MAX_ERROR_BUDGET_RESUMES}). "
                                        "Please provide guidance on how to proceed."
                                    ))
                                    user_rejected = True
                                    break

                                # Check for no-progress (resumed but still failing)
                                pause_reason_code = 'error_budget'
                                if resume_count > 0 and progress_since_resume == 0:
                                    # Still failing with no progress - change message
                                    pause_reason_code = 'error_budget_no_progress'
                                    reason = f"{reason} (no progress since last resume)"

                                # Check if UI supports interactive pause
                                if hasattr(ui, 'has_pause_capability') and ui.has_pause_capability():
                                    # TUI mode - use interactive widget
                                    pending_todos = self._get_pending_todos_summary()
                                    error_stats = self._error_tracker.get_stats()
                                    stats = {
                                        'tool_calls': tool_call_count,
                                        'elapsed_s': elapsed_seconds,
                                        'errors_total': error_stats['total_failures'],
                                        'error_reason': reason,
                                    }

                                    yield PausePromptStart(
                                        reason=f"Error budget: {reason}",
                                        reason_code=pause_reason_code,  # error_budget or error_budget_no_progress
                                        pending_todos=pending_todos,
                                        stats=stats,
                                    )

                                    try:
                                        pause_result = await ui.wait_for_pause_response(timeout=None)
                                        yield PausePromptEnd(
                                            continue_work=pause_result.continue_work,
                                            feedback=pause_result.feedback,
                                        )

                                        if not pause_result.continue_work:
                                            user_rejected = True
                                            break  # User chose to stop

                                        # User chose to continue - partial reset
                                        self.todo_state['error_budget_resume_count'] = \
                                            self.todo_state.get('error_budget_resume_count', 0) + 1
                                        self.todo_state['successful_tools_since_resume'] = 0

                                        # Reset tool error counts (allow retries)
                                        self._error_tracker.reset_tool_error_counts(tool_name=tc.function.name)

                                        # Always inject hint to LLM
                                        current_context.append({
                                            "role": "system",
                                            "content": "<notice>Continuing after error budget pause. Try a different approach; repeated identical calls are blocked.</notice>"
                                        })

                                        if pause_result.feedback:
                                            current_context.append({
                                                "role": "user",
                                                "content": f"[User guidance: {pause_result.feedback}]"
                                            })

                                        # Add error context for LLM awareness
                                        tool_messages.append({
                                            "role": "tool",
                                            "tool_call_id": call_id,
                                            "name": tc.function.name,
                                            "content": error_context.to_prompt_block()
                                        })

                                    except asyncio.CancelledError:
                                        user_rejected = True
                                        break
                                else:
                                    # CLI mode - text-based pause (not hard stop!)
                                    yield TextDelta(content=self._build_pause_message('error_budget'))
                                    break  # Returns to user, they can continue

                    except Exception as e:
                        duration_ms = int((time.monotonic() - start_time) * 1000)

                        # Update tool state in message store
                        if self.memory.message_store:
                            self.memory.message_store.update_tool_state(
                                call_id,
                                CoreToolStatus.ERROR,
                                error=str(e),
                                duration_ms=duration_ms
                            )

                        # Record exception as failure for intelligent retry
                        error_type = self._classify_tool_error(str(e))
                        error_context = self._error_tracker.record_failure(
                            error_type=error_type,
                            tool_name=tc.function.name,
                            tool_args=tc.function.get_parsed_arguments(),
                            error_message=str(e)
                        )

                        # Persist tool result to MessageStore for session replay
                        self.memory.add_tool_result(
                            tool_call_id=call_id,
                            content=error_context.to_prompt_block(),
                            tool_name=tc.function.name,
                            status="error",
                            duration_ms=duration_ms,
                        )

                        # Check if retry should be allowed
                        allowed, reason = self._error_tracker.should_allow_retry(tc.function.name, error_type)

                        if allowed:
                            # Inject structured error context for LLM
                            tool_messages.append({
                                "role": "tool",
                                "tool_call_id": call_id,
                                "name": tc.function.name,
                                "content": error_context.to_prompt_block()
                            })
                        else:
                            # Error budget exceeded - pause instead of hard stop
                            # Check approval precedence (don't show pause during approval wait)
                            if self._awaiting_approval:
                                logger.debug("error budget exceeded but approval pending; deferring pause")
                                tool_messages.append({
                                    "role": "tool",
                                    "tool_call_id": call_id,
                                    "name": tc.function.name,
                                    "content": error_context.to_prompt_block()
                                })
                                continue  # Let approval resolve first

                            # Set state for potential resumption
                            self.todo_state['last_stop_reason'] = 'error_budget'

                            # Check resume cap (prevent infinite Continue loops)
                            resume_count = self.todo_state.get('error_budget_resume_count', 0)
                            progress_since_resume = self.todo_state.get('successful_tools_since_resume', 0)

                            if resume_count >= MAX_ERROR_BUDGET_RESUMES:
                                # Force stop - too many resumes
                                yield TextDelta(content=(
                                    f"\n[ERROR] Reached maximum error recovery attempts "
                                    f"({MAX_ERROR_BUDGET_RESUMES}). "
                                    "Please provide guidance on how to proceed."
                                ))
                                user_rejected = True
                                break

                            # Check for no-progress (resumed but still failing)
                            pause_reason_code = 'error_budget'
                            if resume_count > 0 and progress_since_resume == 0:
                                # Still failing with no progress - change message
                                pause_reason_code = 'error_budget_no_progress'
                                reason = f"{reason} (no progress since last resume)"

                            # Check if UI supports interactive pause
                            if hasattr(ui, 'has_pause_capability') and ui.has_pause_capability():
                                # TUI mode - use interactive widget
                                pending_todos = self._get_pending_todos_summary()
                                error_stats = self._error_tracker.get_stats()
                                stats = {
                                    'tool_calls': tool_call_count,
                                    'elapsed_s': elapsed_seconds,
                                    'errors_total': error_stats['total_failures'],
                                    'error_reason': reason,
                                }

                                yield PausePromptStart(
                                    reason=f"Error budget: {reason}",
                                    reason_code=pause_reason_code,  # error_budget or error_budget_no_progress
                                    pending_todos=pending_todos,
                                    stats=stats,
                                )

                                try:
                                    pause_result = await ui.wait_for_pause_response(timeout=None)
                                    yield PausePromptEnd(
                                        continue_work=pause_result.continue_work,
                                        feedback=pause_result.feedback,
                                    )

                                    if not pause_result.continue_work:
                                        user_rejected = True
                                        break  # User chose to stop

                                    # User chose to continue - partial reset
                                    self.todo_state['error_budget_resume_count'] = \
                                        self.todo_state.get('error_budget_resume_count', 0) + 1
                                    self.todo_state['successful_tools_since_resume'] = 0

                                    # Reset tool error counts (allow retries)
                                    self._error_tracker.reset_tool_error_counts(tool_name=tc.function.name)

                                    # Always inject hint to LLM
                                    current_context.append({
                                        "role": "system",
                                        "content": "<notice>Continuing after error budget pause. Try a different approach; repeated identical calls are blocked.</notice>"
                                    })

                                    if pause_result.feedback:
                                        current_context.append({
                                            "role": "user",
                                            "content": f"[User guidance: {pause_result.feedback}]"
                                        })

                                    # Add error context for LLM awareness
                                    tool_messages.append({
                                        "role": "tool",
                                        "tool_call_id": call_id,
                                        "name": tc.function.name,
                                        "content": error_context.to_prompt_block()
                                    })

                                except asyncio.CancelledError:
                                    user_rejected = True
                                    break
                            else:
                                # CLI mode - text-based pause (not hard stop!)
                                yield TextDelta(content=self._build_pause_message('error_budget'))
                                break  # Returns to user, they can continue

                # If user rejected a tool, add tool_results for remaining unprocessed calls
                # Claude API requires every tool_use to have a corresponding tool_result
                if user_rejected:
                    # Find tool calls that weren't processed (after the rejected one)
                    processed_call_ids = {msg.get("tool_call_id") for msg in tool_messages if msg.get("role") == "tool"}
                    for tc in tool_calls:
                        tc_id = tc.id or f"call_{tool_calls.index(tc)}"
                        if tc_id not in processed_call_ids:
                            skipped_msg = "Tool call skipped (previous tool rejected by user)"
                            tool_messages.append({
                                "role": "tool",
                                "tool_call_id": tc_id,
                                "name": tc.function.name,
                                "content": skipped_msg
                            })
                            # Persist to MessageStore
                            self.memory.add_tool_result(
                                tool_call_id=tc_id,
                                content=skipped_msg,
                                tool_name=tc.function.name,
                                status="skipped",
                            )
                            # Update tool_state
                            if self.memory.message_store:
                                self.memory.message_store.update_tool_state(
                                    tc_id,
                                    CoreToolStatus.SKIPPED
                                )

                    # Still add assistant message and tool_results to context
                    # so next turn has complete conversation history
                    current_context.append({
                        "role": "assistant",
                        "content": response_content,
                        "tool_calls": [
                            {
                                "id": tc.id or f"call_{i}",
                                "type": "function",
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": json.dumps(tc.function.get_parsed_arguments())
                                }
                            }
                            for i, tc in enumerate(tool_calls)
                        ]
                    })
                    current_context.extend(tool_messages)

                    break  # Exit main while loop

                # Add assistant's response with tool calls to context
                current_context.append({
                    "role": "assistant",
                    "content": response_content,
                    "tool_calls": [
                        {
                            "id": tc.id or f"call_{i}",
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": json.dumps(tc.function.get_parsed_arguments())
                            }
                        }
                        for i, tc in enumerate(tool_calls)
                    ]
                })

                # Add tool results to context
                current_context.extend(tool_messages)

                # Inject controller constraint for blocked calls
                # (These are calls that failed before and were blocked from re-execution)
                if blocked_calls:
                    constraint = f"""[CONTROLLER] The following tool calls were BLOCKED because they previously failed:
{chr(10).join(f'- {call}' for call in blocked_calls)}

REQUIRED: Choose a DIFFERENT approach:
- Use a different tool, OR
- Change arguments meaningfully (path, command), OR
- Add a diagnostic step first (read_file, list_directory)
- If impossible, explain to user why task cannot be completed"""

                    current_context.append({
                        "role": "user",
                        "content": constraint
                    })

        except Exception as e:
            # Outer exception handler - catches any exceptions not handled by inner handlers
            # Log full stack trace for debugging
            logger.error(
                f"Unhandled exception in stream_response:\n"
                f"{traceback.format_exc()}"
            )

            # Format error message properly (handles empty str(e))
            error_type = type(e).__name__
            error_msg = str(e).strip()
            if not error_msg:
                error_msg = repr(e)
            formatted_error = f"{error_type}: {error_msg}"

            # Yield error as text with proper formatting
            yield TextDelta(content=f"\n\n[Error: {formatted_error}]")

        # Yield StreamEnd to signal completion
        yield StreamEnd()

    async def chat_async(
        self,
        message: str,
        use_rag: bool = True,
        on_chunk: Optional[Callable[[str], Awaitable[None]]] = None,
        request_approval: Optional[Callable[[str, Dict[str, Any]], Awaitable[bool]]] = None,
    ) -> AgentResponse:
        """
        Async interactive chat for TUI with real-time streaming.

        This is the async version of chat() that allows the TUI to remain
        responsive while streaming LLM responses and executing tools.

        Args:
            message: User message
            use_rag: Whether to use RAG retrieval (default: True)
            on_chunk: Async callback for each content chunk (for UI updates)
            request_approval: Async callback for TUI-native approval dialogs

        Returns:
            Agent response

        Example:
            async def update_ui(chunk: str):
                self.chat_history += chunk
                self.app.invalidate()  # Refresh TUI

            async def approve(tool_name: str, tool_args: dict) -> bool:
                return await tui.request_approval(tool_name, tool_args)

            response = await agent.chat_async(
                message="write a hello world",
                on_chunk=update_ui,
                request_approval=approve
            )
        """
        # USER PROMPT SUBMIT HOOK (same as sync version)
        if self.hook_manager:
            try:
                from src.hooks import HookContinue

                decision, modified_prompt = self.hook_manager.emit_user_prompt_submit(
                    prompt=message,
                    metadata={
                        "stream": True,
                        "use_rag": use_rag,
                        "async": True
                    }
                )

                if decision == HookContinue.BLOCK:
                    return AgentResponse(
                        content="Prompt blocked by hook",
                        metadata={"blocked": True}
                    )

                message = modified_prompt

            except Exception as e:
                if e.__class__.__name__ == 'HookBlockedError':
                    return AgentResponse(
                        content=f"Prompt blocked by hook: {str(e)}",
                        metadata={"blocked": True}
                    )
                logger.warning(f"UserPromptSubmit hook error: {e}", exc_info=True)

        # Reset web tools budget for new turn
        if hasattr(self, '_web_run_budget') and self._web_run_budget:
            self._web_run_budget.reset()

        # Create task context
        task_context = TaskContext(
            task_id=str(uuid.uuid4()),
            description=message,
            task_type="chat",
            key_concepts=[],
        )

        self.memory.set_task_context(task_context)
        self.memory.add_user_message(message)

        # Parse and load file references
        file_references = self.file_reference_parser.parse_and_load(message)

        # Build context (with agent state for task continuation)
        # MemoryManager uses MessageStore when configured (Option A: Single Source of Truth)
        context = self.context_builder.build_context(
            user_query=message,
            task_type="chat",
            language="python",
            use_rag=use_rag and len(self.indexed_chunks) > 0,
            available_chunks=self.indexed_chunks if use_rag else None,
            file_references=file_references if file_references else None,
            agent_state=self.todo_state if self.todo_state.get('todos') else None,
            plan_mode_state=self.plan_mode_state,
        )

        # Execute with async tool calling loop
        execution_result = await self._execute_with_tools_async(
            context=context,
            max_iterations=10,
            on_chunk=on_chunk,
            request_approval=request_approval,  # TUI-native approval
        )

        # Persist the ordered transcript to working memory
        from src.memory.models import MessageRole
        for msg in execution_result.turn_messages:
            if msg["role"] == "assistant":
                self.memory.working_memory.add_message(
                    role=MessageRole.ASSISTANT,
                    content=msg.get("content", ""),
                    metadata={"tool_calls": msg.get("tool_calls")} if msg.get("tool_calls") else None
                )
            elif msg["role"] == "tool":
                self.memory.working_memory.add_message(
                    role=MessageRole.TOOL,
                    content=msg.get("content", ""),
                    metadata={
                        "tool_call_id": msg.get("tool_call_id"),
                        "name": msg.get("name")
                    }
                )

        response_content = execution_result.content
        return AgentResponse(
            content=response_content,
            metadata={
                "execution_mode": "llm_first_async",
                "used_rag": use_rag and len(self.indexed_chunks) > 0,
            }
        )

    @observe_tool_execution("agent_execute_tool", capture_args=True)
    def execute_tool(self, tool_name: str, **kwargs: Any) -> Any:
        """
        Execute a tool.

        Args:
            tool_name: Name of tool
            **kwargs: Tool parameters

        Returns:
            Tool result

        Raises:
            ToolNotFoundError: Tool does not exist
            ToolExecutionError: Tool execution failed
        """
        result = self.tool_executor.execute_tool(tool_name, **kwargs)

        if result.is_success():
            return result.output
        else:
            # Determine error type from error message
            error_msg = result.error or "Unknown error"
            if "not found" in error_msg.lower() or "unknown tool" in error_msg.lower():
                raise ToolNotFoundError(error_msg)
            else:
                raise ToolExecutionError(error_msg)

    def call_llm(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        stream: bool = False,
        **kwargs
    ) -> str:
        """
        Call LLM with conversation messages, returns response text.

        Implements AgentInterface.call_llm().

        Args:
            messages: Conversation history in OpenAI format
            temperature: Sampling temperature (0.0 = deterministic, 1.0 = creative)
            max_tokens: Maximum tokens in response
            stream: Enable streaming (not supported in v1)
            **kwargs: Additional LLM parameters

        Returns:
            str: LLM response text

        Raises:
            LLMError: LLM API error (general)
            RateLimitError: Rate limit exceeded
            TimeoutError: Request timeout
        """
        try:
            # CRITICAL: Validate messages before LLM call
            self.llm.validate_messages(messages)

            # Use the LLM backend's generate method
            # Note: generate_with_tools expects messages with tools list
            # For simple call_llm, we'll use a basic generate call
            response = self.llm.generate_with_tools(
                messages=messages,
                tools=[],  # No tools for simple LLM call
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs
            )

            # Extract text from response
            if isinstance(response, dict):
                return response.get('content', str(response))
            return str(response)
        except (LLMError, RateLimitError, TimeoutError):
            # Re-raise properly typed LLM exceptions
            raise
        except ValueError as e:
            # Message validation errors
            raise ValueError(f"Invalid messages: {e}") from e
        except Exception as e:
            # Wrap unknown exceptions as LLMError
            raise LLMError(f"LLM call failed: {e}") from e

    def get_context(self) -> Dict[str, Any]:
        """
        Get current execution context.

        Implements AgentInterface.get_context().

        Returns:
            Dict[str, Any]: Context dictionary with working_directory,
                          conversation_history, session_id, and active_task
        """
        # Get conversation history from working memory
        conversation_history = [
            {
                "role": msg.role.value,
                "content": msg.content,
                "timestamp": msg.timestamp.isoformat() if msg.timestamp else None,
            }
            for msg in self.memory.working_memory.messages
        ]

        return {
            "working_directory": str(self.working_directory),
            "conversation_history": conversation_history,
            "session_id": self.memory.session_id,
            "active_task": None,  # TODO: Track active task in future iteration
        }

    def update_memory(self, key: str, value: Any) -> None:
        """
        Update agent memory with key-value pair.

        Implements AgentInterface.update_memory().

        Stores structured data in memory manager's key-value store.
        Data is preserved with full structure (dicts, lists, etc.).

        Args:
            key: Memory key (e.g., 'last_test_result', 'validation_status')
            value: Value to store (any JSON-serializable type)

        Raises:
            MemoryError: Memory update failed
        """
        try:
            self.memory.set_value(key, value)
        except Exception as e:
            raise MemoryError(f"Memory update failed for key '{key}': {e}") from e

    def get_memory(self, key: str, default: Any = None) -> Any:
        """
        Retrieve agent memory by key.

        Retrieves structured data from memory manager's key-value store.

        Args:
            key: Memory key
            default: Default value if key not found

        Returns:
            Stored value, or default if not found

        Example:
            results = agent.get_memory('test_results', {'passed': 0, 'failed': 0})
        """
        return self.memory.get_value(key, default)

    def get_available_tools(self) -> str:
        """Get description of available tools."""
        return self.tool_executor.get_tools_description()

    def save_session(self, session_name: Optional[str] = None) -> Path:
        """Save current session."""
        return self.memory.save_session(session_name)

    def load_session(self, session_path: Path) -> None:
        """Load a saved session."""
        self.memory.load_session(session_path)

    def resume_session_from_jsonl(self, jsonl_path: Path) -> "HydrationResult":
        """
        Resume session from JSONL file using SessionHydrator.

        This implements Option A (MessageStore as Single Source of Truth):
        1. Hydrates MessageStore from JSONL
        2. Injects MessageStore into MemoryManager as conversation source
        3. Restores agent runtime state (todos, etc.)

        The key innovation is that resumed sessions use the SAME code path
        as fresh sessions - MemoryManager.get_context_for_llm() always provides
        conversation history, whether from MessageStore (resumed) or WorkingMemory (legacy).

        Args:
            jsonl_path: Path to session.jsonl file

        Returns:
            HydrationResult with store, base_llm_messages, agent_state, report

        Usage:
            result = agent.resume_session_from_jsonl(Path(".clarity/sessions/abc/session.jsonl"))
            # MemoryManager now uses MessageStore for conversation history
            # agent.todo_state is restored
        """
        from src.session import SessionHydrator, HydrationResult

        hydrator = SessionHydrator()
        result = hydrator.hydrate(jsonl_path)

        # Store session reference
        self._session_store = result.store

        # Extract session_id from hydration result
        session_id = result.report.session_id

        # OPTION A: Inject MessageStore into MemoryManager as single source of truth
        # This replaces the old dual-path approach (_resumed_base_context + _sync_to_working_memory)
        # Now MemoryManager.get_context_for_llm() uses MessageStore directly
        self.memory.set_message_store(result.store, session_id)

        # Restore agent state
        if result.agent_state.todos:
            self.todo_state['todos'] = result.agent_state.todos
        if result.agent_state.current_todo_id:
            self.todo_state['current_todo_id'] = result.agent_state.current_todo_id
        if result.agent_state.last_stop_reason:
            self.todo_state['last_stop_reason'] = result.agent_state.last_stop_reason

        # Update _next_id based on restored todos
        if result.agent_state.todos:
            max_id = max(
                (int(t.get('id', '0').split('-')[-1]) for t in result.agent_state.todos if t.get('id')),
                default=0
            )
            self.todo_state['_next_id'] = max_id + 1

        from src.observability import get_logger
        logger = get_logger(__name__)
        logger.info(f"Session resumed: {result.report.context_messages} context messages, "
                   f"todos={len(result.agent_state.todos)}, using MessageStore")

        return result

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
        current_mode = self.permission_manager.get_mode()
        permission_mode = PermissionManager.from_string(mode)
        self.permission_manager.set_mode(permission_mode)

        # Handle plan mode state transitions
        if permission_mode == PermissionMode.PLAN and current_mode != PermissionMode.PLAN:
            # Entering plan mode - activate plan mode state
            session_id = self._session_id or "default-session"
            if not self.plan_mode_state.is_active:
                self.plan_mode_state.enter(session_id)
        elif permission_mode != PermissionMode.PLAN and current_mode == PermissionMode.PLAN:
            # Leaving plan mode - deactivate plan mode state
            if self.plan_mode_state.is_active:
                self.plan_mode_state.reset()

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

    # -------------------------------------------------------------------------
    # Context Pressure Helpers
    # -------------------------------------------------------------------------

    def _get_pressure_level(self, used_tokens: int) -> str:
        """
        Get pressure level based on context utilization.

        Args:
            used_tokens: Number of tokens currently used

        Returns:
            Pressure level string: 'green', 'yellow', 'orange', or 'red'
        """
        if self.context_builder.max_context_tokens <= 0:
            logger.warning(
                f"Invalid max_context_tokens: {self.context_builder.max_context_tokens}"
            )
            return "green"

        utilization = used_tokens / self.context_builder.max_context_tokens

        if utilization >= 0.95:
            return "red"
        elif utilization >= 0.85:
            return "orange"
        elif utilization >= 0.70:
            return "yellow"
        else:
            return "green"

    # -------------------------------------------------------------------------
    # Error Recovery Helpers
    # -------------------------------------------------------------------------

    def _format_oversized_output_error(
        self,
        output_size: int,
        tool_name: str,
        tool_args: Dict[str, Any],
        tool_call_id: str
    ) -> tuple:
        """
        Format error response for oversized tool output.

        This is the unified helper for handling outputs that exceed
        _max_tool_output_chars, providing consistent error messages
        and data structures across sync/async/streaming code paths.

        Args:
            output_size: Size of the output in characters
            tool_name: Name of the tool that generated the output
            tool_args: Arguments passed to the tool
            tool_call_id: ID of the tool call

        Returns:
            Tuple of (error_msg, tool_message_dict, history_entry_dict)
        """
        error_msg = (
            f"Error: Output too large ({output_size:,} characters, "
            f"limit is {self._max_tool_output_chars:,}). "
            f"For read_file: use offset and limit parameters to read specific portions of the file. "
            f"For grep/search: use head_limit parameter to limit results. "
            f"For command output: consider piping through head/tail."
        )

        tool_message = {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": error_msg
        }

        history_entry = {
            "tool": tool_name,
            "arguments": tool_args,
            "success": False,
            "error": error_msg
        }

        return error_msg, tool_message, history_entry

    def _classify_tool_error(self, error_message: str) -> str:
        """
        Classify tool error into error type for recovery tracking.

        Args:
            error_message: The error message from tool execution

        Returns:
            Error type string (file_not_found, permission, command_failed, etc.)
        """
        error_lower = error_message.lower()

        # File/path errors
        if "not found" in error_lower or "no such file" in error_lower:
            return "file_not_found"
        if "directory" in error_lower and ("not found" in error_lower or "does not exist" in error_lower):
            return "directory_not_found"

        # Permission errors
        if "permission" in error_lower or "access denied" in error_lower or "forbidden" in error_lower:
            return "permission_denied"

        # Command execution errors
        if "command not found" in error_lower or "not recognized" in error_lower:
            return "command_not_found"
        if "exit code" in error_lower or "returned" in error_lower and "error" in error_lower:
            return "command_failed"
        if "timeout" in error_lower:
            return "timeout"

        # Edit/patch errors
        if "old_string not found" in error_lower or "no match" in error_lower:
            return "edit_no_match"
        if "conflict" in error_lower or "merge" in error_lower:
            return "edit_conflict"

        # Git errors
        if "git" in error_lower:
            if "uncommitted" in error_lower or "working tree" in error_lower:
                return "git_dirty"
            if "conflict" in error_lower:
                return "git_conflict"
            return "git_error"

        # Network errors
        if "connection" in error_lower or "network" in error_lower:
            return "network_error"

        # Generic tool error
        return "tool_execution_error"

    def _format_stop_explanation(self, reason: str, error_context: ErrorContext) -> str:
        """
        Generate clear user-facing explanation with actionable next steps.

        Args:
            reason: Reason for stopping (from should_allow_retry)
            error_context: Structured error context

        Returns:
            Formatted markdown explanation for the user
        """
        attempts = "\n".join(
            f"  - {a['tool']}: {a['result_summary']}"
            for a in error_context.previous_attempts
        )

        # Generate specific actionable suggestions
        action_menu = self._generate_action_menu(error_context)

        return f"""

---
**I was unable to complete this task.**

**What failed:** {error_context.tool_name}
**Error:** {error_context.error_message}
**Reason for stopping:** {reason}

**What I tried:**
{attempts if attempts else "  (first attempt)"}

**Suggested next steps:**
{action_menu}

---
"""

    def _generate_action_menu(self, error_context: ErrorContext) -> str:
        """
        Generate SPECIFIC actionable next steps based on error type.

        Args:
            error_context: Structured error context

        Returns:
            Formatted markdown list of suggestions
        """
        error_msg = error_context.error_message.lower()
        tool = error_context.tool_name

        suggestions = []

        # File/path related errors
        if "not found" in error_msg or "no such file" in error_msg:
            suggestions.append("1. **Verify the path** - Run `ls` or `dir` in the parent directory")
            suggestions.append("2. **Search for the file** - Tell me what the file contains and I'll search")
            if error_context.tool_args.get("file_path"):
                path = error_context.tool_args["file_path"]
                suggestions.append(f"3. **Confirm location** - Is `{path}` the correct path?")

        # Permission errors
        elif "permission" in error_msg or "access denied" in error_msg:
            suggestions.append("1. **Check permissions** - Run `ls -la` on the file")
            suggestions.append("2. **Run as admin** - You may need elevated privileges")
            suggestions.append("3. **Choose different location** - Save to a directory you own")

        # Command execution errors
        elif tool == "run_command":
            suggestions.append("1. **Check command syntax** - Copy and run manually to debug")
            if error_context.stderr_tail:
                suggestions.append(f"2. **Review stderr** - `{error_context.stderr_tail[:100]}...`")
            suggestions.append("3. **Verify dependencies** - Is the required tool installed?")

        # Edit/patch errors
        elif tool in ("edit_file", "apply_patch"):
            suggestions.append("1. **Show me the file** - I'll read it first to verify content")
            suggestions.append("2. **Check for conflicts** - Has the file changed since I read it?")
            suggestions.append("3. **Manual edit** - Copy my suggested changes and apply manually")

        # Generic fallback
        if not suggestions:
            suggestions.append("1. **Provide more context** - What exactly are you trying to accomplish?")
            suggestions.append("2. **Share error details** - Run the command with `--verbose` if available")
            suggestions.append("3. **Try manual approach** - I can describe the steps for you to execute")

        return "\n".join(suggestions)

    # =========================================================================
    # Task Continuation Support Methods
    # NOTE: todo_state mutations assume single-threaded execution (CLI).
    # If concurrency is added, protect with an asyncio.Lock or equivalent.
    # =========================================================================

    def _normalize_text(self, text: str) -> str:
        """
        Normalize text for content matching across todo operations.

        Used by:
        - _merge_todos_with_stable_ids() for content matching
        - _is_destructive_todo_update() for ID recovery via content
        - Index fallback similarity check

        Normalization: strip, lowercase, collapse whitespace.
        """
        if not text:
            return ""
        return " ".join(text.strip().lower().split())

    def _merge_todos_with_stable_ids(
        self,
        new_todos: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Merge new todos with existing ones, preserving stable IDs.

        This is critical for task continuation - if todo_write returns todos
        without preserving IDs, we need to match them to existing todos to
        maintain continuity.

        Matching priority:
        1. Explicit ID match (if new todo has ID that exists)
        2. Exact content match (normalized)
        3. Same index position (last resort for updates)
        4. Truly new item -> assign new ID

        Args:
            new_todos: List of todos from todo_write tool

        Returns:
            List of todos with stable IDs assigned
        """
        existing = self.todo_state.get('todos', [])
        existing_by_id = {t['id']: t for t in existing if 'id' in t}
        existing_by_content = {
            self._normalize_text(t.get('content', '')): t
            for t in existing if t.get('content')
        }

        used_ids = set()
        result = []

        for idx, new_todo in enumerate(new_todos):
            matched_id = None

            # Priority 1: Explicit ID match
            if 'id' in new_todo and new_todo['id'] in existing_by_id:
                matched_id = new_todo['id']

            # Priority 2: Exact content match (use 'if matched_id is None' to allow fallthrough)
            if matched_id is None and new_todo.get('content'):
                content_key = self._normalize_text(new_todo['content'])
                if content_key in existing_by_content:
                    matched_id = existing_by_content[content_key].get('id')

            # Priority 3: Same index position (fallback when content doesn't match)
            if matched_id is None and idx < len(existing) and 'id' in existing[idx]:
                # Only use index match if content is similar enough
                existing_content = existing[idx].get('content', '')
                new_content = new_todo.get('content', '')
                if existing_content and new_content:
                    # Simple similarity: same first 20 chars (normalized)
                    if self._normalize_text(existing_content)[:20] == self._normalize_text(new_content)[:20]:
                        matched_id = existing[idx]['id']

            # Assign ID
            if matched_id and matched_id not in used_ids:
                new_todo['id'] = matched_id
                used_ids.add(matched_id)
            elif 'id' not in new_todo or new_todo['id'] in used_ids:
                # Assign new ID
                new_todo['id'] = f"T{self.todo_state['_next_id']}"
                self.todo_state['_next_id'] += 1
                used_ids.add(new_todo['id'])

            result.append(new_todo)

        return result

    def _has_incomplete_todos(self) -> bool:
        """Check if there are any in_progress or pending todos."""
        todos = self.todo_state.get('todos', [])
        return any(
            t.get('status') in ('in_progress', 'pending')
            for t in todos
        )

    def _is_destructive_todo_update(self, new_todos: List[Dict]) -> bool:
        """
        Detect if todo_write would destructively overwrite incomplete work.

        Destructive = incomplete todo IDs are missing from new list.
        This is deterministic and hard to circumvent.

        Args:
            new_todos: The new todo list from todo_write

        Returns:
            True if this would drop incomplete todos (destructive)
        """
        existing = self.todo_state.get('todos', [])
        if not existing:
            return False  # No existing todos, can't be destructive

        # Get IDs of incomplete todos
        incomplete_ids = {
            t.get('id') for t in existing
            if t.get('status') in ('in_progress', 'pending') and t.get('id')
        }
        if not incomplete_ids:
            return False  # All complete, safe to replace

        # Get IDs in new list (check both explicit IDs and content-matched)
        new_ids = {t.get('id') for t in new_todos if t.get('id')}

        # Also try content matching for items without IDs (using shared normalization)
        existing_by_content = {
            self._normalize_text(t.get('content', '')): t.get('id')
            for t in existing if t.get('id')
        }
        for new_todo in new_todos:
            if 'id' not in new_todo and new_todo.get('content'):
                content_key = self._normalize_text(new_todo['content'])
                if content_key in existing_by_content:
                    new_ids.add(existing_by_content[content_key])

        # RULE: All incomplete IDs must be preserved
        missing_incomplete = incomplete_ids - new_ids
        if missing_incomplete:
            return True  # Would drop incomplete todos

        return False

    def _check_reset_intent(self, user_message: str) -> tuple:
        """
        Check if user explicitly wants to reset todos.

        Returns:
            Tuple of (is_reset, needs_confirmation)
            - (True, False) = explicit reset, allow immediately
            - (True, True) = loose reset language, needs confirmation
            - (False, False) = not a reset request
        """
        msg_lower = user_message.lower()

        # Explicit reset phrases - allow immediately
        explicit_reset = [
            "reset todos", "reset tasks", "reset the todos", "reset my todos",
            "clear todos", "clear tasks", "clear the todos",
            "discard previous", "discard todos", "discard tasks",
            "forget previous tasks", "forget todos"
        ]
        if any(phrase in msg_lower for phrase in explicit_reset):
            return (True, False)

        # Loose reset phrases - require confirmation
        loose_reset = ["start fresh", "start over"]
        if any(phrase in msg_lower for phrase in loose_reset):
            # Only if they don't also have explicit language
            has_explicit = any(w in msg_lower for w in ["reset", "clear", "discard"])
            if not has_explicit:
                return (True, True)  # Needs confirmation
            return (True, False)  # Has explicit, allow

        return (False, False)

    def _set_todo_in_progress(self, todo_id: str) -> None:
        """
        Set a todo to in_progress, auto-demoting others to pending.

        Enforces invariant: Only one in_progress at a time.

        Args:
            todo_id: ID of the todo to set as in_progress
        """
        for todo in self.todo_state.get('todos', []):
            if todo.get('id') == todo_id:
                todo['status'] = 'in_progress'
                self.todo_state['current_todo_id'] = todo_id
            elif todo.get('status') == 'in_progress':
                # Demote to pending (was interrupted)
                todo['status'] = 'pending'

    def _build_pause_message(self, reason: str) -> str:
        """
        Build pause message and set agent state for resumption.

        Sets state (last_stop_reason, current_todo_id) and returns a
        user-visible message. Caller is responsible for yielding as TextDelta.

        Args:
            reason: Stop reason code (max_iterations, max_tool_calls,
                    max_wall_time, error_budget, user_interrupt, provider_error)

        Returns:
            Formatted pause message string for user display
        """
        # Set stop reason for next turn
        self.todo_state['last_stop_reason'] = reason

        # Preserve current_todo_id if we have an in_progress todo
        in_progress = next(
            (t for t in self.todo_state.get('todos', [])
             if t.get('status') == 'in_progress'),
            None
        )
        if in_progress:
            self.todo_state['current_todo_id'] = in_progress.get('id')

        # When Phase C lands, save checkpoint here:
        # self._save_checkpoint()

        # Build user-visible message
        incomplete = [t for t in self.todo_state.get('todos', [])
                      if t.get('status') in ('in_progress', 'pending')]

        # Map reason codes to human-readable text
        reason_text = {
            'max_iterations': 'iteration limit',
            'max_tool_calls': 'tool call limit',
            'max_wall_time': 'time limit',
            'user_interrupt': 'user interrupt',
            'error_budget': 'error limit',
            'provider_error': 'provider error - retry available',
        }.get(reason, reason)

        if incomplete:
            pending_summary = ", ".join(
                f"{t.get('id', '?')}: {t.get('content', '?')[:30]}..."
                for t in incomplete[:3]
            )
            message = f"\n\n---\n**Paused** ({reason_text}). Pending: {pending_summary}\nSend `?` to continue.\n"
        else:
            message = f"\n\n---\n**Paused** ({reason_text}). Send `?` to continue.\n"

        return message

    def _get_pending_todos_summary(self) -> list[str]:
        """
        Get summary of pending/in_progress todos for pause widget.

        Returns:
            List of truncated task descriptions
        """
        incomplete = [t for t in self.todo_state.get('todos', [])
                      if t.get('status') in ('in_progress', 'pending')]
        return [
            t.get('content', 'Unknown task')[:50]
            for t in incomplete[:5]
        ]

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
                logger.warning(f"SessionEnd hook error: {e}", exc_info=True)
