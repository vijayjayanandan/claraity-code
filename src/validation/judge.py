"""
Validation Judge

Uses LLM API to evaluate generated code quality, providing
detailed scores and feedback.

Supports the same backends as the main agent (OpenAI-compatible APIs).
"""

import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

from src.llm import LLMBackend, LLMBackendType, LLMConfig, OpenAIBackend

from .scenario import ValidationResult, ValidationScenario


class ValidationJudge:
    """
    LLM-based code quality evaluator.

    Uses the same LLM backend as the agent to analyze generated code and provide:
    - Detailed scores (completeness, correctness, quality, best practices)
    - Strengths and weaknesses
    - Actionable feedback
    """

    def __init__(
        self,
        llm_backend: LLMBackend | None = None,
        model_name: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None
    ):
        """
        Initialize judge.

        Args:
            llm_backend: Pre-configured LLM backend (recommended)
            model_name: Model name (if creating new backend)
            api_key: API key (if creating new backend)
            base_url: Base URL (if creating new backend)
        """
        if llm_backend:
            # Use provided backend
            self.llm = llm_backend
        else:
            # Create new backend using config from .env
            api_key = api_key or os.getenv("OPENAI_API_KEY")
            base_url = base_url or os.getenv("LLM_HOST")
            model_name = model_name or os.getenv("LLM_MODEL")

            if not api_key:
                raise ValueError(
                    "API key required. Either:\n"
                    "1. Pass llm_backend parameter (recommended)\n"
                    "2. Set OPENAI_API_KEY in .env\n"
                    "3. Pass api_key parameter"
                )

            if not base_url:
                raise ValueError("Base URL required. Set LLM_HOST in .env or pass base_url parameter.")
            if not model_name:
                raise ValueError("Model name required. Set LLM_MODEL in .env or pass model_name parameter.")

            config = LLMConfig(
                backend_type=LLMBackendType.OPENAI,
                model_name=model_name,
                base_url=base_url,
                temperature=0.0,  # Deterministic for evaluation
                max_tokens=int(os.getenv("LLM_MAX_TOKENS", "4000")),
                top_p=float(os.getenv("LLM_TOP_P", "0.95"))
            )

            self.llm = OpenAIBackend(config, api_key=api_key)

    async def evaluate(
        self,
        scenario: ValidationScenario,
        result: ValidationResult,
        workspace: Path,
        verbose: bool = True
    ) -> dict[str, Any]:
        """
        Evaluate generated code using Claude.

        Args:
            scenario: The validation scenario
            result: Current validation result (with check results)
            workspace: Path to workspace with generated code
            verbose: Print progress

        Returns:
            Dictionary with scores, strengths, weaknesses, feedback
        """

        if verbose:
            print("\n[TARGET] Running Claude judge evaluation...")

        # Collect code files
        code_dir = workspace / "code"
        code_files = self._collect_code_files(code_dir)

        if not code_files:
            return {
                "completeness": 0.0,
                "correctness": 0.0,
                "quality": 0.0,
                "best_practices": 0.0,
                "strengths": [],
                "weaknesses": ["No code files generated"],
                "overall_assessment": "Agent did not generate any code files."
            }

        # Build evaluation prompt
        eval_prompt = self._build_evaluation_prompt(
            scenario, result, code_files
        )

        # Call LLM API (same backend as agent)
        try:
            # Use the LLM backend (works with OpenAI-compatible APIs)
            # Wrap prompt in message format expected by generate()
            messages = [{"role": "user", "content": eval_prompt}]
            response = self.llm.generate(messages)
            response_text = response.content

            # Extract JSON from response (handle markdown code blocks)
            judge_result = self._parse_judge_response(response_text)

            # Save judge report
            judge_report_path = workspace / "judge_report.json"
            with open(judge_report_path, "w") as f:
                json.dump(judge_result, f, indent=2)

            result.judge_report_path = str(judge_report_path)

            if verbose:
                print("   [OK] Judge evaluation complete")
                print(f"      Completeness: {judge_result['completeness']:.1%}")
                print(f"      Correctness: {judge_result['correctness']:.1%}")
                print(f"      Quality: {judge_result['quality']:.1%}")

            return judge_result

        except Exception as e:
            if verbose:
                print(f"   [WARN]  Judge evaluation failed: {e}")

            return {
                "completeness": 0.0,
                "correctness": 0.0,
                "quality": 0.0,
                "best_practices": 0.0,
                "strengths": [],
                "weaknesses": [f"Judge evaluation failed: {str(e)}"],
                "overall_assessment": "Could not evaluate code due to error."
            }

    def _collect_code_files(self, code_dir: Path) -> dict[str, str]:
        """Collect all code files from workspace"""

        code_files = {}

        if not code_dir.exists():
            return code_files

        # Collect Python files
        for py_file in code_dir.rglob("*.py"):
            try:
                rel_path = py_file.relative_to(code_dir)
                content = py_file.read_text()
                code_files[str(rel_path)] = content
            except Exception:
                pass

        # Also collect README
        readme_path = code_dir / "README.md"
        if readme_path.exists():
            try:
                code_files["README.md"] = readme_path.read_text()
            except Exception:
                pass

        # Collect requirements.txt
        req_path = code_dir / "requirements.txt"
        if req_path.exists():
            try:
                code_files["requirements.txt"] = req_path.read_text()
            except Exception:
                pass

        return code_files

    def _build_evaluation_prompt(
        self,
        scenario: ValidationScenario,
        result: ValidationResult,
        code_files: dict[str, str]
    ) -> str:
        """Build evaluation prompt for Claude"""

        # Format code files
        code_section = []
        for file_path, content in sorted(code_files.items()):
            code_section.append(f"### File: {file_path}\n```python\n{content}\n```\n")

        code_text = "\n".join(code_section)

        # Format test results
        test_info = ""
        if result.tests_passed > 0 or result.tests_failed > 0:
            test_info = f"""
**Test Results:**
- Tests Passed: {result.tests_passed}
- Tests Failed: {result.tests_failed}
- Total Tests: {result.tests_passed + result.tests_failed}
"""

        # Format check results
        check_info = ""
        if result.check_results:
            check_info = "\n**Automated Check Results:**\n"
            for key, value in result.check_results.items():
                if isinstance(value, dict):
                    status = "[OK]" if value.get("success") else "[FAIL]"
                    check_info += f"- {key}: {status}\n"

        prompt = f"""You are an expert code reviewer evaluating code generated by an AI coding agent.

**Task Given to Agent:**
{scenario.prompt}

**Generated Code:**
{code_text}

{test_info}
{check_info}

**Your Task:**
Evaluate the generated code on these criteria and provide scores from 0.0 to 1.0 for each:

1. **Completeness** (0.0-1.0):
   - Does it fulfill ALL requirements from the task prompt?
   - Are there missing features or incomplete implementations?
   - Score 1.0 = fully complete, 0.5 = half complete, 0.0 = barely started

2. **Correctness** (0.0-1.0):
   - Does the code work correctly (based on logic analysis)?
   - Are there bugs or logical errors?
   - Do tests pass (if applicable)?
   - Score 1.0 = works perfectly, 0.5 = partially works, 0.0 = broken

3. **Code Quality** (0.0-1.0):
   - Proper structure and organization
   - Good naming conventions
   - Adequate error handling
   - Documentation and comments
   - Score 1.0 = excellent quality, 0.5 = mediocre, 0.0 = poor

4. **Best Practices** (0.0-1.0):
   - Follows Python conventions (PEP 8)
   - Security considerations
   - Efficient implementation
   - Proper use of libraries/frameworks
   - Score 1.0 = exemplary, 0.5 = adequate, 0.0 = violates standards

**Important Guidelines:**
- Be objective and fair
- Consider the difficulty of the task
- Compare against what a competent human developer would produce
- Identify specific strengths and weaknesses (at least 3 each)
- Provide actionable feedback

**Response Format (JSON only):**
```json
{{
  "completeness": <score 0.0-1.0>,
  "correctness": <score 0.0-1.0>,
  "quality": <score 0.0-1.0>,
  "best_practices": <score 0.0-1.0>,
  "strengths": [
    "Specific strength 1",
    "Specific strength 2",
    "Specific strength 3"
  ],
  "weaknesses": [
    "Specific weakness 1",
    "Specific weakness 2",
    "Specific weakness 3"
  ],
  "overall_assessment": "2-3 sentence summary of the code quality and whether it accomplishes the task"
}}
```

Respond with ONLY the JSON, no other text."""

        return prompt

    def _parse_judge_response(self, response_text: str) -> dict[str, Any]:
        """
        Parse judge response, handling markdown code blocks.

        Claude might return:
        ```json
        {...}
        ```

        Or just:
        {...}
        """

        # Remove markdown code blocks
        text = response_text.strip()

        if text.startswith("```"):
            # Extract content between code blocks
            lines = text.split("\n")
            # Remove first line (```json or ```)
            lines = lines[1:]
            # Remove last line (```)
            if lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)

        # Parse JSON
        try:
            result = json.loads(text)

            # Validate required fields
            required = ["completeness", "correctness", "quality", "best_practices"]
            for field in required:
                if field not in result:
                    result[field] = 0.0

            if "strengths" not in result:
                result["strengths"] = []
            if "weaknesses" not in result:
                result["weaknesses"] = []
            if "overall_assessment" not in result:
                result["overall_assessment"] = "No assessment provided"

            # Ensure scores are in range
            for field in required:
                result[field] = max(0.0, min(1.0, float(result[field])))

            return result

        except json.JSONDecodeError as e:
            # Fallback if parsing fails
            return {
                "completeness": 0.0,
                "correctness": 0.0,
                "quality": 0.0,
                "best_practices": 0.0,
                "strengths": [],
                "weaknesses": [f"Failed to parse judge response: {str(e)}"],
                "overall_assessment": "Could not evaluate due to response parsing error.",
                "raw_response": response_text
            }

    def calculate_final_scores(
        self,
        scenario: ValidationScenario,
        result: ValidationResult,
        judge_scores: dict[str, float]
    ) -> dict[str, float]:
        """
        Calculate final weighted scores combining automated checks + judge evaluation.

        Final score components:
        - Completeness: 70% judge + 30% automated (required files, features)
        - Correctness: 70% judge + 30% automated (tests pass, runs without error)
        - Quality: 90% judge + 10% automated (has docs, proper structure)
        - Autonomy: 100% automated (human interventions)

        Then apply scenario-specific weights to get overall score.
        """

        scores = {}

        # Completeness
        judge_completeness = judge_scores.get("completeness", 0.0)
        auto_completeness = self._calculate_auto_completeness(scenario, result)
        scores["completeness"] = (judge_completeness * 0.7) + (auto_completeness * 0.3)

        # Correctness
        judge_correctness = judge_scores.get("correctness", 0.0)
        auto_correctness = self._calculate_auto_correctness(scenario, result)
        scores["correctness"] = (judge_correctness * 0.7) + (auto_correctness * 0.3)

        # Quality
        judge_quality = judge_scores.get("quality", 0.0)
        auto_quality = self._calculate_auto_quality(scenario, result)
        scores["quality"] = (judge_quality * 0.9) + (auto_quality * 0.1)

        # Autonomy (100% automated)
        scores["autonomy"] = result.autonomous_percentage

        # Calculate overall weighted score
        weights = scenario.scoring_weights
        overall = sum(
            scores.get(k, 0.0) * v
            for k, v in weights.items()
        )

        scores["overall"] = overall

        return scores

    def _calculate_auto_completeness(
        self,
        scenario: ValidationScenario,
        result: ValidationResult
    ) -> float:
        """Calculate automated completeness score"""

        score = 0.0
        checks = 0

        # Check required files
        if scenario.success_criteria.required_files:
            checks += 1
            file_check = result.check_results.get("required_files", {})
            if file_check.get("success"):
                score += 1.0

        # Check README
        if scenario.success_criteria.must_have_readme:
            checks += 1
            if result.check_results.get("readme_exists"):
                score += 1.0

        return score / checks if checks > 0 else 1.0

    def _calculate_auto_correctness(
        self,
        scenario: ValidationScenario,
        result: ValidationResult
    ) -> float:
        """Calculate automated correctness score"""

        score = 0.0
        checks = 0

        # Check tests pass
        if scenario.success_criteria.tests_must_pass:
            checks += 1
            test_check = result.check_results.get("test_results", {})
            if test_check.get("success"):
                score += 1.0
            elif test_check.get("passed", 0) > 0:
                # Partial credit for some tests passing
                total = test_check.get("total", 1)
                passed = test_check.get("passed", 0)
                score += (passed / total)

        # Check validation steps
        for key, value in result.check_results.items():
            if key.startswith("step_"):
                checks += 1
                if isinstance(value, dict) and value.get("success"):
                    score += 1.0

        return score / checks if checks > 0 else 1.0

    def _calculate_auto_quality(
        self,
        scenario: ValidationScenario,
        result: ValidationResult
    ) -> float:
        """Calculate automated quality score"""

        score = 0.0
        checks = 0

        # Check has README
        checks += 1
        if "README.md" in result.files_created:
            score += 1.0

        # Check has tests
        checks += 1
        has_tests = any("test" in f.lower() for f in result.files_created)
        if has_tests:
            score += 1.0

        # Check has reasonable LOC (not empty)
        checks += 1
        if result.lines_of_code > 50:
            score += 1.0
        elif result.lines_of_code > 20:
            score += 0.5

        return score / checks if checks > 0 else 0.5
