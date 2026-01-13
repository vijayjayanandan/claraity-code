"""Tests for ContextAssemblyReport and context token tracking."""

import pytest
from src.core.context_builder import ContextAssemblyReport


class TestContextAssemblyReport:
    """Tests for ContextAssemblyReport dataclass."""

    def test_basic_creation(self):
        """Test basic report creation with computed fields."""
        report = ContextAssemblyReport(
            total_limit=200000,
            reserved_output_tokens=12000,
            safety_buffer_tokens=2000,
            system_prompt_tokens=5000,
            tools_schema_tokens=3000,
            file_references_tokens=0,
            rag_tokens=0,
            agent_state_tokens=500,
            working_memory_tokens=10000,
            episodic_memory_tokens=2000,
        )

        # Check computed fields
        assert report.total_input_tokens == 20500  # Sum of all buckets
        assert report.available_for_input == 186000  # 200000 - 12000 - 2000
        assert report.headroom_tokens == 165500  # 186000 - 20500

    def test_utilization_percent(self):
        """Test utilization percentage calculation."""
        report = ContextAssemblyReport(
            total_limit=100000,
            reserved_output_tokens=10000,
            safety_buffer_tokens=0,
            system_prompt_tokens=45000,  # 50% of available (90000)
        )

        assert report.available_for_input == 90000
        assert report.total_input_tokens == 45000
        assert report.utilization_percent == 50.0

    def test_pressure_level_green(self):
        """Test green pressure level (< 60%)."""
        report = ContextAssemblyReport(
            total_limit=100000,
            reserved_output_tokens=10000,
            safety_buffer_tokens=0,
            system_prompt_tokens=45000,  # 50% utilization
        )

        assert report.get_pressure_level() == 'green'
        assert not report.is_over_budget()

    def test_pressure_level_yellow(self):
        """Test yellow pressure level (60-80%)."""
        report = ContextAssemblyReport(
            total_limit=100000,
            reserved_output_tokens=10000,
            safety_buffer_tokens=0,
            system_prompt_tokens=63000,  # 70% utilization
        )

        assert report.get_pressure_level() == 'yellow'
        assert not report.is_over_budget()

    def test_pressure_level_orange(self):
        """Test orange pressure level (80-90%)."""
        report = ContextAssemblyReport(
            total_limit=100000,
            reserved_output_tokens=10000,
            safety_buffer_tokens=0,
            system_prompt_tokens=76500,  # 85% utilization
        )

        assert report.get_pressure_level() == 'orange'
        assert not report.is_over_budget()

    def test_pressure_level_red(self):
        """Test red pressure level (>= 90%)."""
        report = ContextAssemblyReport(
            total_limit=100000,
            reserved_output_tokens=10000,
            safety_buffer_tokens=0,
            system_prompt_tokens=85500,  # 95% utilization
        )

        assert report.get_pressure_level() == 'red'
        assert not report.is_over_budget()

    def test_over_budget_detection(self):
        """Test detection when over budget."""
        report = ContextAssemblyReport(
            total_limit=100000,
            reserved_output_tokens=10000,
            safety_buffer_tokens=0,
            system_prompt_tokens=95000,  # Over 90000 available
        )

        assert report.is_over_budget()
        assert report.headroom_tokens < 0

    def test_format_summary(self):
        """Test human-readable summary format."""
        report = ContextAssemblyReport(
            total_limit=200000,
            reserved_output_tokens=12000,
            safety_buffer_tokens=2000,
            system_prompt_tokens=5000,
            tools_schema_tokens=3000,
            rag_tokens=1000,
            working_memory_tokens=10000,
        )

        summary = report.format_summary()

        # Check key components are present
        assert 'CTX:' in summary
        assert 'GREEN' in summary or 'YELLOW' in summary or 'ORANGE' in summary or 'RED' in summary
        assert 'sys=' in summary
        assert 'tools=' in summary
        assert 'work=' in summary
        assert 'reserve_out=' in summary
        assert 'headroom=' in summary

    def test_to_dict(self):
        """Test serialization to dictionary."""
        report = ContextAssemblyReport(
            total_limit=200000,
            reserved_output_tokens=12000,
            safety_buffer_tokens=2000,
            system_prompt_tokens=5000,
        )

        data = report.to_dict()

        assert data['total_limit'] == 200000
        assert data['reserved_output_tokens'] == 12000
        assert data['system_prompt_tokens'] == 5000
        assert 'total_input_tokens' in data
        assert 'utilization_percent' in data
        assert 'pressure_level' in data
        assert data['pressure_level'] == 'green'

    def test_zero_available_budget(self):
        """Test edge case where available budget is zero."""
        report = ContextAssemblyReport(
            total_limit=10000,
            reserved_output_tokens=10000,  # All reserved for output
            safety_buffer_tokens=0,
            system_prompt_tokens=1000,  # Still trying to use input
        )

        assert report.available_for_input == 0
        assert report.utilization_percent == 100.0  # Capped at 100
        assert report.is_over_budget()

    def test_all_buckets_populated(self):
        """Test with all token buckets populated."""
        report = ContextAssemblyReport(
            total_limit=200000,
            reserved_output_tokens=12000,
            safety_buffer_tokens=2000,
            system_prompt_tokens=5000,
            tools_schema_tokens=3000,
            file_references_tokens=2000,
            rag_tokens=8000,
            agent_state_tokens=500,
            working_memory_tokens=20000,
            episodic_memory_tokens=5000,
        )

        expected_total = 5000 + 3000 + 2000 + 8000 + 500 + 20000 + 5000
        assert report.total_input_tokens == expected_total
        assert report.total_input_tokens == 43500


class TestContextAssemblyReportThresholds:
    """Test threshold edge cases."""

    def test_exactly_60_percent(self):
        """Test exactly at 60% threshold."""
        # 60% of 100000 = 60000 -> yellow
        report = ContextAssemblyReport(
            total_limit=100000,
            reserved_output_tokens=0,
            safety_buffer_tokens=0,
            system_prompt_tokens=60000,
        )

        assert report.utilization_percent == 60.0
        assert report.get_pressure_level() == 'yellow'

    def test_exactly_80_percent(self):
        """Test exactly at 80% threshold."""
        report = ContextAssemblyReport(
            total_limit=100000,
            reserved_output_tokens=0,
            safety_buffer_tokens=0,
            system_prompt_tokens=80000,
        )

        assert report.utilization_percent == 80.0
        assert report.get_pressure_level() == 'orange'

    def test_exactly_90_percent(self):
        """Test exactly at 90% threshold."""
        report = ContextAssemblyReport(
            total_limit=100000,
            reserved_output_tokens=0,
            safety_buffer_tokens=0,
            system_prompt_tokens=90000,
        )

        assert report.utilization_percent == 90.0
        assert report.get_pressure_level() == 'red'

    def test_just_under_thresholds(self):
        """Test just under each threshold."""
        # Just under 60% -> green
        report = ContextAssemblyReport(
            total_limit=100000,
            reserved_output_tokens=0,
            safety_buffer_tokens=0,
            system_prompt_tokens=59999,
        )
        assert report.get_pressure_level() == 'green'

        # Just under 80% -> yellow
        report = ContextAssemblyReport(
            total_limit=100000,
            reserved_output_tokens=0,
            safety_buffer_tokens=0,
            system_prompt_tokens=79999,
        )
        assert report.get_pressure_level() == 'yellow'

        # Just under 90% -> orange
        report = ContextAssemblyReport(
            total_limit=100000,
            reserved_output_tokens=0,
            safety_buffer_tokens=0,
            system_prompt_tokens=89999,
        )
        assert report.get_pressure_level() == 'orange'
