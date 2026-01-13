"""
UI Protocol - Bidirectional communication between UI and Agent.

This module defines:
- UserAction: Events from UI to Agent (approval responses, interrupts)
- UIProtocol: Async coordination layer with queues

Design Principles:
- Agent doesn't know about Textual internals
- UI doesn't touch Agent's private state
- All coordination via async queues (testable, decoupled)
"""

from dataclasses import dataclass
from typing import AsyncIterator, Callable, List, Dict, Any, Optional
import asyncio

from .events import UIEvent


# =============================================================================
# User Actions (UI -> Agent)
# =============================================================================

@dataclass(frozen=True)
class ApprovalResult:
    """
    User's response to a tool approval request.
    """
    call_id: str
    approved: bool
    auto_approve_future: bool = False  # "Don't ask again for this tool"
    feedback: str | None = None        # Modified instructions (if provided)


@dataclass(frozen=True)
class InterruptSignal:
    """
    User interrupted the stream (Ctrl+C).
    """
    pass


@dataclass(frozen=True)
class RetrySignal:
    """
    User requested retry after error.
    """
    pass


@dataclass(frozen=True)
class PauseResult:
    """
    User's response to a pause prompt.
    """
    continue_work: bool
    feedback: str | None = None  # Optional guidance for next steps


# Union type for pattern matching
UserAction = ApprovalResult | InterruptSignal | RetrySignal | PauseResult


# =============================================================================
# Pending Approval Tracker
# =============================================================================

@dataclass
class PendingApproval:
    """
    Tracks a pending approval with its associated future and tool name.

    This allows us to:
    - Deliver approval results to the correct waiting coroutine
    - Track tool names for auto-approve functionality
    """
    future: asyncio.Future
    tool_name: str


# =============================================================================
# UI Protocol (Coordination Layer)
# =============================================================================

class UIProtocol:
    """
    Bidirectional communication layer between UI and Agent.

    Usage in Agent:
        async def stream_response(self, user_input: str, ui: UIProtocol):
            async for event in processor.process(raw_stream):
                yield event

                if isinstance(event, ToolCallStart) and event.requires_approval:
                    result = await ui.wait_for_approval(event.call_id, event.name)
                    if not result.approved:
                        yield ToolCallStatus(event.call_id, ToolStatus.REJECTED)
                        continue

    Usage in Textual App:
        def on_approval_response_message(self, message: ApprovalResponseMessage):
            self.ui_protocol.submit_action(
                ApprovalResult(
                    call_id=message.call_id,
                    approved=message.action in ("yes", "yes_all"),
                    auto_approve_future=message.action == "yes_all",
                    feedback=message.feedback,
                )
            )
    """

    def __init__(self):
        # Queue for UI -> Agent actions
        self._action_queue: asyncio.Queue[UserAction] = asyncio.Queue()

        # Track pending approvals with tool names for targeted delivery
        self._pending_approvals: dict[str, PendingApproval] = {}

        # Track pending pause (only one at a time)
        self._pending_pause: asyncio.Future[PauseResult] | None = None

        # Auto-approve rules (tool_name -> True)
        self._auto_approve: set[str] = set()

        # Interrupt flag
        self._interrupted = asyncio.Event()

        # Callback for todo updates (Agent -> UI)
        self._on_todos_updated: Optional[Callable[[List[Dict[str, Any]]], None]] = None

    # -------------------------------------------------------------------------
    # Agent-side methods
    # -------------------------------------------------------------------------

    async def wait_for_approval(
        self,
        call_id: str,
        tool_name: str,
        timeout: float | None = None
    ) -> ApprovalResult:
        """
        Wait for user to approve/reject a tool call.

        Args:
            call_id: The tool call ID to wait for
            tool_name: Tool name (for auto-approve lookup)
            timeout: Optional timeout in seconds

        Returns:
            ApprovalResult with user's decision

        Raises:
            asyncio.CancelledError: If stream was interrupted
            asyncio.TimeoutError: If timeout exceeded
        """
        # Check auto-approve first
        if tool_name in self._auto_approve:
            return ApprovalResult(
                call_id=call_id,
                approved=True,
                auto_approve_future=True,
            )

        # Create future for this specific call
        future: asyncio.Future[ApprovalResult] = asyncio.Future()
        self._pending_approvals[call_id] = PendingApproval(
            future=future,
            tool_name=tool_name
        )

        try:
            if timeout:
                return await asyncio.wait_for(future, timeout)
            else:
                return await future
        finally:
            self._pending_approvals.pop(call_id, None)

    async def wait_for_pause_response(
        self,
        timeout: float | None = None
    ) -> PauseResult:
        """
        Wait for user to respond to a pause prompt.

        Args:
            timeout: Optional timeout in seconds (None = wait forever)

        Returns:
            PauseResult with user's decision (continue_work, feedback)

        Note:
            CancelledError and TimeoutError are caught and converted to
            PauseResult(continue_work=False) to prevent cascading failures.
        """
        import logging
        logger = logging.getLogger("ui.protocol")

        # Create future for pause response
        future: asyncio.Future[PauseResult] = asyncio.Future()
        self._pending_pause = future
        logger.debug(f"[PAUSE] wait_for_pause_response called, timeout={timeout}, future_id={id(future)}")

        try:
            if timeout:
                result = await asyncio.wait_for(future, timeout)
            else:
                result = await future
            logger.debug(f"[PAUSE] Future resolved: continue_work={result.continue_work}, feedback={result.feedback}")
            return result
        except asyncio.CancelledError:
            # Treat cancellation as "stop" - no error propagation
            # This prevents cascading [Interrupted] on worker replacement
            logger.warning("[PAUSE] Future cancelled - returning continue_work=False")
            return PauseResult(continue_work=False, feedback="Pause cancelled")
        except asyncio.TimeoutError:
            # Timeout waiting for user - default to stop
            logger.warning(f"[PAUSE] Timed out after {timeout}s - returning continue_work=False")
            return PauseResult(continue_work=False, feedback="Timed out waiting for response")
        finally:
            self._pending_pause = None

    def has_pause_capability(self) -> bool:
        """
        Check if this protocol supports interactive pause.

        Returns True for TUI mode, False for simple CLI mode.
        Simple CLI should use text-based pause fallback.
        """
        return True  # TUI supports pause widget

    def check_interrupted(self) -> bool:
        """Check if user has requested interruption."""
        return self._interrupted.is_set()

    async def wait_for_interrupt(self) -> None:
        """Wait until interrupted. Use with asyncio.wait() for cancellation."""
        await self._interrupted.wait()

    def get_action_queue(self) -> asyncio.Queue[UserAction]:
        """Get the action queue for additional consumers."""
        return self._action_queue

    # -------------------------------------------------------------------------
    # UI-side methods
    # -------------------------------------------------------------------------

    def submit_action(self, action: UserAction) -> None:
        """
        Submit a user action (non-blocking).

        Called by Textual message handlers.
        """
        if isinstance(action, ApprovalResult):
            # Deliver to specific waiting future
            pending = self._pending_approvals.get(action.call_id)
            if pending and not pending.future.done():
                # Handle auto-approve BEFORE setting result to avoid race condition
                # (the awaiting coroutine may resume immediately after set_result)
                if action.auto_approve_future and action.approved:
                    self._auto_approve.add(pending.tool_name)

                pending.future.set_result(action)

        elif isinstance(action, PauseResult):
            # Deliver to pending pause future
            if self._pending_pause and not self._pending_pause.done():
                self._pending_pause.set_result(action)

        elif isinstance(action, InterruptSignal):
            self._interrupted.set()
            # Cancel all pending approvals
            for pending in self._pending_approvals.values():
                if not pending.future.done():
                    pending.future.cancel()
            # Cancel pending pause
            if self._pending_pause and not self._pending_pause.done():
                self._pending_pause.cancel()

        # Also put in general queue for other consumers
        # Note: Queue is unbounded so QueueFull shouldn't occur, but handle defensively
        try:
            self._action_queue.put_nowait(action)
        except asyncio.QueueFull:
            # Queue full (shouldn't happen with unbounded queue)
            # Log warning and drop oldest to make room for critical action
            import logging
            logging.warning(f"Action queue full, dropping oldest action to queue: {action}")
            try:
                dropped = self._action_queue.get_nowait()
                logging.warning(f"Dropped action: {dropped}")
                self._action_queue.put_nowait(action)
            except asyncio.QueueEmpty:
                pass

    def reset(self) -> None:
        """Reset state for new conversation turn."""
        self._interrupted.clear()

        # Cancel pending futures BEFORE clearing (don't orphan awaiters)
        for pending in self._pending_approvals.values():
            if not pending.future.done():
                pending.future.cancel()
        self._pending_approvals.clear()

        if self._pending_pause and not self._pending_pause.done():
            self._pending_pause.cancel()
        self._pending_pause = None
        # Don't clear auto_approve - persists within session

    def clear_auto_approve(self) -> None:
        """Clear all auto-approve rules (e.g., on session end)."""
        self._auto_approve.clear()

    def is_auto_approved(self, tool_name: str) -> bool:
        """Check if a tool is set to auto-approve."""
        return tool_name in self._auto_approve

    def add_auto_approve(self, tool_name: str) -> None:
        """Add a tool to auto-approve list."""
        self._auto_approve.add(tool_name)

    def remove_auto_approve(self, tool_name: str) -> None:
        """Remove a tool from auto-approve list."""
        self._auto_approve.discard(tool_name)

    # -------------------------------------------------------------------------
    # Todo Updates (Agent -> UI)
    # -------------------------------------------------------------------------

    def set_todos_callback(
        self,
        callback: Optional[Callable[[List[Dict[str, Any]]], None]]
    ) -> None:
        """
        Register a callback to be called when todos are updated.

        Args:
            callback: Function that receives the updated todo list.
                      Pass None to unregister.

        Usage in Textual App:
            self.ui_protocol.set_todos_callback(self.on_todos_updated)

            def on_todos_updated(self, todos: List[Dict]) -> None:
                todo_bar = self.query_one("#todo-bar", TodoBar)
                todo_bar.update_todos(todos)
        """
        self._on_todos_updated = callback

    def notify_todos_updated(self, todos: List[Dict[str, Any]]) -> None:
        """
        Notify UI that todos have been updated.

        Called by agent after TodoWrite tool executes.

        Args:
            todos: The updated todo list
        """
        if self._on_todos_updated is not None:
            try:
                self._on_todos_updated(todos)
            except Exception:
                # Don't let UI callback errors break agent execution
                import logging
                logging.exception("Error in todos callback")


# Export all types
__all__ = [
    'ApprovalResult',
    'InterruptSignal',
    'RetrySignal',
    'PauseResult',
    'UserAction',
    'PendingApproval',
    'UIProtocol',
]
