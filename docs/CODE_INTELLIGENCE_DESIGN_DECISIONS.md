# Code Intelligence: Design Decisions Document

**Date**: November 18, 2025
**Status**: Final Design - Ready for Implementation
**Purpose**: Finalize all architectural decisions for MCP + LSP integration
**Based On**:
- Preliminary Research (`CODE_INTELLIGENCE_PRELIMINARY_RESEARCH.md`)
- Agent Analysis (`CODE_INTELLIGENCE_AGENT_ANALYSIS.md`)
- SOTA patterns (Cursor, Claude Code, Nuanced MCP)

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Open Questions Answered](#open-questions-answered)
3. [MCP Server Architecture](#mcp-server-architecture)
4. [LSP Integration Design](#lsp-integration-design)
5. [Smart Context Loader Strategy](#smart-context-loader-strategy)
6. [Implementation Plan](#implementation-plan)
7. [Migration & Rollout Strategy](#migration--rollout-strategy)
8. [Performance Targets & Validation](#performance-targets--validation)
9. [Risk Mitigation](#risk-mitigation)

---

## Executive Summary

### Architecture Choice: **Full MCP + LSP Integration (Option B)**

**Decision**: Build production-grade MCP server wrapping LSP + ClarAIty + RAG, following industry SOTA pattern.

### Key Decisions at a Glance

| Decision Area | Choice | Rationale |
|---------------|--------|-----------|
| **Tool Granularity** | Hybrid (fine + coarse) | Flexibility + convenience |
| **Caching** | In-memory LRU + file invalidation | Performance + accuracy |
| **Multi-Repo** | One server per repo | Simplicity, clear isolation |
| **Configuration** | Auto-detect + overrides | Zero config for 95% cases |
| **Progress** | Rich Status + MCP progress | Consistent UX, Windows-safe |
| **Resource Limits** | Max 3 concurrent servers | Balance memory/functionality |
| **Error Handling** | Graceful degradation + logging | Resilient, user-friendly |
| **Integration** | MCP server + agent client | Industry standard, reusable |

### Token Budget Reallocation

```
BEFORE (Current):
  System: 15%, Task: 20%, RAG: 30%, Memory: 35%

AFTER (With Code Intelligence):
  System: 15%, Task: 10%
  ClarAIty: 10% (new - architectural context)
  RAG: 20% (reduced - semantic search)
  LSP: 20% (new - symbol precision)
  Memory: 25% (reduced - conversation history)
```

**Expected Efficiency**: 50%+ better context quality (targeted vs full chunks)

### Components to Build

1. **LSPClientManager** - Wraps multilspy, lazy initialization (~400 LOC)
2. **MCPServer** - FastMCP server exposing tools (~300 LOC)
3. **CodeIntelligenceOrchestrator** - Multi-tier context loader (~500 LOC)
4. **Code Intelligence Tools** - 7 MCP tools for agent (~400 LOC)
5. **Integration** - ContextBuilder enhancements, tool registration (~150 LOC)

**Total**: ~1,750 LOC, ~7 hours implementation time

---

## Open Questions Answered

### Question 1: Tool Granularity

**Options**:
- **Fine-grained**: One tool per LSP method (get_definition, get_references, get_hover)
- **Coarse-grained**: Combined tools (analyze_symbol returns all info)
- **Hybrid**: Both fine and coarse-grained tools

**Analysis**:

**Pros of Fine-Grained**:
- ✅ Mirrors LSP spec exactly
- ✅ LLM can request only what it needs
- ✅ Easier to implement (1:1 mapping to multilspy)
- ✅ Better observability (see which tools LLM uses)

**Cons of Fine-Grained**:
- ❌ More tool calls (3 calls for definition + references + hover)
- ❌ Higher latency (sequential calls)
- ❌ Increases tool count (24 → 30 tools)

**Pros of Coarse-Grained**:
- ✅ Fewer tool calls (1 call gets all info)
- ✅ Lower latency (parallel LSP queries internally)
- ✅ Lower tool count (24 → 26 tools)
- ✅ Simpler for common workflows

**Cons of Coarse-Grained**:
- ❌ May return unnecessary data (waste tokens)
- ❌ Less flexible (can't request just definition)
- ❌ Harder to debug (which part failed?)

**Decision**: **HYBRID APPROACH**

**Tools to Implement**:

**Fine-Grained** (Core LSP operations):
1. `get_symbol_definition(file_path, line, column)` → LSP textDocument/definition
2. `get_symbol_references(file_path, line, column)` → LSP textDocument/references
3. `get_symbol_hover(file_path, line, column)` → LSP textDocument/hover
4. `get_document_symbols(file_path)` → LSP textDocument/documentSymbol

**Coarse-Grained** (High-level workflows):
5. `analyze_symbol(file_path, line, column)` → Combines definition + references + hover
6. `search_code_with_lsp(query, language)` → Workspace symbol search
7. `load_smart_context(task_description, max_tokens)` → Multi-tier context (ClarAIty + RAG + LSP)

**Rationale**:
- LLM gets **flexibility** (can call individual tools for specific needs)
- LLM gets **convenience** (can use wrappers for common patterns)
- **Total tool count**: 24 + 7 = 31 (acceptable for OpenAI function calling)
- Follows **ClarAIty pattern** (we have both query_component and query_architecture_summary)

**Implementation Note**: Coarse-grained tools internally call fine-grained ones (code reuse).

---

### Question 2: Caching Strategy

**What to Cache**:
- Symbol definitions (rarely change)
- Symbol references (change when code edited)
- Hover info (useful for repeated queries)
- Document symbols (change when file edited)

**Where to Cache**:
- **In-memory** (fast but lost on restart)
- **SQLite** (persistent but slower)
- **Redis** (fast + persistent but adds dependency)

**Cache Invalidation**:
- **TTL** (time-based): Cache expires after N minutes
- **File-change based**: Invalidate on file modification
- **LRU** (Least Recently Used): Evict old entries when cache full

**Analysis**:

**Agent Session Patterns** (from Phase A analysis):
- Sessions last 30-60 minutes typically
- Multiple queries to same symbols (refactoring workflows)
- File editing is frequent (need invalidation)
- Multi-turn conversations (cache valuable)

**LSP Query Performance**:
- Definition query: 5-20ms (fast even without cache)
- References query: 10-50ms (depends on codebase size)
- Hover query: 5-15ms (fast)
- **Cache hit saves**: 5-50ms per query

**Decision**: **In-memory LRU cache with file-change invalidation**

**Cache Configuration**:
```python
class LSPCache:
    def __init__(self):
        self.max_size_mb = 10  # 10MB limit (~5,000 entries)
        self.ttl_seconds = 300  # 5 minute TTL
        self.cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self.file_watchers: Dict[str, FileWatcher] = {}

    def get(self, key: str) -> Optional[Any]:
        """Get from cache, check TTL and file modification."""
        if key not in self.cache:
            return None

        entry = self.cache[key]

        # Check TTL
        if time.time() - entry.timestamp > self.ttl_seconds:
            del self.cache[key]
            return None

        # Check file modification
        if entry.file_path and self._file_modified(entry.file_path, entry.file_mtime):
            self._invalidate_file(entry.file_path)
            return None

        # Move to end (LRU)
        self.cache.move_to_end(key)
        return entry.value

    def set(self, key: str, value: Any, file_path: Optional[str] = None):
        """Set cache entry."""
        # Evict if size limit exceeded (LRU)
        while self._size_mb() > self.max_size_mb and len(self.cache) > 0:
            self.cache.popitem(last=False)  # Remove oldest

        self.cache[key] = CacheEntry(
            value=value,
            timestamp=time.time(),
            file_path=file_path,
            file_mtime=self._get_mtime(file_path) if file_path else None
        )
```

**Cache Keys**:
- Definition: `def:{file_path}:{line}:{col}`
- References: `refs:{file_path}:{line}:{col}`
- Hover: `hover:{file_path}:{line}:{col}`
- Document symbols: `doc_symbols:{file_path}`

**Invalidation Strategy**:
1. **On file edit**: Invalidate all entries for that file
2. **On TTL expiry**: Remove after 5 minutes
3. **On memory pressure**: LRU eviction (remove oldest)

**Rationale**:
- **In-memory**: Fast (no I/O), simple (no persistence complexity)
- **LRU**: Fair eviction (keeps frequently used entries)
- **File-change detection**: Ensures accuracy (no stale data)
- **5 min TTL**: Safety net (handles edge cases like external edits)
- **10MB limit**: ~5,000 entries (plenty for typical sessions)

**Performance Impact**:
- Cache hit rate: ~70% (estimated, based on query patterns)
- Latency reduction: 5-50ms saved per cache hit
- Memory overhead: <10MB (acceptable)

---

### Question 3: Multi-Repository Support

**Scenario**: User works on multiple repositories in same session

**Options**:

**Option A: One LSP server per repository**
- Each repo gets its own language server instance
- Clear isolation
- **Memory**: 3 repos × 3 languages = 9 servers × 200MB = 1.8GB

**Option B: Shared LSP server across repos**
- One language server for all repos
- **Problem**: LSP servers expect single workspace root
- May miss cross-file references

**Option C: Virtual workspace**
- Create virtual workspace containing all repos
- Single LSP server sees all code
- **Problem**: LSP server may get confused by multiple projects

**Analysis**:

**Typical Use Cases** (from agent analysis):
- Single repo: 90% of sessions
- Multi-repo (microservices): 8% of sessions
- Multi-repo (monorepo with subprojects): 2% of sessions

**LSP Server Expectations**:
- Most LSP servers expect a single "workspace root"
- Some support multi-root workspaces (VS Code feature)
- multilspy's API: `LanguageServer.create(config, logger, workspace_path)`

**Memory Constraints**:
- 8GB RAM machines are common
- Agent + LLM + RAG: ~2GB
- Available for LSP: ~6GB (3 repos × 3 langs = 9 servers → 1.8GB, acceptable)

**Decision**: **One LSP server per repository (Phase 1)**

**Implementation**:
```python
class LSPClientManager:
    def __init__(self):
        self.servers: Dict[Tuple[str, str], LanguageServer] = {}
        # Key: (repository_root, language) -> LanguageServer

    async def get_server(self, file_path: str, language: str) -> LanguageServer:
        """Get or create LSP server for file's repository."""
        repo_root = self._find_repository_root(file_path)
        key = (repo_root, language)

        if key not in self.servers:
            await self._start_server(repo_root, language)

        return self.servers[key]

    def _find_repository_root(self, file_path: str) -> str:
        """Find git repository root or parent directory."""
        path = Path(file_path).parent
        while path != path.parent:
            if (path / ".git").exists():
                return str(path)
            path = path.parent
        return str(Path(file_path).parent)  # Fallback: file's directory
```

**Repository Detection**:
1. Walk up from file path
2. Find `.git` directory → repository root
3. If no `.git` found → use file's parent directory

**Server Key**: `(repo_root, language)` tuple
- Same repo, same language → reuse server
- Different repo, same language → new server

**Memory Management**:
- Soft limit: 3 concurrent servers (configurable)
- Hard limit: 10 servers (prevents runaway memory)
- Warn user if limit exceeded, require approval

**Future Enhancement (Phase 2)**:
- If memory becomes issue, investigate:
  - Multi-root workspace support (some LSPs support this)
  - Server pooling (share servers across repos when safe)
  - Selective server shutdown (close unused servers after 10 min)

**Rationale**:
- **Simplicity**: Clear isolation, easy to implement
- **Correctness**: LSP servers work as intended
- **Performance**: Acceptable memory overhead for typical use cases
- **Scalability**: Can optimize later if needed

---

### Question 4: Configuration Management

**User Experience Goals**:
- Zero configuration for common cases (Python, TypeScript, Rust)
- Power users can customize (specify alternative LSP servers)
- Easy troubleshooting (clear errors if server not found)

**Options**:

**Option A: Auto-detect** (based on file extensions)
- `.py` → Python (jedi-language-server)
- `.ts`, `.tsx` → TypeScript (typescript-language-server)
- `.rs` → Rust (rust-analyzer)
- **Pros**: Zero config
- **Cons**: Edge cases (Jupyter notebooks, custom extensions)

**Option B: Explicit configuration** (user specifies)
- `.code-intelligence.json`: `{"python": "pylsp", "typescript": "tsserver"}`
- **Pros**: Full control
- **Cons**: Requires manual setup, friction for new users

**Option C: Hybrid** (auto-detect with override)
- Auto-detect by default
- Optional config file for overrides
- **Pros**: Best of both worlds
- **Cons**: More complex implementation

**Decision**: **HYBRID (Auto-detect + Override Configuration)**

**Auto-Detection Strategy**:

```python
# File extension to language mapping
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

# Language to default LSP server (multilspy handles download)
DEFAULT_LSP_SERVERS = {
    "python": "jedi-language-server",
    "typescript": "typescript-language-server",
    "javascript": "typescript-language-server",
    "rust": "rust-analyzer",
    "go": "gopls",
    "java": "jdtls",
    "kotlin": "kotlin-language-server",
    "csharp": "omnisharp",
    "ruby": "solargraph",
    "dart": "dart-analyzer",
}

def detect_language(file_path: str) -> Optional[str]:
    """Detect language from file extension."""
    ext = Path(file_path).suffix.lower()
    return LANGUAGE_DETECTION.get(ext)
```

**Configuration File**: `.code-intelligence.json` (optional)

```json
{
  "lsp_servers": {
    "python": {
      "server": "pylsp",
      "command": "pylsp",
      "args": ["--verbose"]
    },
    "typescript": {
      "server": "typescript-language-server",
      "command": "typescript-language-server",
      "args": ["--stdio"]
    }
  },
  "language_mappings": {
    ".ipynb": "python",
    ".vue": "typescript"
  },
  "cache": {
    "enabled": true,
    "max_size_mb": 10,
    "ttl_seconds": 300
  },
  "resource_limits": {
    "max_concurrent_servers": 3,
    "server_startup_timeout_seconds": 30
  }
}
```

**Configuration Priority**:
1. `.code-intelligence.json` in repository root (highest priority)
2. `.code-intelligence.json` in user home directory
3. Environment variables (`LSP_PYTHON_SERVER=pylsp`)
4. Auto-detection defaults (lowest priority)

**Environment Variables** (`.env`):
```bash
# Enable/disable code intelligence
ENABLE_CODE_INTELLIGENCE=true

# Global LSP server overrides
LSP_PYTHON_SERVER=pylsp
LSP_TYPESCRIPT_SERVER=tsserver

# Resource limits
LSP_MAX_SERVERS=3
LSP_SERVER_TIMEOUT=30

# Cache settings
LSP_CACHE_ENABLED=true
LSP_CACHE_SIZE_MB=10
LSP_CACHE_TTL_SECONDS=300

# Debug mode
LSP_DEBUG=false
LSP_LOG_FILE=.lsp_debug.log
```

**Configuration Loading**:
```python
class CodeIntelligenceConfig:
    def __init__(self, working_directory: Path):
        self.working_directory = working_directory
        self.config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from file + env vars."""
        config = DEFAULT_CONFIG.copy()

        # 1. Load from .code-intelligence.json (repo root)
        repo_config = self.working_directory / ".code-intelligence.json"
        if repo_config.exists():
            with open(repo_config) as f:
                config.update(json.load(f))

        # 2. Load from user home
        home_config = Path.home() / ".code-intelligence.json"
        if home_config.exists():
            with open(home_config) as f:
                user_cfg = json.load(f)
                # Merge without overwriting repo-specific settings
                for key, value in user_cfg.items():
                    if key not in config:
                        config[key] = value

        # 3. Override with environment variables
        if os.getenv("LSP_PYTHON_SERVER"):
            config["lsp_servers"]["python"]["server"] = os.getenv("LSP_PYTHON_SERVER")

        if os.getenv("LSP_MAX_SERVERS"):
            config["resource_limits"]["max_concurrent_servers"] = int(os.getenv("LSP_MAX_SERVERS"))

        return config

    def get_server_for_language(self, language: str) -> Dict[str, Any]:
        """Get LSP server configuration for language."""
        return self.config["lsp_servers"].get(language, DEFAULT_LSP_SERVERS[language])
```

**Rationale**:
- **Zero config for 95%**: Default mappings work for most projects
- **Customizable for power users**: Override via config file or env vars
- **Hierarchical precedence**: Repo > User > Env > Defaults (makes sense)
- **Discoverable**: Clear error messages if server not configured

**Error Handling**:
```python
# If language not supported
raise LanguageNotSupportedError(
    f"Language '{language}' not supported. "
    f"Supported languages: {list(DEFAULT_LSP_SERVERS.keys())}. "
    f"Add custom mapping in .code-intelligence.json"
)

# If LSP server not found
raise LSPServerNotFoundError(
    f"LSP server '{server_name}' not found for {language}. "
    f"multilspy will attempt auto-download. "
    f"Check logs at .lsp_debug.log for details."
)
```

---

### Question 5: Progress Reporting

**User Experience Problem**: LSP server initialization takes 5-30 seconds (first time per language)

**Without Progress**:
- User sees: [silence for 10-30 seconds]
- User thinks: "Is it frozen? Did it crash? Should I cancel?"
- User action: Cancels operation, files bug report

**With Progress**:
- User sees: "Initializing Python language server... (5s)"
- User thinks: "Okay, it's working, I'll wait"
- User action: Waits patiently, success

**Options**:

**Option A: Silent** (no indication)
- ❌ Terrible UX, confusing

**Option B: Simple message** ("Initializing Python language server...")
- ✅ Better than nothing
- ❌ No indication of progress (still looks frozen)

**Option C: Progress bar** ("Initializing: 45%")
- ✅ Clear progress indication
- ❌ LSP init doesn't report progress (can't implement accurately)

**Option D: Spinner/Status** ("Initializing Python language server... [spinner]")
- ✅ Shows activity (not frozen)
- ✅ Doesn't promise false progress
- ✅ Can show elapsed time

**Decision**: **Rich Status Indicators + MCP Progress Reporting**

**Implementation Strategy**:

**For CLI (agent.py)**:
```python
from rich.status import Status
from rich.console import Console

console = Console()

async def get_server(self, language: str) -> LanguageServer:
    """Get or create language server with progress indicator."""
    if language not in self.servers:
        # Show progress indicator during initialization
        with Status(
            f"[INFO] Initializing {language} language server...",
            console=console,
            spinner="dots"
        ):
            await self._start_server(language)

    return self.servers[language]
```

**For MCP Tools (mcp_server.py)**:
```python
from mcp.server.fastmcp import Context

@mcp.tool()
async def get_symbol_definition(
    ctx: Context,
    file_path: str,
    line: int,
    column: int
) -> dict:
    """Get symbol definition using LSP."""
    language = detect_language(file_path)

    # Report progress via MCP
    await ctx.info(f"Detecting language: {language}")

    if not lsp_manager.is_server_running(language):
        await ctx.info(f"Starting {language} language server...")
        await ctx.report_progress(progress=0.0, total=1.0)

        await lsp_manager.get_server(language)  # May take 5-30s

        await ctx.report_progress(progress=1.0, total=1.0)
        await ctx.info(f"{language} server ready")

    # Query LSP server
    result = await lsp_manager.request_definition(file_path, line, column)
    return result
```

**Windows Compatibility** (CRITICAL):
```python
# NEVER use emojis (Windows cp1252 encoding)
# BAD:
await ctx.info("✅ Server ready")

# GOOD:
await ctx.info("[OK] Server ready")

# Text markers only
STATUS_MARKERS = {
    "info": "[INFO]",
    "success": "[OK]",
    "error": "[FAIL]",
    "warning": "[WARN]",
    "progress": "[...]"
}
```

**Progress Messages** (Guidelines):
- Keep under 60 characters (fits in typical terminal width)
- Use present continuous tense ("Initializing...", "Downloading...")
- Include language/file context when relevant
- Show estimated time if known: "Initializing Java server... (20-30s)"

**Examples**:
```
[INFO] Initializing Python language server...
[OK] Python server ready (5.2s)

[INFO] Querying symbol definition...
[OK] Found definition at auth.py:45

[FAIL] Python server failed to start
[INFO] Falling back to RAG-only context loading
```

**Rationale**:
- **Rich Status**: Already used in agent.py (consistent UX)
- **MCP Context**: Standard progress reporting for MCP tools
- **Windows-safe**: No emojis, text markers only
- **Clear feedback**: User knows what's happening, not confused

---

### Question 6: Resource Limits

**Problem**: Without limits, agent could spawn 20+ LSP servers (10+ languages × 2+ repos) → 4-6GB RAM

**Constraints**:
- Typical machine: 8GB RAM
- Agent + LLM + RAG: ~2GB
- Available for LSP: ~6GB
- Need headroom for OS, browser, etc.

**Options**:

**Option A: No limits** (let user's system handle it)
- ❌ Risk: Memory exhaustion, system slowdown, crash

**Option B: Hard limit** (e.g., max 3 servers, block further requests)
- ✅ Prevents memory issues
- ❌ May block legitimate use cases (polyglot projects)

**Option C: Soft limit** (warn user, require approval if exceeded)
- ✅ Protects typical users
- ✅ Allows power users to override
- ✅ Educates user about resource usage

**Option D: Adaptive** (monitor system RAM, start servers if available)
- ✅ Smart, adapts to system
- ❌ Complex to implement (cross-platform RAM monitoring)
- ❌ May still cause issues (other processes use RAM)

**Decision**: **SOFT LIMIT with user override**

**Configuration**:
```bash
# .env
LSP_MAX_SERVERS=3          # Soft limit (warn if exceeded)
LSP_HARD_LIMIT_SERVERS=10  # Hard limit (never exceed)
```

**Implementation**:
```python
class LSPClientManager:
    def __init__(self, config: CodeIntelligenceConfig):
        self.config = config
        self.servers: Dict[Tuple[str, str], LanguageServer] = {}
        self.max_servers = config.resource_limits["max_concurrent_servers"]  # 3
        self.hard_limit = config.resource_limits["hard_limit_servers"]        # 10

    async def get_server(self, repo_root: str, language: str) -> LanguageServer:
        """Get or create language server, respecting limits."""
        key = (repo_root, language)

        if key in self.servers:
            return self.servers[key]

        # Check soft limit
        if len(self.servers) >= self.max_servers:
            if len(self.servers) >= self.hard_limit:
                raise TooManyServersError(
                    f"Hard limit of {self.hard_limit} LSP servers exceeded. "
                    f"Currently running: {self._list_servers()}"
                )

            # Soft limit exceeded - ask user
            approved = await self._prompt_server_limit_approval(language, len(self.servers))
            if not approved:
                raise UserRejectedServerError(
                    f"User declined to start {language} server (limit: {self.max_servers}, "
                    f"current: {len(self.servers)}). Falling back to RAG-only."
                )

        # Start server
        await self._start_server(repo_root, language)
        return self.servers[key]

    async def _prompt_server_limit_approval(self, language: str, current_count: int) -> bool:
        """Ask user for approval to exceed soft limit."""
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

    def _list_servers(self) -> str:
        """List running servers for debugging."""
        servers = []
        for (repo, lang), server in self.servers.items():
            mem_mb = self._estimate_server_memory(server)
            servers.append(f"{lang} ({Path(repo).name}) [{mem_mb}MB]")
        return ", ".join(servers)

    def shutdown_least_recently_used(self) -> None:
        """Shutdown LRU server to free memory (future enhancement)."""
        # Track last access time per server
        # Shutdown oldest server
        # TODO: Phase 2
        pass
```

**Memory Estimates** (for user info):
- Python (jedi-language-server): ~100MB
- TypeScript (typescript-language-server): ~200MB
- Rust (rust-analyzer): ~300MB
- Java (jdtls): ~500MB
- Go (gopls): ~150MB

**User Experience**:
```
# First 3 servers: Silent, just start
[INFO] Initializing Python language server...
[OK] Python server ready (5.2s)

# 4th server: Prompt for approval
[WARN] LSP server limit (3) reached
Currently running: 3 servers
Memory usage: ~600MB

Start TypeScript language server? (yes/no): yes
[OK] Starting TypeScript server...
[OK] TypeScript server ready (8.1s)

# 11th server: Hard limit
[FAIL] Hard limit of 10 LSP servers exceeded.
Currently running: python (project1), typescript (project1), rust (project2), ...
Cannot start JavaScript server. Falling back to RAG-only context.
```

**Rationale**:
- **Soft limit (3)**: Covers 90% of use cases (most projects use 1-3 languages)
- **Hard limit (10)**: Safety net (prevents runaway memory usage)
- **User approval**: Educates user, gives control
- **Graceful fallback**: If limit exceeded, use RAG only (don't fail completely)
- **Configurable**: Power users can increase limits via `.env`

**Future Enhancement (Phase 2)**:
- Automatic server shutdown (LRU policy, after 10 min idle)
- Memory monitoring (psutil library, check available RAM)
- Server pooling (share servers when safe)

---

### Question 7: Error Handling Philosophy

**Scenario**: LSP server fails (crash, timeout, not installed, unsupported language)

**Options**:

**Option A: Fail fast**
- Return error to agent immediately
- Agent shows error to user, stops operation
- **Pros**: Clear failure signals, easy to debug
- **Cons**: Disrupts user workflow, poor UX

**Option B: Graceful degradation**
- Fall back to RAG-only mode
- Log error for debugging
- Continue operation with reduced capabilities
- **Pros**: Resilient, doesn't block user
- **Cons**: May hide problems, silently reduces quality

**Decision**: **GRACEFUL DEGRADATION with logging** (already determined in Phase A)

**Strategy**:

```python
async def load_smart_context(
    task_description: str,
    max_tokens: int
) -> str:
    """Load multi-tier context (ClarAIty + RAG + LSP) with graceful degradation."""
    context_parts = []

    # Layer 1: ClarAIty (architectural context)
    try:
        clarity_context = await self._load_clarity_context(task_description)
        context_parts.append(("clarity", clarity_context))
    except Exception as e:
        logger.warning(f"ClarAIty context failed: {e}")
        # Continue without architectural context

    # Layer 2: RAG (semantic search)
    try:
        rag_context = await self._load_rag_context(task_description)
        context_parts.append(("rag", rag_context))
    except Exception as e:
        logger.warning(f"RAG context failed: {e}")
        # Continue without semantic context

    # Layer 3: LSP (symbol precision)
    try:
        lsp_context = await self._load_lsp_context(task_description)
        context_parts.append(("lsp", lsp_context))
    except LSPServerError as e:
        logger.warning(f"LSP context failed: {e}. Falling back to RAG-only.")
        # Already have RAG context, continue
    except Exception as e:
        logger.error(f"Unexpected LSP error: {e}", exc_info=True)
        # Continue without LSP context

    # Assemble context from available layers
    if not context_parts:
        raise ContextLoadError("All context layers failed. Cannot load context.")

    # User notification (only if LSP failed but others succeeded)
    if "lsp" not in dict(context_parts) and len(context_parts) > 0:
        logger.info("[INFO] LSP unavailable, using ClarAIty + RAG (reduced symbol precision)")

    return self._assemble_context(context_parts, max_tokens)
```

**Error Categories**:

| Error Type | Handling | User Notification |
|------------|----------|-------------------|
| **Server not installed** | Auto-download via multilspy, fall back to RAG if fails | [INFO] Downloading {lang} server... |
| **Server crashes** | Log error, fall back to RAG | [WARN] LSP server crashed, using RAG |
| **Query timeout (>5s)** | Cancel query, use RAG | [WARN] LSP query timeout, using RAG |
| **Unsupported language** | Skip LSP, use RAG | [INFO] {lang} not supported, using RAG |
| **File not found** | Return error (don't degrade) | [FAIL] File not found: {path} |

**Logging Strategy**:
```python
# src/code_intelligence/logging_config.py

import logging
from pathlib import Path

def setup_lsp_logging(debug: bool = False):
    """Setup logging for LSP components."""
    logger = logging.getLogger("code_intelligence")
    logger.setLevel(logging.DEBUG if debug else logging.INFO)

    # File handler (all logs)
    log_file = Path(".lsp_debug.log")
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "[%(asctime)s] %(levelname)s [%(name)s] %(message)s"
    ))
    logger.addHandler(file_handler)

    # Console handler (only warnings and errors)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(logging.Formatter(
        "[%(levelname)s] %(message)s"
    ))
    logger.addHandler(console_handler)

    return logger
```

**Diagnostic Command** (for debugging):
```python
# CLI command: python src/cli.py lsp-status

def lsp_status_command():
    """Show LSP server status and diagnostics."""
    manager = get_lsp_manager()

    print("[LSP SERVER STATUS]")
    print()

    if not manager.servers:
        print("[INFO] No LSP servers running")
        return

    for (repo, lang), server in manager.servers.items():
        status = "running" if server.is_alive() else "crashed"
        mem_mb = estimate_memory(server)
        uptime = time.time() - server.start_time

        print(f"[{status.upper()}] {lang} ({Path(repo).name})")
        print(f"  Memory: {mem_mb}MB")
        print(f"  Uptime: {uptime:.1f}s")
        print(f"  Queries: {server.query_count}")
        print(f"  Cache hits: {server.cache_hits}/{server.cache_hits + server.cache_misses} ({server.cache_hit_rate:.1f}%)")
        print()

    print(f"Total memory: {sum(estimate_memory(s) for s in manager.servers.values())}MB")
    print(f"Cache size: {manager.cache.size_mb():.1f}MB")
    print()
    print(f"Logs: .lsp_debug.log")
```

**Rationale**:
- **Graceful degradation**: Agent continues working even if LSP fails
- **Logging**: Errors logged to file (`.lsp_debug.log`) for debugging
- **User feedback**: Warnings shown in console (not intrusive)
- **Diagnostic command**: Users can check status (`lsp-status`)
- **Fail-fast for user errors**: File not found → return error (don't hide user mistakes)

---

## MCP Server Architecture

### Overview

**Purpose**: Expose LSP + ClarAIty + RAG as MCP tools following industry SOTA pattern

**Technology**: FastMCP (Anthropic's Python SDK)

**Protocol**: JSON-RPC 2.0 over stdio (standard MCP transport)

### MCP Primitives to Implement

**Tools** (executable functions):
```python
# LSP Tools (fine-grained)
@mcp.tool()
async def get_symbol_definition(file_path: str, line: int, column: int) -> dict:
    """Get symbol definition at cursor position using LSP."""

@mcp.tool()
async def get_symbol_references(file_path: str, line: int, column: int) -> list:
    """Find all references to symbol using LSP."""

@mcp.tool()
async def get_symbol_hover(file_path: str, line: int, column: int) -> dict:
    """Get hover info (type, documentation) using LSP."""

@mcp.tool()
async def get_document_symbols(file_path: str) -> list:
    """Get all symbols in document using LSP."""

# High-level tools (coarse-grained)
@mcp.tool()
async def analyze_symbol(file_path: str, line: int, column: int) -> dict:
    """Analyze symbol: definition + references + hover combined."""

@mcp.tool()
async def search_code_with_lsp(query: str, language: str) -> list:
    """Search workspace symbols using LSP."""

@mcp.tool()
async def load_smart_context(task_description: str, max_tokens: int = 2000) -> dict:
    """Load multi-tier context (ClarAIty + RAG + LSP) for task."""
```

**Resources** (read-only data):
```python
@mcp.resource("clarity://components/{component_id}")
def get_component_details(component_id: str) -> str:
    """Get ClarAIty component details."""

@mcp.resource("lsp://definitions/{file_path}:{line}:{column}")
def get_cached_definition(file_path: str, line: int, column: int) -> str:
    """Get cached symbol definition (if available)."""

@mcp.resource("lsp://workspace/symbols")
def get_workspace_symbols() -> str:
    """Get all workspace symbols (cached)."""
```

**Prompts** (templates):
```python
@mcp.prompt()
def code_review_prompt(file_path: str, focus: str = "security") -> str:
    """Generate code review prompt with specific focus."""

@mcp.prompt()
def refactor_prompt(component_id: str, goal: str) -> str:
    """Generate refactoring prompt based on ClarAIty component."""
```

### Server Implementation

```python
# src/code_intelligence/mcp_server.py

from mcp.server.fastmcp import FastMCP, Context
from contextlib import asynccontextmanager
import logging

from .lsp_manager import LSPClientManager
from .orchestrator import CodeIntelligenceOrchestrator
from src.clarity.core.database.clarity_db import ClarityDB

logger = logging.getLogger(__name__)

@asynccontextmanager
async def app_lifespan(server: FastMCP):
    """Manage MCP server lifespan (startup/shutdown)."""
    # Startup: Initialize components
    logger.info("Starting Code Intelligence MCP server...")

    lsp_manager = LSPClientManager(working_directory=Path.cwd())
    clarity_db = ClarityDB()
    orchestrator = CodeIntelligenceOrchestrator(
        lsp_manager=lsp_manager,
        clarity_db=clarity_db,
        retriever=None  # Will be set by agent
    )

    try:
        # Provide context to tools
        yield {
            "lsp_manager": lsp_manager,
            "clarity_db": clarity_db,
            "orchestrator": orchestrator
        }
    finally:
        # Shutdown: Cleanup resources
        logger.info("Shutting down Code Intelligence MCP server...")
        await lsp_manager.shutdown_all()

# Create MCP server
mcp = FastMCP(
    name="CodeIntelligence",
    version="1.0.0",
    lifespan=app_lifespan
)

# Tools
@mcp.tool()
async def get_symbol_definition(
    ctx: Context,
    file_path: str,
    line: int,
    column: int
) -> dict:
    """
    Get symbol definition at cursor position using LSP.

    Args:
        file_path: Absolute path to source file
        line: Line number (1-indexed)
        column: Column number (0-indexed)

    Returns:
        Symbol definition location and signature
    """
    lsp_manager = ctx.request_context["lsp_manager"]

    try:
        await ctx.info(f"Querying definition: {file_path}:{line}:{column}")

        result = await lsp_manager.request_definition(file_path, line, column)

        await ctx.info("[OK] Definition found")
        return result

    except Exception as e:
        await ctx.error(f"[FAIL] Definition query failed: {e}")
        raise

@mcp.tool()
async def get_symbol_references(
    ctx: Context,
    file_path: str,
    line: int,
    column: int
) -> list:
    """
    Find all references to symbol using LSP.

    Args:
        file_path: Absolute path to source file
        line: Line number (1-indexed)
        column: Column number (0-indexed)

    Returns:
        List of reference locations
    """
    lsp_manager = ctx.request_context["lsp_manager"]

    try:
        await ctx.info(f"Finding references: {file_path}:{line}:{column}")

        references = await lsp_manager.request_references(file_path, line, column)

        await ctx.info(f"[OK] Found {len(references)} references")
        return references

    except Exception as e:
        await ctx.error(f"[FAIL] References query failed: {e}")
        raise

@mcp.tool()
async def load_smart_context(
    ctx: Context,
    task_description: str,
    max_tokens: int = 2000,
    file_paths: list = None
) -> dict:
    """
    Load multi-tier context (ClarAIty + RAG + LSP) for coding task.

    Uses intelligent context loading strategy:
    - ClarAIty: Architectural overview (10% tokens)
    - RAG: Semantic search (20% tokens)
    - LSP: Symbol precision (20% tokens)

    Args:
        task_description: Description of the coding task
        max_tokens: Maximum tokens to load (default: 2000)
        file_paths: Optional list of files to focus on

    Returns:
        Multi-tier context dictionary
    """
    orchestrator = ctx.request_context["orchestrator"]

    try:
        await ctx.report_progress(0.0, 1.0)
        await ctx.info(f"Loading smart context for: {task_description[:60]}...")

        # Load context
        context = await orchestrator.load_smart_context(
            task_description=task_description,
            max_tokens=max_tokens,
            file_paths=file_paths
        )

        await ctx.report_progress(1.0, 1.0)
        await ctx.info(f"[OK] Loaded {context['token_count']} tokens across {context['layer_count']} layers")

        return context

    except Exception as e:
        await ctx.error(f"[FAIL] Context loading failed: {e}")
        raise

# Resources
@mcp.resource("clarity://components/{component_id}")
def get_component_details(component_id: str) -> str:
    """Get ClarAIty component details."""
    from src.clarity.core.database.clarity_db import ClarityDB

    db = ClarityDB()
    component = db.get_component(component_id)

    return f"""
Component: {component['name']}
ID: {component['component_id']}
Purpose: {component['purpose']}
Status: {component['status']}

Dependencies: {len(component['dependencies'])}
Key Files: {len(component['artifacts'])}
"""

# Prompts
@mcp.prompt()
def code_review_prompt(file_path: str, focus: str = "security") -> str:
    """Generate code review prompt with specific focus."""
    return f"""Review {file_path} with focus on {focus}.

Focus areas:
- {focus.title()} vulnerabilities and risks
- Best practices and patterns
- Potential improvements
- Edge cases and error handling

Provide specific, actionable feedback with line numbers and code examples.
"""

# Run server
if __name__ == "__main__":
    mcp.run()
```

### Server Deployment

**Development Mode** (with MCP Inspector - debugging UI):
```bash
uv run mcp dev src/code_intelligence/mcp_server.py
```

**Production Run**:
```bash
python src/code_intelligence/mcp_server.py
```

**Install to Claude Desktop** (for external use):
```bash
uv run mcp install src/code_intelligence/mcp_server.py
```

### Integration with Agent

**Option A: Direct Integration** (Recommended for Phase 1)
- Register MCP tools as native agent tools
- No MCP server process (tools call LSPClientManager directly)
- **Pros**: Simpler, no IPC overhead
- **Cons**: Can't be used by external agents

**Option B: MCP Client in Agent** (Future - Phase 2)
- Start MCP server as subprocess
- Agent connects via MCP client
- **Pros**: Can be used by external agents (Claude Code, Cursor)
- **Cons**: More complex, IPC overhead (~5-10ms)

**Decision**: **Option A for Phase 1** (direct integration)

```python
# src/core/agent.py

def _register_code_intelligence_tools(self) -> None:
    """Register Code Intelligence tools (direct integration, no MCP server)."""
    from src.tools.code_intelligence_tools import (
        GetSymbolDefinitionTool,
        GetSymbolReferencesTool,
        GetSymbolHoverTool,
        GetDocumentSymbolsTool,
        AnalyzeSymbolTool,
        SearchCodeWithLSPTool,
        LoadSmartContextTool,
    )

    # LSP manager factory (lazy initialization)
    def get_lsp_manager():
        if not self.lsp_manager:
            self.lsp_manager = LSPClientManager(working_directory=self.working_directory)
        return self.lsp_manager

    # Register tools
    self.tool_executor.register_tool(GetSymbolDefinitionTool(lsp_manager_factory=get_lsp_manager))
    self.tool_executor.register_tool(GetSymbolReferencesTool(lsp_manager_factory=get_lsp_manager))
    self.tool_executor.register_tool(GetSymbolHoverTool(lsp_manager_factory=get_lsp_manager))
    self.tool_executor.register_tool(GetDocumentSymbolsTool(lsp_manager_factory=get_lsp_manager))
    self.tool_executor.register_tool(AnalyzeSymbolTool(lsp_manager_factory=get_lsp_manager))
    self.tool_executor.register_tool(SearchCodeWithLSPTool(lsp_manager_factory=get_lsp_manager))
    self.tool_executor.register_tool(LoadSmartContextTool(
        lsp_manager_factory=get_lsp_manager,
        context_builder=self.context_builder,
        clarity_db=self.clarity_db
    ))
```

---

## LSP Integration Design

### LSPClientManager Architecture

**Purpose**: Manage multiple LSP servers (lazy initialization, query routing, caching, error handling)

**Core Responsibilities**:
1. Detect language from file extension
2. Start LSP servers on-demand (lazy initialization)
3. Route queries to appropriate server
4. Cache query results
5. Handle errors gracefully
6. Manage server lifecycle (startup, health checks, shutdown)

**Class Design**:

```python
# src/code_intelligence/lsp_manager.py

from typing import Dict, Tuple, Optional, List, Any
from pathlib import Path
import logging
from multilspy import LanguageServer
from multilspy.multilspy_config import MultilspyConfig

from .cache import LSPCache
from .config import CodeIntelligenceConfig

logger = logging.getLogger("code_intelligence.lsp_manager")

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
            Definition location and signature
        """
        # Check cache
        cache_key = f"def:{file_path}:{line}:{column}"
        cached = self.cache.get(cache_key)
        if cached:
            logger.debug(f"Cache hit: {cache_key}")
            return cached

        # Detect language and get server
        language = self._detect_language(file_path)
        repo_root = self._find_repository_root(file_path)
        server = await self.get_server(repo_root, language)

        # Query LSP server
        try:
            result = await server.request_definition(file_path, line, column)

            # Cache result
            self.cache.set(cache_key, result, file_path=file_path)

            return result

        except Exception as e:
            logger.error(f"LSP definition query failed: {e}", exc_info=True)
            raise LSPQueryError(f"Definition query failed: {e}") from e

    async def request_references(
        self,
        file_path: str,
        line: int,
        column: int
    ) -> List[Dict[str, Any]]:
        """Find all references to symbol."""
        # Similar to request_definition
        # ...

    async def request_hover(
        self,
        file_path: str,
        line: int,
        column: int
    ) -> Dict[str, Any]:
        """Get hover info (type, documentation)."""
        # Similar to request_definition
        # ...

    async def request_document_symbols(self, file_path: str) -> List[Dict[str, Any]]:
        """Get all symbols in document."""
        # Similar to request_definition
        # ...

    async def get_server(self, repo_root: str, language: str) -> LanguageServer:
        """
        Get or create LSP server for repository and language.

        Lazy initialization: Server starts on first query.
        Respects resource limits (max concurrent servers).

        Args:
            repo_root: Repository root path
            language: Programming language

        Returns:
            Running LanguageServer instance
        """
        key = (repo_root, language)

        if key in self.servers:
            return self.servers[key]

        # Check resource limits
        await self._check_server_limit(language)

        # Start server
        await self._start_server(repo_root, language)

        return self.servers[key]

    async def _start_server(self, repo_root: str, language: str) -> None:
        """Start LSP server for language."""
        key = (repo_root, language)

        logger.info(f"Starting {language} LSP server for {repo_root}")

        try:
            # Configure multilspy
            config = MultilspyConfig.from_dict({
                "code_language": language,
                "trace_lsp_communication": self.config.debug
            })

            # Create server (async context manager)
            server = await LanguageServer.create(
                config,
                logger,
                repo_root
            )

            # Start server
            await server.start_server()

            # Store server
            self.servers[key] = server

            logger.info(f"[OK] {language} server started ({Path(repo_root).name})")

        except Exception as e:
            logger.error(f"[FAIL] Failed to start {language} server: {e}", exc_info=True)
            raise LSPServerStartError(f"Failed to start {language} server: {e}") from e

    def _detect_language(self, file_path: str) -> str:
        """Detect language from file extension."""
        ext = Path(file_path).suffix.lower()

        # Check custom mappings first
        language = self.config.language_mappings.get(ext)
        if language:
            return language

        # Default mappings
        LANGUAGE_DETECTION = {
            ".py": "python", ".pyi": "python",
            ".ts": "typescript", ".tsx": "typescript",
            ".js": "javascript", ".jsx": "javascript",
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

    def _find_repository_root(self, file_path: str) -> str:
        """Find git repository root."""
        path = Path(file_path).resolve().parent

        while path != path.parent:
            if (path / ".git").exists():
                return str(path)
            path = path.parent

        # Fallback: file's parent directory
        return str(Path(file_path).parent)

    async def _check_server_limit(self, language: str) -> None:
        """Check if server limit exceeded, prompt user if needed."""
        current_count = len(self.servers)

        if current_count >= self.hard_limit:
            raise TooManyServersError(
                f"Hard limit of {self.hard_limit} LSP servers exceeded. "
                f"Currently running: {current_count}"
            )

        if current_count >= self.max_servers:
            # Soft limit exceeded - ask user (if interactive)
            approved = await self._prompt_server_approval(language, current_count)
            if not approved:
                raise UserRejectedServerError(
                    f"User declined to start {language} server (limit: {self.max_servers})"
                )

    async def _prompt_server_approval(self, language: str, current_count: int) -> bool:
        """Prompt user for approval to exceed soft limit."""
        # Implementation from Question 6
        # ...

    async def shutdown_all(self) -> None:
        """Shutdown all LSP servers."""
        logger.info("Shutting down all LSP servers...")

        for (repo, lang), server in self.servers.items():
            try:
                await server.shutdown_server()
                logger.info(f"[OK] Shut down {lang} server ({Path(repo).name})")
            except Exception as e:
                logger.warning(f"[WARN] Failed to shut down {lang} server: {e}")

        self.servers.clear()
        logger.info("All LSP servers shut down")

# Exceptions
class LSPError(Exception):
    """Base LSP error."""

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

### Language Support

**Phase 1 Priority** (auto-downloaded by multilspy):
1. **Python** (jedi-language-server) - Primary
2. **TypeScript/JavaScript** (typescript-language-server) - Web projects
3. **Rust** (rust-analyzer) - Systems programming

**Phase 2 Expansion**:
4. Go (gopls)
5. Java (jdtls)
6. Kotlin (kotlin-language-server)
7. C# (omnisharp)
8. Ruby (solargraph)
9. Dart (dart-analyzer)

### Performance Characteristics

**Server Initialization**:
- Python: 2-5 seconds (first time)
- TypeScript: 5-10 seconds (depends on project size)
- Rust: 10-30 seconds (full project analysis)

**Query Latency** (after init):
- Definition: 5-20ms
- References: 10-50ms
- Hover: 5-15ms
- Document symbols: 20-100ms

**Memory Usage**:
- Python: ~100MB per server
- TypeScript: ~200MB per server
- Rust: ~300MB per server

---

## Smart Context Loader Strategy

### Multi-Tier Loading Architecture

**Concept**: Different queries need different context layers

**Three Layers**:
1. **ClarAIty Layer** - Architectural overview (10% tokens)
2. **RAG Layer** - Semantic search (20% tokens)
3. **LSP Layer** - Symbol precision (20% tokens)

### Query Routing Logic

```python
# src/code_intelligence/orchestrator.py

from enum import Enum
from dataclasses import dataclass

class QueryType(Enum):
    ARCHITECTURAL = "architectural"  # "What does this component do?"
    SEMANTIC = "semantic"           # "Find similar error handling"
    SYMBOLIC = "symbolic"           # "What type does X return?"
    COMPLEX = "complex"             # "Refactor authentication"

@dataclass
class LayerWeights:
    """Token budget allocation across layers."""
    clarity: float  # 0.0 to 1.0
    rag: float      # 0.0 to 1.0
    lsp: float      # 0.0 to 1.0

    def __post_init__(self):
        total = self.clarity + self.rag + self.lsp
        if not (0.99 <= total <= 1.01):
            raise ValueError(f"Layer weights must sum to 1.0, got {total}")

class CodeIntelligenceOrchestrator:
    """
    Orchestrates multi-tier context loading.

    Combines ClarAIty (architecture) + RAG (semantic) + LSP (symbolic)
    to provide optimal context for coding tasks.
    """

    def __init__(
        self,
        lsp_manager: LSPClientManager,
        clarity_db: ClarityDB,
        retriever: HybridRetriever
    ):
        self.lsp_manager = lsp_manager
        self.clarity_db = clarity_db
        self.retriever = retriever

    async def load_smart_context(
        self,
        task_description: str,
        max_tokens: int = 2000,
        file_paths: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Load multi-tier context for coding task.

        Args:
            task_description: Description of the task
            max_tokens: Maximum tokens to load (default: 2000)
            file_paths: Optional files to focus on

        Returns:
            Multi-tier context dictionary
        """
        # Classify query type
        query_type = self._classify_query(task_description)

        # Get layer weights based on query type
        weights = self._get_layer_weights(query_type)

        # Calculate token budgets
        clarity_budget = int(max_tokens * weights.clarity)
        rag_budget = int(max_tokens * weights.rag)
        lsp_budget = int(max_tokens * weights.lsp)

        # Load each layer (parallel)
        clarity_context, rag_context, lsp_context = await asyncio.gather(
            self._load_clarity_layer(task_description, clarity_budget),
            self._load_rag_layer(task_description, rag_budget, file_paths),
            self._load_lsp_layer(task_description, lsp_budget, file_paths),
            return_exceptions=True
        )

        # Handle errors gracefully
        if isinstance(clarity_context, Exception):
            logger.warning(f"ClarAIty layer failed: {clarity_context}")
            clarity_context = ""

        if isinstance(rag_context, Exception):
            logger.warning(f"RAG layer failed: {rag_context}")
            rag_context = ""

        if isinstance(lsp_context, Exception):
            logger.warning(f"LSP layer failed: {lsp_context}")
            lsp_context = ""

        # Assemble final context
        return self._assemble_context(
            clarity=clarity_context,
            rag=rag_context,
            lsp=lsp_context,
            query_type=query_type
        )

    def _classify_query(self, task_description: str) -> QueryType:
        """Classify query type based on keywords."""
        task_lower = task_description.lower()

        # Architectural queries
        architectural_keywords = [
            "component", "architecture", "structure", "design",
            "how does", "what is", "explain", "overview"
        ]
        if any(kw in task_lower for kw in architectural_keywords):
            return QueryType.ARCHITECTURAL

        # Symbolic queries
        symbolic_keywords = [
            "type", "signature", "return", "parameter",
            "definition", "declaration", "interface"
        ]
        if any(kw in task_lower for kw in symbolic_keywords):
            return QueryType.SYMBOLIC

        # Semantic queries
        semantic_keywords = [
            "similar", "like", "example", "find",
            "search", "look for", "pattern"
        ]
        if any(kw in task_lower for kw in semantic_keywords):
            return QueryType.SEMANTIC

        # Default: Complex (refactoring, implementation)
        return QueryType.COMPLEX

    def _get_layer_weights(self, query_type: QueryType) -> LayerWeights:
        """Get layer weights based on query type."""
        WEIGHT_MAP = {
            QueryType.ARCHITECTURAL: LayerWeights(clarity=0.5, rag=0.3, lsp=0.2),
            QueryType.SEMANTIC: LayerWeights(clarity=0.1, rag=0.7, lsp=0.2),
            QueryType.SYMBOLIC: LayerWeights(clarity=0.1, rag=0.2, lsp=0.7),
            QueryType.COMPLEX: LayerWeights(clarity=0.33, rag=0.33, lsp=0.34),
        }
        return WEIGHT_MAP[query_type]

    async def _load_clarity_layer(
        self,
        task_description: str,
        budget: int
    ) -> str:
        """Load ClarAIty architectural context."""
        # Extract keywords
        keywords = self._extract_keywords(task_description)

        # Search components
        components = []
        for keyword in keywords:
            matches = self.clarity_db.search_components(keyword)
            components.extend(matches[:2])  # Top 2 per keyword

        # Format context
        if not components:
            return ""

        context_parts = []
        token_count = 0

        for component in components:
            component_text = f"""
[COMPONENT] {component['name']}
Purpose: {component['purpose']}
Status: {component['status']}
Key Files: {', '.join(component['key_files'][:3])}
"""
            component_tokens = self._count_tokens(component_text)

            if token_count + component_tokens > budget:
                break

            context_parts.append(component_text)
            token_count += component_tokens

        return "\n".join(context_parts)

    async def _load_rag_layer(
        self,
        task_description: str,
        budget: int,
        file_paths: Optional[List[str]]
    ) -> str:
        """Load RAG semantic context."""
        # Search with filters
        filters = {}
        if file_paths:
            filters["file_path"] = "|".join(file_paths)  # Regex OR

        # Determine top_k from budget
        # Assume ~400 tokens per chunk
        top_k = max(1, budget // 400)

        results = self.retriever.search(
            query=task_description,
            chunks=self.indexed_chunks,
            top_k=top_k,
            filters=filters
        )

        # Format context
        if not results:
            return ""

        context_parts = []
        token_count = 0

        for i, result in enumerate(results, 1):
            chunk_text = f"""
[RELEVANT CODE {i}] (score: {result.score:.2f})
File: {result.chunk.file_path}:{result.chunk.start_line}
```{result.chunk.language}
{result.chunk.content}
```
"""
            chunk_tokens = self._count_tokens(chunk_text)

            if token_count + chunk_tokens > budget:
                break

            context_parts.append(chunk_text)
            token_count += chunk_tokens

        return "\n".join(context_parts)

    async def _load_lsp_layer(
        self,
        task_description: str,
        budget: int,
        file_paths: Optional[List[str]]
    ) -> str:
        """Load LSP symbol context."""
        if not file_paths:
            # No specific files, can't query LSP
            return ""

        context_parts = []
        token_count = 0

        for file_path in file_paths:
            # Get document symbols
            try:
                symbols = await self.lsp_manager.request_document_symbols(file_path)

                # Format symbols
                for symbol in symbols[:10]:  # Top 10 symbols
                    symbol_text = f"""
[SYMBOL] {symbol['name']} ({symbol['kind']})
Location: {file_path}:{symbol['range']['start']['line']}
Signature: {symbol.get('detail', 'N/A')}
"""
                    symbol_tokens = self._count_tokens(symbol_text)

                    if token_count + symbol_tokens > budget:
                        break

                    context_parts.append(symbol_text)
                    token_count += symbol_tokens

            except Exception as e:
                logger.warning(f"LSP document symbols failed for {file_path}: {e}")
                continue

        return "\n".join(context_parts)

    def _assemble_context(
        self,
        clarity: str,
        rag: str,
        lsp: str,
        query_type: QueryType
    ) -> Dict[str, Any]:
        """Assemble final context from layers."""
        context_sections = []

        if clarity:
            context_sections.append(f"<architectural_context>\n{clarity}\n</architectural_context>")

        if rag:
            context_sections.append(f"<relevant_code>\n{rag}\n</relevant_code>")

        if lsp:
            context_sections.append(f"<symbol_definitions>\n{lsp}\n</symbol_definitions>")

        final_context = "\n\n".join(context_sections)

        return {
            "context": final_context,
            "token_count": self._count_tokens(final_context),
            "layer_count": len(context_sections),
            "query_type": query_type.value,
            "layers": {
                "clarity": bool(clarity),
                "rag": bool(rag),
                "lsp": bool(lsp)
            }
        }

    def _extract_keywords(self, text: str) -> List[str]:
        """Extract keywords from text."""
        # Simple keyword extraction
        # TODO: Use NLP library (spaCy, NLTK) for better extraction
        words = text.lower().split()
        stopwords = {"the", "a", "an", "in", "on", "at", "to", "for", "of", "and", "or"}
        keywords = [w for w in words if len(w) > 3 and w not in stopwords]
        return keywords[:5]  # Top 5 keywords

    def _count_tokens(self, text: str) -> int:
        """Count tokens (simple approximation)."""
        # Approximation: 1 token ≈ 4 characters
        return len(text) // 4
```

### Context Assembly Order

```
┌──────────────────────────────────────────┐
│ FINAL CONTEXT (2000 tokens)             │
├──────────────────────────────────────────┤
│                                          │
│ 1. ARCHITECTURAL CONTEXT (200 tokens)   │
│    <architectural_context>              │
│    [COMPONENT] Authentication           │
│    Purpose: User authentication...      │
│    Key Files: auth.py, login.py...      │
│    </architectural_context>             │
│                                          │
│ 2. RELEVANT CODE (400 tokens)           │
│    <relevant_code>                      │
│    [RELEVANT CODE 1] (score: 0.85)      │
│    File: auth.py:45                     │
│    ```python                            │
│    def authenticate(...)                │
│    ```                                  │
│    </relevant_code>                     │
│                                          │
│ 3. SYMBOL DEFINITIONS (400 tokens)      │
│    <symbol_definitions>                 │
│    [SYMBOL] authenticate (function)     │
│    Location: auth.py:45                 │
│    Signature: (username, password) -> bool
│    </symbol_definitions>                │
│                                          │
└──────────────────────────────────────────┘
```

---

## Implementation Plan

### Components to Build

**1. LSPClientManager** (`src/code_intelligence/lsp_manager.py`)
- **Lines**: ~400 LOC
- **Dependencies**: multilspy, pathlib, logging
- **Time**: 1.5 hours

**Key Methods**:
- `request_definition()`, `request_references()`, `request_hover()`, `request_document_symbols()`
- `get_server()` - Lazy initialization
- `_detect_language()`, `_find_repository_root()`
- `_check_server_limit()`, `_prompt_server_approval()`
- `shutdown_all()`

**2. LSPCache** (`src/code_intelligence/cache.py`)
- **Lines**: ~200 LOC
- **Dependencies**: collections.OrderedDict, pathlib
- **Time**: 0.5 hours

**Key Methods**:
- `get()`, `set()` - LRU cache operations
- `_file_modified()` - File change detection
- `_invalidate_file()` - Cache invalidation
- `_size_mb()` - Memory tracking

**3. CodeIntelligenceOrchestrator** (`src/code_intelligence/orchestrator.py`)
- **Lines**: ~500 LOC
- **Dependencies**: LSPClientManager, ClarityDB, HybridRetriever
- **Time**: 1.5 hours

**Key Methods**:
- `load_smart_context()` - Multi-tier loading
- `_classify_query()` - Query type detection
- `_get_layer_weights()` - Token budget allocation
- `_load_clarity_layer()`, `_load_rag_layer()`, `_load_lsp_layer()`
- `_assemble_context()` - Final context assembly

**4. CodeIntelligenceConfig** (`src/code_intelligence/config.py`)
- **Lines**: ~150 LOC
- **Dependencies**: json, os, pathlib
- **Time**: 0.5 hours

**Key Methods**:
- `_load_config()` - Hierarchical config loading
- `get_server_for_language()` - LSP server configuration

**5. Code Intelligence Tools** (`src/tools/code_intelligence_tools.py`)
- **Lines**: ~400 LOC
- **Dependencies**: Tool base class, LSPClientManager
- **Time**: 1 hour

**Tools to Implement**:
- `GetSymbolDefinitionTool`, `GetSymbolReferencesTool`, `GetSymbolHoverTool`
- `GetDocumentSymbolsTool`, `AnalyzeSymbolTool`
- `SearchCodeWithLSPTool`, `LoadSmartContextTool`

**6. Tool Schemas** (`src/tools/tool_schemas.py`)
- **Lines**: ~200 LOC additions
- **Dependencies**: LLMBackend.ToolDefinition
- **Time**: 0.5 hours

**Schemas to Add**:
- `GET_SYMBOL_DEFINITION_TOOL`, `GET_SYMBOL_REFERENCES_TOOL`, etc.
- Add to `ALL_TOOLS` list

**7. ContextBuilder Enhancement** (`src/core/context_builder.py`)
- **Lines**: ~150 LOC additions
- **Dependencies**: CodeIntelligenceOrchestrator
- **Time**: 0.5 hours

**Changes**:
- Add `lsp_manager`, `orchestrator` parameters to `__init__`
- Add `use_lsp`, `use_clarity` parameters to `build_context()`
- Update token budget allocation
- Add LSP and ClarAIty context assembly

**8. Agent Integration** (`src/core/agent.py`)
- **Lines**: ~100 LOC additions
- **Dependencies**: Code Intelligence components
- **Time**: 0.5 hours

**Changes**:
- Initialize `lsp_manager`, `orchestrator` (lazy)
- Call `_register_code_intelligence_tools()`
- Update `ContextBuilder` initialization

**9. MCP Server** (`src/code_intelligence/mcp_server.py`) - **OPTIONAL Phase 2**
- **Lines**: ~300 LOC
- **Dependencies**: FastMCP, code intelligence components
- **Time**: 1 hour

**Implementation**: FastMCP server exposing tools as MCP primitives

---

### Timeline

**Week 1**: Foundation (LSPClientManager, Cache, Config)
- Day 1-2: LSPClientManager (400 LOC, 1.5 hours)
- Day 2: LSPCache (200 LOC, 0.5 hours)
- Day 2-3: CodeIntelligenceConfig (150 LOC, 0.5 hours)
- Day 3: Integration tests with real LSP servers (1 hour)

**Week 2**: Orchestration (Smart Context Loader)
- Day 1-2: CodeIntelligenceOrchestrator (500 LOC, 1.5 hours)
- Day 2-3: Unit tests for orchestrator (1 hour)
- Day 3: End-to-end context loading tests (1 hour)

**Week 3**: Tools & Integration
- Day 1: Code Intelligence Tools (400 LOC, 1 hour)
- Day 1-2: Tool Schemas (200 LOC, 0.5 hours)
- Day 2: ContextBuilder enhancements (150 LOC, 0.5 hours)
- Day 2-3: Agent integration (100 LOC, 0.5 hours)
- Day 3: Integration tests (agent + tools + LSP) (1 hour)

**Week 4**: Testing & Validation
- Day 1: Performance validation (token efficiency, latency) (2 hours)
- Day 2: Code review (code-reviewer subagent) (1 hour)
- Day 2-3: Bug fixes and polish (2 hours)
- Day 3: Documentation (1 hour)

**Total**: ~4 weeks (7-10 hours actual implementation + testing)

---

### Dependencies

**Python Packages**:
```bash
# Install MCP SDK
pip install "mcp[cli]"

# Install LSP client
pip install multilspy

# Existing dependencies (already installed)
# openai, anthropic, rich, etc.
```

**External Tools** (auto-downloaded by multilspy):
- jedi-language-server (Python)
- typescript-language-server (TypeScript/JavaScript)
- rust-analyzer (Rust)
- Other language servers (downloaded on first use)

---

### Testing Strategy

**Unit Tests**:
- `tests/test_lsp_manager.py` - Mock multilspy, test query routing
- `tests/test_lsp_cache.py` - Test caching, invalidation
- `tests/test_orchestrator.py` - Test multi-tier loading, query classification
- `tests/test_code_intelligence_tools.py` - Test tool execution

**Integration Tests**:
- `tests/test_lsp_integration_python.py` - Real Python LSP server
- `tests/test_lsp_integration_typescript.py` - Real TypeScript LSP server
- `tests/test_smart_context_loading.py` - End-to-end context loading

**End-to-End Tests**:
- `tests/test_agent_with_code_intelligence.py` - Agent + LSP + tools
- `tests/test_multi_tier_queries.py` - Various query types (architectural, semantic, symbolic)

**Performance Tests**:
- `tests/test_lsp_performance.py` - Latency, memory usage
- `tests/test_context_efficiency.py` - Token efficiency (before/after)

---

## Migration & Rollout Strategy

### Feature Flag Configuration

**`.env` Settings**:
```bash
# Code Intelligence (default: disabled for Phase 1)
ENABLE_CODE_INTELLIGENCE=false

# Once stable (Phase 2)
ENABLE_CODE_INTELLIGENCE=true

# Beta flag (opt-in testing)
CODE_INTELLIGENCE_BETA=false
```

**In Code**:
```python
# src/core/agent.py

def __init__(self, ...):
    # ...

    # Code Intelligence (feature flag)
    enable_code_intelligence = os.getenv("ENABLE_CODE_INTELLIGENCE", "false").lower() == "true"

    if enable_code_intelligence:
        self._initialize_code_intelligence()
    else:
        self.lsp_manager = None
        self.orchestrator = None
```

### Rollout Phases

**Phase 1: Development** (Week 1-3)
- Feature disabled by default (`ENABLE_CODE_INTELLIGENCE=false`)
- Developers enable manually for testing
- All existing tests must pass with feature disabled
- New tests added for Code Intelligence components

**Phase 2: Internal Beta** (Week 4)
- Feature enabled for beta users (`CODE_INTELLIGENCE_BETA=true`)
- Collect feedback, monitor performance
- Bug fixes, polish

**Phase 3: General Availability** (Week 5+)
- Feature enabled by default (`ENABLE_CODE_INTELLIGENCE=true`)
- Documentation updated
- Announcement to users

### Backward Compatibility Validation

**Requirements**:
1. All existing tests pass with feature disabled
2. `agent.chat()` API unchanged
3. `agent.execute_task()` API unchanged
4. RAG-only mode still works (if LSP disabled)
5. No performance regression for existing workflows

**Testing**:
```bash
# Run all tests with Code Intelligence disabled
ENABLE_CODE_INTELLIGENCE=false pytest

# Run all tests with Code Intelligence enabled
ENABLE_CODE_INTELLIGENCE=true pytest

# Both must pass
```

---

## Performance Targets & Validation

### Performance Targets

**Token Efficiency**:
- **Goal**: 50%+ reduction in context tokens for same queries
- **Baseline**: Current RAG-only (3 chunks × 400 tokens = 1,200 tokens)
- **Target**: ClarAIty + RAG + LSP (200 + 400 + 400 = 1,000 tokens)
- **Validation**: Compare before/after for 10 sample queries

**Latency**:
- **First LSP query**: <10 seconds (including server initialization)
- **Subsequent queries**: <100ms (cached server)
- **Context assembly**: <2 seconds total (all layers)
- **Validation**: Benchmark with timer decorators

**Memory Usage**:
- **3 LSP servers**: <900MB (Python + TypeScript + Rust)
- **Cache**: <10MB
- **Total overhead**: <1GB
- **Validation**: Monitor with `psutil` library

**Accuracy**:
- **Subjective**: Test on 10 sample queries
- **Validation**: Compare LLM responses with/without Code Intelligence
- **Expectation**: Equal or better quality with fewer tokens

### Validation Metrics

**Metric 1: Token Efficiency**
```python
# tests/test_context_efficiency.py

def test_token_efficiency():
    """Validate token reduction with Code Intelligence."""
    queries = [
        "What does the authenticate function do?",
        "Find all references to authenticate",
        "What type does authenticate return?",
        "Refactor authentication to support OAuth",
        # ... 6 more queries
    ]

    for query in queries:
        # Before: RAG-only
        context_before = context_builder.build_context(
            user_query=query,
            use_rag=True,
            use_lsp=False,
            use_clarity=False
        )
        tokens_before = count_tokens(context_before)

        # After: ClarAIty + RAG + LSP
        context_after = context_builder.build_context(
            user_query=query,
            use_rag=True,
            use_lsp=True,
            use_clarity=True
        )
        tokens_after = count_tokens(context_after)

        # Calculate reduction
        reduction = (tokens_before - tokens_after) / tokens_before

        print(f"Query: {query[:50]}...")
        print(f"  Before: {tokens_before} tokens")
        print(f"  After: {tokens_after} tokens")
        print(f"  Reduction: {reduction * 100:.1f}%")

        # Target: 30%+ reduction (50% is ideal)
        assert reduction >= 0.3, f"Token reduction {reduction:.1%} < 30%"
```

**Metric 2: Latency**
```python
# tests/test_lsp_performance.py

import time

def test_lsp_query_latency():
    """Validate LSP query latency."""
    lsp_manager = LSPClientManager(working_directory=Path.cwd())

    # First query (includes server initialization)
    start = time.time()
    result = await lsp_manager.request_definition("src/auth.py", 45, 10)
    first_query_time = time.time() - start

    print(f"First query (with init): {first_query_time:.2f}s")
    assert first_query_time < 10.0, f"First query {first_query_time:.2f}s > 10s"

    # Subsequent queries (server already running)
    timings = []
    for _ in range(10):
        start = time.time()
        result = await lsp_manager.request_definition("src/auth.py", 45, 10)
        timings.append(time.time() - start)

    avg_query_time = sum(timings) / len(timings)
    print(f"Subsequent queries (avg): {avg_query_time * 1000:.1f}ms")
    assert avg_query_time < 0.1, f"Avg query {avg_query_time * 1000:.1f}ms > 100ms"
```

**Metric 3: Memory Usage**
```python
# tests/test_lsp_memory.py

import psutil
import os

def test_lsp_memory_usage():
    """Validate LSP memory usage."""
    process = psutil.Process(os.getpid())

    # Baseline memory
    baseline_mb = process.memory_info().rss / 1024 / 1024

    # Start 3 LSP servers
    lsp_manager = LSPClientManager(working_directory=Path.cwd())
    await lsp_manager.get_server(".", "python")
    await lsp_manager.get_server(".", "typescript")
    await lsp_manager.get_server(".", "rust")

    # Measure memory
    with_lsp_mb = process.memory_info().rss / 1024 / 1024
    lsp_overhead_mb = with_lsp_mb - baseline_mb

    print(f"Baseline: {baseline_mb:.1f}MB")
    print(f"With LSP: {with_lsp_mb:.1f}MB")
    print(f"Overhead: {lsp_overhead_mb:.1f}MB")

    # Target: <900MB for 3 servers
    assert lsp_overhead_mb < 900, f"LSP overhead {lsp_overhead_mb:.1f}MB > 900MB"
```

**Metric 4: Accuracy (Qualitative)**
- Test on 10 sample queries
- Compare LLM responses with/without Code Intelligence
- Subjective evaluation (better, same, worse)

---

## Risk Mitigation

### Risk 1: LSP Server Crashes

**Likelihood**: Medium (LSP servers can crash on malformed code)

**Impact**: High (queries fail, poor UX)

**Mitigation**:
- Graceful degradation (fall back to RAG)
- Auto-restart crashed servers (max 3 retries)
- Health checks (periodic ping)
- User notification ([WARN] LSP server crashed, restarting...)

**Implementation**:
```python
async def request_definition(self, ...):
    try:
        result = await server.request_definition(...)
        return result
    except ServerCrashError as e:
        logger.error(f"LSP server crashed: {e}")

        # Attempt restart (max 3 retries)
        for retry in range(3):
            try:
                await self._restart_server(language)
                result = await server.request_definition(...)
                logger.info(f"[OK] Recovered after {retry + 1} retries")
                return result
            except Exception:
                if retry == 2:
                    # Give up, fall back to RAG
                    logger.warning("[FAIL] LSP server unrecoverable, using RAG")
                    raise LSPServerError("Server unrecoverable") from e
```

### Risk 2: Token Budget Misallocation

**Likelihood**: Medium (may over/under-allocate layers)

**Impact**: Medium (suboptimal context quality)

**Mitigation**:
- Adaptive allocation (adjust based on query type)
- Validation metrics (measure token efficiency)
- Tuneable weights (configuration)
- A/B testing (compare different allocations)

**Implementation**:
- Start with conservative allocation (10/20/20)
- Measure performance on sample queries
- Tune weights based on results
- Allow configuration override (`.env`)

### Risk 3: Windows Compatibility Issues

**Likelihood**: Medium (emoji encoding, path separators)

**Impact**: High (crashes on Windows)

**Mitigation**:
- No emojis (use text markers: [OK], [FAIL])
- Path normalization (use `Path()` everywhere)
- Test on Windows (CI/CD)
- Use `safe_print()` utility

**Implementation**:
- Code review checklist: No emojis
- CI/CD: Run tests on Windows
- Manual testing: Test on Windows 10/11

### Risk 4: Performance Degradation

**Likelihood**: Low (LSP queries are fast)

**Impact**: Medium (slower agent responses)

**Mitigation**:
- Caching (reduce redundant queries)
- Lazy initialization (don't start unused servers)
- Parallel queries (definition + references in parallel)
- Progress indicators (show user what's happening)
- Performance benchmarks (validate targets)

**Implementation**:
- Benchmark before/after
- Monitor latency in production
- User feedback (is it slow?)

### Risk 5: Configuration Complexity

**Likelihood**: Low (auto-detection handles 95%)

**Impact**: Low (users can't customize if needed)

**Mitigation**:
- Zero config by default (auto-detection)
- Clear documentation (for overrides)
- Example config files (`.code-intelligence.json`)
- Diagnostic command (`lsp-status`)

**Implementation**:
- Write clear docs
- Provide examples
- Test common scenarios

---

## Summary

### Architecture Finalized

**Full MCP + LSP Integration (Option B)** - Production-grade, industry SOTA

**Components**:
1. LSPClientManager - Lazy initialization, multi-repo, caching
2. CodeIntelligenceOrchestrator - Multi-tier context loading
3. MCP Server - FastMCP exposing tools (Phase 2)
4. 7 Code Intelligence Tools - Hybrid fine/coarse-grained
5. Enhanced ContextBuilder - Token reallocation (ClarAIty 10%, RAG 20%, LSP 20%)

**Total Implementation**: ~1,750 LOC, ~7-10 hours

### Key Decisions Made

| Decision | Choice | Confidence |
|----------|--------|------------|
| Tool Granularity | Hybrid (fine + coarse) | High |
| Caching | In-memory LRU + file invalidation | High |
| Multi-Repo | One server per repo | High |
| Configuration | Auto-detect + overrides | High |
| Progress | Rich Status + MCP progress | High |
| Resource Limits | Soft limit (3 servers) | Medium |
| Error Handling | Graceful degradation | High |

### Next Steps

**Phase C: Implementation Specs** (~30 min)
- Populate ClarAIty with method signatures, acceptance criteria, patterns
- Use mutation tools from Phase 0

**Phase D: Implementation** (~7-10 hours)
- Build all components
- Write tests
- Validate performance

**Phase E: Code Review & Validation** (~2 hours)
- Code-reviewer subagent
- Performance benchmarks
- Bug fixes

**Total Time to Production**: ~3-4 weeks (part-time development)

---

**End of Design Decisions Document**

**Status**: ✅ Complete - Ready for Implementation
**Next Action**: Populate implementation specs in ClarAIty DB
