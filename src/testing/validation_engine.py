"""Validation engine with LLM-powered feedback generation."""

import logging
from pathlib import Path
from typing import Any, Optional

from src.llm.base import LLMBackend
from src.llm.openai_backend import OpenAIBackend

from .models import TestSuiteResult
from .test_runner import TestRunner

logger = logging.getLogger(__name__)


class ValidationEngine:
    """
    High-level validation orchestrator.

    Runs tests, linters, and generates LLM-powered fix suggestions.
    """

    def __init__(self, working_directory: str = ".", llm_backend: LLMBackend | None = None):
        """
        Initialize validation engine.

        Args:
            working_directory: Project root directory
            llm_backend: LLM for generating feedback (optional, will try to create if not provided)
        """
        self.working_directory = Path(working_directory)
        self.test_runner = TestRunner(str(working_directory))

        # Try to initialize LLM backend if not provided
        if llm_backend is None:
            try:
                from src.llm.model_config import ModelConfig

                config = ModelConfig.from_env()
                self.llm_backend = OpenAIBackend(config)
            except Exception as e:
                logger.warning(
                    f"Failed to initialize LLM backend: {e}. Feedback generation will be basic."
                )
                self.llm_backend = None
        else:
            self.llm_backend = llm_backend

    def validate_code(self, files_changed: list[str]) -> dict[str, Any]:
        """
        Run full validation pipeline: tests + linters + feedback generation.

        Args:
            files_changed: list of modified files to validate

        Returns:
            dict with validation results:
            {
                'test_result': TestSuiteResult,
                'all_passed': bool,
                'feedback': str,
                'files_validated': list[str]
            }
        """
        logger.info(f"Validating {len(files_changed)} changed files")

        # Step 1: Run tests
        test_result = self.test_runner.run_tests()

        # Step 2: Generate feedback if tests failed
        feedback = ""
        if not test_result.all_passed:
            logger.info("Tests failed, generating fix suggestions")
            feedback = self._generate_failure_feedback(test_result)
        else:
            logger.info("All tests passed")
            feedback = f"[OK] All {test_result.total_tests} tests passed"

        return {
            "test_result": test_result,
            "all_passed": test_result.all_passed,
            "feedback": feedback,
            "files_validated": files_changed,
            "success_rate": test_result.success_rate,
        }

    def _generate_failure_feedback(self, test_result: TestSuiteResult) -> str:
        """
        Generate actionable feedback from test failures with fix suggestions.

        Uses LLM to analyze failures and suggest fixes.

        Args:
            test_result: Test results to analyze

        Returns:
            Actionable feedback string with fix suggestions
        """
        if test_result.all_passed:
            return "[OK] All tests passed, no fixes needed"

        # Build prompt for LLM
        prompt = self._build_feedback_prompt(test_result)

        try:
            # Generate feedback using LLM (if available)
            if self.llm_backend is None:
                feedback_text = "LLM backend not available. Review test failures manually."
            else:
                response = self.llm_backend.generate(
                    prompt=prompt,
                    max_tokens=1000,
                    temperature=0.3,  # Lower temperature for more focused suggestions
                )
                feedback_text = response.get("content", "No feedback generated")

            # Prepend summary
            summary = f"""
[TEST RESULTS]
Framework: {test_result.framework}
Total: {test_result.total_tests} | Passed: {test_result.passed} | Failed: {test_result.failed} | Errors: {test_result.errors}
Success Rate: {test_result.success_rate:.1f}%

{test_result.failure_summary}

[FIX SUGGESTIONS]
{feedback_text}
"""
            return summary.strip()

        except Exception as e:
            logger.error(f"Failed to generate LLM feedback: {e}")
            # Fallback to basic feedback
            return f"""
[TEST RESULTS]
Framework: {test_result.framework}
Total: {test_result.total_tests} | Passed: {test_result.passed} | Failed: {test_result.failed}

{test_result.failure_summary}

[ERROR] Failed to generate AI-powered fix suggestions: {e}

Next steps:
1. Review the test failures above
2. Check the error messages
3. Fix the failing tests
4. Re-run tests
"""

    def _build_feedback_prompt(self, test_result: TestSuiteResult) -> str:
        """Build LLM prompt for generating fix suggestions."""
        failed_tests = [tc for tc in test_result.test_cases if tc.failed]

        if not failed_tests:
            return "All tests passed."

        # Limit to first 3 failures to avoid context overflow
        failures_to_analyze = failed_tests[:3]

        prompt_parts = [
            "You are a code quality assistant analyzing test failures.",
            "",
            f"Test framework: {test_result.framework}",
            f"Failed {len(failed_tests)} out of {test_result.total_tests} tests.",
            "",
            "Failed tests:",
        ]

        for i, test in enumerate(failures_to_analyze, 1):
            prompt_parts.append(f"\n{i}. Test: {test.name}")
            if test.file_path:
                prompt_parts.append(f"   File: {test.file_path}:{test.line_number or '?'}")
            if test.error_message:
                # Truncate very long error messages
                error_msg = test.error_message[:500]
                if len(test.error_message) > 500:
                    error_msg += "\n   [...truncated...]"
                prompt_parts.append(f"   Error: {error_msg}")

        if len(failed_tests) > 3:
            prompt_parts.append(f"\n... and {len(failed_tests) - 3} more failures")

        prompt_parts.extend(
            [
                "",
                "Provide:",
                "1. Root cause analysis (1-2 sentences per failure)",
                "2. Specific fix suggestions (code changes, imports, logic fixes)",
                "3. Priority order (fix most critical issues first)",
                "",
                "Keep your response concise and actionable.",
            ]
        )

        return "\n".join(prompt_parts)
