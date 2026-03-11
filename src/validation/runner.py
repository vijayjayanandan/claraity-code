"""
Validation Runner

CLI interface for running validation scenarios and generating reports.
"""

import argparse
import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# Load environment variables from .env file
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    # If python-dotenv not installed, try manual .env loading
    env_path = Path(__file__).parent.parent.parent / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key] = value

from src.platform import safe_print

from .judge import ValidationJudge
from .orchestrator import ValidationOrchestrator
from .report_generator import ReportGenerator
from .scenario import DifficultyLevel, ValidationReport, ValidationResult, ValidationScenario
from .scenarios import VALIDATION_SCENARIOS, get_scenario_by_id, get_scenarios_by_difficulty


class ValidationRunner:
    """
    Main runner for validation system.

    Handles:
    - CLI argument parsing
    - Scenario selection
    - Orchestration
    - Report generation
    """

    def __init__(self):
        self.orchestrator = ValidationOrchestrator()
        self.judge = None  # Initialized on demand
        self.report_generator = ReportGenerator()

    async def run(self, args):
        """Main entry point"""

        # Select scenarios
        scenarios = self._select_scenarios(args)

        if not scenarios:
            safe_print("[FAIL] No scenarios selected")
            return 1

        safe_print(f"\n{'=' * 70}")
        safe_print("[TEST] Autonomous Validation Framework")
        safe_print(f"{'=' * 70}")
        safe_print(f"Scenarios: {len(scenarios)}")
        safe_print(f"Output: {self.orchestrator.output_dir}")
        safe_print(f"{'=' * 70}\n")

        # Run all scenarios
        results = []
        for i, scenario in enumerate(scenarios, 1):
            safe_print(f"\n[{i}/{len(scenarios)}] Running: {scenario.name}")

            try:
                # Run orchestrator
                result = await self.orchestrator.run_scenario(scenario, verbose=args.verbose)

                # Run judge evaluation (if API key available)
                if args.judge:
                    try:
                        if self.judge is None:
                            self.judge = ValidationJudge()

                        workspace = Path(result.workspace_path)
                        judge_scores = await self.judge.evaluate(
                            scenario, result, workspace, verbose=args.verbose
                        )

                        # Calculate final scores
                        final_scores = self.judge.calculate_final_scores(
                            scenario, result, judge_scores
                        )

                        # Update result
                        result.scores = final_scores
                        result.overall_score = final_scores["overall"]
                        result.judge_scores = judge_scores
                        result.strengths = judge_scores.get("strengths", [])
                        result.weaknesses = judge_scores.get("weaknesses", [])
                        result.judge_feedback = judge_scores.get("overall_assessment", "")

                    except Exception as e:
                        safe_print(f"[WARN]  Judge evaluation failed: {e}")
                        # Continue without judge scores
                        result.warnings.append(f"Judge evaluation failed: {str(e)}")

                else:
                    # No judge, use automated scores only
                    result.scores = {
                        "completeness": 0.0,
                        "correctness": 0.0,
                        "quality": 0.0,
                        "autonomy": result.autonomous_percentage,
                    }
                    result.overall_score = 0.0

                # Determine success
                result.success = result.passed()

                results.append(result)

                # Print summary
                status = "[OK] PASS" if result.success else "[FAIL] FAIL"
                safe_print(f"\n{status} - Score: {result.overall_score:.1%}")

            except Exception as e:
                safe_print(f"\n[FAIL] FAILED - {e}")
                # Create failure result
                failure_result = ValidationResult(
                    scenario_id=scenario.id,
                    scenario_name=scenario.name,
                    run_id="failed",
                    success=False,
                    overall_score=0.0,
                    failure_reason=str(e),
                    failure_stage="orchestration",
                )
                results.append(failure_result)

        # Generate report
        safe_print(f"\n{'=' * 70}")
        safe_print("[REPORT] Generating Report...")
        safe_print(f"{'=' * 70}\n")

        report = self._create_report(results)
        report_path = self.report_generator.generate_report(
            report, format=args.format, output_dir=self.orchestrator.output_dir
        )

        safe_print(f"[OK] Report saved: {report_path}")
        safe_print(f"\n{'=' * 70}")
        safe_print("[TARGET] Summary")
        safe_print(f"{'=' * 70}")
        safe_print(f"Scenarios: {report.total_scenarios}")
        safe_print(f"Passed: {report.scenarios_passed}")
        safe_print(f"Failed: {report.scenarios_failed}")
        safe_print(f"Pass Rate: {report.pass_rate():.1%}")
        safe_print(f"Average Score: {report.average_score:.1%}")
        safe_print(f"Total Cost: ${report.total_cost_usd:.2f}")
        safe_print(f"{'=' * 70}\n")

        # Exit code based on results
        return 0 if report.scenarios_passed == report.total_scenarios else 1

    def _select_scenarios(self, args) -> list[ValidationScenario]:
        """Select scenarios based on CLI args"""

        if args.all:
            return VALIDATION_SCENARIOS

        if args.scenario:
            try:
                return [get_scenario_by_id(args.scenario)]
            except ValueError:
                safe_print(f"[FAIL] Unknown scenario: {args.scenario}")
                safe_print("Available scenarios:")
                for s in VALIDATION_SCENARIOS:
                    safe_print(f"  - {s.id} ({s.difficulty.value}): {s.name}")
                sys.exit(1)

        if args.difficulty:
            try:
                diff = DifficultyLevel(args.difficulty.lower())
                return get_scenarios_by_difficulty(diff)
            except ValueError:
                safe_print(f"[FAIL] Unknown difficulty: {args.difficulty}")
                safe_print("Available: easy, medium, hard")
                sys.exit(1)

        # Default: show help
        return []

    def _create_report(self, results: list[ValidationResult]) -> ValidationReport:
        """Create aggregated report from results"""

        total = len(results)
        passed = sum(1 for r in results if r.success)
        failed = total - passed

        avg_score = sum(r.overall_score for r in results) / total if total > 0 else 0.0
        total_duration = sum(r.duration_seconds for r in results)
        total_cost = sum(r.estimated_cost_usd for r in results)

        # Aggregate strengths and weaknesses
        all_strengths = []
        all_weaknesses = []
        for r in results:
            all_strengths.extend(r.strengths)
            all_weaknesses.extend(r.weaknesses)

        # Identify critical gaps (common weaknesses)
        weakness_counts = {}
        for w in all_weaknesses:
            # Normalize (lowercase, strip)
            normalized = w.lower().strip()
            weakness_counts[normalized] = weakness_counts.get(normalized, 0) + 1

        # Top 5 most common weaknesses = critical gaps
        critical_gaps = sorted(weakness_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        critical_gaps = [gap[0] for gap in critical_gaps]

        # Recommended priorities based on failures
        priorities = []
        if any("context" in w.lower() for w in all_weaknesses):
            priorities.append("🔥 Session management - Save/resume for long tasks")
        if any("search" in w.lower() or "docs" in w.lower() for w in all_weaknesses):
            priorities.append("🔥 Web search integration - Critical for finding docs/examples")
        if any("error" in w.lower() or "fail" in w.lower() for w in all_weaknesses):
            priorities.append("🔥 Better error recovery - Retry strategies, alternative approaches")

        report = ValidationReport(
            generated_at=datetime.now(),
            total_scenarios=total,
            scenarios_passed=passed,
            scenarios_failed=failed,
            results=results,
            average_score=avg_score,
            total_duration_seconds=total_duration,
            total_cost_usd=total_cost,
            strengths=list(set(all_strengths))[:10],  # Top 10 unique strengths
            critical_gaps=critical_gaps,
            recommended_priorities=priorities,
        )

        return report


def main():
    """CLI entry point"""

    parser = argparse.ArgumentParser(
        description="Autonomous Validation Framework for AI Coding Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run all scenarios
  python -m src.validation.run --all

  # Run specific scenario
  python -m src.validation.run --scenario easy_cli_weather

  # Run by difficulty
  python -m src.validation.run --difficulty easy

  # Run with judge evaluation
  python -m src.validation.run --all --judge

  # Generate HTML report
  python -m src.validation.run --all --format html

Available Scenarios:
  - easy_cli_weather: CLI Weather Tool (2 hours)
  - medium_rest_api: Task Management REST API (4 hours)
  - hard_web_scraper: Hacker News Scraper (6 hours)
        """,
    )

    # Scenario selection (mutually exclusive)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="Run all validation scenarios")
    group.add_argument("--scenario", type=str, help="Run specific scenario by ID")
    group.add_argument(
        "--difficulty",
        type=str,
        choices=["easy", "medium", "hard"],
        help="Run all scenarios of given difficulty",
    )

    # Options
    parser.add_argument(
        "--judge",
        action="store_true",
        default=True,
        help="Enable Claude judge evaluation (requires ANTHROPIC_API_KEY)",
    )
    parser.add_argument(
        "--no-judge",
        action="store_false",
        dest="judge",
        help="Disable judge evaluation (automated checks only)",
    )
    parser.add_argument(
        "--format",
        type=str,
        choices=["markdown", "html", "json"],
        default="markdown",
        help="Report format (default: markdown)",
    )
    parser.add_argument("--verbose", action="store_true", default=True, help="Verbose output")
    parser.add_argument(
        "--output-dir",
        type=str,
        default="./validation-results",
        help="Output directory for results",
    )

    args = parser.parse_args()

    # Run validation
    runner = ValidationRunner()
    runner.orchestrator.output_dir = Path(args.output_dir)

    exit_code = asyncio.run(runner.run(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
