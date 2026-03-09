"""Security utilities for ClarAIty agent.

Provides shared secret redaction patterns used by session persistence,
transcript logging, and other components that handle potentially sensitive data.
"""

import re
from typing import Any

# Patterns that match common secret formats
SECRET_PATTERNS: list[re.Pattern] = [
    re.compile(r'(sk-[a-zA-Z0-9_-]{20,})'),                          # OpenAI API keys
    re.compile(r'(sk-ant-[a-zA-Z0-9_-]{20,})'),                      # Anthropic API keys
    re.compile(r'(AKIA[0-9A-Z]{16})'),                                # AWS access key IDs
    re.compile(r'(ghp_[a-zA-Z0-9]{36,})'),                            # GitHub personal tokens
    re.compile(r'(gho_[a-zA-Z0-9]{36,})'),                            # GitHub OAuth tokens
    re.compile(r'(glpat-[a-zA-Z0-9_-]{20,})'),                        # GitLab tokens
    re.compile(r'(xoxb-[a-zA-Z0-9-]+)'),                              # Slack bot tokens
    re.compile(r'(xoxp-[a-zA-Z0-9-]+)'),                              # Slack user tokens
    re.compile(r'(Bearer\s+[a-zA-Z0-9_.\-]{20,})'),                   # Bearer tokens
    re.compile(r'(eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,})'),  # JWTs
    re.compile(r'(?i)(api[_-]?key\s*[=:]\s*)["\']?([a-zA-Z0-9_\-]{16,})["\']?'),     # Generic api_key=value
    re.compile(r'(?i)(password\s*[=:]\s*)["\']?([^\s"\']{8,})["\']?'),                # password=value
    re.compile(r'(?i)(secret\s*[=:]\s*)["\']?([a-zA-Z0-9_\-]{16,})["\']?'),           # secret=value
]

# Keys in dicts that should have their values redacted
SENSITIVE_KEYS = frozenset({
    "api_key", "apiKey", "api-key",
    "password", "passwd", "secret",
    "token", "access_token", "refresh_token",
    "authorization", "auth",
    "private_key", "privateKey",
    "credential", "credentials",
})

REDACTED = "[REDACTED]"


def redact_secrets(text: str) -> str:
    """Redact known secret patterns from a text string.

    Args:
        text: Input text that may contain secrets.

    Returns:
        Text with secrets replaced by [REDACTED].
    """
    if not text or not isinstance(text, str):
        return text

    result = text
    for pattern in SECRET_PATTERNS:
        result = pattern.sub(
            lambda m: m.group()[:4] + REDACTED if len(m.group()) > 4 else REDACTED,
            result,
        )
    return result


def redact_dict(data: dict[str, Any], depth: int = 0, max_depth: int = 10) -> dict[str, Any]:
    """Recursively redact sensitive values from a dictionary.

    Args:
        data: Dictionary that may contain sensitive values.
        depth: Current recursion depth.
        max_depth: Maximum recursion depth.

    Returns:
        New dictionary with sensitive values redacted.
    """
    if depth > max_depth:
        return data

    result = {}
    for key, value in data.items():
        if key.lower() in {k.lower() for k in SENSITIVE_KEYS}:
            result[key] = REDACTED
        elif isinstance(value, str):
            result[key] = redact_secrets(value)
        elif isinstance(value, dict):
            result[key] = redact_dict(value, depth + 1, max_depth)
        elif isinstance(value, list):
            result[key] = [
                redact_dict(item, depth + 1, max_depth) if isinstance(item, dict)
                else redact_secrets(item) if isinstance(item, str)
                else item
                for item in value
            ]
        else:
            result[key] = value
    return result
