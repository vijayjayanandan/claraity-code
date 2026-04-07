"""
Unit tests for CodingAgent.reconfigure_llm().

Tests hot-swap of LLM backend at runtime without losing session state.
No API calls needed - all dependencies are mocked.
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from src.llm.base import LLMBackendType, LLMConfig
from src.llm.config_loader import LLMConfigData


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_agent():
    """Build a minimal mock CodingAgent with the fields reconfigure_llm reads."""
    from src.core.agent import CodingAgent

    # We patch __init__ so we don't need real backends / memory / tools
    with patch.object(CodingAgent, "__init__", lambda self: None):
        agent = CodingAgent()

    # Populate the fields that reconfigure_llm() touches
    agent.model_name = "gpt-4"
    agent.backend_name = "openai"
    agent.context_window = 131072

    # Mock LLM backend with sync + async clients
    agent.llm = MagicMock()
    agent.llm.config = LLMConfig(
        backend_type=LLMBackendType.OPENAI,
        model_name="gpt-4",
        base_url="http://localhost:8000/v1",
        context_window=131072,
        temperature=0.2,
        max_tokens=16384,
        top_p=0.95,
    )

    # Mock memory manager
    agent.memory = MagicMock()
    agent.memory.total_context_tokens = 131072
    agent.memory.working_memory = MagicMock()
    agent.memory.working_memory.max_tokens = int(131072 * 0.4)

    # Mock context builder
    agent.context_builder = MagicMock()
    agent.context_builder.max_context_tokens = 131072

    # Mock subagent manager
    agent.subagent_manager = MagicMock()

    return agent


def _make_config(
    model="gpt-4o",
    backend_type="openai",
    base_url="http://localhost:8000/v1",
    context_window=131072,
    temperature=0.2,
    max_tokens=16384,
    top_p=0.95,
    thinking_budget=None,
    api_key="",
    api_key_env="OPENAI_API_KEY",
    subagents=None,
):
    """Helper to build LLMConfigData with sensible defaults."""
    return LLMConfigData(
        model=model,
        backend_type=backend_type,
        base_url=base_url,
        context_window=context_window,
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=top_p,
        thinking_budget=thinking_budget,
        api_key=api_key,
        api_key_env=api_key_env,
        subagents=subagents or {},
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestReconfigureLlm:
    """Tests for CodingAgent.reconfigure_llm()."""

    @patch("src.core.agent.OpenAIBackend")
    def test_model_change_same_backend(self, MockOpenAI, mock_agent):
        """Model change within same backend: updates model_name, swaps backend."""
        new_backend = MagicMock()
        MockOpenAI.return_value = new_backend

        config = _make_config(model="gpt-4o")
        summary = mock_agent.reconfigure_llm(config, api_key="sk-test")

        assert mock_agent.model_name == "gpt-4o"
        assert mock_agent.llm is new_backend
        assert "gpt-4 -> gpt-4o" in summary
        MockOpenAI.assert_called_once()

    @patch("src.llm.anthropic_backend.AnthropicBackend")
    def test_backend_swap(self, MockAnthropic, mock_agent):
        """Switching from openai to anthropic creates new backend type."""
        old_llm = mock_agent.llm
        new_backend = MagicMock()
        MockAnthropic.return_value = new_backend

        config = _make_config(
            model="claude-sonnet-4-20250514",
            backend_type="anthropic",
            api_key_env="ANTHROPIC_API_KEY",
        )
        summary = mock_agent.reconfigure_llm(config, api_key="sk-ant-test")

        assert mock_agent.llm is new_backend
        assert mock_agent.backend_name == "anthropic"
        assert "Backend: openai -> anthropic" in summary
        # Old clients should have been closed
        old_llm.client.close.assert_called_once()

    @patch("src.core.agent.OpenAIBackend")
    def test_generation_params_only(self, MockOpenAI, mock_agent):
        """Same model + backend but different temperature: summary says params updated."""
        MockOpenAI.return_value = MagicMock()

        config = _make_config(model="gpt-4", temperature=0.8)
        summary = mock_agent.reconfigure_llm(config)

        assert summary == "Generation parameters updated"

    @patch("src.core.agent.OpenAIBackend")
    def test_context_window_change_retunes_memory(self, MockOpenAI, mock_agent):
        """Context window change updates memory allocations."""
        MockOpenAI.return_value = MagicMock()

        config = _make_config(context_window=65536)
        summary = mock_agent.reconfigure_llm(config)

        assert mock_agent.context_window == 65536
        assert mock_agent.memory.total_context_tokens == 65536
        assert mock_agent.memory.working_memory.max_tokens == int(65536 * 0.4)
        assert mock_agent.context_builder.max_context_tokens == 65536
        assert "Context: 131072 -> 65536" in summary

    @patch("src.core.agent.OpenAIBackend")
    def test_context_window_unchanged_skips_retune(self, MockOpenAI, mock_agent):
        """Same context window: memory allocations untouched."""
        MockOpenAI.return_value = MagicMock()
        original_total = mock_agent.memory.total_context_tokens

        config = _make_config(model="gpt-4o", context_window=131072)
        mock_agent.reconfigure_llm(config)

        # total_context_tokens should not have been reassigned
        # (it's a MagicMock, so we check it wasn't set to a new value)
        assert mock_agent.memory.total_context_tokens == original_total

    @patch("src.core.agent.OpenAIBackend", side_effect=ValueError("bad key"))
    def test_construction_failure_preserves_old_backend(self, MockOpenAI, mock_agent):
        """If new backend fails to construct, old backend stays intact."""
        old_llm = mock_agent.llm
        old_model = mock_agent.model_name

        config = _make_config(model="gpt-4o")

        with pytest.raises(ValueError, match="bad key"):
            mock_agent.reconfigure_llm(config, api_key="bad")

        assert mock_agent.llm is old_llm
        assert mock_agent.model_name == old_model

    @patch("src.core.agent.OpenAIBackend")
    def test_subagent_overrides_applied(self, MockOpenAI, mock_agent):
        """Subagent overrides in config are forwarded to subagent_manager."""
        from src.llm.config_loader import SubAgentLLMOverride

        MockOpenAI.return_value = MagicMock()

        overrides = {"code-reviewer": SubAgentLLMOverride(model="gpt-4o-mini")}
        config = _make_config(model="gpt-4o", subagents=overrides)
        mock_agent.reconfigure_llm(config)

        mock_agent.subagent_manager.config_loader.apply_llm_overrides.assert_called_once_with(
            config
        )

    @patch("src.core.agent.OpenAIBackend")
    def test_old_clients_closed(self, MockOpenAI, mock_agent):
        """Both sync and async clients on old backend are closed."""
        old_llm = mock_agent.llm
        MockOpenAI.return_value = MagicMock()

        config = _make_config(model="gpt-4o")
        mock_agent.reconfigure_llm(config)

        old_llm.client.close.assert_called_once()
        old_llm.async_client.close.assert_called_once()
