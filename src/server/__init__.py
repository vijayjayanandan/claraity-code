"""ClarAIty VS Code Server (stdio+TCP transport).

Exposes the CodingAgent over stdio+TCP for VS Code extension integration.

Usage:
    python -m src.server --stdio --data-port 12345
"""

from src.server.serializers import deserialize_action, serialize_event, serialize_store_notification

__all__ = [
    "serialize_event",
    "serialize_store_notification",
    "deserialize_action",
]
