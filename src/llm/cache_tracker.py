"""Prompt cache metrics tracker.

Shared by all LLM backends that support prompt caching (OpenAI, Anthropic, etc.).
Tracks cache reads, writes, and hit rate to measure caching effectiveness.
"""

from typing import Any, Dict


class CacheTracker:
    """Accumulates prompt cache metrics across a session.

    Tracks cache reads, writes, and hit rate to measure
    the effectiveness of prompt caching.
    """

    def __init__(self):
        self.total_input_tokens = 0
        self.cache_read_tokens = 0
        self.cache_write_tokens = 0
        self.total_calls = 0
        self.cache_hits = 0

    def record(self, usage) -> None:
        """Record cache metrics from an API response usage object.

        Args:
            usage: The usage object from an OpenAI-compatible API response.
                   Can be an SDK object (with attributes) or a dict.
        """
        if not usage:
            return

        self.total_calls += 1

        # Support both SDK objects (attributes) and dicts (ProviderDelta.usage)
        if isinstance(usage, dict):
            prompt = usage.get("input_tokens") or 0
            cached = usage.get("cached_tokens") or 0
            # Anthropic-style fields from proxy
            cache_read = usage.get("cache_read_tokens") or 0
            cache_write = usage.get("cache_write_tokens") or 0
        else:
            prompt = getattr(usage, "prompt_tokens", 0) or 0
            # OpenAI-style
            details = getattr(usage, "prompt_tokens_details", None)
            cached = getattr(details, "cached_tokens", 0) or 0 if details else 0
            # Anthropic-style
            cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
            cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0

        self.total_input_tokens += prompt

        # Use whichever style reports a higher value
        read_tokens = max(cached, cache_read)
        self.cache_read_tokens += read_tokens
        self.cache_write_tokens += cache_write

        if read_tokens > 0:
            self.cache_hits += 1

    def summary(self) -> Dict[str, Any]:
        """Return a summary dict of cache performance.

        Calculates effective savings: cache reads save 90% but
        cache writes cost 25% extra. Net savings is the difference.
        """
        if self.total_calls == 0:
            return {"total_calls": 0, "message": "No LLM calls recorded"}

        hit_rate = (self.cache_hits / self.total_calls * 100) if self.total_calls > 0 else 0

        # Cost without caching: all tokens at 1.0x
        cost_without = self.total_input_tokens

        # Cost with caching: each bucket charged at its actual rate
        uncached_tokens = max(0, self.total_input_tokens - self.cache_read_tokens - self.cache_write_tokens)
        cost_with = (
            self.cache_read_tokens * 0.1       # 90% savings
            + self.cache_write_tokens * 1.25   # 25% surcharge
            + uncached_tokens * 1.0            # full price
        )

        savings_pct = ((cost_without - cost_with) / cost_without * 100) if cost_without > 0 else 0

        return {
            "total_calls": self.total_calls,
            "cache_hits": self.cache_hits,
            "hit_rate_pct": round(hit_rate, 1),
            "total_input_tokens": self.total_input_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "savings_pct": round(savings_pct, 1),
        }

    def format_summary(self) -> str:
        """Return a human-readable one-line summary."""
        s = self.summary()
        if s["total_calls"] == 0:
            return "[CACHE] No LLM calls recorded"
        return (
            f"[CACHE SUMMARY] {s['total_calls']} calls | "
            f"{s['cache_hits']} cache hits ({s['hit_rate_pct']}%) | "
            f"{s['cache_read_tokens']:,} tokens served from cache | "
            f"~{s['savings_pct']}% effective input cost reduction"
        )
