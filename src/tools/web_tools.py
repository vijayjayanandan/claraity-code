"""Web search and fetch tools with production-grade security.

This module provides:
- WebFetchTool: Fetch content from URLs with SSRF protection
- WebSearchTool: Search the web via provider interface (Tavily v1)

Security features:
- SSRF protection via DNS resolution + IP range blocking
- Content-type allowlist (text/*, json, xml only)
- Streaming byte cap enforcement
- Per-run budget to prevent runaway cost
- Rate limiting for search API
"""

import hashlib
import ipaddress
import logging
import os
import re
import socket
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

from .base import Tool, ToolResult, ToolStatus

# Try to import structured logging
try:
    from src.observability import get_logger

    logger = get_logger("tools.web")
except ImportError:
    logger = logging.getLogger(__name__)


# =============================================================================
# Helper Classes
# =============================================================================


class TTLCache:
    """Thread-safe TTL cache for web tool results."""

    def __init__(self, ttl_seconds: int = 3600):
        """
        Initialize TTL cache.

        Args:
            ttl_seconds: Time-to-live for cached entries (default: 1 hour)
        """
        self.ttl = ttl_seconds
        self._cache: dict[str, tuple[Any, float]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        """Get cached value if not expired."""
        with self._lock:
            if key in self._cache:
                value, timestamp = self._cache[key]
                if time.time() - timestamp < self.ttl:
                    return value
                del self._cache[key]
            return None

    def set(self, key: str, value: Any) -> None:
        """Cache value with current timestamp."""
        with self._lock:
            self._cache[key] = (value, time.time())

    def clear(self) -> None:
        """Clear all cached entries."""
        with self._lock:
            self._cache.clear()

    @staticmethod
    def make_key(**params) -> str:
        """Create deterministic cache key from parameters."""
        key_str = str(sorted(params.items()))
        return hashlib.md5(key_str.encode()).hexdigest()


class RateLimiter:
    """Thread-safe token bucket rate limiter."""

    def __init__(self, requests_per_minute: int = 10):
        """
        Initialize rate limiter.

        Args:
            requests_per_minute: Maximum requests allowed per minute
        """
        self.limit = requests_per_minute
        self.window_seconds = 60
        self._requests: list[float] = []
        self._lock = threading.Lock()

    def check(self) -> bool:
        """Check if request is allowed under rate limit."""
        with self._lock:
            now = time.time()
            # Remove old requests outside window
            self._requests = [t for t in self._requests if t > now - self.window_seconds]
            return len(self._requests) < self.limit

    def record(self) -> None:
        """Record a request."""
        with self._lock:
            self._requests.append(time.time())

    def wait_time(self) -> float:
        """Time to wait before next request is allowed."""
        with self._lock:
            if len(self._requests) < self.limit:
                return 0.0
            oldest = min(self._requests)
            return max(0.0, (oldest + self.window_seconds) - time.time())


class RunBudget:
    """
    Per-run budget tracker to prevent runaway cost.

    This must be reset at the start of each user turn/prompt.
    """

    def __init__(self, max_searches: int = 3, max_fetches: int = 5):
        """
        Initialize run budget.

        Args:
            max_searches: Maximum web searches per turn (default: 3)
            max_fetches: Maximum URL fetches per turn (default: 5)
        """
        self.max_searches = max_searches
        self.max_fetches = max_fetches
        self._searches_used = 0
        self._fetches_used = 0
        self._lock = threading.Lock()

    def can_search(self) -> bool:
        """Check if search budget allows another request."""
        with self._lock:
            return self._searches_used < self.max_searches

    def can_fetch(self) -> bool:
        """Check if fetch budget allows another request."""
        with self._lock:
            return self._fetches_used < self.max_fetches

    def record_search(self) -> None:
        """Record a search request."""
        with self._lock:
            self._searches_used += 1

    def record_fetch(self) -> None:
        """Record a fetch request."""
        with self._lock:
            self._fetches_used += 1

    def reset(self) -> None:
        """Reset budget for new turn."""
        with self._lock:
            self._searches_used = 0
            self._fetches_used = 0

    @property
    def searches_remaining(self) -> int:
        """Get remaining search budget."""
        with self._lock:
            return max(0, self.max_searches - self._searches_used)

    @property
    def fetches_remaining(self) -> int:
        """Get remaining fetch budget."""
        with self._lock:
            return max(0, self.max_fetches - self._fetches_used)


# =============================================================================
# URL Safety (SSRF Protection)
# =============================================================================


class UrlSafetyError(ValueError):
    """URL validation failed due to security check."""

    pass


class UrlSafety:
    """
    SSRF-hardened URL validation.

    Checks:
    1. Scheme: only http/https
    2. Length: max 2048 chars
    3. Hostname normalization: lowercase + strip trailing dot
    4. Port: only 80, 443 allowed (v1 - minimal attack surface)
    5. DNS resolution: resolve hostname, block if ANY IP is private/internal
    6. Hostname blocklist: localhost, localhost., *.localhost, *.local, *.internal
    """

    # IP ranges to block (SSRF protection)
    BLOCKED_IP_NETWORKS = [
        ipaddress.ip_network("10.0.0.0/8"),  # RFC1918 Class A
        ipaddress.ip_network("172.16.0.0/12"),  # RFC1918 Class B
        ipaddress.ip_network("192.168.0.0/16"),  # RFC1918 Class C
        ipaddress.ip_network("127.0.0.0/8"),  # Loopback
        ipaddress.ip_network("169.254.0.0/16"),  # Link-local (includes metadata)
        ipaddress.ip_network("100.64.0.0/10"),  # CGNAT
        ipaddress.ip_network("0.0.0.0/8"),  # "This" network
        ipaddress.ip_network("224.0.0.0/4"),  # Multicast
        ipaddress.ip_network("240.0.0.0/4"),  # Reserved
        # IPv6
        ipaddress.ip_network("::1/128"),  # Loopback
        ipaddress.ip_network("fc00::/7"),  # ULA
        ipaddress.ip_network("fe80::/10"),  # Link-local
        ipaddress.ip_network("ff00::/8"),  # Multicast
    ]

    # Cloud metadata endpoints to explicitly block
    CLOUD_METADATA_IPS = {"169.254.169.254", "fd00:ec2::254"}

    # v1: Only standard ports to minimize attack surface
    # Non-standard ports (8080, 8443) often indicate internal services
    ALLOWED_PORTS = {80, 443}

    # Hostnames to block (checked after normalization)
    BLOCKED_HOSTNAMES = {"localhost", "localhost."}
    BLOCKED_HOSTNAME_SUFFIXES = (".localhost", ".local", ".internal", ".localdomain")

    # Maximum URL length
    MAX_URL_LENGTH = 2048

    @classmethod
    def normalize_hostname(cls, hostname: str) -> str:
        """Normalize hostname: lowercase + strip trailing dot."""
        return hostname.lower().rstrip(".")

    @classmethod
    def is_ip_blocked(cls, ip_str: str) -> tuple[bool, str]:
        """
        Check if IP is in any blocked range.

        Returns:
            tuple of (is_blocked, reason)
        """
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return False, ""

        # Check explicit cloud metadata IPs
        if ip_str in cls.CLOUD_METADATA_IPS:
            return True, "cloud metadata endpoint"

        # Check all blocked networks
        for network in cls.BLOCKED_IP_NETWORKS:
            if ip in network:
                return True, f"IP in blocked range {network}"

        # Additional checks using ipaddress properties
        if ip.is_private:
            return True, "private IP"
        if ip.is_loopback:
            return True, "loopback IP"
        if ip.is_reserved:
            return True, "reserved IP"
        if ip.is_multicast:
            return True, "multicast IP"
        if ip.is_link_local:
            return True, "link-local IP"

        return False, ""

    @classmethod
    def is_hostname_blocked(cls, hostname: str) -> tuple[bool, str]:
        """
        Check if hostname matches blocklist.

        Returns:
            tuple of (is_blocked, reason)
        """
        normalized = cls.normalize_hostname(hostname)

        if normalized in cls.BLOCKED_HOSTNAMES:
            return True, f"blocked hostname: {normalized}"

        for suffix in cls.BLOCKED_HOSTNAME_SUFFIXES:
            if normalized.endswith(suffix):
                return True, f"blocked hostname suffix: {suffix}"

        return False, ""

    @classmethod
    def validate(cls, url: str) -> str:
        """
        Validate URL for safety, raise UrlSafetyError if blocked.

        Args:
            url: URL to validate

        Returns:
            Validated URL (unchanged if valid)

        Raises:
            UrlSafetyError: If URL fails any security check
        """
        # 1. Check length
        if len(url) > cls.MAX_URL_LENGTH:
            raise UrlSafetyError(f"URL too long: {len(url)} chars (max {cls.MAX_URL_LENGTH})")

        # 2. Parse URL
        try:
            parsed = urlparse(url)
        except Exception as e:
            raise UrlSafetyError(f"Invalid URL format: {e}")

        # 3. Check scheme
        if parsed.scheme not in ("http", "https"):
            raise UrlSafetyError(f"Invalid scheme: {parsed.scheme}. Only http/https allowed")

        # 4. Check hostname exists
        hostname = parsed.hostname
        if not hostname:
            raise UrlSafetyError("No hostname in URL")

        # 5. Normalize hostname
        normalized_hostname = cls.normalize_hostname(hostname)

        # 6. Check hostname blocklist
        is_blocked, reason = cls.is_hostname_blocked(normalized_hostname)
        if is_blocked:
            raise UrlSafetyError(f"Blocked: {reason}")

        # 7. Check port
        port = parsed.port
        if port is None:
            # Default ports based on scheme
            port = 443 if parsed.scheme == "https" else 80

        if port not in cls.ALLOWED_PORTS:
            raise UrlSafetyError(
                f"Port {port} not allowed. Only ports {sorted(cls.ALLOWED_PORTS)} allowed"
            )

        # 8. DNS resolution and IP check
        try:
            # Get all IP addresses (A and AAAA records)
            addr_infos = socket.getaddrinfo(
                normalized_hostname,
                port,
                family=socket.AF_UNSPEC,  # Both IPv4 and IPv6
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror as e:
            raise UrlSafetyError(f"DNS resolution failed for {normalized_hostname}: {e}")

        # 9. Check ALL resolved IPs
        for addr_info in addr_infos:
            ip_str = addr_info[4][0]
            is_blocked, reason = cls.is_ip_blocked(ip_str)
            if is_blocked:
                raise UrlSafetyError(
                    f"Blocked: {normalized_hostname} resolves to {ip_str} ({reason})"
                )

        return url


# =============================================================================
# Content Type Safety
# =============================================================================

ALLOWED_CONTENT_TYPES: set[str] = {
    "text/html",
    "text/plain",
    "text/xml",
    "text/markdown",
    "text/css",
    "text/javascript",
    "application/json",
    "application/xml",
    "application/xhtml+xml",
    "application/javascript",
}


def is_content_type_allowed(content_type: str) -> tuple[bool, str]:
    """
    Check if content-type is in allowlist.

    Args:
        content_type: Content-Type header value

    Returns:
        tuple of (is_allowed, base_type)
    """
    if not content_type:
        return False, ""

    # Parse content-type (ignore charset and other parameters)
    base_type = content_type.split(";")[0].strip().lower()

    # Check exact match
    if base_type in ALLOWED_CONTENT_TYPES:
        return True, base_type

    # Check text/* prefix
    if base_type.startswith("text/"):
        return True, base_type

    return False, base_type


# =============================================================================
# Provider Interface for Web Search
# =============================================================================


@dataclass
class SearchResultItem:
    """Single search result item."""

    title: str
    url: str
    snippet: str
    domain: str  # Extracted from URL for citation


@dataclass
class WebSearchResult:
    """Provider-agnostic search result."""

    results: list[SearchResultItem] = field(default_factory=list)
    answer: str | None = None  # AI summary if provider supports


class RateLimitError(Exception):
    """Rate limit exceeded error."""

    pass


class WebSearchProvider(ABC):
    """Abstract interface for web search providers."""

    @abstractmethod
    def search(
        self,
        query: str,
        max_results: int = 5,
        search_depth: str = "basic",
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
    ) -> WebSearchResult:
        """
        Execute search and return normalized results.

        Args:
            query: Search query
            max_results: Maximum results to return (1-10)
            search_depth: "basic" (fast) or "advanced" (thorough)
            include_domains: Only include results from these domains
            exclude_domains: Exclude results from these domains

        Returns:
            Normalized search result

        Raises:
            RateLimitError: If provider returns 429
            Exception: For other errors
        """
        pass


class TavilyProvider(WebSearchProvider):
    """Tavily API implementation for web search."""

    API_URL = "https://api.tavily.com/search"

    def __init__(
        self,
        api_key: str | None = None,
        api_key_env: str = "TAVILY_API_KEY",
        timeout_seconds: float = 30.0,
    ):
        """
        Initialize Tavily provider.

        Args:
            api_key: API key (optional, falls back to env var)
            api_key_env: Environment variable name for API key
            timeout_seconds: HTTP request timeout
        """
        self.api_key = api_key or os.getenv(api_key_env)
        if not self.api_key:
            raise ValueError(
                f"Tavily API key not provided. set {api_key_env} environment variable "
                f"or pass api_key parameter. Get a key at https://tavily.com"
            )
        self.timeout = timeout_seconds

    def search(
        self,
        query: str,
        max_results: int = 5,
        search_depth: str = "basic",
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
    ) -> WebSearchResult:
        """Execute Tavily search."""
        # Build request payload
        payload = {
            "api_key": self.api_key,
            "query": query,
            "max_results": min(max(1, max_results), 10),
            "search_depth": search_depth if search_depth in ("basic", "advanced") else "basic",
            "include_answer": True,
        }

        if include_domains:
            payload["include_domains"] = include_domains
        if exclude_domains:
            payload["exclude_domains"] = exclude_domains

        # Make API request
        with httpx.Client(timeout=self.timeout) as client:
            try:
                response = client.post(self.API_URL, json=payload)
            except httpx.TimeoutException as e:
                raise Exception(f"Tavily API timeout: {e}")
            except httpx.RequestError as e:
                raise Exception(f"Tavily API request failed: {e}")

        # Handle rate limit
        if response.status_code == 429:
            raise RateLimitError("Tavily API rate limit exceeded")

        # Handle other errors
        if response.status_code != 200:
            raise Exception(f"Tavily API error: {response.status_code} - {response.text}")

        # Parse response
        try:
            data = response.json()
        except Exception as e:
            raise Exception(f"Failed to parse Tavily response: {e}")

        # Convert to normalized format
        results = []
        for item in data.get("results", []):
            url = item.get("url", "")
            domain = urlparse(url).netloc if url else ""
            results.append(
                SearchResultItem(
                    title=item.get("title", "Untitled"),
                    url=url,
                    snippet=item.get("content", "")[:500],  # Truncate snippet
                    domain=domain,
                )
            )

        return WebSearchResult(
            results=results,
            answer=data.get("answer"),
        )


# =============================================================================
# WebFetchTool
# =============================================================================


class WebFetchTool(Tool):
    """
    Fetch content from URLs with SSRF protection.

    Security:
    - SSRF: DNS resolution + IP range blocking
    - Redirects: follow_redirects=False (v1)
    - Byte cap: streaming enforcement (not post-download)
    - Content-type: allowlist (text/*, json, xml only)
    """

    def __init__(
        self,
        cache_ttl_seconds: int = 900,
        timeout_seconds: float = 30.0,
        max_content_bytes: int = 102400,  # 100KB
    ):
        """
        Initialize WebFetchTool.

        Args:
            cache_ttl_seconds: Cache TTL for fetched content (default: 15 min)
            timeout_seconds: HTTP request timeout (default: 30s)
            max_content_bytes: Maximum bytes to read (default: 100KB)
        """
        super().__init__(
            name="web_fetch",
            description="Fetch content from a specific URL. Returns extracted text.",
        )
        self.cache = TTLCache(ttl_seconds=cache_ttl_seconds)
        self.timeout = timeout_seconds
        self.max_bytes = max_content_bytes
        self._run_budget: RunBudget | None = None

    def set_run_budget(self, budget: RunBudget) -> None:
        """set run budget for current turn. Called at turn start."""
        self._run_budget = budget

    def execute(self, url: str, extract_text: bool = True, **kwargs: Any) -> ToolResult:
        """
        Fetch URL content.

        Args:
            url: URL to fetch (http/https only)
            extract_text: Extract plain text from HTML (default: True)

        Returns:
            ToolResult with page content
        """
        start_time = time.perf_counter()
        cache_hit = False
        status_code = 0
        bytes_read = 0
        content_type = ""
        error_type = None

        try:
            # 1. Check run budget
            if self._run_budget and not self._run_budget.can_fetch():
                error_type = "budget_exceeded"
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Fetch budget exceeded ({self._run_budget.max_fetches}/turn). "
                    "Ask user for permission to continue.",
                )

            # 2. Validate URL (SSRF protection)
            try:
                validated_url = UrlSafety.validate(url)
            except UrlSafetyError as e:
                error_type = "ssrf_blocked"
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"URL blocked: {e}",
                )

            # 3. Check cache
            cache_key = TTLCache.make_key(url=validated_url, extract_text=extract_text)
            cached = self.cache.get(cache_key)
            if cached is not None:
                cache_hit = True
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.SUCCESS,
                    output=cached,
                    metadata={"cache_hit": True, "url": validated_url},
                )

            # 4. Record budget usage
            if self._run_budget:
                self._run_budget.record_fetch()

            # 5. Fetch with streaming byte cap
            with httpx.Client(
                timeout=self.timeout,
                follow_redirects=False,  # v1: No redirects (security)
            ) as client:
                with client.stream("GET", validated_url) as response:
                    status_code = response.status_code

                    # Check for redirect (we don't follow, but inform user)
                    if 300 <= status_code < 400:
                        location = response.headers.get("location", "unknown")
                        error_type = "redirect"
                        return ToolResult(
                            tool_name=self.name,
                            status=ToolStatus.ERROR,
                            output=None,
                            error=f"URL redirects to: {location}. "
                            "Fetch the target URL directly if needed.",
                        )

                    # Check status code
                    if status_code != 200:
                        error_type = f"http_{status_code}"
                        return ToolResult(
                            tool_name=self.name,
                            status=ToolStatus.ERROR,
                            output=None,
                            error=f"HTTP {status_code}: {response.reason_phrase}",
                        )

                    # 6. Validate content-type before reading body
                    content_type = response.headers.get("content-type", "")
                    is_allowed, base_type = is_content_type_allowed(content_type)
                    if not is_allowed:
                        error_type = "content_type_blocked"
                        return ToolResult(
                            tool_name=self.name,
                            status=ToolStatus.ERROR,
                            output=None,
                            error=f"Unsupported content-type: {base_type}. "
                            "Only text, JSON, and XML are supported.",
                        )

                    # 7. Stream content with byte cap
                    chunks = []
                    for chunk in response.iter_bytes(chunk_size=8192):
                        bytes_read += len(chunk)
                        chunks.append(chunk)
                        if bytes_read >= self.max_bytes:
                            break

                    content = b"".join(chunks)

            # 8. Decode content
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    text = content.decode("latin-1")
                except UnicodeDecodeError:
                    text = content.decode("utf-8", errors="replace")

            # 9. Extract text if HTML
            if extract_text and "html" in content_type.lower():
                text = self._extract_text(text)

            # 10. Add truncation notice if applicable
            if bytes_read >= self.max_bytes:
                text += f"\n\n[Content truncated at {self.max_bytes} bytes]"

            # 11. Cache result
            self.cache.set(cache_key, text)

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=text,
                metadata={
                    "url": validated_url,
                    "bytes_read": bytes_read,
                    "content_type": content_type,
                    "cache_hit": False,
                },
            )

        except httpx.TimeoutException:
            error_type = "timeout"
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Request timed out after {self.timeout}s",
            )
        except httpx.RequestError as e:
            error_type = "request_error"
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Request failed: {e}",
            )
        except Exception as e:
            error_type = "unknown"
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Fetch failed: {e}",
            )
        finally:
            # Log observability fields
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.info(
                "web_fetch completed",
                extra={
                    "tool": "web_fetch",
                    "url": url[:100],  # Truncate for logs
                    "elapsed_ms": round(elapsed_ms, 2),
                    "status_code": status_code,
                    "bytes_read": bytes_read,
                    "cache_hit": cache_hit,
                    "content_type": content_type,
                    "error_type": error_type,
                },
            )

    def _extract_text(self, html: str) -> str:
        """
        Extract readable text from HTML.

        Strips script/style tags, collapses whitespace, preserves structure.
        """
        # Remove script and style elements
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)

        # Remove HTML comments
        html = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)

        # Replace block elements with newlines
        html = re.sub(r"<(br|hr|p|div|h[1-6]|li|tr)[^>]*>", "\n", html, flags=re.IGNORECASE)

        # Remove remaining HTML tags
        html = re.sub(r"<[^>]+>", "", html)

        # Decode common HTML entities
        html = html.replace("&nbsp;", " ")
        html = html.replace("&amp;", "&")
        html = html.replace("&lt;", "<")
        html = html.replace("&gt;", ">")
        html = html.replace("&quot;", '"')
        html = html.replace("&#39;", "'")

        # Collapse multiple whitespace
        html = re.sub(r"[ \t]+", " ", html)
        html = re.sub(r"\n\s*\n", "\n\n", html)

        return html.strip()

    def _get_parameters(self) -> dict[str, Any]:
        """Get parameter schema for LLM."""
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to fetch (http/https only)"},
                "extract_text": {
                    "type": "boolean",
                    "description": "Extract plain text from HTML (default: true)",
                },
            },
            "required": ["url"],
        }


# =============================================================================
# WebSearchTool
# =============================================================================


class WebSearchTool(Tool):
    """
    Web search via provider interface.

    Features:
    - Provider-agnostic (TavilyProvider v1)
    - Caching + rate limiting
    - Per-run budget
    - Inline citations (domain + url)
    """

    # Query limits
    MAX_QUERY_LENGTH = 500

    def __init__(
        self,
        provider: WebSearchProvider | None = None,
        cache_ttl_seconds: int = 3600,
        rate_limit_per_minute: int = 10,
    ):
        """
        Initialize WebSearchTool.

        Args:
            provider: Search provider (default: TavilyProvider)
            cache_ttl_seconds: Cache TTL for search results (default: 1 hour)
            rate_limit_per_minute: Max requests per minute (default: 10)
        """
        super().__init__(
            name="web_search",
            description="Search the web for current information. Returns results with citations.",
        )
        self._provider = provider  # Lazy init if None
        self.cache = TTLCache(ttl_seconds=cache_ttl_seconds)
        self.rate_limiter = RateLimiter(requests_per_minute=rate_limit_per_minute)
        self._run_budget: RunBudget | None = None

    def set_run_budget(self, budget: RunBudget) -> None:
        """set run budget for current turn. Called at turn start."""
        self._run_budget = budget

    def _get_provider(self) -> WebSearchProvider:
        """Get or create search provider."""
        if self._provider is None:
            self._provider = TavilyProvider()
        return self._provider

    def execute(
        self,
        query: str,
        max_results: int = 5,
        search_depth: str = "basic",
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        """
        Search the web.

        Args:
            query: Search query
            max_results: Number of results (1-10, default: 5)
            search_depth: "basic" (fast) or "advanced" (thorough)
            include_domains: Only include results from these domains
            exclude_domains: Exclude results from these domains

        Returns:
            ToolResult with search results and citations
        """
        start_time = time.perf_counter()
        cache_hit = False
        results_count = 0
        rate_limit_wait_ms = 0
        error_type = None

        try:
            # 1. Check run budget
            if self._run_budget and not self._run_budget.can_search():
                error_type = "budget_exceeded"
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Search budget exceeded ({self._run_budget.max_searches}/turn). "
                    "Ask user for permission to continue.",
                )

            # 2. Sanitize query
            query = self._sanitize_query(query)
            if not query:
                error_type = "empty_query"
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error="Query cannot be empty",
                )

            # 3. Check cache
            cache_key = TTLCache.make_key(
                query=query,
                max_results=max_results,
                search_depth=search_depth,
                include_domains=str(include_domains),
                exclude_domains=str(exclude_domains),
            )
            cached = self.cache.get(cache_key)
            if cached is not None:
                cache_hit = True
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.SUCCESS,
                    output=cached,
                    metadata={"cache_hit": True, "query": query},
                )

            # 4. Check rate limit
            if not self.rate_limiter.check():
                wait_time = self.rate_limiter.wait_time()
                rate_limit_wait_ms = wait_time * 1000
                if wait_time > 10:  # Don't wait more than 10 seconds
                    error_type = "rate_limited"
                    return ToolResult(
                        tool_name=self.name,
                        status=ToolStatus.ERROR,
                        output=None,
                        error=f"Rate limited. Try again in {wait_time:.0f} seconds.",
                    )
                time.sleep(wait_time)

            # 5. Record usage
            self.rate_limiter.record()
            if self._run_budget:
                self._run_budget.record_search()

            # 6. Execute search with retry on 429
            provider = self._get_provider()
            result = None
            for attempt in range(2):  # Retry once on rate limit
                try:
                    result = provider.search(
                        query=query,
                        max_results=max_results,
                        search_depth=search_depth,
                        include_domains=include_domains,
                        exclude_domains=exclude_domains,
                    )
                    break
                except RateLimitError:
                    if attempt == 0:
                        time.sleep(2)  # Brief backoff
                        continue
                    error_type = "provider_rate_limited"
                    return ToolResult(
                        tool_name=self.name,
                        status=ToolStatus.ERROR,
                        output=None,
                        error="Search provider rate limit. Try again later.",
                    )

            if result is None:
                error_type = "no_result"
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error="Search failed unexpectedly",
                )

            # 7. Format results
            results_count = len(result.results)
            formatted = self._format_results(result)

            # 8. Cache result
            self.cache.set(cache_key, formatted)

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=formatted,
                metadata={
                    "query": query,
                    "results_count": results_count,
                    "cache_hit": False,
                },
            )

        except ValueError as e:
            # Provider initialization error (missing API key)
            error_type = "config_error"
            return ToolResult(
                tool_name=self.name, status=ToolStatus.ERROR, output=None, error=str(e)
            )
        except Exception as e:
            error_type = "unknown"
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Search failed: {e}",
            )
        finally:
            # Log observability fields
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.info(
                "web_search completed",
                extra={
                    "tool": "web_search",
                    "query": query[:100] if query else "",  # Truncate for logs
                    "elapsed_ms": round(elapsed_ms, 2),
                    "results_count": results_count,
                    "cache_hit": cache_hit,
                    "rate_limit_wait_ms": round(rate_limit_wait_ms, 2),
                    "provider": "tavily",
                    "error_type": error_type,
                },
            )

    def _sanitize_query(self, query: str) -> str:
        """Sanitize search query."""
        if not query:
            return ""

        # Truncate to max length
        query = query[: self.MAX_QUERY_LENGTH]

        # Remove control characters but keep printable and whitespace
        query = "".join(c for c in query if c.isprintable() or c.isspace())

        # Collapse multiple spaces
        query = " ".join(query.split())

        return query.strip()

    def _format_results(self, result: WebSearchResult) -> str:
        """
        Format search results with inline citations.

        Format:
        **Summary:** {answer if available}

        ## Search Results

        1. **{title}**
           {snippet}...
           Source: [{domain}]({url})
        """
        parts = []

        # AI-generated answer summary (if available)
        if result.answer:
            parts.append(f"**Summary:** {result.answer}\n")

        if not result.results:
            parts.append("No search results found.")
            return "\n".join(parts)

        parts.append("## Search Results\n")

        for i, item in enumerate(result.results, 1):
            # Title
            parts.append(f"{i}. **{item.title}**")

            # Snippet (truncated)
            snippet = item.snippet[:300] if item.snippet else "No description available"
            if len(item.snippet) > 300:
                snippet += "..."
            parts.append(f"   {snippet}")

            # Citation: Source: [domain](url)
            parts.append(f"   Source: [{item.domain}]({item.url})")
            parts.append("")  # Blank line between results

        return "\n".join(parts)

    def _get_parameters(self) -> dict[str, Any]:
        """Get parameter schema for LLM."""
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "max_results": {
                    "type": "number",
                    "description": "Results to return (1-10, default: 5)",
                },
                "search_depth": {
                    "type": "string",
                    "enum": ["basic", "advanced"],
                    "description": "'basic' (fast) or 'advanced' (thorough)",
                },
                "include_domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Only include results from these domains",
                },
                "exclude_domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Exclude results from these domains",
                },
            },
            "required": ["query"],
        }
