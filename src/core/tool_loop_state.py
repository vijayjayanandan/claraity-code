"""
Tool Loop State - Structured state for the agent's tool execution loop.

Replaces 12+ local variables that were shared across stream_response(),
making the loop state explicit, testable, and passable to phase functions.

Lifecycle:
- Created once per stream_response() call
- reset_iteration() called at the top of each while-loop iteration
- reset_budgets_after_continue() called when user chooses "Continue" at pause
"""

import time
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


@dataclass
class ToolLoopState:
    """
    All mutable state for one tool-execution loop.

    Attributes:
        current_context: LLM conversation context (mutated in-place).
        tool_call_count: Running total of tool calls executed.
        iteration: Current LLM-call iteration (1-based).
        pause_continue_count: How many times user chose "Continue" at pause.
        loop_start_time: Monotonic timestamp when loop started.

        response_content: Text content from the current LLM response.
        tool_calls: Tool calls from the current LLM response (or None).
        tool_messages: Tool result messages for the current iteration.
        blocked_calls: Summaries of calls blocked by repeat detection.
        user_rejected: True if user rejected a tool (breaks the loop).
        provider_error: User-friendly error message if LLM call failed.

        MAX_TOOL_CALLS: Primary budget - generous for multi-step workflows.
        MAX_WALL_TIME_SECONDS: Wall-time budget (None = disabled).
        ABSOLUTE_MAX_ITERATIONS: Emergency brake.
        MAX_PAUSE_CONTINUES: Safety cap on continuation count.
        MAX_ERROR_BUDGET_RESUMES: Cap on error budget "Continue" loops.
    """

    current_context: List[Dict[str, Any]]

    # Accumulated counters (persist across iterations)
    tool_call_count: int = 0
    iteration: int = 0
    pause_continue_count: int = 0
    loop_start_time: float = field(default_factory=time.monotonic)

    # Per-iteration state (reset each loop)
    response_content: str = ""
    tool_calls: Optional[Any] = None
    tool_messages: List[Dict[str, Any]] = field(default_factory=list)
    blocked_calls: List[str] = field(default_factory=list)
    user_rejected: bool = False
    provider_error: Optional[str] = None

    # Budget constants
    MAX_TOOL_CALLS: int = 200
    MAX_WALL_TIME_SECONDS: Optional[int] = None
    ABSOLUTE_MAX_ITERATIONS: int = 50
    MAX_PAUSE_CONTINUES: int = 3
    MAX_ERROR_BUDGET_RESUMES: int = 2

    def reset_iteration(self) -> None:
        """Reset per-iteration state at the top of the while-loop."""
        self.blocked_calls.clear()
        self.response_content = ""
        self.tool_calls = None
        self.tool_messages = []
        self.user_rejected = False
        self.provider_error = None

    def reset_budgets_after_continue(self) -> None:
        """Reset budgets when user chooses 'Continue' at a pause prompt."""
        self.pause_continue_count += 1
        self.tool_call_count = 0
        self.iteration = 0
        self.loop_start_time = time.monotonic()

    @property
    def elapsed_seconds(self) -> float:
        """Seconds since the loop started."""
        return time.monotonic() - self.loop_start_time
