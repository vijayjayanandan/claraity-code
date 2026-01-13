"""Data models for test execution results."""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum


class TestStatus(Enum):
    """Test execution status."""
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"


@dataclass
class TestCase:
    """Individual test case result."""

    name: str
    status: TestStatus
    duration_seconds: float = 0.0
    error_message: Optional[str] = None
    stack_trace: Optional[str] = None
    file_path: Optional[str] = None
    line_number: Optional[int] = None

    @property
    def passed(self) -> bool:
        """Whether test passed."""
        return self.status == TestStatus.PASSED

    @property
    def failed(self) -> bool:
        """Whether test failed or errored."""
        return self.status in (TestStatus.FAILED, TestStatus.ERROR)


@dataclass
class TestSuiteResult:
    """Complete test suite execution result."""

    framework: str  # pytest, jest, cargo, etc.
    total_tests: int
    passed: int
    failed: int
    errors: int
    skipped: int
    duration_seconds: float
    test_cases: List[TestCase] = field(default_factory=list)
    raw_output: str = ""
    exit_code: int = 0

    @property
    def all_passed(self) -> bool:
        """Whether all tests passed."""
        return self.failed == 0 and self.errors == 0 and self.total_tests > 0

    @property
    def success_rate(self) -> float:
        """Percentage of tests that passed."""
        if self.total_tests == 0:
            return 0.0
        return (self.passed / self.total_tests) * 100.0

    @property
    def failure_summary(self) -> str:
        """Human-readable summary of failures."""
        if self.all_passed:
            return "All tests passed"

        failed_tests = [tc for tc in self.test_cases if tc.failed]
        if not failed_tests:
            return f"{self.failed + self.errors} tests failed"

        summary_lines = [f"{len(failed_tests)} test(s) failed:\n"]
        for test in failed_tests[:5]:  # Show first 5 failures
            summary_lines.append(f"  - {test.name}")
            if test.error_message:
                # Truncate long error messages
                error_preview = test.error_message[:100]
                if len(test.error_message) > 100:
                    error_preview += "..."
                summary_lines.append(f"    Error: {error_preview}")

        if len(failed_tests) > 5:
            summary_lines.append(f"  ... and {len(failed_tests) - 5} more")

        return "\n".join(summary_lines)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "framework": self.framework,
            "total_tests": self.total_tests,
            "passed": self.passed,
            "failed": self.failed,
            "errors": self.errors,
            "skipped": self.skipped,
            "duration_seconds": self.duration_seconds,
            "success_rate": self.success_rate,
            "all_passed": self.all_passed,
            "exit_code": self.exit_code,
            "test_cases": [
                {
                    "name": tc.name,
                    "status": tc.status.value,
                    "duration": tc.duration_seconds,
                    "error_message": tc.error_message,
                    "file_path": tc.file_path,
                    "line_number": tc.line_number,
                }
                for tc in self.test_cases
            ]
        }
