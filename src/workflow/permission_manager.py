"""Permission manager for controlling agent autonomy levels.

This module provides the PermissionManager that controls when the agent
should ask for user approval before executing operations. Three modes:
- PLAN: Always show plan and ask for approval
- NORMAL: Ask for approval only for high-risk operations (default)
- AUTO: Never ask for approval, execute automatically
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Callable
import logging

from .task_planner import ExecutionPlan
from .task_analyzer import TaskAnalysis

logger = logging.getLogger(__name__)


class PermissionMode(Enum):
    """Permission modes for agent execution.

    PLAN: Always show execution plan and require approval before execution.
          Useful for learning how the agent works and reviewing plans.

    NORMAL: Ask for approval only for high-risk operations (default).
            Balances autonomy with safety.

    AUTO: Fully autonomous mode - never ask for approval.
          Useful for batch processing and trusted environments.
    """
    PLAN = "plan"      # Always ask for approval
    NORMAL = "normal"  # Ask only for high-risk operations
    AUTO = "auto"      # Never ask for approval


@dataclass
class ApprovalDecision:
    """Result of an approval decision.

    Attributes:
        requires_approval: Whether approval is required
        reason: Human-readable reason for the decision
        approved: Whether user approved (None if not asked)
        approval_type: Type of approval requested (plan_review, risk_assessment, etc.)
    """
    requires_approval: bool
    reason: str
    approved: Optional[bool] = None
    approval_type: str = "general"

    def __str__(self) -> str:
        """Human-readable representation."""
        if not self.requires_approval:
            return f"No approval required: {self.reason}"
        elif self.approved is None:
            return f"Approval required ({self.approval_type}): {self.reason}"
        elif self.approved:
            return f"Approved: {self.reason}"
        else:
            return f"Rejected: {self.reason}"


class PermissionManager:
    """Manages permission modes and approval decisions.

    The PermissionManager determines when user approval is needed based on:
    - Current permission mode (PLAN/NORMAL/AUTO)
    - Task risk level
    - Task complexity
    - Operation type

    Examples:
        >>> pm = PermissionManager(mode=PermissionMode.NORMAL)
        >>> decision = pm.check_approval_required(plan, analysis)
        >>> if decision.requires_approval:
        ...     approved = pm.get_approval(plan, analysis)
        ...     if not approved:
        ...         print("Operation cancelled")
    """

    def __init__(
        self,
        mode: PermissionMode = PermissionMode.NORMAL,
        approval_callback: Optional[Callable[[ExecutionPlan, TaskAnalysis], bool]] = None
    ):
        """Initialize permission manager.

        Args:
            mode: Initial permission mode (default: NORMAL)
            approval_callback: Optional callback function for getting approval.
                             Signature: (plan, analysis) -> bool
                             If not provided, uses console input.
        """
        self.mode = mode
        self.approval_callback = approval_callback
        logger.info(f"PermissionManager initialized with mode: {mode.value}")

    def set_mode(self, mode: PermissionMode) -> None:
        """Change permission mode.

        Args:
            mode: New permission mode
        """
        old_mode = self.mode
        self.mode = mode
        logger.info(f"Permission mode changed: {old_mode.value} → {mode.value}")

    def get_mode(self) -> PermissionMode:
        """Get current permission mode.

        Returns:
            Current PermissionMode
        """
        return self.mode

    def check_approval_required(
        self,
        plan: ExecutionPlan,
        analysis: Optional[TaskAnalysis] = None
    ) -> ApprovalDecision:
        """Determine if approval is required for a plan.

        Decision logic:
        - PLAN mode: Always require approval
        - NORMAL mode: Require for high-risk or analysis.requires_approval
        - AUTO mode: Never require approval

        Args:
            plan: Execution plan to check
            analysis: Optional task analysis

        Returns:
            ApprovalDecision indicating if approval is needed and why
        """
        # AUTO mode: Never require approval
        if self.mode == PermissionMode.AUTO:
            return ApprovalDecision(
                requires_approval=False,
                reason="AUTO mode enabled - executing without approval",
                approval_type="auto"
            )

        # PLAN mode: Always require approval
        if self.mode == PermissionMode.PLAN:
            return ApprovalDecision(
                requires_approval=True,
                reason="PLAN mode enabled - review required before execution",
                approval_type="plan_review"
            )

        # NORMAL mode: Conditional approval based on risk and analysis
        if self.mode == PermissionMode.NORMAL:
            # Check plan's requires_approval flag (set by planner)
            if plan.requires_approval:
                return ApprovalDecision(
                    requires_approval=True,
                    reason=f"Plan marked as requiring approval (risk: {plan.overall_risk})",
                    approval_type="risk_assessment"
                )

            # Check task analysis if available
            if analysis and analysis.requires_approval:
                return ApprovalDecision(
                    requires_approval=True,
                    reason=f"Task analysis indicates approval needed (complexity: {analysis.complexity.name}, risk: {analysis.risk_level})",
                    approval_type="task_analysis"
                )

            # No approval needed in NORMAL mode
            return ApprovalDecision(
                requires_approval=False,
                reason="Operation within normal risk parameters",
                approval_type="normal"
            )

        # Shouldn't reach here, but default to requiring approval for safety
        logger.warning(f"Unexpected permission mode: {self.mode}")
        return ApprovalDecision(
            requires_approval=True,
            reason="Unknown permission mode - defaulting to safe behavior",
            approval_type="safety_default"
        )

    def get_approval(
        self,
        plan: ExecutionPlan,
        analysis: Optional[TaskAnalysis] = None
    ) -> bool:
        """Get user approval for a plan.

        This method checks if approval is required and gets user consent if needed.
        In AUTO mode, always returns True (no approval needed).

        Args:
            plan: Execution plan to approve
            analysis: Optional task analysis

        Returns:
            True if approved (or approval not needed), False if rejected
        """
        # Check if approval is required
        decision = self.check_approval_required(plan, analysis)

        if not decision.requires_approval:
            logger.info(f"No approval required: {decision.reason}")
            return True

        # Approval is required - get user consent
        logger.info(f"Requesting approval: {decision.reason}")

        if self.approval_callback:
            # Use custom approval callback
            approved = self.approval_callback(plan, analysis)
        else:
            # Use default console approval
            approved = self._get_console_approval(plan, analysis, decision)

        # Update decision with result
        decision.approved = approved

        if approved:
            logger.info("Approval granted by user")
        else:
            logger.info("Approval rejected by user")

        return approved

    def _get_console_approval(
        self,
        plan: ExecutionPlan,
        analysis: Optional[TaskAnalysis],
        decision: ApprovalDecision
    ) -> bool:
        """Get approval from user via console input.

        Args:
            plan: Execution plan
            analysis: Optional task analysis
            decision: Approval decision with context

        Returns:
            True if approved, False if rejected
        """
        print("\n" + "="*70)
        print("⚠️  USER APPROVAL REQUIRED")
        print("="*70)
        print(f"Mode: {self.mode.value.upper()}")
        print(f"Reason: {decision.reason}\n")

        # Show task information
        print(f"Task: {plan.task_description}")
        print(f"Risk Level: {plan.overall_risk.upper()}")
        print(f"Total Steps: {len(plan.steps)}")
        print(f"Estimated Time: {plan.total_estimated_time}")

        # Show analysis details if available
        if analysis:
            print(f"\nTask Analysis:")
            print(f"  Type: {analysis.task_type.value}")
            print(f"  Complexity: {analysis.complexity.name}")
            print(f"  Estimated Files: {analysis.estimated_files}")
            print(f"  Estimated Iterations: {analysis.estimated_iterations}")

        # Show plan overview
        print(f"\nExecution Plan:")
        for i, step in enumerate(plan.steps[:5], 1):  # Show first 5 steps
            print(f"  {i}. {step.description}")
        if len(plan.steps) > 5:
            print(f"  ... and {len(plan.steps) - 5} more steps")

        # Show rollback strategy if available
        if plan.rollback_strategy:
            print(f"\nRollback Strategy: {plan.rollback_strategy}")

        # Ask for approval
        print("\n" + "─"*70)
        print("Do you want to proceed? (yes/no): ", end="", flush=True)

        try:
            response = input().strip().lower()
            approved = response in ["yes", "y"]

            if approved:
                print("✅ Approved - proceeding with execution\n")
            else:
                print("❌ Rejected - task cancelled\n")

            return approved

        except (EOFError, KeyboardInterrupt):
            print("\n❌ Approval cancelled (interrupted)\n")
            return False

    def format_mode_description(self) -> str:
        """Get description of current permission mode.

        Returns:
            Human-readable description of current mode
        """
        descriptions = {
            PermissionMode.PLAN: (
                "📋 PLAN Mode\n"
                "  Always shows execution plan and asks for approval.\n"
                "  Best for: Learning, reviewing agent decisions, high-security environments"
            ),
            PermissionMode.NORMAL: (
                "⚖️  NORMAL Mode (Default)\n"
                "  Asks for approval only for high-risk operations.\n"
                "  Best for: Balanced autonomy and safety, production use"
            ),
            PermissionMode.AUTO: (
                "🤖 AUTO Mode\n"
                "  Fully autonomous - never asks for approval.\n"
                "  Best for: Batch processing, trusted environments, CI/CD"
            )
        }

        return descriptions.get(self.mode, "Unknown mode")

    @classmethod
    def from_string(cls, mode_str: str) -> PermissionMode:
        """Parse permission mode from string.

        Args:
            mode_str: Mode string ("plan", "normal", or "auto")

        Returns:
            PermissionMode enum value

        Raises:
            ValueError: If mode string is invalid
        """
        mode_str = mode_str.lower().strip()

        for mode in PermissionMode:
            if mode.value == mode_str:
                return mode

        raise ValueError(
            f"Invalid permission mode: '{mode_str}'. "
            f"Valid modes: {', '.join(m.value for m in PermissionMode)}"
        )
