"""Jira connection via mcp-atlassian MCP server (sooperset/mcp-atlassian).

Supports multiple named profiles (e.g. "personal", "corporate").
Each profile stores its Jira URL and username in a JSON config file.
API tokens are stored securely in SecretStore (OS keychain / encrypted file).

Transport: stdio via `uvx mcp-atlassian`
Config dir: .clarity/integrations/jira/<profile>.json  (no secrets)
Secrets:    SecretStore key "jira_api_token_<profile>"
"""

import json
import logging
from pathlib import Path
from typing import Optional

from src.integrations.mcp.config import McpServerConfig

try:
    from src.observability import get_logger
    logger = get_logger("integrations.jira.connection")
except ImportError:
    logger = logging.getLogger(__name__)

# Config directory for all Jira profiles
DEFAULT_CONFIG_DIR = Path(".clarity") / "integrations" / "jira"


def _secret_key(profile: str) -> str:
    """SecretStore key for a profile's API token."""
    return f"jira_api_token_{profile}"


class JiraConnection:
    """Manages a single Jira profile connection via mcp-atlassian.

    Config file (.clarity/integrations/jira/<profile>.json) holds:
      - jira_url: Jira Cloud URL (e.g. "https://mycompany.atlassian.net")
      - username: Atlassian account email
      - enabled: whether the profile is active

    API token is stored separately in SecretStore (never in the JSON file).

    Usage:
        conn = JiraConnection("corporate")
        conn.configure(
            jira_url="https://mycompany.atlassian.net",
            username="user@mycompany.com",
            api_token="ATATT3x...",
        )
        config = conn.get_mcp_config()  # -> McpServerConfig for StdioTransport
    """

    def __init__(
        self,
        profile: str = "default",
        config_dir: Path | None = None,
        secret_store=None,
    ):
        self._profile = profile
        self._config_dir = config_dir or DEFAULT_CONFIG_DIR
        self._config_path = self._config_dir / f"{profile}.json"
        self._secret_store = secret_store
        self._jira_url: str | None = None
        self._username: str | None = None
        self._enabled: bool = False
        self._load_config()

    def _get_secret_store(self):
        """Lazy-load SecretStore (avoids import cost if never needed)."""
        if self._secret_store is None:
            from src.integrations.secrets import get_secret_store
            self._secret_store = get_secret_store()
        return self._secret_store

    def _load_config(self) -> None:
        """Load profile config from disk (no secrets)."""
        if self._config_path.exists():
            try:
                data = json.loads(self._config_path.read_text())
                self._jira_url = data.get("jira_url")
                self._username = data.get("username")
                self._enabled = data.get("enabled", False)
            except (json.JSONDecodeError, OSError):
                logger.warning("jira_config_load_failed", profile=self._profile)

    def _save_config(self) -> None:
        """Persist profile config to disk (no secrets ever written here)."""
        self._config_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "jira_url": self._jira_url,
            "username": self._username,
            "enabled": self._enabled,
        }
        self._config_path.write_text(json.dumps(data, indent=2))

    @property
    def profile(self) -> str:
        return self._profile

    @property
    def jira_url(self) -> str | None:
        return self._jira_url

    @property
    def username(self) -> str | None:
        return self._username

    @property
    def enabled(self) -> bool:
        return self._enabled

    def configure(self, jira_url: str, username: str, api_token: str) -> None:
        """Set Jira credentials and enable the profile.

        Args:
            jira_url: e.g. "https://mycompany.atlassian.net"
            username: Atlassian account email
            api_token: API token from id.atlassian.com (stored in SecretStore)
        """
        if not jira_url:
            raise ValueError("jira_url is required")
        if not username:
            raise ValueError("username is required")
        if not api_token:
            raise ValueError("api_token is required")

        self._jira_url = jira_url.rstrip("/")
        self._username = username
        self._enabled = True
        self._save_config()

        # Store token securely (never in the JSON file)
        store = self._get_secret_store()
        store.set(_secret_key(self._profile), api_token)

        logger.info(
            "jira_configured",
            profile=self._profile,
            jira_url=self._jira_url,
        )

    def disable(self) -> None:
        """Disable the profile (keeps config on disk, token in SecretStore)."""
        self._enabled = False
        self._save_config()
        logger.info("jira_disabled", profile=self._profile)

    def has_api_token(self) -> bool:
        """Check if an API token exists in SecretStore for this profile."""
        store = self._get_secret_store()
        return store.has(_secret_key(self._profile))

    def _get_api_token(self) -> str | None:
        """Retrieve API token from SecretStore."""
        store = self._get_secret_store()
        return store.get(_secret_key(self._profile))

    def delete_api_token(self) -> None:
        """Remove API token from SecretStore."""
        store = self._get_secret_store()
        store.delete(_secret_key(self._profile))

    def is_configured(self) -> bool:
        """Check if profile has all required fields including API token."""
        return bool(
            self._enabled
            and self._jira_url
            and self._username
            and self.has_api_token()
        )

    def get_mcp_config(self) -> McpServerConfig:
        """Build McpServerConfig for mcp-atlassian stdio transport.

        Returns:
            McpServerConfig with command `uvx mcp-atlassian` and
            JIRA_URL/JIRA_USERNAME/JIRA_API_TOKEN as extra_env.

        Raises:
            ValueError: If profile is not fully configured.
        """
        if not self._jira_url:
            raise ValueError(
                f"Jira profile '{self._profile}' not configured: no jira_url"
            )
        if not self._username:
            raise ValueError(
                f"Jira profile '{self._profile}' not configured: no username"
            )

        api_token = self._get_api_token()
        if not api_token:
            raise ValueError(
                f"Jira profile '{self._profile}' not configured: "
                f"no API token in SecretStore (key: {_secret_key(self._profile)})"
            )

        return McpServerConfig(
            name=f"mcp-atlassian-{self._profile}",
            command="uvx mcp-atlassian",
            tool_prefix="",  # mcp-atlassian already prefixes tools with jira_
            auth_secret_key="",
            extra_env={
                "JIRA_URL": self._jira_url,
                "JIRA_USERNAME": self._username,
                "JIRA_API_TOKEN": api_token,
            },
            connect_timeout=30.0,
            invoke_timeout=60.0,
            discovery_timeout=30.0,
            max_result_chars=8192,
            max_result_items=50,
            cache_ttl_seconds=3600.0,
        )

    @classmethod
    def list_profiles(cls, config_dir: Path | None = None) -> list[str]:
        """list all configured profile names.

        Returns:
            Sorted list of profile names (e.g. ["corporate", "personal"]).
        """
        d = config_dir or DEFAULT_CONFIG_DIR
        if not d.exists():
            return []
        return sorted(
            p.stem for p in d.glob("*.json")
            if p.is_file()
        )
