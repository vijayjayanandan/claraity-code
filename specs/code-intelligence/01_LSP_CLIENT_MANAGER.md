# LSP Client Manager

**Status**: Ready for implementation
**Estimated Time**: 1.5 hours
**Lines of Code**: ~400 LOC
**Dependencies**: multilspy, CodeIntelligenceConfig, LSPCache

---

## Overview

The **LSPClientManager** is the core component that manages multiple Language Server Protocol (LSP) servers. It provides:

- **Lazy initialization** - Servers start only when first queried
- **Multi-language support** - Python, TypeScript, Rust, etc.
- **Multi-repository support** - One server per repo + language
- **Query caching** - In-memory LRU cache with file invalidation
- **Resource limits** - Prevent memory exhaustion
- **Graceful error handling** - Fall back to RAG on failures

---

## Architecture

```
LSPClientManager
    │
    ├─> servers: Dict[(repo_root, language), LanguageServer]
    ├─> cache: LSPCache
    ├─> config: CodeIntelligenceConfig
    │
    └─> Methods:
        ├─> request_definition(file_path, line, column)
        ├─> request_references(file_path, line, column)
        ├─> request_hover(file_path, line, column)
        ├─> request_document_symbols(file_path)
        ├─> get_server(repo_root, language)
        ├─> _start_server(repo_root, language)
        ├─> _detect_language(file_path)
        ├─> _find_repository_root(file_path)
        ├─> _check_server_limit(language)
        └─> shutdown_all()
```

---

## Public Interface

### Class: LSPClientManager

```python
from typing import Dict, Tuple, Optional, List, Any
from pathlib import Path
from multilspy import LanguageServer
from multilspy.multilspy_config import MultilspyConfig

class LSPClientManager:
    """
    Manages multiple LSP servers with lazy initialization.

    Features:
    - Auto-detects language from file extension
    - Lazy initialization (servers start on first query)
    - Multi-repository support (one server per repo+language)
    - Query caching (in-memory LRU + file invalidation)
    - Graceful error handling (fall back to RAG)
    - Resource limits (max concurrent servers)
    """

    def __init__(
        self,
        working_directory: Path,
        config: Optional[CodeIntelligenceConfig] = None
    ):
        """
        Initialize LSP client manager.

        Args:
            working_directory: Base working directory
            config: Optional configuration (auto-loaded if None)
        """

    async def request_definition(
        self,
        file_path: str,
        line: int,
        column: int
    ) -> Dict[str, Any]:
        """Get symbol definition at cursor position."""

    async def request_references(
        self,
        file_path: str,
        line: int,
        column: int
    ) -> List[Dict[str, Any]]:
        """Find all references to symbol."""

    async def request_hover(
        self,
        file_path: str,
        line: int,
        column: int
    ) -> Dict[str, Any]:
        """Get hover info (type, documentation)."""

    async def request_document_symbols(
        self,
        file_path: str
    ) -> List[Dict[str, Any]]:
        """Get all symbols in document."""

    async def get_server(
        self,
        repo_root: str,
        language: str
    ) -> LanguageServer:
        """Get or create LSP server (lazy initialization)."""

    async def shutdown_all(self) -> None:
        """Shutdown all LSP servers."""
```

---

## Implementation Details

### Method: __init__

```python
def __init__(
    self,
    working_directory: Path,
    config: Optional[CodeIntelligenceConfig] = None
):
    """
    Initialize LSP client manager.

    Args:
        working_directory: Base working directory for the agent
        config: Optional configuration (auto-loaded if None)
    """
    self.working_directory = working_directory
    self.config = config or CodeIntelligenceConfig(working_directory)

    # Server registry: (repo_root, language) -> LanguageServer
    self.servers: Dict[Tuple[str, str], LanguageServer] = {}

    # Cache
    self.cache = LSPCache(
        max_size_mb=self.config.cache["max_size_mb"],
        ttl_seconds=self.config.cache["ttl_seconds"]
    )

    # Resource tracking
    self.max_servers = self.config.resource_limits["max_concurrent_servers"]
    self.hard_limit = self.config.resource_limits["hard_limit_servers"]

    # Logger
    import logging
    self.logger = logging.getLogger("code_intelligence.lsp_manager")
```

---

### Method: request_definition

```python
async def request_definition(
    self,
    file_path: str,
    line: int,
    column: int
) -> Dict[str, Any]:
    """
    Get symbol definition at cursor position.

    Args:
        file_path: Path to source file
        line: Line number (1-indexed)
        column: Column number (0-indexed)

    Returns:
        Definition location and signature:
        {
            "uri": "file:///path/to/file.py",
            "range": {
                "start": {"line": 45, "character": 4},
                "end": {"line": 45, "character": 16}
            },
            "signature": "def authenticate(username: str, password: str) -> bool"
        }

    Raises:
        UnsupportedLanguageError: Language not supported
        LSPServerStartError: Failed to start LSP server
        LSPQueryError: Query failed
    """
    # Check cache first
    cache_key = f"def:{file_path}:{line}:{column}"
    cached = self.cache.get(cache_key)
    if cached:
        self.logger.debug(f"Cache hit: {cache_key}")
        return cached

    # Detect language and repository
    language = self._detect_language(file_path)
    repo_root = self._find_repository_root(file_path)

    # Get or create server (lazy initialization)
    server = await self.get_server(repo_root, language)

    # Query LSP server
    try:
        result = await server.request_definition(file_path, line, column)

        # Cache result
        self.cache.set(cache_key, result, file_path=file_path)

        return result

    except Exception as e:
        self.logger.error(f"LSP definition query failed: {e}", exc_info=True)
        raise LSPQueryError(f"Definition query failed: {e}") from e
```

**Example Usage**:
```python
lsp_manager = LSPClientManager(working_directory=Path.cwd())

# First call to Python file - starts jedi-language-server (5s)
result = await lsp_manager.request_definition("src/auth.py", 45, 10)

print(result["signature"])
# Output: "def authenticate(username: str, password: str) -> bool"

# Second call - cached server (<20ms)
result2 = await lsp_manager.request_definition("src/auth.py", 50, 5)
```

---

### Method: request_references

```python
async def request_references(
    self,
    file_path: str,
    line: int,
    column: int
) -> List[Dict[str, Any]]:
    """
    Find all references to symbol at cursor position.

    Args:
        file_path: Path to source file
        line: Line number (1-indexed)
        column: Column number (0-indexed)

    Returns:
        List of reference locations:
        [
            {
                "uri": "file:///path/to/login.py",
                "range": {"start": {"line": 23, "character": 8}, ...}
            },
            {
                "uri": "file:///path/to/api.py",
                "range": {"start": {"line": 67, "character": 15}, ...}
            }
        ]

    Raises:
        UnsupportedLanguageError: Language not supported
        LSPServerStartError: Failed to start LSP server
        LSPQueryError: Query failed
    """
    # Check cache
    cache_key = f"refs:{file_path}:{line}:{column}"
    cached = self.cache.get(cache_key)
    if cached:
        self.logger.debug(f"Cache hit: {cache_key}")
        return cached

    # Detect language and repository
    language = self._detect_language(file_path)
    repo_root = self._find_repository_root(file_path)

    # Get server
    server = await self.get_server(repo_root, language)

    # Query
    try:
        references = await server.request_references(file_path, line, column)

        # Cache
        self.cache.set(cache_key, references, file_path=file_path)

        return references

    except Exception as e:
        self.logger.error(f"LSP references query failed: {e}", exc_info=True)
        raise LSPQueryError(f"References query failed: {e}") from e
```

**Example Usage**:
```python
# Find all references to authenticate()
references = await lsp_manager.request_references("src/auth.py", 45, 10)

print(f"Found {len(references)} references:")
for ref in references:
    file = Path(ref["uri"]).name
    line = ref["range"]["start"]["line"]
    print(f"  - {file}:{line}")

# Output:
# Found 15 references:
#   - login.py:23
#   - api.py:67
#   - middleware.py:88
#   ...
```

---

### Method: request_hover

```python
async def request_hover(
    self,
    file_path: str,
    line: int,
    column: int
) -> Dict[str, Any]:
    """
    Get hover information (type signature, documentation).

    Args:
        file_path: Path to source file
        line: Line number (1-indexed)
        column: Column number (0-indexed)

    Returns:
        Hover information:
        {
            "contents": "def authenticate(username: str, password: str) -> bool\n\nAuthenticate user against database.",
            "range": {"start": {...}, "end": {...}}
        }

    Raises:
        UnsupportedLanguageError: Language not supported
        LSPServerStartError: Failed to start LSP server
        LSPQueryError: Query failed
    """
    # Check cache
    cache_key = f"hover:{file_path}:{line}:{column}"
    cached = self.cache.get(cache_key)
    if cached:
        return cached

    # Detect language and repository
    language = self._detect_language(file_path)
    repo_root = self._find_repository_root(file_path)

    # Get server
    server = await self.get_server(repo_root, language)

    # Query
    try:
        hover_info = await server.request_hover(file_path, line, column)

        # Cache
        self.cache.set(cache_key, hover_info, file_path=file_path)

        return hover_info

    except Exception as e:
        self.logger.error(f"LSP hover query failed: {e}", exc_info=True)
        raise LSPQueryError(f"Hover query failed: {e}") from e
```

---

### Method: request_document_symbols

```python
async def request_document_symbols(
    self,
    file_path: str
) -> List[Dict[str, Any]]:
    """
    Get all symbols in document (functions, classes, methods).

    Args:
        file_path: Path to source file

    Returns:
        List of symbols:
        [
            {
                "name": "authenticate",
                "kind": "function",
                "range": {"start": {"line": 45, "character": 0}, ...},
                "detail": "def authenticate(username: str, password: str) -> bool"
            },
            {
                "name": "User",
                "kind": "class",
                "range": {"start": {"line": 10, "character": 0}, ...},
                "children": [...]
            }
        ]

    Raises:
        UnsupportedLanguageError: Language not supported
        LSPServerStartError: Failed to start LSP server
        LSPQueryError: Query failed
    """
    # Check cache (file-level, invalidate on file change)
    cache_key = f"doc_symbols:{file_path}"
    cached = self.cache.get(cache_key)
    if cached:
        return cached

    # Detect language and repository
    language = self._detect_language(file_path)
    repo_root = self._find_repository_root(file_path)

    # Get server
    server = await self.get_server(repo_root, language)

    # Query
    try:
        symbols = await server.request_document_symbols(file_path)

        # Cache
        self.cache.set(cache_key, symbols, file_path=file_path)

        return symbols

    except Exception as e:
        self.logger.error(f"LSP document symbols query failed: {e}", exc_info=True)
        raise LSPQueryError(f"Document symbols query failed: {e}") from e
```

**Example Usage**:
```python
# Get all symbols in auth.py
symbols = await lsp_manager.request_document_symbols("src/auth.py")

print("Functions:")
for symbol in symbols:
    if symbol["kind"] == "function":
        print(f"  - {symbol['name']}: {symbol['detail']}")

# Output:
# Functions:
#   - authenticate: def authenticate(username: str, password: str) -> bool
#   - hash_password: def hash_password(password: str) -> str
#   - verify_password: def verify_password(password: str, hash: str) -> bool
```

---

### Method: get_server

```python
async def get_server(
    self,
    repo_root: str,
    language: str
) -> LanguageServer:
    """
    Get or create LSP server for repository and language.

    Lazy initialization: Server starts on first query.
    Respects resource limits (max concurrent servers).

    Args:
        repo_root: Repository root path
        language: Programming language (python, typescript, rust, etc.)

    Returns:
        Running LanguageServer instance

    Raises:
        TooManyServersError: Hard limit exceeded
        UserRejectedServerError: User declined to start server
        LSPServerStartError: Failed to start server
    """
    key = (repo_root, language)

    # Return existing server
    if key in self.servers:
        return self.servers[key]

    # Check resource limits
    await self._check_server_limit(language)

    # Start new server
    await self._start_server(repo_root, language)

    return self.servers[key]
```

---

### Method: _start_server (Private)

```python
async def _start_server(
    self,
    repo_root: str,
    language: str
) -> None:
    """
    Start LSP server for language.

    Args:
        repo_root: Repository root path
        language: Programming language

    Raises:
        LSPServerStartError: Failed to start server
    """
    key = (repo_root, language)

    self.logger.info(f"Starting {language} LSP server for {repo_root}")

    try:
        # Configure multilspy
        config = MultilspyConfig.from_dict({
            "code_language": language,
            "trace_lsp_communication": self.config.debug
        })

        # Create server (async context manager)
        server = await LanguageServer.create(
            config,
            self.logger,
            repo_root
        )

        # Start server (may take 5-30 seconds first time)
        await server.start_server()

        # Store server
        self.servers[key] = server

        self.logger.info(f"[OK] {language} server started ({Path(repo_root).name})")

    except Exception as e:
        self.logger.error(f"[FAIL] Failed to start {language} server: {e}", exc_info=True)
        raise LSPServerStartError(f"Failed to start {language} server: {e}") from e
```

**Implementation Note**: Use Rich Status for progress indication:

```python
from rich.status import Status
from rich.console import Console

console = Console()

async def _start_server(self, repo_root: str, language: str):
    with Status(
        f"[INFO] Initializing {language} language server...",
        console=console,
        spinner="dots"
    ):
        # multilspy auto-downloads server binary if needed
        server = await LanguageServer.create(...)
        await server.start_server()
```

---

### Method: _detect_language (Private)

```python
def _detect_language(self, file_path: str) -> str:
    """
    Detect programming language from file extension.

    Args:
        file_path: Path to source file

    Returns:
        Language name (python, typescript, rust, etc.)

    Raises:
        UnsupportedLanguageError: Language not supported
    """
    ext = Path(file_path).suffix.lower()

    # Check custom mappings first (from config)
    language = self.config.language_mappings.get(ext)
    if language:
        return language

    # Default mappings
    LANGUAGE_DETECTION = {
        ".py": "python",
        ".pyi": "python",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "javascript",
        ".jsx": "javascript",
        ".rs": "rust",
        ".go": "go",
        ".java": "java",
        ".kt": "kotlin",
        ".cs": "csharp",
        ".rb": "ruby",
        ".dart": "dart",
    }

    language = LANGUAGE_DETECTION.get(ext)
    if not language:
        raise UnsupportedLanguageError(
            f"Language not supported for {ext}. "
            f"Supported: {list(LANGUAGE_DETECTION.keys())}"
        )

    return language
```

---

### Method: _find_repository_root (Private)

```python
def _find_repository_root(self, file_path: str) -> str:
    """
    Find git repository root by walking up directory tree.

    Args:
        file_path: Path to source file

    Returns:
        Repository root path (or file's parent if no git repo found)
    """
    path = Path(file_path).resolve().parent

    # Walk up until we find .git directory
    while path != path.parent:
        if (path / ".git").exists():
            return str(path)
        path = path.parent

    # Fallback: file's parent directory
    return str(Path(file_path).parent)
```

---

### Method: _check_server_limit (Private)

```python
async def _check_server_limit(self, language: str) -> None:
    """
    Check if server limit exceeded, prompt user if needed.

    Args:
        language: Language for new server

    Raises:
        TooManyServersError: Hard limit exceeded
        UserRejectedServerError: User declined to start server
    """
    current_count = len(self.servers)

    # Hard limit - never exceed
    if current_count >= self.hard_limit:
        raise TooManyServersError(
            f"Hard limit of {self.hard_limit} LSP servers exceeded. "
            f"Currently running: {current_count}"
        )

    # Soft limit - ask user for approval
    if current_count >= self.max_servers:
        approved = await self._prompt_server_approval(language, current_count)
        if not approved:
            raise UserRejectedServerError(
                f"User declined to start {language} server (limit: {self.max_servers})"
            )
```

---

### Method: _prompt_server_approval (Private)

```python
async def _prompt_server_approval(
    self,
    language: str,
    current_count: int
) -> bool:
    """
    Prompt user for approval to exceed soft limit.

    Args:
        language: Language for new server
        current_count: Current number of servers

    Returns:
        True if approved, False if rejected
    """
    from src.platform import safe_print

    safe_print("\n" + "-" * 60)
    safe_print(f"[WARN] LSP server limit ({self.max_servers}) reached")
    safe_print(f"Currently running: {current_count} servers")
    safe_print(f"Memory usage: ~{current_count * 200}MB")
    safe_print(f"\nStart {language} language server? (yes/no): ", end="", flush=True)

    try:
        response = input().strip().lower()
        approved = response in ["yes", "y"]

        if approved:
            safe_print(f"[OK] Starting {language} server...\n")
        else:
            safe_print(f"[CANCEL] Falling back to RAG-only context\n")

        return approved

    except (EOFError, KeyboardInterrupt):
        safe_print("\n[CANCEL] Interrupted\n")
        return False
```

---

### Method: shutdown_all

```python
async def shutdown_all(self) -> None:
    """
    Shutdown all LSP servers and cleanup resources.

    Called on agent shutdown to ensure clean exit.
    """
    self.logger.info("Shutting down all LSP servers...")

    for (repo, lang), server in self.servers.items():
        try:
            await server.shutdown_server()
            self.logger.info(f"[OK] Shut down {lang} server ({Path(repo).name})")
        except Exception as e:
            self.logger.warning(f"[WARN] Failed to shut down {lang} server: {e}")

    self.servers.clear()
    self.logger.info("All LSP servers shut down")
```

---

## Error Handling

### Exception Hierarchy

```python
class LSPError(Exception):
    """Base exception for LSP errors."""

class LSPServerStartError(LSPError):
    """LSP server failed to start."""

class LSPQueryError(LSPError):
    """LSP query failed."""

class UnsupportedLanguageError(LSPError):
    """Language not supported."""

class TooManyServersError(LSPError):
    """Too many LSP servers running."""

class UserRejectedServerError(LSPError):
    """User declined to start server."""
```

### Graceful Degradation Pattern

```python
# In orchestrator or tools
try:
    result = await lsp_manager.request_definition(file, line, col)
    return result
except LSPError as e:
    logger.warning(f"LSP query failed: {e}. Falling back to RAG.")
    # Fall back to RAG-only context loading
    return None  # Caller handles fallback
```

---

## Acceptance Criteria

### Functional Requirements

- [ ] **Language detection** works for all supported extensions
- [ ] **Lazy initialization** - servers start only on first query
- [ ] **Multi-repo support** - different repos get separate servers
- [ ] **Caching works** - repeated queries hit cache (70%+ hit rate)
- [ ] **Resource limits** - respects max_servers configuration
- [ ] **Graceful errors** - raises proper exceptions on failures
- [ ] **Shutdown cleanup** - all servers shut down cleanly

### Performance Targets

- [ ] **First query**: <10 seconds (including server initialization)
- [ ] **Subsequent queries**: <100ms (cached server)
- [ ] **Cache hit rate**: >70% for typical workflows
- [ ] **Memory per server**: <300MB (varies by language)

### Quality Metrics

- [ ] **Test coverage**: 95%+ for all public methods
- [ ] **Integration tests**: Pass with real Python/TypeScript/Rust servers
- [ ] **Error handling**: All exception paths tested
- [ ] **Windows compatibility**: No emojis, paths normalized

---

## Testing Strategy

### Unit Tests (tests/test_lsp_manager.py)

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from pathlib import Path

@pytest.mark.asyncio
async def test_request_definition_cache_hit():
    """Test definition query with cache hit."""
    lsp_manager = LSPClientManager(Path.cwd())

    # Mock cache
    lsp_manager.cache.get = MagicMock(return_value={"uri": "file:///test.py"})

    result = await lsp_manager.request_definition("test.py", 10, 5)

    assert result["uri"] == "file:///test.py"
    # Should not start server (cache hit)
    assert len(lsp_manager.servers) == 0

@pytest.mark.asyncio
async def test_language_detection():
    """Test language detection from file extensions."""
    lsp_manager = LSPClientManager(Path.cwd())

    assert lsp_manager._detect_language("test.py") == "python"
    assert lsp_manager._detect_language("test.ts") == "typescript"
    assert lsp_manager._detect_language("test.rs") == "rust"

    with pytest.raises(UnsupportedLanguageError):
        lsp_manager._detect_language("test.xyz")

@pytest.mark.asyncio
async def test_server_limit_hard_limit():
    """Test hard limit enforcement."""
    lsp_manager = LSPClientManager(Path.cwd())
    lsp_manager.hard_limit = 0  # Force limit

    with pytest.raises(TooManyServersError):
        await lsp_manager._check_server_limit("python")
```

### Integration Tests (tests/test_lsp_integration_python.py)

```python
@pytest.mark.asyncio
@pytest.mark.integration
async def test_python_lsp_server_real():
    """Test with real Python LSP server."""
    lsp_manager = LSPClientManager(Path.cwd())

    # Create test file
    test_file = Path("test_lsp_temp.py")
    test_file.write_text("def hello(): pass")

    try:
        # Query definition (will start jedi-language-server)
        result = await lsp_manager.request_definition(
            str(test_file),
            1,  # Line 1
            4   # Column 4 (on "hello")
        )

        assert result is not None
        assert "uri" in result
        assert "range" in result

    finally:
        test_file.unlink()
        await lsp_manager.shutdown_all()
```

---

## Implementation Patterns

### Pattern: Progress Indicator During Initialization

```python
from rich.status import Status
from rich.console import Console

async def _start_server(self, repo_root: str, language: str):
    console = Console()

    with Status(
        f"[INFO] Initializing {language} language server...",
        console=console,
        spinner="dots"
    ):
        config = MultilspyConfig.from_dict({"code_language": language})
        server = await LanguageServer.create(config, self.logger, repo_root)
        await server.start_server()  # May take 5-30 seconds

    self.servers[(repo_root, language)] = server
    print(f"[OK] {language} server ready")
```

### Pattern: Retry Logic for Server Crashes

```python
async def request_definition(self, file_path, line, column):
    max_retries = 3

    for attempt in range(max_retries):
        try:
            server = await self.get_server(repo_root, language)
            result = await server.request_definition(file_path, line, column)
            return result

        except ServerCrashError as e:
            if attempt < max_retries - 1:
                self.logger.warning(f"Server crashed, restarting (attempt {attempt + 1})")
                await self._restart_server(repo_root, language)
            else:
                raise LSPQueryError("Server unrecoverable after 3 retries") from e
```

### Antipattern: Starting All Servers Upfront

```python
# BAD: Don't do this
async def __init__(self, ...):
    # Starting servers upfront wastes resources
    await self._start_server(".", "python")
    await self._start_server(".", "typescript")
    await self._start_server(".", "rust")
    # User may only need Python!

# GOOD: Lazy initialization
async def get_server(self, repo_root, language):
    if key not in self.servers:
        await self._start_server(repo_root, language)  # Start only when needed
    return self.servers[key]
```

---

## File Location

**Path**: `src/code_intelligence/lsp_manager.py`

---

**Status**: ✅ Ready for implementation
**Next**: Read [02_LSP_CACHE.md](02_LSP_CACHE.md)
