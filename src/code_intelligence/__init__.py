"""
Code Intelligence - LSP + MCP integration for AI Coding Agent.

Provides multi-tier context loading combining:
- LSP (Language Server Protocol) for symbol-level precision
- RAG (Retrieval Augmented Generation) for semantic search
- ClarAIty for architectural context
"""

from src.code_intelligence.cache import CacheEntry, LSPCache
from src.code_intelligence.lsp_client_manager import (
    LSPClientManager,
    LSPError,
    LSPQueryError,
    LSPServerNotFoundError,
    LSPServerStartupError,
    LSPTimeoutError,
)

__all__ = [
    # Cache
    "LSPCache",
    "CacheEntry",
    # LSP Client Manager
    "LSPClientManager",
    "LSPError",
    "LSPServerNotFoundError",
    "LSPServerStartupError",
    "LSPQueryError",
    "LSPTimeoutError",
]
