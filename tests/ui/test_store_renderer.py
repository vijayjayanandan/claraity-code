"""Tests for src.ui.store_renderer - store-driven message rendering."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from types import SimpleNamespace

from src.ui.store_renderer import StoreRenderer


# ---- Helpers ----

def make_meta(**kwargs):
    """Create a mock message meta."""
    defaults = {
        "stream_id": "stream-1",
        "uuid": "uuid-1",
        "event_type": None,
        "extra": {},
        "status": None,
        "duration_ms": None,
        "segments": [],
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def make_message(role="user", content="Hello", meta=None, tool_calls=None, tool_call_id=None):
    """Create a mock message."""
    if meta is None:
        meta = make_meta()
    msg = SimpleNamespace(
        is_user=(role == "user"),
        is_assistant=(role == "assistant"),
        is_tool=(role == "tool"),
        is_system=(role == "system"),
        content=content,
        meta=meta,
        tool_calls=tool_calls or [],
        tool_call_id=tool_call_id,
        get_text_content=lambda: content if isinstance(content, str) else "",
    )
    return msg


def make_tool_call(tc_id="tc-1", name="read_file", arguments='{"path": "a.py"}'):
    return SimpleNamespace(
        id=tc_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def make_renderer(message_store=None, tool_cards=None):
    """Create a StoreRenderer with mock dependencies."""
    segment_renderer = MagicMock()
    segment_renderer.render_segments = AsyncMock(return_value=1)
    segment_renderer.render_tool_segments_only = AsyncMock()

    tool_cards = tool_cards if tool_cards is not None else {}
    store_widgets = {}
    segment_idx = {}
    on_clarify = AsyncMock()
    on_plan = AsyncMock()
    on_tc_created = MagicMock()
    scroll = MagicMock()

    renderer = StoreRenderer(
        segment_renderer=segment_renderer,
        tool_cards=tool_cards,
        message_store=message_store,
        store_message_widgets=store_widgets,
        store_rendered_segment_idx=segment_idx,
        silent_tools={"task_create", "task_update"},
        on_clarify_request=on_clarify,
        on_plan_approval=on_plan,
        on_tool_card_created=on_tc_created,
        scroll_to_bottom=scroll,
    )
    return renderer, {
        "segment_renderer": segment_renderer,
        "store_widgets": store_widgets,
        "segment_idx": segment_idx,
        "on_clarify": on_clarify,
        "on_plan": on_plan,
        "on_tc_created": on_tc_created,
        "scroll": scroll,
    }


# ---- apply_tool_result_to_card ----

class TestApplyToolResultToCard:
    @pytest.mark.asyncio
    async def test_success_result(self):
        card = MagicMock()
        tool_cards = {"tc-1": card}
        renderer, _ = make_renderer(tool_cards=tool_cards)

        msg = make_message(
            role="tool",
            content="File contents here",
            meta=make_meta(status="success", duration_ms=150),
            tool_call_id="tc-1",
        )
        await renderer.apply_tool_result_to_card(msg)
        card.set_result.assert_called_once_with("File contents here", duration_ms=150)

    @pytest.mark.asyncio
    async def test_error_result(self):
        card = MagicMock()
        tool_cards = {"tc-1": card}
        renderer, _ = make_renderer(tool_cards=tool_cards)

        msg = make_message(
            role="tool",
            content="File not found",
            meta=make_meta(status="error"),
            tool_call_id="tc-1",
        )
        await renderer.apply_tool_result_to_card(msg)
        card.set_error.assert_called_once_with("File not found")

    @pytest.mark.asyncio
    async def test_missing_tool_call_id(self):
        renderer, _ = make_renderer()
        msg = make_message(role="tool", tool_call_id=None)
        # Should not raise
        await renderer.apply_tool_result_to_card(msg)

    @pytest.mark.asyncio
    async def test_no_matching_card(self):
        renderer, _ = make_renderer(tool_cards={})
        msg = make_message(role="tool", tool_call_id="tc-missing")
        # Should not raise
        await renderer.apply_tool_result_to_card(msg)


# ---- hydrate_tool_card_from_store ----

class TestHydrateToolCardFromStore:
    def test_no_store_sets_pending(self):
        renderer, _ = make_renderer(message_store=None)
        card = MagicMock()
        renderer.hydrate_tool_card_from_store(card, "tc-1")
        # Should set PENDING via ToolStatus
        assert card.status is not None

    def test_success_result(self):
        store = MagicMock()
        store.get_tool_approval.return_value = None

        result_msg = MagicMock()
        result_msg.get_text_content.return_value = "file content"
        result_msg.meta = make_meta(status="success", duration_ms=200)
        store.get_tool_result.return_value = result_msg

        renderer, _ = make_renderer(message_store=store)
        card = MagicMock()
        renderer.hydrate_tool_card_from_store(card, "tc-1")
        card.set_result.assert_called_once_with("file content", duration_ms=200)

    def test_error_result(self):
        store = MagicMock()
        store.get_tool_approval.return_value = None

        result_msg = MagicMock()
        result_msg.get_text_content.return_value = "bad things"
        result_msg.meta = make_meta(status="error")
        store.get_tool_result.return_value = result_msg

        renderer, _ = make_renderer(message_store=store)
        card = MagicMock()
        renderer.hydrate_tool_card_from_store(card, "tc-1")
        card.set_error.assert_called_once()

    def test_no_result_shows_interrupted(self):
        store = MagicMock()
        store.get_tool_approval.return_value = None
        store.get_tool_result.return_value = None

        renderer, _ = make_renderer(message_store=store)
        card = MagicMock()
        renderer.hydrate_tool_card_from_store(card, "tc-1")
        assert "Interrupted" in card.result_preview

    def test_approved_but_no_result(self):
        store = MagicMock()
        approval_msg = MagicMock()
        approval_msg.meta = make_meta(extra={"approved": True})
        store.get_tool_approval.return_value = approval_msg
        store.get_tool_result.return_value = None

        renderer, _ = make_renderer(message_store=store)
        card = MagicMock()
        renderer.hydrate_tool_card_from_store(card, "tc-1")
        assert "Approved" in card.result_preview


# ---- render_store_message: system messages ----

class TestRenderStoreMessageSystem:
    @pytest.mark.asyncio
    async def test_clarify_request_calls_callback(self):
        renderer, deps = make_renderer()
        conversation = AsyncMock()

        msg = make_message(
            role="system",
            meta=make_meta(event_type="clarify_request"),
        )
        await renderer.render_store_message(msg, conversation)
        deps["on_clarify"].assert_called_once_with(msg, conversation)

    @pytest.mark.asyncio
    async def test_plan_submitted_calls_callback(self):
        renderer, deps = make_renderer()
        conversation = AsyncMock()

        msg = make_message(
            role="system",
            meta=make_meta(
                event_type="plan_submitted",
                extra={"plan_hash": "abc123", "excerpt": "Do X", "truncated": False, "plan_path": "/tmp/plan.md"},
            ),
        )
        await renderer.render_store_message(msg, conversation)
        deps["on_plan"].assert_called_once()

    @pytest.mark.asyncio
    async def test_plan_submitted_skipped_if_result_exists(self):
        store = MagicMock()
        store.get_tool_result.return_value = MagicMock()  # Result exists

        renderer, deps = make_renderer(message_store=store)
        conversation = AsyncMock()

        msg = make_message(
            role="system",
            meta=make_meta(
                event_type="plan_submitted",
                extra={"plan_hash": "abc", "call_id": "tc-1"},
            ),
        )
        await renderer.render_store_message(msg, conversation)
        deps["on_plan"].assert_not_called()

    @pytest.mark.asyncio
    async def test_compact_boundary_clears_widgets(self):
        tool_cards = {"tc-1": MagicMock()}
        renderer, deps = make_renderer(tool_cards=tool_cards)
        store_widgets = deps["store_widgets"]
        store_widgets["s-1"] = MagicMock()

        conversation = MagicMock()
        child = MagicMock()
        conversation.children = [child]

        msg = make_message(
            role="system",
            meta=make_meta(event_type="compact_boundary"),
        )
        await renderer.render_store_message(msg, conversation)
        child.remove.assert_called_once()
        assert len(store_widgets) == 0
        assert len(tool_cards) == 0


# ---- set_message_store ----

class TestSetMessageStore:
    def test_updates_store(self):
        renderer, _ = make_renderer(message_store=None)
        new_store = MagicMock()
        renderer.set_message_store(new_store)
        assert renderer._message_store is new_store
