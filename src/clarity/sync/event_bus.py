"""
Event Bus for ClarAIty

Provides publish-subscribe pattern for loose coupling between components.
All ClarAIty components communicate via events.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Callable, Any, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """Standard event types in ClarAIty."""

    # Blueprint events
    BLUEPRINT_GENERATED = "blueprint_generated"
    BLUEPRINT_APPROVED = "blueprint_approved"
    BLUEPRINT_REJECTED = "blueprint_rejected"
    BLUEPRINT_CLEARED = "blueprint_cleared"

    # File system events
    FILE_CHANGED = "file_changed"
    FILE_CREATED = "file_created"
    FILE_DELETED = "file_deleted"
    FILES_BATCH_CHANGED = "files_batch_changed"

    # Component events
    COMPONENT_ADDED = "component_added"
    COMPONENT_UPDATED = "component_updated"
    COMPONENT_DELETED = "component_deleted"

    # Relationship events
    RELATIONSHIP_ADDED = "relationship_added"
    RELATIONSHIP_REMOVED = "relationship_removed"

    # Sync events
    SYNC_STARTED = "sync_started"
    SYNC_COMPLETED = "sync_completed"
    SYNC_FAILED = "sync_failed"

    # Scan events
    SCAN_STARTED = "scan_started"
    SCAN_PROGRESS = "scan_progress"
    SCAN_COMPLETED = "scan_completed"

    # Generation events
    GENERATION_STARTED = "generation_started"
    GENERATION_PROGRESS = "generation_progress"
    GENERATION_COMPLETED = "generation_completed"
    GENERATION_FAILED = "generation_failed"

    # System events
    STATUS_CHANGED = "status_changed"
    ERROR_OCCURRED = "error_occurred"


@dataclass
class ClarityEvent:
    """
    Base event class for ClarAIty system.

    All events have a type, source, timestamp, and arbitrary data payload.
    """
    type: str  # EventType or custom string
    source: str  # Component that emitted the event
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    event_id: Optional[str] = None  # Optional unique ID

    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary for serialization."""
        return {
            'type': self.type,
            'source': self.source,
            'data': self.data,
            'timestamp': self.timestamp.isoformat(),
            'event_id': self.event_id,
        }


class EventBus:
    """
    Central event bus for publish-subscribe messaging.

    Features:
    - Async event handling (non-blocking)
    - Multiple subscribers per event type
    - Error isolation (one handler failure doesn't affect others)
    - Event history (optional, for debugging)
    """

    def __init__(self, keep_history: bool = False, history_size: int = 1000):
        """
        Initialize event bus.

        Args:
            keep_history: Whether to keep event history
            history_size: Maximum events to keep in history
        """
        self._subscribers: Dict[str, List[Callable]] = {}
        self._wildcard_subscribers: List[Callable] = []  # Subscribe to all events
        self._lock = asyncio.Lock()

        # Optional event history for debugging
        self._keep_history = keep_history
        self._history_size = history_size
        self._history: List[ClarityEvent] = []

        logger.info("EventBus initialized")

    def subscribe(self, event_type: str, handler: Callable[[ClarityEvent], Any]):
        """
        Subscribe to an event type.

        Args:
            event_type: Event type to subscribe to (or "*" for all events)
            handler: Async or sync callable that receives ClarityEvent
        """
        if event_type == "*":
            self._wildcard_subscribers.append(handler)
            logger.debug(f"Subscribed to all events: {handler.__name__}")
        else:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []
            self._subscribers[event_type].append(handler)
            logger.debug(f"Subscribed to {event_type}: {handler.__name__}")

    def unsubscribe(self, event_type: str, handler: Callable):
        """
        Unsubscribe from an event type.

        Args:
            event_type: Event type to unsubscribe from
            handler: Handler to remove
        """
        if event_type == "*":
            if handler in self._wildcard_subscribers:
                self._wildcard_subscribers.remove(handler)
                logger.debug(f"Unsubscribed from all events: {handler.__name__}")
        else:
            if event_type in self._subscribers and handler in self._subscribers[event_type]:
                self._subscribers[event_type].remove(handler)
                logger.debug(f"Unsubscribed from {event_type}: {handler.__name__}")

    async def publish(self, event: ClarityEvent):
        """
        Publish an event to all subscribers.

        Args:
            event: Event to publish
        """
        # Add to history
        if self._keep_history:
            async with self._lock:
                self._history.append(event)
                if len(self._history) > self._history_size:
                    self._history.pop(0)

        # Get subscribers
        handlers = self._subscribers.get(event.type, []).copy()
        handlers.extend(self._wildcard_subscribers)

        if not handlers:
            logger.debug(f"No subscribers for event: {event.type}")
            return

        logger.debug(f"Publishing event {event.type} to {len(handlers)} handlers")

        # Call handlers (async and sync)
        tasks = []
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    tasks.append(handler(event))
                else:
                    # Sync handler - run in executor to avoid blocking
                    loop = asyncio.get_event_loop()
                    tasks.append(loop.run_in_executor(None, handler, event))
            except Exception as e:
                logger.error(f"Error preparing handler {handler.__name__}: {e}", exc_info=True)

        # Wait for all handlers (with error isolation)
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Log any errors
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    handler_name = handlers[i].__name__ if i < len(handlers) else "unknown"
                    logger.error(
                        f"Handler {handler_name} failed for event {event.type}: {result}",
                        exc_info=result
                    )

    def publish_sync(self, event: ClarityEvent):
        """
        Synchronous publish (creates task but doesn't wait).

        Use this when you need to publish but can't await.

        Args:
            event: Event to publish
        """
        try:
            loop = asyncio.get_event_loop()
            asyncio.create_task(self.publish(event))
        except RuntimeError:
            # No event loop - create one
            asyncio.run(self.publish(event))

    def get_history(self, event_type: Optional[str] = None, limit: int = 100) -> List[ClarityEvent]:
        """
        Get event history.

        Args:
            event_type: Filter by event type (None = all)
            limit: Maximum events to return

        Returns:
            List of events (most recent first)
        """
        if not self._keep_history:
            return []

        history = self._history.copy()

        # Filter by type
        if event_type:
            history = [e for e in history if e.type == event_type]

        # Reverse (most recent first) and limit
        return list(reversed(history))[:limit]

    def clear_history(self):
        """Clear event history."""
        self._history.clear()
        logger.debug("Event history cleared")

    def get_subscriber_count(self, event_type: Optional[str] = None) -> int:
        """
        Get number of subscribers.

        Args:
            event_type: Specific event type (None = total across all types)

        Returns:
            Number of subscribers
        """
        if event_type:
            return len(self._subscribers.get(event_type, []))
        else:
            return sum(len(handlers) for handlers in self._subscribers.values()) + len(self._wildcard_subscribers)


# Global event bus instance
event_bus = EventBus(keep_history=True)


# Convenience functions for common events

async def emit_file_changed(file_path: str, change_type: str = "modified", source: str = "file_watcher"):
    """Emit file changed event."""
    await event_bus.publish(ClarityEvent(
        type=EventType.FILE_CHANGED,
        source=source,
        data={
            'file_path': file_path,
            'change_type': change_type,
        }
    ))


async def emit_component_added(component_id: int, component_name: str, source: str = "analyzer"):
    """Emit component added event."""
    await event_bus.publish(ClarityEvent(
        type=EventType.COMPONENT_ADDED,
        source=source,
        data={
            'component_id': component_id,
            'component_name': component_name,
        }
    ))


async def emit_sync_started(scope: str, file_count: int, source: str = "sync_orchestrator"):
    """Emit sync started event."""
    await event_bus.publish(ClarityEvent(
        type=EventType.SYNC_STARTED,
        source=source,
        data={
            'scope': scope,
            'file_count': file_count,
        }
    ))


async def emit_sync_completed(stats: Dict[str, Any], source: str = "sync_orchestrator"):
    """Emit sync completed event."""
    await event_bus.publish(ClarityEvent(
        type=EventType.SYNC_COMPLETED,
        source=source,
        data={'stats': stats}
    ))


async def emit_error(error_type: str, error_message: str, details: Optional[Dict] = None, source: str = "system"):
    """Emit error event."""
    await event_bus.publish(ClarityEvent(
        type=EventType.ERROR_OCCURRED,
        source=source,
        data={
            'error_type': error_type,
            'error_message': error_message,
            'details': details or {},
        }
    ))
