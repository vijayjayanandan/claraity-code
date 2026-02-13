"""SubagentRegistry - bridges subagent execution with TUI visibility.

The registry tracks running subagents, subscribes to their MessageStores,
and forwards events to the TUI via callbacks. It acts as the bridge between
the agent execution thread (where subagents run) and the Textual event loop
(where the UI renders).

Lifecycle:
1. DelegationTool calls register() when a subagent starts
2. Registry subscribes to the subagent's store, forwarding notifications
3. TUI receives on_registered callback and mounts SubAgentCard
4. Live store notifications flow through on_notification callbacks
5. DelegationTool calls unregister() when subagent completes
6. Registry unsubscribes from store, TUI receives on_unregistered
"""

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING
import threading

from src.observability import get_logger

if TYPE_CHECKING:
    from src.session.store.memory_store import MessageStore, StoreNotification

logger = get_logger("ui.subagent_registry")

# Type aliases for callback signatures
# (subagent_id, store, transcript_path, parent_tool_call_id, model_name)
RegisteredCallback = Callable[[str, "MessageStore", Path, str, str], None]
UnregisteredCallback = Callable[[str], None]
NotificationCallback = Callable[[str, "StoreNotification"], None]


class SubagentRegistry:
    """Registry tracking running subagents for TUI visibility.

    Thread-safe: register/unregister are called from worker threads,
    while subscribe callbacks run on the caller's thread (typically the
    Textual event loop via call_from_thread).
    """

    def __init__(self, app: Any = None):
        """Initialize the registry.

        Args:
            app: Reference to the AgentApp (used for call_from_thread
                 to dispatch callbacks onto the Textual event loop).
        """
        self._app = app
        self._lock = threading.Lock()

        # Active subagent instances: subagent_id -> instance (has .cancel())
        self._instances: Dict[str, Any] = {}

        # Store unsubscribe handles: subagent_id -> unsubscribe callable
        self._store_unsubscribes: Dict[str, Callable] = {}

        # Subscriber callbacks
        self._on_registered: List[RegisteredCallback] = []
        self._on_unregistered: List[UnregisteredCallback] = []
        self._on_notification: List[NotificationCallback] = []

    # -------------------------------------------------------------------------
    # Subscription API (called by TUI on event loop)
    # -------------------------------------------------------------------------

    def subscribe_on_registered(self, callback: RegisteredCallback) -> Callable:
        """Subscribe to subagent registration events.

        Args:
            callback: Called with (subagent_id, store, transcript_path,
                      parent_tool_call_id) when a subagent registers.

        Returns:
            Unsubscribe callable.
        """
        self._on_registered.append(callback)
        return lambda: self._on_registered.remove(callback) if callback in self._on_registered else None

    def subscribe_on_unregistered(self, callback: UnregisteredCallback) -> Callable:
        """Subscribe to subagent unregistration events.

        Args:
            callback: Called with (subagent_id) when a subagent completes.

        Returns:
            Unsubscribe callable.
        """
        self._on_unregistered.append(callback)
        return lambda: self._on_unregistered.remove(callback) if callback in self._on_unregistered else None

    def subscribe_on_notification(self, callback: NotificationCallback) -> Callable:
        """Subscribe to store notifications from all subagents.

        Args:
            callback: Called with (subagent_id, notification) for every
                      store event from any registered subagent.

        Returns:
            Unsubscribe callable.
        """
        self._on_notification.append(callback)
        return lambda: self._on_notification.remove(callback) if callback in self._on_notification else None

    # -------------------------------------------------------------------------
    # Registration API (called from worker threads)
    # -------------------------------------------------------------------------

    def register(
        self,
        subagent_id: str,
        store: "MessageStore",
        transcript_path: Path,
        parent_tool_call_id: str,
        instance: Any = None,
        model_name: str = "",
    ) -> None:
        """Register a running subagent for TUI visibility.

        Subscribes to the subagent's MessageStore for live updates and
        notifies all registered callbacks.

        Args:
            subagent_id: Unique subagent session ID
            store: The subagent's MessageStore
            transcript_path: Path to the subagent's JSONL transcript
            parent_tool_call_id: Tool call ID of the delegation call
            instance: The SubAgent instance (for cancellation via .cancel())
            model_name: LLM model name used by this subagent
        """
        with self._lock:
            self._instances[subagent_id] = instance

            # Subscribe to the subagent's store for live notifications
            if hasattr(store, 'subscribe'):
                unsub = store.subscribe(
                    lambda notification, sid=subagent_id: self._on_store_notification(sid, notification)
                )
                self._store_unsubscribes[subagent_id] = unsub

        logger.info(
            f"Registered subagent {subagent_id} "
            f"(parent_tool_call_id={parent_tool_call_id}, model={model_name})"
        )

        # Dispatch to subscribers (on TUI event loop if app available)
        self._dispatch_registered(subagent_id, store, transcript_path, parent_tool_call_id, model_name)

    def unregister(self, subagent_id: str) -> None:
        """Unregister a completed subagent.

        Unsubscribes from the store and notifies callbacks.

        Args:
            subagent_id: The subagent session ID to remove
        """
        with self._lock:
            self._instances.pop(subagent_id, None)

            # Unsubscribe from the store
            unsub = self._store_unsubscribes.pop(subagent_id, None)
            if unsub:
                try:
                    unsub()
                except Exception as e:
                    logger.warning(f"Error unsubscribing from store: {e}")

        logger.info(f"Unregistered subagent {subagent_id}")

        # Dispatch to subscribers
        self._dispatch_unregistered(subagent_id)

    def get_instance(self, subagent_id: str) -> Any:
        """Get a subagent instance by ID.

        Used for cancellation (instance.cancel()).

        Args:
            subagent_id: The subagent session ID

        Returns:
            The SubAgent instance, or None if not found
        """
        with self._lock:
            return self._instances.get(subagent_id)

    # -------------------------------------------------------------------------
    # Internal dispatch
    # -------------------------------------------------------------------------

    def _on_store_notification(self, subagent_id: str, notification: "StoreNotification") -> None:
        """Handle a store notification from a subagent.

        Forwards to all notification subscribers, dispatching on the
        TUI event loop if an app reference is available.
        """
        for callback in list(self._on_notification):
            try:
                if self._app and hasattr(self._app, 'call_from_thread'):
                    self._app.call_from_thread(callback, subagent_id, notification)
                else:
                    callback(subagent_id, notification)
            except Exception as e:
                logger.error(f"Error in notification callback: {e}")

    def _dispatch_registered(
        self,
        subagent_id: str,
        store: "MessageStore",
        transcript_path: Path,
        parent_tool_call_id: str,
        model_name: str = "",
    ) -> None:
        """Dispatch registration event to subscribers."""
        for callback in list(self._on_registered):
            try:
                if self._app and hasattr(self._app, 'call_from_thread'):
                    self._app.call_from_thread(
                        callback, subagent_id, store, transcript_path, parent_tool_call_id, model_name
                    )
                else:
                    callback(subagent_id, store, transcript_path, parent_tool_call_id, model_name)
            except Exception as e:
                logger.error(f"Error in registered callback: {e}")

    def _dispatch_unregistered(self, subagent_id: str) -> None:
        """Dispatch unregistration event to subscribers."""
        for callback in list(self._on_unregistered):
            try:
                if self._app and hasattr(self._app, 'call_from_thread'):
                    self._app.call_from_thread(callback, subagent_id)
                else:
                    callback(subagent_id)
            except Exception as e:
                logger.error(f"Error in unregistered callback: {e}")
