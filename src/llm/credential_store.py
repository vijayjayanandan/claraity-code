"""
API key loading from environment variables.

Load chain: CLARAITY_API_KEY > api_key_env (default: OPENAI_API_KEY) > empty

In VS Code mode, the extension stores keys in SecretStorage and injects
them as CLARAITY_API_KEY when spawning the Python binary.

In TUI mode, users set environment variables directly.

API keys are NEVER stored in config.yaml or any plain text file.
"""

import os


def load_api_key(api_key_env: str = "OPENAI_API_KEY") -> str:
    """
    Load an API key from environment variables.

    Chain: CLARAITY_API_KEY > api_key_env > empty string.

    CLARAITY_API_KEY is checked first because the VS Code extension injects
    the API key via this env var when spawning the agent binary.

    Args:
        api_key_env: Name of env var to check as fallback (default: OPENAI_API_KEY)

    Returns:
        The API key string, or empty string if not found
    """
    return (
        os.environ.get("CLARAITY_API_KEY", "")
        or os.environ.get(api_key_env, "")
    )


def has_api_key(api_key_env: str = "OPENAI_API_KEY") -> bool:
    """
    Check if an API key is available in environment variables.

    Args:
        api_key_env: Name of env var to check as fallback

    Returns:
        True if a non-empty key is available
    """
    return bool(load_api_key(api_key_env))
