"""Context objects passed to hook functions.

Each hook event receives a typed context object containing relevant
information about the event. These contexts use Pydantic for validation
and type safety.
"""

from datetime import datetime
from typing import Any, Dict, Optional, List
from pydantic import BaseModel, Field, ConfigDict


class HookContext(BaseModel):
    """Base context passed to all hooks.

    All specific context types inherit from this base class.
    """

    session_id: str = Field(..., description="Unique session identifier")
    event_type: str = Field(..., description="Hook event type (e.g., 'PreToolUse')")
    timestamp: datetime = Field(
        default_factory=datetime.now,
        description="When the event occurred"
    )

    model_config = ConfigDict(arbitrary_types_allowed=True)


class PreToolUseContext(HookContext):
    """Context for PreToolUse hook.

    Passed to hooks before a tool is executed, allowing validation,
    argument modification, or blocking.

    Example:
        def validate_write(context: PreToolUseContext) -> HookResult:
            if not context.arguments['file_path'].endswith('.txt'):
                return HookResult(decision=HookDecision.DENY)
            return HookResult(decision=HookDecision.PERMIT)
    """

    tool: str = Field(..., description="Tool name being called (e.g., 'write_file')")
    arguments: Dict[str, Any] = Field(
        default_factory=dict,
        description="Tool arguments that will be passed to the tool"
    )
    step_id: Optional[int] = Field(
        None,
        description="Workflow step ID if this tool call is part of a workflow"
    )


class PostToolUseContext(HookContext):
    """Context for PostToolUse hook.

    Passed to hooks after a tool completes, allowing result inspection,
    modification, or logging.

    Example:
        def verify_write(context: PostToolUseContext) -> HookResult:
            if context.success:
                # Verify the file was written correctly
                pass
            return HookResult(decision=HookDecision.PERMIT)
    """

    tool: str = Field(..., description="Tool name that was called")
    arguments: Dict[str, Any] = Field(
        default_factory=dict,
        description="Tool arguments that were used"
    )
    result: Any = Field(..., description="Tool execution result")
    success: bool = Field(..., description="Whether tool execution succeeded")
    duration: float = Field(..., description="Execution time in seconds")
    error: Optional[str] = Field(None, description="Error message if tool failed")


class UserPromptSubmitContext(HookContext):
    """Context for UserPromptSubmit hook.

    Passed to hooks when user submits a prompt, allowing validation or
    modification before the LLM processes it.

    Example:
        def filter_sensitive(context: UserPromptSubmitContext) -> UserPromptResult:
            if 'password' in context.prompt.lower():
                return UserPromptResult(decision=HookContinue.BLOCK)
            return UserPromptResult(decision=HookContinue.CONTINUE)
    """

    prompt: str = Field(..., description="User's input prompt")
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata about the prompt"
    )


class NotificationContext(HookContext):
    """Context for Notification hook.

    Passed to hooks when agent requests user approval, allowing
    custom approval logic.

    Example:
        def auto_approve_safe(context: NotificationContext) -> NotificationResult:
            if context.risk_level == 'low':
                return NotificationResult(decision=HookApproval.APPROVE)
            return NotificationResult(decision=HookApproval.DENY)
    """

    notification_type: str = Field(..., description="Type of notification (e.g., 'approval_request')")
    message: str = Field(..., description="Notification message")
    step_info: Optional[Dict[str, Any]] = Field(
        None,
        description="Information about the step requiring approval"
    )
    risk_level: Optional[str] = Field(
        None,
        description="Risk level assessment (low/medium/high)"
    )


class SessionStartContext(HookContext):
    """Context for SessionStart hook.

    Passed to hooks when agent session starts, allowing initialization.

    Example:
        def init_logging(context: SessionStartContext) -> HookResult:
            setup_logger(context.working_directory)
            return HookResult(decision=HookDecision.PERMIT)
    """

    working_directory: str = Field(..., description="Current working directory")
    model_name: str = Field(..., description="LLM model being used")
    config: Dict[str, Any] = Field(
        default_factory=dict,
        description="Session configuration"
    )


class SessionEndContext(HookContext):
    """Context for SessionEnd hook.

    Passed to hooks when agent session ends, allowing cleanup and reporting.

    Example:
        def generate_report(context: SessionEndContext) -> HookResult:
            save_session_report(context.statistics)
            return HookResult(decision=HookDecision.PERMIT)
    """

    duration: float = Field(..., description="Total session duration in seconds")
    statistics: Dict[str, Any] = Field(
        default_factory=dict,
        description="Session statistics (tool calls, tokens used, etc.)"
    )
    exit_reason: str = Field(
        default="normal",
        description="Why session ended (normal/error/user_interrupt)"
    )


class PreCompactContext(HookContext):
    """Context for PreCompact hook.

    Passed to hooks before context compaction, allowing preservation
    of important messages.

    Example:
        def preserve_errors(context: PreCompactContext) -> HookResult:
            # Preserve all messages containing errors
            preserved = [msg for msg in context.messages_to_drop if 'error' in msg.lower()]
            return HookResult(
                decision=HookDecision.PERMIT,
                metadata={'preserve': preserved}
            )
    """

    current_tokens: int = Field(..., description="Current context token count")
    target_tokens: int = Field(..., description="Target token count after compaction")
    messages_to_drop: List[str] = Field(
        default_factory=list,
        description="Messages that will be dropped during compaction"
    )


class StopContext(HookContext):
    """Context for Stop hook.

    Passed to hooks after agent generates a response, allowing inspection
    or modification.

    Example:
        def log_response(context: StopContext) -> HookResult:
            logger.info(f"Agent response: {context.response[:100]}...")
            return HookResult(decision=HookDecision.PERMIT)
    """

    response: str = Field(..., description="Agent's generated response")
    tool_calls: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of tools called during this response generation"
    )
    execution_time: float = Field(..., description="Total execution time in seconds")


class SubagentStopContext(HookContext):
    """Context for SubagentStop hook.

    Passed to hooks when a subagent completes its task.

    Example:
        def verify_subagent(context: SubagentStopContext) -> HookResult:
            if context.duration > 300:  # 5 minutes
                logger.warning(f"Subagent {context.subagent_name} took too long")
            return HookResult(decision=HookDecision.PERMIT)
    """

    subagent_name: str = Field(..., description="Name/type of the subagent")
    result: Any = Field(..., description="Subagent execution result")
    duration: float = Field(..., description="Subagent execution time in seconds")
