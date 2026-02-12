"""SubAgent implementation with independent context and shared capabilities.

A SubAgent is a lightweight wrapper that:
- Operates with its own conversation context (no pollution of main agent)
- Has specialized system prompts for domain expertise
- Uses the main agent's LLM and tools (no duplication)
- Has its own MessageStore and MemoryManager for persistence
- Returns structured results

Architecture:
- Own MessageStore instance (isolated from main session)
- Own MemoryManager instance (single writer to own store)
- SyncJSONLWriter for thread-safe transcript persistence
- Shares main agent's LLM and tools
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Callable, TYPE_CHECKING
from pathlib import Path
import time
import uuid

from src.observability import get_logger
from src.core.tool_status import ToolStatus
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
    """Lightweight subagent with specialized capabilities and own persistence.

    A SubAgent operates with isolated context and has its own persistence stack:
    - Own MessageStore instance (isolated from main session)
    - SyncJSONLWriter for transcript persistence
    - Shares main agent's LLM and tools (no duplication)

    This ensures:
    - No context pollution between main agent and subagent
    - Specialized system prompts for domain expertise
    - Consistent tool behavior (same tools as main agent)
    - Full transcript visibility for TUI

    Example:
        >>> config = SubAgentConfig.load("code-reviewer")
        >>> subagent = SubAgent(config, main_agent)
        >>> result = subagent.execute("Review src/auth.py for security")
        >>> print(result.output)
    """

    def __init__(
        self,
        config: 'SubAgentConfig',
        main_agent: 'AgentInterface',
        transcript_dir: Optional[Path] = None,
    ):
        """Initialize subagent with own persistence stack.

        Args:
            config: SubAgentConfig with name, description, system_prompt
            main_agent: Main agent (provides LLM and tools)
            transcript_dir: Directory for JSONL transcripts (default: .clarity/sessions/subagents/)
        """
        self.config = config
        self.main_agent = main_agent

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

        logger.info(
            f"SubAgent [{self.config.name}] initialized "
            f"(session={self.session_id}, using main agent's LLM and "
            f"{len(self.main_agent.tool_executor.tools)} tools)"
        )

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

        # Open transcript writer
        self._transcript_writer = SyncJSONLWriter(self._transcript_path)
        self._transcript_writer.open()

        # Subscribe to store notifications for transcript persistence
        self._store_unsubscribe = self._message_store.subscribe(
            self._on_store_notification
        )

        try:
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
                    "model": self.main_agent.llm.config.model_name,
                    "tools_available": list(self.main_agent.tool_executor.tools.keys()),
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
            # Cleanup: unsubscribe and close writer
            if self._store_unsubscribe:
                self._store_unsubscribe()
                self._store_unsubscribe = None

            if self._transcript_writer:
                self._transcript_writer.close()
                self._transcript_writer = None

    def _on_store_notification(self, notification) -> None:
        """Handle store notifications by writing to transcript.

        Args:
            notification: StoreNotification from MessageStore
        """
        if self._transcript_writer:
            self._transcript_writer.write_notification(notification)

    def _build_context(self, task_description: str) -> tuple[List[Dict[str, str]], str]:
        """Build fresh LLM context with specialized system prompt.

        Also adds the system and user messages to the MessageStore for persistence.

        Args:
            task_description: Task to execute

        Returns:
            Tuple of (messages for LLM, last message UUID for parent chaining)
        """
        from src.session.models.message import Message

        # Start with specialized system prompt from config
        system_message = self.config.system_prompt

        # Defensive check: warn if tool_executor has no workspace_root
        tool_exec = getattr(self.main_agent, 'tool_executor', None)
        if tool_exec and getattr(tool_exec, '_workspace_root', None) is None:
            logger.warning(
                f"SubAgent [{self.config.name}]: tool_executor._workspace_root is None - "
                f"file operations may use incorrect paths"
            )

        # Add working directory context so LLM uses correct paths
        working_dir = getattr(self.main_agent, 'working_directory', None)
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
        from src.tools.tool_schemas import ALL_TOOLS
        from src.session.models.message import Message

        # Exclude delegation and plan mode tools from subagent
        SUBAGENT_EXCLUDED_TOOLS = {"delegate_to_subagent", "enter_plan_mode", "request_plan_approval"}
        subagent_tools = [t for t in ALL_TOOLS if t.name not in SUBAGENT_EXCLUDED_TOOLS]

        current_context = context.copy()
        all_tool_calls = []
        parent_uuid = last_parent_uuid

        for iteration in range(max_iterations):
            # Check cancellation before each LLM call
            self._cancel_token.check_cancelled()

            logger.debug(f"SubAgent [{self.config.name}]: Iteration {iteration + 1}/{max_iterations}")

            # Native function calling - same as main agent
            llm_response = self.main_agent.llm.generate_with_tools(
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

                # Notify store: tool is RUNNING
                self._message_store.update_tool_state(
                    tool_call_id=tool_call_id,
                    status=ToolStatus.RUNNING,
                    tool_name=tool_name,
                    extra_metadata={"args_summary": args_summary},
                )

                try:
                    result = self.main_agent.tool_executor.execute_tool(
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
        final_response = self.main_agent.llm.generate_with_tools(
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
            "model": self.main_agent.llm.config.model_name,
            "tools_available": len(self.main_agent.tool_executor.tools)
        }
