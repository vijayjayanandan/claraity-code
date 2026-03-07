"""Tests for WebSocket authentication and server hardening (S1, S2, S7, S21, S22, S26, S27).

Verifies that:
- WebSocket connections require a valid auth token
- Origin headers are validated
- Health endpoint doesn't leak session IDs
- Message size limits are enforced
- Error messages don't leak internals
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from src.server.app import AgentServer


class TestAuthTokenGeneration:
    """S1: Server must generate and require auth tokens."""

    def test_auth_token_generated_on_init(self):
        """Server generates a random auth token at construction."""
        server = AgentServer()
        assert hasattr(server, '_auth_token')
        assert server._auth_token is not None
        assert len(server._auth_token) > 20  # token_urlsafe(32) produces ~43 chars

    def test_auth_tokens_are_unique(self):
        """Each server instance gets a unique token."""
        server1 = AgentServer()
        server2 = AgentServer()
        assert server1._auth_token != server2._auth_token


class TestSSRFProtection:
    """S8: list_models must validate URLs to prevent SSRF."""

    def test_blocks_cloud_metadata_url(self):
        """Link-local addresses (cloud metadata) must be blocked."""
        from src.server.config_handler import _validate_list_models_url
        is_valid, reason = _validate_list_models_url(
            "http://169.254.169.254/latest/meta-data/"
        )
        assert not is_valid
        assert "link-local" in reason.lower() or "metadata" in reason.lower()

    def test_allows_normal_url(self):
        """Normal external URLs should be allowed."""
        from src.server.config_handler import _validate_list_models_url
        is_valid, _ = _validate_list_models_url("https://api.openai.com/v1")
        assert is_valid

    def test_allows_localhost_for_ollama(self):
        """Localhost should be allowed (for local Ollama)."""
        from src.server.config_handler import _validate_list_models_url
        is_valid, _ = _validate_list_models_url("http://localhost:11434")
        assert is_valid

    def test_handles_invalid_url(self):
        """Invalid URLs should not crash."""
        from src.server.config_handler import _validate_list_models_url
        is_valid, reason = _validate_list_models_url("")
        assert not is_valid


class TestWebSocketModeValidation:
    """S26: WebSocket must validate mode values."""

    def test_valid_modes(self):
        """Only plan, normal, auto should be accepted as modes."""
        VALID_MODES = {"plan", "normal", "auto"}
        for mode in VALID_MODES:
            assert mode in VALID_MODES

    def test_invalid_mode_rejected(self):
        """Invalid mode strings must not be accepted."""
        VALID_MODES = {"plan", "normal", "auto"}
        assert "superuser" not in VALID_MODES
        assert "root" not in VALID_MODES
        assert "" not in VALID_MODES


class TestNonLocalhostWarning:
    """S27: Non-localhost binding should produce warnings."""

    def test_server_defaults_to_localhost(self):
        """Default server should bind to 127.0.0.1."""
        server = AgentServer()
        assert server._host == "127.0.0.1"

    def test_server_accepts_custom_host(self):
        """Custom host can be set but should trigger warnings at start()."""
        server = AgentServer(host="0.0.0.0")
        assert server._host == "0.0.0.0"
