"""
Special Tool Handlers - Async tool handlers that pause for UI interaction.

These three handlers have a common pattern: execute a tool, persist events
via MemoryManager, wait for user response via UIProtocol, then return the
result to the LLM. They were extracted from CodingAgent to reduce its size.

Handled tools:
- clarify: Ask the user structured questions before proceeding
- request_plan_approval: Submit a plan for user approval
"""

import asyncio
import hashlib
import json
import os
from typing import TYPE_CHECKING, Any

from src.observability import get_logger

if TYPE_CHECKING:
    from src.core.permission_mode import PermissionManager
    from src.core.plan_mode import PlanModeState
    from src.core.protocol import UIProtocol
    from src.memory import MemoryManager
    from src.tools import ToolExecutor

logger = get_logger(__name__)

# The set of tool names handled by this module
HANDLED_TOOLS = frozenset({"clarify", "request_plan_approval"})


class SpecialToolHandlers:
    """Async tool handlers that pause the tool loop for UI interaction.

    Each handler follows the same pattern:
    1. Execute the tool / validate args
    2. Persist a system event via MemoryManager (triggers TUI widget)
    3. Wait for user response via UIProtocol
    4. Persist the response event
    5. Return result to the LLM
    """

    def __init__(
        self,
        memory: "MemoryManager",
        plan_mode_state: "PlanModeState",
        tool_executor: "ToolExecutor",
        permission_manager: "PermissionManager",
        set_auto_approve_fn: Any = None,
    ):
        self._memory = memory
        self._plan_mode_state = plan_mode_state
        self._tool_executor = tool_executor
        self._permission_manager = permission_manager
        # Callback: set_auto_approve_fn(categories: dict[str, bool]) -> dict[str, bool]
        # Called when plan approval needs to enable categories (e.g. edit).
        # Returns confirmed state. Wired by CodingAgent to ToolGatingService.
        self._set_auto_approve_fn = set_auto_approve_fn

    def handles(self, tool_name: str) -> bool:
        """Check if this handler manages the given tool."""
        return tool_name in HANDLED_TOOLS

    # ------------------------------------------------------------------
    # Handler: clarify
    # ------------------------------------------------------------------

    async def handle_clarify(
        self,
        call_id: str,
        tool_args: dict[str, Any],
        ui_protocol: "UIProtocol",
    ) -> dict[str, Any]:
        """Handle the clarify tool - ask structured questions before proceeding.

        Args:
            call_id: Tool call ID for correlation.
            tool_args: Tool arguments (questions, context).
            ui_protocol: UIProtocol for TUI interaction.

        Returns:
            dict with user responses or error/cancellation status.
        """
        questions = tool_args.get("questions", [])
        context = tool_args.get("context")

        # Validate questions
        if not questions:
            return {"error": "clarify.questions is empty"}

        if len(questions) > 4:
            return {"error": "clarify.questions has more than 4 questions (max: 4)"}

        # 1. Persist clarify_request via MemoryManager (SINGLE WRITER)
        if self._memory.has_message_store:
            self._memory.persist_system_event(
                event_type="clarify_request",
                content="[Clarification requested]",
                extra={
                    "call_id": call_id,
                    "questions": questions,
                    "context": context,
                },
                include_in_llm_context=False,
            )

        # 2. Wait for user response via UIProtocol
        try:
            from src.core.protocol import ClarifyResult

            result = await ui_protocol.wait_for_clarify_response(call_id)

            # 3. Persist clarify_response via MemoryManager (SINGLE WRITER)
            if self._memory.has_message_store:
                status = (
                    "submitted"
                    if result.submitted
                    else ("chat" if result.chat_instead else "cancelled")
                )
                self._memory.persist_system_event(
                    event_type="clarify_response",
                    content=f"[Clarification {status}]",
                    extra={
                        "call_id": call_id,
                        "submitted": result.submitted,
                        "responses": result.responses,
                        "chat_instead": result.chat_instead,
                        "chat_message": result.chat_message,
                    },
                    include_in_llm_context=False,
                )

            # 4. Return result to LLM
            if result.submitted:
                return {"submitted": True, "responses": result.responses}
            if result.chat_instead:
                return {"mode": "chat", "message": result.chat_message}
            return {"cancelled": True}

        except asyncio.CancelledError:
            return {"cancelled": True, "reason": "interrupted"}

    # ------------------------------------------------------------------
    # Handler: request_plan_approval
    # ------------------------------------------------------------------

    async def handle_plan_approval(
        self,
        call_id: str,
        ui_protocol: "UIProtocol",
    ) -> tuple[str, bool]:
        """Handle request_plan_approval tool.

        Returns:
            tuple of (result_text, rejected_without_feedback).
            - result_text: Human-readable string for LLM
            - rejected_without_feedback: True if user rejected without feedback
              (caller should stop tool loop and wait for user input)
        """
        from src.core.permission_mode import PermissionManager, PermissionMode

        # 1. Execute the request_plan_approval tool
        result = await self._tool_executor.execute_tool_async("request_plan_approval")

        if not result.is_success():
            return (f"Error: {result.error or 'Failed to request plan approval'}", False)

        # Parse metadata from tool result
        metadata = result.metadata or {}
        plan_hash = metadata.get("plan_hash")
        excerpt = metadata.get("excerpt", "")
        truncated = metadata.get("truncated", False)
        plan_path = metadata.get("plan_path")

        if not plan_hash:
            return ("Error: No plan hash returned from request_plan_approval", False)

        # 2. Read full plan content before approval (state may reset after)
        plan_content = self._plan_mode_state.get_plan_content() or excerpt

        # 3. Persist plan_submitted system event (TUI will mount approval widget)
        if self._memory.has_message_store:
            self._memory.persist_system_event(
                event_type="plan_submitted",
                content="[Plan submitted for approval]",
                extra={
                    "call_id": call_id,
                    "plan_hash": plan_hash,
                    "excerpt": excerpt,
                    "truncated": truncated,
                    "plan_path": plan_path,
                },
                include_in_llm_context=False,
            )

        # Persist mode change event
        if self._memory.has_message_store:
            self._memory.persist_system_event(
                event_type="permission_mode_changed",
                content="Mode: plan -> awaiting_approval",
                extra={"old_mode": "plan", "new_mode": "awaiting_approval"},
                include_in_llm_context=False,
            )

        # 4. Wait for user approval via UIProtocol
        try:
            from src.core.protocol import PlanApprovalResult

            approval = await ui_protocol.wait_for_plan_approval(plan_hash)

            if approval.approved:
                self._plan_mode_state.approve(plan_hash)

                if self._memory.has_message_store:
                    self._memory.persist_system_event(
                        event_type="plan_approved",
                        content="[Plan approved]",
                        extra={
                            "plan_hash": plan_hash,
                            "auto_accept_edits": approval.auto_accept_edits,
                        },
                        include_in_llm_context=False,
                    )
                    # Always return to NORMAL mode (not AUTO).
                    # If auto-accept edits was chosen, enable the "edit"
                    # category via the gating service instead. This keeps
                    # the VS Code auto-approve panel in sync.
                    self._memory.persist_system_event(
                        event_type="permission_mode_changed",
                        content="Mode: plan -> normal",
                        extra={"old_mode": "plan", "new_mode": "normal"},
                        include_in_llm_context=False,
                    )
                    self._permission_manager.set_mode(PermissionManager.from_string("normal"))

                    if approval.auto_accept_edits and self._set_auto_approve_fn:
                        self._set_auto_approve_fn({"edit": True})

                result_text = (
                    "User has approved your plan. You can now start coding. "
                    "Start with updating your todo list if applicable.\n\n"
                    f"Your plan has been saved to: {plan_path}\n"
                    "You can refer back to it if needed during implementation.\n\n"
                    "## Approved Plan:\n"
                    f"{plan_content}"
                )
                return (result_text, False)
            else:
                self._plan_mode_state.reject()

                if self._memory.has_message_store:
                    self._memory.persist_system_event(
                        event_type="plan_rejected",
                        content="[Plan rejected]",
                        extra={
                            "plan_hash": plan_hash,
                            "feedback": approval.feedback,
                        },
                        include_in_llm_context=False,
                    )
                    # CRITICAL: Persist mode change back to plan mode
                    self._memory.persist_system_event(
                        event_type="permission_mode_changed",
                        content="Mode: awaiting_approval -> plan",
                        extra={"old_mode": "awaiting_approval", "new_mode": "plan"},
                        include_in_llm_context=False,
                    )

                # Check if user rejected without feedback (Escape key)
                if approval.feedback is None:
                    return ("Plan approval cancelled.", True)
                else:
                    result_text = (
                        "Plan rejected. You are back in plan mode. "
                        f"Revise the plan and call request_plan_approval again.\n\n"
                        f"User feedback: {approval.feedback}"
                    )
                    return (result_text, False)

        except asyncio.CancelledError:
            return ("Plan approval was cancelled.", True)

