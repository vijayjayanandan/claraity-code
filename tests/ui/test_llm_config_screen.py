"""Tests for src.ui.llm_config_screen -- LLM Configuration Wizard Screen.

Uses Textual's pilot testing API for widget interaction tests.
"""

import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

@pytest.fixture(autouse=True)
def mock_api_env():
    """Prevent tests from reading real API keys from env vars."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("CLARAITY_API_KEY", None)
        os.environ.pop("OPENAI_API_KEY", None)
        yield

from src.llm.config_loader import LLMConfigData, SubAgentLLMOverride, save_llm_config
from src.ui.llm_config_screen import ConfigLLMScreen


# ---------------------------------------------------------------------------
# Unit tests (no Textual app needed)
# ---------------------------------------------------------------------------

class TestConfigLLMScreenInit:
    """Tests for screen initialization and config loading."""

    def test_loads_existing_config(self, tmp_path):
        """Screen should pre-populate from existing config.yaml."""
        config_path = str(tmp_path / "config.yaml")
        config = LLMConfigData(
            model="gpt-4o",
            base_url="http://localhost:8000/v1",
            backend_type="openai",
        )
        save_llm_config(config, config_path)

        screen = ConfigLLMScreen(config_path=config_path)
        assert screen._config.model == "gpt-4o"
        assert screen._config.base_url == "http://localhost:8000/v1"

    def test_defaults_when_no_config(self, tmp_path):
        """Screen should work with default config when file is missing."""
        config_path = str(tmp_path / "nonexistent.yaml")
        screen = ConfigLLMScreen(config_path=config_path)
        assert screen._config.model == ""
        assert screen._config.backend_type == "openai"


class TestListModels:
    """Tests for the static _list_models helper."""

    @patch("src.llm.openai_backend.OpenAIBackend")
    def test_list_models_openai(self, mock_backend_cls):
        """Should create an OpenAI backend and call list_models()."""
        mock_instance = MagicMock()
        mock_instance.list_models.return_value = ["gpt-4o", "gpt-3.5-turbo"]
        mock_backend_cls.return_value = mock_instance

        models = ConfigLLMScreen._list_models(
            "openai", "http://localhost:8000/v1", "test-api-key-123"
        )
        assert models == ["gpt-4o", "gpt-3.5-turbo"]
        mock_instance.list_models.assert_called_once()

    @patch("src.llm.ollama_backend.OllamaBackend")
    def test_list_models_ollama(self, mock_backend_cls):
        """Should create an Ollama backend and call list_models()."""
        mock_instance = MagicMock()
        mock_instance.list_models.return_value = ["llama3:8b", "codellama:7b"]
        mock_backend_cls.return_value = mock_instance

        models = ConfigLLMScreen._list_models(
            "ollama", "http://localhost:11434", ""
        )
        assert models == ["llama3:8b", "codellama:7b"]
        mock_instance.list_models.assert_called_once()


class TestSubagentNames:
    """Tests for subagent names passed to the wizard."""

    def test_screen_accepts_subagent_names(self, tmp_path):
        """Screen should accept subagent names via constructor."""
        config_path = str(tmp_path / "config.yaml")
        names = ["code-reviewer", "test-writer", "doc-writer"]
        screen = ConfigLLMScreen(config_path=config_path, subagent_names=names)
        assert screen._subagent_names == names

    def test_screen_defaults_to_builtin_fallback(self, tmp_path):
        """Screen should default to built-in subagent names when none given."""
        config_path = str(tmp_path / "config.yaml")
        screen = ConfigLLMScreen(config_path=config_path)
        # Verify all 7 built-in subagents are included
        assert "code-reviewer" in screen._subagent_names
        assert "test-writer" in screen._subagent_names
        assert "doc-writer" in screen._subagent_names
        assert "code-writer" in screen._subagent_names
        assert "explore" in screen._subagent_names
        assert "planner" in screen._subagent_names
        assert "general-purpose" in screen._subagent_names
        assert len(screen._subagent_names) == 7


class TestSaveConfig:
    """Tests for config save flow (unit-level, without running the full TUI)."""

    def test_save_creates_valid_yaml(self, tmp_path):
        """Verify that a config saved by the screen can be loaded back."""
        config_path = str(tmp_path / "config.yaml")
        config = LLMConfigData(
            backend_type="openai",
            base_url="http://localhost:8000/v1",
            api_key_env="MY_API_KEY",
            model="gpt-4o",
            temperature=0.3,
            max_tokens=8192,
            context_window=65536,
            subagents={
                "code-reviewer": SubAgentLLMOverride(model="gpt-4o"),
            },
        )
        assert save_llm_config(config, config_path) is True

        # Load back and verify
        from src.llm.config_loader import load_llm_config
        loaded = load_llm_config(config_path)
        assert loaded.model == "gpt-4o"
        assert loaded.base_url == "http://localhost:8000/v1"
        assert loaded.api_key_env == "MY_API_KEY"
        assert loaded.temperature == 0.3
        assert loaded.max_tokens == 8192
        assert loaded.context_window == 65536
        assert "code-reviewer" in loaded.subagents
        assert loaded.subagents["code-reviewer"].model == "gpt-4o"
