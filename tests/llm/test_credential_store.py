"""Tests for src.llm.credential_store -- API key loading from env vars."""

import os
import pytest
from unittest.mock import patch

from src.llm.credential_store import load_api_key, has_api_key


class TestLoadApiKey:
    """Tests for load_api_key()."""

    def test_claraity_env_highest_priority(self):
        with patch.dict(os.environ, {
            "CLARAITY_API_KEY": "sk-from-extension",
            "OPENAI_API_KEY": "sk-from-openai",
        }):
            assert load_api_key() == "sk-from-extension"

    def test_falls_back_to_default_env(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-from-openai"}, clear=False):
            os.environ.pop("CLARAITY_API_KEY", None)
            assert load_api_key() == "sk-from-openai"

    def test_custom_env_var_name(self):
        with patch.dict(os.environ, {"MY_API_KEY": "sk-custom"}, clear=False):
            os.environ.pop("CLARAITY_API_KEY", None)
            assert load_api_key(api_key_env="MY_API_KEY") == "sk-custom"

    def test_nothing_returns_empty(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CLARAITY_API_KEY", None)
            os.environ.pop("NONEXISTENT_KEY", None)
            assert load_api_key(api_key_env="NONEXISTENT_KEY") == ""

    def test_empty_claraity_env_falls_through(self):
        with patch.dict(os.environ, {
            "CLARAITY_API_KEY": "",
            "OPENAI_API_KEY": "sk-fallback",
        }):
            assert load_api_key() == "sk-fallback"


class TestHasApiKey:
    """Tests for has_api_key()."""

    def test_has_key_true(self):
        with patch.dict(os.environ, {"CLARAITY_API_KEY": "sk-exists"}):
            assert has_api_key() is True

    def test_has_key_false(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CLARAITY_API_KEY", None)
            os.environ.pop("OPENAI_API_KEY", None)
            assert has_api_key(api_key_env="NONEXISTENT") is False
