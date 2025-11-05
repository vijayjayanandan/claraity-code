"""In-process Python hooks system for AI Coding Agent.

This module provides a lightweight, high-performance hooks system that allows
users to customize agent behavior without modifying code.

Performance:
    - <1ms overhead per hook execution
    - Maintains 10x speed advantage over competitors
    - Synchronous execution (no async/await needed)

Example:
    Create a hooks.py file in .claude/:

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
from .events import (
    HookEvent,
    HookDecision,
    HookContinue,
    HookApproval,
)

# Context types
from .context import (
    HookContext,
    PreToolUseContext,
    PostToolUseContext,
    UserPromptSubmitContext,
    NotificationContext,
    SessionStartContext,
    SessionEndContext,
    PreCompactContext,
    StopContext,
    SubagentStopContext,
)

# Result types
from .result import (
    HookResult,
    UserPromptResult,
    NotificationResult,
)

# Manager and exceptions
from .manager import (
    HookManager,
    HookLoadError,
    HookBlockedError,
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
