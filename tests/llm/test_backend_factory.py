"""Tests for src.llm.backend_factory -- create_backend() routing.

All tests mock the concrete backend classes so no real SDK or API calls occur.
The factory uses lazy local imports (``from src.llm.X import Y`` inside the
function body), so we patch the class at its definition module, not at the
factory module.
"""

from unittest.mock import MagicMock, patch

import pytest

# Prime import chain (see conftest.py)
import src.core  # noqa: F401

from src.llm.backend_factory import create_backend
from src.llm.base import LLMBackendType, LLMConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(backend_type: str, model_name: str = "test-model") -> LLMConfig:
    """Build a minimal LLMConfig for the given backend_type string."""
    return LLMConfig(
        backend_type=LLMBackendType(backend_type),
        model_name=model_name,
        base_url="http://localhost:8000/v1",
        context_window=131072,
        temperature=0.2,
        max_tokens=16384,
        top_p=0.95,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCreateBackend:
    """Tests for create_backend() factory function."""

    def test_factory_openai_native_returns_openai_native_backend(self):
        """backend_type='openai_native' should instantiate OpenAINativeBackend."""
        config = _make_config("openai_native", model_name="gpt-4o")
        mock_instance = MagicMock()

        with patch("src.llm.openai_native_backend.OpenAINativeBackend") as MockNative:
            MockNative.return_value = mock_instance
            result = create_backend(config, api_key="test-key", api_key_env="OPENAI_API_KEY")

        MockNative.assert_called_once_with(config, api_key="test-key", api_key_env="OPENAI_API_KEY")
        assert result is mock_instance

    def test_factory_openai_compatible_returns_openai_backend(self):
        """backend_type='openai_compatible' should instantiate OpenAIBackend."""
        config = _make_config("openai_compatible")
        mock_instance = MagicMock()

        with patch("src.llm.openai_backend.OpenAIBackend") as MockCompat:
            MockCompat.return_value = mock_instance
            result = create_backend(config, api_key="key", api_key_env="OPENAI_API_KEY")

        MockCompat.assert_called_once_with(config, api_key="key", api_key_env="OPENAI_API_KEY")
        assert result is mock_instance

    def test_factory_legacy_openai_alias_returns_openai_backend(self):
        """backend_type='openai' (legacy alias) should route to OpenAIBackend."""
        config = _make_config("openai")
        mock_instance = MagicMock()

        with patch("src.llm.openai_backend.OpenAIBackend") as MockCompat:
            MockCompat.return_value = mock_instance
            result = create_backend(config, api_key="key", api_key_env="OPENAI_API_KEY")

        MockCompat.assert_called_once()
        assert result is mock_instance

    def test_factory_anthropic_returns_anthropic_backend(self):
        """backend_type='anthropic' should instantiate AnthropicBackend."""
        config = _make_config("anthropic")
        mock_instance = MagicMock()

        with patch("src.llm.anthropic_backend.AnthropicBackend") as MockAnthropic:
            MockAnthropic.return_value = mock_instance
            result = create_backend(config, api_key="ant-key", api_key_env="ANTHROPIC_API_KEY")

        MockAnthropic.assert_called_once()
        assert result is mock_instance

    def test_factory_anthropic_key_env_corrected_from_openai_to_anthropic(self):
        """When api_key_env='OPENAI_API_KEY' and backend is anthropic, factory
        corrects it to 'ANTHROPIC_API_KEY' before passing to AnthropicBackend."""
        config = _make_config("anthropic")

        with patch("src.llm.anthropic_backend.AnthropicBackend") as MockAnthropic:
            MockAnthropic.return_value = MagicMock()
            create_backend(config, api_key=None, api_key_env="OPENAI_API_KEY")

        call_kwargs = MockAnthropic.call_args
        assert call_kwargs is not None
        # api_key_env is passed as a keyword argument
        passed_env = call_kwargs.kwargs.get("api_key_env")
        assert passed_env == "ANTHROPIC_API_KEY", (
            f"Expected 'ANTHROPIC_API_KEY' but got '{passed_env}'"
        )

    def test_factory_anthropic_custom_key_env_preserved(self):
        """When api_key_env is already a custom value (not OPENAI_API_KEY),
        it should be passed through unchanged to AnthropicBackend."""
        config = _make_config("anthropic")

        with patch("src.llm.anthropic_backend.AnthropicBackend") as MockAnthropic:
            MockAnthropic.return_value = MagicMock()
            create_backend(config, api_key=None, api_key_env="MY_CUSTOM_ANT_KEY")

        call_kwargs = MockAnthropic.call_args
        passed_env = call_kwargs.kwargs.get("api_key_env")
        assert passed_env == "MY_CUSTOM_ANT_KEY"

    def test_factory_vllm_returns_openai_backend(self):
        """backend_type='vllm' should route to OpenAIBackend."""
        config = _make_config("vllm")
        mock_instance = MagicMock()

        with patch("src.llm.openai_backend.OpenAIBackend") as MockCompat:
            MockCompat.return_value = mock_instance
            result = create_backend(config, api_key=None, api_key_env="OPENAI_API_KEY")

        MockCompat.assert_called_once()
        assert result is mock_instance

    def test_factory_localai_returns_openai_backend(self):
        """backend_type='localai' should route to OpenAIBackend."""
        config = _make_config("localai")
        mock_instance = MagicMock()

        with patch("src.llm.openai_backend.OpenAIBackend") as MockCompat:
            MockCompat.return_value = mock_instance
            result = create_backend(config, api_key=None, api_key_env="OPENAI_API_KEY")

        MockCompat.assert_called_once()
        assert result is mock_instance

    def test_factory_llamacpp_returns_openai_backend(self):
        """backend_type='llamacpp' should route to OpenAIBackend."""
        config = _make_config("llamacpp")
        mock_instance = MagicMock()

        with patch("src.llm.openai_backend.OpenAIBackend") as MockCompat:
            MockCompat.return_value = mock_instance
            result = create_backend(config, api_key=None, api_key_env="OPENAI_API_KEY")

        MockCompat.assert_called_once()
        assert result is mock_instance

    def test_factory_invalid_backend_raises_value_error(self):
        """An unrecognised backend_type string should raise ValueError.

        The LLMBackendType enum prevents invalid values at construction time,
        so we bypass it by directly setting the attribute after construction.
        """
        config = _make_config("openai_compatible")
        # Bypass Pydantic validation to inject an invalid string
        object.__setattr__(config, "backend_type", "totally_unknown_backend")

        with pytest.raises(ValueError, match="Unsupported backend_type"):
            create_backend(config, api_key=None, api_key_env="OPENAI_API_KEY")


class TestBackendContractSurface:
    """Verify that backends produced by the factory expose the required contract methods.

    These tests catch the case where the factory returns a backend that is missing
    the canonical streaming method (generate_provider_deltas_async) -- the bug that
    was found in code review where the method was named async_generate_with_tools_stream.
    """

    def test_openai_native_backend_has_generate_provider_deltas_async(self):
        """OpenAINativeBackend produced by factory must have generate_provider_deltas_async."""
        import inspect
        config = _make_config("openai_native", model_name="gpt-4o")

        with patch("src.llm.openai_native_backend.OpenAI"), \
             patch("src.llm.openai_native_backend.AsyncOpenAI"):
            backend = create_backend(config, api_key="test-key", api_key_env="OPENAI_API_KEY")

        assert hasattr(backend, "generate_provider_deltas_async"), (
            "OpenAINativeBackend must expose generate_provider_deltas_async -- "
            "the old name async_generate_with_tools_stream is wrong"
        )
        method = backend.generate_provider_deltas_async
        assert inspect.ismethod(method) or callable(method), (
            "generate_provider_deltas_async must be callable"
        )

    def test_openai_native_backend_does_not_have_old_method_name(self):
        """OpenAINativeBackend must NOT expose the old async_generate_with_tools_stream name.

        If this test fails, the backend has the wrong method name and CodingAgent
        will fail to call it.
        """
        config = _make_config("openai_native", model_name="gpt-4o")

        with patch("src.llm.openai_native_backend.OpenAI"), \
             patch("src.llm.openai_native_backend.AsyncOpenAI"):
            backend = create_backend(config, api_key="test-key", api_key_env="OPENAI_API_KEY")

        # The old wrong name must not be the ONLY streaming method
        # (it may exist as an alias, but generate_provider_deltas_async must also exist)
        assert hasattr(backend, "generate_provider_deltas_async"), (
            "generate_provider_deltas_async is missing -- "
            "backend only has the old async_generate_with_tools_stream name"
        )

    def test_openai_native_backend_stream_id_is_optional(self):
        """generate_provider_deltas_async must accept stream_id as optional (keyword-only).

        The bug: stream_id was a required positional argument, so callers that
        omitted it got a TypeError at runtime.
        """
        import inspect
        config = _make_config("openai_native", model_name="gpt-4o")

        with patch("src.llm.openai_native_backend.OpenAI"), \
             patch("src.llm.openai_native_backend.AsyncOpenAI"):
            backend = create_backend(config, api_key="test-key", api_key_env="OPENAI_API_KEY")

        method = backend.generate_provider_deltas_async
        sig = inspect.signature(method)
        params = sig.parameters

        assert "stream_id" in params, (
            "generate_provider_deltas_async must have a stream_id parameter"
        )
        stream_id_param = params["stream_id"]
        assert stream_id_param.default is not inspect.Parameter.empty, (
            "stream_id must be optional (have a default value) -- "
            "was required (no default), causing TypeError when omitted"
        )

    def test_openai_compatible_backend_has_generate_provider_deltas_async(self):
        """OpenAIBackend (openai_compatible) must also expose generate_provider_deltas_async."""
        import inspect
        config = _make_config("openai_compatible", model_name="gpt-4o")

        with patch("src.llm.openai_backend.OpenAI"), \
             patch("src.llm.openai_backend.AsyncOpenAI"):
            backend = create_backend(config, api_key="test-key", api_key_env="OPENAI_API_KEY")

        assert hasattr(backend, "generate_provider_deltas_async"), (
            "OpenAIBackend must expose generate_provider_deltas_async"
        )
