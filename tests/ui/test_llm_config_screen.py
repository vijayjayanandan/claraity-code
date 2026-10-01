"""Tests for src.ui.llm_config_screen -- LLM Configuration Wizard Screen.

Uses Textual's pilot testing API for widget interaction tests.
"""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


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
        assert screen._config.backend_type == "openai_compatible"


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


# ---------------------------------------------------------------------------
# Thinking control (model-aware) -- Textual pilot tests
# ---------------------------------------------------------------------------

from textual.app import App
from textual.containers import Vertical
from textual.widgets import Input, Select

from src.llm.config_loader import load_llm_config


class _Host(App):
    """Minimal app that pushes the config screen and records the result."""

    def __init__(self, config_path: str):
        super().__init__()
        self._config_path = config_path
        self.result = "unset"

    def on_mount(self) -> None:
        def _done(result):
            self.result = result

        self.push_screen(ConfigLLMScreen(config_path=self._config_path), _done)


def _write(tmp_path, **kwargs) -> str:
    path = str(tmp_path / "config.yaml")
    save_llm_config(LLMConfigData(base_url="http://localhost:8000/v1", **kwargs), path)
    return path


def _option_values(select: Select) -> list:
    return [value for _label, value in select._options if value is not Select.BLANK]


class TestThinkingControl:
    @pytest.mark.asyncio
    async def test_claude_adaptive_shows_effort_dropdown(self, tmp_path):
        app = _Host(_write(tmp_path, model="claude-opus-5-5", reasoning_effort="xhigh"))
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            assert screen.query_one("#effort-group", Vertical).display is True
            assert screen.query_one("#budget-group", Vertical).display is False
            select = screen.query_one("#thinking-effort", Select)
            assert _option_values(select) == ["low", "medium", "high", "xhigh", "max"]
            assert select.value == "xhigh"

    @pytest.mark.asyncio
    async def test_legacy_model_shows_budget(self, tmp_path):
        app = _Host(_write(tmp_path, model="claude-sonnet-4-6", thinking_budget=8000))
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            assert screen.query_one("#effort-group", Vertical).display is False
            assert screen.query_one("#budget-group", Vertical).display is True

    @pytest.mark.asyncio
    async def test_switching_to_openai_model_clamps_and_swaps_options(self, tmp_path):
        app = _Host(_write(tmp_path, model="claude-opus-5-5", reasoning_effort="max"))
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            screen.query_one("#model-input", Input).value = "gpt-5.1"
            await pilot.pause()
            select = screen.query_one("#thinking-effort", Select)
            assert _option_values(select) == ["off", "low", "medium", "high"]
            assert select.value == "high"

    @pytest.mark.asyncio
    async def test_old_budget_on_adaptive_model_shows_medium_and_saves_medium(self, tmp_path):
        path = _write(tmp_path, model="claude-opus-5-5", thinking_budget=5000)
        app = _Host(path)
        async with app.run_test() as pilot:
            await pilot.pause()
            select = app.screen.query_one("#thinking-effort", Select)
            assert select.value == "medium"
            app.screen._save_config()
            await pilot.pause()
        loaded = load_llm_config(path)
        assert loaded.reasoning_effort == "medium"
        assert loaded.thinking_budget is None

    @pytest.mark.asyncio
    async def test_save_chosen_effort(self, tmp_path):
        path = _write(tmp_path, model="claude-opus-5-5")
        app = _Host(path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#thinking-effort", Select).value = "max"
            await pilot.pause()
            app.screen._save_config()
            await pilot.pause()
        assert load_llm_config(path).reasoning_effort == "max"

    @pytest.mark.asyncio
    async def test_openai_default_saves_no_effort(self, tmp_path):
        path = _write(tmp_path, model="gpt-5.1")
        app = _Host(path)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.screen.query_one("#thinking-effort", Select).value == "off"
            app.screen._save_config()
            await pilot.pause()
        assert load_llm_config(path).reasoning_effort is None
