"""
ClarAIty WebSocket Support

Provides WebSocket endpoint for real-time architecture generation updates.
Streams component creation, decision-making, and code generation events.
"""

from fastapi import WebSocket, WebSocketDisconnect
from typing import Dict, List, Any, Optional
import json
import asyncio
from datetime import datetime


class ConnectionManager:
    """Manages WebSocket connections for real-time updates"""

    def __init__(self):
        """Initialize connection manager"""
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, session_id: str):
        """
        Accept WebSocket connection

        Args:
            websocket: WebSocket connection
            session_id: Generation session ID
        """
        await websocket.accept()

        if session_id not in self.active_connections:
            self.active_connections[session_id] = []

        self.active_connections[session_id].append(websocket)

    def disconnect(self, websocket: WebSocket, session_id: str):
        """
        Remove WebSocket connection

        Args:
            websocket: WebSocket connection
            session_id: Generation session ID
        """
        if session_id in self.active_connections:
            if websocket in self.active_connections[session_id]:
                self.active_connections[session_id].remove(websocket)

            # Clean up empty session
            if not self.active_connections[session_id]:
                del self.active_connections[session_id]

    async def send_to_session(self, session_id: str, message: Dict[str, Any]):
        """
        Send message to all connections in a session

        Args:
            session_id: Generation session ID
            message: Message data
        """
        if session_id not in self.active_connections:
            return

        # Add timestamp
        message['timestamp'] = datetime.utcnow().isoformat()

        # Send to all connections
        disconnected = []
        for connection in self.active_connections[session_id]:
            try:
                await connection.send_json(message)
            except Exception:
                # Mark for removal
                disconnected.append(connection)

        # Clean up disconnected
        for connection in disconnected:
            self.disconnect(connection, session_id)

    async def broadcast(self, message: Dict[str, Any]):
        """
        Broadcast message to all active connections

        Args:
            message: Message data
        """
        message['timestamp'] = datetime.utcnow().isoformat()

        for session_id in list(self.active_connections.keys()):
            await self.send_to_session(session_id, message)


# Global connection manager
manager = ConnectionManager()


async def send_generation_event(
    session_id: str,
    event_type: str,
    data: Dict[str, Any],
    status: str = "in_progress"
):
    """
    Send generation event to WebSocket clients

    Args:
        session_id: Generation session ID
        event_type: Event type (component_created, decision_made, code_generated, etc.)
        data: Event data
        status: Event status (in_progress, completed, error)
    """
    message = {
        "type": event_type,
        "status": status,
        "data": data
    }
    await manager.send_to_session(session_id, message)


async def send_component_created(
    session_id: str,
    component: Dict[str, Any]
):
    """
    Send component creation event

    Args:
        session_id: Generation session ID
        component: Component data
    """
    await send_generation_event(
        session_id=session_id,
        event_type="component_created",
        data={
            "component": component,
            "message": f"Created component: {component.get('name', 'unknown')}"
        }
    )


async def send_decision_made(
    session_id: str,
    component_id: str,
    decision: Dict[str, Any]
):
    """
    Send design decision event

    Args:
        session_id: Generation session ID
        component_id: Component ID
        decision: Decision data
    """
    await send_generation_event(
        session_id=session_id,
        event_type="decision_made",
        data={
            "component_id": component_id,
            "decision": decision,
            "message": f"Design decision: {decision.get('question', 'unknown')}"
        }
    )


async def send_code_generated(
    session_id: str,
    component_id: str,
    artifact: Dict[str, Any]
):
    """
    Send code generation event

    Args:
        session_id: Generation session ID
        component_id: Component ID
        artifact: Code artifact data
    """
    await send_generation_event(
        session_id=session_id,
        event_type="code_generated",
        data={
            "component_id": component_id,
            "artifact": artifact,
            "message": f"Generated: {artifact.get('file_path', 'unknown')}"
        }
    )


async def send_relationship_added(
    session_id: str,
    relationship: Dict[str, Any]
):
    """
    Send relationship creation event

    Args:
        session_id: Generation session ID
        relationship: Relationship data
    """
    await send_generation_event(
        session_id=session_id,
        event_type="relationship_added",
        data={
            "relationship": relationship,
            "message": f"Added relationship: {relationship.get('source_name', '')} -> {relationship.get('target_name', '')}"
        }
    )


async def send_validation_request(
    session_id: str,
    artifact_type: str,
    artifact_id: str,
    ai_proposal: str
):
    """
    Send validation request to user

    Args:
        session_id: Generation session ID
        artifact_type: Type of artifact
        artifact_id: Artifact ID
        ai_proposal: AI's proposed solution
    """
    await send_generation_event(
        session_id=session_id,
        event_type="validation_request",
        data={
            "artifact_type": artifact_type,
            "artifact_id": artifact_id,
            "ai_proposal": ai_proposal,
            "message": f"Please validate: {artifact_type}"
        },
        status="waiting"
    )


async def send_progress_update(
    session_id: str,
    stage: str,
    progress: float,
    message: str
):
    """
    Send progress update

    Args:
        session_id: Generation session ID
        stage: Current stage (architecture, design, code, verification)
        progress: Progress percentage (0.0 - 1.0)
        message: Progress message
    """
    await send_generation_event(
        session_id=session_id,
        event_type="progress",
        data={
            "stage": stage,
            "progress": progress,
            "message": message
        }
    )


async def send_error(
    session_id: str,
    error_type: str,
    error_message: str,
    details: Optional[Dict[str, Any]] = None
):
    """
    Send error event

    Args:
        session_id: Generation session ID
        error_type: Error type
        error_message: Error message
        details: Additional error details
    """
    await send_generation_event(
        session_id=session_id,
        event_type="error",
        data={
            "error_type": error_type,
            "error_message": error_message,
            "details": details or {}
        },
        status="error"
    )


async def send_generation_complete(
    session_id: str,
    summary: Dict[str, Any]
):
    """
    Send generation complete event

    Args:
        session_id: Generation session ID
        summary: Generation summary
    """
    await send_generation_event(
        session_id=session_id,
        event_type="generation_complete",
        data={
            "summary": summary,
            "message": "Generation completed successfully"
        },
        status="completed"
    )


# WebSocket endpoint handler
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for real-time generation updates

    Args:
        websocket: WebSocket connection
        session_id: Generation session ID
    """
    await manager.connect(websocket, session_id)

    try:
        # Send connection confirmation
        await websocket.send_json({
            "type": "connected",
            "session_id": session_id,
            "message": "Connected to ClarAIty generation stream",
            "timestamp": datetime.utcnow().isoformat()
        })

        # Keep connection alive and listen for client messages
        while True:
            # Wait for client messages
            data = await websocket.receive_text()

            # Parse message
            try:
                message = json.loads(data)
                message_type = message.get('type')

                # Handle different message types
                if message_type == 'ping':
                    # Respond to ping
                    await websocket.send_json({
                        "type": "pong",
                        "timestamp": datetime.utcnow().isoformat()
                    })

                elif message_type == 'validation_response':
                    # Handle user validation response
                    # This would trigger continuation of generation
                    await websocket.send_json({
                        "type": "validation_received",
                        "message": "Validation response received",
                        "timestamp": datetime.utcnow().isoformat()
                    })

                else:
                    # Unknown message type
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Unknown message type: {message_type}",
                        "timestamp": datetime.utcnow().isoformat()
                    })

            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "message": "Invalid JSON",
                    "timestamp": datetime.utcnow().isoformat()
                })

    except WebSocketDisconnect:
        manager.disconnect(websocket, session_id)

    except Exception as e:
        manager.disconnect(websocket, session_id)
        print(f"WebSocket error: {e}")
