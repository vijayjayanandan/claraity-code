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
    period: int = 0,
) -> ReminderDef:
    """Create a test ReminderDef."""
    return ReminderDef(
        id=id,
        trigger=trigger or (lambda s: True),
        content=content or (lambda s: "Test reminder content."),
        period=period,
    )


# ---------------------------------------------------------------------------
# inject_reminders
# ---------------------------------------------------------------------------


class TestInjectReminders:
    def test_appends_separate_user_message_after_tool_result(self):
        context = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Hello"},
            {"role": "tool", "tool_call_id": "c1", "content": "Tool result here"},
        ]
        state = _make_state()
        reminder = _make_reminder(content=lambda s: "Do this thing.")

        inject_reminders(context, state, [reminder])

        assert len(context) == 4
        assert context[3]["role"] == "user"
        assert '<system-reminder id="test-reminder">' in context[3]["content"]
        assert "Do this thing." in context[3]["content"]

    def test_never_modifies_existing_messages(self):
        context = [
            {"role": "user", "content": "Hello"},
            {"role": "tool", "tool_call_id": "c1", "content": "Tool result here"},
        ]
        before = [dict(m) for m in context]

        inject_reminders(context, _make_state(), [_make_reminder()])

        assert context[:2] == before
        assert "<system-reminder" not in context[1]["content"]

    def test_no_injection_when_trigger_false(self):
        context = [{"role": "user", "content": "Hello"}]
        state = _make_state()
        reminder = _make_reminder(trigger=lambda s: False)

        inject_reminders(context, state, [reminder])

        assert len(context) == 1

    def test_multiple_reminders_share_one_message(self):
        context = [{"role": "user", "content": "Hello"}]
        state = _make_state()
        r1 = _make_reminder(id="r1", content=lambda s: "First.")
        r2 = _make_reminder(id="r2", content=lambda s: "Second.")

        inject_reminders(context, state, [r1, r2])

        assert len(context) == 2
        assert 'id="r1"' in context[1]["content"]
        assert 'id="r2"' in context[1]["content"]

    def test_no_hide_from_user_instruction(self):
        context = [{"role": "user", "content": "Hello"}]
        inject_reminders(context, _make_state(iteration=1), REMINDERS)
        assert "NEVER mention" not in context[-1]["content"]

    def test_deterministic_output(self):
        a = [{"role": "user", "content": "Hello"}]
        b = [{"role": "user", "content": "Hello"}]
        inject_reminders(a, _make_state(), REMINDERS)
        inject_reminders(b, _make_state(), REMINDERS)
        assert a == b

    def test_empty_context_no_crash(self):
        context: list = []
        inject_reminders(context, _make_state(), [_make_reminder()])
        assert context == []

    def test_period_skips_non_matching_iterations(self):
        context = [{"role": "user", "content": "Hello"}]
        state = _make_state(iteration=3)
        reminder = _make_reminder(period=5)  # Only fires on 0, 5, 10, ...

        inject_reminders(context, state, [reminder])

        assert len(context) == 1

    def test_period_fires_on_matching_iteration(self):
        context = [{"role": "user", "content": "Hello"}]
        state = _make_state(iteration=5)
        reminder = _make_reminder(period=5)

        inject_reminders(context, state, [reminder])

        assert "<system-reminder" in context[-1]["content"]

    def test_trigger_exception_skipped_gracefully(self):
        context = [{"role": "user", "content": "Hello"}]
        state = _make_state()

        def bad_trigger(s):
            raise ValueError("boom")

        reminder = _make_reminder(trigger=bad_trigger)

        inject_reminders(context, state, [reminder])  # Should not raise
        assert len(context) == 1


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


def _in_progress(title="Fix login bug"):
    return lambda: title


def _nothing_in_progress():
    return None


class TestPeriodicTriggers:
    def test_task_nudge_fires_when_in_progress_task_is_stale(self):
        state = _make_state(
            iteration=5, last_task_tool_iteration=-1, in_progress_task_probe=_in_progress()
        )
        reminder = next(r for r in REMINDERS if r.id == "task-nudge")
        assert reminder.trigger(state) is True

    def test_task_nudge_silent_when_nothing_in_progress(self):
        state = _make_state(
            iteration=5, last_task_tool_iteration=-1, in_progress_task_probe=_nothing_in_progress
        )
        reminder = next(r for r in REMINDERS if r.id == "task-nudge")
        assert reminder.trigger(state) is False

    def test_task_nudge_silent_without_probe(self):
        state = _make_state(iteration=5, last_task_tool_iteration=-1)
        reminder = next(r for r in REMINDERS if r.id == "task-nudge")
        assert reminder.trigger(state) is False

    def test_task_nudge_silent_when_task_tools_recently_used(self):
        state = _make_state(
            iteration=5, last_task_tool_iteration=3, in_progress_task_probe=_in_progress()
        )
        reminder = next(r for r in REMINDERS if r.id == "task-nudge")
        # 5 - 3 = 2, which is < 5
        assert reminder.trigger(state) is False

    def test_task_nudge_silent_on_iteration_1(self):
        state = _make_state(
            iteration=1, last_task_tool_iteration=-1, in_progress_task_probe=_in_progress()
        )
        reminder = next(r for r in REMINDERS if r.id == "task-nudge")
        assert reminder.trigger(state) is False

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

    def test_task_nudge_names_the_task(self):
        state = _make_state(in_progress_task_probe=_in_progress("Fix login bug"))
        reminder = next(r for r in REMINDERS if r.id == "task-nudge")
        content = reminder.content(state)
        assert "Fix login bug" in content
        assert "task_update" in content

    def test_available_skills_mentions_lightbulb(self):
        state = _make_state()
        reminder = next(r for r in REMINDERS if r.id == "available-skills")
        assert "lightbulb" in reminder.content(state)
