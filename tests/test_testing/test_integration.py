"""Integration tests for SELF_TESTING_LAYER with real test execution."""

import pytest
from pathlib import Path
from src.testing import TestRunner, ValidationEngine, RunTestsTool
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

    def test_run_tests_tool_integration(self):
        """Test RunTestsTool can be called and returns proper ToolResult."""
        tool = RunTestsTool(working_directory=".")

        # Execute tool on specific test file
        result = tool.execute(file_pattern="tests/test_testing/test_models.py")

        # Verify ToolResult structure
        assert result.status is not None
        assert result.output is not None
        assert 'test_result' in result.metadata

        # Verify test result in metadata
        test_result_dict = result.metadata['test_result']
        assert test_result_dict['framework'] == "pytest"
        assert test_result_dict['total_tests'] > 0
        assert 'success_rate' in test_result_dict

    def test_full_workflow_detect_run_validate(self):
        """Test complete workflow: detect → run → validate."""
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

        # Print results for visibility
        print(f"\n[INTEGRATION TEST RESULTS]")
        print(f"Framework: {framework}")
        print(f"Tests run: {test_result.total_tests}")
        print(f"Passed: {test_result.passed}")
        print(f"Failed: {test_result.failed}")
        print(f"Success rate: {test_result.success_rate:.1f}%")
        print(f"Duration: {test_result.duration_seconds:.2f}s")

    def test_tool_handles_missing_framework_gracefully(self, tmp_path):
        """Test tool returns proper error when no framework detected."""
        tool = RunTestsTool(working_directory=str(tmp_path))

        result = tool.execute()

        # Should return error status
        from src.tools.base import ToolStatus
        assert result.status == ToolStatus.ERROR
        assert "No test framework detected" in result.output


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

    def test_tool_result_metadata_for_llm(self):
        """Test that tool returns structured metadata for LLM to parse."""
        tool = RunTestsTool(working_directory=".")

        result = tool.execute(file_pattern="tests/test_testing/test_models.py")

        # Metadata should have structured test results
        assert 'test_result' in result.metadata
        test_data = result.metadata['test_result']

        # Verify all fields an LLM would need
        required_fields = ['framework', 'total_tests', 'passed', 'failed',
                          'success_rate', 'all_passed', 'test_cases']
        for field in required_fields:
            assert field in test_data, f"Missing field: {field}"

        # Test cases should have structured info
        if test_data['test_cases']:
            test_case = test_data['test_cases'][0]
            assert 'name' in test_case
            assert 'status' in test_case
