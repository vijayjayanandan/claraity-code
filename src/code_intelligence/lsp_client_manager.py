"""
LSP Client Manager - Manages multiple language servers with lazy initialization.

Features:
- Lazy initialization (servers start only when first queried)
- Connection pooling (keeps servers alive between queries)
- Cache integration (checks cache before querying LSP)
- Progress indicators (Rich status display)
- Error handling with retries
- Multi-language support (Python, TypeScript for Phase 1)
"""

import asyncio
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

from src.code_intelligence.cache import LSPCache


# Ensure Python user Scripts directory is in PATH (for jedi-language-server etc.)
# On Windows, pip --user installs scripts to a directory not in system PATH
def _ensure_user_scripts_in_path():
    """Add Python user Scripts directory to PATH if not present."""
    if sys.platform == "win32":
        user_scripts = (
            Path.home()
            / "AppData"
            / "Roaming"
            / "Python"
            / f"Python{sys.version_info.major}{sys.version_info.minor}"
            / "Scripts"
        )
        if user_scripts.exists():
            user_scripts_str = str(user_scripts)
            if user_scripts_str not in os.environ.get("PATH", ""):
                os.environ["PATH"] = user_scripts_str + os.pathsep + os.environ.get("PATH", "")


_ensure_user_scripts_in_path()

# multilspy imports
try:
    from multilspy import LanguageServer
    from multilspy.multilspy_config import Language, MultilspyConfig
    from multilspy.multilspy_logger import MultilspyLogger

    MULTILSPY_AVAILABLE = True
except ImportError:
    MULTILSPY_AVAILABLE = False
    LanguageServer = None
    MultilspyConfig = None
    Language = None
    MultilspyLogger = None


# Custom Exceptions
class LSPError(Exception):
    """Base exception for LSP-related errors."""

    pass


class LSPServerNotFoundError(LSPError):
    """Language server binary not found."""

    pass


class LSPServerStartupError(LSPError):
    """Failed to start language server."""

    pass


class LSPQueryError(LSPError):
    """LSP query failed."""

    pass


class LSPTimeoutError(LSPError):
    """LSP query timed out."""

    pass


class ServerWrapper:
    """
    Wrapper for multilspy LanguageServer that manages lifecycle.

    Keeps the async context manager active and provides access to the server.
    """

    def __init__(self, language: str, lsp_server: Any, repo_root: str):
        self.language = language
        self.lsp_server = lsp_server
        self.repo_root = repo_root
        self._context_manager = None
        self._server_instance = None

    async def __aenter__(self):
        """Start the server."""
        self._context_manager = self.lsp_server.start_server()
        self._server_instance = await self._context_manager.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Stop the server."""
        if self._context_manager:
            await self._context_manager.__aexit__(exc_type, exc_val, exc_tb)

    def get_server(self):
        """Get the active server instance."""
        return self._server_instance

    def get_relative_path(self, absolute_path: str) -> str:
        """Convert absolute path to relative path from repo root."""
        from src.code_intelligence.path_utils import normalize_path

        abs_path = normalize_path(absolute_path)
        repo_root = normalize_path(self.repo_root)

        try:
            return str(abs_path.relative_to(repo_root))
        except ValueError:
            # File is outside repo - return as-is
            return str(abs_path)


class LSPClientManager:
    """
    Manages multiple language servers with lazy initialization.

    Features:
    - Lazy initialization (servers start only when needed)
    - Connection pooling (reuses servers)
    - Cache integration (LSPCache)
    - Progress indicators (Rich)
    - Retry logic (1 retry on failure)
    - Multi-language (Python + TypeScript in Phase 1)
    """

    # Phase 1: Python + TypeScript support
    # TODO: Make configurable via CodeIntelligenceConfig (Component 04)
    SUPPORTED_LANGUAGES = {
        "python": "pyright",
        "typescript": "tsserver",
        "javascript": "tsserver",  # Uses same server as TypeScript
    }

    def __init__(
        self,
        repo_root: str | None = None,
        cache: LSPCache | None = None,
        max_servers: int = 3,
        query_timeout: float = 5.0,
    ):
        """
        Initialize LSP Client Manager.

        Args:
            repo_root: Repository root path (auto-detected if None)
            cache: Optional LSP cache
            max_servers: Maximum concurrent language servers (default: 3)
            query_timeout: Query timeout in seconds (default: 5.0)
        """
        init_start = time.perf_counter()

        # Initialize logger first (needed by _detect_repo_root)
        self.logger = logging.getLogger("code_intelligence.lsp_manager")

        self.repo_root = repo_root or self._detect_repo_root()

        # Log repo_root at init (helps debug path issues)
        from src.code_intelligence.path_utils import normalize_path

        self.logger.info(
            f"LSPClientManager init: repo_root={self.repo_root}, "
            f"normalized={normalize_path(self.repo_root)}"
        )

        self.cache = cache or LSPCache(repo_root=self.repo_root)
        self.max_servers = max_servers
        self.query_timeout = query_timeout

        # Active language servers (lazy initialization)
        self.servers: dict[str, ServerWrapper] = {}  # language -> ServerWrapper instance

        # Server initialization locks (prevent duplicate startup)
        self._server_locks: dict[str, asyncio.Lock] = {}

        # Initialize multilspy logger (if available)
        if MULTILSPY_AVAILABLE:
            self.multilspy_logger = MultilspyLogger()
        else:
            self.multilspy_logger = None
            self.logger.warning("multilspy not available - using mock implementation")

        # [PERF] Log init timing
        init_ms = (time.perf_counter() - init_start) * 1000
        self.logger.debug(f"[PERF] Manager init: {init_ms:.1f}ms")

    async def request_definition(
        self, file_path: str, line: int, column: int
    ) -> dict[str, Any] | None:
        """
        Request symbol definition location.

        Args:
            file_path: Path to file
            line: Line number (0-indexed)
            column: Column number (0-indexed)

        Returns:
            Definition location or None if not found

        Raises:
            LSPServerNotFoundError: Language not supported
            LSPServerStartupError: Failed to start server
            LSPTimeoutError: Query timed out
            LSPQueryError: Query failed

        Example:
            >>> result = await manager.request_definition("src/auth.py", 45, 10)
            >>> print(result)
            {"uri": "src/auth/user.py", "range": {"start": {"line": 45, "character": 4}}}
        """
        # Check cache first
        cache_key = self._cache_key("def", file_path, line, column)
        cached = self.cache.get(cache_key)
        if cached is not None:
            self.logger.debug(f"Cache hit: {cache_key}")
            return cached

        # Query LSP server (propagate LSP errors)
        server = await self._get_server(file_path)

        # Make LSP request (with retry)
        result = await self._query_with_retry(
            server, "textDocument/definition", file_path, line, column
        )

        # Cache result
        self.cache.set(cache_key, result, file_path=file_path)

        return result

    async def request_references(
        self, file_path: str, line: int, column: int
    ) -> list[dict[str, Any]]:
        """
        Request all references to a symbol.

        Args:
            file_path: Path to file
            line: Line number (0-indexed)
            column: Column number (0-indexed)

        Returns:
            list of reference locations (may be empty)

        Example:
            >>> refs = await manager.request_references("src/auth.py", 45, 10)
            >>> print(len(refs))
            5
        """
        # Check cache
        cache_key = self._cache_key("refs", file_path, line, column)
        cached = self.cache.get(cache_key)
        if cached is not None:
            self.logger.debug(f"Cache hit: {cache_key}")
            return cached

        # Query LSP
        try:
            server = await self._get_server(file_path)

            result = await self._query_with_retry(
                server, "textDocument/references", file_path, line, column
            )

            # Cache result
            self.cache.set(cache_key, result or [], file_path=file_path)

            return result or []

        except Exception as e:
            self.logger.error(f"References query failed: {e}")
            raise LSPQueryError(f"Failed to get references: {e}") from e

    async def request_hover(self, file_path: str, line: int, column: int) -> dict[str, Any] | None:
        """
        Request hover information (type signature, docstring).

        Args:
            file_path: Path to file
            line: Line number (0-indexed)
            column: Column number (0-indexed)

        Returns:
            Hover information or None

        Example:
            >>> hover = await manager.request_hover("src/auth.py", 45, 10)
            >>> print(hover["contents"])
            "def authenticate(username: str, password: str) -> Token"
        """
        # Check cache
        cache_key = self._cache_key("hover", file_path, line, column)
        cached = self.cache.get(cache_key)
        if cached is not None:
            self.logger.debug(f"Cache hit: {cache_key}")
            return cached

        # Query LSP
        try:
            server = await self._get_server(file_path)

            result = await self._query_with_retry(
                server, "textDocument/hover", file_path, line, column
            )

            # Cache result
            self.cache.set(cache_key, result, file_path=file_path)

            return result

        except Exception as e:
            self.logger.error(f"Hover query failed: {e}")
            raise LSPQueryError(f"Failed to get hover info: {e}") from e

    async def request_document_symbols(self, file_path: str) -> list[dict[str, Any]]:
        """
        Request document symbols (file outline).

        Args:
            file_path: Path to file

        Returns:
            list of symbols (classes, functions, variables)

        Example:
            >>> symbols = await manager.request_document_symbols("src/auth.py")
            >>> for sym in symbols:
            ...     print(f"{sym['name']} ({sym['kind']})")
            User (class)
            authenticate (function)
        """
        total_start = time.perf_counter()

        # Check cache (no line/column for document symbols)
        cache_key = f"doc_symbols:{file_path}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            total_ms = (time.perf_counter() - total_start) * 1000
            self.logger.debug(
                f"[PERF] request_document_symbols: file={file_path}, "
                f"cache_hit=True, total_ms={total_ms:.1f}"
            )
            return cached

        # Query LSP
        try:
            get_server_start = time.perf_counter()
            server = await self._get_server(file_path)
            get_server_ms = (time.perf_counter() - get_server_start) * 1000

            query_start = time.perf_counter()
            result = await self._query_with_retry(server, "textDocument/documentSymbol", file_path)
            query_ms = (time.perf_counter() - query_start) * 1000

            # Cache result
            self.cache.set(cache_key, result or [], file_path=file_path)

            total_ms = (time.perf_counter() - total_start) * 1000
            self.logger.info(
                f"[PERF] request_document_symbols: file={file_path}, "
                f"cache_hit=False, get_server_ms={get_server_ms:.1f}, "
                f"query_ms={query_ms:.1f}, total_ms={total_ms:.1f}"
            )

            return result or []

        except Exception as e:
            total_ms = (time.perf_counter() - total_start) * 1000
            self.logger.error(f"Document symbols query failed: {e} (total_ms={total_ms:.1f})")
            raise LSPQueryError(f"Failed to get document symbols: {e}") from e

    async def request_workspace_symbols(
        self, query: str, repo_root: str | None = None
    ) -> list[dict[str, Any]]:
        """
        Search for symbols across workspace.

        Note: This is NOT cached (always queries fresh).

        Args:
            query: Symbol name to search for
            repo_root: Repository root (auto-detected if None)

        Returns:
            list of matching symbols

        Example:
            >>> symbols = await manager.request_workspace_symbols("User")
            >>> for sym in symbols:
            ...     print(f"{sym['name']} - {sym['location']['uri']}")
            User - src/models/user.py
            UserSchema - src/schemas.py
        """
        # Workspace symbols are NOT cached (results change as code evolves)

        try:
            # Detect language from repo (use first available server)
            # For now, try Python first, fallback to TypeScript
            language = self._detect_primary_language(repo_root)

            server = await self._get_server_by_language(language)

            result = await self._query_workspace_symbols(server, query)

            return result or []

        except Exception as e:
            self.logger.warning(f"Workspace symbols query failed: {e}")
            # Don't raise - workspace search is best-effort
            return []

    async def close_all_servers(self) -> None:
        """
        Close all active language servers gracefully.

        Called during agent shutdown.

        Raises:
            LSPError: If any servers fail to close (after attempting all)
        """
        self.logger.info(f"Closing {len(self.servers)} language servers...")

        errors = []
        # Iterate over copy to allow safe deletion
        for language, server in list(self.servers.items()):
            try:
                await self._close_server(server)
                # Only remove from dict if closed successfully
                del self.servers[language]
                self.logger.info(f"Closed {language} server")
            except Exception as e:
                self.logger.error(f"Failed to close {language} server: {e}")
                errors.append((language, e))

        if errors:
            # Report errors with details
            error_msg = "; ".join([f"{lang}: {err}" for lang, err in errors])
            self.logger.error(f"Failed to close {len(errors)} servers: {error_msg}")
            raise LSPError(f"Failed to close {len(errors)} servers: {error_msg}")

        self.logger.info("All servers closed successfully")

    # ========== Private Methods ==========

    async def _get_server(self, file_path: str) -> Any:
        """
        Get or start language server for file.

        Args:
            file_path: Path to file

        Returns:
            Language server instance

        Raises:
            LSPServerNotFoundError: Language not supported
            LSPServerStartupError: Failed to start server
        """
        # Detect language
        language = self._detect_language(file_path)

        if language not in self.SUPPORTED_LANGUAGES:
            raise LSPServerNotFoundError(
                f"Language '{language}' not supported. "
                f"Supported: {list(self.SUPPORTED_LANGUAGES.keys())}"
            )

        # Normalize JavaScript to TypeScript (they share tsserver)
        if language == "javascript":
            language = "typescript"

        return await self._get_server_by_language(language)

    async def _get_server_by_language(self, language: str) -> Any:
        """Get or start server for specific language."""
        get_server_start = time.perf_counter()

        # Get event loop identity for debugging async issues
        try:
            loop = asyncio.get_running_loop()
            loop_id = id(loop)
        except RuntimeError:
            loop_id = None

        # Check if server already running
        if language in self.servers:
            wrapper = self.servers[language]
            get_server_ms = (time.perf_counter() - get_server_start) * 1000
            self.logger.debug(
                f"[PERF] Server reuse: language={language}, "
                f"reused=True, wrapper_id={id(wrapper)}, "
                f"loop_id={loop_id}, get_server_ms={get_server_ms:.1f}"
            )
            return wrapper

        # Check server limit
        if len(self.servers) >= self.max_servers:
            self.logger.warning(
                f"Max servers ({self.max_servers}) reached. Active: {list(self.servers.keys())}"
            )
            # For now, raise error. Later: could implement LRU eviction
            raise LSPServerStartupError(f"Max servers ({self.max_servers}) already running")

        # Use lock to prevent duplicate startup
        if language not in self._server_locks:
            self._server_locks[language] = asyncio.Lock()

        async with self._server_locks[language]:
            # Check again (another task may have started it)
            if language in self.servers:
                wrapper = self.servers[language]
                get_server_ms = (time.perf_counter() - get_server_start) * 1000
                self.logger.debug(
                    f"[PERF] Server reuse (after lock): language={language}, "
                    f"reused=True, wrapper_id={id(wrapper)}, "
                    f"loop_id={loop_id}, get_server_ms={get_server_ms:.1f}"
                )
                return wrapper

            # Start server
            self.logger.info(f"Starting {language} language server...")
            startup_start = time.perf_counter()

            try:
                server = await self._start_server(language)
                self.servers[language] = server

                startup_ms = (time.perf_counter() - startup_start) * 1000
                get_server_ms = (time.perf_counter() - get_server_start) * 1000
                self.logger.info(
                    f"[PERF] Server started: language={language}, "
                    f"reused=False, wrapper_id={id(server)}, "
                    f"loop_id={loop_id}, startup_ms={startup_ms:.1f}, "
                    f"get_server_ms={get_server_ms:.1f}"
                )
                return server

            except Exception as e:
                self.logger.error(f"Failed to start {language} server: {e}")
                raise LSPServerStartupError(f"Failed to start {language} server: {e}") from e

    async def _start_server(self, language: str) -> ServerWrapper:
        """
        Start language server process using multilspy.

        Args:
            language: Language name

        Returns:
            ServerWrapper instance with active LSP server

        Raises:
            LSPServerStartupError: Failed to start server
        """
        if not MULTILSPY_AVAILABLE:
            # Fallback to mock if multilspy not available
            self.logger.warning(f"[MOCK] Starting {language} server (multilspy not available)")
            await asyncio.sleep(0.1)
            return MockLanguageServer(language)

        try:
            self.logger.info(f"Starting {language} language server...")

            # Map our language names to multilspy Language enum
            language_map = {
                "python": Language.PYTHON,
                "typescript": Language.TYPESCRIPT,
                "javascript": Language.JAVASCRIPT,
            }

            if language not in language_map:
                raise LSPServerStartupError(f"Language {language} not supported")

            # Create multilspy config
            config = MultilspyConfig.from_dict(
                {
                    "code_language": language_map[language],
                    "trace_lsp_communication": False,  # Set to True for debugging
                }
            )

            # Create language server
            lsp_server = LanguageServer.create(
                config=config, logger=self.multilspy_logger, repository_root_path=self.repo_root
            )

            # Wrap in ServerWrapper to manage async context
            wrapper = ServerWrapper(language, lsp_server, self.repo_root)

            # Start the server (enters async context)
            await wrapper.__aenter__()

            self.logger.info(f"{language} server started successfully")
            return wrapper

        except Exception as e:
            self.logger.error(f"Failed to start {language} server: {e}")
            raise LSPServerStartupError(f"Failed to start {language} server: {e}") from e

    async def _query_with_retry(
        self,
        server: Any,
        method: str,
        file_path: str,
        line: int | None = None,
        column: int | None = None,
    ) -> Any:
        """
        Query LSP server with retry logic.

        Args:
            server: Language server instance
            method: LSP method name
            file_path: File path
            line: Optional line number
            column: Optional column number

        Returns:
            Query result

        Raises:
            LSPTimeoutError: Query timed out
            LSPQueryError: Query failed after retry
        """
        for attempt in range(2):  # Try twice
            try:
                # Make query with timeout
                result = await asyncio.wait_for(
                    self._make_lsp_query(server, method, file_path, line, column),
                    timeout=self.query_timeout,
                )
                return result

            except asyncio.TimeoutError:
                if attempt == 0:
                    self.logger.warning(f"Query timeout, retrying... ({method})")
                    continue
                else:
                    raise LSPTimeoutError(f"Query timed out after {self.query_timeout}s")

            except Exception as e:
                if attempt == 0:
                    self.logger.warning(f"Query failed, retrying: {e}")
                    continue
                else:
                    raise LSPQueryError(f"Query failed after retry: {e}") from e

    async def _make_lsp_query(
        self,
        server: Any,
        method: str,
        file_path: str,
        line: int | None = None,
        column: int | None = None,
    ) -> Any:
        """
        Make LSP query using multilspy.

        Args:
            server: ServerWrapper or MockLanguageServer instance
            method: LSP method name
            file_path: Absolute file path
            line: Line number (0-indexed)
            column: Column number (0-indexed)

        Returns:
            Query result (format depends on method)
        """
        # Handle mock server (fallback)
        if isinstance(server, MockLanguageServer):
            self.logger.debug(f"[MOCK] Query: {method} at {file_path}:{line}:{column}")
            await asyncio.sleep(0.05)
            if method == "textDocument/definition":
                return {"uri": file_path, "range": {"start": {"line": line, "character": column}}}
            elif method == "textDocument/references":
                return [{"uri": file_path, "range": {"start": {"line": line + 1, "character": 0}}}]
            elif method == "textDocument/hover":
                return {"contents": f"Mock hover info for {file_path}:{line}:{column}"}
            elif method == "textDocument/documentSymbol":
                return [{"name": "MockSymbol", "kind": "function", "range": {"start": {"line": 0}}}]
            else:
                return None

        # Real multilspy integration
        if not isinstance(server, ServerWrapper):
            raise LSPQueryError(f"Invalid server type: {type(server)}")

        # Security: Validate file_path is within repo_root
        from src.code_intelligence.path_utils import is_within_repo, normalize_path

        if not is_within_repo(file_path, self.repo_root):
            abs_path = normalize_path(file_path)
            repo_root_path = normalize_path(self.repo_root)
            self.logger.warning(
                "[SECURITY] Rejected path outside repo:\n"
                f"  raw file_path: {file_path}\n"
                f"  normalized: {abs_path}\n"
                f"  repo_root (raw): {self.repo_root}\n"
                f"  repo_root (normalized): {repo_root_path}\n"
                f"  cwd: {Path.cwd().resolve(strict=False)}"
            )
            raise LSPQueryError(f"File path outside repository: {file_path}")

        lsp = server.get_server()
        relative_path = server.get_relative_path(file_path)

        self.logger.debug(f"LSP Query: {method} at {relative_path}:{line}:{column}")

        query_start = time.perf_counter()
        try:
            # Open file before querying (required by multilspy)
            with lsp.open_file(relative_path):
                if method == "textDocument/definition":
                    # Returns List[Location]
                    locations = await lsp.request_definition(relative_path, line, column)
                    # Convert to dict format for compatibility
                    if locations:
                        loc = locations[0]  # Take first location
                        result = {
                            "uri": loc.get("uri", ""),
                            "range": loc.get("range", {}),
                            "absolutePath": loc.get("absolutePath", ""),
                            "relativePath": loc.get("relativePath", ""),
                        }
                    else:
                        result = None

                elif method == "textDocument/references":
                    # Returns List[Location]
                    locations = await lsp.request_references(relative_path, line, column)
                    # Convert to list of dicts
                    result = [
                        {
                            "uri": loc.get("uri", ""),
                            "range": loc.get("range", {}),
                            "absolutePath": loc.get("absolutePath", ""),
                            "relativePath": loc.get("relativePath", ""),
                        }
                        for loc in (locations or [])
                    ]

                elif method == "textDocument/hover":
                    # Returns Hover | None
                    hover = await lsp.request_hover(relative_path, line, column)
                    if hover:
                        result = {
                            "contents": hover.get("contents", ""),
                            "range": hover.get("range", {}),
                        }
                    else:
                        result = None

                elif method == "textDocument/documentSymbol":
                    # Returns Tuple[List[UnifiedSymbolInformation], tree]
                    symbols, tree = await lsp.request_document_symbols(relative_path)
                    # Convert to list of dicts
                    result = [
                        {
                            "name": sym.get("name", ""),
                            "kind": sym.get("kind", ""),
                            "location": sym.get("location", {}),
                            "range": sym.get("range", {}),
                        }
                        for sym in (symbols or [])
                    ]

                else:
                    raise LSPQueryError(f"Unknown LSP method: {method}")

            # [PERF] Log query timing
            query_ms = (time.perf_counter() - query_start) * 1000
            self.logger.debug(
                f"[PERF] LSP query: method={method}, file={relative_path}, query_ms={query_ms:.1f}"
            )
            return result

        except Exception as e:
            query_ms = (time.perf_counter() - query_start) * 1000
            self.logger.error(f"LSP query failed: {method} - {e} (query_ms={query_ms:.1f})")
            raise LSPQueryError(f"LSP query failed: {e}") from e

    async def _query_workspace_symbols(self, server: Any, query: str) -> list[dict[str, Any]]:
        """Query workspace symbols using multilspy."""
        # Handle mock server
        if isinstance(server, MockLanguageServer):
            self.logger.debug(f"[MOCK] Workspace symbol search: {query}")
            await asyncio.sleep(0.1)
            return [
                {
                    "name": f"Mock{query}",
                    "kind": "class",
                    "location": {"uri": "mock.py", "range": {"start": {"line": 0}}},
                }
            ]

        # Real multilspy integration
        if not isinstance(server, ServerWrapper):
            raise LSPQueryError(f"Invalid server type: {type(server)}")

        lsp = server.get_server()

        try:
            # Request workspace symbols
            symbols = await lsp.request_workspace_symbol(query)

            if not symbols:
                return []

            # Convert to dict format
            return [
                {
                    "name": sym.get("name", ""),
                    "kind": sym.get("kind", ""),
                    "location": sym.get("location", {}),
                }
                for sym in symbols
            ]

        except Exception as e:
            self.logger.warning(f"Workspace symbol search failed: {e}")
            return []

    async def _close_server(self, server: Any, timeout: float = 5.0) -> None:
        """
        Close language server gracefully with timeout.

        Args:
            server: Server instance to close
            timeout: Shutdown timeout in seconds (default: 5.0)

        Raises:
            asyncio.TimeoutError: Server shutdown timed out
            LSPError: Failed to close server
        """
        if isinstance(server, MockLanguageServer):
            self.logger.debug(f"[MOCK] Closing server: {server}")
            await asyncio.sleep(0.01)
            return

        if isinstance(server, ServerWrapper):
            try:
                # Exit async context manager with timeout (prevents hanging)
                await asyncio.wait_for(server.__aexit__(None, None, None), timeout=timeout)
                self.logger.debug(f"Closed {server.language} server")
            except asyncio.TimeoutError:
                self.logger.error(f"Server shutdown timed out after {timeout}s")
                raise LSPError(f"Server shutdown timeout: {server.language}")
            except Exception as e:
                self.logger.error(f"Error closing server: {e}")
                raise LSPError(f"Failed to close server: {server.language}") from e
        else:
            self.logger.warning(f"Unknown server type: {type(server)}")

    def _detect_language(self, file_path: str) -> str:
        """
        Detect language from file extension.

        Args:
            file_path: Path to file

        Returns:
            Language name

        Example:
            >>> manager._detect_language("src/auth.py")
            "python"
            >>> manager._detect_language("src/app.ts")
            "typescript"
        """
        ext = Path(file_path).suffix.lower()

        extension_map = {
            ".py": "python",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".js": "javascript",
            ".jsx": "javascript",
        }

        return extension_map.get(ext, "unknown")

    def _detect_primary_language(self, repo_root: str | None) -> str:
        """
        Detect primary language in repository.

        For now, defaults to Python. Later: scan repo for most common language.
        """
        # TODO: Implement repo scanning
        # For now, default to Python
        return "python"

    def _cache_key(
        self, operation: str, file_path: str, line: int | None = None, column: int | None = None
    ) -> str:
        """
        Generate cache key for LSP query.

        Format: {operation}:{file_path}:{line}:{column}

        Args:
            operation: Operation type (def, refs, hover, etc.)
            file_path: File path
            line: Line number
            column: Column number

        Returns:
            Cache key string
        """
        if line is not None and column is not None:
            return f"{operation}:{file_path}:{line}:{column}"
        else:
            return f"{operation}:{file_path}"

    def _detect_repo_root(self) -> str:
        """
        Detect repository root (looks for .git directory).

        Returns:
            Repository root path (defaults to cwd if not found)
        """
        current = Path.cwd().resolve(strict=False)

        # Walk up looking for .git
        while current != current.parent:
            if (current / ".git").exists():
                self.logger.debug(f"Detected repo root: {current}")
                return str(current)
            current = current.parent

        # Fallback to cwd
        cwd = str(Path.cwd())
        self.logger.warning(f"No .git found, using cwd as repo root: {cwd}")
        return cwd


class MockLanguageServer:
    """Mock language server for testing without multilspy."""

    def __init__(self, language: str):
        self.language = language

    def __repr__(self):
        return f"MockLanguageServer({self.language})"
