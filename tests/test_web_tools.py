"""Tests for web search and fetch tools.

Testing Strategy:
- WebFetchTool uses sync httpx.Client with stream=True context manager
- WebSearchTool uses sync httpx.Client.post() for Tavily API
- All mocks patch 'src.tools.web_tools.httpx.Client' (the imported reference)
- Use patch.object(UrlSafety, 'validate', ...) to bypass DNS checks in unit tests
- Integration tests (marked) hit real endpoints and require TAVILY_API_KEY
"""

import time
from unittest.mock import Mock, patch, MagicMock

import pytest

from src.tools.base import ToolStatus
from src.tools.web_tools import (
    TTLCache,
    RateLimiter,
    RunBudget,
    UrlSafety,
    UrlSafetyError,
    is_content_type_allowed,
    WebFetchTool,
    WebSearchTool,
    WebSearchProvider,
    WebSearchResult,
    SearchResultItem,
    TavilyProvider,
    RateLimitError,
)


# =============================================================================
# TTLCache Tests
# =============================================================================

class TestTTLCache:
    """Tests for TTLCache helper class."""

    def test_cache_hit(self):
        """Test that cached values are returned within TTL."""
        cache = TTLCache(ttl_seconds=60)
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_cache_miss_no_key(self):
        """Test that missing keys return None."""
        cache = TTLCache(ttl_seconds=60)
        assert cache.get("nonexistent") is None

    def test_cache_miss_expired(self):
        """Test that expired entries return None."""
        cache = TTLCache(ttl_seconds=1)
        cache.set("key1", "value1")
        time.sleep(1.1)
        assert cache.get("key1") is None

    def test_make_key_deterministic(self):
        """Test that cache keys are deterministic regardless of param order."""
        key1 = TTLCache.make_key(query="test", max_results=5)
        key2 = TTLCache.make_key(max_results=5, query="test")
        assert key1 == key2

    def test_make_key_different_values(self):
        """Test that different values produce different keys."""
        key1 = TTLCache.make_key(query="test1")
        key2 = TTLCache.make_key(query="test2")
        assert key1 != key2

    def test_clear(self):
        """Test that clear removes all entries."""
        cache = TTLCache(ttl_seconds=60)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.clear()
        assert cache.get("key1") is None
        assert cache.get("key2") is None


# =============================================================================
# RateLimiter Tests
# =============================================================================

class TestRateLimiter:
    """Tests for RateLimiter helper class."""

    def test_allows_under_limit(self):
        """Test that requests under limit are allowed."""
        limiter = RateLimiter(requests_per_minute=5)
        for _ in range(5):
            assert limiter.check() is True
            limiter.record()

    def test_blocks_over_limit(self):
        """Test that requests over limit are blocked."""
        limiter = RateLimiter(requests_per_minute=2)
        limiter.record()
        limiter.record()
        assert limiter.check() is False

    def test_wait_time_when_limited(self):
        """Test that wait_time returns positive value when limited."""
        limiter = RateLimiter(requests_per_minute=1)
        limiter.record()
        wait = limiter.wait_time()
        assert wait > 0
        assert wait <= 60  # Should be less than window

    def test_wait_time_when_allowed(self):
        """Test that wait_time returns 0 when under limit."""
        limiter = RateLimiter(requests_per_minute=5)
        assert limiter.wait_time() == 0.0


# =============================================================================
# RunBudget Tests
# =============================================================================

class TestRunBudget:
    """Tests for RunBudget helper class."""

    def test_initial_budget(self):
        """Test that budget starts with expected values."""
        budget = RunBudget(max_searches=3, max_fetches=5)
        assert budget.can_search() is True
        assert budget.can_fetch() is True
        assert budget.searches_remaining == 3
        assert budget.fetches_remaining == 5

    def test_search_budget_exhaustion(self):
        """Test that search budget is properly tracked."""
        budget = RunBudget(max_searches=2, max_fetches=5)
        budget.record_search()
        assert budget.searches_remaining == 1
        budget.record_search()
        assert budget.can_search() is False
        assert budget.searches_remaining == 0

    def test_fetch_budget_exhaustion(self):
        """Test that fetch budget is properly tracked."""
        budget = RunBudget(max_searches=3, max_fetches=1)
        budget.record_fetch()
        assert budget.can_fetch() is False
        assert budget.fetches_remaining == 0

    def test_reset(self):
        """Test that reset restores budget."""
        budget = RunBudget(max_searches=2, max_fetches=2)
        budget.record_search()
        budget.record_fetch()
        budget.reset()
        assert budget.searches_remaining == 2
        assert budget.fetches_remaining == 2


# =============================================================================
# UrlSafety Tests
# =============================================================================

class TestUrlSafety:
    """Tests for UrlSafety SSRF protection."""

    def test_blocks_file_scheme(self):
        """Test that file:// URLs are blocked."""
        with pytest.raises(UrlSafetyError, match="scheme"):
            UrlSafety.validate("file:///etc/passwd")

    def test_blocks_ftp_scheme(self):
        """Test that ftp:// URLs are blocked."""
        with pytest.raises(UrlSafetyError, match="scheme"):
            UrlSafety.validate("ftp://example.com/file")

    def test_blocks_javascript_scheme(self):
        """Test that javascript: URLs are blocked."""
        with pytest.raises(UrlSafetyError, match="scheme"):
            UrlSafety.validate("javascript:alert(1)")

    def test_blocks_localhost(self):
        """Test that localhost URLs are blocked."""
        with pytest.raises(UrlSafetyError):
            UrlSafety.validate("http://localhost/admin")

    def test_blocks_localhost_with_trailing_dot(self):
        """Test that localhost. (with trailing dot) is blocked."""
        with pytest.raises(UrlSafetyError):
            UrlSafety.validate("http://localhost./admin")

    def test_blocks_subdomain_localhost(self):
        """Test that *.localhost is blocked."""
        with pytest.raises(UrlSafetyError):
            UrlSafety.validate("http://foo.localhost/admin")

    def test_blocks_local_suffix(self):
        """Test that *.local is blocked."""
        with pytest.raises(UrlSafetyError):
            UrlSafety.validate("http://myserver.local/admin")

    def test_blocks_internal_suffix(self):
        """Test that *.internal is blocked."""
        with pytest.raises(UrlSafetyError):
            UrlSafety.validate("http://api.internal/data")

    def test_blocks_private_ip_direct(self):
        """Test that direct private IPs are blocked."""
        with pytest.raises(UrlSafetyError):
            UrlSafety.validate("http://192.168.1.1/")

    def test_blocks_loopback_ip(self):
        """Test that loopback IP is blocked."""
        with pytest.raises(UrlSafetyError):
            UrlSafety.validate("http://127.0.0.1/")

    def test_blocks_private_ip_via_dns(self):
        """Test that DNS resolving to private IP is blocked."""
        # Mock DNS to return 10.0.0.1
        with patch('src.tools.web_tools.socket.getaddrinfo') as mock_dns:
            mock_dns.return_value = [
                (2, 1, 6, '', ('10.0.0.1', 80))
            ]
            with pytest.raises(UrlSafetyError, match="10.0.0.1"):
                UrlSafety.validate("http://internal.example.com/")

    def test_blocks_cloud_metadata(self):
        """Test that cloud metadata endpoint is blocked."""
        with pytest.raises(UrlSafetyError):
            UrlSafety.validate("http://169.254.169.254/latest/meta-data/")

    def test_blocks_ipv6_loopback(self):
        """Test that IPv6 loopback is blocked."""
        with pytest.raises(UrlSafetyError):
            UrlSafety.validate("http://[::1]/")

    def test_blocks_uncommon_port(self):
        """Test that non-standard ports are blocked."""
        with pytest.raises(UrlSafetyError, match="port"):
            UrlSafety.validate("http://example.com:22/")

    def test_blocks_port_8080(self):
        """Test that port 8080 is blocked (v1 minimal surface)."""
        with pytest.raises(UrlSafetyError, match="port"):
            UrlSafety.validate("http://example.com:8080/")

    def test_blocks_long_url(self):
        """Test that overly long URLs are blocked."""
        long_url = "https://example.com/" + "a" * 2100
        with pytest.raises(UrlSafetyError, match="too long"):
            UrlSafety.validate(long_url)

    def test_allows_valid_https(self):
        """Test that valid HTTPS URLs are allowed."""
        # Mock DNS to return a public IP
        with patch('src.tools.web_tools.socket.getaddrinfo') as mock_dns:
            mock_dns.return_value = [
                (2, 1, 6, '', ('93.184.216.34', 443))  # example.com IP
            ]
            url = UrlSafety.validate("https://example.com/page")
            assert url == "https://example.com/page"

    def test_allows_valid_http(self):
        """Test that valid HTTP URLs are allowed."""
        with patch('src.tools.web_tools.socket.getaddrinfo') as mock_dns:
            mock_dns.return_value = [
                (2, 1, 6, '', ('93.184.216.34', 80))
            ]
            url = UrlSafety.validate("http://example.com/page")
            assert url == "http://example.com/page"

    def test_hostname_normalization(self):
        """Test hostname normalization (lowercase, strip trailing dot)."""
        assert UrlSafety.normalize_hostname("EXAMPLE.COM.") == "example.com"
        assert UrlSafety.normalize_hostname("Example.Com") == "example.com"

    def test_is_ip_blocked_private_ranges(self):
        """Test IP blocking for various private ranges."""
        # RFC1918
        assert UrlSafety.is_ip_blocked("10.0.0.1")[0] is True
        assert UrlSafety.is_ip_blocked("172.16.0.1")[0] is True
        assert UrlSafety.is_ip_blocked("192.168.0.1")[0] is True

        # Loopback
        assert UrlSafety.is_ip_blocked("127.0.0.1")[0] is True

        # Link-local
        assert UrlSafety.is_ip_blocked("169.254.1.1")[0] is True

        # CGNAT
        assert UrlSafety.is_ip_blocked("100.64.0.1")[0] is True

    def test_is_ip_allowed_public(self):
        """Test that public IPs are allowed."""
        assert UrlSafety.is_ip_blocked("8.8.8.8")[0] is False
        assert UrlSafety.is_ip_blocked("93.184.216.34")[0] is False


# =============================================================================
# Content Type Tests
# =============================================================================

class TestContentType:
    """Tests for content-type validation."""

    def test_allows_text_html(self):
        """Test that text/html is allowed."""
        allowed, base = is_content_type_allowed("text/html; charset=utf-8")
        assert allowed is True
        assert base == "text/html"

    def test_allows_text_plain(self):
        """Test that text/plain is allowed."""
        allowed, base = is_content_type_allowed("text/plain")
        assert allowed is True

    def test_allows_application_json(self):
        """Test that application/json is allowed."""
        allowed, base = is_content_type_allowed("application/json")
        assert allowed is True

    def test_allows_application_xml(self):
        """Test that application/xml is allowed."""
        allowed, base = is_content_type_allowed("application/xml")
        assert allowed is True

    def test_blocks_application_pdf(self):
        """Test that application/pdf is blocked."""
        allowed, base = is_content_type_allowed("application/pdf")
        assert allowed is False
        assert base == "application/pdf"

    def test_blocks_image_types(self):
        """Test that image types are blocked."""
        allowed, _ = is_content_type_allowed("image/png")
        assert allowed is False
        allowed, _ = is_content_type_allowed("image/jpeg")
        assert allowed is False

    def test_blocks_empty(self):
        """Test that empty content-type is blocked."""
        allowed, _ = is_content_type_allowed("")
        assert allowed is False


# =============================================================================
# WebFetchTool Tests
# =============================================================================

class TestWebFetchTool:
    """Tests for WebFetchTool."""

    def test_blocks_ssrf_localhost(self):
        """Test that localhost URLs are blocked."""
        tool = WebFetchTool()
        result = tool.execute(url="http://localhost/admin")
        assert result.status == ToolStatus.ERROR
        assert "blocked" in result.error.lower()

    def test_blocks_ssrf_private_ip(self):
        """Test that private IPs are blocked."""
        tool = WebFetchTool()
        result = tool.execute(url="http://192.168.1.1/")
        assert result.status == ToolStatus.ERROR
        assert "blocked" in result.error.lower()

    def test_enforces_byte_cap_streaming(self):
        """
        Test that byte cap is enforced during streaming.

        WebFetchTool uses sync httpx.Client with stream=True context manager.
        """
        tool = WebFetchTool(max_content_bytes=100)

        # Create mock response that yields large chunks
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {'content-type': 'text/html'}
        mock_response.reason_phrase = 'OK'
        # iter_bytes yields 10KB chunks - tool should stop after ~100 bytes
        mock_response.iter_bytes.return_value = iter([b'x' * 10000] * 100)

        # Mock context manager for response
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)

        # Mock client.stream() context manager
        mock_client = MagicMock()
        mock_client.stream.return_value = mock_response

        # Mock Client class
        with patch('src.tools.web_tools.httpx.Client') as mock_client_class:
            mock_client_class.return_value.__enter__ = Mock(return_value=mock_client)
            mock_client_class.return_value.__exit__ = Mock(return_value=False)

            # Also patch UrlSafety to allow test URL
            with patch.object(UrlSafety, 'validate', return_value="https://example.com/large"):
                result = tool.execute(url="https://example.com/large")

            # Should truncate to ~100 bytes, not download full 1MB
            assert result.status == ToolStatus.SUCCESS
            # Output should be truncated (check for truncation notice)
            assert "truncated" in result.output.lower()

    def test_rejects_binary_content_type(self):
        """Test that binary content-types are rejected before downloading body."""
        tool = WebFetchTool()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {'content-type': 'application/pdf'}
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)

        mock_client = MagicMock()
        mock_client.stream.return_value = mock_response

        with patch('src.tools.web_tools.httpx.Client') as mock_client_class:
            mock_client_class.return_value.__enter__ = Mock(return_value=mock_client)
            mock_client_class.return_value.__exit__ = Mock(return_value=False)

            with patch.object(UrlSafety, 'validate', return_value="https://example.com/file.pdf"):
                result = tool.execute(url="https://example.com/file.pdf")

            assert result.status == ToolStatus.ERROR
            assert "content-type" in result.error.lower()

    def test_extracts_text_from_html(self):
        """Test HTML to text extraction."""
        tool = WebFetchTool()
        html = "<html><head><script>bad</script></head><body><h1>Title</h1><p>Content</p></body></html>"
        text = tool._extract_text(html)
        assert "Title" in text
        assert "Content" in text
        assert "bad" not in text  # Script stripped

    def test_extracts_text_strips_style(self):
        """Test that style tags are stripped."""
        tool = WebFetchTool()
        html = "<html><head><style>.foo { color: red; }</style></head><body>Text</body></html>"
        text = tool._extract_text(html)
        assert "Text" in text
        assert "color" not in text

    def test_budget_exceeded(self):
        """Test that exceeding fetch budget returns error."""
        budget = RunBudget(max_searches=3, max_fetches=0)
        tool = WebFetchTool()
        tool.set_run_budget(budget)

        result = tool.execute(url="https://example.com/")
        assert result.status == ToolStatus.ERROR
        assert "budget" in result.error.lower()

    def test_redirect_not_followed(self):
        """Test that redirects are reported, not followed."""
        tool = WebFetchTool()

        mock_response = MagicMock()
        mock_response.status_code = 301
        mock_response.headers = {
            'content-type': 'text/html',
            'location': 'https://other.com/page'
        }
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)

        mock_client = MagicMock()
        mock_client.stream.return_value = mock_response

        with patch('src.tools.web_tools.httpx.Client') as mock_client_class:
            mock_client_class.return_value.__enter__ = Mock(return_value=mock_client)
            mock_client_class.return_value.__exit__ = Mock(return_value=False)

            with patch.object(UrlSafety, 'validate', return_value="https://example.com/old"):
                result = tool.execute(url="https://example.com/old")

            assert result.status == ToolStatus.ERROR
            assert "redirect" in result.error.lower()
            assert "other.com" in result.error

    def test_cache_hit(self):
        """Test that cached results are returned."""
        tool = WebFetchTool()

        # Pre-populate cache
        cache_key = TTLCache.make_key(url="https://example.com/page", extract_text=True)
        tool.cache.set(cache_key, "Cached content")

        # Bypass URL validation since we're testing cache
        with patch.object(UrlSafety, 'validate', return_value="https://example.com/page"):
            result = tool.execute(url="https://example.com/page")

        assert result.status == ToolStatus.SUCCESS
        assert result.output == "Cached content"
        assert result.metadata.get("cache_hit") is True


# =============================================================================
# WebSearchTool Tests
# =============================================================================

class TestWebSearchTool:
    """Tests for WebSearchTool."""

    def test_returns_citations(self):
        """Test that search results include citations."""
        mock_provider = Mock(spec=WebSearchProvider)
        mock_provider.search.return_value = WebSearchResult(
            results=[SearchResultItem(
                title="Python 3.12",
                url="https://docs.python.org/3/whatsnew/3.12.html",
                snippet="What's new in Python 3.12",
                domain="docs.python.org"
            )],
            answer="Python 3.12 introduces..."
        )

        tool = WebSearchTool(provider=mock_provider)
        result = tool.execute(query="Python 3.12 features")

        assert result.status == ToolStatus.SUCCESS
        assert "docs.python.org" in result.output
        assert "https://docs.python.org" in result.output
        assert "Source:" in result.output  # Citation format

    def test_formats_summary(self):
        """Test that AI summary is included when available."""
        mock_provider = Mock(spec=WebSearchProvider)
        mock_provider.search.return_value = WebSearchResult(
            results=[SearchResultItem(
                title="Test",
                url="https://example.com",
                snippet="Test snippet",
                domain="example.com"
            )],
            answer="This is the AI summary"
        )

        tool = WebSearchTool(provider=mock_provider)
        result = tool.execute(query="test")

        assert "**Summary:**" in result.output
        assert "This is the AI summary" in result.output

    def test_handles_429_retry(self):
        """Test that 429 errors trigger one retry."""
        mock_provider = Mock(spec=WebSearchProvider)
        mock_provider.search.side_effect = [
            RateLimitError("429"),
            WebSearchResult(results=[], answer=None)
        ]

        tool = WebSearchTool(provider=mock_provider)
        result = tool.execute(query="test")

        # Should retry once, then succeed
        assert mock_provider.search.call_count == 2
        assert result.status == ToolStatus.SUCCESS

    def test_budget_exceeded(self):
        """Test that exceeding search budget returns error."""
        budget = RunBudget(max_searches=0, max_fetches=5)
        mock_provider = Mock(spec=WebSearchProvider)

        tool = WebSearchTool(provider=mock_provider)
        tool.set_run_budget(budget)

        result = tool.execute(query="test")
        assert result.status == ToolStatus.ERROR
        assert "budget" in result.error.lower()

    def test_empty_query(self):
        """Test that empty query returns error."""
        tool = WebSearchTool(provider=Mock(spec=WebSearchProvider))
        result = tool.execute(query="")
        assert result.status == ToolStatus.ERROR
        assert "empty" in result.error.lower()

    def test_query_sanitization(self):
        """Test that query is sanitized."""
        tool = WebSearchTool(provider=Mock(spec=WebSearchProvider))

        # Test length limit
        long_query = "a" * 1000
        sanitized = tool._sanitize_query(long_query)
        assert len(sanitized) <= 500

        # Test whitespace collapse
        assert tool._sanitize_query("  multiple   spaces  ") == "multiple spaces"

    def test_cache_hit(self):
        """Test that cached results are returned."""
        mock_provider = Mock(spec=WebSearchProvider)
        tool = WebSearchTool(provider=mock_provider)

        # Pre-populate cache
        cache_key = TTLCache.make_key(
            query="test query",
            max_results=5,
            search_depth="basic",
            include_domains="None",
            exclude_domains="None",
        )
        tool.cache.set(cache_key, "Cached search results")

        result = tool.execute(query="test query")

        assert result.status == ToolStatus.SUCCESS
        assert result.output == "Cached search results"
        assert result.metadata.get("cache_hit") is True
        # Provider should not be called
        mock_provider.search.assert_not_called()

    def test_no_results(self):
        """Test handling of empty search results."""
        mock_provider = Mock(spec=WebSearchProvider)
        mock_provider.search.return_value = WebSearchResult(results=[], answer=None)

        tool = WebSearchTool(provider=mock_provider)
        result = tool.execute(query="obscure query")

        assert result.status == ToolStatus.SUCCESS
        assert "no search results" in result.output.lower()


# =============================================================================
# TavilyProvider Tests
# =============================================================================

class TestTavilyProvider:
    """Tests for TavilyProvider."""

    def test_init_without_api_key_raises(self):
        """Test that missing API key raises ValueError."""
        with patch.dict('os.environ', {}, clear=True):
            with pytest.raises(ValueError, match="API key"):
                TavilyProvider()

    def test_init_with_api_key(self):
        """Test initialization with API key."""
        provider = TavilyProvider(api_key="test_key")
        assert provider.api_key == "test_key"

    def test_search_success(self):
        """Test successful search."""
        provider = TavilyProvider(api_key="test_key")

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {
                    "title": "Test Result",
                    "url": "https://example.com/page",
                    "content": "Test content snippet"
                }
            ],
            "answer": "Test answer"
        }

        with patch('src.tools.web_tools.httpx.Client') as mock_client_class:
            mock_client = Mock()
            mock_client.post.return_value = mock_response
            mock_client.__enter__ = Mock(return_value=mock_client)
            mock_client.__exit__ = Mock(return_value=False)
            mock_client_class.return_value = mock_client

            result = provider.search(query="test")

        assert len(result.results) == 1
        assert result.results[0].title == "Test Result"
        assert result.results[0].domain == "example.com"
        assert result.answer == "Test answer"

    def test_search_rate_limit(self):
        """Test that 429 raises RateLimitError."""
        provider = TavilyProvider(api_key="test_key")

        mock_response = Mock()
        mock_response.status_code = 429

        with patch('src.tools.web_tools.httpx.Client') as mock_client_class:
            mock_client = Mock()
            mock_client.post.return_value = mock_response
            mock_client.__enter__ = Mock(return_value=mock_client)
            mock_client.__exit__ = Mock(return_value=False)
            mock_client_class.return_value = mock_client

            with pytest.raises(RateLimitError):
                provider.search(query="test")


# =============================================================================
# Integration Tests
# =============================================================================

# Load .env for integration tests (API keys)
from pathlib import Path
from dotenv import load_dotenv
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)


@pytest.mark.integration
class TestWebToolsIntegration:
    """
    Integration tests that require real network access.

    Run with: pytest -m integration
    Requires: TAVILY_API_KEY environment variable for search tests
    """

    def test_real_fetch_httpbin(self):
        """Test fetching from httpbin.org."""
        tool = WebFetchTool()
        result = tool.execute(url="https://httpbin.org/html")

        assert result.status == ToolStatus.SUCCESS
        assert "Herman Melville" in result.output  # Known content

    def test_real_fetch_blocked_private(self):
        """Test that real private IPs are blocked."""
        tool = WebFetchTool()
        result = tool.execute(url="http://192.168.1.1/")

        assert result.status == ToolStatus.ERROR
        assert "blocked" in result.error.lower()

    @pytest.mark.skipif(
        not __import__('os').getenv('TAVILY_API_KEY'),
        reason="TAVILY_API_KEY not set"
    )
    def test_real_search_with_citations(self):
        """Test real Tavily search returns citations."""
        tool = WebSearchTool()
        result = tool.execute(query="Python asyncio tutorial")

        assert result.status == ToolStatus.SUCCESS
        assert "Source:" in result.output
        assert "http" in result.output
