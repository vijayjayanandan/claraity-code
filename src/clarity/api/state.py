"""
Blueprint State Manager

Manages in-memory state for the current blueprint and notifies WebSocket clients
of state changes.
"""

import asyncio
import logging
from typing import Optional, Dict, Any
from datetime import datetime
import uuid

from ..core.blueprint import Blueprint
from .websocket import manager as ws_manager

logger = logging.getLogger(__name__)


class BlueprintState:
    """Represents the current state of a blueprint."""

    def __init__(self, blueprint: Blueprint, session_id: str):
        self.blueprint = blueprint
        self.session_id = session_id
        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()
        self.status = "pending"  # pending, approved, rejected, generating
        self.feedback: Optional[str] = None


class BlueprintStateManager:
    """
    Manage blueprint state and lifecycle.

    Handles blueprint creation, approval, rejection, and broadcasts
    state changes via WebSocket.
    """

    def __init__(self):
        """Initialize state manager."""
        self.current_state: Optional[BlueprintState] = None
        self._lock = asyncio.Lock()

    async def set_blueprint(
        self,
        blueprint: Blueprint,
        session_id: Optional[str] = None
    ) -> str:
        """
        Set the current blueprint.

        Args:
            blueprint: Blueprint object
            session_id: Optional session ID (generates new one if not provided)

        Returns:
            Session ID
        """
        async with self._lock:
            if session_id is None:
                session_id = str(uuid.uuid4())

            self.current_state = BlueprintState(blueprint, session_id)
            logger.info(f"Blueprint set for session {session_id}")

            # Notify WebSocket clients
            await self._notify_clients({
                "type": "blueprint_updated",
                "status": "pending",
                "data": blueprint.to_dict(),
                "session_id": session_id,
            })

            return session_id

    async def get_blueprint(self) -> Optional[Blueprint]:
        """
        Get the current blueprint.

        Returns:
            Current blueprint or None
        """
        if self.current_state:
            return self.current_state.blueprint
        return None

    async def get_state(self) -> Optional[Dict[str, Any]]:
        """
        Get the current state.

        Returns:
            State dictionary or None
        """
        if not self.current_state:
            return None

        return {
            "blueprint": self.current_state.blueprint.to_dict(),
            "session_id": self.current_state.session_id,
            "created_at": self.current_state.created_at.isoformat(),
            "updated_at": self.current_state.updated_at.isoformat(),
            "status": self.current_state.status,
            "feedback": self.current_state.feedback,
        }

    async def approve(self) -> bool:
        """
        Approve the current blueprint.

        Returns:
            True if approved successfully, False if no blueprint exists
        """
        async with self._lock:
            if not self.current_state:
                logger.warning("Attempt to approve but no blueprint exists")
                return False

            self.current_state.status = "approved"
            self.current_state.updated_at = datetime.utcnow()
            logger.info(f"Blueprint approved for session {self.current_state.session_id}")

            # Notify WebSocket clients
            await self._notify_clients({
                "type": "blueprint_approved",
                "status": "approved",
                "session_id": self.current_state.session_id,
                "message": "Blueprint approved - ready for code generation"
            })

            return True

    async def reject(self, feedback: Optional[str] = None) -> bool:
        """
        Reject the current blueprint.

        Args:
            feedback: Optional feedback explaining rejection

        Returns:
            True if rejected successfully, False if no blueprint exists
        """
        async with self._lock:
            if not self.current_state:
                logger.warning("Attempt to reject but no blueprint exists")
                return False

            self.current_state.status = "rejected"
            self.current_state.feedback = feedback
            self.current_state.updated_at = datetime.utcnow()
            logger.info(
                f"Blueprint rejected for session {self.current_state.session_id}"
                f"{f' with feedback: {feedback}' if feedback else ''}"
            )

            # Notify WebSocket clients
            await self._notify_clients({
                "type": "blueprint_rejected",
                "status": "rejected",
                "session_id": self.current_state.session_id,
                "feedback": feedback,
                "message": "Blueprint rejected - refinement needed"
            })

            return True

    async def set_status(self, status: str) -> bool:
        """
        Set the current status.

        Args:
            status: New status (pending, approved, rejected, generating, complete, error)

        Returns:
            True if set successfully, False if no blueprint exists
        """
        async with self._lock:
            if not self.current_state:
                return False

            old_status = self.current_state.status
            self.current_state.status = status
            self.current_state.updated_at = datetime.utcnow()
            logger.info(
                f"Status changed from {old_status} to {status} "
                f"for session {self.current_state.session_id}"
            )

            # Notify WebSocket clients
            await self._notify_clients({
                "type": "status_changed",
                "status": status,
                "old_status": old_status,
                "session_id": self.current_state.session_id,
            })

            return True

    async def clear(self):
        """Clear the current blueprint state."""
        async with self._lock:
            if self.current_state:
                session_id = self.current_state.session_id
                self.current_state = None
                logger.info(f"Cleared blueprint state for session {session_id}")

                # Notify WebSocket clients
                await self._notify_clients({
                    "type": "blueprint_cleared",
                    "session_id": session_id,
                })

    async def _notify_clients(self, message: Dict[str, Any]):
        """
        Notify WebSocket clients of state changes.

        Args:
            message: Message to broadcast
        """
        try:
            await ws_manager.broadcast(message)
        except Exception as e:
            logger.error(f"Failed to notify WebSocket clients: {e}")


# Global state manager instance
state_manager = BlueprintStateManager()
