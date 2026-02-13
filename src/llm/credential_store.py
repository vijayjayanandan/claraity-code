"""
Secure API key storage using the OS credential store.

Uses the `keyring` library to store API keys in:
- Windows: Credential Manager
- macOS: Keychain
- Linux: Secret Service (GNOME Keyring / KWallet)

Fallback chain for loading:
    keyring > os.getenv(api_key_env) > empty string

Engineering Principles:
- Never stores secrets in config.yaml or logs
- Graceful degradation: if keyring is unavailable, falls back to env vars
- No emojis (Windows cp1252 compatibility)
"""

import os
import sys
from typing import Optional

SERVICE_NAME = "claraity"
"""Keyring service name. All credentials are scoped under this."""

USERNAME = "api_key"
"""Default keyring username for the main LLM API key."""


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
        _safe_stderr("keyring not installed, falling back to env vars")
        return None


def save_api_key(api_key: str, username: str = USERNAME) -> bool:
    """
    Save an API key to the OS credential store.

    Args:
        api_key: The API key to store
        username: Credential identifier (default: "api_key")

    Returns:
        True if saved successfully, False otherwise
    """
    if not api_key:
        return False

    kr = _get_keyring()
    if kr is None:
        return False

    try:
        kr.set_password(SERVICE_NAME, username, api_key)
        return True
    except Exception as e:
        _safe_stderr(f"Failed to save key to credential store: {e}")
        return False


def load_api_key(
    username: str = USERNAME,
    api_key_env: str = "OPENAI_API_KEY",
) -> str:
    """
    Load an API key with fallback chain: keyring > env var > empty.

    Args:
        username: Credential identifier (default: "api_key")
        api_key_env: Name of env var to check as fallback

    Returns:
        The API key string, or empty string if not found
    """
    # Try keyring first
    kr = _get_keyring()
    if kr is not None:
        try:
            stored = kr.get_password(SERVICE_NAME, username)
            if stored:
                return stored
        except Exception as e:
            _safe_stderr(f"Failed to read from credential store: {e}")

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
    Check if an API key is available (in keyring or env var).

    Args:
        username: Credential identifier (default: "api_key")
        api_key_env: Name of env var to check as fallback

    Returns:
        True if a non-empty key is available
    """
    return bool(load_api_key(username, api_key_env))
