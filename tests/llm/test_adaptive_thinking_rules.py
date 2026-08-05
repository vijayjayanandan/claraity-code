"""Tests for Claude 5-family / Opus 4.7+ request param sanitization.

These models reject temperature/top_p and thinking budget_tokens with
HTTP 400. Both backends must strip sampling params and rewrite thinking
config to adaptive before dispatch.
"""

from src.llm.anthropic_backend import AnthropicBackend
from src.llm.model_config import uses_adaptive_thinking
from src.llm.openai_backend import OpenAIBackend


class TestUsesAdaptiveThinking:
    def test_claude5_family_models(self):
        assert uses_adaptive_thinking("claude-sonnet-5")
        assert uses_adaptive_thinking("claude-fable-5")
        assert uses_adaptive_thinking("claude-mythos-5")
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
        OpenAIBackend._apply_adaptive_thinking_rules(params)
        assert "temperature" not in params
        assert "top_p" not in params

    def test_rewrites_thinking_in_extra_body(self):
        params = {
            "model": "claude-sonnet-5",
            "temperature": 1,
            "extra_body": {"thinking": {"type": "enabled", "budget_tokens": 8000}},
        }
        OpenAIBackend._apply_adaptive_thinking_rules(params)
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
        OpenAIBackend._apply_adaptive_thinking_rules(params)
        assert params["temperature"] == 0.2
        assert params["extra_body"]["thinking"]["type"] == "enabled"

    def test_noop_for_non_claude(self):
        params = {"model": "gpt-4o", "temperature": 0.7, "top_p": 0.9}
        OpenAIBackend._apply_adaptive_thinking_rules(params)
        assert params["temperature"] == 0.7
        assert params["top_p"] == 0.9

    def test_no_extra_body_is_safe(self):
        params = {"model": "claude-fable-5", "temperature": 0.2}
        OpenAIBackend._apply_adaptive_thinking_rules(params)
        assert "temperature" not in params
        assert "extra_body" not in params


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
