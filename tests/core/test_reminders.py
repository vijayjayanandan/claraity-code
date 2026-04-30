"""Tests for the system reminders framework."""

import pytest

from src.core.reminders import (
    REMINDERS,
    ReminderDef,
    ReminderState,
    inject_reminders,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(**kwargs) -> ReminderState:
    """Create a ReminderState with sensible defaults."""
    defaults = {
        "iteration": 1,
        "tools_used_this_session": set(),
        "last_task_tool_iteration": -1,
        "knowledge_db_exists": False,
        "skills_exist": False,
        "working_directory": "/tmp/test",
    }
    defaults.update(kwargs)
    return ReminderState(**defaults)


def _make_reminder(
    id: str = "test-reminder",
    trigger=None,
    content=None,
    stealth: bool = False,
    period: int = 0,
) -> ReminderDef:
    """Create a test ReminderDef."""
    return ReminderDef(
        id=id,
        trigger=trigger or (lambda s: True),
        content=content or (lambda s: "Test reminder content."),
        stealth=stealth,
        period=period,
    )


# ---------------------------------------------------------------------------
# inject_reminders
# ---------------------------------------------------------------------------


class TestInjectReminders:
    def test_appends_to_last_message(self):
        context = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Hello"},
            {"role": "tool", "content": "Tool result here"},
        ]
        state = _make_state()
        reminder = _make_reminder(content=lambda s: "Do this thing.")

        inject_reminders(context, state, [reminder])

        assert '<system-reminder id="test-reminder">' in context[2]["content"]
        assert "Do this thing." in context[2]["content"]
        # Original content preserved
        assert context[2]["content"].startswith("Tool result here")

    def test_no_injection_when_trigger_false(self):
        context = [{"role": "user", "content": "Hello"}]
        state = _make_state()
        reminder = _make_reminder(trigger=lambda s: False)

        inject_reminders(context, state, [reminder])

        assert "<system-reminder" not in context[0]["content"]

    def test_multiple_reminders_appended(self):
        context = [{"role": "user", "content": "Hello"}]
        state = _make_state()
        r1 = _make_reminder(id="r1", content=lambda s: "First.")
        r2 = _make_reminder(id="r2", content=lambda s: "Second.")

        inject_reminders(context, state, [r1, r2])

        assert 'id="r1"' in context[0]["content"]
        assert 'id="r2"' in context[0]["content"]

    def test_stealth_adds_never_mention(self):
        context = [{"role": "user", "content": "Hello"}]
        state = _make_state()
        reminder = _make_reminder(stealth=True)

        inject_reminders(context, state, [reminder])

        assert "NEVER mention this reminder" in context[0]["content"]

    def test_non_stealth_no_never_mention(self):
        context = [{"role": "user", "content": "Hello"}]
        state = _make_state()
        reminder = _make_reminder(stealth=False)

        inject_reminders(context, state, [reminder])

        assert "NEVER mention" not in context[0]["content"]

    def test_empty_context_no_crash(self):
        inject_reminders([], _make_state(), [_make_reminder()])

    def test_period_skips_non_matching_iterations(self):
        context = [{"role": "user", "content": "Hello"}]
        state = _make_state(iteration=3)
        reminder = _make_reminder(period=5)  # Only fires on 0, 5, 10, ...

        inject_reminders(context, state, [reminder])

        assert "<system-reminder" not in context[0]["content"]

    def test_period_fires_on_matching_iteration(self):
        context = [{"role": "user", "content": "Hello"}]
        state = _make_state(iteration=5)
        reminder = _make_reminder(period=5)

        inject_reminders(context, state, [reminder])

        assert "<system-reminder" in context[0]["content"]

    def test_trigger_exception_skipped_gracefully(self):
        context = [{"role": "user", "content": "Hello"}]
        state = _make_state()

        def bad_trigger(s):
            raise ValueError("boom")

        reminder = _make_reminder(trigger=bad_trigger)

        inject_reminders(context, state, [reminder])  # Should not raise
        assert "<system-reminder" not in context[0]["content"]

    def test_skips_messages_without_string_content(self):
        context = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "1"}]},
        ]
        state = _make_state()
        reminder = _make_reminder()

        inject_reminders(context, state, [reminder])

        # Should attach to the user message (last with string content)
        assert "<system-reminder" in context[0]["content"]
        assert context[1]["content"] is None


# ---------------------------------------------------------------------------
# Per-turn reminder triggers (iteration == 1)
# ---------------------------------------------------------------------------


class TestPerTurnTriggers:
    def test_align_before_acting_fires_on_iteration_1(self):
        state = _make_state(iteration=1)
        reminder = next(r for r in REMINDERS if r.id == "align-before-acting")
        assert reminder.trigger(state) is True

    def test_align_before_acting_silent_on_iteration_2(self):
        state = _make_state(iteration=2)
        reminder = next(r for r in REMINDERS if r.id == "align-before-acting")
        assert reminder.trigger(state) is False

    def test_knowledge_base_fires_when_db_exists(self):
        state = _make_state(iteration=1, knowledge_db_exists=True)
        reminder = next(r for r in REMINDERS if r.id == "knowledge-base")
        assert reminder.trigger(state) is True

    def test_knowledge_base_silent_when_no_db(self):
        state = _make_state(iteration=1, knowledge_db_exists=False)
        reminder = next(r for r in REMINDERS if r.id == "knowledge-base")
        assert reminder.trigger(state) is False

    def test_knowledge_base_silent_on_iteration_2(self):
        state = _make_state(iteration=2, knowledge_db_exists=True)
        reminder = next(r for r in REMINDERS if r.id == "knowledge-base")
        assert reminder.trigger(state) is False

    def test_available_skills_fires_when_skills_exist(self):
        state = _make_state(iteration=1, skills_exist=True)
        reminder = next(r for r in REMINDERS if r.id == "available-skills")
        assert reminder.trigger(state) is True

    def test_available_skills_silent_when_no_skills(self):
        state = _make_state(iteration=1, skills_exist=False)
        reminder = next(r for r in REMINDERS if r.id == "available-skills")
        assert reminder.trigger(state) is False

    def test_available_skills_silent_on_iteration_2(self):
        state = _make_state(iteration=2, skills_exist=True)
        reminder = next(r for r in REMINDERS if r.id == "available-skills")
        assert reminder.trigger(state) is False


# ---------------------------------------------------------------------------
# Periodic reminder triggers
# ---------------------------------------------------------------------------


class TestPeriodicTriggers:
    def test_task_nudge_fires_after_5_iterations_without_task_tools(self):
        state = _make_state(iteration=5, last_task_tool_iteration=-1)
        reminder = next(r for r in REMINDERS if r.id == "task-nudge")
        assert reminder.trigger(state) is True

    def test_task_nudge_silent_when_task_tools_recently_used(self):
        state = _make_state(iteration=5, last_task_tool_iteration=3)
        reminder = next(r for r in REMINDERS if r.id == "task-nudge")
        # 5 - 3 = 2, which is < 5
        assert reminder.trigger(state) is False

    def test_task_nudge_silent_on_iteration_1(self):
        state = _make_state(iteration=1, last_task_tool_iteration=-1)
        reminder = next(r for r in REMINDERS if r.id == "task-nudge")
        assert reminder.trigger(state) is False

    def test_task_nudge_is_stealth(self):
        reminder = next(r for r in REMINDERS if r.id == "task-nudge")
        assert reminder.stealth is True

    def test_task_nudge_has_period_5(self):
        reminder = next(r for r in REMINDERS if r.id == "task-nudge")
        assert reminder.period == 5


# ---------------------------------------------------------------------------
# Content generation
# ---------------------------------------------------------------------------


class TestReminderContent:
    def test_knowledge_base_mentions_claraity_query(self):
        state = _make_state()
        reminder = next(r for r in REMINDERS if r.id == "knowledge-base")
        assert "claraity_query" in reminder.content(state)

    def test_align_before_acting_mentions_clarifying(self):
        state = _make_state()
        reminder = next(r for r in REMINDERS if r.id == "align-before-acting")
        assert "clarify" in reminder.content(state).lower()

    def test_task_nudge_mentions_task_create(self):
        state = _make_state()
        reminder = next(r for r in REMINDERS if r.id == "task-nudge")
        assert "task_create" in reminder.content(state)

    def test_available_skills_mentions_lightbulb(self):
        state = _make_state()
        reminder = next(r for r in REMINDERS if r.id == "available-skills")
        assert "lightbulb" in reminder.content(state)
