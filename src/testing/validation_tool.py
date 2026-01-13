"""LLM tool for autonomous test execution."""

from typing import Optional, List, Dict, Any
import logging

from src.tools.base import Tool, ToolResult, ToolStatus
from .validation_engine import ValidationEngine
from .test_runner import TestRunner

logger = logging.getLogger(__name__)


class RunTestsTool(Tool):
    """
    Run tests autonomously and get feedback on failures.

    This tool enables the agent to validate its own code by:
    1. Auto-detecting test framework (pytest, jest, etc.)
    2. Running tests
    3. Parsing results
    4. Generating fix suggestions for failures (LLM-powered)

    Examples:
        # Run all tests
        run_tests()

        # Run specific test file
        run_tests(file_pattern="tests/test_auth.py")

        # Use specific framework
        run_tests(framework="pytest")
    """

    def __init__(self, working_directory: str = "."):
        """Initialize run tests tool."""
        super().__init__(
            name="run_tests",
            description="Run tests autonomously and get feedback on failures"
        )
        self.validation_engine = ValidationEngine(working_directory)
        self.test_runner = TestRunner(working_directory)

    def _get_parameters(self) -> Dict[str, Any]:
        """Return parameter schema for this tool."""
        return {
            "type": "object",
            "properties": {
                "framework": {
                    "type": "string",
                    "description": "Optional: Override framework detection (pytest, jest, vitest, cargo)",
                    "enum": ["pytest", "jest", "vitest", "cargo"]
                },
                "file_pattern": {
                    "type": "string",
                    "description": "Optional: Test file pattern to filter tests (e.g., 'tests/test_auth.py')"
                },
                "files_changed": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional: List of changed files for validation context"
                }
            },
            "required": []
        }

    def execute(
        self,
        framework: Optional[str] = None,
        file_pattern: Optional[str] = None,
        files_changed: Optional[List[str]] = None
    ) -> ToolResult:
        """
        Execute tests and return results with feedback.

        Args:
            framework: Optional framework override (pytest, jest, vitest, cargo)
            file_pattern: Optional test file pattern to filter tests
            files_changed: Optional list of changed files (for validation context)

        Returns:
            ToolResult with test results and feedback
        """
        try:
            logger.info(f"Running tests (framework={framework}, pattern={file_pattern})")

            # If files_changed provided, use full validation pipeline
            if files_changed:
                result = self.validation_engine.validate_code(files_changed)

                output = result['feedback']

                status = ToolStatus.SUCCESS if result['all_passed'] else ToolStatus.ERROR

                return ToolResult(
                    tool_name=self.name,
                    status=status,
                    output=output,
                    metadata={
                        'test_result': result['test_result'].to_dict(),
                        'success_rate': result['success_rate']
                    }
                )

            # Otherwise, just run tests
            test_result = self.test_runner.run_tests(
                framework=framework,
                file_pattern=file_pattern
            )

            # Generate feedback if failures
            if not test_result.all_passed:
                feedback = self.validation_engine._generate_failure_feedback(test_result)
                status = ToolStatus.ERROR
            else:
                feedback = f"[OK] All {test_result.total_tests} tests passed ({test_result.duration_seconds:.2f}s)"
                status = ToolStatus.SUCCESS

            return ToolResult(
                tool_name=self.name,
                status=status,
                output=feedback,
                metadata={
                    'test_result': test_result.to_dict()
                }
            )

        except ValueError as e:
            logger.error(f"Test execution failed: {e}")
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                error=str(e),
                output=f"[ERROR] {str(e)}"
            )
        except Exception as e:
            logger.error(f"Unexpected error running tests: {e}", exc_info=True)
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                error=str(e),
                output=f"[ERROR] Unexpected error: {str(e)}"
            )


class DetectTestFrameworkTool(Tool):
    """
    Detect test framework from project files.

    Returns the detected framework name (pytest, jest, vitest, cargo)
    or None if no framework detected.
    """

    def __init__(self, working_directory: str = "."):
        """Initialize detect framework tool."""
        super().__init__(
            name="detect_test_framework",
            description="Detect test framework from project files"
        )
        self.test_runner = TestRunner(working_directory)

    def _get_parameters(self) -> Dict[str, Any]:
        """Return parameter schema for this tool."""
        return {
            "type": "object",
            "properties": {},
            "required": []
        }

    def execute(self) -> ToolResult:
        """
        Detect test framework.

        Returns:
            ToolResult with detected framework name
        """
        try:
            framework = self.test_runner.detect_test_framework()

            if framework:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.SUCCESS,
                    output=f"[OK] Detected test framework: {framework}",
                    metadata={'framework': framework}
                )
            else:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output="[WARN] No test framework detected. Supported: pytest, jest, vitest, cargo"
                )

        except Exception as e:
            logger.error(f"Framework detection failed: {e}")
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                error=str(e),
                output=f"[ERROR] {str(e)}"
            )
