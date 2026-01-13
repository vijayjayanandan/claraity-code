"""Tests for Phase 1: Headroom guard and auto-compaction."""

import os
import pytest
from unittest.mock import Mock, patch, MagicMock

from src.core.context_builder import (
    ContextBuilder,
    ContextAssemblyReport,
    ContextBudgetExceededError,
)
from src.memory import MemoryManager
from src.memory.models import MessageRole


class TestHeadroomGuard:
    """Tests for headroom guard functionality."""

    @pytest.fixture
    def mock_memory_manager(self):
        """Create a mock memory manager."""
        mm = Mock(spec=MemoryManager)
        mm.working_memory = Mock()
        mm.working_memory.get_current_token_count.return_value = 1000
        mm.working_memory._compact = Mock()
        mm.episodic_memory = Mock()
        mm.episodic_memory.current_token_count = 500
        mm.episodic_memory._compress_old_turns = Mock()
        mm.optimize_context = Mock()
        mm.get_context_for_llm = Mock(return_value=[
            {"role": "user", "content": "test message"}
        ])
        return mm

    def test_build_context_with_headroom_guard_normal(self, mock_memory_manager):
        """Test headroom guard with normal (under budget) context."""
        builder = ContextBuilder(
            memory_manager=mock_memory_manager,
            max_context_tokens=100000,
            reserved_output_tokens=10000,
            safety_buffer_tokens=2000,
        )

        context, report = builder.build_context_with_headroom_guard(
            user_query="test query",
            use_rag=False,
        )

        assert context is not None
        assert report is not None
        assert not report.is_over_budget()
        # Compaction should NOT have been triggered
        mock_memory_manager.episodic_memory._compress_old_turns.assert_not_called()

    def test_get_headroom_status(self, mock_memory_manager):
        """Test quick headroom status check."""
        builder = ContextBuilder(
            memory_manager=mock_memory_manager,
            max_context_tokens=100000,
            reserved_output_tokens=10000,
            safety_buffer_tokens=2000,
        )

        status = builder.get_headroom_status()

        assert 'working_memory_tokens' in status
        assert 'episodic_memory_tokens' in status
        assert 'estimated_utilization_percent' in status
        assert 'needs_compaction' in status
        assert status['working_memory_tokens'] == 1000
        assert status['episodic_memory_tokens'] == 500


class TestCompactionTrigger:
    """Tests for compaction trigger logic."""

    def test_red_pressure_triggers_aggressive_compaction(self):
        """Test that RED pressure triggers aggressive compaction."""
        # Create a mock memory manager
        mm = Mock(spec=MemoryManager)
        mm.working_memory = Mock()
        mm.working_memory._compact = Mock()
        mm.episodic_memory = Mock()
        mm.episodic_memory._compress_old_turns = Mock()
        mm.optimize_context = Mock()

        builder = ContextBuilder(
            memory_manager=mm,
            max_context_tokens=100000,
        )

        # Create a RED pressure report (95% utilization)
        report = ContextAssemblyReport(
            total_limit=100000,
            reserved_output_tokens=10000,
            safety_buffer_tokens=0,
            system_prompt_tokens=85500,  # 95% of 90000 available
        )

        assert report.get_pressure_level() == 'red'

        # Trigger compaction
        builder._trigger_compaction(report)

        # Verify aggressive compaction was triggered
        mm.episodic_memory._compress_old_turns.assert_called_once()
        mm.working_memory._compact.assert_called_once()
        mm.optimize_context.assert_called_once()

    def test_orange_pressure_triggers_light_compaction(self):
        """Test that ORANGE pressure triggers light compaction."""
        mm = Mock(spec=MemoryManager)
        mm.working_memory = Mock()
        mm.working_memory._compact = Mock()
        mm.episodic_memory = Mock()
        mm.episodic_memory._compress_old_turns = Mock()
        mm.optimize_context = Mock()

        builder = ContextBuilder(
            memory_manager=mm,
            max_context_tokens=100000,
        )

        # Create an ORANGE pressure report (85% utilization)
        report = ContextAssemblyReport(
            total_limit=100000,
            reserved_output_tokens=10000,
            safety_buffer_tokens=0,
            system_prompt_tokens=76500,  # 85% of 90000 available
        )

        assert report.get_pressure_level() == 'orange'

        # Trigger compaction
        builder._trigger_compaction(report)

        # Verify only light compaction was triggered
        mm.episodic_memory._compress_old_turns.assert_called_once()
        mm.working_memory._compact.assert_not_called()
        mm.optimize_context.assert_not_called()


class TestStrictMode:
    """Tests for strict mode behavior."""

    def test_strict_mode_raises_exception(self):
        """Test that strict mode raises exception when over budget."""
        mm = Mock(spec=MemoryManager)
        mm.working_memory = Mock()
        mm.working_memory.get_current_token_count.return_value = 100000  # Huge
        mm.working_memory._compact = Mock()
        mm.episodic_memory = Mock()
        mm.episodic_memory.current_token_count = 50000  # Huge
        mm.episodic_memory._compress_old_turns = Mock()
        mm.optimize_context = Mock()
        mm.get_context_for_llm = Mock(return_value=[
            {"role": "user", "content": "x" * 50000}  # Large message
        ])

        builder = ContextBuilder(
            memory_manager=mm,
            max_context_tokens=10000,  # Very small limit
            reserved_output_tokens=5000,
            safety_buffer_tokens=1000,
        )

        # Enable strict mode
        with patch.dict(os.environ, {"CONTEXT_STRICT_MODE": "true"}):
            with pytest.raises(ContextBudgetExceededError):
                builder.build_context_with_headroom_guard(
                    user_query="test",
                    use_rag=False,
                    max_compaction_attempts=1,
                )

    def test_non_strict_mode_logs_warning(self):
        """Test that non-strict mode logs warning but doesn't raise."""
        mm = Mock(spec=MemoryManager)
        mm.working_memory = Mock()
        mm.working_memory.get_current_token_count.return_value = 100000
        mm.working_memory._compact = Mock()
        mm.episodic_memory = Mock()
        mm.episodic_memory.current_token_count = 50000
        mm.episodic_memory._compress_old_turns = Mock()
        mm.optimize_context = Mock()
        mm.get_context_for_llm = Mock(return_value=[
            {"role": "user", "content": "x" * 50000}
        ])

        builder = ContextBuilder(
            memory_manager=mm,
            max_context_tokens=10000,
            reserved_output_tokens=5000,
            safety_buffer_tokens=1000,
        )

        # Non-strict mode (default)
        with patch.dict(os.environ, {"CONTEXT_STRICT_MODE": "false"}):
            # Should NOT raise, just log
            context, report = builder.build_context_with_headroom_guard(
                user_query="test",
                use_rag=False,
                max_compaction_attempts=1,
            )

            assert context is not None
            assert report.is_over_budget()


class TestContextBudgetExceededError:
    """Tests for the custom exception."""

    def test_exception_message(self):
        """Test exception contains useful information."""
        with pytest.raises(ContextBudgetExceededError) as exc_info:
            raise ContextBudgetExceededError(
                "Context budget exceeded. Used 100,000 tokens, available 50,000 tokens."
            )

        assert "100,000" in str(exc_info.value)
        assert "50,000" in str(exc_info.value)

    def test_exception_inherits_from_exception(self):
        """Test exception is a proper Exception subclass."""
        assert issubclass(ContextBudgetExceededError, Exception)


class TestHeadroomStatusQuickCheck:
    """Tests for the quick headroom status check."""

    def test_needs_compaction_at_80_percent(self):
        """Test needs_compaction flag at 80% threshold."""
        mm = Mock(spec=MemoryManager)
        mm.working_memory = Mock()
        mm.episodic_memory = Mock()

        builder = ContextBuilder(
            memory_manager=mm,
            max_context_tokens=100000,
            reserved_output_tokens=10000,
            safety_buffer_tokens=2000,
            tools_schema_tokens=3000,
        )

        # Available = 100000 - 10000 - 2000 = 88000
        # System prompt estimate = 5000
        # Tools schema = 3000
        # So need working + episodic to push past 80%
        # 80% of 88000 = 70400
        # 70400 - 5000 - 3000 = 62400 from memory

        # Under 80%
        mm.working_memory.get_current_token_count.return_value = 30000
        mm.episodic_memory.current_token_count = 20000
        status = builder.get_headroom_status()
        # estimated = 30000 + 20000 + 3000 + 5000 = 58000
        # utilization = 58000 / 88000 = 65.9%
        assert not status['needs_compaction']

        # Over 80%
        mm.working_memory.get_current_token_count.return_value = 50000
        mm.episodic_memory.current_token_count = 30000
        status = builder.get_headroom_status()
        # estimated = 50000 + 30000 + 3000 + 5000 = 88000
        # utilization = 88000 / 88000 = 100%
        assert status['needs_compaction']
