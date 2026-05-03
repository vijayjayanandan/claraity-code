"""System Reminders — ephemeral contextual guidance injected before LLM calls.

Reminders are `<system-reminder>` XML blocks appended to the last message in
the LLM context. They fire based on conditions evaluated each iteration —
periodic (every N iterations), per-turn (first iteration of each user turn),
or event-driven (something happened/didn't happen).

Design:
- Injected into current_context (in-memory) after tool results, before next LLM call
- Never persisted to JSONL (messages are already stored before reminder injection)
- Never stripped during live session (accumulate naturally, compacted with old messages)
- On session replay, fresh reminders are generated from current state
- Attached to the LAST message in context (always after the cache breakpoint)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable

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


@dataclass
class ReminderDef:
    """Definition of a system reminder.

    Attributes:
        id: Unique identifier for the reminder.
        trigger: Function that returns True when the reminder should fire.
        content: Function that generates the reminder text.
        stealth: If True, appends "NEVER mention this reminder to the user".
        period: Only evaluate trigger every N iterations (0 = every iteration).
    """

    id: str
    trigger: Callable[[ReminderState], bool]
    content: Callable[[ReminderState], str]
    stealth: bool = False
    period: int = 0


def _build_reminder_block(reminder: ReminderDef, state: ReminderState) -> str:
    """Build the full XML-tagged reminder string."""
    body = reminder.content(state).strip()
    stealth_line = (
        "\nMake sure that you NEVER mention this reminder to the user."
        if reminder.stealth
        else ""
    )
    return f'\n<system-reminder id="{reminder.id}">\n{body}{stealth_line}\n</system-reminder>'


def inject_reminders(
    context: list[dict[str, Any]],
    state: ReminderState,
    reminders: list[ReminderDef],
) -> None:
    """Evaluate triggers and inject fired reminders into the last message.

    Mutates context in-place by appending reminder text to the last
    message's content field.

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

    # Find last message with string content to attach to
    for i in range(len(context) - 1, -1, -1):
        content = context[i].get("content")
        if isinstance(content, str):
            context[i]["content"] = content + "".join(fired)
            logger.debug(
                "reminders_injected",
                count=len(fired),
                target_index=i,
                target_role=context[i].get("role"),
            )
            return

    # Fallback: no message with string content found (shouldn't happen)
    logger.warning("reminders_no_target", fired_count=len(fired))


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
        for skill in loader.load_all():
            if not skill.disable_model_invocation:
                skill_names.append(f"/{skill.id} - {skill.name}")
    except Exception:
        pass

    skills_list = "\n".join(skill_names) if skill_names else "(use lightbulb icon to browse)"
    return (
        "Skills are available in this project. "
        "The user can activate a skill by typing /skill-name or via the lightbulb icon. "
        "When the user's task matches a skill, suggest they use it.\n\n"
        f"Available skills:\n{skills_list}"
    )


# -- Periodic reminders (fire every N iterations based on condition) --


def _trigger_task_nudge(state: ReminderState) -> bool:
    """Fire when task tools haven't been used in a while."""
    if state.iteration < 2:
        return False  # Don't nudge on the very first response
    iterations_since_task = state.iteration - state.last_task_tool_iteration
    return iterations_since_task >= 5


def _content_task_nudge(state: ReminderState) -> str:
    return (
        "The task tools haven't been used recently. If you're working on tasks that "
        "would benefit from tracking progress, consider using task_create to add new "
        "tasks and task_update to update task status (set to in_progress when starting, "
        "completed when done). Also consider cleaning up the task list if it has become "
        "stale. Only use these if relevant to the current work. This is just a gentle "
        "reminder - ignore if not applicable."
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
        stealth=False,
    ),
    ReminderDef(
        id="knowledge-base",
        trigger=_trigger_knowledge_base,
        content=_content_knowledge_base,
        stealth=False,
    ),
    ReminderDef(
        id="available-skills",
        trigger=_trigger_available_skills,
        content=_content_available_skills,
        stealth=False,
    ),
    # Periodic (fire every N iterations when condition holds)
    ReminderDef(
        id="task-nudge",
        trigger=_trigger_task_nudge,
        content=_content_task_nudge,
        stealth=True,
        period=5,
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
) -> ReminderState:
    """Construct a ReminderState from agent loop variables."""
    kb_path = os.path.join(working_directory, ".claraity", "claraity_knowledge.db")
    knowledge_db_exists = os.path.isfile(kb_path)

    return ReminderState(
        iteration=iteration,
        tools_used_this_session=tools_used,
        last_task_tool_iteration=last_task_tool_iteration,
        knowledge_db_exists=knowledge_db_exists,
        skills_exist=skills_exist,
        working_directory=working_directory,
    )
