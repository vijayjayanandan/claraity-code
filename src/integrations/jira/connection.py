"""Jira connection state and configuration.

Thin module: manages connected state and config persistence.

Auth uses Atlassian's Remote MCP Server at https://mcp.atlassian.com/v1/mcp
with OAuth 2.1 via the `mcp-remote` npm proxy. The proxy handles the browser-
based OAuth flow and caches tokens locally. No API tokens or SecretStore needed.

Transport: stdio via `npx mcp-remote https://mcp.atlassian.com/v1/mcp`

Config file: .clarity/integrations/jira.json (no secrets)
"""

import json
import logging
import shutil
from pathlib import Path
from typing import Optional

from src.integrations.mcp.config import McpServerConfig

try:
    from src.observability import get_logger
    logger = get_logger("integrations.jira.connection")
except ImportError:
    logger = logging.getLogger(__name__)

# Atlassian Remote MCP Server (centralized, not per-instance)
ATLASSIAN_MCP_URL = "https://mcp.atlassian.com/v1/mcp"

# Default config file location
DEFAULT_CONFIG_PATH = Path(".clarity") / "integrations" / "jira.json"


class JiraConnection:
    """Manages Jira integration state and configuration.

    Auth is handled by the Atlassian Remote MCP Server's OAuth 2.1 flow,
    proxied through `npx mcp-remote`. This class:
    - Persists connection config (cloud URL, enabled flag) to disk
    - Checks that npx/mcp-remote is available
    - Builds McpServerConfig for the MCP client (stdio transport)
    """

    def __init__(self, config_path: Optional[Path] = None):
        self._config_path = config_path or DEFAULT_CONFIG_PATH
        self._cloud_url: Optional[str] = None
        self._enabled: bool = False
        self._load_config()

    def _load_config(self) -> None:
        """Load config from disk (no secrets)."""
        if self._config_path.exists():
            try:
                data = json.loads(self._config_path.read_text())
                self._cloud_url = data.get("cloud_url")
                self._enabled = data.get("enabled", False)
            except (json.JSONDecodeError, OSError):
                logger.warning("jira_config_load_failed")

    def _save_config(self) -> None:
        """Persist config to disk (no secrets ever written here)."""
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "cloud_url": self._cloud_url,
            "enabled": self._enabled,
        }
        self._config_path.write_text(json.dumps(data, indent=2))

    @property
    def cloud_url(self) -> Optional[str]:
        return self._cloud_url

    @property
    def enabled(self) -> bool:
        return self._enabled

    def configure(self, cloud_url: str) -> None:
        """Set the Jira Cloud URL and enable the integration.

        Args:
            cloud_url: e.g. "https://mycompany.atlassian.net"
        """
        self._cloud_url = cloud_url.rstrip("/")
        self._enabled = True
        self._save_config()
        logger.info("jira_configured", cloud_url=self._cloud_url)

    def disable(self) -> None:
        """Disable the Jira integration."""
        self._enabled = False
        self._save_config()
        logger.info("jira_disabled")

    def is_connected(self) -> bool:
        """Check if Jira is configured and mcp-remote is available.

        OAuth tokens are managed by mcp-remote (cached locally by the proxy).
        We just need npx to be on PATH.
        """
        if not self._enabled or not self._cloud_url:
            return False
        return shutil.which("npx") is not None

    def get_mcp_config(self) -> McpServerConfig:
        """Build McpServerConfig for the Atlassian Remote MCP Server.

        Uses stdio transport via `npx mcp-remote` which handles:
        - OAuth 2.1 browser-based auth flow
        - Token caching and refresh
        - MCP JSON-RPC framing over stdin/stdout

        Returns:
            McpServerConfig ready for McpClient with StdioTransport.
        """
        if not self._cloud_url:
            raise ValueError("Jira not configured: no cloud_url set")

        return McpServerConfig(
            name="atlassian-rovo",
            command=f"npx -y mcp-remote {ATLASSIAN_MCP_URL}",
            tool_prefix="jira",
            # No auth_secret_key needed - mcp-remote handles OAuth
            auth_secret_key="",
            connect_timeout=60.0,   # First connect may trigger browser OAuth
            invoke_timeout=60.0,
            discovery_timeout=30.0,
            max_result_chars=8192,
            max_result_items=50,
            cache_ttl_seconds=3600.0,
        )
