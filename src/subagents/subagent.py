"""SubAgent implementation with independent context and configurable capabilities.

A SubAgent is a lightweight wrapper that:
- Operates with its own conversation context (no pollution of main agent)
- Has specialized system prompts for domain expertise
- Can use its own LLM model or inherit the main agent's
- Can be scoped to specific tools via config.tools or inherit all
- Has its own MessageStore for persistence
- Returns structured results

Architecture:
- Own MessageStore instance (isolated from main session)
- SyncJSONLWriter for thread-safe transcript persistence
- Configurable LLM backend/model (config.llm) -- creates own backend instance
- Configurable tool allowlist (config.tools) -- filters available tools
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Callable, TYPE_CHECKING
from pathlib import Path
import time
import uuid

from src.observability import get_logger
from src.core.events import ToolStatus
from src.core.cancel_token import CancelToken, CancelledException
from .sync_writer import SyncJSONLWriter

if TYPE_CHECKING:
    from src.core.agent_interface import AgentInterface
    from src.subagents.config import SubAgentConfig
    from src.memory.memory_manager import MemoryManager
    from src.session.store.memory_store import MessageStore
    from src.session.subagent_registry import SubAgentSessionInfo

logger = get_logger(__name__)


# Default transcript directory (relative to project root)
DEFAULT_TRANSCRIPT_DIR = Path(".clarity/sessions/subagents")


@dataclass
class SubAgentResult:
    """Result from a subagent execution.

    Attributes:
        success: Whether execution succeeded
        subagent_name: Name of the subagent
        output: Primary output content
        metadata: Additional information (tools used, time, etc.)
        error: Error message if failed
        tool_calls: Tools that were called
        execution_time: Time taken in seconds
    """
    success: bool
    subagent_name: str
    output: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    execution_time: float = 0.0

    def __str__(self) -> str:
        """Human-readable representation."""
        status = "[OK] SUCCESS" if self.success else "[FAIL] FAILED"
        lines = [
            f"SubAgent [{self.subagent_name}]: {status}",
            f"Execution Time: {self.execution_time:.2f}s",
        ]

        if self.tool_calls:
            lines.append(f"Tools Used: {len(self.tool_calls)}")

        if self.error:
            lines.append(f"Error: {self.error}")

        if self.output and not self.error:
            preview = self.output[:200] + "..." if len(self.output) > 200 else self.output
            lines.append(f"Output: {preview}")

        return "\n".join(lines)


class SubAgent:
    """Lightweight subagent with configurable LLM model and tool access.

    A SubAgent operates with isolated context and its own persistence stack:
    - Own MessageStore instance (isolated from main session)
    - SyncJSONLWriter for transcript persistence
    - Configurable LLM backend/model via config.llm (or inherits main agent's)
    - Configurable tool allowlist via config.tools (or inherits all tools)

    This ensures:
    - No context pollution between main agent and subagent
    - Specialized system prompts for domain expertise
    - Per-subagent model selection (e.g., cheaper model for doc-writing)
    - Scoped tool access (e.g., read-only tools for code review)
    - Full transcript visibility for TUI

    Example:
        >>> config = SubAgentConfig.load("code-reviewer")
        >>> subagent = SubAgent(config, main_agent)
        >>> result = subagent.execute("Review src/auth.py for security")
        >>> print(result.output)
    """

    # Tools that require user approval in NORMAL permission mode
    RISKY_TOOLS = frozenset({
        'write_file', 'edit_file', 'append_to_file', 'run_command', 'git_commit',
    })

    def __init__(
        self,
        config: 'SubAgentConfig',
        main_agent: Optional['AgentInterface'] = None,
        transcript_dir: Optional[Path] = None,
        *,
        llm: Optional[Any] = None,
        tool_executor: Optional[Any] = None,
        working_directory: Optional[str] = None,
        permission_mode: str = "normal",
        approval_callback: Optional[Callable[[str, Dict[str, Any], str], tuple]] = None,
        auto_approve_tools: Optional[set] = None,
    ):
        """Initialize subagent with own persistence and configurable LLM/tools.

        Supports two modes:
        1. main_agent mode (existing): extract deps from main agent
        2. Direct injection (subprocess): provide llm, tool_executor, working_directory

        Args:
            config: SubAgentConfig with name, description, system_prompt,
                    and optional model/tools/context_window overrides
            main_agent: Main agent (provides default LLM, tools, and working directory).
                       Optional if llm and tool_executor are provided directly.
            transcript_dir: Directory for JSONL transcripts (default: .clarity/sessions/subagents/)
            llm: LLMBackend instance (direct injection for subprocess mode)
            tool_executor: ToolExecutor instance (direct injection for subprocess mode)
            working_directory: Working directory path (direct injection for subprocess mode)
            permission_mode: "normal" (ask for risky tools), "auto" (never ask), "plan" (read-only)
            approval_callback: Callable(tool_name, tool_args, tool_call_id) -> (approved, feedback)
            auto_approve_tools: Set of tool names pre-approved by the user (session-scoped)
        """
        self.config = config
        self.main_agent = main_agent  # May be None in subprocess mode

        # Tool approval settings (inherited from parent agent)
        self._permission_mode = permission_mode
        self._approval_callback = approval_callback
        self._auto_approve_tools: set = auto_approve_tools or set()

        # Resolve dependencies: direct injection or extract from main_agent
        if main_agent is not None:
            self._llm_source = main_agent.llm
            self._tool_executor = main_agent.tool_executor
            self._working_directory = getattr(main_agent, 'working_directory', None)
        else:
            if llm is None or tool_executor is None:
                raise ValueError(
                    "SubAgent requires either main_agent or both llm and tool_executor"
                )
            self._llm_source = llm
            self._tool_executor = tool_executor
            self._working_directory = working_directory

        # Generate unique session ID for this subagent
        self.session_id = str(uuid.uuid4())[:8]

        # Own persistence stack (same architecture as main session)
        # Import here to avoid circular import
        from src.session.store.memory_store import MessageStore
        self._message_store = MessageStore()

        # Transcript path
        self._transcript_dir = transcript_dir or DEFAULT_TRANSCRIPT_DIR
        self._transcript_path = self._transcript_dir / f"{config.name}-{self.session_id}.jsonl"

        # Transcript writer (opened during execute())
        self._transcript_writer: Optional[SyncJSONLWriter] = None

        # Store subscription unsubscribe function
        self._store_unsubscribe: Optional[Callable[[], None]] = None

        # Cancellation support
        self._cancel_token = CancelToken()

        # Track execution history
        self.execution_history: List[SubAgentResult] = []

        # Per-subagent LLM: create separate backend if llm overrides are set
        self._override_llm = None
        if self.config.llm and self.config.llm.has_overrides:
            self._override_llm = self._create_override_llm()

        # Log initialization with actual LLM and tool info
        model_name = self.llm.config.model_name
        model_source = "override" if self._override_llm else ("injected" if main_agent is None else "main agent")
        tool_info = (
            f"{len(self.config.tools)} configured"
            if self.config.tools
            else f"{len(self._tool_executor.tools)} inherited"
        )
        logger.info(
            f"SubAgent [{self.config.name}] initialized "
            f"(session={self.session_id}, model={model_name} [{model_source}], "
            f"tools={tool_info})"
        )

    @property
    def llm(self):
        """Return the LLM backend for this subagent.

        Uses the override LLM if config.llm has overrides, otherwise
        falls back to the injected LLM source. In both cases, the subagent
        maintains its own separate conversation context.
        """
        return self._override_llm or self._llm_source

    def _create_override_llm(self):
        """Create a separate LLM backend from config.llm overrides.

        Each field in SubAgentLLMConfig is optional. Omitted fields
        inherit from the main agent's LLM configuration.

        Supported backend types:
        - "openai" (and OpenAI-compatible: "vllm", "localai", "llamacpp")
        - "ollama"

        Returns:
            LLMBackend instance with overrides applied, or None on failure.
        """
        try:
            from src.llm import OpenAIBackend, OllamaBackend, LLMConfig

            llm_overrides = self.config.llm
            main_llm = self._llm_source
            main_config = main_llm.config

            # Resolve each field: override if set, else inherit from main
            backend_type = llm_overrides.backend_type or main_config.backend_type
            model_name = llm_overrides.model or main_config.model_name
            base_url = llm_overrides.base_url or main_config.base_url
            context_window = llm_overrides.context_window or main_config.context_window
            api_key = llm_overrides.api_key or getattr(main_llm, 'api_key', None)

            override_config = LLMConfig(
                backend_type=backend_type,
                model_name=model_name,
                base_url=base_url,
                context_window=context_window,
                temperature=main_config.temperature,
                max_tokens=main_config.max_tokens,
                top_p=main_config.top_p,
            )

            # Create the right backend class based on type
            OPENAI_COMPATIBLE = {"openai", "vllm", "localai", "llamacpp"}
            if backend_type in OPENAI_COMPATIBLE:
                override_llm = OpenAIBackend(
                    config=override_config, api_key=api_key,
                )
            elif backend_type == "ollama":
                override_llm = OllamaBackend(config=override_config)
            else:
                logger.warning(
                    f"SubAgent [{self.config.name}]: Unsupported backend_type "
                    f"'{backend_type}', falling back to main agent's LLM."
                )
                return None

            logger.info(
                f"SubAgent [{self.config.name}]: LLM override active "
                f"(backend={backend_type}, model={model_name}, "
                f"base_url={base_url})"
            )
            return override_llm

        except Exception as e:
            logger.warning(
                f"SubAgent [{self.config.name}]: Failed to create override LLM: "
                f"{e}. Falling back to main agent's LLM."
            )
            return None

    def _needs_approval(self, tool_name: str, tool_args: Dict[str, Any]) -> bool:
        """Check if a tool call requires user approval before execution.

        Mirrors the parent agent's needs_approval() logic:
        - AUTO mode: never ask
        - Tool already auto-approved by user: skip
        - Agent-internal writes (.clarity/): skip
        - NORMAL mode + risky tool: ask
        """
        if self._permission_mode == "auto":
            return False

        if tool_name in self._auto_approve_tools:
            return False

        from src.core.plan_mode import is_agent_internal_write
        if is_agent_internal_write(tool_name, tool_args):
            return False

        return tool_name in self.RISKY_TOOLS

    def cancel(self) -> None:
        """Signal cancellation to stop execution."""
        logger.info(f"SubAgent [{self.config.name}]: Cancel requested")
        self._cancel_token.cancel()

    def get_session_info(self) -> "SubAgentSessionInfo":
        """Return public session info for registry/UI wiring.

        This allows the delegation tool to register this subagent's
        store and transcript path with the UI without accessing private attributes.

        Returns:
            SubAgentSessionInfo with subagent_id, store, and transcript_path
        """
        from src.session.subagent_registry import SubAgentSessionInfo
        return SubAgentSessionInfo(
            subagent_id=self.session_id,
            store=self._message_store,
            transcript_path=self._transcript_path
        )

    def execute(
        self,
        task_description: str,
        context: Optional[Dict[str, Any]] = None,
        max_iterations: int = 50
    ) -> SubAgentResult:
        """Execute a task with this subagent.

        Opens transcript writer, subscribes to store notifications,
        executes the task, and cleans up resources.

        Args:
            task_description: Description of task to execute
            context: Optional additional context (currently unused, for future extension)
            max_iterations: Maximum tool-calling iterations (default: 50)

        Returns:
            SubAgentResult with execution details
        """
        start_time = time.time()

        logger.info(f"SubAgent [{self.config.name}]: Starting execution")
        logger.debug(f"Task: {task_description[:100]}...")

        try:
            # Open transcript writer (inside try so failures hit structured error handler)
            self._transcript_writer = SyncJSONLWriter(self._transcript_path)
            self._transcript_writer.open()

            # Subscribe to store notifications for transcript persistence
            self._store_unsubscribe = self._message_store.subscribe(
                self._on_store_notification
            )
            # Check cancellation before starting
            self._cancel_token.check_cancelled()

            # Build fresh context with specialized system prompt
            messages, last_uuid = self._build_context(task_description)

            # Execute with tool calling loop (using main agent's infrastructure)
            output, tool_calls = self._execute_with_tools(
                messages,
                max_iterations=max_iterations,
                last_parent_uuid=last_uuid,
            )

            # Create result
            execution_time = time.time() - start_time
            result = SubAgentResult(
                success=True,
                subagent_name=self.config.name,
                output=output,
                metadata={
                    "task_description": task_description,
                    "backend_type": self.llm.config.backend_type,
                    "model": self.llm.config.model_name,
                    "llm_override": self._override_llm is not None,
                    "tools_available": list(self._tool_executor.tools.keys()),
                    "tools_filtered": self.config.tools is not None,
                    "iterations": len(tool_calls),
                    "subagent_id": self.session_id,
                    "transcript_path": str(self._transcript_path),
                },
                tool_calls=tool_calls,
                execution_time=execution_time
            )

            # Track in history
            self.execution_history.append(result)

            logger.info(
                f"SubAgent [{self.config.name}]: [OK] Success "
                f"(time={execution_time:.2f}s, tools={len(tool_calls)})"
            )

            return result

        except CancelledException:
            execution_time = time.time() - start_time
            logger.info(f"SubAgent [{self.config.name}]: Cancelled by user")
            result = SubAgentResult(
                success=False,
                subagent_name=self.config.name,
                output="",
                metadata={
                    "task_description": task_description,
                    "cancelled": True,
                    "subagent_id": self.session_id,
                    "transcript_path": str(self._transcript_path),
                },
                error="Cancelled by user",
                execution_time=execution_time
            )
            self.execution_history.append(result)
            return result

        except Exception as e:
            execution_time = time.time() - start_time
            error_msg = f"SubAgent execution failed: {e}"
            logger.error(f"SubAgent [{self.config.name}]: [FAIL] {error_msg}")

            result = SubAgentResult(
                success=False,
                subagent_name=self.config.name,
                output="",
                metadata={
                    "task_description": task_description,
                    "error_type": type(e).__name__,
                    "subagent_id": self.session_id,
                    "transcript_path": str(self._transcript_path),
                },
                error=str(e),
                execution_time=execution_time
            )

            self.execution_history.append(result)

            return result

        finally:
            # Cleanup: each step wrapped independently so one failure
            # doesn't skip subsequent cleanup (prevents resource leaks)
            try:
                if self._store_unsubscribe:
                    self._store_unsubscribe()
                    self._store_unsubscribe = None
            except Exception as e:
                logger.warning(f"SubAgent [{self.config.name}]: unsubscribe failed: {e}")

            try:
                if self._transcript_writer:
                    self._transcript_writer.close()
                    self._transcript_writer = None
            except Exception as e:
                logger.warning(f"SubAgent [{self.config.name}]: writer close failed: {e}")

    def _on_store_notification(self, notification) -> None:
        """Handle store notifications by writing to transcript.

        Args:
            notification: StoreNotification from MessageStore
        """
        if self._transcript_writer:
            self._transcript_writer.write_notification(notification)

    def _resolve_tools(self, all_tools: List) -> List:
        """Build the filtered tool list for this subagent.

        1. Exclude tools that subagents must never use (delegation, plan mode)
        2. If config.tools is set, further filter to only those tools

        Args:
            all_tools: Full list of ToolDefinition objects from tool_schemas

        Returns:
            Filtered list of ToolDefinition objects
        """
        SUBAGENT_EXCLUDED_TOOLS = {
            "delegate_to_subagent", "enter_plan_mode", "request_plan_approval"
        }
        tools = [t for t in all_tools if t.name not in SUBAGENT_EXCLUDED_TOOLS]

        # Apply config.tools allowlist if specified
        if self.config.tools is not None:
            allowed = set(self.config.tools)
            available_names = {t.name for t in tools}
            missing = allowed - available_names
            if missing:
                logger.warning(
                    f"SubAgent [{self.config.name}]: Allowlist includes tools "
                    f"not found in executor: {sorted(missing)}"
                )
            tools = [t for t in tools if t.name in allowed]
            logger.debug(
                f"SubAgent [{self.config.name}]: Tool allowlist active - "
                f"{len(tools)} tools available: {[t.name for t in tools]}"
            )

        return tools

    def _load_project_instructions(self) -> str:
        """Load CLARAITY.md project instructions from the working directory.

        Looks for CLARAITY.md in the working directory (case-insensitive).
        Returns the file contents if found, empty string otherwise.
        """
        working_dir = self._working_directory
        if not working_dir:
            return ""

        working_path = Path(working_dir)
        # Check common casing variants
        for filename in ("CLARAITY.md", "claraity.md", "Claraity.md"):
            instructions_path = working_path / filename
            try:
                if instructions_path.is_file():
                    content = instructions_path.read_text(encoding="utf-8")
                    if content.strip():
                        logger.info(
                            f"SubAgent [{self.config.name}]: Loaded project "
                            f"instructions from {instructions_path}"
                        )
                        return content.strip()
            except (OSError, UnicodeDecodeError) as e:
                logger.warning(
                    f"SubAgent [{self.config.name}]: Failed to read "
                    f"{instructions_path}: {e}"
                )
        return ""

    def _build_context(self, task_description: str) -> tuple[List[Dict[str, str]], str]:
        """Build fresh LLM context with specialized system prompt.

        Assembles the system message from three layers:
        1. SUBAGENT_BASE_PROMPT -- universal rules for all subagents
        2. config.system_prompt -- role-specific instructions
        3. CLARAITY.md -- project-specific conventions (if found)
        4. Working directory context

        Also adds the system and user messages to the MessageStore for persistence.

        Args:
            task_description: Task to execute

        Returns:
            Tuple of (messages for LLM, last message UUID for parent chaining)
        """
        from src.session.models.message import Message
        from src.prompts.subagents import SUBAGENT_BASE_PROMPT

        # Layer 1: Universal base prompt + Layer 2: Role-specific prompt
        system_message = SUBAGENT_BASE_PROMPT + "\n\n" + self.config.system_prompt

        # Defensive check: warn if tool_executor has no workspace_root
        if self._tool_executor and getattr(self._tool_executor, '_workspace_root', None) is None:
            logger.warning(
                f"SubAgent [{self.config.name}]: tool_executor._workspace_root is None - "
                f"file operations may use incorrect paths"
            )

        # Layer 3: Project-specific instructions from CLARAITY.md
        project_instructions = self._load_project_instructions()
        if project_instructions:
            system_message += (
                "\n\n# Project Instructions (from CLARAITY.md)\n\n"
                + project_instructions
            )

        # Layer 4: Working directory context so LLM uses correct paths
        working_dir = self._working_directory
        if working_dir:
            system_message += f"\n\n## Working Directory:\nThe current working directory is: {working_dir}\nAll file paths should be relative to this directory.\n"

        # Add system message to store
        system_msg = Message.create_system(
            content=system_message,
            session_id=self.session_id,
            seq=self._message_store.next_seq(),
        )
        self._message_store.add_message(system_msg)

        # Add user message to store
        user_msg = Message.create_user(
            content=task_description,
            session_id=self.session_id,
            parent_uuid=system_msg.uuid,
            seq=self._message_store.next_seq(),
        )
        self._message_store.add_message(user_msg)

        # Build fresh context (no conversation history - that's the point!)
        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": task_description}
        ]

        return messages, user_msg.uuid

    def _execute_with_tools(
        self,
        context: List[Dict[str, str]],
        max_iterations: int,
        last_parent_uuid: str = "",
    ) -> tuple[str, List[Dict[str, Any]]]:
        """Execute with tool calling loop using native function calling.

        Args:
            context: LLM context (messages)
            max_iterations: Maximum iterations
            last_parent_uuid: UUID of the last message (for parent chaining)

        Returns:
            Tuple of (final_output, tool_calls)
        """
        from src.llm.base import ToolDefinition
        from src.session.models.message import Message

        # Build tool definitions from the tool executor's registered tools
        all_tool_defs = [
            ToolDefinition(**t.get_schema())
            for t in self._tool_executor.tools.values()
        ]
        # Filter using existing _resolve_tools logic
        subagent_tools = self._resolve_tools(all_tool_defs)

        current_context = context.copy()
        all_tool_calls = []
        parent_uuid = last_parent_uuid

        for iteration in range(max_iterations):
            # Check cancellation before each LLM call
            self._cancel_token.check_cancelled()

            logger.debug(f"SubAgent [{self.config.name}]: Iteration {iteration + 1}/{max_iterations}")

            # Native function calling with this subagent's LLM
            llm_response = self.llm.generate_with_tools(
                messages=current_context,
                tools=subagent_tools,
                tool_choice="auto"
            )

            response_content = llm_response.content or ""
            tool_calls = llm_response.tool_calls

            if not tool_calls:
                # No tool calls - done
                logger.debug(f"SubAgent [{self.config.name}]: No tool calls, finishing")

                # Add final assistant message to store
                assistant_msg = Message.create_assistant(
                    content=response_content,
                    session_id=self.session_id,
                    parent_uuid=parent_uuid,
                    seq=self._message_store.next_seq(),
                )
                self._message_store.add_message(assistant_msg)

                return response_content, all_tool_calls

            # Build assistant message WITH tool_calls for context
            assistant_dict = {
                "role": "assistant",
                "content": response_content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    }
                    for tc in tool_calls
                ]
            }
            current_context.append(assistant_dict)

            # Also add to store (for persistence)
            # Pass the actual ToolCall objects from LLM response, not dicts
            assistant_msg = Message.create_assistant(
                content=response_content,
                session_id=self.session_id,
                parent_uuid=parent_uuid,
                seq=self._message_store.next_seq(),
                tool_calls=tool_calls  # Pass ToolCall objects directly
            )
            self._message_store.add_message(assistant_msg)
            parent_uuid = assistant_msg.uuid

            # Execute each tool call
            logger.debug(f"SubAgent [{self.config.name}]: Executing {len(tool_calls)} tool(s)")
            tool_messages = []

            for tc in tool_calls:
                # Check cancellation before each tool execution
                self._cancel_token.check_cancelled()

                tool_name = tc.function.name
                tool_args = tc.function.get_parsed_arguments()
                tool_call_id = tc.id  # Use LLM-generated ID (not custom)

                # Build compact args summary for UI display
                args_summary = ", ".join(
                    f'{k}="{v}"' if isinstance(v, str) else f"{k}={v}"
                    for k, v in list(tool_args.items())[:3]
                )

                # --- Clarify interception: can't use ClarifyTool.execute() in
                # subprocess (it calls input()). Route through same IPC callback.
                if tool_name == "clarify" and self._approval_callback:
                    import json as _json
                    self._message_store.update_tool_state(
                        tool_call_id=tool_call_id, status=ToolStatus.AWAITING_APPROVAL,
                        tool_name=tool_name, extra_metadata={"args_summary": args_summary},
                    )
                    _, clarify_result = self._approval_callback(tool_name, tool_args, tool_call_id)
                    result_dict = clarify_result if isinstance(clarify_result, dict) else {}
                    tool_messages.append({
                        "role": "tool", "tool_call_id": tool_call_id,
                        "name": tool_name, "content": _json.dumps(result_dict),
                    })
                    self._message_store.update_tool_state(
                        tool_call_id=tool_call_id, status=ToolStatus.SUCCESS,
                        tool_name=tool_name,
                    )
                    continue

                # --- Approval gate: ask user before executing risky tools ---
                if self._needs_approval(tool_name, tool_args):
                    self._message_store.update_tool_state(
                        tool_call_id=tool_call_id,
                        status=ToolStatus.AWAITING_APPROVAL,
                        tool_name=tool_name,
                        extra_metadata={"args_summary": args_summary},
                    )

                    if self._approval_callback:
                        approved, feedback = self._approval_callback(
                            tool_name, tool_args, tool_call_id
                        )
                    else:
                        # No callback (shouldn't happen) - safe default: reject
                        approved, feedback = False, None

                    if not approved:
                        rejection_msg = (
                            f"User rejected with feedback: {feedback}"
                            if feedback
                            else "Tool call rejected by user"
                        )
                        self._message_store.update_tool_state(
                            tool_call_id=tool_call_id,
                            status=ToolStatus.REJECTED,
                            tool_name=tool_name,
                        )
                        tool_messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "name": tool_name,
                            "content": rejection_msg,
                        })
                        all_tool_calls.append({
                            "tool": tool_name, "arguments": tool_args,
                            "args_summary": args_summary, "success": False,
                            "result": None, "error": rejection_msg,
                            "tool_call_id": tool_call_id,
                        })
                        if feedback:
                            # Feedback: LLM sees the guidance and can retry
                            continue
                        else:
                            # Hard rejection: stop the subagent
                            break
                    # Approved
                    self._message_store.update_tool_state(
                        tool_call_id=tool_call_id,
                        status=ToolStatus.APPROVED,
                        tool_name=tool_name,
                    )

                # Notify store: tool is RUNNING
                self._message_store.update_tool_state(
                    tool_call_id=tool_call_id,
                    status=ToolStatus.RUNNING,
                    tool_name=tool_name,
                    extra_metadata={"args_summary": args_summary},
                )

                try:
                    # Defense-in-depth: block tools not in the allowlist
                    allowed_tool_names = {t.name for t in subagent_tools}
                    if tool_name not in allowed_tool_names:
                        logger.warning(
                            f"SubAgent [{self.config.name}]: Blocked tool "
                            f"'{tool_name}'. Allowed: {sorted(allowed_tool_names)}. "
                            f"Config allowlist: {self.config.tools}"
                        )
                        raise PermissionError(
                            f"Tool '{tool_name}' is not allowed for "
                            f"subagent '{self.config.name}'"
                        )

                    result = self._tool_executor.execute_tool(
                        tool_name, **tool_args
                    )

                    if result.is_success():
                        output = str(result.output)
                        tool_messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "name": tool_name,
                            "content": output,
                        })
                        all_tool_calls.append({
                            "tool": tool_name, "arguments": tool_args,
                            "args_summary": args_summary, "success": True,
                            "result": result.output, "error": None,
                            "tool_call_id": tool_call_id,
                        })
                        self._message_store.update_tool_state(
                            tool_call_id=tool_call_id,
                            status=ToolStatus.SUCCESS,
                            result=output, tool_name=tool_name,
                        )
                    else:
                        error_content = f"Error: {result.error}"
                        tool_messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "name": tool_name,
                            "content": error_content,
                        })
                        all_tool_calls.append({
                            "tool": tool_name, "arguments": tool_args,
                            "args_summary": args_summary, "success": False,
                            "result": None, "error": result.error,
                            "tool_call_id": tool_call_id,
                        })
                        self._message_store.update_tool_state(
                            tool_call_id=tool_call_id,
                            status=ToolStatus.ERROR,
                            error=result.error, tool_name=tool_name,
                        )
                except Exception as e:
                    error_content = f"Exception: {str(e)}"
                    tool_messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "name": tool_name,
                        "content": error_content,
                    })
                    all_tool_calls.append({
                        "tool": tool_name, "arguments": tool_args,
                        "args_summary": args_summary, "success": False,
                        "result": None, "error": str(e),
                        "tool_call_id": tool_call_id,
                    })
                    self._message_store.update_tool_state(
                        tool_call_id=tool_call_id,
                        status=ToolStatus.ERROR,
                        error=str(e), tool_name=tool_name,
                    )

            # Add tool messages to context (role: "tool")
            current_context.extend(tool_messages)

            # Add tool messages to store (for persistence)
            for tool_msg_dict in tool_messages:
                tool_msg = Message.create_tool(
                    tool_call_id=tool_msg_dict["tool_call_id"],
                    content=tool_msg_dict["content"],
                    session_id=self.session_id,
                    parent_uuid=parent_uuid,
                    seq=self._message_store.next_seq(),
                )
                self._message_store.add_message(tool_msg)
                parent_uuid = tool_msg.uuid

        # Max iterations reached - generate summary with tool_choice="none"
        logger.warning(f"SubAgent [{self.config.name}]: Max iterations reached")

        current_context.append({
            "role": "user",
            "content": "You've reached the maximum number of tool iterations. Based on the information gathered, provide a clear, concise answer."
        })

        # Add summary prompt to store
        summary_msg = Message.create_user(
            content="You've reached the maximum number of tool iterations. Based on the information gathered, provide a clear, concise answer.",
            session_id=self.session_id,
            parent_uuid=parent_uuid,
            seq=self._message_store.next_seq(),
        )
        self._message_store.add_message(summary_msg)
        parent_uuid = summary_msg.uuid

        self._cancel_token.check_cancelled()
        final_response = self.llm.generate_with_tools(
            messages=current_context, tools=subagent_tools, tool_choice="none"
        )

        # Add final assistant message to store
        final_msg = Message.create_assistant(
            content=final_response.content or "",
            session_id=self.session_id,
            parent_uuid=parent_uuid,
            seq=self._message_store.next_seq(),
        )
        self._message_store.add_message(final_msg)

        return final_response.content or "", all_tool_calls

    def get_statistics(self) -> Dict[str, Any]:
        """Get subagent statistics.

        Returns:
            Statistics dictionary
        """
        total_executions = len(self.execution_history)
        successful = sum(1 for r in self.execution_history if r.success)
        failed = total_executions - successful

        total_time = sum(r.execution_time for r in self.execution_history)
        avg_time = total_time / total_executions if total_executions > 0 else 0

        total_tools = sum(len(r.tool_calls) for r in self.execution_history)
        avg_tools = total_tools / total_executions if total_executions > 0 else 0

        return {
            "subagent_name": self.config.name,
            "total_executions": total_executions,
            "successful": successful,
            "failed": failed,
            "success_rate": successful / total_executions if total_executions > 0 else 0,
            "total_execution_time": total_time,
            "average_execution_time": avg_time,
            "total_tool_calls": total_tools,
            "average_tool_calls": avg_tools,
            "backend_type": self.llm.config.backend_type,
            "model": self.llm.config.model_name,
            "llm_override": self._override_llm is not None,
            "tools_available": len(self._tool_executor.tools),
            "tools_filtered": self.config.tools is not None,
        }
