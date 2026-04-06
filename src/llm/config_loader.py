"""
Unified LLM configuration loader.

Loads LLM settings from `.claraity/config.yaml` and resolves them
against environment variables and CLI flags using a layered priority:

    Environment variables / CLI flags  (highest priority)
        > config.yaml
        > code defaults                (lowest priority)

Mirrors the pattern in `src/observability/log_config_loader.py`.

Engineering Principles:
- No emojis in code (Windows cp1252 compatibility)
- Graceful degradation: invalid/missing config falls back to defaults
- Never crashes the app on bad config -- warn and continue
- `save_llm_config` does a YAML merge: updates `llm:` section, preserves `logging:`
"""

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# =============================================================================
# CONSTANTS
# =============================================================================

SYSTEM_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".claraity")
SYSTEM_CONFIG_PATH = os.path.join(SYSTEM_CONFIG_DIR, "config.yaml")

DEFAULT_CONFIG_PATH = SYSTEM_CONFIG_PATH

VALID_BACKEND_TYPES = {"openai", "vllm", "localai", "llamacpp", "anthropic"}


# =============================================================================
# DATA MODEL
# =============================================================================


@dataclass
class SubAgentLLMOverride:
    """Per-subagent LLM overrides from config.yaml.

    All fields are optional. ``None`` means "inherit from the main agent".
    """

    model: str | None = None
    backend_type: str | None = None
    base_url: str | None = None
    api_key_env: str | None = None
    context_window: int | None = None


@dataclass
class AutoApproveConfig:
    """Persisted auto-approve category settings.

    Each field maps to a tool category. True means tools in that
    category run without asking for user confirmation.
    """

    read: bool = True
    edit: bool = False
    execute: bool = False
    browser: bool = False
    knowledge_update: bool = False
    subagent: bool = False


@dataclass
class PromptEnrichmentConfig:
    """Configuration for the prompt enrichment feature.

    model: LLM model to use for enrichment. Empty string means inherit
           the main agent's model.
    system_prompt: System prompt sent to the enrichment LLM. Empty string
                   means use the built-in default defined in stdio_server.py.
    """

    model: str = ""
    system_prompt: str = ""


@dataclass
class LimitsConfig:
    """Configurable limits for the tool execution loop.

    When iteration_limit_enabled is False, the iteration check is skipped
    and the agent runs until it finishes or the user interrupts.
    """

    iteration_limit_enabled: bool = True
    max_iterations: int = 50


@dataclass
class LLMConfigData:
    """LLM configuration from config.yaml.

    Provides defaults that match the existing .env-based setup so that
    switching to the config file is a no-op for users who haven't created
    one yet.

    API keys are NEVER stored in config.yaml. The ``api_key`` field is
    runtime-only (populated from env var or OS keyring).

    ``api_key_env`` stores the NAME of an env var to check for the key.
    """

    backend_type: str = "openai"
    base_url: str = ""
    api_key: str = ""  # Runtime only -- loaded from env/keyring, never in YAML
    api_key_env: str = "OPENAI_API_KEY"
    model: str = ""
    context_window: int = 131072
    temperature: float = 0.2
    max_tokens: int = 16384
    top_p: float = 0.95
    thinking_budget: int | None = None  # Extended thinking token budget (Claude, etc.)
    subagents: dict[str, SubAgentLLMOverride] = field(default_factory=dict)
    limits: LimitsConfig = field(default_factory=LimitsConfig)
    auto_approve: AutoApproveConfig = field(default_factory=AutoApproveConfig)
    prompt_enrichment: PromptEnrichmentConfig = field(default_factory=PromptEnrichmentConfig)


# =============================================================================
# HELPERS
# =============================================================================


def _safe_stderr(message: str) -> None:
    """Write warning to stderr without going through logging (avoids recursion)."""
    try:
        print(f"[LLMConfigLoader] {message}", file=sys.__stderr__)
    except Exception:
        pass


def _validate_backend(backend: str, context: str) -> str | None:
    """Validate backend type string. Returns lowercase or None if invalid."""
    lower = backend.lower()
    if lower in VALID_BACKEND_TYPES:
        return lower
    _safe_stderr(f"Invalid backend_type '{backend}' in {context}, ignoring")
    return None


# =============================================================================
# LOADER
# =============================================================================


def load_llm_config(config_path: str = DEFAULT_CONFIG_PATH) -> LLMConfigData:
    """
    Load LLM configuration from YAML file.

    Returns defaults if the file doesn't exist or is invalid.
    Never raises -- always returns a valid LLMConfigData.

    Args:
        config_path: Path to the YAML config file

    Returns:
        LLMConfigData with loaded or default values
    """
    config = LLMConfigData()
    path = Path(config_path)

    if not path.exists():
        return config

    try:
        import yaml
    except ImportError:
        _safe_stderr("PyYAML not installed, using default LLM config")
        return config

    try:
        raw = path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
    except Exception as e:
        _safe_stderr(f"Failed to parse {config_path}: {e}, using defaults")
        return config

    if not isinstance(data, dict):
        return config

    llm_data = data.get("llm")
    if not isinstance(llm_data, dict):
        return config

    # -- backend_type --
    if "backend_type" in llm_data:
        validated = _validate_backend(str(llm_data["backend_type"]), "llm.backend_type")
        if validated:
            config.backend_type = validated

    # -- base_url --
    if "base_url" in llm_data and llm_data["base_url"]:
        config.base_url = str(llm_data["base_url"])

    # -- api_key in YAML is not supported -- warn and ignore --
    if "api_key" in llm_data and llm_data["api_key"]:
        _safe_stderr("api_key in config.yaml is not supported. Use environment variable or OS credential store.")

    # -- api_key_env (env var name, fallback) --
    if "api_key_env" in llm_data and llm_data["api_key_env"]:
        config.api_key_env = str(llm_data["api_key_env"])

    # -- model --
    if "model" in llm_data and llm_data["model"]:
        config.model = str(llm_data["model"])

    # -- Numeric/float fields --
    for key, attr, type_fn in [
        ("context_window", "context_window", int),
        ("temperature", "temperature", float),
        ("max_tokens", "max_tokens", int),
        ("top_p", "top_p", float),
        ("thinking_budget", "thinking_budget", int),
    ]:
        if key in llm_data:
            try:
                val = type_fn(llm_data[key])
                setattr(config, attr, val)
            except (TypeError, ValueError):
                _safe_stderr(f"Invalid value for llm.{key}, ignoring")

    # -- Subagent overrides --
    subagents_data = llm_data.get("subagents")
    if isinstance(subagents_data, dict):
        for name, overrides in subagents_data.items():
            if not isinstance(overrides, dict):
                _safe_stderr(f"Invalid subagent config for '{name}', ignoring")
                continue

            override = SubAgentLLMOverride()

            if "model" in overrides and overrides["model"]:
                override.model = str(overrides["model"])
            if "backend_type" in overrides and overrides["backend_type"]:
                validated = _validate_backend(
                    str(overrides["backend_type"]),
                    f"llm.subagents.{name}.backend_type",
                )
                if validated:
                    override.backend_type = validated
            if "base_url" in overrides and overrides["base_url"]:
                override.base_url = str(overrides["base_url"])
            if "api_key_env" in overrides and overrides["api_key_env"]:
                override.api_key_env = str(overrides["api_key_env"])
            if "context_window" in overrides:
                try:
                    override.context_window = int(overrides["context_window"])
                except (TypeError, ValueError):
                    _safe_stderr(f"Invalid context_window for subagent '{name}', ignoring")

            config.subagents[str(name)] = override

    # -- Limits (top-level `limits:` section, separate from `llm:`) --
    limits_data = data.get("limits")
    if isinstance(limits_data, dict):
        lc = config.limits
        for key, attr, type_fn in [
            ("iteration_limit_enabled", "iteration_limit_enabled", bool),
            ("max_iterations", "max_iterations", int),
        ]:
            if key in limits_data:
                try:
                    setattr(lc, attr, type_fn(limits_data[key]))
                except (TypeError, ValueError):
                    _safe_stderr(f"Invalid value for limits.{key}, ignoring")

    # -- Auto-approve (top-level `auto_approve:` section) --
    aa_data = data.get("auto_approve")
    if isinstance(aa_data, dict):
        ac = config.auto_approve
        for key in ("read", "edit", "execute", "browser", "knowledge_update", "subagent"):
            if key in aa_data:
                try:
                    setattr(ac, key, bool(aa_data[key]))
                except (TypeError, ValueError):
                    _safe_stderr(f"Invalid value for auto_approve.{key}, ignoring")

    # -- Prompt enrichment (top-level `prompt_enrichment:` section) --
    pe_data = data.get("prompt_enrichment")
    if isinstance(pe_data, dict):
        pe = config.prompt_enrichment
        if "model" in pe_data and pe_data["model"]:
            pe.model = str(pe_data["model"])
        if "system_prompt" in pe_data and pe_data["system_prompt"]:
            pe.system_prompt = str(pe_data["system_prompt"])

    # Populate api_key from credential store (runtime only, never saved to YAML)
    try:
        from src.llm.credential_store import load_api_key

        config.api_key = load_api_key(api_key_env=config.api_key_env)
    except Exception:
        pass  # Graceful degradation

    return config


# =============================================================================
# SAVE (YAML merge)
# =============================================================================


def save_llm_config(
    config: LLMConfigData,
    config_path: str = DEFAULT_CONFIG_PATH,
) -> bool:
    """
    Save LLM configuration to YAML file.

    Does a YAML merge: reads existing file, updates the ``llm:`` section,
    and preserves everything else (e.g. ``logging:``).

    Args:
        config: LLM configuration to save
        config_path: Path to the YAML config file

    Returns:
        True if saved successfully, False otherwise
    """
    try:
        import yaml
    except ImportError:
        _safe_stderr("PyYAML not installed, cannot save LLM config")
        return False

    path = Path(config_path)

    # Read existing file to preserve non-LLM sections
    existing_data: dict = {}
    if path.exists():
        try:
            raw = path.read_text(encoding="utf-8")
            existing_data = yaml.safe_load(raw) or {}
            if not isinstance(existing_data, dict):
                existing_data = {}
        except Exception as e:
            _safe_stderr(f"Failed to read existing config for merge: {e}")
            existing_data = {}

    # Build the llm section
    llm_section: dict = {
        "backend_type": config.backend_type,
        "base_url": config.base_url,
        "model": config.model,
        "context_window": config.context_window,
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
        "top_p": config.top_p,
    }

    # Only write thinking_budget if set
    if config.thinking_budget is not None:
        llm_section["thinking_budget"] = config.thinking_budget

    # api_key is saved via credential_store.py (keyring/env only, never to YAML)

    # Only write api_key_env if non-default
    if config.api_key_env and config.api_key_env != "OPENAI_API_KEY":
        llm_section["api_key_env"] = config.api_key_env

    # Add subagent overrides (only non-None fields)
    if config.subagents:
        subagents_section: dict = {}
        for name, override in config.subagents.items():
            entry: dict = {}
            if override.model is not None:
                entry["model"] = override.model
            if override.backend_type is not None:
                entry["backend_type"] = override.backend_type
            if override.base_url is not None:
                entry["base_url"] = override.base_url
            if override.api_key_env is not None:
                entry["api_key_env"] = override.api_key_env
            if override.context_window is not None:
                entry["context_window"] = override.context_window
            if entry:
                subagents_section[name] = entry
        if subagents_section:
            llm_section["subagents"] = subagents_section

    # Merge into existing data
    existing_data["llm"] = llm_section

    # Build limits section (top-level, separate from llm)
    existing_data["limits"] = {
        "iteration_limit_enabled": config.limits.iteration_limit_enabled,
        "max_iterations": config.limits.max_iterations,
    }

    # Build auto_approve section (top-level)
    existing_data["auto_approve"] = {
        "read": config.auto_approve.read,
        "edit": config.auto_approve.edit,
        "execute": config.auto_approve.execute,
        "browser": config.auto_approve.browser,
        "knowledge_update": config.auto_approve.knowledge_update,
        "subagent": config.auto_approve.subagent,
    }

    # Build prompt_enrichment section (top-level, only if non-default)
    pe = config.prompt_enrichment
    if pe.model or pe.system_prompt:
        existing_data["prompt_enrichment"] = {
            "model": pe.model,
            "system_prompt": pe.system_prompt,
        }
    else:
        # Remove the section if both fields are empty (clean YAML)
        existing_data.pop("prompt_enrichment", None)

    # Write back
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.dump(existing_data, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
        return True
    except Exception as e:
        _safe_stderr(f"Failed to save LLM config: {e}")
        return False


# =============================================================================
# RESOLVE (priority layering)
# =============================================================================


def resolve_llm_config(
    env_vars: dict[str, str | None],
    cli_args: dict[str, str | None],
    config: LLMConfigData,
) -> LLMConfigData:
    """
    Apply priority layering to resolve the final LLM config.

    Priority: cli_args > env_vars > config (already loaded from YAML) > defaults

    CLI args and env vars that are None are skipped (not set).
    Mutates and returns the input ``config`` object in-place.

    Expected keys in env_vars / cli_args:
        model, backend, url, context_window, temperature, max_tokens,
        top_p, api_key_env

    Args:
        env_vars: Values from environment variables (None if not set)
        cli_args: Values from argparse (None if not passed)
        config: Config loaded from YAML (mutated in-place)

    Returns:
        The same LLMConfigData instance with resolved values
    """
    # Apply env vars first (lower priority)
    _apply_overrides(env_vars, config, "env var")

    # Apply CLI args second (higher priority -- overwrites env)
    _apply_overrides(cli_args, config, "CLI flag")

    return config


def _apply_overrides(
    overrides: dict[str, str | None],
    config: LLMConfigData,
    source: str,
) -> None:
    """Apply a dict of overrides to the config, skipping None values."""
    if not overrides:
        return

    if overrides.get("model"):
        config.model = str(overrides["model"])

    if overrides.get("backend"):
        validated = _validate_backend(str(overrides["backend"]), source)
        if validated:
            config.backend_type = validated

    if overrides.get("url"):
        config.base_url = str(overrides["url"])

    if overrides.get("api_key"):
        config.api_key = str(overrides["api_key"])

    if overrides.get("api_key_env"):
        config.api_key_env = str(overrides["api_key_env"])

    for key, attr, type_fn in [
        ("context_window", "context_window", int),
        ("temperature", "temperature", float),
        ("max_tokens", "max_tokens", int),
        ("top_p", "top_p", float),
        ("thinking_budget", "thinking_budget", int),
    ]:
        val = overrides.get(key)
        if val is not None:
            try:
                setattr(config, attr, type_fn(val))
            except (TypeError, ValueError):
                _safe_stderr(f"Invalid {key} from {source}, ignoring")


# =============================================================================
# CONVENIENCE
# =============================================================================


def is_llm_configured(config_path: str = DEFAULT_CONFIG_PATH) -> bool:
    """
    Check whether a usable LLM configuration exists.

    Returns True if the config file has a non-empty ``llm.model`` field
    *or* the ``LLM_MODEL`` environment variable is set.

    Args:
        config_path: Path to the YAML config file

    Returns:
        True if LLM is configured, False otherwise
    """
    # Check env var first (fast path)
    if os.environ.get("LLM_MODEL"):
        return True

    config = load_llm_config(config_path)
    return bool(config.model)


# =============================================================================
# TRACE CONFIG
# =============================================================================


def load_trace_enabled(config_path: str = DEFAULT_CONFIG_PATH) -> bool:
    """Read trace_enabled from config.yaml. Default: False."""
    path = Path(config_path)
    if not path.exists():
        return False
    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return bool(data.get("trace_enabled", False))
    except Exception:
        pass
    return False


def save_trace_enabled(enabled: bool, config_path: str = DEFAULT_CONFIG_PATH) -> bool:
    """Write trace_enabled to config.yaml (YAML merge — preserves other keys)."""
    try:
        import yaml
    except ImportError:
        return False

    path = Path(config_path)
    existing: dict = {}
    if path.exists():
        try:
            existing = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if not isinstance(existing, dict):
                existing = {}
        except Exception:
            existing = {}

    existing["trace_enabled"] = enabled
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.dump(existing, default_flow_style=False, sort_keys=False), encoding="utf-8")
        return True
    except Exception:
        return False
