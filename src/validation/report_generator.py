"""
Report Generator

Generates validation reports in multiple formats (Markdown, HTML, JSON).
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from .scenario import ValidationReport, ValidationResult


class ReportGenerator:
    """Generates comprehensive validation reports"""

    def generate_report(
        self,
        report: ValidationReport,
        format: str = "markdown",
        output_dir: Path | None = None
    ) -> Path:
        """
        Generate validation report in specified format.

        Args:
            report: ValidationReport to generate from
            format: "markdown", "html", or "json"
            output_dir: Output directory (default: validation-results)

        Returns:
            Path to generated report file
        """

        if output_dir is None:
            output_dir = Path("./validation-results")

        output_dir.mkdir(exist_ok=True, parents=True)

        timestamp = report.generated_at.strftime("%Y%m%d_%H%M%S")

        if format == "markdown":
            content = self._generate_markdown(report)
            filename = f"validation_report_{timestamp}.md"
        elif format == "html":
            content = self._generate_html(report)
            filename = f"validation_report_{timestamp}.html"
        elif format == "json":
            content = json.dumps(report.to_dict(), indent=2)
            filename = f"validation_report_{timestamp}.json"
        else:
            raise ValueError(f"Unknown format: {format}")

        report_path = output_dir / filename
        report_path.write_text(content, encoding="utf-8")

        return report_path

    def _generate_markdown(self, report: ValidationReport) -> str:
        """Generate markdown report"""

        # Header
        md = f"""# [TEST] Autonomous Validation Report

**Generated:** {report.generated_at.strftime("%Y-%m-%d %H:%M:%S")}

---

## Executive Summary

| Metric | Value |
|--------|-------|
| **Total Scenarios** | {report.total_scenarios} |
| **Passed** | {report.scenarios_passed} [OK] |
| **Failed** | {report.scenarios_failed} [FAIL] |
| **Pass Rate** | {report.pass_rate():.1%} |
| **Average Score** | {report.average_score:.1%} |
| **Total Duration** | {report.total_duration_seconds/3600:.1f} hours |
| **Total Cost** | ${report.total_cost_usd:.2f} |

---

## Scenario Results

"""

        # Individual results
        for i, result in enumerate(report.results, 1):
            status = "[OK] PASS" if result.success else "[FAIL] FAIL"
            md += f"### {i}. {status} - {result.scenario_name}\n\n"

            md += f"""**Scenario ID:** `{result.scenario_id}`
**Duration:** {result.duration_seconds/60:.1f} minutes
**Overall Score:** {result.overall_score:.1%}

"""

            # Detailed scores
            if result.scores:
                md += "**Detailed Scores:**\n"
                for key, value in sorted(result.scores.items()):
                    if key != "overall":
                        md += f"- {key.title()}: {value:.1%}\n"
                md += "\n"

            # Metrics
            md += f"""**Metrics:**
- Files Created: {len(result.files_created)}
- Lines of Code: {result.lines_of_code}
- Tests: {result.tests_passed} passed, {result.tests_failed} failed
- Autonomy: {result.autonomous_percentage:.1%}
- Cost: ${result.estimated_cost_usd:.3f}

"""

            # Strengths and weaknesses
            if result.strengths:
                md += "**Strengths:**\n"
                for strength in result.strengths:
                    md += f"- [OK] {strength}\n"
                md += "\n"

            if result.weaknesses:
                md += "**Weaknesses:**\n"
                for weakness in result.weaknesses:
                    md += f"- [WARN] {weakness}\n"
                md += "\n"

            # Judge feedback
            if result.judge_feedback:
                md += f"**Judge Assessment:**\n> {result.judge_feedback}\n\n"

            # Failure info
            if not result.success and result.failure_reason:
                md += f"**Failure Reason:**\n```\n{result.failure_reason}\n```\n\n"

            # Artifacts
            md += f"""**Artifacts:**
- Workspace: `{result.workspace_path}`
- Agent Log: `{result.agent_log_path}`
"""

            if result.judge_report_path:
                md += f"- Judge Report: `{result.judge_report_path}`\n"

            md += "\n---\n\n"

        # Key findings
        md += "## [REPORT] Key Findings\n\n"

        if report.strengths:
            md += "### What Works Well [OK]\n\n"
            for strength in report.strengths[:10]:  # Top 10
                md += f"- {strength}\n"
            md += "\n"

        if report.critical_gaps:
            md += "### Critical Gaps [WARN]\n\n"
            for i, gap in enumerate(report.critical_gaps, 1):
                md += f"{i}. {gap.title()}\n"
            md += "\n"

        if report.recommended_priorities:
            md += "### Recommended Priorities [TARGET]\n\n"
            for priority in report.recommended_priorities:
                md += f"- {priority}\n"
            md += "\n"

        # Footer
        md += """---

## Next Steps

"""

        if report.pass_rate() >= 0.8:
            md += """[OK] **Agent is performing well!**

Consider:
- Expanding test coverage with more scenarios
- Optimizing performance and cost
- Adding advanced features
"""
        elif report.pass_rate() >= 0.5:
            md += """[WARN] **Agent shows promise but needs improvement**

Recommended actions:
1. Address critical gaps identified above
2. Re-run validation to measure improvements
3. Focus on failed scenarios
"""
        else:
            md += """[FAIL] **Agent needs significant improvement**

Critical actions required:
1. Review failure reasons in detail
2. Implement fixes for critical gaps
3. Consider architecture changes if needed
4. Re-validate after improvements
"""

        md += f"""
---

*Generated by Autonomous Validation Framework*
*Report ID: {report.generated_at.strftime("%Y%m%d_%H%M%S")}*
"""

        return md

    def _generate_html(self, report: ValidationReport) -> str:
        """Generate HTML report (simple version)"""

        # For now, wrap markdown in HTML
        md_content = self._generate_markdown(report)

        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Validation Report - {report.generated_at.strftime("%Y-%m-%d")}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            line-height: 1.6;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
        }}
        .container {{
            background: white;
            padding: 40px;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}
        h1 {{ color: #2c3e50; border-bottom: 3px solid #3498db; padding-bottom: 10px; }}
        h2 {{ color: #34495e; margin-top: 30px; }}
        h3 {{ color: #7f8c8d; }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background: #3498db; color: white; }}
        tr:hover {{ background: #f5f5f5; }}
        .pass {{ color: #27ae60; font-weight: bold; }}
        .fail {{ color: #e74c3c; font-weight: bold; }}
        .metric {{ background: #ecf0f1; padding: 15px; border-radius: 5px; margin: 10px 0; }}
        code {{ background: #f8f9fa; padding: 2px 6px; border-radius: 3px; }}
        pre {{ background: #f8f9fa; padding: 15px; border-radius: 5px; overflow-x: auto; }}
        blockquote {{ border-left: 4px solid #3498db; padding-left: 20px; color: #555; }}
    </style>
</head>
<body>
    <div class="container">
        <pre style="white-space: pre-wrap; font-family: inherit; background: none; padding: 0;">
{md_content}
        </pre>
    </div>
</body>
</html>
"""

        return html
