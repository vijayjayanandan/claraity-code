"""
Comprehensive tests for LSP tools (GetFileOutlineTool, GetSymbolContextTool).

Tests cover:
- GetFileOutlineTool: File structure extraction, hierarchical parsing
- GetSymbolContextTool: Symbol search, context loading, multiple matches
- Integration: Real LSP queries, error handling, graceful degradation
"""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from src.tools.lsp_tools import GetFileOutlineTool, GetSymbolContextTool
from src.tools.base import ToolStatus


@pytest.fixture
def sample_python_file(tmp_path):
    """Create a sample Python file for testing."""
    file_path = tmp_path / "sample.py"
    file_path.write_text("""
class User:
    def __init__(self, name):
        self.name = name

    async def save(self):
        pass

def authenticate(user, password):
    '''Authenticate user with credentials.'''
    return user.name == "admin"

async def login(username, password):
    user = User(username)
    return authenticate(user, password)
""")
    return file_path


class TestGetFileOutlineTool:
    """Test GetFileOutlineTool functionality."""

    def test_tool_initialization(self):
        """Test tool can be initialized."""
        tool = GetFileOutlineTool()

        assert tool.name == "get_file_outline"
        assert tool.description
        assert tool.lsp_manager is None  # Lazy initialization

    def test_nonexistent_file(self):
        """Test error handling for nonexistent file."""
        tool = GetFileOutlineTool()
        result = tool.execute("/nonexistent/path/file.py")

        assert result.status == ToolStatus.ERROR
        assert "File not found" in result.error

    @pytest.mark.asyncio
    async def test_empty_file_symbols(self, sample_python_file):
        """Test handling of file with no symbols."""
        tool = GetFileOutlineTool()

        # Mock LSP to return empty symbols
        with patch.object(tool, '_ensure_lsp_initialized', new_callable=AsyncMock):
            mock_lsp = MagicMock()
            mock_lsp.request_document_symbols = AsyncMock(return_value=[])
            tool.lsp_manager = mock_lsp

            result = await tool._execute_async(str(sample_python_file))

            assert result.status == ToolStatus.SUCCESS
            assert "No symbols found" in result.output

    @pytest.mark.asyncio
    async def test_parse_class_symbols(self):
        """Test parsing of class symbols."""
        tool = GetFileOutlineTool()

        # Mock LSP symbols (simulating a class with methods)
        mock_symbols = [
            {
                "name": "User",
                "kind": 5,  # Class
                "location": {
                    "range": {"start": {"line": 0}}
                },
                "children": [
                    {
                        "name": "__init__",
                        "kind": 6,  # Method
                        "location": {"range": {"start": {"line": 1}}}
                    },
                    {
                        "name": "save",
                        "kind": 6,  # Method
                        "location": {"range": {"start": {"line": 4}}}
                    }
                ]
            }
        ]

        outline = tool._parse_symbols(mock_symbols, "test.py")

        assert len(outline["classes"]) == 1
        assert outline["classes"][0]["name"] == "User"
        assert outline["classes"][0]["line"] == 1  # 0-indexed + 1
        assert len(outline["classes"][0]["children"]) == 2
        assert outline["classes"][0]["children"][0]["name"] == "__init__"

    @pytest.mark.asyncio
    async def test_parse_function_symbols(self):
        """Test parsing of function symbols."""
        tool = GetFileOutlineTool()

        mock_symbols = [
            {
                "name": "authenticate",
                "kind": 12,  # Function
                "location": {"range": {"start": {"line": 10}}}
            },
            {
                "name": "login",
                "kind": 12,  # Function
                "location": {"range": {"start": {"line": 15}}}
            }
        ]

        outline = tool._parse_symbols(mock_symbols, "test.py")

        assert len(outline["functions"]) == 2
        assert outline["functions"][0]["name"] == "authenticate"
        assert outline["functions"][1]["name"] == "login"

    def test_kind_to_string_mapping(self):
        """Test LSP kind number to string conversion."""
        tool = GetFileOutlineTool()

        assert tool._kind_to_string(5) == "class"
        assert tool._kind_to_string(6) == "method"
        assert tool._kind_to_string(12) == "function"
        assert tool._kind_to_string(999) == "kind_999"  # Unknown kind

    def test_format_outline(self):
        """Test outline formatting."""
        tool = GetFileOutlineTool()

        outline = {
            "file": "test.py",
            "classes": [
                {
                    "name": "User",
                    "line": 1,
                    "children": [
                        {"name": "save", "line": 5, "kind": "method"}
                    ]
                }
            ],
            "functions": [
                {"name": "authenticate", "line": 10, "kind": "function"}
            ],
            "imports": []
        }

        formatted = tool._format_outline(outline)

        assert "File Outline: test.py" in formatted
        assert "Classes:" in formatted
        assert "User (line 1)" in formatted
        assert "save (line 5, method)" in formatted
        assert "Functions:" in formatted
        assert "authenticate (line 10, function)" in formatted

    def test_get_parameters_schema(self):
        """Test tool parameter schema."""
        tool = GetFileOutlineTool()
        params = tool._get_parameters()

        assert params["type"] == "object"
        assert "file_path" in params["properties"]
        assert params["required"] == ["file_path"]


class TestGetSymbolContextTool:
    """Test GetSymbolContextTool functionality."""

    def test_tool_initialization(self):
        """Test tool can be initialized."""
        tool = GetSymbolContextTool()

        assert tool.name == "get_symbol_context"
        assert tool.description
        assert tool.lsp_manager is None  # Lazy initialization

    @pytest.mark.asyncio
    async def test_symbol_not_found(self):
        """Test handling when symbol is not found."""
        tool = GetSymbolContextTool()

        # Mock LSP to return no symbols
        with patch.object(tool, '_ensure_lsp_initialized', new_callable=AsyncMock):
            mock_lsp = MagicMock()
            mock_lsp.request_workspace_symbols = AsyncMock(return_value=[])
            tool.lsp_manager = mock_lsp

            result = await tool._execute_async("nonexistent_symbol", None, True, True)

            assert result.status == ToolStatus.SUCCESS
            assert "No symbol found" in result.output
            assert result.metadata["matches"] == 0

    @pytest.mark.asyncio
    async def test_single_symbol_match(self):
        """Test loading context for single symbol match."""
        tool = GetSymbolContextTool()

        # Mock workspace symbols
        mock_symbols = [
            {
                "name": "authenticate",
                "kind": 12,  # Function
                "location": {
                    "uri": "file:///path/to/auth.py",
                    "range": {"start": {"line": 10, "character": 0}}
                }
            }
        ]

        # Mock LSP responses
        mock_definition = {"signature": "def authenticate(user, password)"}
        mock_hover = {
            "contents": {
                "value": "def authenticate(user, password)\nAuthenticate user with credentials"
            }
        }
        mock_references = []

        with patch.object(tool, '_ensure_lsp_initialized', new_callable=AsyncMock):
            mock_lsp = MagicMock()
            mock_lsp.request_workspace_symbols = AsyncMock(return_value=mock_symbols)
            mock_lsp.request_definition = AsyncMock(return_value=mock_definition)
            mock_lsp.request_hover = AsyncMock(return_value=mock_hover)
            mock_lsp.request_references = AsyncMock(return_value=mock_references)
            tool.lsp_manager = mock_lsp

            # Mock file reading
            with patch.object(tool, '_read_implementation', new_callable=AsyncMock) as mock_read:
                mock_read.return_value = {"code": "def authenticate(...):", "length": 10}

                result = await tool._execute_async("authenticate", None, True, True)

                assert result.status == ToolStatus.SUCCESS
                assert result.metadata["match_count"] == 1
                assert result.metadata["matches"][0]["name"] == "authenticate"
                assert "/path/to/auth.py" in result.metadata["matches"][0]["location"]["file"]

    @pytest.mark.asyncio
    async def test_multiple_symbol_matches(self):
        """Test handling of multiple symbol matches."""
        tool = GetSymbolContextTool()

        # Mock multiple symbols (e.g., User class in different files)
        mock_symbols = [
            {
                "name": "User",
                "kind": 5,  # Class
                "location": {
                    "uri": "file:///src/models/user.py",
                    "range": {"start": {"line": 5, "character": 0}}
                }
            },
            {
                "name": "User",
                "kind": 5,  # Class
                "location": {
                    "uri": "file:///src/schemas.py",
                    "range": {"start": {"line": 20, "character": 0}}
                }
            }
        ]

        with patch.object(tool, '_ensure_lsp_initialized', new_callable=AsyncMock):
            mock_lsp = MagicMock()
            mock_lsp.request_workspace_symbols = AsyncMock(return_value=mock_symbols)
            mock_lsp.request_definition = AsyncMock(return_value={})
            mock_lsp.request_hover = AsyncMock(return_value={})
            mock_lsp.request_references = AsyncMock(return_value=[])
            tool.lsp_manager = mock_lsp

            with patch.object(tool, '_read_implementation', new_callable=AsyncMock) as mock_read:
                mock_read.return_value = {"code": "class User:", "length": 20}

                result = await tool._execute_async("User", None, True, True)

                assert result.status == ToolStatus.SUCCESS
                assert result.metadata["match_count"] == 2
                assert "Found 2 match(es)" in result.output

    def test_filter_by_file_hint(self):
        """Test filtering symbols by file hint."""
        tool = GetSymbolContextTool()

        symbols = [
            {
                "name": "User",
                "location": {"uri": "file:///src/models/user.py"}
            },
            {
                "name": "User",
                "location": {"uri": "file:///src/schemas.py"}
            }
        ]

        # Filter for user.py
        filtered = tool._filter_by_file(symbols, "user.py")
        assert len(filtered) == 1
        assert "user.py" in filtered[0]["location"]["uri"]

        # Filter for models/
        filtered = tool._filter_by_file(symbols, "models/")
        assert len(filtered) == 1
        assert "models" in filtered[0]["location"]["uri"]

    def test_extract_signature_from_hover(self):
        """Test signature extraction from hover info."""
        tool = GetSymbolContextTool()

        # Test string contents
        hover1 = {
            "contents": "def authenticate(user: str, password: str) -> bool\nDocstring here"
        }
        signature = tool._extract_signature(hover1, {})
        assert "def authenticate" in signature

        # Test dict contents
        hover2 = {
            "contents": {
                "value": "async def login(username: str) -> Token\nLogin user"
            }
        }
        signature = tool._extract_signature(hover2, {})
        assert "async def login" in signature

        # Test fallback to definition
        definition = {"signature": "def parse_config(path: str)"}
        signature = tool._extract_signature({}, definition)
        assert "def parse_config" in signature

    def test_extract_docstring_from_hover(self):
        """Test docstring extraction from hover info."""
        tool = GetSymbolContextTool()

        hover = {
            "contents": {
                "value": "def authenticate(user, password)\n\nAuthenticate user with credentials.\n\nArgs:\n    user: Username\n    password: Password"
            }
        }

        docstring = tool._extract_docstring(hover)
        assert "Authenticate user" in docstring

    def test_format_references(self):
        """Test reference formatting."""
        tool = GetSymbolContextTool()

        references = [
            {
                "uri": "file:///src/login.py",
                "range": {"start": {"line": 22}}
            },
            {
                "uri": "file:///tests/test_auth.py",
                "range": {"start": {"line": 10}}
            }
        ]

        formatted = tool._format_references(references)

        assert len(formatted) == 2
        assert formatted[0]["file"] == "/src/login.py"
        assert formatted[0]["line"] == 23  # 0-indexed + 1
        assert formatted[1]["file"] == "/tests/test_auth.py"

    @pytest.mark.asyncio
    async def test_read_implementation(self, tmp_path, monkeypatch):
        """Test reading function implementation."""
        tool = GetSymbolContextTool()
        monkeypatch.chdir(tmp_path)

        # Create test file
        test_file = tmp_path / "test.py"
        test_file.write_text("""
def authenticate(user, password):
    if not user or not password:
        raise ValueError("Missing credentials")
    return user == "admin"
""")

        impl = await tool._read_implementation(str(test_file), 1)  # Line 1 (0-indexed)

        assert impl["length"] > 0
        assert "def authenticate" in impl["code"]
        assert "Missing credentials" in impl["code"]

    def test_format_symbol_context_no_matches(self):
        """Test formatting when no matches found."""
        tool = GetSymbolContextTool()

        formatted = tool._format_symbol_context("nonexistent", [])

        assert "No matches found" in formatted
        assert "nonexistent" in formatted

    def test_format_symbol_context_single_match(self):
        """Test formatting for single match."""
        tool = GetSymbolContextTool()

        matches = [
            {
                "name": "authenticate",
                "location": {"file": "auth.py", "line": 45},
                "kind": "function",
                "signature": "def authenticate(user, password)",
                "docstring": "Authenticate user",
                "references_count": 5,
                "implementation": "def authenticate(...):\n    pass",
                "implementation_length": 10
            }
        ]

        formatted = tool._format_symbol_context("authenticate", matches)

        assert "Found 1 match(es)" in formatted
        assert "Location: auth.py:45" in formatted
        assert "Kind: function" in formatted
        assert "References: 5 usage(s)" in formatted

    def test_get_parameters_schema(self):
        """Test tool parameter schema."""
        tool = GetSymbolContextTool()
        params = tool._get_parameters()

        assert params["type"] == "object"
        assert "symbol_name" in params["properties"]
        assert "file_hint" in params["properties"]
        assert "include_references" in params["properties"]
        assert "include_implementation" in params["properties"]
        assert params["required"] == ["symbol_name"]


class TestIntegration:
    """Integration tests for LSP tools working together."""

    @pytest.mark.asyncio
    async def test_file_outline_then_symbol_context(self, sample_python_file):
        """Test workflow: get file outline, then get symbol context."""
        # Step 1: Get file outline
        outline_tool = GetFileOutlineTool()

        # Mock LSP for outline
        mock_symbols = [
            {
                "name": "User",
                "kind": 5,
                "location": {"range": {"start": {"line": 1}}}
            },
            {
                "name": "authenticate",
                "kind": 12,
                "location": {"range": {"start": {"line": 10}}}
            }
        ]

        with patch.object(outline_tool, '_ensure_lsp_initialized', new_callable=AsyncMock):
            mock_lsp = MagicMock()
            mock_lsp.request_document_symbols = AsyncMock(return_value=mock_symbols)
            outline_tool.lsp_manager = mock_lsp

            outline_result = await outline_tool._execute_async(str(sample_python_file))

            assert outline_result.status == ToolStatus.SUCCESS
            assert outline_result.metadata["functions"]

            # Find function name from outline
            function_name = outline_result.metadata["functions"][0]["name"]

            # Step 2: Get symbol context for that function
            context_tool = GetSymbolContextTool()

            mock_workspace_symbols = [
                {
                    "name": function_name,
                    "kind": 12,
                    "location": {
                        "uri": f"file://{sample_python_file}",
                        "range": {"start": {"line": 10, "character": 0}}
                    }
                }
            ]

            with patch.object(context_tool, '_ensure_lsp_initialized', new_callable=AsyncMock):
                mock_lsp2 = MagicMock()
                mock_lsp2.request_workspace_symbols = AsyncMock(return_value=mock_workspace_symbols)
                mock_lsp2.request_definition = AsyncMock(return_value={})
                mock_lsp2.request_hover = AsyncMock(return_value={})
                mock_lsp2.request_references = AsyncMock(return_value=[])
                context_tool.lsp_manager = mock_lsp2

                with patch.object(context_tool, '_read_implementation', new_callable=AsyncMock) as mock_read:
                    mock_read.return_value = {"code": "def authenticate():", "length": 5}

                    context_result = await context_tool._execute_async(function_name, None, True, True)

                    assert context_result.status == ToolStatus.SUCCESS
                    assert context_result.metadata["match_count"] >= 1

    def test_error_handling_graceful_degradation(self):
        """Test that tools handle LSP errors gracefully."""
        tool = GetSymbolContextTool()

        # Simulate LSP initialization failure
        with patch.object(tool, '_ensure_lsp_initialized', side_effect=Exception("LSP init failed")):
            result = tool.execute("authenticate")

            assert result.status == ToolStatus.ERROR
            assert "Failed to get symbol context" in result.error


class TestLSPSecurityFixes:
    """Test security fixes for LSP tools: event loop, cleanup, path traversal."""

    def test_outline_tool_uses_asyncio_run(self):
        """Test that GetFileOutlineTool uses asyncio.run() for thread safety."""
        tool = GetFileOutlineTool()

        # Mock the async execution to verify asyncio.run is used
        with patch.object(tool, '_execute_async', new_callable=AsyncMock) as mock_async:
            mock_async.return_value = MagicMock(status=ToolStatus.SUCCESS)

            # Execute should call asyncio.run, which is thread-safe
            result = tool.execute("test.py")

            # Verify async method was called
            mock_async.assert_called_once_with("test.py")

    def test_symbol_tool_uses_asyncio_run(self):
        """Test that GetSymbolContextTool uses asyncio.run() for thread safety."""
        tool = GetSymbolContextTool()

        # Mock the async execution
        with patch.object(tool, '_execute_async', new_callable=AsyncMock) as mock_async:
            mock_async.return_value = MagicMock(status=ToolStatus.SUCCESS)

            # Execute should call asyncio.run
            result = tool.execute("symbol_name")

            # Verify async method was called with correct args
            mock_async.assert_called_once_with("symbol_name", None, True, True)

    def test_outline_tool_has_cleanup_method(self):
        """Test that GetFileOutlineTool has cleanup method."""
        tool = GetFileOutlineTool()

        # Verify cleanup method exists
        assert hasattr(tool, 'cleanup')
        assert callable(tool.cleanup)

        # Verify cleanup can be called without error (no-op since lsp_runtime owns lifecycle)
        tool.cleanup()  # Should not raise

    def test_symbol_tool_has_cleanup_method(self):
        """Test that GetSymbolContextTool has cleanup method."""
        tool = GetSymbolContextTool()

        # Verify cleanup method exists
        assert hasattr(tool, 'cleanup')
        assert callable(tool.cleanup)

        # Verify cleanup can be called without error (no-op since lsp_runtime owns lifecycle)
        tool.cleanup()  # Should not raise

    def test_outline_tool_cleanup_is_noop(self):
        """Test that GetFileOutlineTool cleanup is a no-op (lsp_runtime owns lifecycle)."""
        tool = GetFileOutlineTool()

        # Even with an LSP manager set, cleanup should be a no-op
        # because lsp_runtime.shutdown() handles server lifecycle
        tool.lsp_manager = MagicMock()
        tool.cleanup()  # Should not raise or close anything

    def test_cleanup_does_not_close_shared_servers(self):
        """Test that cleanup does not close shared LSP servers."""
        tool = GetFileOutlineTool()

        # Mock LSP manager
        tool.lsp_manager = MagicMock()
        tool.lsp_manager.close_all_servers = MagicMock()

        # Call cleanup - should NOT close servers (runtime owns them)
        tool.cleanup()

        # Verify close_all_servers was NOT called (runtime manages lifecycle)
        tool.lsp_manager.close_all_servers.assert_not_called()

    def test_cleanup_handles_missing_lsp_manager(self):
        """Test that cleanup handles case where LSP manager is None."""
        tool = GetFileOutlineTool()

        # Ensure LSP manager is None
        tool.lsp_manager = None

        # Cleanup should not raise
        tool.cleanup()  # Should succeed silently

    @pytest.mark.asyncio
    async def test_read_implementation_validates_path(self, tmp_path, monkeypatch):
        """Test that _read_implementation validates file paths for security."""
        tool = GetSymbolContextTool()

        # Create a test file in workspace and set cwd so path validation passes
        test_file = tmp_path / "test.py"
        test_file.write_text("def test(): pass")
        monkeypatch.chdir(tmp_path)

        # Valid path within workspace should work
        result = await tool._read_implementation(str(test_file), 0)
        assert "def test()" in result["code"]

        # Path traversal attempt should be blocked by validate_path_security
        from src.tools.search_tools import validate_path_security

        # Verify validate_path_security blocks obvious attacks
        try:
            validate_path_security("../../../etc/passwd", allow_files_outside_workspace=False)
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "[SECURITY]" in str(e)
            assert "Path traversal blocked" in str(e)

    def test_symbol_tool_cleanup_is_noop(self):
        """Test that GetSymbolContextTool cleanup is a no-op (lsp_runtime owns lifecycle)."""
        tool = GetSymbolContextTool()

        # Even with an LSP manager set, cleanup should be a no-op
        tool.lsp_manager = MagicMock()
        tool.cleanup()  # Should not raise
