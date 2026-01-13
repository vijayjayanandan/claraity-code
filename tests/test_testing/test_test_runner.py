"""Tests for TestRunner."""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import json
import tempfile
import os

from src.testing.test_runner import TestRunner
from src.testing.models import TestStatus


class TestFrameworkDetection:
    """Tests for test framework detection."""

    def test_detect_pytest_from_pytest_ini(self, tmp_path):
        """Test detects pytest from pytest.ini file."""
        (tmp_path / "pytest.ini").write_text("[pytest]\ntestpaths = tests")

        runner = TestRunner(str(tmp_path))
        assert runner.detect_test_framework() == "pytest"

    def test_detect_pytest_from_pyproject_toml(self, tmp_path):
        """Test detects pytest from pyproject.toml."""
        (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\ntestpaths = ['tests']")

        runner = TestRunner(str(tmp_path))
        assert runner.detect_test_framework() == "pytest"

    def test_detect_pytest_from_requirements_txt(self, tmp_path):
        """Test detects pytest from requirements.txt."""
        (tmp_path / "requirements.txt").write_text("pytest>=7.0.0\nrequests")

        runner = TestRunner(str(tmp_path))
        assert runner.detect_test_framework() == "pytest"

    def test_detect_jest_from_package_json(self, tmp_path):
        """Test detects jest from package.json."""
        package_json = {
            "name": "myapp",
            "devDependencies": {
                "jest": "^29.0.0"
            }
        }
        (tmp_path / "package.json").write_text(json.dumps(package_json))

        runner = TestRunner(str(tmp_path))
        assert runner.detect_test_framework() == "jest"

    def test_detect_vitest_from_package_json(self, tmp_path):
        """Test detects vitest from package.json."""
        package_json = {
            "name": "myapp",
            "devDependencies": {
                "vitest": "^0.34.0"
            }
        }
        (tmp_path / "package.json").write_text(json.dumps(package_json))

        runner = TestRunner(str(tmp_path))
        assert runner.detect_test_framework() == "vitest"

    def test_detect_cargo_from_cargo_toml(self, tmp_path):
        """Test detects cargo from Cargo.toml."""
        (tmp_path / "Cargo.toml").write_text("[package]\nname = 'myapp'")

        runner = TestRunner(str(tmp_path))
        assert runner.detect_test_framework() == "cargo"

    def test_detect_no_framework(self, tmp_path):
        """Test returns None when no framework detected."""
        runner = TestRunner(str(tmp_path))
        assert runner.detect_test_framework() is None


class TestRunTests:
    """Tests for run_tests method."""

    def test_run_tests_raises_if_no_framework_detected(self, tmp_path):
        """Test raises ValueError if no framework detected."""
        runner = TestRunner(str(tmp_path))

        with pytest.raises(ValueError, match="No test framework detected"):
            runner.run_tests()

    def test_run_tests_raises_for_unsupported_framework(self, tmp_path):
        """Test raises ValueError for unsupported framework."""
        runner = TestRunner(str(tmp_path))

        with pytest.raises(ValueError, match="Unsupported test framework"):
            runner.run_tests(framework="mocha")

    @patch('subprocess.run')
    def test_run_tests_calls_pytest_when_detected(self, mock_run, tmp_path):
        """Test calls _run_pytest when pytest is detected."""
        (tmp_path / "pytest.ini").write_text("[pytest]")

        # Mock pytest execution
        mock_run.return_value = Mock(
            returncode=0,
            stdout="5 passed in 1.23s",
            stderr=""
        )

        runner = TestRunner(str(tmp_path))
        result = runner.run_tests()

        assert result.framework == "pytest"
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "pytest" in args

    @patch('subprocess.run')
    def test_run_tests_with_file_pattern(self, mock_run, tmp_path):
        """Test passes file pattern to test framework."""
        (tmp_path / "pytest.ini").write_text("[pytest]")

        mock_run.return_value = Mock(
            returncode=0,
            stdout="3 passed in 0.5s",
            stderr=""
        )

        runner = TestRunner(str(tmp_path))
        result = runner.run_tests(file_pattern="tests/test_auth.py")

        args = mock_run.call_args[0][0]
        assert "tests/test_auth.py" in args


class TestPytestExecution:
    """Tests for _run_pytest method."""

    @patch('subprocess.run')
    def test_run_pytest_parses_json_report(self, mock_run, tmp_path):
        """Test parses pytest JSON report correctly."""
        # Create mock JSON report
        report_data = {
            "summary": {
                "total": 5,
                "passed": 4,
                "failed": 1,
                "error": 0,
                "skipped": 0
            },
            "duration": 2.5,
            "tests": [
                {
                    "nodeid": "tests/test_example.py::test_success",
                    "outcome": "passed",
                    "duration": 0.5
                },
                {
                    "nodeid": "tests/test_example.py::test_failure",
                    "outcome": "failed",
                    "duration": 0.3,
                    "call": {
                        "longrepr": "AssertionError: Expected True, got False"
                    },
                    "filename": "tests/test_example.py",
                    "lineno": 42
                }
            ]
        }

        report_path = tmp_path / ".pytest_report.json"
        report_path.write_text(json.dumps(report_data))

        mock_run.return_value = Mock(
            returncode=1,
            stdout="1 failed, 4 passed in 2.50s",
            stderr=""
        )

        runner = TestRunner(str(tmp_path))
        result = runner._run_pytest()

        assert result.framework == "pytest"
        assert result.total_tests == 5
        assert result.passed == 4
        assert result.failed == 1
        assert result.errors == 0
        assert result.duration_seconds == 2.5
        assert len(result.test_cases) == 2

        # Check failed test details
        failed_test = next(tc for tc in result.test_cases if tc.status == TestStatus.FAILED)
        assert failed_test.name == "tests/test_example.py::test_failure"
        assert "AssertionError" in failed_test.error_message
        assert failed_test.file_path == "tests/test_example.py"
        assert failed_test.line_number == 42

    @patch('subprocess.run')
    def test_run_pytest_fallback_to_stdout_parsing(self, mock_run, tmp_path):
        """Test falls back to stdout parsing if JSON report missing."""
        mock_run.return_value = Mock(
            returncode=0,
            stdout="5 passed, 1 skipped in 1.23s",
            stderr=""
        )

        runner = TestRunner(str(tmp_path))
        result = runner._run_pytest()

        assert result.framework == "pytest"
        assert result.passed == 5
        assert result.skipped == 1
        assert result.total_tests == 6

    @patch('subprocess.run')
    def test_run_pytest_handles_timeout(self, mock_run, tmp_path):
        """Test handles subprocess timeout."""
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired("pytest", 300)

        runner = TestRunner(str(tmp_path))

        with pytest.raises(subprocess.TimeoutExpired):
            runner._run_pytest()

    @patch('subprocess.run')
    def test_run_pytest_handles_execution_error(self, mock_run, tmp_path):
        """Test handles pytest execution errors gracefully."""
        mock_run.side_effect = Exception("pytest not found")

        runner = TestRunner(str(tmp_path))
        result = runner._run_pytest()

        assert result.framework == "pytest"
        assert result.errors == 1
        assert result.total_tests == 0
        assert "pytest not found" in result.raw_output


class TestJestExecution:
    """Tests for _run_jest method."""

    @patch('subprocess.run')
    def test_run_jest_parses_json_output(self, mock_run, tmp_path):
        """Test parses jest JSON output correctly."""
        jest_output = {
            "numTotalTests": 10,
            "numPassedTests": 8,
            "numFailedTests": 2,
            "numPendingTests": 0,
            "testResults": [
                {
                    "name": "src/auth.test.js",
                    "assertionResults": [
                        {
                            "fullName": "Auth should validate token",
                            "status": "passed",
                            "duration": 150
                        },
                        {
                            "fullName": "Auth should reject invalid token",
                            "status": "failed",
                            "duration": 200,
                            "failureMessages": ["Expected 401, got 200"]
                        }
                    ],
                    "perfStats": {
                        "runtime": 2500
                    }
                }
            ]
        }

        mock_run.return_value = Mock(
            returncode=1,
            stdout=json.dumps(jest_output),
            stderr=""
        )

        runner = TestRunner(str(tmp_path))
        result = runner._run_jest()

        assert result.framework == "jest"
        assert result.total_tests == 10
        assert result.passed == 8
        assert result.failed == 2
        assert len(result.test_cases) == 2

        # Check failed test
        failed_test = next(tc for tc in result.test_cases if tc.status == TestStatus.FAILED)
        assert failed_test.name == "Auth should reject invalid token"
        assert "Expected 401, got 200" in failed_test.error_message

    @patch('subprocess.run')
    def test_run_jest_fallback_to_stdout_parsing(self, mock_run, tmp_path):
        """Test falls back to stdout parsing if JSON parse fails."""
        mock_run.return_value = Mock(
            returncode=0,
            stdout="Tests: 8 passed, 2 failed, 10 total",
            stderr=""
        )

        runner = TestRunner(str(tmp_path))
        result = runner._run_jest()

        assert result.framework == "jest"
        assert result.passed == 8
        assert result.failed == 2
        assert result.total_tests == 10


class TestStdoutParsing:
    """Tests for fallback stdout parsing."""

    def test_parse_pytest_stdout_with_all_statuses(self):
        """Test parses pytest stdout with various test statuses."""
        stdout = "3 passed, 2 failed, 1 error, 1 skipped in 5.43s"

        runner = TestRunner()
        result = runner._parse_pytest_stdout(stdout, exit_code=1)

        assert result.passed == 3
        assert result.failed == 2
        assert result.errors == 1
        assert result.skipped == 1
        assert result.total_tests == 7
        assert result.duration_seconds == 5.43

    def test_parse_jest_stdout(self):
        """Test parses jest stdout summary."""
        stdout = "Tests: 2 failed, 8 passed, 10 total\nSnapshots: 0 total"

        runner = TestRunner()
        result = runner._parse_jest_stdout(stdout, exit_code=1)

        assert result.passed == 8
        assert result.failed == 2
        assert result.total_tests == 10
