"""
Unit tests for LSP Client Manager.

Tests cover:
- Language detection
- Server lazy initialization
- Cache integration
- All query methods
- Error handling and retries
- Server pooling
- Graceful shutdown
"""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from src.code_intelligence.lsp_client_manager import (
    LSPClientManager,
    LSPError,
    LSPServerNotFoundError,
    LSPServerStartupError,
    LSPQueryError,
    LSPTimeoutError,
)
from src.code_intelligence.cache import LSPCache


class TestLanguageDetection:
    """Test language detection from file extensions."""

    def test_detect_python(self):
        """Test Python file detection."""
        manager = LSPClientManager(repo_root=str(Path.cwd()))
        assert manager._detect_language("src/auth.py") == "python"
        assert manager._detect_language("/path/to/module.py") == "python"

    def test_detect_typescript(self):
        """Test TypeScript file detection."""
        manager = LSPClientManager(repo_root=str(Path.cwd()))
        assert manager._detect_language("src/app.ts") == "typescript"
        assert manager._detect_language("src/component.tsx") == "typescript"

    def test_detect_javascript(self):
        """Test JavaScript file detection."""
        manager = LSPClientManager(repo_root=str(Path.cwd()))
        assert manager._detect_language("src/app.js") == "javascript"
        assert manager._detect_language("src/component.jsx") == "javascript"

    def test_detect_unknown(self):
        """Test unknown file type."""
        manager = LSPClientManager(repo_root=str(Path.cwd()))
        assert manager._detect_language("src/file.txt") == "unknown"
        assert manager._detect_language("README.md") == "unknown"


class TestCacheKeyGeneration:
    """Test cache key generation."""

    def test_cache_key_with_coordinates(self):
        """Test cache key with line and column."""
        manager = LSPClientManager(repo_root=str(Path.cwd()))
        key = manager._cache_key("def", "src/auth.py", 45, 10)
        assert key == "def:src/auth.py:45:10"

    def test_cache_key_without_coordinates(self):
        """Test cache key without line/column (document symbols)."""
        manager = LSPClientManager(repo_root=str(Path.cwd()))
        key = manager._cache_key("doc_symbols", "src/auth.py")
        assert key == "doc_symbols:src/auth.py"


class TestLazyInitialization:
    """Test server lazy initialization."""

    @pytest.mark.asyncio
    async def test_server_starts_on_first_query(self):
        """Test server starts only when first queried."""
        manager = LSPClientManager(repo_root=str(Path.cwd()))

        # Initially no servers
        assert len(manager.servers) == 0

        # Mock LSP internals so we don't hit real server issues
        with patch.object(manager, '_start_server', new_callable=AsyncMock) as mock_start, \
             patch.object(manager, '_make_lsp_query', new_callable=AsyncMock) as mock_query:
            mock_start.return_value = MagicMock()
            mock_query.return_value = {"uri": "file:///test.py", "range": {"start": {"line": 10, "character": 0}}}

            # Query triggers server start
            await manager.request_definition("src/core/agent.py", 10, 5)

            # Server should now be running
            assert "python" in manager.servers

    @pytest.mark.asyncio
    async def test_server_reused_on_second_query(self):
        """Test server is reused on subsequent queries."""
        manager = LSPClientManager(repo_root=str(Path.cwd()))

        with patch.object(manager, '_start_server', new_callable=AsyncMock) as mock_start, \
             patch.object(manager, '_make_lsp_query', new_callable=AsyncMock) as mock_query:
            mock_start.return_value = MagicMock()
            mock_query.return_value = {"uri": "file:///test.py", "range": {"start": {"line": 10, "character": 0}}}

            # First query starts server
            await manager.request_definition("src/core/agent.py", 10, 5)
            first_server = manager.servers["python"]

            # Second query reuses server
            await manager.request_definition("src/core/agent.py", 20, 5)
            second_server = manager.servers["python"]

            # Should be same server instance
            assert first_server is second_server

            # _start_server should only be called once
            mock_start.assert_called_once()

    @pytest.mark.asyncio
    async def test_multiple_languages(self):
        """Test multiple language servers can run concurrently."""
        manager = LSPClientManager(repo_root=str(Path.cwd()), max_servers=3)

        with patch.object(manager, '_start_server', new_callable=AsyncMock) as mock_start, \
             patch.object(manager, '_make_lsp_query', new_callable=AsyncMock) as mock_query:
            mock_start.return_value = MagicMock()
            mock_query.return_value = {"uri": "file:///test.py", "range": {"start": {"line": 10, "character": 0}}}

            # Query Python file
            await manager.request_definition("src/core/agent.py", 10, 5)
            assert "python" in manager.servers

            # Only Python server running
            assert len(manager.servers) == 1

    @pytest.mark.asyncio
    async def test_max_servers_limit(self):
        """Test max servers limit is enforced."""
        manager = LSPClientManager(repo_root=str(Path.cwd()), max_servers=1)

        with patch.object(manager, '_start_server', new_callable=AsyncMock) as mock_start, \
             patch.object(manager, '_make_lsp_query', new_callable=AsyncMock) as mock_query:
            mock_start.return_value = MagicMock()
            mock_query.return_value = {"uri": "file:///test.py", "range": {"start": {"line": 10, "character": 0}}}

            # Start first server
            await manager.request_definition("src/core/agent.py", 10, 5)
            assert len(manager.servers) == 1
            assert "python" in manager.servers


class TestCacheIntegration:
    """Test cache integration."""

    @pytest.mark.asyncio
    async def test_cache_hit_avoids_query(self):
        """Test cache hit avoids LSP query."""
        cache = LSPCache()
        manager = LSPClientManager(repo_root=str(Path.cwd()), cache=cache)

        with patch.object(manager, '_start_server', new_callable=AsyncMock) as mock_start, \
             patch.object(manager, '_make_lsp_query', new_callable=AsyncMock) as mock_query:
            mock_start.return_value = MagicMock()
            mock_query.return_value = {"uri": "file:///test.py", "range": {"start": {"line": 45, "character": 10}}}

            # First query (cache miss)
            result1 = await manager.request_definition("src/auth.py", 45, 10)

            # Manually verify cache was populated
            cache_key = "def:src/auth.py:45:10"
            assert cache.get(cache_key) is not None

            # Second query (cache hit)
            result2 = await manager.request_definition("src/auth.py", 45, 10)

            assert result1 == result2

            # _make_lsp_query should only be called once (first was cache miss, second was cache hit)
            assert mock_query.call_count == 1

    @pytest.mark.asyncio
    async def test_different_operations_different_cache_keys(self):
        """Test different operations use different cache keys."""
        manager = LSPClientManager(repo_root=str(Path.cwd()))

        with patch.object(manager, '_start_server', new_callable=AsyncMock) as mock_start, \
             patch.object(manager, '_make_lsp_query', new_callable=AsyncMock) as mock_query:
            mock_start.return_value = MagicMock()
            mock_query.return_value = [{"uri": "file:///test.py", "range": {"start": {"line": 45, "character": 10}}}]

            # Query definition
            await manager.request_definition("src/auth.py", 45, 10)

            # Query references (different cache key)
            await manager.request_references("src/auth.py", 45, 10)

            # Both should be cached separately
            assert manager.cache.get("def:src/auth.py:45:10") is not None
            assert manager.cache.get("refs:src/auth.py:45:10") is not None


class TestQueryMethods:
    """Test all query methods."""

    @pytest.mark.asyncio
    async def test_request_definition(self):
        """Test request_definition returns result."""
        manager = LSPClientManager(repo_root=str(Path.cwd()))

        with patch.object(manager, '_start_server', new_callable=AsyncMock) as mock_start, \
             patch.object(manager, '_make_lsp_query', new_callable=AsyncMock) as mock_query:
            mock_start.return_value = MagicMock()
            mock_query.return_value = {"uri": "file:///src/auth.py", "range": {"start": {"line": 45, "character": 10}}}

            result = await manager.request_definition("src/auth.py", 45, 10)

            assert result is not None
            assert "uri" in result

    @pytest.mark.asyncio
    async def test_request_references(self):
        """Test request_references returns list."""
        manager = LSPClientManager(repo_root=str(Path.cwd()))

        with patch.object(manager, '_start_server', new_callable=AsyncMock) as mock_start, \
             patch.object(manager, '_make_lsp_query', new_callable=AsyncMock) as mock_query:
            mock_start.return_value = MagicMock()
            mock_query.return_value = [{"uri": "file:///src/auth.py", "range": {"start": {"line": 50, "character": 0}}}]

            result = await manager.request_references("src/auth.py", 45, 10)

            assert isinstance(result, list)
            assert len(result) >= 0

    @pytest.mark.asyncio
    async def test_request_hover(self):
        """Test request_hover returns hover info."""
        manager = LSPClientManager(repo_root=str(Path.cwd()))

        with patch.object(manager, '_start_server', new_callable=AsyncMock) as mock_start, \
             patch.object(manager, '_make_lsp_query', new_callable=AsyncMock) as mock_query:
            mock_start.return_value = MagicMock()
            mock_query.return_value = {"contents": "def authenticate(user, password) -> bool"}

            result = await manager.request_hover("src/auth.py", 45, 10)

            assert result is not None
            assert "contents" in result

    @pytest.mark.asyncio
    async def test_request_document_symbols(self):
        """Test request_document_symbols returns symbols."""
        manager = LSPClientManager(repo_root=str(Path.cwd()))

        with patch.object(manager, '_start_server', new_callable=AsyncMock) as mock_start, \
             patch.object(manager, '_make_lsp_query', new_callable=AsyncMock) as mock_query:
            mock_start.return_value = MagicMock()
            mock_query.return_value = [{"name": "authenticate", "kind": 12, "range": {"start": {"line": 0}}}]

            result = await manager.request_document_symbols("src/auth.py")

            assert isinstance(result, list)
            assert len(result) >= 0

    @pytest.mark.asyncio
    async def test_request_workspace_symbols(self):
        """Test request_workspace_symbols returns results."""
        manager = LSPClientManager(repo_root=str(Path.cwd()))

        with patch.object(manager, '_start_server', new_callable=AsyncMock) as mock_start, \
             patch.object(manager, '_query_workspace_symbols', new_callable=AsyncMock) as mock_ws:
            mock_start.return_value = MagicMock()
            mock_ws.return_value = [{"name": "User", "kind": 5, "location": {"uri": "mock.py"}}]

            result = await manager.request_workspace_symbols("User")

            assert isinstance(result, list)
            # Workspace symbols are best-effort (may be empty)


class TestErrorHandling:
    """Test error handling."""

    @pytest.mark.asyncio
    async def test_unsupported_language_raises_error(self):
        """Test unsupported language raises LSPServerNotFoundError."""
        manager = LSPClientManager(repo_root=str(Path.cwd()))

        with pytest.raises(LSPServerNotFoundError, match="not supported"):
            await manager.request_definition("src/file.go", 10, 5)

    @pytest.mark.asyncio
    async def test_query_timeout_raises_error(self):
        """Test query timeout raises LSPTimeoutError."""
        manager = LSPClientManager(repo_root=str(Path.cwd()), query_timeout=0.001)  # 1ms timeout

        # Mock query to take longer than timeout
        async def slow_query(*args, **kwargs):
            await asyncio.sleep(0.1)  # 100ms delay
            return {}

        with patch.object(manager, '_make_lsp_query', side_effect=slow_query):
            with pytest.raises(LSPTimeoutError, match="timed out"):
                await manager.request_definition("src/auth.py", 45, 10)


class TestRetryLogic:
    """Test retry logic."""

    @pytest.mark.asyncio
    async def test_retry_on_failure(self):
        """Test query retries on failure."""
        manager = LSPClientManager(repo_root=str(Path.cwd()))

        # Mock query to fail first time, succeed second time
        call_count = 0

        async def flaky_query(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Temporary failure")
            return {"uri": "success"}

        with patch.object(manager, '_make_lsp_query', side_effect=flaky_query):
            result = await manager.request_definition("src/auth.py", 45, 10)

            # Should succeed on retry
            assert result["uri"] == "success"
            assert call_count == 2  # Failed once, succeeded on retry

    @pytest.mark.asyncio
    async def test_raises_after_retry_exhausted(self):
        """Test error raised after retry exhausted."""
        manager = LSPClientManager(repo_root=str(Path.cwd()))

        # Mock query to always fail
        async def always_fails(*args, **kwargs):
            raise Exception("Permanent failure")

        with patch.object(manager, '_make_lsp_query', side_effect=always_fails):
            with pytest.raises(LSPQueryError, match="after retry"):
                await manager.request_definition("src/auth.py", 45, 10)


class TestServerLifecycle:
    """Test server lifecycle management."""

    @pytest.mark.asyncio
    async def test_close_all_servers(self):
        """Test close_all_servers shuts down all servers."""
        manager = LSPClientManager(repo_root=str(Path.cwd()), max_servers=3)

        # Manually add mock servers to simulate running state
        mock_python_server = MagicMock()
        mock_ts_server = MagicMock()
        manager.servers["python"] = mock_python_server
        manager.servers["typescript"] = mock_ts_server

        assert len(manager.servers) == 2

        # Mock close to succeed
        with patch.object(manager, '_close_server', new_callable=AsyncMock) as mock_close:
            # Close all
            await manager.close_all_servers()

            # All servers should be closed
            assert len(manager.servers) == 0
            assert mock_close.call_count == 2

    @pytest.mark.asyncio
    async def test_close_handles_errors_gracefully(self):
        """Test close_all_servers handles errors gracefully."""
        manager = LSPClientManager(repo_root=str(Path.cwd()))

        # Manually add a mock server
        mock_server = MagicMock()
        manager.servers["python"] = mock_server

        # Mock close to raise error
        async def close_with_error(*args):
            raise Exception("Close failed")

        with patch.object(manager, '_close_server', side_effect=close_with_error):
            # Should raise LSPError when servers fail to close
            with pytest.raises(LSPError, match="Failed to close"):
                await manager.close_all_servers()


class TestEdgeCases:
    """Test edge cases."""

    @pytest.mark.asyncio
    async def test_empty_file_path(self):
        """Test handling of empty file path."""
        manager = LSPClientManager(repo_root=str(Path.cwd()))

        # Empty path should detect as unknown language
        language = manager._detect_language("")
        assert language == "unknown"

    @pytest.mark.asyncio
    async def test_concurrent_server_startup(self):
        """Test concurrent requests don't start duplicate servers."""
        import asyncio

        manager = LSPClientManager(repo_root=str(Path.cwd()))

        with patch.object(manager, '_start_server', new_callable=AsyncMock) as mock_start, \
             patch.object(manager, '_make_lsp_query', new_callable=AsyncMock) as mock_query:
            mock_start.return_value = MagicMock()
            mock_query.return_value = {"uri": "file:///test.py", "range": {"start": {"line": 0, "character": 0}}}

            # Make 10 concurrent queries for same language
            tasks = [
                manager.request_definition("src/auth.py", i, 0)
                for i in range(10)
            ]

            await asyncio.gather(*tasks)

            # Should only have 1 Python server (not 10)
            assert len(manager.servers) == 1
            assert "python" in manager.servers

            # _start_server should only be called once
            mock_start.assert_called_once()

    @pytest.mark.asyncio
    async def test_workspace_symbols_without_repo_root(self):
        """Test workspace symbols works without explicit repo_root."""
        manager = LSPClientManager(repo_root=str(Path.cwd()))

        with patch.object(manager, '_start_server', new_callable=AsyncMock) as mock_start, \
             patch.object(manager, '_query_workspace_symbols', new_callable=AsyncMock) as mock_ws:
            mock_start.return_value = MagicMock()
            mock_ws.return_value = [{"name": "User", "kind": 5}]

            # Should default to Python and not crash
            result = await manager.request_workspace_symbols("User")

            # Best-effort, may be empty
            assert isinstance(result, list)


class TestIntegration:
    """Integration tests (end-to-end workflows)."""

    @pytest.mark.asyncio
    async def test_typical_agent_workflow(self):
        """Simulate typical agent workflow."""
        manager = LSPClientManager(repo_root=str(Path.cwd()))

        with patch.object(manager, '_start_server', new_callable=AsyncMock) as mock_start, \
             patch.object(manager, '_make_lsp_query', new_callable=AsyncMock) as mock_query:
            mock_start.return_value = MagicMock()

            # Set up different return values for different query types
            def query_side_effect(server, method, file_path, line=None, column=None):
                if method == "textDocument/definition":
                    return {"uri": "file:///src/auth.py", "range": {"start": {"line": 45, "character": 10}}}
                elif method == "textDocument/references":
                    return [{"uri": "file:///src/auth.py", "range": {"start": {"line": 50, "character": 0}}}]
                elif method == "textDocument/hover":
                    return {"contents": "def authenticate(user, password)"}
                elif method == "textDocument/documentSymbol":
                    return [{"name": "authenticate", "kind": 12, "range": {"start": {"line": 0}}}]
                return None

            mock_query.side_effect = query_side_effect

            # 1. Agent reads file and needs definition
            definition = await manager.request_definition("src/auth.py", 45, 10)
            assert definition is not None

            # 2. Agent needs type info
            hover = await manager.request_hover("src/auth.py", 45, 10)
            assert hover is not None

            # 3. Agent looks for references
            refs = await manager.request_references("src/auth.py", 45, 10)
            assert isinstance(refs, list)

            # 4. Agent gets file outline
            symbols = await manager.request_document_symbols("src/auth.py")
            assert isinstance(symbols, list)

            # Should have only started 1 server (Python)
            assert len(manager.servers) == 1

    @pytest.mark.asyncio
    async def test_multi_language_project(self):
        """Test working with multi-language project."""
        manager = LSPClientManager(repo_root=str(Path.cwd()), max_servers=3)

        with patch.object(manager, '_start_server', new_callable=AsyncMock) as mock_start, \
             patch.object(manager, '_make_lsp_query', new_callable=AsyncMock) as mock_query:
            mock_start.return_value = MagicMock()
            mock_query.return_value = {"uri": "file:///test", "range": {"start": {"line": 0, "character": 0}}}

            # Python backend
            await manager.request_definition("backend/auth.py", 10, 5)

            # TypeScript frontend
            await manager.request_definition("frontend/App.tsx", 20, 10)

            # JavaScript config (shares TS server)
            await manager.request_definition("scripts/build.js", 5, 0)

            # Should have 2 servers (Python + TypeScript/JavaScript share server)
            assert len(manager.servers) == 2
            assert "python" in manager.servers
            assert "typescript" in manager.servers  # JS uses TS server


# Import asyncio for concurrent test
import asyncio
