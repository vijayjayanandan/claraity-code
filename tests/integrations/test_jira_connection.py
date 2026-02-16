"""Tests for profile-based JiraConnection (mcp-atlassian + SecretStore)."""

import json
import pytest
from pathlib import Path
from typing import Dict, Optional

from src.integrations.jira.connection import JiraConnection, _secret_key


# ---------------------------------------------------------------------------
# Fake SecretStore for testing (no OS keychain or encryption needed)
# ---------------------------------------------------------------------------

class FakeSecretStore:
    """In-memory SecretStore for test isolation."""

    def __init__(self):
        self._data: Dict[str, str] = {}

    def get(self, key: str) -> Optional[str]:
        return self._data.get(key)

    def set(self, key: str, value: str) -> None:
        self._data[key] = value

    def delete(self, key: str) -> None:
        self._data.pop(key, None)

    def has(self, key: str) -> bool:
        return key in self._data


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def config_dir(tmp_path):
    """Temporary config directory for test isolation."""
    return tmp_path / "jira"


@pytest.fixture
def secret_store():
    """Fresh in-memory secret store."""
    return FakeSecretStore()


@pytest.fixture
def conn(config_dir, secret_store):
    """Fresh JiraConnection with temp config dir and fake secret store."""
    return JiraConnection(profile="test", config_dir=config_dir, secret_store=secret_store)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class TestConfigure:
    def test_configure_saves_non_secret_fields(self, conn, config_dir):
        conn.configure(
            jira_url="https://mycompany.atlassian.net",
            username="user@mycompany.com",
            api_token="ATATT3x-test-token",
        )

        assert conn.jira_url == "https://mycompany.atlassian.net"
        assert conn.username == "user@mycompany.com"
        assert conn.enabled is True
        assert conn.profile == "test"

        # Verify file on disk has NO api_token
        data = json.loads((config_dir / "test.json").read_text())
        assert data["jira_url"] == "https://mycompany.atlassian.net"
        assert data["username"] == "user@mycompany.com"
        assert data["enabled"] is True
        assert "api_token" not in data

    def test_configure_stores_token_in_secret_store(self, conn, secret_store):
        conn.configure(
            jira_url="https://mycompany.atlassian.net",
            username="user@mycompany.com",
            api_token="ATATT3x-test-token",
        )

        assert secret_store.get(_secret_key("test")) == "ATATT3x-test-token"

    def test_configure_strips_trailing_slash(self, conn):
        conn.configure(
            jira_url="https://mycompany.atlassian.net/",
            username="user@mycompany.com",
            api_token="token",
        )
        assert conn.jira_url == "https://mycompany.atlassian.net"

    def test_configure_rejects_empty_jira_url(self, conn):
        with pytest.raises(ValueError, match="jira_url"):
            conn.configure(jira_url="", username="user@x.com", api_token="tok")

    def test_configure_rejects_empty_username(self, conn):
        with pytest.raises(ValueError, match="username"):
            conn.configure(jira_url="https://x.atlassian.net", username="", api_token="tok")

    def test_configure_rejects_empty_api_token(self, conn):
        with pytest.raises(ValueError, match="api_token"):
            conn.configure(jira_url="https://x.atlassian.net", username="u@x.com", api_token="")

    def test_disable(self, conn):
        conn.configure(
            jira_url="https://x.atlassian.net",
            username="u@x.com",
            api_token="tok",
        )
        conn.disable()
        assert conn.enabled is False
        assert conn.is_configured() is False


# ---------------------------------------------------------------------------
# Config persistence and reload
# ---------------------------------------------------------------------------

class TestPersistence:
    def test_config_survives_reload(self, config_dir, secret_store):
        conn1 = JiraConnection(profile="test", config_dir=config_dir, secret_store=secret_store)
        conn1.configure(
            jira_url="https://mycompany.atlassian.net",
            username="user@mycompany.com",
            api_token="ATATT3x-token",
        )

        # New instance from same config dir + same secret store
        conn2 = JiraConnection(profile="test", config_dir=config_dir, secret_store=secret_store)
        assert conn2.jira_url == "https://mycompany.atlassian.net"
        assert conn2.username == "user@mycompany.com"
        assert conn2.enabled is True
        assert conn2.has_api_token() is True

    def test_missing_config_file_loads_defaults(self, config_dir, secret_store):
        conn = JiraConnection(profile="nonexistent", config_dir=config_dir, secret_store=secret_store)
        assert conn.jira_url is None
        assert conn.username is None
        assert conn.enabled is False

    def test_corrupt_config_file_loads_defaults(self, config_dir, secret_store):
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "bad.json").write_text("not json{{{")
        conn = JiraConnection(profile="bad", config_dir=config_dir, secret_store=secret_store)
        assert conn.enabled is False

    def test_disabled_profile_persists(self, config_dir, secret_store):
        conn = JiraConnection(profile="test", config_dir=config_dir, secret_store=secret_store)
        conn.configure(
            jira_url="https://x.atlassian.net",
            username="u@x.com",
            api_token="tok",
        )
        conn.disable()

        reloaded = JiraConnection(profile="test", config_dir=config_dir, secret_store=secret_store)
        assert reloaded.enabled is False
        assert reloaded.jira_url == "https://x.atlassian.net"

    def test_no_secrets_in_config_file(self, conn, config_dir):
        """Config file must never contain tokens or passwords."""
        conn.configure(
            jira_url="https://test.atlassian.net",
            username="u@x.com",
            api_token="super-secret-token",
        )

        raw = (config_dir / "test.json").read_text()
        assert "super-secret-token" not in raw
        data = json.loads(raw)
        assert set(data.keys()) == {"jira_url", "username", "enabled"}


# ---------------------------------------------------------------------------
# API token management
# ---------------------------------------------------------------------------

class TestApiToken:
    def test_has_api_token_false_initially(self, conn):
        assert conn.has_api_token() is False

    def test_has_api_token_true_after_configure(self, conn):
        conn.configure(
            jira_url="https://x.atlassian.net",
            username="u@x.com",
            api_token="tok",
        )
        assert conn.has_api_token() is True

    def test_delete_api_token(self, conn):
        conn.configure(
            jira_url="https://x.atlassian.net",
            username="u@x.com",
            api_token="tok",
        )
        conn.delete_api_token()
        assert conn.has_api_token() is False


# ---------------------------------------------------------------------------
# is_configured
# ---------------------------------------------------------------------------

class TestIsConfigured:
    def test_not_configured_when_disabled(self, conn):
        assert conn.is_configured() is False

    def test_not_configured_without_api_token(self, config_dir, secret_store):
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "partial.json").write_text(json.dumps({
            "jira_url": "https://x.atlassian.net",
            "username": "u@x.com",
            "enabled": True,
        }))
        conn = JiraConnection(profile="partial", config_dir=config_dir, secret_store=secret_store)
        assert conn.is_configured() is False  # no token in SecretStore

    def test_configured_with_all_fields(self, conn):
        conn.configure(
            jira_url="https://x.atlassian.net",
            username="u@x.com",
            api_token="tok",
        )
        assert conn.is_configured() is True


# ---------------------------------------------------------------------------
# get_mcp_config
# ---------------------------------------------------------------------------

class TestGetMcpConfig:
    def test_builds_correct_command(self, conn):
        conn.configure(
            jira_url="https://mycompany.atlassian.net",
            username="user@mycompany.com",
            api_token="ATATT3x-token",
        )

        config = conn.get_mcp_config()
        assert config.command == "uvx mcp-atlassian"
        assert config.tool_prefix == ""  # mcp-atlassian already prefixes with jira_
        assert config.name == "mcp-atlassian-test"

    def test_extra_env_contains_jira_vars(self, conn):
        conn.configure(
            jira_url="https://mycompany.atlassian.net",
            username="user@mycompany.com",
            api_token="ATATT3x-token",
        )

        config = conn.get_mcp_config()
        assert config.extra_env["JIRA_URL"] == "https://mycompany.atlassian.net"
        assert config.extra_env["JIRA_USERNAME"] == "user@mycompany.com"
        assert config.extra_env["JIRA_API_TOKEN"] == "ATATT3x-token"

    def test_raises_without_jira_url(self, conn, secret_store):
        conn._enabled = True
        conn._username = "u@x.com"
        secret_store.set(_secret_key("test"), "tok")
        with pytest.raises(ValueError, match="jira_url"):
            conn.get_mcp_config()

    def test_raises_without_username(self, conn, secret_store):
        conn._enabled = True
        conn._jira_url = "https://x.atlassian.net"
        secret_store.set(_secret_key("test"), "tok")
        with pytest.raises(ValueError, match="username"):
            conn.get_mcp_config()

    def test_raises_without_api_token(self, conn):
        conn._enabled = True
        conn._jira_url = "https://x.atlassian.net"
        conn._username = "u@x.com"
        # No token in secret store
        with pytest.raises(ValueError, match="api_token"):
            conn.get_mcp_config()

    def test_no_auth_secret_key(self, conn):
        """API token passed via extra_env, not auth_secret_key."""
        conn.configure(
            jira_url="https://x.atlassian.net",
            username="u@x.com",
            api_token="tok",
        )
        config = conn.get_mcp_config()
        assert config.auth_secret_key == ""

    def test_same_tool_prefix_across_profiles(self, config_dir, secret_store):
        """All profiles use empty prefix (mcp-atlassian already prefixes with jira_)."""
        conn1 = JiraConnection(profile="personal", config_dir=config_dir, secret_store=secret_store)
        conn1.configure(
            jira_url="https://personal.atlassian.net",
            username="me@gmail.com",
            api_token="tok1",
        )
        conn2 = JiraConnection(profile="corporate", config_dir=config_dir, secret_store=secret_store)
        conn2.configure(
            jira_url="https://corp.atlassian.net",
            username="me@corp.com",
            api_token="tok2",
        )

        assert conn1.get_mcp_config().tool_prefix == ""
        assert conn2.get_mcp_config().tool_prefix == ""

    def test_different_mcp_server_names_per_profile(self, config_dir, secret_store):
        """Each profile gets a unique MCP server name."""
        conn1 = JiraConnection(profile="personal", config_dir=config_dir, secret_store=secret_store)
        conn1.configure(
            jira_url="https://personal.atlassian.net",
            username="me@gmail.com",
            api_token="tok1",
        )
        conn2 = JiraConnection(profile="corporate", config_dir=config_dir, secret_store=secret_store)
        conn2.configure(
            jira_url="https://corp.atlassian.net",
            username="me@corp.com",
            api_token="tok2",
        )

        assert conn1.get_mcp_config().name == "mcp-atlassian-personal"
        assert conn2.get_mcp_config().name == "mcp-atlassian-corporate"


# ---------------------------------------------------------------------------
# list_profiles
# ---------------------------------------------------------------------------

class TestListProfiles:
    def test_no_profiles_when_dir_missing(self, tmp_path):
        profiles = JiraConnection.list_profiles(config_dir=tmp_path / "nonexistent")
        assert profiles == []

    def test_lists_profile_names(self, config_dir, secret_store):
        conn1 = JiraConnection(profile="personal", config_dir=config_dir, secret_store=secret_store)
        conn1.configure(
            jira_url="https://personal.atlassian.net",
            username="me@gmail.com",
            api_token="tok1",
        )
        conn2 = JiraConnection(profile="corporate", config_dir=config_dir, secret_store=secret_store)
        conn2.configure(
            jira_url="https://corp.atlassian.net",
            username="me@corp.com",
            api_token="tok2",
        )

        profiles = JiraConnection.list_profiles(config_dir=config_dir)
        assert profiles == ["corporate", "personal"]  # sorted

    def test_ignores_non_json_files(self, config_dir, secret_store):
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "readme.txt").write_text("not a profile")
        (config_dir / "test.json").write_text(json.dumps({"enabled": True}))

        profiles = JiraConnection.list_profiles(config_dir=config_dir)
        assert profiles == ["test"]
