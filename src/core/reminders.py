"""System Reminders — ephemeral contextual guidance injected before LLM calls.

Reminders are `<system-reminder>` XML blocks sent as their own user-role
message. They fire based on conditions evaluated each iteration —
periodic (every N iterations), per-turn (first iteration of each user turn),
or event-driven (something happened/didn't happen).

Design:
- Injected into current_context (in-memory) just before each LLM call
- Always a SEPARATE user-role message, never appended to a tool result.
  The system prompt tells the model that tool output is data, so a reminder
  inside a tool result reads as prompt injection. The Anthropic backend merges
  the message into the same user turn as a trailing text block after the
  tool_result blocks; OpenAI-compatible backends send it as a user message
  after the tool messages.
- The SYSTEM_REMINDERS section of the system prompt declares these blocks as
  trusted harness messages. Tool output has the tag escaped (see
  _neutralize_reminder_tags in agent.py) so files can't impersonate them.
- Content must be deterministic for a given state, so the prompt-cache
  prefix stays stable while the message is in context.
- Never persisted to JSONL. current_context is rebuilt from the store at the
  start of each user turn, so reminders last for the turn they fire in.
"""

from __future__ import annotations

import functools
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from src.observability import get_logger

logger = get_logger(__name__)


@dataclass
class ReminderState:
    """Snapshot of agent state for trigger evaluation."""

    iteration: int
    tools_used_this_session: set[str] = field(default_factory=set)
    last_task_tool_iteration: int = -1
    knowledge_db_exists: bool = False
    skills_exist: bool = False
    working_directory: str = ""
    # Lazy probe: returns the title of the in-progress task, or None.
    # Lazy because it hits the bead store and is only needed by the task nudge.
    in_progress_task_probe: Callable[[], str | None] | None = None


@dataclass
class ReminderDef:
    """Definition of a system reminder.

    Attributes:
        id: Unique identifier for the reminder.
        trigger: Function that returns True when the reminder should fire.
        content: Function that generates the reminder text.
        period: Only evaluate trigger every N iterations (0 = every iteration).
    """

    id: str
    trigger: Callable[[ReminderState], bool]
    content: Callable[[ReminderState], str]
    period: int = 0


def neutralize_reminder_tags(text: str) -> str:
    """Escape <system-reminder> tags so untrusted content can't impersonate the harness.

    Apply to every piece of external content (tool output, file contents,
    command output, error text) before it enters LLM context.
    """
    return text.replace("<system-reminder", "&lt;system-reminder").replace(
        "</system-reminder", "&lt;/system-reminder"
    )


def neutralize_content(content: Any) -> Any:
    """neutralize_reminder_tags for str or multimodal block-list message content."""
    if isinstance(content, str):
        return neutralize_reminder_tags(content)
    if isinstance(content, list):
        return [
            {**b, "text": neutralize_reminder_tags(b.get("text", ""))}
            if isinstance(b, dict) and b.get("type") == "text"
            else b
            for b in content
        ]
    return content


def _build_reminder_block(reminder: ReminderDef, state: ReminderState) -> str:
    """Build the full XML-tagged reminder string."""
    body = reminder.content(state).strip()
    return f'<system-reminder id="{reminder.id}">\n{body}\n</system-reminder>'


def inject_reminders(
    context: list[dict[str, Any]],
    state: ReminderState,
    reminders: list[ReminderDef],
) -> None:
    """Evaluate triggers and append fired reminders as one user-role message.

    Mutates context in-place. Existing messages are never modified.

    Args:
        context: The LLM conversation context (mutated).
        state: Current agent state snapshot.
        reminders: List of reminder definitions to evaluate.
    """
    if not context:
        return

    fired: list[str] = []
    for reminder in reminders:
        try:
            # Period check: only evaluate every N iterations
            if reminder.period > 0 and state.iteration % reminder.period != 0:
                continue
            if reminder.trigger(state):
                fired.append(_build_reminder_block(reminder, state))
        except Exception:
            logger.warning("reminder_trigger_error", reminder_id=reminder.id)

    if not fired:
        return

    context.append({"role": "user", "content": "\n".join(fired)})
    logger.debug(
        "reminders_injected",
        count=len(fired),
        after_role=context[-2].get("role") if len(context) > 1 else None,
    )


# ===========================================================================
# Reminder Definitions
# ===========================================================================

# -- Per-turn reminders (fire on iteration 1 = first LLM call of each user turn) --


def _trigger_align_before_acting(state: ReminderState) -> bool:
    """Fire at the start of each user turn."""
    return state.iteration == 1


def _content_align_before_acting(state: ReminderState) -> str:
    return (
        "Before implementing any non-trivial change:\n"
        "1. Ask clarifying questions when requirements are ambiguous - don't assume.\n"
        "2. Explain your approach concisely before writing code so the user can verify direction.\n"
        "3. Break complex work into steps and confirm the plan.\n"
        "4. If you're unsure about something, say so - it's better to ask than to guess wrong.\n"
        "The goal is alignment: the user should never be surprised by what you produce."
    )


def _trigger_knowledge_base(state: ReminderState) -> bool:
    """Fire at the start of each user turn when knowledge DB exists."""
    return state.iteration == 1 and state.knowledge_db_exists


def _content_knowledge_base(state: ReminderState) -> str:
    return (
        "This project has a ClarAIty knowledge database (.claraity/claraity_knowledge.db). "
        "Before reading files to understand the codebase, query the knowledge DB first "
        "using claraity_query. It contains pre-scanned architecture, components, files, "
        "decisions, and invariants. Use it to orient yourself before diving into code. "
        "Only read files when you need details the DB doesn't provide."
    )


def _trigger_available_skills(state: ReminderState) -> bool:
    """Fire at the start of each user turn when skills exist."""
    return state.iteration == 1 and state.skills_exist


def _content_available_skills(state: ReminderState) -> str:
    # List skill names so the LLM can suggest relevant ones.
    # Skills with disable-model-invocation are excluded from the list.
    skill_names: list[str] = []
    try:
        from pathlib import Path

        from src.skills.skill_loader import SkillLoader

        loader = SkillLoader(working_directory=Path(state.working_directory))
        skills, _ = loader.load_all()
        for skill in skills:
            if not skill.disable_model_invocation:
                skill_names.append(f"/{skill.id} - {skill.name}")
    except Exception:
        pass

    # Sorted so the text is stable regardless of filesystem order.
    skills_list = "\n".join(sorted(skill_names)) if skill_names else "(use lightbulb icon to browse)"
    return (
        "Skills are available in this project and globally. "
        "The user can activate a skill by typing /skill-name or via the lightbulb icon. "
        "When the user's task matches a skill, suggest they use it. "
        "To create a skill, see the Skills section of your system prompt for the "
        "project and global directories.\n\n"
        f"Available skills:\n{skills_list}"
    )


# -- Periodic reminders (fire every N iterations based on condition) --

TASK_NUDGE_STALE_ITERATIONS = 5


def _trigger_task_nudge(state: ReminderState) -> bool:
    """Fire when a task is in progress but task tools haven't been used in a while."""
    if state.iteration < 2:
        return False  # Don't nudge on the very first response
    iterations_since_task = state.iteration - state.last_task_tool_iteration
    if iterations_since_task < TASK_NUDGE_STALE_ITERATIONS:
        return False
    # Checked last: the probe reads the bead store.
    probe = state.in_progress_task_probe
    return probe is not None and probe() is not None


def _content_task_nudge(state: ReminderState) -> str:
    title = state.in_progress_task_probe() if state.in_progress_task_probe else None
    return (
        f'The task "{title}" is marked in_progress, but the task tools haven\'t been '
        "used for several steps. If it is finished, mark it completed with task_update; "
        "if the work has moved on, update the task list to match."
    )


# ---------------------------------------------------------------------------
# Registry — ordered list of all active reminders
# ---------------------------------------------------------------------------

REMINDERS: list[ReminderDef] = [
    # Per-turn (fire once at the start of each user turn)
    ReminderDef(
        id="align-before-acting",
        trigger=_trigger_align_before_acting,
        content=_content_align_before_acting,
    ),
    ReminderDef(
        id="knowledge-base",
        trigger=_trigger_knowledge_base,
        content=_content_knowledge_base,
    ),
    ReminderDef(
        id="available-skills",
        trigger=_trigger_available_skills,
        content=_content_available_skills,
    ),
    # Periodic (fire every N iterations when condition holds)
    ReminderDef(
        id="task-nudge",
        trigger=_trigger_task_nudge,
        content=_content_task_nudge,
        period=TASK_NUDGE_STALE_ITERATIONS,
    ),
]


# ---------------------------------------------------------------------------
# Helper to build ReminderState from agent loop variables
# ---------------------------------------------------------------------------


def build_reminder_state(
    iteration: int,
    tools_used: set[str],
    last_task_tool_iteration: int,
    skills_exist: bool,
    working_directory: str,
    in_progress_task_probe: Callable[[], str | None] | None = None,
) -> ReminderState:
    """Construct a ReminderState from agent loop variables."""
    kb_path = os.path.join(working_directory, ".claraity", "claraity_knowledge.db")
    knowledge_db_exists = os.path.isfile(kb_path)

    # Memoize so trigger and content see the same answer from one store read.
    if in_progress_task_probe is not None:
        in_progress_task_probe = functools.lru_cache(maxsize=1)(in_progress_task_probe)

    return ReminderState(
        iteration=iteration,
        tools_used_this_session=tools_used,
        last_task_tool_iteration=last_task_tool_iteration,
        knowledge_db_exists=knowledge_db_exists,
        skills_exist=skills_exist,
        working_directory=working_directory,
        in_progress_task_probe=in_progress_task_probe,
    )
