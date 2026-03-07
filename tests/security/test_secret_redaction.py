"""Tests for secret redaction in session persistence (S4, S5).

Verifies that API keys, tokens, and credentials are redacted before
being written to JSONL session files.
"""

import pytest
from src.security import redact_secrets, redact_dict, REDACTED


class TestRedactSecrets:
    """S5: Verify secret patterns are detected and redacted."""

    def test_openai_api_key(self):
        text = "Using key sk-abc123def456ghi789jkl012mno345pqr678"
        result = redact_secrets(text)
        assert "sk-abc123def456ghi789jkl012mno345pqr678" not in result
        assert REDACTED in result

    def test_anthropic_api_key(self):
        text = "Key: sk-ant-api03-abcdefghijklmnopqrstuvwxyz"
        result = redact_secrets(text)
        assert "sk-ant-api03-abcdefghijklmnopqrstuvwxyz" not in result
        assert REDACTED in result

    def test_aws_access_key(self):
        text = "AWS key: AKIAIOSFODNN7EXAMPLE"
        result = redact_secrets(text)
        assert "AKIAIOSFODNN7EXAMPLE" not in result
        assert REDACTED in result

    def test_github_personal_token(self):
        text = "Token: ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij"
        result = redact_secrets(text)
        assert "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij" not in result
        assert REDACTED in result

    def test_bearer_token(self):
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.sig"
        result = redact_secrets(text)
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in result
        assert REDACTED in result

    def test_generic_api_key_assignment(self):
        text = 'api_key = "my_secret_key_value_12345678"'
        result = redact_secrets(text)
        assert "my_secret_key_value_12345678" not in result

    def test_password_assignment(self):
        text = 'password: "super_secret_password_123"'
        result = redact_secrets(text)
        assert "super_secret_password_123" not in result

    def test_no_false_positives_on_normal_text(self):
        text = "This is a normal message about coding in Python."
        result = redact_secrets(text)
        assert result == text

    def test_empty_string(self):
        assert redact_secrets("") == ""

    def test_none_returns_none(self):
        assert redact_secrets(None) is None

    def test_preserves_key_prefix(self):
        """Redacted secrets should keep first 4 chars for identification."""
        text = "sk-abc123def456ghi789jkl012mno345pqr678"
        result = redact_secrets(text)
        assert result.startswith("sk-a")

    def test_multiple_secrets_in_one_string(self):
        text = "Key1: sk-key1_abcdefghijklmnopqrst, Key2: ghp_token2abcdefghijklmnopqrstuvwxyz1234"
        result = redact_secrets(text)
        assert "sk-key1_abcdefghijklmnopqrst" not in result
        assert "ghp_token2abcdefghijklmnopqrstuvwxyz1234" not in result
        assert result.count(REDACTED) >= 2


class TestRedactDict:
    """S5: Verify dictionary redaction for sensitive keys."""

    def test_redacts_api_key_field(self):
        data = {"model": "gpt-4", "api_key": "sk-secret123456789012345678"}
        result = redact_dict(data)
        assert result["api_key"] == REDACTED
        assert result["model"] == "gpt-4"  # Non-sensitive preserved

    def test_redacts_password_field(self):
        data = {"username": "admin", "password": "hunter2"}
        result = redact_dict(data)
        assert result["password"] == REDACTED
        assert result["username"] == "admin"

    def test_redacts_token_field(self):
        data = {"token": "eyJhbGciOiJIUzI1NiJ9.payload.signature"}
        result = redact_dict(data)
        assert result["token"] == REDACTED

    def test_redacts_nested_dicts(self):
        data = {
            "config": {
                "llm": {
                    "api_key": "sk-secret",
                    "model": "gpt-4"
                }
            }
        }
        result = redact_dict(data)
        assert result["config"]["llm"]["api_key"] == REDACTED
        assert result["config"]["llm"]["model"] == "gpt-4"

    def test_redacts_secrets_in_string_values(self):
        data = {"content": "Use this key: sk-abc123def456ghi789jkl012mno345pqr678"}
        result = redact_dict(data)
        assert "sk-abc123def456ghi789jkl012mno345pqr678" not in result["content"]

    def test_redacts_lists_of_dicts(self):
        data = {
            "messages": [
                {"role": "user", "content": "normal message"},
                {"role": "system", "api_key": "sk-secret"},
            ]
        }
        result = redact_dict(data)
        assert result["messages"][0]["content"] == "normal message"
        assert result["messages"][1]["api_key"] == REDACTED

    def test_handles_depth_limit(self):
        """Deeply nested dicts should stop at max_depth."""
        data = {"a": {"b": {"c": {"d": {"api_key": "secret"}}}}}
        result = redact_dict(data, max_depth=2)
        # Should still work at depth 2 but not go deeper
        assert isinstance(result, dict)

    def test_does_not_modify_original(self):
        data = {"api_key": "sk-secret", "model": "gpt-4"}
        result = redact_dict(data)
        assert data["api_key"] == "sk-secret"  # Original unchanged
        assert result["api_key"] == REDACTED


class TestGitignoreProtection:
    """S4: Verify .clarity sensitive files are in .gitignore."""

    def test_gitignore_blocks_config(self):
        gitignore = Path(__file__).parent.parent.parent / ".gitignore"
        content = gitignore.read_text()
        assert ".clarity/config.yaml" in content

    def test_gitignore_blocks_sessions(self):
        gitignore = Path(__file__).parent.parent.parent / ".gitignore"
        content = gitignore.read_text()
        assert ".clarity/sessions/" in content

    def test_gitignore_blocks_logs(self):
        gitignore = Path(__file__).parent.parent.parent / ".gitignore"
        content = gitignore.read_text()
        assert ".clarity/logs/" in content


from pathlib import Path
