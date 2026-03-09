"""In-process Python hooks manager."""

import importlib.util
import logging
import sys
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, Optional

from .context import (
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
from .events import HookApproval, HookContinue, HookDecision, HookEvent
from .result import HookResult, NotificationResult, UserPromptResult

logger = logging.getLogger(__name__)


class HookLoadError(Exception):
    """Raised when hooks file cannot be loaded."""

    pass


class HookBlockedError(Exception):
    """Raised when hook blocks an operation."""

    pass


class HookManager:
    """
    In-process Python hooks manager.

    Loads Python hook functions from .clarity/hooks.py and executes them
    synchronously (no subprocess, no async/await).

    Performance: <1ms per hook execution
    """

    def __init__(self, hooks_file: Path | None = None, session_id: str | None = None):
        """
        Initialize hook manager.

        Args:
            hooks_file: Path to hooks.py file (default: .clarity/hooks.py)
            session_id: Session identifier (generated if not provided)
        """
        self.session_id = session_id or str(uuid.uuid4())
        self.hooks: dict[HookEvent, dict[str, list[Callable]]] = {event: {} for event in HookEvent}
        self.logger = logging.getLogger(__name__)

        # Load hooks
        if hooks_file:
            self.load_hooks(hooks_file)
        else:
            self._load_default_hooks()

    def _load_default_hooks(self) -> None:
        """Load hooks from default locations."""
        hooks_paths = [
            Path("./.clarity/hooks.py"),  # Project level
            Path.home() / ".clarity" / "hooks.py",  # User level
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
            if not hasattr(module, "HOOKS"):
                raise HookLoadError(f"No HOOKS dict found in {hooks_file}")

            hooks_config = module.HOOKS

            # Register hooks
            for pattern, hook_funcs in hooks_config.items():
                self._register_pattern(pattern, hook_funcs)

            self.logger.info(f"Successfully loaded hooks from {hooks_file}")

        except Exception as e:
            raise HookLoadError(f"Failed to load hooks from {hooks_file}: {e}")

    def _register_pattern(self, pattern: str, hook_funcs: list[Callable]) -> None:
        """
        Register hook functions for a pattern.

        Patterns:
        - 'PreToolUse:write_file' → PreToolUse event, write_file tool
        - 'PreToolUse:*' → PreToolUse event, all tools
        - 'SessionStart' → SessionStart event

        Args:
            pattern: Pattern string
            hook_funcs: list of hook functions
        """
        # Parse pattern
        if ":" in pattern:
            event_str, tool_pattern = pattern.split(":", 1)
        else:
            event_str = pattern
            tool_pattern = "*"

        # Get event enum
        try:
            # Convert from user-friendly format to enum name
            # 'PreToolUse' → 'PRE_TOOL_USE'
            event_name = event_str
            # Try direct match first
            if hasattr(HookEvent, event_str):
                event = HookEvent[event_str]
            else:
                # Try converting to uppercase with underscores
                event_name_upper = event_str.upper().replace(" ", "_")
                # Convert camelCase to SCREAMING_SNAKE_CASE
                import re

                event_name_upper = re.sub(r"(?<!^)(?=[A-Z])", "_", event_str).upper()
                event = HookEvent[event_name_upper]
        except KeyError:
            self.logger.error(f"Unknown event type: {event_str}")
            return

        # Register each function
        if tool_pattern not in self.hooks[event]:
            self.hooks[event][tool_pattern] = []

        for func in hook_funcs if isinstance(hook_funcs, list) else [hook_funcs]:
            self.hooks[event][tool_pattern].append(func)
            self.logger.debug(f"Registered hook: {event.value}:{tool_pattern} → {func.__name__}")

    def _get_matching_hooks(self, event: HookEvent, tool: str | None = None) -> list[Callable]:
        """
        Get hooks matching the event and tool.

        Args:
            event: Hook event
            tool: Tool name (for PreToolUse/PostToolUse)

        Returns:
            list of matching hook functions
        """
        if event not in self.hooks:
            return []

        matching = []

        # Check wildcard hooks (*) first
        if "*" in self.hooks[event]:
            matching.extend(self.hooks[event]["*"])

        # Check tool-specific hooks
        if tool and tool in self.hooks[event]:
            matching.extend(self.hooks[event][tool])

        return matching

    # ========== EVENT EMISSION METHODS (SYNCHRONOUS) ==========

    def emit_pre_tool_use(
        self, tool: str, arguments: dict[str, Any], step_id: int | None = None
    ) -> tuple[HookDecision, dict[str, Any]]:
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
            step_id=step_id,
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
        arguments: dict[str, Any],
        result: Any,
        success: bool,
        duration: float,
        error: str | None = None,
    ) -> Any | None:
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
            error=error,
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
        self, prompt: str, metadata: dict[str, Any] | None = None
    ) -> tuple[HookContinue, str]:
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
            metadata=metadata or {},
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

    def emit_notification(
        self,
        notification_type: str,
        message: str,
        step_info: dict[str, Any] | None = None,
        risk_level: str | None = None,
    ) -> HookApproval:
        """
        Emit Notification hook.

        Args:
            notification_type: Type of notification
            message: Notification message
            step_info: Step information
            risk_level: Risk level

        Returns:
            Approval decision
        """
        hooks = self._get_matching_hooks(HookEvent.NOTIFICATION)

        if not hooks:
            return HookApproval.APPROVE

        context = NotificationContext(
            session_id=self.session_id,
            event_type=HookEvent.NOTIFICATION.value,
            notification_type=notification_type,
            message=message,
            step_info=step_info,
            risk_level=risk_level,
        )

        for hook_func in hooks:
            try:
                result = hook_func(context)

                if result.decision == HookApproval.DENY:
                    self.logger.info(f"Notification denied by hook: {result.message}")
                    return HookApproval.DENY

            except Exception as e:
                self.logger.error(f"Notification hook error: {e}", exc_info=True)

        return HookApproval.APPROVE

    def emit_session_start(
        self, working_directory: str, model_name: str, config: dict[str, Any] | None = None
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
            config=config or {},
        )

        for hook_func in hooks:
            try:
                hook_func(context)
            except Exception as e:
                self.logger.error(f"SessionStart hook error: {e}", exc_info=True)

    def emit_session_end(
        self, duration: float, statistics: dict[str, Any] | None = None, exit_reason: str = "normal"
    ) -> None:
        """Emit SessionEnd hook."""
        hooks = self._get_matching_hooks(HookEvent.SESSION_END)

        if not hooks:
            return

        context = SessionEndContext(
            session_id=self.session_id,
            event_type=HookEvent.SESSION_END.value,
            duration=duration,
            statistics=statistics or {},
            exit_reason=exit_reason,
        )

        for hook_func in hooks:
            try:
                hook_func(context)
            except Exception as e:
                self.logger.error(f"SessionEnd hook error: {e}", exc_info=True)

    def emit_pre_compact(
        self, current_tokens: int, target_tokens: int, messages_to_drop: list[str] | None = None
    ) -> None:
        """Emit PreCompact hook."""
        hooks = self._get_matching_hooks(HookEvent.PRE_COMPACT)

        if not hooks:
            return

        context = PreCompactContext(
            session_id=self.session_id,
            event_type=HookEvent.PRE_COMPACT.value,
            current_tokens=current_tokens,
            target_tokens=target_tokens,
            messages_to_drop=messages_to_drop or [],
        )

        for hook_func in hooks:
            try:
                hook_func(context)
            except Exception as e:
                self.logger.error(f"PreCompact hook error: {e}", exc_info=True)

    def emit_stop(
        self,
        response: str,
        tool_calls: list[dict[str, Any]] | None = None,
        execution_time: float = 0.0,
    ) -> None:
        """Emit Stop hook."""
        hooks = self._get_matching_hooks(HookEvent.STOP)

        if not hooks:
            return

        context = StopContext(
            session_id=self.session_id,
            event_type=HookEvent.STOP.value,
            response=response,
            tool_calls=tool_calls or [],
            execution_time=execution_time,
        )

        for hook_func in hooks:
            try:
                hook_func(context)
            except Exception as e:
                self.logger.error(f"Stop hook error: {e}", exc_info=True)

    def emit_subagent_stop(self, subagent_name: str, result: Any, duration: float) -> None:
        """Emit SubagentStop hook."""
        hooks = self._get_matching_hooks(HookEvent.SUBAGENT_STOP)

        if not hooks:
            return

        context = SubagentStopContext(
            session_id=self.session_id,
            event_type=HookEvent.SUBAGENT_STOP.value,
            subagent_name=subagent_name,
            result=result,
            duration=duration,
        )

        for hook_func in hooks:
            try:
                hook_func(context)
            except Exception as e:
                self.logger.error(f"SubagentStop hook error: {e}", exc_info=True)
