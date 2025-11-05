# In-Process Python Hooks Architecture - Design Document

**Version:** 2.0 (In-Process Design)
**Date:** 2025-10-17
**Status:** Implementation Ready
**Approach:** In-Process Python Functions (NOT Subprocess)

---

## EXECUTIVE SUMMARY

### Design Decision: In-Process Python Hooks

**Rationale:**
- **Performance:** <1ms overhead vs 50-200ms for subprocess
- **Maintains competitive advantage:** 10x faster direct tool execution preserved
- **Synchronous:** Works with 100% synchronous codebase (no async/await needed)
- **Type-safe:** Python type hints, IDE support, debuggable
- **Simpler:** 800 lines vs 1,200 lines, 6 days vs 10 days

**Trade-off Accepted:**
- Python-only (no Bash/Node.js scripts) - covers 95% of real use cases
- No process isolation - user's hook code runs in agent process

### Key Metrics
- **Timeline:** 6 days
- **Code Volume:** ~800 lines production + ~400 lines tests
- **Performance:** <1ms per hook execution (vs 50-200ms subprocess)
- **Test Coverage:** 58 tests, 90%+ coverage
- **Backward Compatible:** Zero breaking changes

---

## ARCHITECTURE OVERVIEW

### System Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    USER'S HOOK FILE                             │
│                   .claude/hooks.py                              │
│                                                                  │
│  def validate_write(context: PreToolUseContext):                │
│      if not context.arguments['file_path'].endswith('.txt'):   │
│          return HookResult(decision=HookDecision.DENY)          │
│      return HookResult(decision=HookDecision.PERMIT)            │
│                                                                  │
│  HOOKS = {                                                       │
│      'PreToolUse:write_file': [validate_write]                  │
│  }                                                               │
└──────────────────────────┬──────────────────────────────────────┘
                           │ (imported as Python module)
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                       HookManager                               │
│  • Loads .claude/hooks.py at startup                            │
│  • Registers Python functions                                   │
│  • Emits events (synchronous function calls)                    │
│  • Enforces decisions (permit/deny/block)                       │
└───────────┬─────────────────────────────┬───────────────────────┘
            │                             │
            ▼                             ▼
┌───────────────────────┐      ┌────────────────────────┐
│   ToolExecutor        │      │    CodingAgent         │
│  • PreToolUse hook    │      │  • SessionStart hook   │
│  • PostToolUse hook   │      │  • UserPromptSubmit    │
│  • Synchronous calls  │      │  • Stop hook           │
└───────────────────────┘      └────────────────────────┘
```

### Data Flow: PreToolUse Hook (In-Process)

```
1. User requests: "Write hello.py"
   ↓
2. Agent determines tool: WriteFileTool
   ↓
3. ToolExecutor.execute_tool("write_file", file_path="hello.py", content="...")
   ↓
4. HookManager.emit_pre_tool_use(tool="write_file", arguments={...})
   ↓ (no subprocess, no serialization)
5. For each registered Python function:
   ↓
   5a. Direct function call: hook_func(context)  # <1ms
   ↓
   5b. Get result: HookResult(decision=PERMIT, modified_arguments={...})
   ↓
   5c. Enforce decision:
       - PERMIT: Continue with potentially modified arguments
       - DENY: Return error, tool not executed
       - BLOCK: Raise exception, abort workflow
   ↓
6. If all hooks permit: Execute actual tool with modified arguments
   ↓
7. Tool executes → Returns result
   ↓
8. HookManager.emit_post_tool_use(tool, result, ...)
   ↓
9. PostToolUse hooks can modify result before returning
```

**Performance:** Total hook overhead = 0.5-1ms (vs 50-200ms subprocess)

---

## COMPONENT SPECIFICATIONS

### Component 1: Hook Events (`src/hooks/events.py`)

**Purpose:** Define all hook event types and decision enums.

```python
"""Hook events and decision types for in-process Python hooks."""

from enum import Enum


class HookEvent(Enum):
    """All supported hook events."""
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    NOTIFICATION = "Notification"
    SESSION_START = "SessionStart"
    SESSION_END = "SessionEnd"
    PRE_COMPACT = "PreCompact"
    STOP = "Stop"
    SUBAGENT_STOP = "SubagentStop"


class HookDecision(Enum):
    """Decisions that hooks can make for PreToolUse."""
    PERMIT = "permit"   # Allow operation, proceed
    DENY = "deny"       # Reject operation, return error gracefully
    BLOCK = "block"     # Block operation, raise exception (hard failure)


class HookContinue(Enum):
    """Decisions for UserPromptSubmit."""
    CONTINUE = "continue"
    BLOCK = "block"


class HookApproval(Enum):
    """Decisions for Notification."""
    APPROVE = "approve"
    DENY = "deny"
```

**Lines:** ~50 lines
**Dependencies:** `enum` (stdlib)
**Tests:** 5 tests

---

### Component 2: Hook Contexts (`src/hooks/context.py`)

**Purpose:** Type-safe context dataclasses passed to hook functions.

```python
"""Context objects passed to hook functions."""

from datetime import datetime
from typing import Any, Dict, Optional, List
from pydantic import BaseModel, Field, ConfigDict


class HookContext(BaseModel):
    """Base context passed to all hooks."""
    session_id: str = Field(..., description="Unique session identifier")
    event_type: str = Field(..., description="Hook event type")
    timestamp: datetime = Field(default_factory=datetime.now)

    model_config = ConfigDict(arbitrary_types_allowed=True)


class PreToolUseContext(HookContext):
    """Context for PreToolUse hook."""
    tool: str = Field(..., description="Tool name being called")
    arguments: Dict[str, Any] = Field(default_factory=dict)
    step_id: Optional[int] = Field(None, description="Workflow step ID")


class PostToolUseContext(HookContext):
    """Context for PostToolUse hook."""
    tool: str
    arguments: Dict[str, Any]
    result: Any = Field(..., description="Tool execution result")
    success: bool = Field(..., description="Whether tool succeeded")
    duration: float = Field(..., description="Execution time in seconds")
    error: Optional[str] = Field(None, description="Error message if failed")


class UserPromptSubmitContext(HookContext):
    """Context for UserPromptSubmit hook."""
    prompt: str = Field(..., description="User's input prompt")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class NotificationContext(HookContext):
    """Context for Notification hook (approval requests)."""
    notification_type: str
    message: str
    step_info: Optional[Dict[str, Any]] = None
    risk_level: Optional[str] = None


class SessionStartContext(HookContext):
    """Context for SessionStart hook."""
    working_directory: str
    model_name: str
    config: Dict[str, Any] = Field(default_factory=dict)


class SessionEndContext(HookContext):
    """Context for SessionEnd hook."""
    duration: float
    statistics: Dict[str, Any] = Field(default_factory=dict)
    exit_reason: str = Field(default="normal")


class PreCompactContext(HookContext):
    """Context for PreCompact hook."""
    current_tokens: int
    target_tokens: int
    messages_to_drop: List[str] = Field(default_factory=list)


class StopContext(HookContext):
    """Context for Stop hook."""
    response: str
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    execution_time: float


class SubagentStopContext(HookContext):
    """Context for SubagentStop hook."""
    subagent_name: str
    result: Any
    duration: float
```

**Lines:** ~150 lines
**Dependencies:** `pydantic`, `datetime`, `typing`
**Tests:** 18 tests

---

### Component 3: Hook Results (`src/hooks/result.py`)

**Purpose:** Return type for hook functions.

```python
"""Hook result types."""

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field
from .events import HookDecision, HookContinue, HookApproval


class HookResult(BaseModel):
    """Result returned by hook functions."""
    decision: HookDecision = Field(default=HookDecision.PERMIT)
    message: Optional[str] = Field(None, description="Optional message")
    modified_arguments: Optional[Dict[str, Any]] = Field(None)
    modified_result: Optional[Any] = Field(None)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class UserPromptResult(BaseModel):
    """Result for UserPromptSubmit hooks."""
    decision: HookContinue = Field(default=HookContinue.CONTINUE)
    modified_prompt: Optional[str] = None
    message: Optional[str] = None


class NotificationResult(BaseModel):
    """Result for Notification hooks."""
    decision: HookApproval = Field(default=HookApproval.APPROVE)
    message: Optional[str] = None
```

**Lines:** ~50 lines
**Tests:** 5 tests

---

### Component 4: Hook Manager (`src/hooks/manager.py`)

**Purpose:** Central orchestration - load hooks, register, emit events.

```python
"""In-process Python hooks manager."""

import logging
import importlib.util
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from datetime import datetime
import uuid

from .events import HookEvent, HookDecision, HookContinue
from .context import (
    PreToolUseContext, PostToolUseContext, UserPromptSubmitContext,
    NotificationContext, SessionStartContext, SessionEndContext,
    PreCompactContext, StopContext, SubagentStopContext
)
from .result import HookResult, UserPromptResult, NotificationResult

logger = logging.getLogger(__name__)


class HookManager:
    """
    In-process Python hooks manager.

    Loads Python hook functions from .claude/hooks.py and executes them
    synchronously (no subprocess, no async/await).

    Performance: <1ms per hook execution
    """

    def __init__(
        self,
        hooks_file: Optional[Path] = None,
        session_id: Optional[str] = None
    ):
        """
        Initialize hook manager.

        Args:
            hooks_file: Path to hooks.py file (default: .claude/hooks.py)
            session_id: Session identifier (generated if not provided)
        """
        self.session_id = session_id or str(uuid.uuid4())
        self.hooks: Dict[HookEvent, Dict[str, List[Callable]]] = {
            event: {} for event in HookEvent
        }
        self.logger = logging.getLogger(__name__)

        # Load hooks
        if hooks_file:
            self.load_hooks(hooks_file)
        else:
            self._load_default_hooks()

    def _load_default_hooks(self) -> None:
        """Load hooks from default locations."""
        hooks_paths = [
            Path("./.claude/hooks.py"),              # Project level
            Path.home() / ".claude" / "hooks.py",    # User level
        ]

        for path in hooks_paths:
            if path.exists():
                try:
                    self.load_hooks(path)
                    self.logger.info(f"Loaded hooks from {path}")
                    return
                except Exception as e:
                    self.logger.warning(f"Failed to load {path}: {e}")

        self.logger.info("No hooks file found, starting with empty registry")

    def load_hooks(self, hooks_file: Path) -> None:
        """
        Load hook functions from Python file.

        Expected format in hooks.py:

        HOOKS = {
            'PreToolUse:write_file': [validate_write_func],
            'PreToolUse:*': [log_all_func],
            'PostToolUse:write_file': [verify_write_func],
            'SessionStart': [init_func],
        }

        Args:
            hooks_file: Path to Python file with HOOKS dict

        Raises:
            HookLoadError: If file cannot be loaded or HOOKS not found
        """
        try:
            # Load Python module
            spec = importlib.util.spec_from_file_location("user_hooks", hooks_file)
            if not spec or not spec.loader:
                raise HookLoadError(f"Cannot load {hooks_file}")

            module = importlib.util.module_from_spec(spec)
            sys.modules["user_hooks"] = module
            spec.loader.exec_module(module)

            # Get HOOKS dict
            if not hasattr(module, 'HOOKS'):
                raise HookLoadError(f"No HOOKS dict found in {hooks_file}")

            hooks_config = module.HOOKS

            # Register hooks
            for pattern, hook_funcs in hooks_config.items():
                self._register_pattern(pattern, hook_funcs)

            self.logger.info(f"Successfully loaded hooks from {hooks_file}")

        except Exception as e:
            raise HookLoadError(f"Failed to load hooks from {hooks_file}: {e}")

    def _register_pattern(self, pattern: str, hook_funcs: List[Callable]) -> None:
        """
        Register hook functions for a pattern.

        Patterns:
        - 'PreToolUse:write_file' → PreToolUse event, write_file tool
        - 'PreToolUse:*' → PreToolUse event, all tools
        - 'SessionStart' → SessionStart event

        Args:
            pattern: Pattern string
            hook_funcs: List of hook functions
        """
        # Parse pattern
        if ':' in pattern:
            event_str, tool_pattern = pattern.split(':', 1)
        else:
            event_str = pattern
            tool_pattern = '*'

        # Get event enum
        try:
            event = HookEvent[event_str.upper().replace(' ', '_')]
        except KeyError:
            self.logger.error(f"Unknown event type: {event_str}")
            return

        # Register each function
        if tool_pattern not in self.hooks[event]:
            self.hooks[event][tool_pattern] = []

        for func in hook_funcs if isinstance(hook_funcs, list) else [hook_funcs]:
            self.hooks[event][tool_pattern].append(func)
            self.logger.debug(f"Registered hook: {event.value}:{tool_pattern} → {func.__name__}")

    def _get_matching_hooks(self, event: HookEvent, tool: Optional[str] = None) -> List[Callable]:
        """
        Get hooks matching the event and tool.

        Args:
            event: Hook event
            tool: Tool name (for PreToolUse/PostToolUse)

        Returns:
            List of matching hook functions
        """
        if event not in self.hooks:
            return []

        matching = []

        # Check wildcard hooks (*) first
        if '*' in self.hooks[event]:
            matching.extend(self.hooks[event]['*'])

        # Check tool-specific hooks
        if tool and tool in self.hooks[event]:
            matching.extend(self.hooks[event][tool])

        return matching

    # ========== EVENT EMISSION METHODS (SYNCHRONOUS) ==========

    def emit_pre_tool_use(
        self,
        tool: str,
        arguments: Dict[str, Any],
        step_id: Optional[int] = None
    ) -> Tuple[HookDecision, Dict[str, Any]]:
        """
        Emit PreToolUse hook (synchronous, <1ms).

        Args:
            tool: Tool name
            arguments: Tool arguments
            step_id: Workflow step ID

        Returns:
            (decision, modified_arguments)

        Raises:
            HookBlockedError: If hook blocks operation
        """
        hooks = self._get_matching_hooks(HookEvent.PRE_TOOL_USE, tool)

        if not hooks:
            return HookDecision.PERMIT, arguments

        self.logger.debug(f"Emitting PreToolUse for {tool} ({len(hooks)} hooks)")

        # Prepare context
        context = PreToolUseContext(
            session_id=self.session_id,
            event_type=HookEvent.PRE_TOOL_USE.value,
            tool=tool,
            arguments=arguments.copy(),
            step_id=step_id
        )

        modified_args = arguments.copy()

        # Execute each hook (synchronous)
        for hook_func in hooks:
            try:
                # Direct function call - no subprocess, no serialization
                result = hook_func(context)

                # Handle decision
                if result.decision == HookDecision.DENY:
                    self.logger.info(f"Hook DENIED {tool}: {result.message}")
                    return HookDecision.DENY, arguments

                elif result.decision == HookDecision.BLOCK:
                    self.logger.error(f"Hook BLOCKED {tool}: {result.message}")
                    raise HookBlockedError(f"Tool {tool} blocked by hook: {result.message}")

                # Apply modified arguments
                if result.modified_arguments:
                    modified_args.update(result.modified_arguments)
                    self.logger.debug(f"Hook modified arguments for {tool}")

                # Update context for next hook
                context.arguments = modified_args

            except HookBlockedError:
                raise
            except Exception as e:
                self.logger.error(f"Hook error for {tool}: {e}", exc_info=True)
                # Continue to next hook

        return HookDecision.PERMIT, modified_args

    def emit_post_tool_use(
        self,
        tool: str,
        arguments: Dict[str, Any],
        result: Any,
        success: bool,
        duration: float,
        error: Optional[str] = None
    ) -> Optional[Any]:
        """
        Emit PostToolUse hook (synchronous, <1ms).

        Args:
            tool: Tool name
            arguments: Tool arguments used
            result: Tool result
            success: Whether tool succeeded
            duration: Execution time
            error: Error message if failed

        Returns:
            Modified result if any hook modifies it, else None
        """
        hooks = self._get_matching_hooks(HookEvent.POST_TOOL_USE, tool)

        if not hooks:
            return None

        self.logger.debug(f"Emitting PostToolUse for {tool} ({len(hooks)} hooks)")

        context = PostToolUseContext(
            session_id=self.session_id,
            event_type=HookEvent.POST_TOOL_USE.value,
            tool=tool,
            arguments=arguments,
            result=result,
            success=success,
            duration=duration,
            error=error
        )

        modified_result = None

        for hook_func in hooks:
            try:
                hook_result = hook_func(context)

                # Check for modified result
                if hook_result.modified_result is not None:
                    modified_result = hook_result.modified_result
                    self.logger.debug(f"Hook modified result for {tool}")

            except Exception as e:
                self.logger.error(f"PostToolUse hook error for {tool}: {e}", exc_info=True)

        return modified_result

    def emit_user_prompt_submit(
        self,
        prompt: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Tuple[HookContinue, str]:
        """
        Emit UserPromptSubmit hook.

        Args:
            prompt: User's input
            metadata: Additional metadata

        Returns:
            (decision, modified_prompt)

        Raises:
            HookBlockedError: If hook blocks prompt
        """
        hooks = self._get_matching_hooks(HookEvent.USER_PROMPT_SUBMIT)

        if not hooks:
            return HookContinue.CONTINUE, prompt

        context = UserPromptSubmitContext(
            session_id=self.session_id,
            event_type=HookEvent.USER_PROMPT_SUBMIT.value,
            prompt=prompt,
            metadata=metadata or {}
        )

        modified_prompt = prompt

        for hook_func in hooks:
            try:
                result = hook_func(context)

                if result.decision == HookContinue.BLOCK:
                    raise HookBlockedError(f"Prompt blocked by hook: {result.message}")

                if result.modified_prompt:
                    modified_prompt = result.modified_prompt

            except HookBlockedError:
                raise
            except Exception as e:
                self.logger.error(f"UserPromptSubmit hook error: {e}", exc_info=True)

        return HookContinue.CONTINUE, modified_prompt

    def emit_session_start(
        self,
        working_directory: str,
        model_name: str,
        config: Optional[Dict[str, Any]] = None
    ) -> None:
        """Emit SessionStart hook."""
        hooks = self._get_matching_hooks(HookEvent.SESSION_START)

        if not hooks:
            return

        context = SessionStartContext(
            session_id=self.session_id,
            event_type=HookEvent.SESSION_START.value,
            working_directory=working_directory,
            model_name=model_name,
            config=config or {}
        )

        for hook_func in hooks:
            try:
                hook_func(context)
            except Exception as e:
                self.logger.error(f"SessionStart hook error: {e}", exc_info=True)

    def emit_session_end(
        self,
        duration: float,
        statistics: Dict[str, Any],
        exit_reason: str = "normal"
    ) -> None:
        """Emit SessionEnd hook."""
        hooks = self._get_matching_hooks(HookEvent.SESSION_END)

        if not hooks:
            return

        context = SessionEndContext(
            session_id=self.session_id,
            event_type=HookEvent.SESSION_END.value,
            duration=duration,
            statistics=statistics,
            exit_reason=exit_reason
        )

        for hook_func in hooks:
            try:
                hook_func(context)
            except Exception as e:
                self.logger.error(f"SessionEnd hook error: {e}", exc_info=True)

    def emit_stop(
        self,
        response: str,
        tool_calls: List[Dict[str, Any]],
        execution_time: float
    ) -> None:
        """Emit Stop hook."""
        hooks = self._get_matching_hooks(HookEvent.STOP)

        if not hooks:
            return

        context = StopContext(
            session_id=self.session_id,
            event_type=HookEvent.STOP.value,
            response=response,
            tool_calls=tool_calls,
            execution_time=execution_time
        )

        for hook_func in hooks:
            try:
                hook_func(context)
            except Exception as e:
                self.logger.error(f"Stop hook error: {e}", exc_info=True)


class HookLoadError(Exception):
    """Raised when hooks file cannot be loaded."""
    pass


class HookBlockedError(Exception):
    """Raised when hook blocks an operation."""
    pass
```

**Lines:** ~400 lines
**Tests:** 25 tests

---

## INTEGRATION POINTS

### Integration 1: ToolExecutor (`src/tools/base.py`)

**Modification:** Add hook_manager parameter, integrate PreToolUse/PostToolUse hooks.

```python
# src/tools/base.py

class ToolExecutor:
    """Executes tools with optional hook integration."""

    def __init__(self, hook_manager: Optional['HookManager'] = None):
        """
        Initialize tool executor.

        Args:
            hook_manager: Optional hook manager for event hooks
        """
        self.tools: Dict[str, Tool] = {}
        self.hook_manager = hook_manager
        self.logger = logging.getLogger(__name__)

    def execute_tool(self, tool_name: str, **kwargs) -> ToolResult:
        """
        Execute tool with hook integration (SYNCHRONOUS).

        Performance:
        - Without hooks: 1-10ms (baseline)
        - With hooks: 2-11ms (<1ms hook overhead)

        Args:
            tool_name: Tool name
            **kwargs: Tool arguments

        Returns:
            ToolResult
        """
        # PRE HOOK
        if self.hook_manager:
            try:
                decision, modified_kwargs = self.hook_manager.emit_pre_tool_use(
                    tool=tool_name,
                    arguments=kwargs
                )

                if decision == HookDecision.DENY:
                    return ToolResult(
                        tool_name=tool_name,
                        status=ToolStatus.ERROR,
                        output=None,
                        error="Operation denied by hook"
                    )

                # Use modified arguments
                kwargs = modified_kwargs

            except HookBlockedError as e:
                return ToolResult(
                    tool_name=tool_name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Operation blocked: {e}"
                )

        # EXECUTE TOOL
        if tool_name not in self.tools:
            return ToolResult(
                tool_name=tool_name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Tool not found: {tool_name}"
            )

        tool = self.tools[tool_name]
        start_time = time.time()

        try:
            result = tool.execute(**kwargs)
        except Exception as e:
            result = ToolResult(
                tool_name=tool_name,
                status=ToolStatus.ERROR,
                output=None,
                error=str(e)
            )

        duration = time.time() - start_time

        # POST HOOK
        if self.hook_manager:
            try:
                modified_result = self.hook_manager.emit_post_tool_use(
                    tool=tool_name,
                    arguments=kwargs,
                    result=result.output,
                    success=result.is_success(),
                    duration=duration,
                    error=result.error
                )

                if modified_result is not None:
                    result.output = modified_result

            except Exception as e:
                self.logger.warning(f"PostToolUse hook error: {e}")

        return result
```

**Changes:** ~50 lines added
**Tests:** 10 integration tests

---

### Integration 2: CodingAgent (`src/core/agent.py`)

**Modification:** Add session hooks (SessionStart, UserPromptSubmit, Stop, SessionEnd).

```python
# src/core/agent.py

class CodingAgent:
    """AI coding agent with hook support."""

    def __init__(
        self,
        ...,
        hook_manager: Optional[HookManager] = None,
        hooks_file: Optional[Path] = None
    ):
        """
        Initialize agent with optional hooks.

        Args:
            hook_manager: Pre-configured hook manager
            hooks_file: Path to hooks.py file
        """
        # ... existing initialization ...

        # Initialize hook manager
        if hook_manager:
            self.hook_manager = hook_manager
        elif hooks_file:
            self.hook_manager = HookManager(hooks_file=hooks_file)
        else:
            # Try to load from default locations
            self.hook_manager = HookManager()

        # Pass to components
        self.tool_executor = ToolExecutor(hook_manager=self.hook_manager)

        # Emit SessionStart
        self.start_time = time.time()
        try:
            self.hook_manager.emit_session_start(
                working_directory=str(self.working_directory),
                model_name=self.model_name,
                config={
                    "context_window": self.context_window,
                    "backend": type(self.llm).__name__
                }
            )
        except Exception as e:
            self.logger.warning(f"SessionStart hook error: {e}")

    def execute_task(self, task_description: str, ...) -> AgentResponse:
        """Execute task with hook integration."""

        # Emit UserPromptSubmit
        try:
            decision, modified_task = self.hook_manager.emit_user_prompt_submit(
                prompt=task_description
            )

            if decision == HookContinue.BLOCK:
                return AgentResponse(
                    content="Task blocked by hook",
                    metadata={"blocked": True}
                )

            task_description = modified_task

        except Exception as e:
            self.logger.warning(f"UserPromptSubmit hook error: {e}")

        # ... execute task ...
        start_time = time.time()
        response_content = # ... execution ...
        execution_time = time.time() - start_time

        # Emit Stop
        try:
            self.hook_manager.emit_stop(
                response=response_content,
                tool_calls=self.tool_execution_history,
                execution_time=execution_time
            )
        except Exception as e:
            self.logger.warning(f"Stop hook error: {e}")

        return AgentResponse(...)

    def __del__(self):
        """Cleanup - emit SessionEnd."""
        try:
            duration = time.time() - self.start_time
            self.hook_manager.emit_session_end(
                duration=duration,
                statistics=self.get_statistics(),
                exit_reason="normal"
            )
        except:
            pass
```

**Changes:** ~70 lines added
**Tests:** 8 integration tests

---

## CONFIGURATION FORMAT

### Configuration File: `.claude/hooks.py`

**Format:** Python file (NOT JSON, NOT subprocess commands)

**Example:**

```python
"""
User's hook functions for AI Coding Agent.

This file is loaded by the agent at startup. Define your hook functions
and register them in the HOOKS dictionary.
"""

from pathlib import Path
from src.hooks import (
    PreToolUseContext, PostToolUseContext,
    HookResult, HookDecision
)


def validate_write(context: PreToolUseContext) -> HookResult:
    """
    Validate write operations - only allow .txt and .py files.

    Performance: <0.1ms
    """
    file_path = Path(context.arguments['file_path'])

    allowed_extensions = ['.txt', '.py', '.md']

    if file_path.suffix not in allowed_extensions:
        return HookResult(
            decision=HookDecision.DENY,
            message=f"Only {allowed_extensions} files allowed, got {file_path.suffix}"
        )

    return HookResult(decision=HookDecision.PERMIT)


def backup_before_write(context: PreToolUseContext) -> HookResult:
    """
    Backup file before writing.

    Performance: ~1ms (file copy)
    """
    import shutil
    from datetime import datetime

    file_path = Path(context.arguments['file_path'])

    if file_path.exists():
        backup_dir = Path('.backups')
        backup_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = backup_dir / f"{file_path.name}.{timestamp}.bak"

        shutil.copy(file_path, backup_path)
        print(f"✓ Backed up to {backup_path}")

    return HookResult(decision=HookDecision.PERMIT)


def log_tool_execution(context: PostToolUseContext) -> HookResult:
    """
    Log all tool executions for audit trail.

    Performance: <0.5ms (file append)
    """
    import json

    log_entry = {
        'timestamp': context.timestamp.isoformat(),
        'tool': context.tool,
        'success': context.success,
        'duration_ms': context.duration * 1000
    }

    log_file = Path('.audit/tools.jsonl')
    log_file.parent.mkdir(exist_ok=True)

    with log_file.open('a') as f:
        f.write(json.dumps(log_entry) + '\n')

    return HookResult(decision=HookDecision.PERMIT)


# Register hooks
HOOKS = {
    # PreToolUse hooks for write_file
    'PreToolUse:write_file': [
        validate_write,
        backup_before_write,
    ],

    # PostToolUse hooks for all tools
    'PostToolUse:*': [
        log_tool_execution,
    ],
}
```

**Benefits:**
- ✅ Python type hints, IDE autocomplete
- ✅ Can import any Python library
- ✅ Debuggable (breakpoints work)
- ✅ Type-safe context objects

---

## PERFORMANCE CHARACTERISTICS

### Benchmark Results (Expected)

| Operation | Without Hooks | With 1 Hook | With 3 Hooks |
|-----------|---------------|-------------|--------------|
| read_file | 2ms | 2.5ms | 3.5ms |
| write_file | 5ms | 6ms | 8ms |
| edit_file | 8ms | 9ms | 11ms |
| 50 operations | 100ms | 125ms | 175ms |

**Hook overhead:** 0.5-1ms per hook (99% faster than subprocess's 50-200ms)

### Comparison to Subprocess Approach

| Metric | In-Process | Subprocess | Speedup |
|--------|-----------|------------|---------|
| **Single hook call** | 0.5ms | 50ms | **100x faster** |
| **100 hook calls** | 50ms | 5000ms | **100x faster** |
| **Tool execution (no hooks)** | 2ms | 2ms | **Same baseline** |
| **Tool execution (with hooks)** | 3ms | 52ms | **17x faster** |

**Competitive advantage preserved:** 10x faster direct tool execution maintained.

---

## TESTING STRATEGY

### Test Coverage Plan

| Component | Unit Tests | Integration Tests | Total |
|-----------|------------|-------------------|-------|
| events.py | 5 | - | 5 |
| context.py | 18 | - | 18 |
| result.py | 5 | - | 5 |
| manager.py | 20 | 5 | 25 |
| ToolExecutor integration | - | 10 | 10 |
| Agent integration | - | 8 | 8 |
| E2E scenarios | - | 8 | 8 |
| **TOTAL** | **48** | **31** | **79** |

### Example Tests

**Unit Test:**
```python
def test_hook_manager_pre_tool_use_deny():
    """Test that hook can deny operation."""
    manager = HookManager()

    # Register hook that denies
    def deny_all(context):
        return HookResult(decision=HookDecision.DENY, message="Blocked")

    manager.hooks[HookEvent.PRE_TOOL_USE]['write_file'] = [deny_all]

    # Emit
    decision, args = manager.emit_pre_tool_use('write_file', {'file_path': 'test.py'})

    assert decision == HookDecision.DENY
```

**Integration Test:**
```python
def test_tool_executor_with_hook_validation():
    """Test ToolExecutor respects hook validation."""

    # Create hook that validates
    def validate_txt_only(context):
        if not context.arguments['file_path'].endswith('.txt'):
            return HookResult(decision=HookDecision.DENY)
        return HookResult(decision=HookDecision.PERMIT)

    # Setup
    manager = HookManager()
    manager.hooks[HookEvent.PRE_TOOL_USE]['write_file'] = [validate_txt_only]

    executor = ToolExecutor(hook_manager=manager)
    executor.register_tool(WriteFileTool())

    # Try to write .py file (should be denied)
    result = executor.execute_tool('write_file', file_path='test.py', content='...')

    assert not result.is_success()
    assert 'denied' in result.error.lower()
```

---

## IMPLEMENTATION TIMELINE

### 6-Day Plan

**Day 1: Core Infrastructure**
- events.py (50 lines)
- context.py (150 lines)
- result.py (50 lines)
- Unit tests (28 tests)

**Day 2: Hook Manager**
- manager.py (400 lines)
- Configuration loading
- Event emission
- Unit tests (20 tests)

**Day 3: ToolExecutor Integration**
- Modify tools/base.py (50 lines)
- PreToolUse/PostToolUse integration
- Integration tests (10 tests)

**Day 4: Agent Integration**
- Modify core/agent.py (70 lines)
- Session hooks
- Integration tests (8 tests)

**Day 5: Examples + CLI**
- Example hooks.py files
- CLI flag support
- Tests (5 tests)

**Day 6: E2E + Documentation**
- E2E tests (8 tests)
- docs/HOOKS.md
- Performance benchmarks

**Total:** 58 tests, ~800 lines production code

---

## SUCCESS CRITERIA

- ✅ All 58 tests passing
- ✅ <1ms average hook execution time
- ✅ 10x speed advantage maintained (with hooks enabled)
- ✅ Zero breaking changes to existing code
- ✅ Complete documentation
- ✅ 5+ example hook functions

---

## MIGRATION NOTES

### For Future Subprocess Support (v2.0)

If users request subprocess hooks in the future, we can add them as an **optional mode**:

```python
# Future hybrid approach
class HookManager:
    def register_python_hook(self, event, func):
        """Fast in-process hook (<1ms)."""
        pass

    def register_subprocess_hook(self, event, command):
        """Isolated subprocess hook (~50ms)."""
        pass
```

**User choice:**
```python
# Fast (in-process) - recommended
HOOKS = {
    'PreToolUse:write_file': [validate_write],  # Python function
}

# Isolated (subprocess) - if needed
HOOKS = {
    'PreToolUse:write_file': [
        SubprocessHook("python validate.py")  # Explicit wrapper
    ],
}
```

This preserves the fast path (in-process) while allowing subprocess for users who need isolation.

---

**Document Status:** ✅ Ready for Implementation
**Next Step:** Begin Day 1 implementation (Core Infrastructure)
