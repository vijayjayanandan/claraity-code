"""Tests for the model-aware thinking effort setting (llm.reasoning_effort).

Wire formats:
  - Claude adaptive (Anthropic Messages): thinking={type: adaptive} +
    extra_body.output_config.effort in low|medium|high|xhigh|max
    (verified live against claude-opus-5-5, 2026-10-01).
  - Claude adaptive via OpenAI-compatible proxy: same, inside extra_body.
  - OpenAI reasoning (chat completions): top-level reasoning_effort,
    clamped to low|medium|high.
  - OpenAI native (Responses API): reasoning.effort, clamped likewise.
"""

from unittest.mock import MagicMock, patch

import pytest

# Prime import chain (see conftest.py)
import src.core  # noqa: F401

from src.llm.anthropic_backend import AnthropicBackend
from src.llm.base import LLMBackendType, LLMConfig
from src.llm.config_loader import LLMConfigData, load_llm_config, save_llm_config
from src.llm.model_config import (
    effective_effort,
    normalize_effort,
    openai_effort,
    thinking_mode,
)
from src.llm.openai_backend import OpenAIBackend
from src.server.config_handler import save_config_from_request


class TestEffortHelpers:
    @pytest.mark.parametrize("value", ["low", "medium", "high", "xhigh", "max", " MAX "])
    def test_normalize_accepts_all_levels(self, value):
        assert normalize_effort(value) == value.strip().lower()

    @pytest.mark.parametrize("value", [None, "", "bogus", "minimal", 3])
    def test_normalize_rejects_invalid(self, value):
        assert normalize_effort(value) is None

    @pytest.mark.parametrize(
        "effort,expected",
        [("low", "low"), ("medium", "medium"), ("high", "high"),
         ("xhigh", "high"), ("max", "high"), (None, None), ("", None), ("bogus", None)],
    )
    def test_openai_effort_clamps(self, effort, expected):
        assert openai_effort(effort) == expected

    @pytest.mark.parametrize(
        "model,mode",
        [("claude-opus-5-5", "claude_effort"), ("vertex_ai/claude-sonnet-5", "claude_effort"),
         ("gpt-5.1", "openai_effort"), ("o3-mini", "openai_effort"),
         ("azure/gpt-6.1-sol", "openai_effort"),
         ("claude-sonnet-4-6", "budget"), ("gpt-4o", "budget"), ("kimi-k2.5", "budget"),
         ("", "budget")],
    )
    def test_thinking_mode(self, model, mode):
        assert thinking_mode(model) == mode

    @pytest.mark.parametrize(
        "model,saved,expected",
        [("claude-opus-5-5", None, "medium"), ("claude-opus-5-5", "low", "low"),
         ("claude-opus-4-8", None, "medium"), ("gpt-5.1", None, None),
         ("gpt-5.1", "high", "high"), ("claude-sonnet-4-6", None, None)],
    )
    def test_effective_effort_defaults_claude_adaptive_to_medium(self, model, saved, expected):
        assert effective_effort(model, saved) == expected


class TestAnthropicEffort:
    def test_effort_enables_adaptive_and_sets_output_config(self):
        params = {"model": "claude-opus-5-5", "temperature": 0.2}
        AnthropicBackend._apply_adaptive_thinking_rules(params, "max")
        assert params["thinking"] == {"type": "adaptive", "display": "summarized"}
        assert params["extra_body"] == {"output_config": {"effort": "max"}}
        assert "temperature" not in params

    def test_effort_overrides_legacy_budget(self):
        params = {
            "model": "claude-opus-5-5",
            "thinking": {"type": "enabled", "budget_tokens": 5000},
        }
        AnthropicBackend._apply_adaptive_thinking_rules(params, "low")
        assert params["thinking"]["type"] == "adaptive"
        assert params["extra_body"]["output_config"] == {"effort": "low"}

    def test_legacy_budget_without_effort_stays_adaptive_default(self):
        params = {
            "model": "claude-opus-5-5",
            "thinking": {"type": "enabled", "budget_tokens": 5000},
        }
        AnthropicBackend._apply_adaptive_thinking_rules(params, None)
        assert params["thinking"] == {"type": "adaptive", "display": "summarized"}
        assert "extra_body" not in params

    def test_no_effort_no_budget_means_no_thinking(self):
        params = {"model": "claude-opus-5-5"}
        AnthropicBackend._apply_adaptive_thinking_rules(params, None)
        assert "thinking" not in params
        assert "extra_body" not in params

    def test_invalid_effort_is_ignored(self):
        params = {"model": "claude-opus-5-5"}
        AnthropicBackend._apply_adaptive_thinking_rules(params, "bogus")
        assert "thinking" not in params
        assert "extra_body" not in params

    def test_older_claude_ignores_effort(self):
        params = {
            "model": "claude-sonnet-4-6",
            "temperature": 1,
            "thinking": {"type": "enabled", "budget_tokens": 8000},
        }
        AnthropicBackend._apply_adaptive_thinking_rules(params, "high")
        assert params["thinking"]["type"] == "enabled"
        assert "extra_body" not in params


class TestOpenAICompatEffort:
    def test_claude_via_proxy_gets_output_config(self):
        params = {"model": "claude-opus-5-5", "temperature": 0.2}
        OpenAIBackend._apply_model_param_rules(params, "high")
        assert params["extra_body"] == {
            "thinking": {"type": "adaptive", "display": "summarized"},
            "output_config": {"effort": "high"},
        }

    def test_gpt5_gets_reasoning_effort(self):
        params = {"model": "gpt-5.1", "max_tokens": 1000, "temperature": 0.2}
        OpenAIBackend._apply_model_param_rules(params, "medium")
        assert params["reasoning_effort"] == "medium"
        assert params["max_completion_tokens"] == 1000

    def test_gpt5_clamps_claude_only_level(self):
        params = {"model": "gpt-5.1"}
        OpenAIBackend._apply_model_param_rules(params, "max")
        assert params["reasoning_effort"] == "high"

    def test_gpt5_without_effort_sends_nothing(self):
        params = {"model": "gpt-5.1"}
        OpenAIBackend._apply_model_param_rules(params, None)
        assert "reasoning_effort" not in params

    def test_legacy_gpt_ignores_effort(self):
        params = {"model": "gpt-4o", "temperature": 0.7}
        OpenAIBackend._apply_model_param_rules(params, "high")
        assert "reasoning_effort" not in params
        assert params["temperature"] == 0.7


class TestOpenAINativeEffort:
    def _backend(self, effort):
        config = LLMConfig(
            backend_type=LLMBackendType.OPENAI_NATIVE,
            model_name="gpt-6.1",
            base_url="https://api.openai.com/v1",
            context_window=131072,
            temperature=0.2,
            max_tokens=4096,
            top_p=0.95,
            reasoning_effort=effort,
        )
        with patch("src.llm.openai_native_backend.OpenAI", return_value=MagicMock()), \
             patch("src.llm.openai_native_backend.AsyncOpenAI", return_value=MagicMock()):
            from src.llm.openai_native_backend import OpenAINativeBackend
            return OpenAINativeBackend(config, api_key="test-key")

    def test_clamps_max_to_high(self):
        params = self._backend("max")._build_responses_params([{"role": "user", "content": "hi"}])
        assert params["reasoning"]["effort"] == "high"

    def test_agent_kwarg_does_not_leak_to_responses_api(self):
        params = self._backend("low")._build_responses_params(
            [{"role": "user", "content": "hi"}], reasoning_effort="low", thinking_budget=5000
        )
        assert "reasoning_effort" not in params
        assert "thinking_budget" not in params
        assert params["reasoning"]["effort"] == "low"

    def test_history_thinking_keys_are_stripped_from_responses_input(self):
        """Regression: Claude history (thinking + signature) 400'd on the Responses API."""
        history = [
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": "hello",
                "thinking": "some reasoning",
                "thinking_signature": "sig",
            },
            {"role": "user", "content": "again"},
        ]
        items = self._backend("low")._prepare_responses_input(history)
        assert all(set(i) <= {"role", "content"} for i in items)
        assert [i["role"] for i in items] == ["user", "assistant", "user"]


class TestConfigPersistence:
    @pytest.mark.parametrize("level", ["xhigh", "max"])
    def test_yaml_round_trip_accepts_claude_levels(self, tmp_path, level):
        path = str(tmp_path / "config.yaml")
        assert save_llm_config(LLMConfigData(model="claude-opus-5-5", reasoning_effort=level), path)
        assert load_llm_config(path).reasoning_effort == level

    def test_yaml_invalid_effort_ignored(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text("llm:\n  model: x\n  reasoning_effort: bogus\n", encoding="utf-8")
        assert load_llm_config(str(path)).reasoning_effort is None

    @patch("src.llm.config_loader.save_llm_config", return_value=True)
    def test_save_request_accepts_max(self, mock_save):
        save_config_from_request(
            {"config": {"model": "claude-opus-5-5", "reasoning_effort": "max"}}, "/fake.yaml"
        )
        assert mock_save.call_args[0][0].reasoning_effort == "max"

    @patch("src.llm.config_loader.save_llm_config", return_value=True)
    def test_save_request_rejects_invalid(self, mock_save):
        save_config_from_request(
            {"config": {"model": "claude-opus-5-5", "reasoning_effort": "bogus"}}, "/fake.yaml"
        )
        assert mock_save.call_args[0][0].reasoning_effort is None
