"""Tests for src.ui.segment_renderer - segment rendering into widgets."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from types import SimpleNamespace

from src.ui.segment_renderer import SegmentRenderer


# ---- Helpers ----

def make_tool_call(tc_id="tc-1", name="read_file", arguments='{"path": "foo.py"}'):
    """Create a mock tool call."""
    return SimpleNamespace(
        id=tc_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def make_message(tool_calls=None, uuid="msg-1"):
    """Create a mock message."""
    msg = SimpleNamespace(
        tool_calls=tool_calls or [],
        uuid=uuid,
    )
    return msg


def make_renderer(tool_cards=None, message_store=None, silent_tools=None, is_replaying=False):
    """Create a SegmentRenderer with mock dependencies."""
    tool_cards = tool_cards if tool_cards is not None else {}
    on_created = MagicMock()
    renderer = SegmentRenderer(
        tool_cards=tool_cards,
        message_store=message_store,
        silent_tools=silent_tools or set(),
        is_replaying_fn=lambda: is_replaying,
        on_tool_card_created=on_created,
    )
    return renderer, on_created


# ---- get_tool_call_safe ----

class TestGetToolCallSafe:
    def test_returns_tool_call_by_index(self):
        tc = make_tool_call()
        msg = make_message(tool_calls=[tc])
        renderer, _ = make_renderer()
        assert renderer.get_tool_call_safe(msg, 0) is tc

    def test_returns_none_for_no_tool_calls(self):
        msg = make_message(tool_calls=None)
        msg.tool_calls = None
        renderer, _ = make_renderer()
        assert renderer.get_tool_call_safe(msg, 0) is None

    def test_returns_none_for_empty_tool_calls(self):
        msg = make_message(tool_calls=[])
        msg.tool_calls = []
        renderer, _ = make_renderer()
        assert renderer.get_tool_call_safe(msg, 0) is None

    def test_returns_none_for_out_of_bounds(self):
        msg = make_message(tool_calls=[make_tool_call()])
        renderer, _ = make_renderer()
        assert renderer.get_tool_call_safe(msg, 5) is None

    def test_context_passed_to_logs(self):
        msg = make_message(tool_calls=[])
        msg.tool_calls = []
        renderer, _ = make_renderer()
        # Should not raise, just log and return None
        assert renderer.get_tool_call_safe(msg, 0, context="test_ctx") is None


# ---- get_tool_call_by_id ----

class TestGetToolCallById:
    def test_finds_by_id(self):
        tc1 = make_tool_call(tc_id="tc-a")
        tc2 = make_tool_call(tc_id="tc-b")
        msg = make_message(tool_calls=[tc1, tc2])
        renderer, _ = make_renderer()
        assert renderer.get_tool_call_by_id(msg, "tc-b") is tc2

    def test_returns_none_for_missing_id(self):
        tc = make_tool_call(tc_id="tc-a")
        msg = make_message(tool_calls=[tc])
        renderer, _ = make_renderer()
        assert renderer.get_tool_call_by_id(msg, "tc-nonexistent") is None

    def test_returns_none_for_no_tool_calls(self):
        msg = make_message()
        msg.tool_calls = None
        renderer, _ = make_renderer()
        assert renderer.get_tool_call_by_id(msg, "tc-1") is None


# ---- render_segments ----

class TestRenderSegments:
    @pytest.mark.asyncio
    async def test_renders_text_segment(self):
        from src.session.models.message import TextSegment
        widget = AsyncMock()
        widget.add_text = AsyncMock()
        renderer, _ = make_renderer()

        segments = [TextSegment(content="Hello world")]
        msg = make_message()
        count = await renderer.render_segments(widget, msg, segments)

        assert count == 1
        widget.add_text.assert_called_once_with("Hello world")

    @pytest.mark.asyncio
    async def test_skips_empty_text(self):
        from src.session.models.message import TextSegment
        widget = AsyncMock()
        widget.add_text = AsyncMock()
        renderer, _ = make_renderer()

        segments = [TextSegment(content="   ")]
        msg = make_message()
        count = await renderer.render_segments(widget, msg, segments)

        assert count == 1
        widget.add_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_renders_code_block_segment(self):
        from src.session.models.message import CodeBlockSegment
        widget = MagicMock()
        widget.add_text = AsyncMock()
        renderer, _ = make_renderer()

        segments = [CodeBlockSegment(language="python", content="x = 1")]
        msg = make_message()
        count = await renderer.render_segments(widget, msg, segments)

        assert count == 1
        widget.start_code_block.assert_called_once_with("python")
        widget.append_code.assert_called_once_with("x = 1")
        widget.end_code_block.assert_called_once()

    @pytest.mark.asyncio
    async def test_renders_thinking_segment(self):
        from src.session.models.message import ThinkingSegment
        widget = MagicMock()
        widget.add_text = AsyncMock()
        renderer, _ = make_renderer()

        segments = [ThinkingSegment(content="Let me think...")]
        msg = make_message()
        count = await renderer.render_segments(widget, msg, segments)

        assert count == 1
        widget.start_thinking.assert_called_once()
        widget.append_thinking.assert_called_once_with("Let me think...")
        widget.end_thinking.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_idx_skips_earlier_segments(self):
        from src.session.models.message import TextSegment
        widget = AsyncMock()
        widget.add_text = AsyncMock()
        renderer, _ = make_renderer()

        segments = [
            TextSegment(content="First"),
            TextSegment(content="Second"),
            TextSegment(content="Third"),
        ]
        msg = make_message()
        count = await renderer.render_segments(widget, msg, segments, start_idx=2)

        assert count == 1
        widget.add_text.assert_called_once_with("Third")

    @pytest.mark.asyncio
    async def test_silent_tool_skipped(self):
        from src.session.models.message import ToolCallRefSegment
        tc = make_tool_call(tc_id="tc-1", name="task_create")
        msg = make_message(tool_calls=[tc])
        widget = MagicMock()
        widget.add_text = AsyncMock()
        renderer, on_created = make_renderer(silent_tools={"task_create"})

        segments = [ToolCallRefSegment(tool_call_id="tc-1")]
        count = await renderer.render_segments(widget, msg, segments)

        assert count == 1
        on_created.assert_not_called()

    @pytest.mark.asyncio
    async def test_tool_call_ref_segment_creates_card(self):
        from src.session.models.message import ToolCallRefSegment
        tc = make_tool_call(tc_id="tc-1", name="read_file", arguments='{"path": "x.py"}')
        msg = make_message(tool_calls=[tc])

        tool_cards = {}
        mock_card = MagicMock()
        widget = MagicMock()
        widget.add_text = AsyncMock()
        widget.add_tool_card = MagicMock(return_value=mock_card)

        renderer, on_created = make_renderer(tool_cards=tool_cards)

        segments = [ToolCallRefSegment(tool_call_id="tc-1")]
        count = await renderer.render_segments(widget, msg, segments)

        assert count == 1
        widget.add_tool_card.assert_called_once()
        assert tool_cards["tc-1"] is mock_card
        on_created.assert_called_once_with("tc-1", mock_card)

    @pytest.mark.asyncio
    async def test_skip_existing_cards(self):
        from src.session.models.message import ToolCallRefSegment
        tc = make_tool_call(tc_id="tc-1", name="read_file")
        msg = make_message(tool_calls=[tc])

        existing_card = MagicMock()
        tool_cards = {"tc-1": existing_card}
        widget = MagicMock()
        widget.add_text = AsyncMock()

        renderer, on_created = make_renderer(tool_cards=tool_cards)

        segments = [ToolCallRefSegment(tool_call_id="tc-1")]
        count = await renderer.render_segments(widget, msg, segments, skip_existing_cards=True)

        assert count == 1
        widget.add_tool_card.assert_not_called()


# ---- render_tool_segments_only ----

class TestRenderToolSegmentsOnly:
    @pytest.mark.asyncio
    async def test_renders_tool_ref_segment(self):
        from src.session.models.message import ToolCallRefSegment, TextSegment
        tc = make_tool_call(tc_id="tc-1", name="read_file", arguments='{"path": "a.py"}')
        msg = make_message(tool_calls=[tc])

        tool_cards = {}
        mock_card = MagicMock()
        widget = MagicMock()
        widget.add_tool_card = MagicMock(return_value=mock_card)

        renderer, on_created = make_renderer(tool_cards=tool_cards)

        # Mix of text (should be skipped) and tool ref (should be rendered)
        segments = [
            TextSegment(content="Some text"),
            ToolCallRefSegment(tool_call_id="tc-1"),
        ]
        await renderer.render_tool_segments_only(widget, msg, segments)

        widget.add_tool_card.assert_called_once()
        assert tool_cards["tc-1"] is mock_card

    @pytest.mark.asyncio
    async def test_skips_silent_tools(self):
        from src.session.models.message import ToolCallRefSegment
        tc = make_tool_call(tc_id="tc-1", name="task_update")
        msg = make_message(tool_calls=[tc])

        widget = MagicMock()
        renderer, on_created = make_renderer(silent_tools={"task_update"})

        segments = [ToolCallRefSegment(tool_call_id="tc-1")]
        await renderer.render_tool_segments_only(widget, msg, segments)

        widget.add_tool_card.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_already_tracked_cards(self):
        from src.session.models.message import ToolCallRefSegment
        tc = make_tool_call(tc_id="tc-1", name="read_file")
        msg = make_message(tool_calls=[tc])

        existing_card = MagicMock()
        tool_cards = {"tc-1": existing_card}
        widget = MagicMock()

        renderer, _ = make_renderer(tool_cards=tool_cards)

        segments = [ToolCallRefSegment(tool_call_id="tc-1")]
        await renderer.render_tool_segments_only(widget, msg, segments)

        widget.add_tool_card.assert_not_called()


# ---- set_message_store ----

class TestSetMessageStore:
    def test_updates_store_reference(self):
        renderer, _ = make_renderer(message_store=None)
        new_store = MagicMock()
        renderer.set_message_store(new_store)
        assert renderer._message_store is new_store
