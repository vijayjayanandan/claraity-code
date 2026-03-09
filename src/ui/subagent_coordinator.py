"""
Subagent lifecycle coordinator for the TUI.

Manages subagent registration, unregistration, card mounting, notification
routing, and pending mount queues. Works with SubagentRegistry and SubAgentCard
widgets to provide live subagent visibility in the TUI.
"""

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from src.observability import get_logger

logger = get_logger(__name__)

if TYPE_CHECKING:
    from ..session.store.memory_store import StoreNotification
    from .protocol import UIProtocol
    from .subagent_registry import SubagentRegistry
    from .widgets.subagent_card import SubAgentCard
    from .widgets.tool_card import ToolCard


class SubagentCoordinator:
    """Manages subagent lifecycle: registration, card mounting, notifications.

    Keeps its own subscription/buffering dicts and exposes methods that the
    app calls from Textual event handlers. Card mounting is deferred via
    a ``mount_callback`` since it requires Textual DOM access.

    Args:
        tool_cards: Shared dict mapping tool_call_id -> ToolCard (app owns this)
        mount_callback: Callable(coroutine, *args) for scheduling widget mount
                       via Textual's call_later().
    """

    def __init__(
        self,
        tool_cards: dict,
        mount_callback: Callable,
    ):
        self._tool_cards = tool_cards
        self._mount_callback = mount_callback

        # Subagent tracking state
        self._subagent_subscriptions: dict[str, dict] = {}
        self._pending_subagent_mounts: dict[str, dict] = {}
        self._buffered_subagent_notifications: dict[str, list] = {}

        # Registry unsubscribe handles
        self._unsubscribe_registry_reg: Callable[[], None] | None = None
        self._unsubscribe_registry_unreg: Callable[[], None] | None = None
        self._unsubscribe_registry_notif: Callable[[], None] | None = None

    @property
    def subscriptions(self) -> dict[str, dict]:
        """Active subagent subscriptions."""
        return self._subagent_subscriptions

    def setup_registry(
        self,
        registry: "SubagentRegistry",
        agent: Any,
        ui_protocol: "UIProtocol",
        pause_callback: Callable,
    ) -> None:
        """Subscribe to registry events and wire to delegation tool.

        Args:
            registry: SubagentRegistry instance
            agent: CodingAgent instance (for delegation tool wiring)
            ui_protocol: UIProtocol instance
            pause_callback: Callback for subagent pause requests
        """
        self._unsubscribe_registry_reg = registry.subscribe_on_registered(
            self.on_subagent_registered
        )
        self._unsubscribe_registry_unreg = registry.subscribe_on_unregistered(
            self.on_subagent_unregistered
        )
        self._unsubscribe_registry_notif = registry.subscribe_on_notification(
            self.handle_subagent_notification
        )
        logger.info("Subscribed to SubagentRegistry events")

        # Wire registry to delegation tool on agent
        if agent:
            delegation_tool = agent.tool_executor.tools.get("delegate_to_subagent")
            if delegation_tool and hasattr(delegation_tool, "set_registry"):
                delegation_tool.set_registry(registry)
                delegation_tool.set_ui_protocol(ui_protocol)
                ui_protocol.set_pause_requested_callback(pause_callback)
                logger.info(
                    "Wired SubagentRegistry, UIProtocol, and pause callback to delegation tool"
                )
            else:
                logger.warning(
                    "delegate_to_subagent tool not found or missing set_registry - "
                    f"tools: {list(agent.tool_executor.tools.keys())}"
                )

    def cleanup(self) -> None:
        """Unsubscribe from all registry events and subagent stores."""
        if self._unsubscribe_registry_reg:
            self._unsubscribe_registry_reg()
        if self._unsubscribe_registry_unreg:
            self._unsubscribe_registry_unreg()
        if self._unsubscribe_registry_notif:
            self._unsubscribe_registry_notif()

        for _sub_id, sub_info in self._subagent_subscriptions.items():
            if sub_info.get("unsubscribe"):
                sub_info["unsubscribe"]()

    def on_subagent_registered(
        self,
        subagent_id: str,
        store: Any,
        transcript_path: Path,
        parent_tool_call_id: str,
        model_name: str = "",
        subagent_name: str = "",
    ) -> None:
        """Handle subagent registration.

        Args:
            subagent_id: Unique ID of the subagent session
            store: The subagent's MessageStore (may be None for subprocess mode)
            transcript_path: Path to the subagent's JSONL transcript
            parent_tool_call_id: Tool call ID of the spawning delegation call
            model_name: LLM model name used by this subagent
            subagent_name: Subagent type/name
        """
        logger.info(
            f"TUI: Subagent registered: {subagent_id}, "
            f"parent_tool_call_id={parent_tool_call_id}, model={model_name}, "
            f"mode={'subprocess' if store is None else 'in-process'}"
        )

        self._subagent_subscriptions[subagent_id] = {
            "card": None,
            "transcript_path": transcript_path,
            "parent_tool_call_id": parent_tool_call_id,
            "store": store,
            "model_name": model_name,
            "subagent_name": subagent_name,
        }

        self.try_mount_subagent_card(
            subagent_id, transcript_path, parent_tool_call_id, model_name, subagent_name
        )

    def on_subagent_unregistered(self, subagent_id: str) -> None:
        """Handle subagent completion.

        Args:
            subagent_id: The subagent session ID that completed
        """
        logger.debug(f"TUI: Subagent unregistered: {subagent_id}")

        sub = self._subagent_subscriptions.pop(subagent_id, None)
        if sub:
            if sub.get("card"):
                sub["card"].mark_completed()

    def try_mount_subagent_card(
        self,
        subagent_id: str,
        transcript_path: Path,
        parent_tool_call_id: str,
        model_name: str = "",
        subagent_name: str = "",
    ) -> None:
        """Mount SubAgentCard, or queue if parent ToolCard doesn't exist yet.

        Args:
            subagent_id: Unique ID of the subagent session
            transcript_path: Path to the subagent's JSONL transcript
            parent_tool_call_id: Tool call ID of the spawning delegation call
            model_name: LLM model name
            subagent_name: Subagent type/name
        """
        from .widgets.subagent_card import SubAgentCard

        parent_tool_card = self._tool_cards.get(parent_tool_call_id)

        if parent_tool_card:
            store = self._subagent_subscriptions.get(subagent_id, {}).get("store")
            buffered = self._buffered_subagent_notifications.pop(subagent_id, [])

            card = SubAgentCard(
                subagent_id=subagent_id,
                transcript_path=transcript_path,
                store=store,
                buffered_notifications=buffered,
                model_name=model_name,
                subagent_name=subagent_name,
                id=f"subagent-{subagent_id}",
            )

            if subagent_id in self._subagent_subscriptions:
                self._subagent_subscriptions[subagent_id]["card"] = card

            self._mount_callback(parent_tool_card.mount, card)

            logger.info(
                f"TUI: Mounted SubAgentCard {subagent_id} inside ToolCard {parent_tool_call_id}"
            )
        else:
            self._pending_subagent_mounts[parent_tool_call_id] = {
                "subagent_id": subagent_id,
                "transcript_path": transcript_path,
                "model_name": model_name,
                "subagent_name": subagent_name,
            }
            logger.info(
                f"TUI: Queued SubAgentCard {subagent_id} "
                f"for pending mount (parent {parent_tool_call_id} not found). "
                f"Available tool_cards: {list(self._tool_cards.keys())}"
            )

    def on_tool_card_created(self, tool_call_id: str, tool_card: "ToolCard") -> None:
        """Check for pending subagent mounts when a ToolCard is created.

        Args:
            tool_call_id: The tool call ID of the created ToolCard
            tool_card: The created ToolCard instance
        """
        pending = self._pending_subagent_mounts.pop(tool_call_id, None)
        if pending:
            self.try_mount_subagent_card(
                pending["subagent_id"],
                pending["transcript_path"],
                tool_call_id,
                pending.get("model_name", ""),
            )

    def handle_subagent_notification(
        self,
        subagent_id: str,
        notification: "StoreNotification",
    ) -> None:
        """Bridge sync callback to async handler via mount_callback (call_later).

        Args:
            subagent_id: The subagent session ID
            notification: StoreNotification from the subagent's MessageStore
        """
        self._mount_callback(
            self.async_handle_subagent_notification,
            subagent_id,
            notification,
        )

    async def async_handle_subagent_notification(
        self,
        subagent_id: str,
        notification: "StoreNotification",
    ) -> None:
        """Async handler for subagent store notifications."""
        sub = self._subagent_subscriptions.get(subagent_id)
        if sub and sub.get("card"):
            await sub["card"].update_from_notification(notification)
        else:
            buf = self._buffered_subagent_notifications.setdefault(subagent_id, [])
            if len(buf) < 500:
                buf.append(notification)
            logger.debug(f"TUI: Buffered notification for {subagent_id} (total={len(buf)})")

    def find_subagent_tool_card(self, call_id: str):
        """Search active SubAgentCards for a tool card with the given call_id."""
        for sub_info in self._subagent_subscriptions.values():
            sa_card = sub_info.get("card")
            if sa_card and call_id in sa_card._tool_cards:
                return sa_card._tool_cards[call_id]
        return None
