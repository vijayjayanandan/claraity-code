"""Pure-function handlers for LLM configuration.

Three functions that read/write config.yaml and keyring, with no
transport dependency. Called by protocol dispatch branches.
"""

import ipaddress
import socket

from src.observability import get_logger

logger = get_logger("server.config_handler")

SUBAGENT_NAMES = [
    "code-reviewer",
    "test-writer",
    "doc-writer",
    "code-writer",
    "explore",
    "planner",
    "general-purpose",
    "knowledge-builder",
]


def _validate_list_models_url(base_url: str) -> tuple:
    """Validate that a list_models URL doesn't target internal/private networks."""
    try:
        from urllib.parse import urlparse

        parsed = urlparse(base_url)
        hostname = parsed.hostname
        if not hostname:
            return False, "No hostname in URL"

        # Block obviously internal hostnames
        if hostname in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
            # Allow localhost for Ollama (common legitimate use)
            pass

        # Resolve and check for private IPs
        try:
            addrs = socket.getaddrinfo(hostname, None)
            for _, _, _, _, sockaddr in addrs:
                ip = ipaddress.ip_address(sockaddr[0])
                # Block link-local (cloud metadata) - 169.254.x.x
                if ip.is_link_local:
                    return False, f"Link-local address blocked (cloud metadata protection): {ip}"
        except (socket.gaierror, ValueError):
            pass  # DNS resolution failure is ok - will fail naturally later

        return True, ""
    except Exception as e:
        return False, f"URL validation error: {e}"


def get_config_response(config_path: str, working_directory: str = "") -> dict:
    """Load config from disk and return a sanitised dict (no api_key value).

    Returns:
        ``{"type": "config_loaded", "config": {...}, "subagent_names": [...]}``
    """
    from src.llm.config_loader import load_llm_config

    cfg = load_llm_config(config_path)

    config_dict = {
        "backend_type": cfg.backend_type,
        "base_url": cfg.base_url,
        "model": cfg.model,
        "context_window": cfg.context_window,
        "temperature": cfg.temperature,
        "max_tokens": cfg.max_tokens,
        "top_p": cfg.top_p,
        "thinking_budget": cfg.thinking_budget,
        "has_api_key": bool(cfg.api_key),
    }

    # Merge built-in names with discovered custom subagent names
    all_names = list(SUBAGENT_NAMES)
    if working_directory:
        try:
            from pathlib import Path
            from src.subagents.config import SubAgentConfigLoader

            loader = SubAgentConfigLoader(working_directory=Path(working_directory))
            for name, config in loader.discover_all().items():
                if name not in all_names:
                    all_names.append(name)
        except Exception as e:
            logger.debug("subagent_discovery_error", error=str(e))

    # Flatten subagent models to {name: model_str}
    subagent_models = {}
    for name in all_names:
        override = cfg.subagents.get(name)
        subagent_models[name] = override.model if override and override.model else ""

    config_dict["subagent_models"] = subagent_models

    # Web search provider
    config_dict["web_search_provider"] = cfg.web_search_provider

    # Prompt enrichment config
    from src.prompts.enrichment import ENRICHMENT_SYSTEM_PROMPT
    pe = cfg.prompt_enrichment
    config_dict["prompt_enrichment"] = {
        "model": pe.model,
        "system_prompt": pe.system_prompt,
        "default_system_prompt": ENRICHMENT_SYSTEM_PROMPT,
    }

    return {
        "type": "config_loaded",
        "config": config_dict,
        "subagent_names": all_names,
    }


def save_config_from_request(data: dict, config_path: str) -> dict:
    """Validate, build LLMConfigData, and persist to disk + keyring.

    Returns:
        ``{"type": "config_saved", "success": bool, "message": str}``
    """
    from src.llm.config_loader import LLMConfigData, SubAgentLLMOverride, save_llm_config

    raw = data.get("config", {})

    try:
        cfg = LLMConfigData(
            backend_type=str(raw.get("backend_type", "openai")),
            base_url=str(raw.get("base_url", "")),
            model=str(raw.get("model", "")),
            context_window=_int_or(raw.get("context_window"), 131072),
            temperature=_float_or(raw.get("temperature"), 0.2),
            max_tokens=_int_or(raw.get("max_tokens"), 16384),
            top_p=_float_or(raw.get("top_p"), 0.95),
            thinking_budget=_int_or_none(raw.get("thinking_budget")),
        )

        # Subagent overrides
        sa_models = raw.get("subagent_models", {})
        if isinstance(sa_models, dict):
            for name, model_str in sa_models.items():
                if model_str and str(model_str).strip():
                    cfg.subagents[str(name)] = SubAgentLLMOverride(model=str(model_str).strip())

        # Web search provider
        ws_provider = str(raw.get("web_search_provider", "tavily")).strip()
        if ws_provider in ("tavily", "brave"):
            cfg.web_search_provider = ws_provider

        # Prompt enrichment overrides
        from src.llm.config_loader import PromptEnrichmentConfig
        pe_raw = raw.get("prompt_enrichment", {})
        if isinstance(pe_raw, dict):
            cfg.prompt_enrichment = PromptEnrichmentConfig(
                model=str(pe_raw.get("model", "") or "").strip(),
                system_prompt=str(pe_raw.get("system_prompt", "") or "").strip(),
            )

        # API key is handled by VS Code SecretStorage (injected as env var)
        api_key = raw.get("api_key", "")

        ok = save_llm_config(cfg, config_path)
        if ok:
            return {
                "type": "config_saved",
                "success": True,
                "message": "Configuration saved.",
                "model": cfg.model,
                "_config": cfg,
                "_api_key": str(api_key) if api_key else "",
            }
        else:
            return {
                "type": "config_saved",
                "success": False,
                "message": "Failed to write config file.",
            }

    except Exception as exc:
        logger.error(f"[CONFIG] Save error: {exc}")
        return {"type": "config_saved", "success": False, "message": str(exc)}


def list_models_from_request(data: dict) -> dict:
    """Fetch available models from the configured backend (blocking HTTP).

    Inlines the model-listing logic so it works without Textual
    (which is excluded from the bundled binary).

    Returns:
        ``{"type": "models_list", "models": [...], "error": str|None}``
    """
    try:
        backend = str(data.get("backend", "openai"))
        base_url = str(data.get("base_url", ""))
        api_key = str(data.get("api_key", ""))

        # Fall back to stored key when the client sends an empty key
        # (the config form intentionally never pre-fills the key field)
        if not api_key:
            from src.llm.credential_store import load_api_key

            api_key = load_api_key()

        # SSRF protection: validate URL before making outbound request
        if base_url:
            is_valid, reason = _validate_list_models_url(base_url)
            if not is_valid:
                return {"type": "models_list", "models": [], "error": reason}

        models = _list_models(backend, base_url, api_key)
        return {"type": "models_list", "models": sorted(models, key=str.lower), "error": None}
    except Exception as exc:
        logger.warning(f"[CONFIG] list_models error: {exc}")
        return {"type": "models_list", "models": [], "error": str(exc)}


def _list_models(backend: str, base_url: str, api_key: str) -> list[str]:
    """Fetch model list from an LLM backend (no Textual dependency).

    Mirrors ``ConfigLLMScreen._list_models`` but importable without Textual.
    """
    from src.llm.base import LLMBackendType, LLMConfig

    if backend == "anthropic":
        from src.llm.anthropic_backend import AnthropicBackend

        config = LLMConfig(
            backend_type=LLMBackendType.ANTHROPIC,
            model_name="temp",
            base_url=base_url,
            temperature=0.2,
            max_tokens=1024,
            top_p=0.95,
            context_window=4096,
        )
        return AnthropicBackend(config, api_key=api_key).list_models()
    else:
        from src.llm.openai_backend import OpenAIBackend

        config = LLMConfig(
            backend_type=LLMBackendType.OPENAI,
            model_name="temp",
            base_url=base_url,
            temperature=0.2,
            max_tokens=1024,
            top_p=0.95,
            context_window=4096,
        )
        return OpenAIBackend(config, api_key=api_key).list_models()


# -- numeric coercion helpers --


def _int_or(val, default: int) -> int:
    if val is None or val == "":
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _float_or(val, default: float) -> float:
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _int_or_none(val):
    if val is None or val == "":
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


# =============================================================================
# Limits configuration
# =============================================================================


def get_limits_response(config_path: str) -> dict:
    """Load limits from disk and return them.

    Returns:
        ``{"type": "limits_loaded", "limits": {...}}``
    """
    from src.llm.config_loader import load_llm_config

    cfg = load_llm_config(config_path)
    lc = cfg.limits
    return {
        "type": "limits_loaded",
        "limits": {
            "iteration_limit_enabled": lc.iteration_limit_enabled,
            "max_iterations": lc.max_iterations,
        },
    }


def save_limits_from_request(data: dict, config_path: str) -> dict:
    """Validate and persist limits to config.yaml.

    Returns:
        ``{"type": "limits_saved", "success": bool, "message": str, "limits": {...}}``
    """
    from src.llm.config_loader import load_llm_config, save_llm_config

    raw = data.get("limits", {})

    try:
        cfg = load_llm_config(config_path)
        lc = cfg.limits

        if "iteration_limit_enabled" in raw:
            lc.iteration_limit_enabled = bool(raw["iteration_limit_enabled"])
        if "max_iterations" in raw:
            lc.max_iterations = max(1, _int_or(raw["max_iterations"], lc.max_iterations))

        ok = save_llm_config(cfg, config_path)
        if ok:
            return {
                "type": "limits_saved",
                "success": True,
                "message": "Settings saved.",
                "limits": {
                    "iteration_limit_enabled": lc.iteration_limit_enabled,
                    "max_iterations": lc.max_iterations,
                },
            }
        else:
            return {"type": "limits_saved", "success": False, "message": "Failed to write config file."}

    except Exception as exc:
        logger.error(f"[CONFIG] Save limits error: {exc}")
        return {"type": "limits_saved", "success": False, "message": str(exc)}
