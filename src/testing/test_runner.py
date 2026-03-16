"""Test runner for autonomous test execution."""

import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Optional

from .models import TestCase, TestStatus, TestSuiteResult

logger = logging.getLogger(__name__)


def _validate_file_pattern(pattern: str) -> None:
    """
    Validate file pattern to prevent command injection.

    Args:
        pattern: File pattern to validate

    Raises:
        ValueError: If pattern contains dangerous characters
    """
    if not pattern:
        return

    # Check for shell metacharacters that could enable command injection
    dangerous_chars = [";", "|", "&", "$", "`", "\n", "\r"]
    for char in dangerous_chars:
        if char in pattern:
            raise ValueError(
                f"File pattern contains dangerous character: {char!r}. "
                "Only safe path patterns are allowed."
            )

    # Additional check for command substitution patterns
    if "$(" in pattern or "${" in pattern:
        raise ValueError(
            "File pattern contains command substitution syntax. "
            "Only safe path patterns are allowed."
        )


def _validate_working_directory(directory: str) -> Path:
    """
    Validate working directory to prevent path traversal attacks.

    Args:
        directory: Directory path to validate

    Returns:
        Validated absolute Path object

    Raises:
        ValueError: If directory path is dangerous
    """
    # Convert to absolute path
    try:
        dir_path = Path(directory).resolve()
    except Exception as e:
        raise ValueError(f"Invalid directory path: {e}")

    # Check for path traversal attempts
    if ".." in Path(directory).parts:
        raise ValueError("Directory path contains '..' (path traversal). Use absolute paths only.")

    # Verify directory exists
    if not dir_path.exists():
        raise ValueError(f"Directory does not exist: {dir_path}")

    if not dir_path.is_dir():
        raise ValueError(f"Path is not a directory: {dir_path}")

    return dir_path


class TestRunner:
    """
    Autonomous test runner supporting multiple frameworks.

    Detects test framework from project files and executes tests,
    parsing results into structured TestSuiteResult objects.

    Supported frameworks:
    - pytest (Python)
    - jest (JavaScript/TypeScript)
    """

    def __init__(self, working_directory: str = "."):
        """
        Initialize test runner.

        Args:
            working_directory: Project root directory

        Raises:
            ValueError: If working_directory is invalid or dangerous
        """
        self.working_directory = _validate_working_directory(working_directory)

    def detect_test_framework(self) -> str | None:
        """
        Detect test framework from project files.

        Checks for:
        - pytest.ini, pyproject.toml, setup.cfg (pytest)
        - package.json with jest/vitest (jest/vitest)
        - Cargo.toml (cargo test)

        Returns:
            Framework name (pytest, jest, vitest, cargo) or None
        """
        # Check for Python pytest
        if (self.working_directory / "pytest.ini").exists():
            return "pytest"

        if (self.working_directory / "pyproject.toml").exists():
            # Check if pyproject.toml has pytest config
            try:
                content = (self.working_directory / "pyproject.toml").read_text()
                if "[tool.pytest" in content or "pytest" in content:
                    return "pytest"
            except Exception:
                pass

        # Check for requirements.txt with pytest
        if (self.working_directory / "requirements.txt").exists():
            try:
                content = (self.working_directory / "requirements.txt").read_text()
                if "pytest" in content:
                    return "pytest"
            except Exception:
                pass

        # Check for JavaScript/TypeScript jest/vitest
        package_json = self.working_directory / "package.json"
        if package_json.exists():
            try:
                with open(package_json) as f:
                    pkg = json.load(f)
                    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}

                    if "jest" in deps or "@jest/globals" in deps:
                        return "jest"
                    if "vitest" in deps:
                        return "vitest"
            except Exception:
                pass

        # Check for Rust cargo
        if (self.working_directory / "Cargo.toml").exists():
            return "cargo"

        return None

    def run_tests(
        self, framework: str | None = None, file_pattern: str | None = None
    ) -> TestSuiteResult:
        """
        Run tests using detected or specified framework.

        Args:
            framework: Override framework detection (pytest, jest, vitest, cargo)
            file_pattern: Optional pattern to filter tests

        Returns:
            TestSuiteResult with comprehensive test results

        Raises:
            ValueError: If framework unsupported, detection fails, or file_pattern is dangerous
        """
        # Validate file pattern for security
        if file_pattern:
            _validate_file_pattern(file_pattern)

        if framework is None:
            framework = self.detect_test_framework()

        if framework is None:
            raise ValueError("No test framework detected. Supported: pytest, jest, vitest, cargo")

        logger.info(f"Running tests with framework: {framework}")

        if framework == "pytest":
            return self._run_pytest(file_pattern)
        elif framework == "jest":
            return self._run_jest(file_pattern)
        elif framework == "vitest":
            return self._run_vitest(file_pattern)
        elif framework == "cargo":
            return self._run_cargo(file_pattern)
        else:
            raise ValueError(f"Unsupported test framework: {framework}")

    def _run_pytest(self, file_pattern: str | None = None) -> TestSuiteResult:
        """
        Run pytest tests and parse JSON report output.

        Args:
            file_pattern: Optional pattern to filter tests

        Returns:
            TestSuiteResult

        Raises:
            subprocess.TimeoutExpired: If tests timeout
        """
        # Use python -m pytest for cross-platform compatibility
        cmd = [
            "python",
            "-m",
            "pytest",
            "--json-report",
            "--json-report-file=.pytest_report.json",
            "-v",
        ]

        if file_pattern:
            cmd.append(file_pattern)

        try:
            result = subprocess.run(
                cmd,
                cwd=self.working_directory,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
            )

            # Read JSON report
            report_path = self.working_directory / ".pytest_report.json"
            if report_path.exists():
                with open(report_path) as f:
                    report = json.load(f)

                # Parse pytest report
                summary = report.get("summary", {})
                tests = report.get("tests", [])

                test_cases = []
                for test in tests:
                    status_map = {
                        "passed": TestStatus.PASSED,
                        "failed": TestStatus.FAILED,
                        "error": TestStatus.ERROR,
                        "skipped": TestStatus.SKIPPED,
                    }

                    test_cases.append(
                        TestCase(
                            name=test.get("nodeid", "unknown"),
                            status=status_map.get(test.get("outcome"), TestStatus.ERROR),
                            duration_seconds=test.get("duration", 0.0),
                            error_message=test.get("call", {}).get("longrepr")
                            if test.get("outcome") != "passed"
                            else None,
                            file_path=test.get("filename"),
                            line_number=test.get("lineno"),
                        )
                    )

                return TestSuiteResult(
                    framework="pytest",
                    total_tests=summary.get("total", 0),
                    passed=summary.get("passed", 0),
                    failed=summary.get("failed", 0),
                    errors=summary.get("error", 0),
                    skipped=summary.get("skipped", 0),
                    duration_seconds=report.get("duration", 0.0),
                    test_cases=test_cases,
                    raw_output=result.stdout,
                    exit_code=result.returncode,
                )
            else:
                # Fallback: parse stdout
                logger.warning("pytest JSON report not found, parsing stdout")
                return self._parse_pytest_stdout(result.stdout, result.returncode)

        except subprocess.TimeoutExpired:
            logger.error("pytest execution timed out")
            raise
        except Exception as e:
            logger.error(f"pytest execution failed: {e}")
            # Return error result
            return TestSuiteResult(
                framework="pytest",
                total_tests=0,
                passed=0,
                failed=0,
                errors=1,
                skipped=0,
                duration_seconds=0.0,
                raw_output=str(e),
                exit_code=1,
            )

    def _run_jest(self, file_pattern: str | None = None) -> TestSuiteResult:
        """
        Run jest tests and parse JSON output.

        Args:
            file_pattern: Optional pattern to filter tests

        Returns:
            TestSuiteResult

        Raises:
            subprocess.TimeoutExpired: If tests timeout
        """
        cmd = ["npm", "test", "--", "--json", "--verbose"]

        if file_pattern:
            cmd.append(file_pattern)

        try:
            result = subprocess.run(
                cmd,
                cwd=self.working_directory,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=300,
            )

            # Parse jest JSON output
            try:
                output = json.loads(result.stdout)

                test_cases = []
                for test_result in output.get("testResults", []):
                    for assertion in test_result.get("assertionResults", []):
                        status_map = {
                            "passed": TestStatus.PASSED,
                            "failed": TestStatus.FAILED,
                            "pending": TestStatus.SKIPPED,
                            "todo": TestStatus.SKIPPED,
                        }

                        test_cases.append(
                            TestCase(
                                name=assertion.get("fullName", "unknown"),
                                status=status_map.get(assertion.get("status"), TestStatus.ERROR),
                                duration_seconds=assertion.get("duration", 0.0)
                                / 1000.0,  # ms to seconds
                                error_message=assertion.get("failureMessages", [None])[0],
                                file_path=test_result.get("name"),
                            )
                        )

                summary = output.get("numTotalTests", 0)

                return TestSuiteResult(
                    framework="jest",
                    total_tests=output.get("numTotalTests", 0),
                    passed=output.get("numPassedTests", 0),
                    failed=output.get("numFailedTests", 0),
                    errors=0,
                    skipped=output.get("numPendingTests", 0),
                    duration_seconds=output.get("testResults", [{}])[0]
                    .get("perfStats", {})
                    .get("runtime", 0)
                    / 1000.0,
                    test_cases=test_cases,
                    raw_output=result.stdout,
                    exit_code=result.returncode,
                )

            except json.JSONDecodeError:
                logger.warning("Failed to parse jest JSON output")
                return self._parse_jest_stdout(result.stdout, result.returncode)

        except subprocess.TimeoutExpired:
            logger.error("jest execution timed out")
            raise
        except Exception as e:
            logger.error(f"jest execution failed: {e}")
            return TestSuiteResult(
                framework="jest",
                total_tests=0,
                passed=0,
                failed=0,
                errors=1,
                skipped=0,
                duration_seconds=0.0,
                raw_output=str(e),
                exit_code=1,
            )

    def _run_vitest(self, file_pattern: str | None = None) -> TestSuiteResult:
        """Run vitest tests (similar to jest)."""
        # Implementation similar to jest
        raise NotImplementedError("vitest support coming soon")

    def _run_cargo(self, file_pattern: str | None = None) -> TestSuiteResult:
        """Run cargo test for Rust projects."""
        raise NotImplementedError("cargo test support coming soon")

    def _parse_pytest_stdout(self, stdout: str, exit_code: int) -> TestSuiteResult:
        """Fallback: Parse pytest stdout when JSON report unavailable."""
        # Simple parsing of pytest summary line
        # Example: "5 passed, 2 failed in 1.23s"

        passed = failed = errors = skipped = 0
        duration = 0.0

        summary_match = re.search(r"(\d+) passed", stdout)
        if summary_match:
            passed = int(summary_match.group(1))

        failed_match = re.search(r"(\d+) failed", stdout)
        if failed_match:
            failed = int(failed_match.group(1))

        error_match = re.search(r"(\d+) error", stdout)
        if error_match:
            errors = int(error_match.group(1))

        skipped_match = re.search(r"(\d+) skipped", stdout)
        if skipped_match:
            skipped = int(skipped_match.group(1))

        duration_match = re.search(r"in ([\d.]+)s", stdout)
        if duration_match:
            duration = float(duration_match.group(1))

        total = passed + failed + errors + skipped

        return TestSuiteResult(
            framework="pytest",
            total_tests=total,
            passed=passed,
            failed=failed,
            errors=errors,
            skipped=skipped,
            duration_seconds=duration,
            raw_output=stdout,
            exit_code=exit_code,
        )

    def _parse_jest_stdout(self, stdout: str, exit_code: int) -> TestSuiteResult:
        """Fallback: Parse jest stdout when JSON parsing fails."""
        # Similar pattern matching for jest output

        passed = failed = 0

        # Jest summary: "Tests: 1 failed, 5 passed, 6 total"
        passed_match = re.search(r"(\d+) passed", stdout)
        if passed_match:
            passed = int(passed_match.group(1))

        failed_match = re.search(r"(\d+) failed", stdout)
        if failed_match:
            failed = int(failed_match.group(1))

        total_match = re.search(r"(\d+) total", stdout)
        total = int(total_match.group(1)) if total_match else passed + failed

        return TestSuiteResult(
            framework="jest",
            total_tests=total,
            passed=passed,
            failed=failed,
            errors=0,
            skipped=0,
            duration_seconds=0.0,
            raw_output=stdout,
            exit_code=exit_code,
        )
