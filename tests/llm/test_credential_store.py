"""Tests for src.llm.credential_store -- Secure API key storage."""

import os
import pytest
from unittest.mock import patch, MagicMock

from src.llm.credential_store import (
    save_api_key,
    load_api_key,
    delete_api_key,
    has_api_key,
    SERVICE_NAME,
    USERNAME,
)


class TestSaveApiKey:
    """Tests for save_api_key()."""

    @patch("src.llm.credential_store._get_keyring")
    def test_save_success(self, mock_get_kr):
        mock_kr = MagicMock()
        mock_get_kr.return_value = mock_kr

        assert save_api_key("sk-test-123") is True
        mock_kr.set_password.assert_called_once_with(SERVICE_NAME, USERNAME, "sk-test-123")

    @patch("src.llm.credential_store._get_keyring")
    def test_save_empty_key_returns_false(self, mock_get_kr):
        assert save_api_key("") is False
        mock_get_kr.assert_not_called()

    @patch("src.llm.credential_store._get_keyring", return_value=None)
    def test_save_no_keyring_returns_false(self, mock_get_kr):
        assert save_api_key("sk-test-123") is False

    @patch("src.llm.credential_store._get_keyring")
    def test_save_keyring_error_returns_false(self, mock_get_kr):
        mock_kr = MagicMock()
        mock_kr.set_password.side_effect = Exception("keyring error")
        mock_get_kr.return_value = mock_kr

        assert save_api_key("sk-test-123") is False


class TestLoadApiKey:
    """Tests for load_api_key()."""

    @patch("src.llm.credential_store._get_keyring")
    def test_load_from_keyring(self, mock_get_kr):
        mock_kr = MagicMock()
        mock_kr.get_password.return_value = "sk-from-keyring"
        mock_get_kr.return_value = mock_kr

        assert load_api_key() == "sk-from-keyring"

    @patch("src.llm.credential_store._get_keyring")
    def test_load_falls_back_to_env_var(self, mock_get_kr):
        mock_kr = MagicMock()
        mock_kr.get_password.return_value = None  # Not in keyring
        mock_get_kr.return_value = mock_kr

        with patch.dict(os.environ, {"MY_API_KEY": "sk-from-env"}):
            assert load_api_key(api_key_env="MY_API_KEY") == "sk-from-env"

    @patch("src.llm.credential_store._get_keyring", return_value=None)
    def test_load_no_keyring_uses_env_var(self, mock_get_kr):
        with patch.dict(os.environ, {"MY_API_KEY": "sk-env-only"}):
            assert load_api_key(api_key_env="MY_API_KEY") == "sk-env-only"

    @patch("src.llm.credential_store._get_keyring", return_value=None)
    def test_load_nothing_returns_empty(self, mock_get_kr):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NONEXISTENT_KEY", None)
            assert load_api_key(api_key_env="NONEXISTENT_KEY") == ""

    @patch("src.llm.credential_store._get_keyring")
    def test_load_keyring_error_falls_back(self, mock_get_kr):
        mock_kr = MagicMock()
        mock_kr.get_password.side_effect = Exception("keyring error")
        mock_get_kr.return_value = mock_kr

        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-fallback"}):
            assert load_api_key() == "sk-fallback"


class TestDeleteApiKey:
    """Tests for delete_api_key()."""

    @patch("src.llm.credential_store._get_keyring")
    def test_delete_success(self, mock_get_kr):
        mock_kr = MagicMock()
        mock_get_kr.return_value = mock_kr

        assert delete_api_key() is True
        mock_kr.delete_password.assert_called_once_with(SERVICE_NAME, USERNAME)

    @patch("src.llm.credential_store._get_keyring", return_value=None)
    def test_delete_no_keyring(self, mock_get_kr):
        assert delete_api_key() is False


class TestHasApiKey:
    """Tests for has_api_key()."""

    @patch("src.llm.credential_store.load_api_key", return_value="sk-exists")
    def test_has_key_true(self, mock_load):
        assert has_api_key() is True

    @patch("src.llm.credential_store.load_api_key", return_value="")
    def test_has_key_false(self, mock_load):
        assert has_api_key() is False
