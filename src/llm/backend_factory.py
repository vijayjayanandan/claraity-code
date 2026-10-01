"""Backend factory for LLM backends.

Single point of construction for all LLMBackend instances. Replaces the
duplicated if/elif backend selection blocks that previously existed in:
  - src/core/agent.py (x2: __init__ and reconfigure_llm)
  - src/server/config_handler.py (list_models_from_request)
  - src/server/stdio_server.py (_get_enrichment_backend)
  - src/subagents/runner.py (_create_llm_backend)

Adding a new provider = 1 line here only.
"""

from src.llm.base import LLMBackend, LLMConfig
from src.llm.model_config import requires_responses_api, uses_adaptive_thinking

try:
    from src.observability import get_logger

    logger = get_logger("llm.backend_factory")
except ImportError:  # pragma: no cover - observability always available in app
    import logging

    logger = logging.getLogger(__name__)

# OpenAI-compatible backends (all speak the OpenAI Chat Completions API)
_OPENAI_COMPATIBLE_TYPES = {"openai_compatible", "openai", "vllm", "localai", "llamacpp"}


def create_backend(
    config: LLMConfig,
    api_key: str | None,
    api_key_env: str,
) -> LLMBackend:
    """Instantiate the correct LLMBackend for the given config.

    Args:
        config: LLMConfig with backend_type and all generation parameters.
        api_key: Resolved API key string (may be empty/None -- backend reads
                 from env var as fallback).
        api_key_env: Name of the environment variable holding the API key.
                     For Anthropic this is corrected from OPENAI_API_KEY to
                     ANTHROPIC_API_KEY if the caller forgot.

    Returns:
        A concrete LLMBackend instance ready to use.

    Raises:
        ValueError: If backend_type is not recognised.
        ImportError: If a required optional SDK is not installed.
    """
    backend_type = str(config.backend_type).lower()

    if backend_type == "openai_native":
        from src.llm.openai_native_backend import OpenAINativeBackend

        return OpenAINativeBackend(config, api_key=api_key, api_key_env=api_key_env)

    if backend_type in _OPENAI_COMPATIBLE_TYPES:
        # Modern Claude models (Claude 5-family / Opus 4.7+) are rejected on
        # /v1/chat/completions by gateways (premium models require prompt
        # caching, only expressible on the Messages API). Route them to the
        # native AnthropicBackend against the same base_url and key. Older
        # Claude models (sonnet-4-6, haiku) stay on the proven chat
        # completions path. Opt out: llm.route_claude_to_messages: false.
        if getattr(config, "route_claude_to_messages", True) and uses_adaptive_thinking(
            config.model_name
        ):
            from src.llm.anthropic_backend import AnthropicBackend

            logger.info(
                "backend_routed",
                model=config.model_name,
                requested_backend=backend_type,
                routed_backend="anthropic",
                reason="modern Claude models require the Messages API",
            )
            # Keep the caller's api_key_env: in the routed case the key is
            # the gateway's (e.g. OPENAI_API_KEY / CLARAITY_API_KEY), not a
            # real Anthropic key.
            return AnthropicBackend(config, api_key=api_key, api_key_env=api_key_env)

        # gpt-6+ models reject function tools on /v1/chat/completions unless
        # reasoning is disabled. Route them to the Responses API via the
        # native backend (which honors base_url for gateways). gpt-5.x and
        # o-mini models work with tools on chat completions and stay put.
        # Opt out: llm.route_gpt_to_responses: false.
        if getattr(config, "route_gpt_to_responses", True) and requires_responses_api(
            config.model_name
        ):
            from src.llm.openai_native_backend import OpenAINativeBackend

            logger.info(
                "backend_routed",
                model=config.model_name,
                requested_backend=backend_type,
                routed_backend="openai_native",
                reason="gpt-6+ models require the Responses API for tool use",
            )
            return OpenAINativeBackend(config, api_key=api_key, api_key_env=api_key_env)

        from src.llm.openai_backend import OpenAIBackend

        return OpenAIBackend(config, api_key=api_key, api_key_env=api_key_env)

    if backend_type == "anthropic":
        from src.llm.anthropic_backend import AnthropicBackend

        # Callers that haven't updated their api_key_env still pass OPENAI_API_KEY.
        # Correct it here so Anthropic picks up the right credential automatically.
        corrected_env = "ANTHROPIC_API_KEY" if api_key_env == "OPENAI_API_KEY" else api_key_env
        return AnthropicBackend(config, api_key=api_key, api_key_env=corrected_env)

    raise ValueError(
        f"Unsupported backend_type: '{backend_type}'. "
        f"Valid types: openai_native, openai_compatible, anthropic, vllm, localai, llamacpp."
    )
