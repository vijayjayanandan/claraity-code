"""
Agent-UI Protocol - Bidirectional communication between Agent and UI.

This module defines:
- UserAction: Events from UI to Agent (approval responses, interrupts)
- UIProtocol: Async coordination layer with queues

Design Principles:
- Agent doesn't know about Textual internals
- UI doesn't touch Agent's private state
- All coordination via async queues (testable, decoupled)
- This module lives in core/ so agent has no UI dependency
"""

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, Optional

from src.core.events import UIEvent
from src.observability import get_logger

logger = get_logger("core.protocol")


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
    feedback: str | None = None  # Modified instructions (if provided)


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


@dataclass(frozen=True)
class ClarifyResult:
    """
    User's response to a clarify request.
    """

    call_id: str
    submitted: bool
    responses: dict[str, Any] | None = None  # question_id -> selected_option_id(s)
    chat_instead: bool = False  # User chose to chat instead
    chat_message: str | None = None  # User's chat message if chat_instead=True


@dataclass(frozen=True)
class PlanApprovalResult:
    """
    User's response to a plan approval request.
    """

    plan_hash: str
    approved: bool
    auto_accept_edits: bool = False  # If True, auto-approve edit_file calls during implementation
    feedback: str | None = None  # User feedback for revisions


# Union type for pattern matching
UserAction = (
    ApprovalResult
    | InterruptSignal
    | RetrySignal
    | PauseResult
    | ClarifyResult
    | PlanApprovalResult
)


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

    # =========================================================================
    # STATE LIFECYCLE
    #
    # _interrupted (asyncio.Event):
    #   Set by:    InterruptSignal (user clicks Stop/Ctrl+C)
    #   Cleared:   reset() (new conversation turn) or clear_interrupt()
    #              (user clicks Continue on a pause prompt)
    #   Checked:   agent.stream_response() between iterations & during streaming
    #   Checked:   delegation.execute_async() between subprocess stdout lines
    #   NOTE: If you handle a Continue after interrupt, you MUST call
    #         clear_interrupt() or the next iteration will re-trigger pause.
    #
    # _pending_approvals (dict[call_id -> PendingApproval]):
    #   Set by:    wait_for_approval() — creates future
    #   Resolved:  submit_action(ApprovalResult) — sets future result
    #   Cancelled: submit_action(InterruptSignal) — cancels all pending
    #   Cleared:   reset() — cancels all pending, clears dict
    #
    # _pending_pause (Future[PauseResult] | None):
    #   Set by:    wait_for_pause_response() — creates future
    #   Resolved:  submit_action(PauseResult) — sets future result
    #   Cleared:   wait_for_pause_response() finally block, or reset()
    #   NOTE: Only one pause can be active at a time.
    #
    # _pending_clarify (dict[call_id -> Future[ClarifyResult]]):
    #   Set by:    wait_for_clarify_response() — creates future
    #   Resolved:  submit_action(ClarifyResult) — sets future result
    #   Cleared:   wait_for_clarify_response() finally block, or reset()
    #
    # _pending_plan_approval (dict[plan_hash -> Future[PlanApprovalResult]]):
    #   Set by:    wait_for_plan_approval() — creates future
    #   Resolved:  submit_action(PlanApprovalResult) — sets future result
    #   Cleared:   wait_for_plan_approval() finally block, or reset()
    #
    # _auto_approve (set[str]):
    #   Added to:  submit_action(ApprovalResult) when auto_approve_future=True
    #   Cleared:   reset() — clears set
    # =========================================================================

    def __init__(self):
        # Queue for UI -> Agent actions
        self._action_queue: asyncio.Queue[UserAction] = asyncio.Queue()

        # Track pending approvals with tool names for targeted delivery
        self._pending_approvals: dict[str, PendingApproval] = {}

        # Track pending pause (only one at a time)
        self._pending_pause: asyncio.Future[PauseResult] | None = None

        # Track pending clarify requests (call_id -> future)
        self._pending_clarify: dict[str, asyncio.Future[ClarifyResult]] = {}

        # Track pending plan approval (plan_hash -> future)
        self._pending_plan_approval: dict[str, asyncio.Future[PlanApprovalResult]] = {}

        # Auto-approve rules (tool_name -> True)
        self._auto_approve: set[str] = set()

        # Interrupt flag (see STATE LIFECYCLE above)
        self._interrupted = asyncio.Event()

        # Callback for todo updates (Agent -> UI)
        self._on_todos_updated: Callable[[list[dict[str, Any]]], None] | None = None

        # Callback for pause requests (delegation tool -> UI)
        self._on_pause_requested: Callable | None = None

    # -------------------------------------------------------------------------
    # Agent-side methods
    # -------------------------------------------------------------------------

    async def wait_for_approval(
        self, call_id: str, tool_name: str, timeout: float | None = None
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
        self._pending_approvals[call_id] = PendingApproval(future=future, tool_name=tool_name)

        try:
            if timeout:
                return await asyncio.wait_for(future, timeout)
            else:
                return await future
        finally:
            self._pending_approvals.pop(call_id, None)

    async def wait_for_pause_response(self, timeout: float | None = None) -> PauseResult:
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
        # Create future for pause response
        future: asyncio.Future[PauseResult] = asyncio.Future()
        self._pending_pause = future
        logger.debug(
            f"[PAUSE] wait_for_pause_response called, timeout={timeout}, future_id={id(future)}"
        )

        try:
            if timeout:
                result = await asyncio.wait_for(future, timeout)
            else:
                result = await future
            logger.debug(
                f"[PAUSE] Future resolved: continue_work={result.continue_work}, feedback={result.feedback}"
            )
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

    async def wait_for_clarify_response(
        self, call_id: str, timeout: float | None = None
    ) -> ClarifyResult:
        """
        Wait for user to complete clarify interview.

        Args:
            call_id: The tool call ID to wait for
            timeout: Optional timeout in seconds (None = wait forever)

        Returns:
            ClarifyResult with user's answers or cancellation

        Raises:
            asyncio.CancelledError: If stream was interrupted
            asyncio.TimeoutError: If timeout exceeded
        """
        # Create future for this specific call
        future: asyncio.Future[ClarifyResult] = asyncio.Future()
        self._pending_clarify[call_id] = future
        logger.debug(
            f"[CLARIFY] wait_for_clarify_response called, call_id={call_id}, timeout={timeout}"
        )

        try:
            if timeout:
                result = await asyncio.wait_for(future, timeout)
            else:
                result = await future
            logger.debug(f"[CLARIFY] Future resolved: submitted={result.submitted}")
            return result
        except asyncio.CancelledError:
            logger.warning(f"[CLARIFY] Future cancelled for call_id={call_id}")
            return ClarifyResult(
                call_id=call_id,
                submitted=False,
                responses=None,
                chat_instead=False,
                chat_message="Clarify cancelled",
            )
        except asyncio.TimeoutError:
            logger.warning(f"[CLARIFY] Timed out after {timeout}s for call_id={call_id}")
            return ClarifyResult(
                call_id=call_id,
                submitted=False,
                responses=None,
                chat_instead=False,
                chat_message="Timed out waiting for response",
            )
        finally:
            self._pending_clarify.pop(call_id, None)

    async def wait_for_plan_approval(
        self, plan_hash: str, timeout: float | None = None
    ) -> PlanApprovalResult:
        """
        Wait for user to approve or reject a plan.

        Args:
            plan_hash: The hash of the plan being submitted for approval
            timeout: Optional timeout in seconds (None = wait forever)

        Returns:
            PlanApprovalResult with user's decision

        Raises:
            asyncio.CancelledError: If stream was interrupted
            asyncio.TimeoutError: If timeout exceeded
        """
        # Create future for this specific plan
        future: asyncio.Future[PlanApprovalResult] = asyncio.Future()
        self._pending_plan_approval[plan_hash] = future
        logger.debug(
            f"[PLAN] wait_for_plan_approval called, plan_hash={plan_hash}, timeout={timeout}"
        )

        try:
            if timeout:
                result = await asyncio.wait_for(future, timeout)
            else:
                result = await future
            logger.debug(f"[PLAN] Future resolved: approved={result.approved}")
            return result
        except asyncio.CancelledError:
            logger.warning(f"[PLAN] Future cancelled for plan_hash={plan_hash}")
            return PlanApprovalResult(
                plan_hash=plan_hash, approved=False, feedback="Plan approval cancelled"
            )
        except asyncio.TimeoutError:
            logger.warning(f"[PLAN] Timed out after {timeout}s for plan_hash={plan_hash}")
            return PlanApprovalResult(
                plan_hash=plan_hash, approved=False, feedback="Timed out waiting for response"
            )
        finally:
            self._pending_plan_approval.pop(plan_hash, None)

    def check_interrupted(self) -> bool:
        """Check if user has requested interruption."""
        return self._interrupted.is_set()

    def clear_interrupt(self) -> None:
        """Clear the interrupt flag (e.g. after user clicks Continue on a pause prompt)."""
        self._interrupted.clear()

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

        elif isinstance(action, ClarifyResult):
            # Deliver to specific pending clarify future
            pending = self._pending_clarify.get(action.call_id)
            if pending and not pending.done():
                pending.set_result(action)

        elif isinstance(action, PlanApprovalResult):
            # Deliver to specific pending plan approval future
            pending = self._pending_plan_approval.get(action.plan_hash)
            if pending and not pending.done():
                pending.set_result(action)

        elif isinstance(action, InterruptSignal):
            self._interrupted.set()
            # Cancel all pending approvals
            for pending in self._pending_approvals.values():
                if not pending.future.done():
                    pending.future.cancel()
            # Cancel pending pause
            if self._pending_pause and not self._pending_pause.done():
                self._pending_pause.cancel()
            # Cancel all pending clarify
            for pending in self._pending_clarify.values():
                if not pending.done():
                    pending.cancel()
            # Cancel all pending plan approvals
            for pending in self._pending_plan_approval.values():
                if not pending.done():
                    pending.cancel()

        # Also put in general queue for other consumers
        # Note: Queue is unbounded so QueueFull shouldn't occur, but handle defensively
        try:
            self._action_queue.put_nowait(action)
        except asyncio.QueueFull:
            # Queue full (shouldn't happen with unbounded queue)
            # Log warning and drop oldest to make room for critical action
            logger.warning(f"Action queue full, dropping oldest action to queue: {action}")
            try:
                dropped = self._action_queue.get_nowait()
                logger.warning(f"Dropped action: {dropped}")
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

        # Cancel pending clarify futures
        for pending in self._pending_clarify.values():
            if not pending.done():
                pending.cancel()
        self._pending_clarify.clear()

        # Cancel pending plan approval futures
        for pending in self._pending_plan_approval.values():
            if not pending.done():
                pending.cancel()
        self._pending_plan_approval.clear()

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
    # Pause Requests (Delegation Tool -> UI)
    # -------------------------------------------------------------------------

    def set_pause_requested_callback(self, callback: Callable | None) -> None:
        """
        Register a callback invoked when a subagent requests a pause.

        The callback signature is:
            async def on_pause(reason, reason_code, pending_todos, stats) -> None

        It should mount the PausePromptWidget. The existing
        wait_for_pause_response() is then used to await the user's decision.

        Args:
            callback: Async callable or None to unregister.
        """
        self._on_pause_requested = callback

    async def request_pause(
        self,
        reason: str,
        reason_code: str,
        stats: dict[str, Any],
        pending_todos: list[dict[str, Any]] | None = None,
    ) -> "PauseResult":
        """
        Request a pause from the user (called by delegation tool).

        1. Calls the registered callback to mount the PausePromptWidget
        2. Awaits user's decision via wait_for_pause_response()

        Args:
            reason: Human-readable pause reason
            reason_code: Machine-readable code (e.g., "iteration_limit")
            stats: dict with iteration/time stats for display
            pending_todos: Optional list of pending todo items

        Returns:
            PauseResult with user's decision
        """
        if self._on_pause_requested is not None:
            result = self._on_pause_requested(reason, reason_code, pending_todos, stats)
            # Support both sync and async callbacks
            if asyncio.iscoroutine(result):
                await result

        return await self.wait_for_pause_response()

    # -------------------------------------------------------------------------
    # Todo Updates (Agent -> UI)
    # -------------------------------------------------------------------------

    def set_todos_callback(self, callback: Callable[[list[dict[str, Any]]], None] | None) -> None:
        """
        Register a callback to be called when todos are updated.

        Args:
            callback: Function that receives the updated todo list.
                      Pass None to unregister.

        Usage in Textual App:
            self.ui_protocol.set_todos_callback(self.on_todos_updated)

            def on_todos_updated(self, todos: list[dict]) -> None:
                todo_bar = self.query_one("#todo-bar", TodoBar)
                todo_bar.update_todos(todos)
        """
        self._on_todos_updated = callback

    def notify_todos_updated(self, todos: list[dict[str, Any]]) -> None:
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
                logger.exception("Error in todos callback")

    def notify_beads_updated(self) -> None:
        """Push a fresh beads snapshot to the client (e.g. VS Code sidebar).

        Base implementation is a no-op. Overridden by server transports
        (stdio_server) to send a beads_data push message.
        The TUI has no beads panel so it leaves this as a no-op.
        """


# Export all types
__all__ = [
    "ApprovalResult",
    "InterruptSignal",
    "RetrySignal",
    "PauseResult",
    "ClarifyResult",
    "PlanApprovalResult",
    "UserAction",
    "PendingApproval",
    "UIProtocol",
]
