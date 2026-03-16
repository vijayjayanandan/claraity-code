"""
Secure API key storage with fallback chain.

Storage priority:
    Save: keyring (OS credential store) > config.yaml
    Load: keyring > config.yaml > os.getenv(api_key_env) > empty string

Uses the `keyring` library when available for OS-level secure storage:
- Windows: Credential Manager
- macOS: Keychain
- Linux: Secret Service (GNOME Keyring / KWallet)

When keyring is not installed, falls back to storing the API key in
.clarity/config.yaml (same pattern as gh, aws, npm CLI tools).

Engineering Principles:
- Always persists the key somewhere (never silently drops it)
- Graceful degradation: keyring > config.yaml > env var
- No emojis (Windows cp1252 compatibility)
"""

import os
import sys
from pathlib import Path
from typing import Optional

SERVICE_NAME = "claraity"
"""Keyring service name. All credentials are scoped under this."""

USERNAME = "api_key"
"""Default keyring username for the main LLM API key."""

DEFAULT_CONFIG_PATH = os.path.join(".clarity", "config.yaml")


def _safe_stderr(message: str) -> None:
    """Write warning to stderr without going through logging."""
    try:
        print(f"[CredentialStore] {message}", file=sys.__stderr__)
    except Exception:
        pass


def _get_keyring():
    """Import and return the keyring module, or None if unavailable."""
    try:
        import keyring

        return keyring
    except ImportError:
        return None


# ---- config.yaml fallback ----


def _save_to_config_yaml(api_key: str, config_path: str = DEFAULT_CONFIG_PATH) -> bool:
    """Save api_key into the llm section of config.yaml."""
    try:
        import yaml

        path = Path(config_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        data: dict = {}
        if path.exists():
            raw = path.read_text(encoding="utf-8")
            data = yaml.safe_load(raw) or {}
            if not isinstance(data, dict):
                data = {}

        if "llm" not in data or not isinstance(data.get("llm"), dict):
            data["llm"] = {}

        data["llm"]["api_key"] = api_key

        path.write_text(
            yaml.dump(data, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
        return True
    except Exception as e:
        _safe_stderr(f"Failed to save api_key to config.yaml: {e}")
        return False


def _load_from_config_yaml(config_path: str = DEFAULT_CONFIG_PATH) -> str:
    """Load api_key from the llm section of config.yaml."""
    try:
        import yaml

        path = Path(config_path)
        if not path.exists():
            return ""
        raw = path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
        if isinstance(data, dict) and isinstance(data.get("llm"), dict):
            return str(data["llm"].get("api_key", "") or "")
        return ""
    except Exception:
        return ""


# ---- Public API ----


def save_api_key(api_key: str, username: str = USERNAME) -> bool:
    """
    Save an API key. Tries keyring first, falls back to config.yaml.

    Args:
        api_key: The API key to store
        username: Credential identifier (default: "api_key")

    Returns:
        True if saved successfully, False otherwise
    """
    if not api_key:
        return False

    # Try keyring first
    kr = _get_keyring()
    if kr is not None:
        try:
            kr.set_password(SERVICE_NAME, username, api_key)
            return True
        except Exception as e:
            _safe_stderr(f"Keyring save failed: {e}, falling back to config.yaml")

    # Fallback to config.yaml
    return _save_to_config_yaml(api_key)


def load_api_key(
    username: str = USERNAME,
    api_key_env: str = "OPENAI_API_KEY",
) -> str:
    """
    Load an API key with fallback chain:
    CLARAITY_API_KEY env > keyring > config.yaml > api_key_env env > empty.

    CLARAITY_API_KEY is checked first because the VS Code extension injects
    the API key via this env var when spawning the agent binary.

    Args:
        username: Credential identifier (default: "api_key")
        api_key_env: Name of env var to check as fallback

    Returns:
        The API key string, or empty string if not found
    """
    # Highest priority: CLARAITY_API_KEY env var (set by VS Code extension)
    from_ext = os.environ.get("CLARAITY_API_KEY", "")
    if from_ext:
        return from_ext

    # Try keyring
    kr = _get_keyring()
    if kr is not None:
        try:
            stored = kr.get_password(SERVICE_NAME, username)
            if stored:
                return stored
        except Exception as e:
            _safe_stderr(f"Keyring read failed: {e}")

    # Try config.yaml
    from_yaml = _load_from_config_yaml()
    if from_yaml:
        return from_yaml

    # Fallback to environment variable
    return os.environ.get(api_key_env, "")


def delete_api_key(username: str = USERNAME) -> bool:
    """
    Delete an API key from the OS credential store.

    Args:
        username: Credential identifier (default: "api_key")

    Returns:
        True if deleted successfully, False otherwise
    """
    kr = _get_keyring()
    if kr is None:
        return False

    try:
        kr.delete_password(SERVICE_NAME, username)
        return True
    except Exception as e:
        _safe_stderr(f"Failed to delete key from credential store: {e}")
        return False


def has_api_key(
    username: str = USERNAME,
    api_key_env: str = "OPENAI_API_KEY",
) -> bool:
    """
    Check if an API key is available (in keyring, config.yaml, or env var).

    Args:
        username: Credential identifier (default: "api_key")
        api_key_env: Name of env var to check as fallback

    Returns:
        True if a non-empty key is available
    """
    return bool(load_api_key(username, api_key_env))
