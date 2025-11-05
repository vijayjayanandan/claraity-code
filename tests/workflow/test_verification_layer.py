"""Tests for verification layer.

Tests the three-tier verification approach:
- Tier 1: Basic syntax checks (no tools needed)
- Tier 2: Use available tools (pytest, ruff, eslint, etc.)
- Tier 3: Respect project config (future)
"""

import pytest
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from src.workflow.verification_layer import (
    VerificationLayer,
    VerificationError,
    VerificationResult,
    VerificationSeverity
)


@pytest.fixture
def temp_file():
    """Create a temporary file for testing."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        yield Path(f.name)
    # Cleanup
    Path(f.name).unlink(missing_ok=True)


@pytest.fixture
def verifier():
    """Create verification layer instance without recommendations."""
    return VerificationLayer(show_recommendations=False)


class TestVerificationError:
    """Tests for VerificationError dataclass."""

    def test_error_string_formatting(self):
        """Test error string formatting."""
        error = VerificationError(
            tool="ruff",
            severity=VerificationSeverity.ERROR,
            message="Line too long",
            file_path="/path/to/file.py",
            line=42,
            column=80,
            code="E501"
        )

        error_str = str(error)
        assert "/path/to/file.py:42:80" in error_str
        assert "[E501]" in error_str
        assert "Line too long" in error_str
        assert "❌" in error_str

    def test_warning_formatting(self):
        """Test warning formatting."""
        warning = VerificationError(
            tool="ruff",
            severity=VerificationSeverity.WARNING,
            message="Unused import",
            file_path="/path/to/file.py",
            line=5
        )

        warning_str = str(warning)
        assert "/path/to/file.py:5" in warning_str
        assert "Unused import" in warning_str
        assert "⚠️" in warning_str

    def test_error_without_line(self):
        """Test error formatting without line number."""
        error = VerificationError(
            tool="pytest",
            severity=VerificationSeverity.ERROR,
            message="Test failed",
            file_path="/path/to/test.py"
        )

        error_str = str(error)
        assert "/path/to/test.py" in error_str
        assert "Test failed" in error_str


class TestVerificationResult:
    """Tests for VerificationResult dataclass."""

    def test_result_with_errors(self):
        """Test result with errors."""
        result = VerificationResult(
            file_path="/path/to/file.py",
            passed=False,
            errors=[
                VerificationError(
                    tool="ruff",
                    severity=VerificationSeverity.ERROR,
                    message="Error 1",
                    file_path="/path/to/file.py"
                )
            ],
            tools_run=["python-syntax", "ruff"]
        )

        assert result.has_errors is True
        assert result.has_warnings is False
        assert not result.passed

    def test_result_with_warnings_only(self):
        """Test result with warnings but no errors."""
        result = VerificationResult(
            file_path="/path/to/file.py",
            passed=True,
            warnings=[
                VerificationError(
                    tool="ruff",
                    severity=VerificationSeverity.WARNING,
                    message="Warning 1",
                    file_path="/path/to/file.py"
                )
            ]
        )

        assert result.has_errors is False
        assert result.has_warnings is True
        assert result.passed

    def test_format_for_display(self):
        """Test formatting result for display."""
        result = VerificationResult(
            file_path="/path/to/file.py",
            passed=False,
            errors=[
                VerificationError(
                    tool="ruff",
                    severity=VerificationSeverity.ERROR,
                    message="Error 1",
                    file_path="/path/to/file.py",
                    line=10
                )
            ],
            warnings=[
                VerificationError(
                    tool="ruff",
                    severity=VerificationSeverity.WARNING,
                    message="Warning 1",
                    file_path="/path/to/file.py",
                    line=20
                )
            ],
            tools_run=["python-syntax", "ruff"],
            tools_skipped=["pytest"],
            summary="Found issues",
            tier=2
        )

        display = result.format_for_display()
        assert "FAILED" in display
        assert "Errors (1)" in display
        assert "Warnings (1)" in display
        assert "python-syntax, ruff" in display
        assert "pytest" in display
        assert "**Tier:** 2" in display


class TestToolDetection:
    """Tests for tool detection."""

    def test_detect_tools(self, verifier):
        """Test tool detection."""
        tools = verifier.available_tools

        # Should detect available tools
        assert isinstance(tools, dict)
        assert 'pytest' in tools
        assert 'ruff' in tools
        assert 'python' in tools
        assert 'npx' in tools
        assert 'mvn' in tools

        # Values should be boolean
        for tool, available in tools.items():
            assert isinstance(available, bool)

    @patch('shutil.which')
    def test_detect_tools_none_available(self, mock_which):
        """Test when no tools are available."""
        mock_which.return_value = None

        verifier = VerificationLayer(show_recommendations=False)
        tools = verifier.available_tools

        assert all(available is False for available in tools.values())


class TestPythonVerification:
    """Tests for Python file verification."""

    def test_verify_python_valid_syntax(self, temp_file, verifier):
        """Test verifying Python file with valid syntax."""
        # Write valid Python code
        temp_file.write_text("def hello():\n    return 'world'\n")

        result = verifier.verify_file(str(temp_file))

        assert result.passed
        assert not result.has_errors
        assert 'python-syntax' in result.tools_run
        assert result.tier >= 1

    def test_verify_python_syntax_error(self, temp_file, verifier):
        """Test verifying Python file with syntax error."""
        # Write invalid Python code
        temp_file.write_text("def hello(\n    return 'world'\n")

        result = verifier.verify_file(str(temp_file))

        assert not result.passed
        assert result.has_errors
        assert len(result.errors) == 1
        assert result.errors[0].tool == "python-syntax"
        assert result.errors[0].severity == VerificationSeverity.ERROR
        assert 'python-syntax' in result.tools_run

    def test_verify_python_indentation_error(self, temp_file, verifier):
        """Test verifying Python file with indentation error."""
        temp_file.write_text("def hello():\nreturn 'world'\n")

        result = verifier.verify_file(str(temp_file))

        assert not result.passed
        assert result.has_errors

    @patch('subprocess.run')
    def test_verify_python_with_ruff(self, mock_run, temp_file, verifier):
        """Test Python verification with ruff."""
        # Write valid Python code
        temp_file.write_text("def hello():\n    return 'world'\n")

        # Mock ruff availability
        verifier.available_tools['ruff'] = True

        # Mock ruff output (no issues)
        mock_run.return_value = Mock(
            returncode=0,
            stdout='[]',
            stderr=''
        )

        result = verifier.verify_file(str(temp_file))

        assert result.passed
        assert 'ruff' in result.tools_run
        assert result.tier == 2

    @patch('subprocess.run')
    def test_verify_python_ruff_finds_issues(self, mock_run, temp_file, verifier):
        """Test ruff finding issues."""
        temp_file.write_text("def hello():\n    return 'world'\n")

        # Mock ruff availability
        verifier.available_tools['ruff'] = True

        # Mock ruff output with issues
        mock_run.return_value = Mock(
            returncode=1,
            stdout='[{"code": "E501", "message": "Line too long", "filename": "'
                   + str(temp_file) + '", "location": {"row": 1, "column": 80}}]',
            stderr=''
        )

        result = verifier.verify_file(str(temp_file))

        # Syntax is OK, but ruff found issue
        assert not result.passed
        assert result.has_errors
        assert any(e.code == "E501" for e in result.errors)

    @patch('subprocess.run')
    def test_verify_python_test_file_with_pytest(self, mock_run, temp_file, verifier):
        """Test running pytest on test file."""
        # Create test file
        test_file = temp_file.parent / "test_sample.py"
        test_file.write_text("def test_hello():\n    assert True\n")

        # Mock pytest availability
        verifier.available_tools['pytest'] = True
        verifier.available_tools['ruff'] = False  # Disable ruff for this test

        # Mock pytest success
        mock_run.return_value = Mock(
            returncode=0,
            stdout='test_sample.py::test_hello PASSED',
            stderr=''
        )

        result = verifier.verify_file(str(test_file))

        assert result.passed
        assert 'pytest' in result.tools_run

        # Cleanup
        test_file.unlink()

    @patch('subprocess.run')
    def test_verify_python_test_failure(self, mock_run, temp_file, verifier):
        """Test pytest detecting test failure."""
        # Create test file
        test_file = temp_file.parent / "test_fail.py"
        test_file.write_text("def test_fail():\n    assert False\n")

        # Mock pytest availability
        verifier.available_tools['pytest'] = True
        verifier.available_tools['ruff'] = False

        # Mock pytest failure
        mock_run.return_value = Mock(
            returncode=1,
            stdout='test_fail.py::test_fail FAILED\nAssertionError',
            stderr=''
        )

        result = verifier.verify_file(str(test_file))

        assert not result.passed
        assert result.has_errors
        assert any('FAILED' in e.message for e in result.errors)

        # Cleanup
        test_file.unlink()

    def test_verify_python_without_tools(self, temp_file):
        """Test Python verification works without any tools."""
        # Create verifier with no tools
        with patch('shutil.which', return_value=None):
            verifier_no_tools = VerificationLayer(show_recommendations=False)

        # Write valid Python
        temp_file.write_text("def hello():\n    return 'world'\n")

        result = verifier_no_tools.verify_file(str(temp_file))

        # Should still pass with Tier 1 syntax check
        assert result.passed
        assert result.tier == 1
        assert 'python-syntax' in result.tools_run


class TestJavaScriptVerification:
    """Tests for JavaScript/TypeScript verification."""

    def test_verify_javascript_basic(self, verifier):
        """Test basic JavaScript verification."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False) as f:
            f.write("function hello() { return 'world'; }\n")
            js_file = Path(f.name)

        try:
            result = verifier.verify_file(str(js_file))

            # Basic verification should pass
            assert result.passed
            assert result.tier >= 1
            assert 'basic-check' in result.tools_run

        finally:
            js_file.unlink()

    def test_verify_typescript_basic(self, verifier):
        """Test basic TypeScript verification."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.ts', delete=False) as f:
            f.write("function hello(): string { return 'world'; }\n")
            ts_file = Path(f.name)

        try:
            result = verifier.verify_file(str(ts_file))

            assert result.passed
            assert result.tier >= 1

        finally:
            ts_file.unlink()


class TestJavaVerification:
    """Tests for Java verification."""

    def test_verify_java_basic(self, verifier):
        """Test basic Java verification."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.java', delete=False) as f:
            f.write("public class Hello {\n"
                   "    public static void main(String[] args) {\n"
                   "        System.out.println(\"Hello\");\n"
                   "    }\n"
                   "}\n")
            java_file = Path(f.name)

        try:
            result = verifier.verify_file(str(java_file))

            # Basic verification should pass
            assert result.passed
            assert result.tier >= 1

        finally:
            java_file.unlink()


class TestErrorHandling:
    """Tests for error handling."""

    def test_verify_nonexistent_file(self, verifier):
        """Test verifying non-existent file."""
        result = verifier.verify_file("/nonexistent/file.py")

        assert not result.passed
        assert result.has_errors
        assert "not found" in result.errors[0].message.lower()

    def test_verify_unsupported_extension(self, verifier):
        """Test verifying file with unsupported extension."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.xyz', delete=False) as f:
            f.write("some content\n")
            unknown_file = Path(f.name)

        try:
            result = verifier.verify_file(str(unknown_file))

            # Should pass but with no verification
            assert result.passed
            assert "No verification available" in result.summary

        finally:
            unknown_file.unlink()

    def test_verify_unreadable_file(self, temp_file, verifier):
        """Test verifying unreadable file."""
        temp_file.write_text("def hello():\n    return 'world'\n")

        # Mock file reading to fail
        with patch('builtins.open', side_effect=PermissionError("Access denied")):
            result = verifier._check_python_syntax(temp_file)

            assert result is not None
            assert result.severity == VerificationSeverity.ERROR
            assert "Failed to parse" in result.message

    @patch('subprocess.run')
    def test_ruff_timeout(self, mock_run, temp_file, verifier):
        """Test ruff timing out."""
        temp_file.write_text("def hello():\n    return 'world'\n")

        verifier.available_tools['ruff'] = True

        # Mock timeout
        mock_run.side_effect = subprocess.TimeoutExpired('ruff', 30)

        result = verifier.verify_file(str(temp_file))

        # Should still pass (syntax is OK, ruff just timed out)
        assert result.passed
        assert result.has_warnings
        assert any('timed out' in w.message.lower() for w in result.warnings)

    @patch('subprocess.run')
    def test_pytest_timeout(self, mock_run, temp_file, verifier):
        """Test pytest timing out."""
        # Create test file
        test_file = temp_file.parent / "test_slow.py"
        test_file.write_text("def test_slow():\n    import time\n    time.sleep(100)\n")

        verifier.available_tools['pytest'] = True
        verifier.available_tools['ruff'] = False

        # Mock timeout
        mock_run.side_effect = subprocess.TimeoutExpired('pytest', 60)

        result = verifier.verify_file(str(test_file))

        assert not result.passed
        assert result.has_errors
        assert any('timed out' in e.message.lower() for e in result.errors)

        # Cleanup
        test_file.unlink()


class TestThreeTierApproach:
    """Tests for the three-tier verification approach."""

    def test_tier1_works_without_tools(self, temp_file):
        """Test Tier 1 works even without any tools."""
        # Mock no tools available
        with patch('shutil.which', return_value=None):
            verifier = VerificationLayer(show_recommendations=False)

        temp_file.write_text("def hello():\n    return 'world'\n")

        result = verifier.verify_file(str(temp_file))

        assert result.passed
        assert result.tier == 1
        assert 'python-syntax' in result.tools_run
        assert len(result.tools_skipped) > 0  # Should have skipped ruff, pytest

    @patch('subprocess.run')
    def test_tier2_uses_available_tools(self, mock_run, temp_file, verifier):
        """Test Tier 2 uses available tools."""
        temp_file.write_text("def hello():\n    return 'world'\n")

        verifier.available_tools['ruff'] = True
        mock_run.return_value = Mock(returncode=0, stdout='[]', stderr='')

        result = verifier.verify_file(str(temp_file))

        assert result.tier == 2
        assert 'python-syntax' in result.tools_run
        assert 'ruff' in result.tools_run

    def test_tools_skipped_when_not_available(self, temp_file, verifier):
        """Test tools are marked as skipped when not available."""
        temp_file.write_text("def hello():\n    return 'world'\n")

        # Disable all tools
        verifier.available_tools['ruff'] = False
        verifier.available_tools['pytest'] = False

        result = verifier.verify_file(str(temp_file))

        assert 'ruff' in result.tools_skipped


class TestIntegration:
    """Integration tests with real files."""

    def test_verify_real_python_module(self, verifier):
        """Test verifying a real Python module from the codebase."""
        # Verify our own verification layer file
        file_path = Path(__file__).parent.parent.parent / "src" / "workflow" / "verification_layer.py"

        if file_path.exists():
            result = verifier.verify_file(str(file_path))

            # Should at least pass syntax check
            assert 'python-syntax' in result.tools_run
            # File should have valid syntax
            assert not any(e.tool == 'python-syntax' for e in result.errors)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
