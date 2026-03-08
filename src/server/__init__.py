"""ClarAIty VS Code WebSocket Server.

Exposes the CodingAgent over WebSocket for VS Code extension integration.

Usage:
    python -m src.server                # Default: localhost:9120
    python -m src.server --port 9121    # Custom port
"""

from src.server.app import AgentServer
from src.server.ws_protocol import WebSocketProtocol
from src.server.serializers import serialize_event, serialize_store_notification, deserialize_action

__all__ = [
    "AgentServer",
    "WebSocketProtocol",
    "serialize_event",
    "serialize_store_notification",
    "deserialize_action",
]
