"""
UI Protocol - Re-exported from src.core.protocol.

All protocol types are defined in src/core/protocol.py (the canonical home).
This module re-exports them for backward compatibility so existing
UI code can continue to use `from src.ui.protocol import ...`.
"""

# Re-export everything from core.protocol
from src.core.protocol import (  # noqa: F401
    ApprovalResult,
    ClarifyResult,
    InterruptSignal,
    PauseResult,
    PendingApproval,
    PlanApprovalResult,
    RetrySignal,
    UIProtocol,
    UserAction,
)

__all__ = [
    'ApprovalResult',
    'InterruptSignal',
    'RetrySignal',
    'PauseResult',
    'ClarifyResult',
    'PlanApprovalResult',
    'UserAction',
    'PendingApproval',
    'UIProtocol',
]
