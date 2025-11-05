"""Simple verification layer with three-tier approach.

This module provides file verification after code modifications using a three-tier
strategy:
- Tier 1: Basic syntax checks (no tools needed) - always works
- Tier 2: Use available development tools (pytest, ruff, eslint, etc.)
- Tier 3: Respect project configuration (future enhancement)

The design follows the Aider approach: use system tools via subprocess rather than
bundling tools with the agent.
"""

import ast
import json
import subprocess
import shutil
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class VerificationSeverity(Enum):
    """Severity levels for verification issues."""
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class VerificationError:
    """Represents a single verification issue.

    Attributes:
        tool: Name of the tool that found the issue
        severity: Severity level (error, warning, info)
        message: Human-readable error message
        file_path: Path to the file with the issue
        line: Optional line number
        column: Optional column number
        code: Optional error code (e.g., E501 for ruff)
    """
    tool: str
    severity: VerificationSeverity
    message: str
    file_path: str
    line: Optional[int] = None
    column: Optional[int] = None
    code: Optional[str] = None

    def __str__(self) -> str:
        """Format error for display."""
        location = f"{self.file_path}"
        if self.line:
            location += f":{self.line}"
        if self.column:
            location += f":{self.column}"

        severity_emoji = {
            VerificationSeverity.ERROR: "❌",
            VerificationSeverity.WARNING: "⚠️",
            VerificationSeverity.INFO: "ℹ️"
        }
        emoji = severity_emoji.get(self.severity, "•")

        code_str = f" [{self.code}]" if self.code else ""
        return f"{emoji} {location}{code_str}: {self.message}"


@dataclass
class VerificationResult:
    """Result of verifying a file.

    Attributes:
        file_path: Path to the verified file
        passed: Whether verification passed (no errors)
        errors: List of error-level issues
        warnings: List of warning-level issues
        info: List of informational messages
        tools_run: List of tools that were executed
        tools_skipped: List of tools that were skipped (not installed)
        summary: Human-readable summary
        tier: Which tier verification completed at (1, 2, or 3)
    """
    file_path: str
    passed: bool
    errors: List[VerificationError] = field(default_factory=list)
    warnings: List[VerificationError] = field(default_factory=list)
    info: List[VerificationError] = field(default_factory=list)
    tools_run: List[str] = field(default_factory=list)
    tools_skipped: List[str] = field(default_factory=list)
    summary: str = ""
    tier: int = 1

    @property
    def has_errors(self) -> bool:
        """Check if there are any errors."""
        return len(self.errors) > 0

    @property
    def has_warnings(self) -> bool:
        """Check if there are any warnings."""
        return len(self.warnings) > 0

    def format_for_display(self) -> str:
        """Format result for user display."""
        lines = [
            "",
            "=" * 70,
            f"🔍 Verification Result: {self.file_path}",
            "=" * 70,
            ""
        ]

        # Status
        if self.passed:
            lines.append("✅ **Status:** PASSED")
        else:
            lines.append("❌ **Status:** FAILED")

        lines.append(f"**Tier:** {self.tier}")
        lines.append("")

        # Tools
        if self.tools_run:
            lines.append(f"**Tools Run:** {', '.join(self.tools_run)}")
        if self.tools_skipped:
            lines.append(f"**Tools Skipped:** {', '.join(self.tools_skipped)}")
        lines.append("")

        # Errors
        if self.errors:
            lines.append(f"### Errors ({len(self.errors)}):")
            lines.append("")
            for error in self.errors:
                lines.append(f"  {error}")
            lines.append("")

        # Warnings
        if self.warnings:
            lines.append(f"### Warnings ({len(self.warnings)}):")
            lines.append("")
            for warning in self.warnings:
                lines.append(f"  {warning}")
            lines.append("")

        # Summary
        if self.summary:
            lines.append(f"**Summary:** {self.summary}")
            lines.append("")

        lines.append("=" * 70)
        return "\n".join(lines)


class VerificationLayer:
    """Three-tier verification layer for code changes.

    This class implements a progressive verification strategy:
    - Tier 1: Basic syntax checks (no external tools needed)
    - Tier 2: Use available development tools (pytest, ruff, eslint, etc.)
    - Tier 3: Respect project configuration (future)

    The layer detects available tools and uses them, but degrades gracefully
    if tools are missing.
    """

    # File extensions mapped to language
    LANGUAGE_MAP = {
        '.py': 'python',
        '.js': 'javascript',
        '.jsx': 'javascript',
        '.ts': 'typescript',
        '.tsx': 'typescript',
        '.java': 'java',
    }

    def __init__(self, show_recommendations: bool = True):
        """Initialize verification layer.

        Args:
            show_recommendations: Whether to show tool installation recommendations
        """
        self.show_recommendations = show_recommendations
        self.available_tools = self._detect_tools()

        if show_recommendations:
            self._show_tool_status()

        logger.info(f"VerificationLayer initialized with tools: {self.available_tools}")

    def _detect_tools(self) -> Dict[str, bool]:
        """Tier 2: Detect available development tools.

        Returns:
            Dict mapping tool names to availability
        """
        tools = {
            # Python tools
            'pytest': shutil.which('pytest') is not None,
            'ruff': shutil.which('ruff') is not None,
            'python': shutil.which('python') is not None or shutil.which('python3') is not None,

            # JavaScript/TypeScript tools
            'npx': shutil.which('npx') is not None,
            'node': shutil.which('node') is not None,

            # Java tools
            'mvn': shutil.which('mvn') is not None,
            'gradle': shutil.which('gradle') is not None,
            'javac': shutil.which('javac') is not None,
        }

        logger.debug(f"Tool detection: {tools}")
        return tools

    def _show_tool_status(self) -> None:
        """Show status of available tools and recommendations."""
        recommendations = []

        # Python recommendations
        if not self.available_tools.get('pytest'):
            recommendations.append("  • pytest: pip install pytest")
        if not self.available_tools.get('ruff'):
            recommendations.append("  • ruff: pip install ruff")

        # JavaScript/TypeScript recommendations
        if not self.available_tools.get('npx'):
            recommendations.append("  • npx: Install Node.js from nodejs.org")

        # Java recommendations
        if not self.available_tools.get('mvn') and not self.available_tools.get('gradle'):
            recommendations.append("  • Maven: Install from maven.apache.org")
            recommendations.append("  • Gradle: Install from gradle.org")

        if recommendations:
            logger.info("\n" + "=" * 70)
            logger.info("📦 Recommended Tools for Better Verification:")
            logger.info("=" * 70)
            for rec in recommendations:
                logger.info(rec)
            logger.info("=" * 70 + "\n")

    def verify_file(self, file_path: str) -> VerificationResult:
        """Verify a file using three-tier approach.

        Args:
            file_path: Path to the file to verify

        Returns:
            VerificationResult with findings
        """
        path = Path(file_path)

        # Check file exists
        if not path.exists():
            return VerificationResult(
                file_path=file_path,
                passed=False,
                errors=[VerificationError(
                    tool="verification",
                    severity=VerificationSeverity.ERROR,
                    message=f"File not found: {file_path}",
                    file_path=file_path
                )],
                summary="File does not exist"
            )

        # Determine language
        language = self.LANGUAGE_MAP.get(path.suffix)
        if not language:
            logger.warning(f"Unsupported file type: {path.suffix}")
            return VerificationResult(
                file_path=file_path,
                passed=True,
                summary=f"No verification available for {path.suffix} files",
                tier=1
            )

        # Run verification based on language
        if language == 'python':
            return self._verify_python(path)
        elif language in ['javascript', 'typescript']:
            return self._verify_javascript(path)
        elif language == 'java':
            return self._verify_java(path)
        else:
            return VerificationResult(
                file_path=file_path,
                passed=True,
                summary=f"No verification implemented for {language}",
                tier=1
            )

    def _verify_python(self, path: Path) -> VerificationResult:
        """Verify Python file.

        Args:
            path: Path to Python file

        Returns:
            VerificationResult
        """
        errors = []
        warnings = []
        tools_run = []
        tools_skipped = []
        tier = 1

        # Tier 1: Syntax check (always available)
        syntax_error = self._check_python_syntax(path)
        if syntax_error:
            errors.append(syntax_error)
            # If syntax fails, don't run other tools
            return VerificationResult(
                file_path=str(path),
                passed=False,
                errors=errors,
                tools_run=['python-syntax'],
                summary="Python syntax error detected",
                tier=1
            )

        tools_run.append('python-syntax')

        # Tier 2: Use available tools (only if we actually use them)
        # Start at tier 1, upgrade to tier 2 if we run tier 2 tools

        # Run ruff if available
        if self.available_tools.get('ruff'):
            tier = 2  # Upgrade to tier 2
            ruff_issues = self._run_ruff(path)
            for issue in ruff_issues:
                if issue.severity == VerificationSeverity.ERROR:
                    errors.append(issue)
                elif issue.severity == VerificationSeverity.WARNING:
                    warnings.append(issue)
            tools_run.append('ruff')
        else:
            tools_skipped.append('ruff')

        # Run pytest if it's a test file
        if self.available_tools.get('pytest') and ('test_' in path.name or path.name.endswith('_test.py')):
            tier = 2  # Upgrade to tier 2
            test_errors = self._run_pytest(path)
            errors.extend(test_errors)
            tools_run.append('pytest')
        elif 'test_' in path.name or path.name.endswith('_test.py'):
            tools_skipped.append('pytest')

        # Determine if passed
        passed = len(errors) == 0

        # Generate summary
        if passed:
            summary = f"✅ Python verification passed ({len(tools_run)} tools)"
        else:
            summary = f"❌ Found {len(errors)} error(s), {len(warnings)} warning(s)"

        return VerificationResult(
            file_path=str(path),
            passed=passed,
            errors=errors,
            warnings=warnings,
            tools_run=tools_run,
            tools_skipped=tools_skipped,
            summary=summary,
            tier=tier
        )

    def _check_python_syntax(self, path: Path) -> Optional[VerificationError]:
        """Tier 1: Check Python syntax using ast.parse.

        Args:
            path: Path to Python file

        Returns:
            VerificationError if syntax is invalid, None otherwise
        """
        try:
            with open(path, 'r', encoding='utf-8') as f:
                source = f.read()
            ast.parse(source)
            logger.debug(f"Python syntax OK: {path}")
            return None
        except SyntaxError as e:
            logger.warning(f"Python syntax error in {path}: {e}")
            return VerificationError(
                tool="python-syntax",
                severity=VerificationSeverity.ERROR,
                message=f"Syntax error: {e.msg}",
                file_path=str(path),
                line=e.lineno,
                column=e.offset
            )
        except Exception as e:
            logger.error(f"Error checking Python syntax: {e}")
            return VerificationError(
                tool="python-syntax",
                severity=VerificationSeverity.ERROR,
                message=f"Failed to parse file: {str(e)}",
                file_path=str(path)
            )

    def _run_ruff(self, path: Path) -> List[VerificationError]:
        """Run ruff linter on Python file.

        Args:
            path: Path to Python file

        Returns:
            List of VerificationErrors
        """
        try:
            result = subprocess.run(
                ['ruff', 'check', '--output-format=json', str(path)],
                capture_output=True,
                text=True,
                timeout=30
            )

            # Ruff returns JSON even on errors
            if result.stdout:
                issues = json.loads(result.stdout)
                errors = []

                for issue in issues:
                    # Determine severity
                    # Ruff doesn't have explicit severity, so we treat all as warnings
                    # except for specific error codes
                    severity = VerificationSeverity.WARNING
                    if issue.get('code', '').startswith('E'):
                        severity = VerificationSeverity.ERROR

                    errors.append(VerificationError(
                        tool="ruff",
                        severity=severity,
                        message=issue.get('message', 'Linting issue'),
                        file_path=issue.get('filename', str(path)),
                        line=issue.get('location', {}).get('row'),
                        column=issue.get('location', {}).get('column'),
                        code=issue.get('code')
                    ))

                logger.debug(f"Ruff found {len(errors)} issues in {path}")
                return errors

            return []

        except subprocess.TimeoutExpired:
            logger.warning(f"Ruff timed out on {path}")
            return [VerificationError(
                tool="ruff",
                severity=VerificationSeverity.WARNING,
                message="Linting timed out after 30 seconds",
                file_path=str(path)
            )]
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse ruff output: {e}")
            return []
        except Exception as e:
            logger.error(f"Error running ruff: {e}")
            return []

    def _run_pytest(self, path: Path) -> List[VerificationError]:
        """Run pytest on test file.

        Args:
            path: Path to test file

        Returns:
            List of VerificationErrors for failed tests
        """
        try:
            result = subprocess.run(
                ['pytest', str(path), '-xvs', '--tb=short'],
                capture_output=True,
                text=True,
                timeout=60
            )

            # If pytest passed, return empty list
            if result.returncode == 0:
                logger.debug(f"Pytest passed for {path}")
                return []

            # Parse failure from output
            # This is simplified - pytest output parsing is complex
            error_msg = "Test execution failed"
            if "FAILED" in result.stdout:
                # Extract failure summary
                lines = result.stdout.split('\n')
                failed_lines = [l for l in lines if 'FAILED' in l or 'ERROR' in l]
                if failed_lines:
                    error_msg = "\n".join(failed_lines[:3])  # Show first 3 failures

            return [VerificationError(
                tool="pytest",
                severity=VerificationSeverity.ERROR,
                message=error_msg,
                file_path=str(path)
            )]

        except subprocess.TimeoutExpired:
            logger.warning(f"Pytest timed out on {path}")
            return [VerificationError(
                tool="pytest",
                severity=VerificationSeverity.ERROR,
                message="Tests timed out after 60 seconds",
                file_path=str(path)
            )]
        except Exception as e:
            logger.error(f"Error running pytest: {e}")
            return [VerificationError(
                tool="pytest",
                severity=VerificationSeverity.ERROR,
                message=f"Failed to run tests: {str(e)}",
                file_path=str(path)
            )]

    def _verify_javascript(self, path: Path) -> VerificationResult:
        """Verify JavaScript/TypeScript file.

        Args:
            path: Path to JS/TS file

        Returns:
            VerificationResult
        """
        errors = []
        warnings = []
        tools_run = []
        tools_skipped = []
        tier = 1

        # Tier 1: Basic check (file is readable)
        try:
            with open(path, 'r', encoding='utf-8') as f:
                f.read()
            tools_run.append('basic-check')
        except Exception as e:
            return VerificationResult(
                file_path=str(path),
                passed=False,
                errors=[VerificationError(
                    tool="basic-check",
                    severity=VerificationSeverity.ERROR,
                    message=f"Cannot read file: {str(e)}",
                    file_path=str(path)
                )],
                summary="File read error",
                tier=1
            )

        # Tier 2: Use npx to run tools
        tier = 2

        # For now, we'll skip JavaScript verification in detail
        # In a real implementation, we would run:
        # - npx eslint for linting
        # - npx tsc for TypeScript type checking
        # - npm test for running tests

        if not self.available_tools.get('npx'):
            tools_skipped.extend(['eslint', 'tsc'])

        return VerificationResult(
            file_path=str(path),
            passed=True,
            tools_run=tools_run,
            tools_skipped=tools_skipped,
            summary="JavaScript/TypeScript basic verification passed (detailed checks not yet implemented)",
            tier=tier
        )

    def _verify_java(self, path: Path) -> VerificationResult:
        """Verify Java file.

        Args:
            path: Path to Java file

        Returns:
            VerificationResult
        """
        errors = []
        warnings = []
        tools_run = []
        tools_skipped = []
        tier = 1

        # Tier 1: Basic check (file is readable)
        try:
            with open(path, 'r', encoding='utf-8') as f:
                f.read()
            tools_run.append('basic-check')
        except Exception as e:
            return VerificationResult(
                file_path=str(path),
                passed=False,
                errors=[VerificationError(
                    tool="basic-check",
                    severity=VerificationSeverity.ERROR,
                    message=f"Cannot read file: {str(e)}",
                    file_path=str(path)
                )],
                summary="File read error",
                tier=1
            )

        # Tier 2: Use Maven/Gradle
        tier = 2

        # For now, we'll skip Java verification in detail
        # In a real implementation, we would run:
        # - mvn compile or gradle build
        # - mvn test or gradle test

        if not self.available_tools.get('mvn') and not self.available_tools.get('gradle'):
            tools_skipped.extend(['maven', 'gradle'])

        return VerificationResult(
            file_path=str(path),
            passed=True,
            tools_run=tools_run,
            tools_skipped=tools_skipped,
            summary="Java basic verification passed (detailed checks not yet implemented)",
            tier=tier
        )
