"""In-process Python hooks system for AI Coding Agent.

This module provides a lightweight, high-performance hooks system that allows
users to customize agent behavior without modifying code.

Performance:
    - <1ms overhead per hook execution
    - Maintains 10x speed advantage over competitors
    - Synchronous execution (no async/await needed)

Example:
    Create a hooks.py file in .claraity/:

    ```python
    from src.hooks import PreToolUseContext, HookResult, HookDecision

    def validate_write(context: PreToolUseContext) -> HookResult:
        if not context.arguments['file_path'].endswith('.txt'):
            return HookResult(decision=HookDecision.DENY)
        return HookResult(decision=HookDecision.PERMIT)

    HOOKS = {
        'PreToolUse:write_file': [validate_write],
    }
    ```
"""

# Events and decisions
# Context types
from .context import (
    HookContext,
    NotificationContext,
    PostToolUseContext,
    PreCompactContext,
    PreToolUseContext,
    SessionEndContext,
    SessionStartContext,
    StopContext,
    SubagentStopContext,
    UserPromptSubmitContext,
)
from .events import (
    HookApproval,
    HookContinue,
    HookDecision,
    HookEvent,
)

# Manager and exceptions
from .manager import (
    HookBlockedError,
    HookLoadError,
    HookManager,
)

# Result types
from .result import (
    HookResult,
    NotificationResult,
    UserPromptResult,
)

__all__ = [
    # Events
    "HookEvent",
    "HookDecision",
    "HookContinue",
    "HookApproval",
    # Contexts
    "HookContext",
    "PreToolUseContext",
    "PostToolUseContext",
    "UserPromptSubmitContext",
    "NotificationContext",
    "SessionStartContext",
    "SessionEndContext",
    "PreCompactContext",
    "StopContext",
    "SubagentStopContext",
    # Results
    "HookResult",
    "UserPromptResult",
    "NotificationResult",
    # Manager
    "HookManager",
    "HookLoadError",
    "HookBlockedError",
]

__version__ = "1.0.0"
