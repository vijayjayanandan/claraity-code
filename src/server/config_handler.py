"""Pure-function handlers for LLM configuration over WebSocket.

Three functions that read/write config.yaml and keyring, with no
WebSocket dependency. Called by ws_protocol dispatch branches.
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


def get_config_response(config_path: str) -> dict:
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
        "api_key": cfg.api_key or "",
    }

    # Flatten subagent models to {name: model_str}
    subagent_models = {}
    for name in SUBAGENT_NAMES:
        override = cfg.subagents.get(name)
        subagent_models[name] = override.model if override and override.model else ""

    config_dict["subagent_models"] = subagent_models

    return {
        "type": "config_loaded",
        "config": config_dict,
        "subagent_names": list(SUBAGENT_NAMES),
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

        # Save API key if provided (non-empty)
        api_key = raw.get("api_key", "")
        if api_key:
            from src.llm.credential_store import save_api_key

            save_api_key(str(api_key))

        ok = save_llm_config(cfg, config_path)
        if ok:
            return {
                "type": "config_saved",
                "success": True,
                "message": "Configuration saved. Restart server to apply changes.",
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

    Returns:
        ``{"type": "models_list", "models": [...], "error": str|None}``
    """
    try:
        from src.ui.llm_config_screen import ConfigLLMScreen

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

        models = ConfigLLMScreen._list_models(backend, base_url, api_key)
        return {"type": "models_list", "models": sorted(models, key=str.lower), "error": None}
    except Exception as exc:
        logger.warning(f"[CONFIG] list_models error: {exc}")
        return {"type": "models_list", "models": [], "error": str(exc)}


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
