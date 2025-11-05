"""Hook result types.

These classes define the return values that hook functions should return.
They use Pydantic for validation and type safety.
"""

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

from .events import HookDecision, HookContinue, HookApproval


class HookResult(BaseModel):
    """Result returned by most hook functions.

    This is the primary return type for hooks that can permit, deny, or block
    operations, and optionally modify arguments or results.

    Example:
        def my_hook(context: PreToolUseContext) -> HookResult:
            if not valid(context.arguments):
                return HookResult(
                    decision=HookDecision.DENY,
                    message="Invalid arguments"
                )

            # Modify arguments
            modified_args = context.arguments.copy()
            modified_args['validated'] = True

            return HookResult(
                decision=HookDecision.PERMIT,
                modified_arguments=modified_args
            )
    """

    decision: HookDecision = Field(
        default=HookDecision.PERMIT,
        description="Whether to permit, deny, or block the operation"
    )

    message: Optional[str] = Field(
        None,
        description="Optional message explaining the decision"
    )

    modified_arguments: Optional[Dict[str, Any]] = Field(
        None,
        description="Modified arguments to use instead of original (PreToolUse only)"
    )

    modified_result: Optional[Any] = Field(
        None,
        description="Modified result to return instead of original (PostToolUse only)"
    )

    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata for logging or debugging"
    )


class UserPromptResult(BaseModel):
    """Result returned by UserPromptSubmit hooks.

    Allows hooks to continue or block prompt processing, and optionally
    modify the prompt.

    Example:
        def filter_prompt(context: UserPromptSubmitContext) -> UserPromptResult:
            if contains_sensitive_data(context.prompt):
                return UserPromptResult(
                    decision=HookContinue.BLOCK,
                    message="Prompt contains sensitive data"
                )

            # Sanitize prompt
            sanitized = sanitize(context.prompt)
            return UserPromptResult(
                decision=HookContinue.CONTINUE,
                modified_prompt=sanitized
            )
    """

    decision: HookContinue = Field(
        default=HookContinue.CONTINUE,
        description="Whether to continue or block prompt processing"
    )

    modified_prompt: Optional[str] = Field(
        None,
        description="Modified prompt to use instead of original"
    )

    message: Optional[str] = Field(
        None,
        description="Optional message explaining the decision"
    )


class NotificationResult(BaseModel):
    """Result returned by Notification hooks.

    Allows hooks to approve or deny approval requests.

    Example:
        def auto_approve_safe(context: NotificationContext) -> NotificationResult:
            if context.risk_level == 'low':
                return NotificationResult(
                    decision=HookApproval.APPROVE,
                    message="Auto-approved low-risk operation"
                )

            return NotificationResult(
                decision=HookApproval.DENY,
                message="High-risk operation requires manual approval"
            )
    """

    decision: HookApproval = Field(
        default=HookApproval.APPROVE,
        description="Whether to approve or deny the request"
    )

    message: Optional[str] = Field(
        None,
        description="Optional message explaining the decision"
    )
