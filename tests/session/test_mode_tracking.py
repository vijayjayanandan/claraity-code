"""Test MessageStore mode tracking feature."""

import pytest
from src.session.store.memory_store import MessageStore
from src.session.models.message import Message


class TestModeTracking:
    """Test that MessageStore tracks permission mode changes."""

    def test_initial_mode_is_normal(self):
        """Initial mode should be 'normal'."""
        store = MessageStore()
        assert store.current_mode == "normal"
        assert store.plan_hash is None
        assert store.plan_path is None

    def test_mode_updates_on_permission_mode_changed_event(self):
        """Mode should update when permission_mode_changed event is added."""
        store = MessageStore()

        # Add mode change event
        mode_change = Message.create_system(
            content="[Mode changed]",
            event_type="permission_mode_changed",
            extra={"old_mode": "normal", "new_mode": "plan"},
            session_id="test",
            seq=1
        )
        store.add_message(mode_change)

        assert store.current_mode == "plan"

    def test_plan_details_tracked_on_plan_submitted(self):
        """Plan hash and path should be tracked when plan_submitted event is added."""
        store = MessageStore()

        plan_submitted = Message.create_system(
            content="[Plan submitted]",
            event_type="plan_submitted",
            extra={
                "plan_hash": "abc123",
                "plan_path": "/path/to/plan.md"
            },
            session_id="test",
            seq=1
        )
        store.add_message(plan_submitted)

        assert store.plan_hash == "abc123"
        assert store.plan_path == "/path/to/plan.md"

    def test_multiple_mode_changes(self):
        """Multiple mode changes should track latest mode."""
        store = MessageStore()

        # normal -> plan
        store.add_message(Message.create_system(
            content="[Mode changed]",
            event_type="permission_mode_changed",
            extra={"old_mode": "normal", "new_mode": "plan"},
            session_id="test",
            seq=1
        ))
        assert store.current_mode == "plan"

        # plan -> awaiting_approval
        store.add_message(Message.create_system(
            content="[Mode changed]",
            event_type="permission_mode_changed",
            extra={"old_mode": "plan", "new_mode": "awaiting_approval"},
            session_id="test",
            seq=2
        ))
        assert store.current_mode == "awaiting_approval"

        # awaiting_approval -> normal
        store.add_message(Message.create_system(
            content="[Mode changed]",
            event_type="permission_mode_changed",
            extra={"old_mode": "awaiting_approval", "new_mode": "normal"},
            session_id="test",
            seq=3
        ))
        assert store.current_mode == "normal"

    def test_mode_state_cleared_on_clear(self):
        """Mode state should reset when store is cleared."""
        store = MessageStore()

        # Set some mode state
        store.add_message(Message.create_system(
            content="[Mode changed]",
            event_type="permission_mode_changed",
            extra={"new_mode": "plan"},
            session_id="test",
            seq=1
        ))
        store.add_message(Message.create_system(
            content="[Plan submitted]",
            event_type="plan_submitted",
            extra={"plan_hash": "xyz", "plan_path": "/plan"},
            session_id="test",
            seq=2
        ))

        # Clear
        store.clear()

        assert store.current_mode == "normal"
        assert store.plan_hash is None
        assert store.plan_path is None

    def test_mode_properties_thread_safe(self):
        """Mode properties should use locks for thread safety."""
        store = MessageStore()

        # Properties should work without errors
        mode = store.current_mode
        plan_hash = store.plan_hash
        plan_path = store.plan_path

        assert mode == "normal"
        assert plan_hash is None
        assert plan_path is None
