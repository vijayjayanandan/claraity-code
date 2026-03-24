"""MCP server configuration."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class McpServerConfig:
    """Configuration for an MCP server connection.

    All timeout and truncation limits live here (not scattered as constants).
    """

    # Server identity
    name: str  # e.g. "atlassian-rovo"
    server_url: str | None = None  # For remote (SSE) transport
    command: str | None = None  # For local (stdio) transport - full command string
    args: list[str] = field(default_factory=list)  # CLI args (used by settings layer)

    # Timeouts (seconds)
    connect_timeout: float = 30.0
    invoke_timeout: float = 60.0
    discovery_timeout: float = 30.0

    # Result handling
    max_result_chars: int = 8192  # Truncate results beyond this
    max_result_items: int = 50  # Max array items in result before truncation

    # Discovery cache
    cache_ttl_seconds: float = 3600.0  # 1 hour default

    # Auth (header names only; values come from SecretStore)
    auth_header_name: str = "Authorization"
    auth_secret_key: str = ""  # SecretStore key to look up at connect time

    # Extra headers (non-secret, e.g. content-type)
    extra_headers: dict[str, str] = field(default_factory=dict)

    # Extra environment variables for stdio subprocess (e.g. Okta config)
    extra_env: dict[str, str] = field(default_factory=dict)

    # Tool name prefix for namespacing (e.g. "jira" -> "jira_searchJiraIssuesUsingJql")
    tool_prefix: str = ""
