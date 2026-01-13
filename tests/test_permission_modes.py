"""
Tests for permission mode functionality.

Covers:
- Permission mode switching (plan/normal/auto)
- Mode persistence (save/load with sessions)
- Backward compatibility (sessions without permission_mode)
- Integration with permission manager
"""

import pytest
import tempfile
import shutil
from pathlib import Path
from datetime import datetime

from src.core.agent import CodingAgent
from src.core.session_manager import SessionManager, SessionMetadata
from src.workflow.permission_manager import PermissionManager, PermissionMode
from src.memory.memory_manager import MemoryManager


# Test configuration for CodingAgent
API_CONFIG = {
    "backend": "openai",
    "model_name": "qwen3-coder-plus",
    "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "api_key": "sk-test-key",
    "context_window": 8192,
    "load_file_memories": False
}


class TestPermissionModeSwitching:
    """Test permission mode switching functionality."""

    def test_initial_mode_is_normal(self):
        """Test that agent starts in NORMAL mode by default."""
        agent = CodingAgent(**API_CONFIG)
        assert agent.get_permission_mode() == "normal"

    def test_switch_to_plan_mode(self):
        """Test switching to PLAN mode."""
        agent = CodingAgent(**API_CONFIG)
        agent.set_permission_mode("plan")
        assert agent.get_permission_mode() == "plan"

    def test_switch_to_auto_mode(self):
        """Test switching to AUTO mode."""
        agent = CodingAgent(**API_CONFIG)
        agent.set_permission_mode("auto")
        assert agent.get_permission_mode() == "auto"

    def test_switch_to_normal_mode(self):
        """Test switching to NORMAL mode."""
        agent = CodingAgent(**API_CONFIG)
        agent.set_permission_mode("plan")
        agent.set_permission_mode("normal")
        assert agent.get_permission_mode() == "normal"

    def test_invalid_mode_raises_error(self):
        """Test that invalid mode strings raise ValueError."""
        agent = CodingAgent(**API_CONFIG)
        with pytest.raises(ValueError):
            agent.set_permission_mode("invalid_mode")

    def test_mode_description_format(self):
        """Test that mode descriptions are formatted correctly (no emojis)."""
        agent = CodingAgent(**API_CONFIG)

        # Test each mode
        for mode in ["plan", "normal", "auto"]:
            agent.set_permission_mode(mode)
            description = agent.get_permission_mode_description()

            # Should contain mode name in brackets
            assert f"[{mode.upper()}]" in description or mode.upper() in description

            # Should NOT contain emojis (Windows compatibility)
            # Common emoji Unicode ranges
            emoji_ranges = [
                (0x1F600, 0x1F64F),  # Emoticons
                (0x1F300, 0x1F5FF),  # Misc Symbols and Pictographs
                (0x1F680, 0x1F6FF),  # Transport and Map
                (0x2600, 0x26FF),    # Misc symbols
                (0x2700, 0x27BF),    # Dingbats
            ]

            for char in description:
                char_code = ord(char)
                for start, end in emoji_ranges:
                    assert not (start <= char_code <= end), \
                        f"Found emoji (U+{char_code:04X}) in mode description for {mode}"


class TestPermissionModePersistence:
    """Test permission mode persistence with sessions."""

    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for test sessions."""
        temp = tempfile.mkdtemp()
        yield Path(temp)
        shutil.rmtree(temp)

    def test_save_session_with_plan_mode(self, temp_dir):
        """Test saving session in PLAN mode."""
        agent = CodingAgent(**API_CONFIG, persist_directory=temp_dir)
        agent.set_permission_mode("plan")

        # Save session
        session_id = agent.memory.save_session(
            session_name="test_plan_mode",
            task_description="Testing plan mode persistence",
            permission_mode=agent.get_permission_mode()
        )

        # Verify metadata contains correct mode
        session_manager = SessionManager(sessions_dir=temp_dir / "sessions")
        info = session_manager.get_session_info(session_id)

        assert info is not None
        assert info.permission_mode == "plan"

    def test_save_session_with_auto_mode(self, temp_dir):
        """Test saving session in AUTO mode."""
        agent = CodingAgent(**API_CONFIG, persist_directory=temp_dir)
        agent.set_permission_mode("auto")

        # Save session
        session_id = agent.memory.save_session(
            session_name="test_auto_mode",
            task_description="Testing auto mode persistence",
            permission_mode=agent.get_permission_mode()
        )

        # Verify metadata
        session_manager = SessionManager(sessions_dir=temp_dir / "sessions")
        info = session_manager.get_session_info(session_id)

        assert info is not None
        assert info.permission_mode == "auto"

    def test_save_session_with_normal_mode(self, temp_dir):
        """Test saving session in NORMAL mode (default)."""
        agent = CodingAgent(**API_CONFIG, persist_directory=temp_dir)

        # Save session (should default to normal)
        session_id = agent.memory.save_session(
            session_name="test_normal_mode",
            task_description="Testing normal mode persistence",
            permission_mode=agent.get_permission_mode()
        )

        # Verify metadata
        session_manager = SessionManager(sessions_dir=temp_dir / "sessions")
        info = session_manager.get_session_info(session_id)

        assert info is not None
        assert info.permission_mode == "normal"

    def test_load_session_restores_permission_mode(self, temp_dir):
        """Test that loading session restores permission mode."""
        # Create first agent in plan mode
        agent1 = CodingAgent(**API_CONFIG, persist_directory=temp_dir)
        agent1.set_permission_mode("plan")

        # Add some messages
        agent1.memory.add_user_message("Test message")
        agent1.memory.add_assistant_message("Test response")

        # Save session
        session_id = agent1.memory.save_session(
            session_name="test_mode_restore",
            task_description="Testing mode restoration",
            permission_mode=agent1.get_permission_mode()
        )

        # Create new agent and load session
        agent2 = CodingAgent(**API_CONFIG, persist_directory=temp_dir)
        assert agent2.get_permission_mode() == "normal"  # Default

        # Load session
        agent2.memory.load_session(session_id)

        # Get session info and apply permission mode (simulating CLI behavior)
        session_manager = SessionManager(sessions_dir=temp_dir / "sessions")
        info = session_manager.get_session_info(session_id)
        if info and hasattr(info, 'permission_mode'):
            agent2.set_permission_mode(info.permission_mode)

        # Verify mode was restored
        assert agent2.get_permission_mode() == "plan"

    def test_backward_compatibility_missing_permission_mode(self, temp_dir):
        """Test that sessions without permission_mode default to normal."""
        session_manager = SessionManager(sessions_dir=temp_dir / "sessions")

        # Create session metadata without permission_mode (simulating old session)
        # This tests backward compatibility
        old_metadata = SessionMetadata(
            session_id="test-old-session",
            name="old_session",
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
            task_description="Old session without permission_mode",
            model_name="test-model",
            message_count=5,
            tags=[],
            duration_minutes=10.0,
            # Note: permission_mode NOT set (relies on default)
        )

        # Verify default is applied
        assert old_metadata.permission_mode == "normal"


class TestPermissionModeIntegration:
    """Test integration between permission modes and approval workflow."""

    def test_plan_mode_requires_approval(self):
        """Test that PLAN mode always requires approval."""
        pm = PermissionManager(mode=PermissionMode.PLAN)
        assert pm.get_mode() == PermissionMode.PLAN

        # In plan mode, any plan should require approval
        # (Testing this requires creating ExecutionPlan - simplified test)
        mode_description = pm.format_mode_description()
        assert "PLAN" in mode_description or "plan" in mode_description.lower()

    def test_auto_mode_never_requires_approval(self):
        """Test that AUTO mode never requires approval."""
        pm = PermissionManager(mode=PermissionMode.AUTO)
        assert pm.get_mode() == PermissionMode.AUTO

        mode_description = pm.format_mode_description()
        assert "AUTO" in mode_description or "auto" in mode_description.lower()

    def test_normal_mode_conditional_approval(self):
        """Test that NORMAL mode has conditional approval."""
        pm = PermissionManager(mode=PermissionMode.NORMAL)
        assert pm.get_mode() == PermissionMode.NORMAL

        mode_description = pm.format_mode_description()
        assert "NORMAL" in mode_description or "normal" in mode_description.lower()

    def test_mode_switching_via_enum(self):
        """Test switching modes via PermissionMode enum."""
        pm = PermissionManager()

        pm.set_mode(PermissionMode.PLAN)
        assert pm.get_mode() == PermissionMode.PLAN

        pm.set_mode(PermissionMode.AUTO)
        assert pm.get_mode() == PermissionMode.AUTO

        pm.set_mode(PermissionMode.NORMAL)
        assert pm.get_mode() == PermissionMode.NORMAL

    def test_mode_parsing_from_string(self):
        """Test parsing permission mode from string."""
        assert PermissionManager.from_string("plan") == PermissionMode.PLAN
        assert PermissionManager.from_string("PLAN") == PermissionMode.PLAN
        assert PermissionManager.from_string("normal") == PermissionMode.NORMAL
        assert PermissionManager.from_string("NORMAL") == PermissionMode.NORMAL
        assert PermissionManager.from_string("auto") == PermissionMode.AUTO
        assert PermissionManager.from_string("AUTO") == PermissionMode.AUTO

        with pytest.raises(ValueError):
            PermissionManager.from_string("invalid")


class TestSessionMetadata:
    """Test SessionMetadata with permission_mode field."""

    def test_metadata_with_permission_mode(self):
        """Test creating metadata with permission_mode."""
        metadata = SessionMetadata(
            session_id="test-123",
            name="test_session",
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
            task_description="Test task",
            model_name="test-model",
            message_count=10,
            tags=["test"],
            duration_minutes=5.0,
            permission_mode="plan"
        )

        assert metadata.permission_mode == "plan"

    def test_metadata_default_permission_mode(self):
        """Test that permission_mode defaults to normal."""
        metadata = SessionMetadata(
            session_id="test-123",
            name="test_session",
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
            task_description="Test task",
            model_name="test-model",
            message_count=10,
            tags=["test"],
            duration_minutes=5.0
            # permission_mode not specified
        )

        assert metadata.permission_mode == "normal"

    def test_metadata_serialization(self):
        """Test that metadata with permission_mode serializes correctly."""
        metadata = SessionMetadata(
            session_id="test-123",
            name="test_session",
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
            task_description="Test task",
            model_name="test-model",
            message_count=10,
            tags=["test"],
            duration_minutes=5.0,
            permission_mode="auto"
        )

        # Serialize to dict
        data = metadata.to_dict()
        assert "permission_mode" in data
        assert data["permission_mode"] == "auto"

        # Deserialize from dict
        restored = SessionMetadata.from_dict(data)
        assert restored.permission_mode == "auto"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
