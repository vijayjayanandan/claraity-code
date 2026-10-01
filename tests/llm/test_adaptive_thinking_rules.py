"""Tests for Claude 5-family / Opus 4.7+ request param sanitization.

These models reject temperature/top_p and thinking budget_tokens with
HTTP 400. Both backends must strip sampling params and rewrite thinking
config to adaptive before dispatch.
"""

from src.llm.anthropic_backend import AnthropicBackend
from src.llm.model_config import (
    requires_responses_api,
    uses_adaptive_thinking,
    uses_max_completion_tokens,
)
from src.llm.openai_backend import OpenAIBackend


class TestUsesAdaptiveThinking:
    def test_claude5_family_models(self):
        assert uses_adaptive_thinking("claude-sonnet-5")
        assert uses_adaptive_thinking("claude-fable-5")
        assert uses_adaptive_thinking("claude-mythos-5")
        assert uses_adaptive_thinking("claude-opus-5")
        assert uses_adaptive_thinking("claude-opus-5-5")
        assert uses_adaptive_thinking("claude-opus-4-7")
        assert uses_adaptive_thinking("claude-opus-4-8")

    def test_provider_prefixed_ids(self):
        assert uses_adaptive_thinking("vertex_ai/claude-sonnet-5")
        assert uses_adaptive_thinking("anthropic.claude-opus-4-8")

    def test_case_insensitive(self):
        assert uses_adaptive_thinking("Claude-Sonnet-5")

    def test_older_models_not_matched(self):
        assert not uses_adaptive_thinking("claude-sonnet-4-5")
        assert not uses_adaptive_thinking("claude-sonnet-4-6")
        assert not uses_adaptive_thinking("claude-opus-4-6")
        assert not uses_adaptive_thinking("claude-haiku-4-5")

    def test_non_claude_models_not_matched(self):
        assert not uses_adaptive_thinking("gpt-4o")
        assert not uses_adaptive_thinking("kimi-k2.5")
        assert not uses_adaptive_thinking("")
        assert not uses_adaptive_thinking(None)


class TestOpenAIBackendRules:
    def test_strips_temperature_and_top_p(self):
        params = {"model": "claude-sonnet-5", "temperature": 0.2, "top_p": 0.95}
        OpenAIBackend._apply_model_param_rules(params)
        assert "temperature" not in params
        assert "top_p" not in params

    def test_rewrites_thinking_in_extra_body(self):
        params = {
            "model": "claude-sonnet-5",
            "temperature": 1,
            "extra_body": {"thinking": {"type": "enabled", "budget_tokens": 8000}},
        }
        OpenAIBackend._apply_model_param_rules(params)
        assert params["extra_body"]["thinking"] == {
            "type": "adaptive",
            "display": "summarized",
        }
        assert "temperature" not in params

    def test_noop_for_older_claude(self):
        params = {
            "model": "claude-sonnet-4-5",
            "temperature": 0.2,
            "extra_body": {"thinking": {"type": "enabled", "budget_tokens": 8000}},
        }
        OpenAIBackend._apply_model_param_rules(params)
        assert params["temperature"] == 0.2
        assert params["extra_body"]["thinking"]["type"] == "enabled"

    def test_noop_for_non_claude(self):
        params = {"model": "gpt-4o", "temperature": 0.7, "top_p": 0.9}
        OpenAIBackend._apply_model_param_rules(params)
        assert params["temperature"] == 0.7
        assert params["top_p"] == 0.9

    def test_no_extra_body_is_safe(self):
        params = {"model": "claude-fable-5", "temperature": 0.2}
        OpenAIBackend._apply_model_param_rules(params)
        assert "temperature" not in params
        assert "extra_body" not in params


class TestUsesMaxCompletionTokens:
    def test_gpt5_and_newer(self):
        assert uses_max_completion_tokens("gpt-5.4-2026-03-05")
        assert uses_max_completion_tokens("gpt-5.5")
        assert uses_max_completion_tokens("gpt-6.1-sol")
        assert uses_max_completion_tokens("gpt-7")

    def test_o_series(self):
        assert uses_max_completion_tokens("o1")
        assert uses_max_completion_tokens("o1-pro")
        assert uses_max_completion_tokens("o3-mini")

    def test_provider_prefixed_ids(self):
        assert uses_max_completion_tokens("azure/gpt-6.1-sol")
        assert uses_max_completion_tokens("openai/o3-mini")

    def test_legacy_models_not_matched(self):
        assert not uses_max_completion_tokens("gpt-4o")
        assert not uses_max_completion_tokens("gpt-4.1")
        assert not uses_max_completion_tokens("gpt-3.5-turbo")
        assert not uses_max_completion_tokens("gpt-oss-120b")

    def test_no_false_positives(self):
        assert not uses_max_completion_tokens("solo1")
        assert not uses_max_completion_tokens("claude-opus-5-5")
        assert not uses_max_completion_tokens("kimi-k2.5")
        assert not uses_max_completion_tokens("")
        assert not uses_max_completion_tokens(None)


class TestRequiresResponsesApi:
    def test_gpt6_and_newer(self):
        assert requires_responses_api("gpt-6.1-sol")
        assert requires_responses_api("gpt-6")
        assert requires_responses_api("gpt-7-preview")
        assert requires_responses_api("azure/gpt-6.1-sol")

    def test_gpt5_and_older_not_matched(self):
        """gpt-5.x works with tools on chat completions -- don't route it."""
        assert not requires_responses_api("gpt-5.4-2026-03-05")
        assert not requires_responses_api("gpt-5.5")
        assert not requires_responses_api("gpt-4o")
        assert not requires_responses_api("o3-mini")
        assert not requires_responses_api("claude-opus-5-5")
        assert not requires_responses_api("")
        assert not requires_responses_api(None)


class TestOpenAIBackendModernGptRules:
    def test_renames_max_tokens_and_strips_sampling(self):
        params = {
            "model": "gpt-6.1-sol",
            "temperature": 0.2,
            "top_p": 0.95,
            "max_tokens": 16384,
        }
        OpenAIBackend._apply_model_param_rules(params)
        assert "max_tokens" not in params
        assert params["max_completion_tokens"] == 16384
        assert "temperature" not in params
        assert "top_p" not in params

    def test_no_max_tokens_key_is_safe(self):
        params = {"model": "o3-mini", "temperature": 1}
        OpenAIBackend._apply_model_param_rules(params)
        assert "max_completion_tokens" not in params
        assert "temperature" not in params

    def test_noop_for_legacy_gpt(self):
        params = {"model": "gpt-4o", "temperature": 0.7, "max_tokens": 4096}
        OpenAIBackend._apply_model_param_rules(params)
        assert params["max_tokens"] == 4096
        assert params["temperature"] == 0.7


class TestAnthropicBackendRules:
    def test_strips_temperature_and_rewrites_thinking(self):
        params = {
            "model": "claude-opus-4-8",
            "temperature": 1,
            "thinking": {"type": "enabled", "budget_tokens": 16000},
        }
        AnthropicBackend._apply_adaptive_thinking_rules(params)
        assert "temperature" not in params
        assert params["thinking"] == {"type": "adaptive", "display": "summarized"}

    def test_no_thinking_key_is_safe(self):
        params = {"model": "claude-sonnet-5", "temperature": 0.2}
        AnthropicBackend._apply_adaptive_thinking_rules(params)
        assert "temperature" not in params
        assert "thinking" not in params

    def test_noop_for_older_claude(self):
        params = {
            "model": "claude-opus-4-6",
            "temperature": 0.2,
            "thinking": {"type": "enabled", "budget_tokens": 8000},
        }
        AnthropicBackend._apply_adaptive_thinking_rules(params)
        assert params["temperature"] == 0.2
        assert params["thinking"]["type"] == "enabled"
