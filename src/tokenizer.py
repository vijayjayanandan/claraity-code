"""Resilient tokenizer wrapper around tiktoken.

tiktoken downloads BPE vocabulary data on first use. This fails in
corporate environments with SSL-inspecting proxies.  This module
provides ``get_encoding()`` which falls back to a character-based
estimator when the download cannot complete.
"""

from src.observability import get_logger

logger = get_logger(__name__)

_CHARS_PER_TOKEN = 4  # Conservative average for English text


class _FallbackEncoding:
    """Character-based token estimator used when tiktoken is unavailable."""

    def encode(self, text: str) -> list[int]:
        """Return a fake token list whose *length* approximates real token count."""
        n = max(1, len(text) // _CHARS_PER_TOKEN)
        return list(range(n))


def get_encoding(name: str = "cl100k_base"):
    """Return a tiktoken encoding, or a fallback estimator on failure.

    The returned object supports ``.encode(text) -> list[int]`` which is
    the only method the codebase uses.
    """
    try:
        import tiktoken

        return tiktoken.get_encoding(name)
    except Exception as exc:
        logger.warning(
            "tiktoken_download_failed",
            encoding=name,
            error=str(exc),
            fallback="char_estimate",
        )
        return _FallbackEncoding()
