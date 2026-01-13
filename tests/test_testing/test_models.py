"""Tests for testing data models."""

import pytest
from src.testing.models import TestCase, TestStatus, TestSuiteResult


class TestTestCase:
    """Tests for TestCase dataclass."""

    def test_passed_property(self):
        """Test passed property returns True for passed status."""
        test = TestCase(
            name="test_example",
            status=TestStatus.PASSED,
            duration_seconds=0.5
        )
        assert test.passed is True
        assert test.failed is False

    def test_failed_property_for_failed_status(self):
        """Test failed property returns True for failed status."""
        test = TestCase(
            name="test_example",
            status=TestStatus.FAILED,
            duration_seconds=0.5,
            error_message="AssertionError: 1 != 2"
        )
        assert test.passed is False
        assert test.failed is True

    def test_failed_property_for_error_status(self):
        """Test failed property returns True for error status."""
        test = TestCase(
            name="test_example",
            status=TestStatus.ERROR,
            error_message="NameError: undefined"
        )
        assert test.failed is True

    def test_test_case_with_file_location(self):
        """Test TestCase with file path and line number."""
        test = TestCase(
            name="test_auth",
            status=TestStatus.PASSED,
            duration_seconds=1.2,
            file_path="tests/test_auth.py",
            line_number=42
        )
        assert test.file_path == "tests/test_auth.py"
        assert test.line_number == 42


class TestTestSuiteResult:
    """Tests for TestSuiteResult dataclass."""

    def test_all_passed_with_all_tests_passing(self):
        """Test all_passed returns True when all tests pass."""
        result = TestSuiteResult(
            framework="pytest",
            total_tests=5,
            passed=5,
            failed=0,
            errors=0,
            skipped=0,
            duration_seconds=2.5
        )
        assert result.all_passed is True

    def test_all_passed_with_failures(self):
        """Test all_passed returns False when tests fail."""
        result = TestSuiteResult(
            framework="pytest",
            total_tests=5,
            passed=3,
            failed=2,
            errors=0,
            skipped=0,
            duration_seconds=2.5
        )
        assert result.all_passed is False

    def test_all_passed_with_errors(self):
        """Test all_passed returns False when tests error."""
        result = TestSuiteResult(
            framework="pytest",
            total_tests=5,
            passed=4,
            failed=0,
            errors=1,
            skipped=0,
            duration_seconds=2.5
        )
        assert result.all_passed is False

    def test_all_passed_with_zero_tests(self):
        """Test all_passed returns False when no tests run."""
        result = TestSuiteResult(
            framework="pytest",
            total_tests=0,
            passed=0,
            failed=0,
            errors=0,
            skipped=0,
            duration_seconds=0.0
        )
        assert result.all_passed is False

    def test_success_rate_calculation(self):
        """Test success rate percentage calculation."""
        result = TestSuiteResult(
            framework="pytest",
            total_tests=10,
            passed=8,
            failed=2,
            errors=0,
            skipped=0,
            duration_seconds=5.0
        )
        assert result.success_rate == 80.0

    def test_success_rate_with_zero_tests(self):
        """Test success rate returns 0 when no tests."""
        result = TestSuiteResult(
            framework="pytest",
            total_tests=0,
            passed=0,
            failed=0,
            errors=0,
            skipped=0,
            duration_seconds=0.0
        )
        assert result.success_rate == 0.0

    def test_failure_summary_all_passed(self):
        """Test failure summary when all tests pass."""
        result = TestSuiteResult(
            framework="pytest",
            total_tests=5,
            passed=5,
            failed=0,
            errors=0,
            skipped=0,
            duration_seconds=2.5
        )
        assert "All tests passed" in result.failure_summary

    def test_failure_summary_with_failures(self):
        """Test failure summary includes test names and errors."""
        failed_test = TestCase(
            name="test_authentication",
            status=TestStatus.FAILED,
            error_message="AssertionError: Expected 200, got 401"
        )

        result = TestSuiteResult(
            framework="pytest",
            total_tests=5,
            passed=4,
            failed=1,
            errors=0,
            skipped=0,
            duration_seconds=2.5,
            test_cases=[failed_test]
        )

        summary = result.failure_summary
        assert "1 test(s) failed" in summary
        assert "test_authentication" in summary
        assert "Expected 200, got 401" in summary

    def test_failure_summary_truncates_long_errors(self):
        """Test failure summary truncates very long error messages."""
        long_error = "A" * 200  # 200 character error

        failed_test = TestCase(
            name="test_long_error",
            status=TestStatus.FAILED,
            error_message=long_error
        )

        result = TestSuiteResult(
            framework="pytest",
            total_tests=1,
            passed=0,
            failed=1,
            errors=0,
            skipped=0,
            duration_seconds=1.0,
            test_cases=[failed_test]
        )

        summary = result.failure_summary
        assert "..." in summary  # Truncation indicator
        assert len(summary) < 500  # Summary should be reasonable length

    def test_failure_summary_limits_to_5_failures(self):
        """Test failure summary shows max 5 failures."""
        failed_tests = [
            TestCase(name=f"test_{i}", status=TestStatus.FAILED, error_message=f"Error {i}")
            for i in range(10)
        ]

        result = TestSuiteResult(
            framework="pytest",
            total_tests=10,
            passed=0,
            failed=10,
            errors=0,
            skipped=0,
            duration_seconds=5.0,
            test_cases=failed_tests
        )

        summary = result.failure_summary
        assert "test_0" in summary
        assert "test_4" in summary
        assert "... and 5 more" in summary

    def test_to_dict_serialization(self):
        """Test to_dict converts to serializable dictionary."""
        test = TestCase(
            name="test_example",
            status=TestStatus.PASSED,
            duration_seconds=1.5
        )

        result = TestSuiteResult(
            framework="pytest",
            total_tests=1,
            passed=1,
            failed=0,
            errors=0,
            skipped=0,
            duration_seconds=1.5,
            test_cases=[test]
        )

        data = result.to_dict()

        assert data['framework'] == "pytest"
        assert data['total_tests'] == 1
        assert data['passed'] == 1
        assert data['all_passed'] is True
        assert data['success_rate'] == 100.0
        assert len(data['test_cases']) == 1
        assert data['test_cases'][0]['name'] == "test_example"
        assert data['test_cases'][0]['status'] == "passed"
