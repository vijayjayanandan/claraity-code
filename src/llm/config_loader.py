"""
Unified LLM configuration loader.

Loads LLM settings from `.clarity/config.yaml` and resolves them
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

VALID_BACKEND_TYPES = {"openai", "ollama", "vllm", "localai", "llamacpp", "anthropic"}


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
class LLMConfigData:
    """LLM configuration from config.yaml.

    Provides defaults that match the existing .env-based setup so that
    switching to the config file is a no-op for users who haven't created
    one yet.

    API keys are stored in the OS credential store (keyring), NOT in
    config.yaml. The ``api_key`` field is runtime-only (populated from
    keyring/env, never persisted to YAML).

    ``api_key_env`` stores the NAME of an env var as fallback when keyring
    is unavailable.
    """

    backend_type: str = "openai"
    base_url: str = ""
    api_key: str = ""          # Runtime only -- loaded from keyring/env, never saved to YAML
    api_key_env: str = "OPENAI_API_KEY"
    model: str = ""
    context_window: int = 131072
    temperature: float = 0.2
    max_tokens: int = 16384
    top_p: float = 0.95
    thinking_budget: int | None = None  # Extended thinking token budget (Claude, etc.)
    subagents: dict[str, SubAgentLLMOverride] = field(default_factory=dict)


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


def _migrate_api_key_to_keyring(api_key: str, config_path: str) -> None:
    """One-time migration: move api_key from YAML to OS credential store.

    Only removes the api_key from YAML if keyring is available and the save
    succeeds. If keyring is unavailable, the key stays in config.yaml (which
    is the intended fallback storage).
    """
    try:
        from src.llm.credential_store import _get_keyring
        kr = _get_keyring()
        if kr is None:
            # No keyring -- config.yaml IS the storage, don't remove it
            return
        kr.set_password("claraity", "api_key", api_key)
        _safe_stderr("Migrated api_key from config.yaml to OS credential store")
        _remove_api_key_from_yaml(config_path)
    except Exception as e:
        _safe_stderr(f"api_key migration to keyring failed, key remains in config.yaml: {e}")


def _remove_api_key_from_yaml(config_path: str) -> None:
    """Remove the api_key field from config.yaml after migration."""
    try:
        import yaml
        path = Path(config_path)
        if not path.exists():
            return
        raw = path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
        if isinstance(data, dict) and isinstance(data.get("llm"), dict):
            data["llm"].pop("api_key", None)
            path.write_text(
                yaml.dump(data, default_flow_style=False, sort_keys=False),
                encoding="utf-8",
            )
    except Exception as e:
        _safe_stderr(f"Failed to remove api_key from YAML: {e}")


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

    # -- api_key: if present in YAML and keyring is available, migrate --
    if "api_key" in llm_data and llm_data["api_key"]:
        _migrate_api_key_to_keyring(str(llm_data["api_key"]), config_path)

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
                    _safe_stderr(
                        f"Invalid context_window for subagent '{name}', ignoring"
                    )

            config.subagents[str(name)] = override

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

    # api_key is saved via credential_store.py (keyring > config.yaml fallback)
    # It is NOT written here to avoid double-writing

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
