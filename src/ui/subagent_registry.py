"""SubagentRegistry - bridges subagent execution with TUI visibility.

The registry tracks running subagents and forwards events to the TUI via callbacks.

Two modes of operation:
1. In-process (CLI/legacy): register() with a shared MessageStore, registry
   subscribes to store notifications and forwards them via call_from_thread.
2. Subprocess (TUI): register() with store=None, delegation tool calls
   push_notification() directly from the event loop (no call_from_thread needed).

Lifecycle:
1. DelegationTool calls register() when a subagent starts
2. For in-process: registry subscribes to store, forwarding notifications
   For subprocess: delegation tool calls push_notification() with IPC events
3. TUI receives on_registered callback and mounts SubAgentCard
4. Live notifications flow through on_notification callbacks
5. DelegationTool calls unregister() when subagent completes
6. Registry cleans up, TUI receives on_unregistered
"""

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING
import threading

from src.observability import get_logger

if TYPE_CHECKING:
    from src.session.store.memory_store import MessageStore, StoreNotification

logger = get_logger("ui.subagent_registry")

# Type aliases for callback signatures
# (subagent_id, store, transcript_path, parent_tool_call_id, model_name, subagent_name)
# store may be None in subprocess mode
RegisteredCallback = Callable[[str, Optional["MessageStore"], Path, str, str, str], None]
UnregisteredCallback = Callable[[str], None]
NotificationCallback = Callable[[str, "StoreNotification"], None]


class SubagentRegistry:
    """Registry tracking running subagents for TUI visibility.

    Thread-safe: register/unregister may be called from worker threads
    (in-process mode) or from the event loop (subprocess mode).
    """

    def __init__(self, app: Any = None):
        """Initialize the registry.

        Args:
            app: Reference to the AgentApp (used for call_from_thread
                 to dispatch callbacks onto the Textual event loop).
        """
        self._app = app
        self._lock = threading.Lock()

        # Active subagent instances: subagent_id -> instance
        # In subprocess mode, instance is asyncio.Process (has .terminate())
        # In in-process mode, instance is SubAgent (has .cancel())
        self._instances: Dict[str, Any] = {}

        # Store unsubscribe handles: subagent_id -> unsubscribe callable
        self._store_unsubscribes: Dict[str, Callable] = {}

        # Track which subagents are subprocess-based (no call_from_thread needed)
        self._subprocess_ids: set = set()

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
                      parent_tool_call_id, model_name, subagent_name) when a subagent registers.
                      store may be None for subprocess-based subagents.

        Returns:
            Unsubscribe callable.
        """
        with self._lock:
            self._on_registered.append(callback)

        def _unsub():
            with self._lock:
                if callback in self._on_registered:
                    self._on_registered.remove(callback)

        return _unsub

    def subscribe_on_unregistered(self, callback: UnregisteredCallback) -> Callable:
        """Subscribe to subagent unregistration events.

        Returns:
            Unsubscribe callable.
        """
        with self._lock:
            self._on_unregistered.append(callback)

        def _unsub():
            with self._lock:
                if callback in self._on_unregistered:
                    self._on_unregistered.remove(callback)

        return _unsub

    def subscribe_on_notification(self, callback: NotificationCallback) -> Callable:
        """Subscribe to store notifications from all subagents.

        Returns:
            Unsubscribe callable.
        """
        with self._lock:
            self._on_notification.append(callback)

        def _unsub():
            with self._lock:
                if callback in self._on_notification:
                    self._on_notification.remove(callback)

        return _unsub

    # -------------------------------------------------------------------------
    # Registration API
    # -------------------------------------------------------------------------

    def register(
        self,
        subagent_id: str,
        store: Optional["MessageStore"],
        transcript_path: Path,
        parent_tool_call_id: str,
        instance: Any = None,
        model_name: str = "",
        subagent_name: str = "",
    ) -> None:
        """Register a running subagent for TUI visibility.

        Args:
            subagent_id: Unique subagent session ID
            store: The subagent's MessageStore (None for subprocess mode)
            transcript_path: Path to the subagent's JSONL transcript
            parent_tool_call_id: Tool call ID of the delegation call
            instance: SubAgent instance (in-process) or asyncio.Process (subprocess)
            model_name: LLM model name used by this subagent
            subagent_name: Subagent type/name (e.g., "knowledge-builder", "planner")
        """
        is_subprocess = (store is None)

        with self._lock:
            self._instances[subagent_id] = instance

            if is_subprocess:
                self._subprocess_ids.add(subagent_id)
            elif hasattr(store, 'subscribe'):
                # In-process mode: subscribe to store for live notifications
                unsub = store.subscribe(
                    lambda notification, sid=subagent_id: self._on_store_notification(sid, notification)
                )
                self._store_unsubscribes[subagent_id] = unsub

        logger.info(
            f"Registered subagent {subagent_id} "
            f"(name={subagent_name}, parent_tool_call_id={parent_tool_call_id}, model={model_name}, "
            f"mode={'subprocess' if is_subprocess else 'in-process'})"
        )

        # Dispatch to subscribers (snapshot under lock, invoke outside lock)
        with self._lock:
            callbacks = list(self._on_registered)

        if is_subprocess:
            # Subprocess: caller is already on event loop, dispatch directly
            for callback in callbacks:
                try:
                    callback(subagent_id, store, transcript_path, parent_tool_call_id, model_name, subagent_name)
                except Exception as e:
                    logger.error(f"Error in registered callback: {e}")
        else:
            # In-process: use call_from_thread to get onto event loop
            self._dispatch_registered(subagent_id, store, transcript_path, parent_tool_call_id, model_name, subagent_name)

    def unregister(self, subagent_id: str) -> None:
        """Unregister a completed subagent.

        Unsubscribes from the store (if in-process) and notifies callbacks.
        """
        is_subprocess = False
        with self._lock:
            self._instances.pop(subagent_id, None)
            is_subprocess = subagent_id in self._subprocess_ids
            self._subprocess_ids.discard(subagent_id)

            # Unsubscribe from the store (in-process mode only)
            unsub = self._store_unsubscribes.pop(subagent_id, None)
            if unsub:
                try:
                    unsub()
                except Exception as e:
                    logger.warning(f"Error unsubscribing from store: {e}")

        logger.info(f"Unregistered subagent {subagent_id}")

        # Dispatch to subscribers (snapshot under lock, invoke outside lock)
        with self._lock:
            callbacks = list(self._on_unregistered)

        if is_subprocess:
            # Already on event loop
            for callback in callbacks:
                try:
                    callback(subagent_id)
                except Exception as e:
                    logger.error(f"Error in unregistered callback: {e}")
        else:
            self._dispatch_unregistered(subagent_id)

    def push_notification(self, subagent_id: str, notification: "StoreNotification") -> None:
        """Forward an IPC notification to TUI callbacks.

        Called by the delegation tool's execute_async() which runs on the
        event loop. No call_from_thread needed - we're already on the loop.

        Args:
            subagent_id: The subagent that emitted this notification
            notification: Deserialized StoreNotification from IPC
        """
        with self._lock:
            callbacks = list(self._on_notification)
        for callback in callbacks:
            try:
                callback(subagent_id, notification)
            except Exception as e:
                logger.error(f"Error in push_notification callback: {e}")

    def get_instance(self, subagent_id: str) -> Any:
        """Get a subagent instance by ID.

        Returns SubAgent (has .cancel()) or asyncio.Process (has .terminate()).
        """
        with self._lock:
            return self._instances.get(subagent_id)

    def cancel(self, subagent_id: str) -> None:
        """Cancel a running subagent.

        Handles both in-process (SubAgent.cancel()) and subprocess
        (asyncio.Process.terminate()) modes.
        """
        with self._lock:
            inst = self._instances.get(subagent_id)
            is_subprocess = subagent_id in self._subprocess_ids

        if inst is None:
            return

        if is_subprocess and hasattr(inst, 'terminate'):
            logger.info(f"Terminating subprocess subagent {subagent_id}")
            inst.terminate()
        elif hasattr(inst, 'cancel'):
            logger.info(f"Cancelling in-process subagent {subagent_id}")
            inst.cancel()

    # -------------------------------------------------------------------------
    # Internal dispatch (in-process mode, uses call_from_thread)
    # -------------------------------------------------------------------------

    def _on_store_notification(self, subagent_id: str, notification: "StoreNotification") -> None:
        """Handle a store notification from an in-process subagent.

        Forwards to all notification subscribers, dispatching on the
        TUI event loop if an app reference is available.
        """
        with self._lock:
            callbacks = list(self._on_notification)
        for callback in callbacks:
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
        store: Optional["MessageStore"],
        transcript_path: Path,
        parent_tool_call_id: str,
        model_name: str = "",
        subagent_name: str = "",
    ) -> None:
        """Dispatch registration event to subscribers (in-process mode)."""
        with self._lock:
            callbacks = list(self._on_registered)
        for callback in callbacks:
            try:
                if self._app and hasattr(self._app, 'call_from_thread'):
                    self._app.call_from_thread(
                        callback, subagent_id, store, transcript_path, parent_tool_call_id, model_name, subagent_name
                    )
                else:
                    callback(subagent_id, store, transcript_path, parent_tool_call_id, model_name, subagent_name)
            except Exception as e:
                logger.error(f"Error in registered callback: {e}")

    def _dispatch_unregistered(self, subagent_id: str) -> None:
        """Dispatch unregistration event to subscribers (in-process mode)."""
        with self._lock:
            callbacks = list(self._on_unregistered)
        for callback in callbacks:
            try:
                if self._app and hasattr(self._app, 'call_from_thread'):
                    self._app.call_from_thread(callback, subagent_id)
                else:
                    callback(subagent_id)
            except Exception as e:
                logger.error(f"Error in unregistered callback: {e}")
