# Web Search Capabilities

Production-grade web search and fetch tools for the AI coding agent, featuring comprehensive security controls, provider abstraction, and intelligent resource management.

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Security Features](#security-features)
4. [API Reference](#api-reference)
5. [Usage Examples](#usage-examples)
6. [Configuration](#configuration)
7. [Adding New Providers](#adding-new-providers)
8. [Testing](#testing)

---

## Overview

The web search capabilities enable the AI agent to:

- **Search the web** for current information (documentation, error messages, library versions, best practices)
- **Fetch URL content** directly (documentation pages, API responses, known resources)

### Why Web Search Matters

AI coding agents often need access to:
- Latest library documentation and changelogs
- Error message solutions from Stack Overflow
- Current best practices and patterns
- API references and specifications
- Real-time information beyond the training cutoff

### Design Principles

1. **Security First**: SSRF protection, content-type allowlists, and byte caps prevent abuse
2. **Cost Control**: Per-turn budgets and rate limiting prevent runaway API costs
3. **Provider Agnostic**: Abstract interface allows swapping search providers without code changes
4. **Cache Efficient**: TTL caching reduces redundant API calls and improves response time
5. **Observability**: Structured logging for all operations enables debugging and monitoring

---

## Architecture

### Component Diagram

```
+------------------+     +------------------+
|  WebSearchTool   |     |  WebFetchTool    |
|------------------|     |------------------|
| - provider       |     | - cache          |
| - cache          |     | - timeout        |
| - rate_limiter   |     | - max_bytes      |
| - run_budget     |     | - run_budget     |
+--------+---------+     +--------+---------+
         |                        |
         v                        v
+------------------+     +------------------+
| WebSearchProvider|     |   UrlSafety      |
| (ABC)            |     |------------------|
|------------------|     | - validate()     |
| + search()       |     | - is_ip_blocked()|
+--------+---------+     | - DNS resolution |
         |               +------------------+
         v
+------------------+
|  TavilyProvider  |
|------------------|
| - API_URL        |
| - api_key        |
| + search()       |
+------------------+
```

### Class Hierarchy

```
Tool (base.py)
  |
  +-- WebSearchTool
  |     - Uses WebSearchProvider interface
  |     - Manages caching, rate limiting, budgets
  |
  +-- WebFetchTool
        - Uses UrlSafety for SSRF protection
        - Streaming byte cap enforcement
        - Content-type validation

WebSearchProvider (ABC)
  |
  +-- TavilyProvider
        - Tavily API v1 implementation
        - Supports include/exclude domains

Helper Classes:
  - TTLCache: Thread-safe TTL cache
  - RateLimiter: Token bucket rate limiter
  - RunBudget: Per-turn budget tracker
  - UrlSafety: SSRF protection utilities
```

### Data Flow

**Web Search Flow:**
```
1. User query arrives
2. Check run budget (max_searches per turn)
3. Check cache (1-hour TTL)
4. Check rate limiter (10 req/min)
5. Call TavilyProvider.search()
6. Format results with citations
7. Cache and return
```

**Web Fetch Flow:**
```
1. URL arrives
2. Check run budget (max_fetches per turn)
3. UrlSafety.validate() - SSRF checks
4. Check cache (15-min TTL)
5. HTTP GET with streaming
6. Validate content-type
7. Apply byte cap (100KB)
8. Extract text if HTML
9. Cache and return
```

---

## Security Features

The web tools implement defense-in-depth with multiple security layers.

### 1. SSRF Protection (Server-Side Request Forgery)

The `UrlSafety` class prevents the agent from accessing internal network resources.

**Checks Performed:**
- **Scheme Validation**: Only `http://` and `https://` allowed
- **URL Length**: Maximum 2048 characters
- **Port Restriction**: Only ports 80 and 443 allowed (v1 minimal surface)
- **Hostname Blocklist**: `localhost`, `*.local`, `*.internal`, `*.localdomain`
- **DNS Resolution**: Resolves hostname before request, blocks if ANY IP is private
- **IP Range Blocking**: Blocks all private, loopback, link-local, and reserved ranges

**Blocked IP Ranges:**
```
RFC1918 Private:
  - 10.0.0.0/8       (Class A private)
  - 172.16.0.0/12    (Class B private)
  - 192.168.0.0/16   (Class C private)

Special Purpose:
  - 127.0.0.0/8      (Loopback)
  - 169.254.0.0/16   (Link-local, includes cloud metadata)
  - 100.64.0.0/10    (CGNAT)
  - 0.0.0.0/8        ("This" network)
  - 224.0.0.0/4      (Multicast)
  - 240.0.0.0/4      (Reserved)

IPv6:
  - ::1/128          (Loopback)
  - fc00::/7         (ULA)
  - fe80::/10        (Link-local)
  - ff00::/8         (Multicast)
```

**Cloud Metadata Protection:**
```
Explicitly blocked IPs:
  - 169.254.169.254  (AWS/GCP/Azure metadata)
  - fd00:ec2::254    (AWS IMDSv2)
```

### 2. Content-Type Allowlist

Only text-based content types are allowed to prevent binary file downloads:

```python
ALLOWED_CONTENT_TYPES = {
    'text/html',
    'text/plain',
    'text/xml',
    'text/markdown',
    'text/css',
    'text/javascript',
    'application/json',
    'application/xml',
    'application/xhtml+xml',
    'application/javascript',
}
```

Additionally, any `text/*` content type is allowed.

**Blocked:**
- `application/pdf`
- `image/*`
- `video/*`
- `application/octet-stream`
- Binary formats

### 3. Streaming Byte Cap

Content is read via streaming with a byte cap (default: 100KB):

```python
for chunk in response.iter_bytes(chunk_size=8192):
    bytes_read += len(chunk)
    chunks.append(chunk)
    if bytes_read >= self.max_bytes:
        break  # Stop reading, don't download entire file
```

This prevents:
- Memory exhaustion from large files
- Slow responses from downloading gigabyte files
- Wasted bandwidth on content that will be truncated anyway

### 4. Per-Turn Budget Limits

The `RunBudget` class limits operations per user turn:

| Resource | Default Limit | Purpose |
|----------|---------------|---------|
| Searches | 3 per turn | Prevent runaway API costs |
| Fetches | 5 per turn | Prevent excessive network usage |

When budget is exceeded, the tool returns an error asking the user for permission to continue.

### 5. Rate Limiting

The `RateLimiter` class implements token bucket rate limiting:

- **Limit**: 10 requests per minute (configurable)
- **Behavior**: If rate limited, waits up to 10 seconds; longer waits return an error
- **Scope**: Per WebSearchTool instance (shared across agent lifetime)

### 6. No Redirect Following

`WebFetchTool` does not follow redirects (`follow_redirects=False`):

- **Rationale**: Redirects can be used to bypass SSRF protection
- **Behavior**: Returns error with redirect target URL, user can fetch directly
- **Example**: `http://evil.com/redirect?url=http://169.254.169.254/` would be blocked

---

## API Reference

### TTLCache

Thread-safe TTL cache for web tool results.

```python
class TTLCache:
    def __init__(self, ttl_seconds: int = 3600)
    def get(self, key: str) -> Optional[Any]
    def set(self, key: str, value: Any) -> None
    def clear(self) -> None

    @staticmethod
    def make_key(**params) -> str
```

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `__init__` | `ttl_seconds: int = 3600` | `None` | Initialize cache with TTL (default: 1 hour) |
| `get` | `key: str` | `Optional[Any]` | Get cached value if not expired, else None |
| `set` | `key: str, value: Any` | `None` | Cache value with current timestamp |
| `clear` | None | `None` | Clear all cached entries |
| `make_key` | `**params` | `str` | Create deterministic cache key from parameters (MD5 hash) |

**Thread Safety:** All operations use `threading.Lock()`.

---

### RateLimiter

Thread-safe token bucket rate limiter.

```python
class RateLimiter:
    def __init__(self, requests_per_minute: int = 10)
    def check(self) -> bool
    def record(self) -> None
    def wait_time(self) -> float
```

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `__init__` | `requests_per_minute: int = 10` | `None` | Initialize with rate limit |
| `check` | None | `bool` | Check if request is allowed under rate limit |
| `record` | None | `None` | Record a request timestamp |
| `wait_time` | None | `float` | Seconds to wait before next request is allowed |

**Algorithm:** Sliding window - removes timestamps older than 60 seconds before counting.

---

### RunBudget

Per-turn budget tracker to prevent runaway costs.

```python
class RunBudget:
    def __init__(self, max_searches: int = 3, max_fetches: int = 5)
    def can_search(self) -> bool
    def can_fetch(self) -> bool
    def record_search(self) -> None
    def record_fetch(self) -> None
    def reset(self) -> None

    @property
    def searches_remaining(self) -> int
    @property
    def fetches_remaining(self) -> int
```

| Method/Property | Returns | Description |
|-----------------|---------|-------------|
| `can_search()` | `bool` | Check if search budget allows another request |
| `can_fetch()` | `bool` | Check if fetch budget allows another request |
| `record_search()` | `None` | Record a search request |
| `record_fetch()` | `None` | Record a fetch request |
| `reset()` | `None` | Reset budget for new turn |
| `searches_remaining` | `int` | Get remaining search budget |
| `fetches_remaining` | `int` | Get remaining fetch budget |

**Integration:** Must call `reset()` at the start of each user turn.

---

### UrlSafety

SSRF-hardened URL validation.

```python
class UrlSafety:
    @classmethod
    def normalize_hostname(cls, hostname: str) -> str

    @classmethod
    def is_ip_blocked(cls, ip_str: str) -> Tuple[bool, str]

    @classmethod
    def is_hostname_blocked(cls, hostname: str) -> Tuple[bool, str]

    @classmethod
    def validate(cls, url: str) -> str
```

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `normalize_hostname` | `hostname: str` | `str` | Lowercase + strip trailing dot |
| `is_ip_blocked` | `ip_str: str` | `Tuple[bool, str]` | Check if IP is in blocked range, returns (blocked, reason) |
| `is_hostname_blocked` | `hostname: str` | `Tuple[bool, str]` | Check if hostname matches blocklist |
| `validate` | `url: str` | `str` | Full validation, raises `UrlSafetyError` if blocked |

**Raises:** `UrlSafetyError` (subclass of `ValueError`) for validation failures.

---

### WebSearchProvider (ABC)

Abstract interface for web search providers.

```python
class WebSearchProvider(ABC):
    @abstractmethod
    def search(
        self,
        query: str,
        max_results: int = 5,
        search_depth: str = "basic",
        include_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
    ) -> WebSearchResult
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | `str` | Required | Search query |
| `max_results` | `int` | `5` | Maximum results to return (1-10) |
| `search_depth` | `str` | `"basic"` | `"basic"` (fast) or `"advanced"` (thorough) |
| `include_domains` | `Optional[List[str]]` | `None` | Only include results from these domains |
| `exclude_domains` | `Optional[List[str]]` | `None` | Exclude results from these domains |

**Returns:** `WebSearchResult` dataclass

**Raises:**
- `RateLimitError` if provider returns 429
- `Exception` for other errors

---

### TavilyProvider

Tavily API implementation for web search.

```python
class TavilyProvider(WebSearchProvider):
    API_URL = "https://api.tavily.com/search"

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_key_env: str = "TAVILY_API_KEY",
        timeout_seconds: float = 30.0,
    )

    def search(...) -> WebSearchResult
```

| Constructor Parameter | Type | Default | Description |
|----------------------|------|---------|-------------|
| `api_key` | `Optional[str]` | `None` | API key (falls back to env var) |
| `api_key_env` | `str` | `"TAVILY_API_KEY"` | Environment variable name for API key |
| `timeout_seconds` | `float` | `30.0` | HTTP request timeout |

**Raises:** `ValueError` if API key not provided and not in environment.

---

### WebSearchResult / SearchResultItem

Result dataclasses.

```python
@dataclass
class SearchResultItem:
    title: str       # Result title
    url: str         # Full URL
    snippet: str     # Content snippet (truncated to 500 chars)
    domain: str      # Extracted domain for citation

@dataclass
class WebSearchResult:
    results: List[SearchResultItem] = field(default_factory=list)
    answer: Optional[str] = None  # AI summary if provider supports
```

---

### WebFetchTool

Fetch content from URLs with SSRF protection.

```python
class WebFetchTool(Tool):
    def __init__(
        self,
        cache_ttl_seconds: int = 900,
        timeout_seconds: float = 30.0,
        max_content_bytes: int = 102400,
    )

    def set_run_budget(self, budget: RunBudget) -> None

    def execute(
        self,
        url: str,
        extract_text: bool = True,
        **kwargs: Any
    ) -> ToolResult
```

| Constructor Parameter | Type | Default | Description |
|----------------------|------|---------|-------------|
| `cache_ttl_seconds` | `int` | `900` | Cache TTL for fetched content (15 min) |
| `timeout_seconds` | `float` | `30.0` | HTTP request timeout |
| `max_content_bytes` | `int` | `102400` | Maximum bytes to read (100KB) |

| Execute Parameter | Type | Default | Description |
|-------------------|------|---------|-------------|
| `url` | `str` | Required | URL to fetch (http/https only) |
| `extract_text` | `bool` | `True` | Extract plain text from HTML |

**Returns:** `ToolResult` with:
- `status`: `SUCCESS` or `ERROR`
- `output`: Page content (text)
- `metadata`: `{url, bytes_read, content_type, cache_hit}`

---

### WebSearchTool

Web search via provider interface.

```python
class WebSearchTool(Tool):
    MAX_QUERY_LENGTH = 500

    def __init__(
        self,
        provider: Optional[WebSearchProvider] = None,
        cache_ttl_seconds: int = 3600,
        rate_limit_per_minute: int = 10,
    )

    def set_run_budget(self, budget: RunBudget) -> None

    def execute(
        self,
        query: str,
        max_results: int = 5,
        search_depth: str = "basic",
        include_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
        **kwargs: Any
    ) -> ToolResult
```

| Constructor Parameter | Type | Default | Description |
|----------------------|------|---------|-------------|
| `provider` | `Optional[WebSearchProvider]` | `None` | Search provider (default: TavilyProvider) |
| `cache_ttl_seconds` | `int` | `3600` | Cache TTL for search results (1 hour) |
| `rate_limit_per_minute` | `int` | `10` | Max requests per minute |

| Execute Parameter | Type | Default | Description |
|-------------------|------|---------|-------------|
| `query` | `str` | Required | Search query |
| `max_results` | `int` | `5` | Number of results (1-10) |
| `search_depth` | `str` | `"basic"` | `"basic"` (fast) or `"advanced"` (thorough) |
| `include_domains` | `Optional[List[str]]` | `None` | Only include results from these domains |
| `exclude_domains` | `Optional[List[str]]` | `None` | Exclude results from these domains |

**Returns:** `ToolResult` with formatted results including citations.

**Output Format:**
```markdown
**Summary:** {AI-generated answer if available}

## Search Results

1. **{title}**
   {snippet}...
   Source: [{domain}]({url})

2. **{title}**
   ...
```

---

## Usage Examples

### Basic Web Search

```python
from src.tools.web_tools import WebSearchTool, RunBudget

# Initialize tool with budget
budget = RunBudget(max_searches=3, max_fetches=5)
search_tool = WebSearchTool()
search_tool.set_run_budget(budget)

# Execute search
result = search_tool.execute(
    query="Python 3.12 new features",
    max_results=5,
    search_depth="basic"
)

if result.status == ToolStatus.SUCCESS:
    print(result.output)
else:
    print(f"Error: {result.error}")
```

### Web Search with Domain Filtering

```python
# Search only official documentation sites
result = search_tool.execute(
    query="asyncio tutorial",
    include_domains=["docs.python.org", "realpython.com"],
    max_results=3
)

# Exclude certain domains
result = search_tool.execute(
    query="React hooks best practices",
    exclude_domains=["w3schools.com", "tutorialspoint.com"],
    search_depth="advanced"
)
```

### Basic Web Fetch

```python
from src.tools.web_tools import WebFetchTool, RunBudget

budget = RunBudget(max_searches=3, max_fetches=5)
fetch_tool = WebFetchTool()
fetch_tool.set_run_budget(budget)

# Fetch documentation page
result = fetch_tool.execute(
    url="https://docs.python.org/3/library/asyncio.html",
    extract_text=True
)

if result.status == ToolStatus.SUCCESS:
    print(f"Fetched {result.metadata['bytes_read']} bytes")
    print(result.output[:500])  # First 500 chars
```

### Fetch JSON API Response

```python
# Fetch JSON without text extraction
result = fetch_tool.execute(
    url="https://api.github.com/repos/python/cpython",
    extract_text=False  # Keep raw JSON
)

if result.status == ToolStatus.SUCCESS:
    import json
    data = json.loads(result.output)
    print(f"Stars: {data['stargazers_count']}")
```

### Agent Integration

In `src/core/agent.py`, the tools are registered and budget is managed:

```python
# Tool initialization
from src.tools.web_tools import WebSearchTool, WebFetchTool, RunBudget

self._web_run_budget = RunBudget(max_searches=3, max_fetches=5)
self._web_search_tool = WebSearchTool()
self._web_fetch_tool = WebFetchTool()
self._web_search_tool.set_run_budget(self._web_run_budget)
self._web_fetch_tool.set_run_budget(self._web_run_budget)
self.tool_executor.register_tool(self._web_search_tool)
self.tool_executor.register_tool(self._web_fetch_tool)

# At the start of each user turn:
def handle_user_message(self, message: str):
    self._web_run_budget.reset()  # Reset per-turn budget
    # ... process message
```

---

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TAVILY_API_KEY` | Yes (for search) | None | Tavily API key ([Get one here](https://tavily.com)) |

### Timeout Configuration

In `src/tools/base.py`, per-tool timeout overrides are configured:

```python
TOOL_TIMEOUT_OVERRIDES = {
    "web_search": 45,  # API call + processing
    "web_fetch": 60,   # Large pages can be slow
}
```

These timeouts apply when executing tools asynchronously via `ToolExecutor.execute_tool_async()`.

### Default Values Summary

| Setting | Default | Location |
|---------|---------|----------|
| Search cache TTL | 1 hour | `WebSearchTool.__init__` |
| Fetch cache TTL | 15 minutes | `WebFetchTool.__init__` |
| Rate limit | 10 req/min | `WebSearchTool.__init__` |
| Max searches/turn | 3 | `RunBudget.__init__` |
| Max fetches/turn | 5 | `RunBudget.__init__` |
| Max content bytes | 100KB | `WebFetchTool.__init__` |
| Max query length | 500 chars | `WebSearchTool.MAX_QUERY_LENGTH` |
| HTTP timeout | 30s | Both tools |
| Tool timeout (async) | 45s/60s | `base.py` |

---

## Adding New Providers

To add a new search provider (e.g., Brave Search, Bing), implement the `WebSearchProvider` interface.

### Step 1: Implement the Provider Class

```python
from src.tools.web_tools import (
    WebSearchProvider,
    WebSearchResult,
    SearchResultItem,
    RateLimitError,
)
from urllib.parse import urlparse
import httpx
import os


class BraveProvider(WebSearchProvider):
    """Brave Search API implementation."""

    API_URL = "https://api.search.brave.com/res/v1/web/search"

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_key_env: str = "BRAVE_API_KEY",
        timeout_seconds: float = 30.0,
    ):
        self.api_key = api_key or os.getenv(api_key_env)
        if not self.api_key:
            raise ValueError(
                f"Brave API key not provided. Set {api_key_env} environment variable."
            )
        self.timeout = timeout_seconds

    def search(
        self,
        query: str,
        max_results: int = 5,
        search_depth: str = "basic",
        include_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
    ) -> WebSearchResult:
        """Execute Brave search."""
        # Build request
        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": self.api_key,
        }
        params = {
            "q": query,
            "count": min(max(1, max_results), 10),
        }

        # Make API request
        with httpx.Client(timeout=self.timeout) as client:
            try:
                response = client.get(
                    self.API_URL,
                    headers=headers,
                    params=params
                )
            except httpx.TimeoutException as e:
                raise Exception(f"Brave API timeout: {e}")

        # Handle rate limit
        if response.status_code == 429:
            raise RateLimitError("Brave API rate limit exceeded")

        if response.status_code != 200:
            raise Exception(f"Brave API error: {response.status_code}")

        # Parse response
        data = response.json()

        # Convert to normalized format
        results = []
        for item in data.get("web", {}).get("results", []):
            url = item.get("url", "")
            domain = urlparse(url).netloc if url else ""
            results.append(SearchResultItem(
                title=item.get("title", "Untitled"),
                url=url,
                snippet=item.get("description", "")[:500],
                domain=domain,
            ))

        return WebSearchResult(
            results=results,
            answer=None,  # Brave doesn't provide AI summaries
        )
```

### Step 2: Register the Provider

In agent initialization or configuration:

```python
from src.tools.web_tools import WebSearchTool
from my_providers import BraveProvider

# Use Brave instead of Tavily
provider = BraveProvider()  # Uses BRAVE_API_KEY env var
search_tool = WebSearchTool(provider=provider)
```

### Step 3: Add Tool Schema (Optional)

If the new provider has different parameters, update `src/tools/tool_schemas.py`:

```python
WEB_SEARCH_BRAVE_TOOL = ToolDefinition(
    name="web_search_brave",
    description="Search using Brave Search API...",
    parameters={...}
)
```

### Provider Implementation Checklist

- [ ] Implement `WebSearchProvider.search()` method
- [ ] Handle rate limiting (raise `RateLimitError` on 429)
- [ ] Normalize results to `SearchResultItem` format
- [ ] Support `include_domains` and `exclude_domains` if API supports
- [ ] Handle API key via constructor or environment variable
- [ ] Add appropriate timeout handling
- [ ] Add logging for observability
- [ ] Write unit tests mocking API responses
- [ ] Write integration tests (marked with `@pytest.mark.integration`)

---

## Testing

The test suite (`tests/test_web_tools.py`) contains 66 tests covering:

### Test Categories

| Category | Count | Description |
|----------|-------|-------------|
| TTLCache | 6 | Cache behavior, expiration, key generation |
| RateLimiter | 4 | Rate limiting, wait times |
| RunBudget | 4 | Budget tracking, exhaustion, reset |
| UrlSafety | 20 | SSRF protection, IP blocking, hostname validation |
| Content-Type | 7 | Allowlist/blocklist validation |
| WebFetchTool | 9 | Fetch behavior, caching, security |
| WebSearchTool | 9 | Search behavior, caching, formatting |
| TavilyProvider | 4 | Provider-specific tests |
| Integration | 3 | Real network tests |

### Running Tests

```bash
# Run all web tools tests
pytest tests/test_web_tools.py -v

# Run unit tests only (no network)
pytest tests/test_web_tools.py -v -m "not integration"

# Run integration tests (requires TAVILY_API_KEY)
pytest tests/test_web_tools.py -v -m integration

# Run with coverage
pytest tests/test_web_tools.py -v --cov=src.tools.web_tools --cov-report=term-missing
```

### Testing SSRF Protection

Key SSRF tests to ensure security:

```python
def test_blocks_localhost(self):
    """Test that localhost URLs are blocked."""
    with pytest.raises(UrlSafetyError):
        UrlSafety.validate("http://localhost/admin")

def test_blocks_private_ip_via_dns(self):
    """Test that DNS resolving to private IP is blocked."""
    with patch('src.tools.web_tools.socket.getaddrinfo') as mock_dns:
        mock_dns.return_value = [(2, 1, 6, '', ('10.0.0.1', 80))]
        with pytest.raises(UrlSafetyError, match="10.0.0.1"):
            UrlSafety.validate("http://internal.example.com/")

def test_blocks_cloud_metadata(self):
    """Test that cloud metadata endpoint is blocked."""
    with pytest.raises(UrlSafetyError):
        UrlSafety.validate("http://169.254.169.254/latest/meta-data/")
```

### Mocking Patterns

**Mock httpx.Client for fetch tests:**
```python
with patch('src.tools.web_tools.httpx.Client') as mock_client_class:
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {'content-type': 'text/html'}
    mock_response.iter_bytes.return_value = iter([b'<html>...</html>'])
    mock_client.stream.return_value.__enter__ = Mock(return_value=mock_response)
    mock_client_class.return_value.__enter__ = Mock(return_value=mock_client)

    result = tool.execute(url="https://example.com/")
```

**Mock provider for search tests:**
```python
mock_provider = Mock(spec=WebSearchProvider)
mock_provider.search.return_value = WebSearchResult(
    results=[SearchResultItem(
        title="Test",
        url="https://example.com",
        snippet="Test snippet",
        domain="example.com"
    )],
    answer="AI summary"
)
tool = WebSearchTool(provider=mock_provider)
```

---

## Troubleshooting

### Common Errors

| Error | Cause | Solution |
|-------|-------|----------|
| `Tavily API key not provided` | Missing `TAVILY_API_KEY` | Set environment variable or pass `api_key` to provider |
| `URL blocked: blocked hostname` | URL points to localhost/internal | Use public URLs only |
| `Port 8080 not allowed` | Non-standard port in URL | Only ports 80/443 are allowed |
| `Search budget exceeded` | Too many searches in one turn | Ask user for permission to continue |
| `Unsupported content-type: application/pdf` | Trying to fetch binary file | Only text/JSON/XML supported |
| `Request timed out` | Slow server or network | Increase timeout or try different URL |

### Debugging

Enable debug logging:

```python
import logging
logging.getLogger("tools.web").setLevel(logging.DEBUG)
```

Check observability logs for:
- `web_fetch completed` - Fetch operation details
- `web_search completed` - Search operation details

Log fields include: `elapsed_ms`, `status_code`, `bytes_read`, `cache_hit`, `error_type`

---

## File Reference

| File | Purpose |
|------|---------|
| `src/tools/web_tools.py` | Main implementation (1162 lines) |
| `tests/test_web_tools.py` | Test suite (740 lines, 66 tests) |
| `src/tools/tool_schemas.py` | LLM function calling definitions |
| `src/tools/base.py` | Tool timeout configuration |
| `src/core/agent.py` | Agent integration (budget reset) |

---

## Changelog

### v1.0.0 (Initial Release)

- WebSearchTool with TavilyProvider
- WebFetchTool with SSRF protection
- TTLCache, RateLimiter, RunBudget helpers
- Full SSRF protection suite
- Content-type allowlist
- Streaming byte cap
- Per-turn budget limits
- 66 unit and integration tests
