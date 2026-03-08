"""
User-friendly error handling helpers.

Classifies exceptions into actionable messages, generates error reference IDs,
and extracts displayable text from multimodal message content.
"""

from typing import Any

from src.observability import get_logger

logger = get_logger(__name__)


def classify_error(e: Exception) -> tuple[str, str]:
    """
    Classify an exception into a user-friendly message.

    Industry standard approach:
    - Show friendly, actionable messages to users
    - Log technical details for debugging
    - Provide error reference ID for support

    Args:
        e: The exception to classify

    Returns:
        Tuple of (user_friendly_message, error_category)
    """
    error_str = str(e).lower()
    error_type = type(e).__name__.lower()

    # Timeout errors
    if any(x in error_str or x in error_type for x in ['timeout', 'timed out', 'deadline']):
        return (
            "Request timed out. The server took too long to respond. Please try again.",
            "timeout"
        )

    # Rate limiting
    if any(x in error_str for x in ['rate limit', 'rate_limit', 'too many requests', '429']):
        return (
            "Too many requests. Please wait a moment and try again.",
            "rate_limit"
        )

    # Authentication errors
    if any(x in error_str for x in ['authentication', 'unauthorized', 'invalid api key', '401', '403']):
        return (
            "Authentication failed. Please check your API key configuration.",
            "auth"
        )

    # Model/API service errors (like the LiteLLM "repeating chunk" error)
    if any(x in error_str for x in [
        'internal', 'server error', '500', '502', '503', '504',
        'repeating', 'service unavailable', 'overloaded', 'capacity'
    ]):
        return (
            "The AI service encountered a temporary issue. Please try again.",
            "service"
        )

    # Network/Connection errors
    if any(x in error_str or x in error_type for x in [
        'connection', 'network', 'dns', 'resolve', 'refused',
        'reset', 'broken pipe', 'eof', 'ssl', 'certificate'
    ]):
        return (
            "Connection error. Please check your network and try again.",
            "network"
        )

    # Context/Token limit errors
    if any(x in error_str for x in ['context', 'token', 'too long', 'maximum']):
        return (
            "The conversation is too long. Please start a new conversation or clear history.",
            "context"
        )

    # Invalid request errors
    if any(x in error_str for x in ['invalid', 'malformed', 'bad request', '400']):
        return (
            "Invalid request. Please try rephrasing your message.",
            "invalid"
        )

    # Default fallback - generic message
    return (
        "An unexpected error occurred. Please try again.",
        "unexpected"
    )


def generate_error_reference() -> str:
    """Generate a short error reference ID for user support."""
    import uuid
    return uuid.uuid4().hex[:8]


def extract_user_content_text(content: Any) -> str:
    """
    Extract displayable text from user message content.

    Handles both simple string content and multimodal content (list).
    For multimodal content, extracts text parts and adds placeholders for attachments.

    Args:
        content: Message content (string or list of content parts)

    Returns:
        String representation suitable for display
    """
    if isinstance(content, str):
        return content

    if not isinstance(content, list):
        return str(content) if content is not None else ""

    parts = []
    for item in content:
        if not isinstance(item, dict):
            continue

        item_type = item.get("type", "")

        if item_type == "text":
            # Extract text content
            text = item.get("text", "")
            if text:
                parts.append(text)

        elif item_type == "image_url":
            # Show image placeholder
            image_url = item.get("image_url", {})
            url = image_url.get("url", "") if isinstance(image_url, dict) else str(image_url)

            # Extract filename from data URL if present
            if url.startswith("data:image/"):
                # Format: data:image/png;base64,<data>
                parts.append("[IMAGE]")
            else:
                parts.append(f"[IMAGE: {url}]")

        elif item_type == "file":
            # Show file placeholder (if we add file support)
            filename = item.get("filename", "unknown")
            parts.append(f"[FILE: {filename}]")

    return "\n".join(parts) if parts else ""


def format_user_error(e: Exception, include_reference: bool = True) -> str:
    """
    Format an exception as a user-friendly error message.

    Args:
        e: The exception
        include_reference: Whether to include an error reference ID

    Returns:
        User-friendly error message
    """
    user_msg, category = classify_error(e)

    if include_reference:
        ref_id = generate_error_reference()
        # Log the mapping for debugging
        logger.info(f"Error reference {ref_id}: {type(e).__name__}: {e}")
        return f"{user_msg} (ref: {ref_id})"

    return user_msg


# Backward-compatible aliases (underscore-prefixed names used in app.py)
_classify_error = classify_error
_generate_error_reference = generate_error_reference
_extract_user_content_text = extract_user_content_text
_format_user_error = format_user_error
