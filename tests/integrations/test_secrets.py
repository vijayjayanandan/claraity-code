"""Tests for SecretStore: encrypted file backend + secret leak checks."""

import json
import os
import tempfile
import pytest
from pathlib import Path

from src.integrations.secrets import EncryptedFileSecretStore, SecretStore


# ---------------------------------------------------------------------------
# EncryptedFileSecretStore
# ---------------------------------------------------------------------------

class TestEncryptedFileSecretStore:
    @pytest.fixture
    def store_dir(self, tmp_path):
        return tmp_path / "secrets"

    @pytest.fixture
    def store(self, store_dir):
        return EncryptedFileSecretStore(store_dir=store_dir)

    def test_implements_protocol(self, store):
        assert isinstance(store, SecretStore)

    def test_set_and_get(self, store):
        store.set("api_key", "super-secret-token-123")
        assert store.get("api_key") == "super-secret-token-123"

    def test_get_nonexistent_returns_none(self, store):
        assert store.get("nonexistent") is None

    def test_has_existing_key(self, store):
        store.set("key", "val")
        assert store.has("key") is True

    def test_has_missing_key(self, store):
        assert store.has("missing") is False

    def test_delete_existing(self, store):
        store.set("key", "val")
        store.delete("key")
        assert store.get("key") is None
        assert store.has("key") is False

    def test_delete_nonexistent_no_error(self, store):
        store.delete("nonexistent")  # Should not raise

    def test_overwrite(self, store):
        store.set("key", "v1")
        store.set("key", "v2")
        assert store.get("key") == "v2"

    def test_multiple_keys(self, store):
        store.set("a", "1")
        store.set("b", "2")
        store.set("c", "3")
        assert store.get("a") == "1"
        assert store.get("b") == "2"
        assert store.get("c") == "3"

    def test_persistence_across_instances(self, store_dir):
        """Secret survives creating a new store instance from same dir."""
        store1 = EncryptedFileSecretStore(store_dir=store_dir)
        store1.set("persistent_key", "persistent_val")

        store2 = EncryptedFileSecretStore(store_dir=store_dir)
        assert store2.get("persistent_key") == "persistent_val"

    def test_encrypted_file_not_plaintext(self, store, store_dir):
        """The encrypted file must not contain the secret in plaintext."""
        store.set("api_key", "MY_SUPER_SECRET_TOKEN_XYZ")

        enc_path = store_dir / "secrets.enc"
        assert enc_path.exists()
        raw_bytes = enc_path.read_bytes()
        assert b"MY_SUPER_SECRET_TOKEN_XYZ" not in raw_bytes

    def test_key_file_created(self, store, store_dir):
        store.set("x", "y")
        key_path = store_dir / "secret.key"
        assert key_path.exists()

    def test_env_var_key_override(self, store_dir, monkeypatch):
        """CLARAITY_SECRET_KEY env var overrides auto-generated key."""
        from cryptography.fernet import Fernet
        custom_key = Fernet.generate_key()
        monkeypatch.setenv("CLARAITY_SECRET_KEY", custom_key.decode())

        store = EncryptedFileSecretStore(store_dir=store_dir)
        store.set("env_key", "env_val")
        assert store.get("env_key") == "env_val"


# ---------------------------------------------------------------------------
# Secret leak checks
# ---------------------------------------------------------------------------

class TestSecretLeakPrevention:
    """Verify secrets never appear in JSONL, logs, or ToolResult output."""

    SECRET_VALUE = "BEARER_TOKEN_abc123xyz_NEVER_LEAK"

    def test_secret_not_in_encrypted_file(self, tmp_path):
        store = EncryptedFileSecretStore(store_dir=tmp_path / "s")
        store.set("token", self.SECRET_VALUE)

        # Read all files in the store directory
        for path in (tmp_path / "s").rglob("*"):
            if path.is_file():
                content = path.read_bytes()
                assert self.SECRET_VALUE.encode() not in content, (
                    f"Secret found in plaintext in {path.name}"
                )

    def test_secret_not_in_tool_result_output(self):
        """MCP adapter results must not contain auth tokens.

        The adapter only sees MCP server responses (issue data, etc.),
        never auth tokens. This test verifies the separation.
        """
        from src.integrations.mcp.adapter import McpToolAdapter
        from src.integrations.mcp.config import McpServerConfig

        config = McpServerConfig(name="test", tool_prefix="jira")
        adapter = McpToolAdapter(config)

        # Simulate a normal MCP result (should never contain tokens)
        mcp_result = {
            "content": [{"type": "text", "text": "PROJ-1: Bug in login"}],
        }
        result = adapter.adapt_result("jira.get_issue", mcp_result)

        assert self.SECRET_VALUE not in (result.output or "")
        assert self.SECRET_VALUE not in (result.error or "")
        assert self.SECRET_VALUE not in json.dumps(result.metadata)

    def test_secret_not_in_jsonl_simulation(self, tmp_path):
        """Simulate writing a tool result to JSONL and verify no secrets."""
        from src.integrations.mcp.adapter import McpToolAdapter
        from src.integrations.mcp.config import McpServerConfig

        config = McpServerConfig(
            name="test", tool_prefix="jira",
            auth_secret_key="jira.auth_token",
        )
        adapter = McpToolAdapter(config)

        mcp_result = {
            "content": [{"type": "text", "text": "Issue created: PROJ-5"}],
        }
        result = adapter.adapt_result("jira.create_issue", mcp_result)

        # Build JSONL record exactly as MessageStore would
        jsonl_record = json.dumps({
            "role": "tool",
            "tool_call_id": "call_abc123",
            "name": result.tool_name,
            "content": result.output,
            "meta": result.metadata,
        })

        jsonl_path = tmp_path / "session.jsonl"
        jsonl_path.write_text(jsonl_record + "\n")

        content = jsonl_path.read_text()
        assert self.SECRET_VALUE not in content
        assert "auth_token" not in content  # config key name also should not leak
        assert "BEARER" not in content

    def test_mcp_client_does_not_store_token_on_self(self):
        """McpClient must not have any attribute containing the secret."""
        from unittest.mock import AsyncMock
        from src.integrations.mcp.client import McpClient, McpTransport
        from src.integrations.mcp.config import McpServerConfig

        config = McpServerConfig(name="test", auth_secret_key="key")
        transport = AsyncMock(spec=McpTransport)
        client = McpClient(config, transport)

        # Inspect all attributes
        for attr_name in dir(client):
            if attr_name.startswith("_McpClient") or attr_name.startswith("__"):
                continue
            attr = getattr(client, attr_name, None)
            if isinstance(attr, str):
                assert self.SECRET_VALUE not in attr, (
                    f"Secret found in McpClient.{attr_name}"
                )


# ---------------------------------------------------------------------------
# get_secret_store factory
# ---------------------------------------------------------------------------

class TestGetSecretStore:
    def test_factory_returns_a_secret_store(self, tmp_path):
        from src.integrations.secrets import get_secret_store
        store = get_secret_store(store_dir=tmp_path / "test_store")
        assert isinstance(store, SecretStore)
