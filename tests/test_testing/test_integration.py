"""Integration tests for testing layer with real test execution."""

import pytest
from pathlib import Path
from src.testing import TestRunner, ValidationEngine
from src.testing.models import TestStatus


class TestRealPytestExecution:
    """Integration tests using real pytest execution on this project."""

    def test_run_tests_on_own_test_suite(self):
        """Test that TestRunner can run pytest on our own test suite."""
        runner = TestRunner(working_directory=".")

        # Detect framework
        framework = runner.detect_test_framework()
        assert framework == "pytest", "Should detect pytest from this project"

        # Run tests on a specific test file
        result = runner.run_tests(file_pattern="tests/test_testing/test_models.py")

        # Verify result structure
        assert result.framework == "pytest"
        assert result.total_tests > 0, "Should find tests in test_models.py"
        assert result.passed >= 0
        assert result.duration_seconds > 0

        # Should have test cases
        assert len(result.test_cases) > 0, "Should have parsed test cases"

        # Verify test case structure
        for test_case in result.test_cases:
            assert test_case.name is not None
            assert test_case.status in [TestStatus.PASSED, TestStatus.FAILED, TestStatus.SKIPPED, TestStatus.ERROR]
            assert test_case.duration_seconds >= 0

    def test_validation_engine_with_real_tests(self):
        """Test ValidationEngine validates code using real tests."""
        from unittest.mock import patch

        engine = ValidationEngine(working_directory=".")

        # First, run tests with a specific file pattern to get a real result
        actual_result = engine.test_runner.run_tests(file_pattern="tests/test_testing/test_models.py")

        # Now patch run_tests to return this result (avoid running all tests)
        with patch.object(engine.test_runner, 'run_tests', return_value=actual_result):
            result = engine.validate_code(files_changed=["src/testing/models.py"])

        # Verify validation result structure
        assert 'test_result' in result
        assert 'all_passed' in result
        assert 'feedback' in result
        assert 'success_rate' in result

        test_result = result['test_result']
        assert test_result.framework == "pytest"
        assert test_result.total_tests > 0

        # Feedback should be provided
        assert len(result['feedback']) > 0

    def test_full_workflow_detect_run_validate(self):
        """Test complete workflow: detect -> run -> validate."""
        from unittest.mock import patch

        # Step 1: Detect framework
        runner = TestRunner(working_directory=".")
        framework = runner.detect_test_framework()
        assert framework == "pytest"

        # Step 2: Run tests on a specific file
        test_result = runner.run_tests(file_pattern="tests/test_testing/test_models.py")
        assert test_result.total_tests > 0

        # Step 3: Validate (using the same targeted test result to avoid collection errors)
        engine = ValidationEngine(working_directory=".")
        with patch.object(engine.test_runner, 'run_tests', return_value=test_result):
            validation_result = engine.validate_code(files_changed=["src/testing/models.py"])

        # Verify full pipeline executed
        assert validation_result['test_result'].total_tests > 0
        assert validation_result['feedback'] is not None


class TestLLMIntegration:
    """Tests for LLM integration aspects."""

    def test_feedback_generation_format(self):
        """Test that feedback is in LLM-friendly format."""
        from src.testing.models import TestCase, TestStatus, TestSuiteResult

        # Create a failed test scenario
        failed_test = TestCase(
            name="test_authentication",
            status=TestStatus.FAILED,
            error_message="AssertionError: Expected 200, got 401",
            file_path="tests/test_auth.py",
            line_number=42
        )

        test_result = TestSuiteResult(
            framework="pytest",
            total_tests=5,
            passed=4,
            failed=1,
            errors=0,
            skipped=0,
            duration_seconds=2.5,
            test_cases=[failed_test]
        )

        engine = ValidationEngine(working_directory=".")
        feedback = engine._generate_failure_feedback(test_result)

        # Verify feedback contains essential information
        assert "[TEST RESULTS]" in feedback
        assert "Framework: pytest" in feedback
        assert "test_authentication" in feedback
        assert "Expected 200, got 401" in feedback
        assert "[FIX SUGGESTIONS]" in feedback or "[ERROR]" in feedback
