"""Tests for ThinkTagParser - streaming <think> tag separation."""

import pytest

from src.llm.openai_backend import ThinkTagParser


class TestThinkTagParserBasic:
    """Basic functionality tests."""

    def test_no_think_tags(self):
        """Plain text passes through as-is."""
        parser = ThinkTagParser()
        result = parser.feed("Hello world")
        assert result == [("text", "Hello world")]

    def test_empty_input(self):
        """Empty string produces no output."""
        parser = ThinkTagParser()
        result = parser.feed("")
        assert result == []

    def test_think_block_only(self):
        """Content that is entirely a think block."""
        parser = ThinkTagParser()
        result = parser.feed("<think>reasoning here</think>")
        assert result == [("thinking", "reasoning here")]

    def test_think_then_text(self):
        """Think block followed by regular text."""
        parser = ThinkTagParser()
        result = parser.feed("<think>let me think</think>The answer is 42")
        assert result == [
            ("thinking", "let me think"),
            ("text", "The answer is 42"),
        ]

    def test_text_then_think(self):
        """Regular text followed by think block."""
        parser = ThinkTagParser()
        result = parser.feed("Hello <think>reasoning</think>")
        assert result == [
            ("text", "Hello "),
            ("thinking", "reasoning"),
        ]

    def test_text_think_text(self):
        """Text, think block, then more text."""
        parser = ThinkTagParser()
        result = parser.feed("Before <think>middle</think> After")
        assert result == [
            ("text", "Before "),
            ("thinking", "middle"),
            ("text", " After"),
        ]

    def test_multiple_think_blocks(self):
        """Multiple think blocks in one chunk."""
        parser = ThinkTagParser()
        result = parser.feed("<think>first</think>gap<think>second</think>end")
        assert result == [
            ("thinking", "first"),
            ("text", "gap"),
            ("thinking", "second"),
            ("text", "end"),
        ]


class TestThinkTagParserStreaming:
    """Tests for cross-chunk boundary handling."""

    def test_think_tag_split_across_chunks(self):
        """<think> tag split across two chunks."""
        parser = ThinkTagParser()
        r1 = parser.feed("Hello <thi")
        r2 = parser.feed("nk>reasoning</think>done")

        # First chunk: "Hello " is text, "<thi" is buffered (partial tag)
        assert r1 == [("text", "Hello ")]
        # Second chunk: completes the tag, yields thinking + text
        assert r2 == [("thinking", "reasoning"), ("text", "done")]

    def test_close_tag_split_across_chunks(self):
        """</think> tag split across two chunks."""
        parser = ThinkTagParser()
        r1 = parser.feed("<think>reasoning</th")
        r2 = parser.feed("ink>The answer")

        # First chunk: thinking content, "</th" buffered
        assert r1 == [("thinking", "reasoning")]
        # Second chunk: completes close tag, yields text
        assert r2 == [("text", "The answer")]

    def test_character_by_character(self):
        """Feed one character at a time."""
        parser = ThinkTagParser()
        text = "<think>hi</think>ok"
        all_results = []
        for ch in text:
            all_results.extend(parser.feed(ch))
        all_results.extend(parser.flush())

        # Concatenate by kind
        thinking = "".join(t for k, t in all_results if k == "thinking")
        normal = "".join(t for k, t in all_results if k == "text")
        assert thinking == "hi"
        assert normal == "ok"

    def test_three_chunk_split(self):
        """Tag split across three chunks."""
        parser = ThinkTagParser()
        r1 = parser.feed("text<")
        r2 = parser.feed("thin")
        r3 = parser.feed("k>reasoning</think>done")

        assert r1 == [("text", "text")]
        assert r2 == []  # Still buffering partial tag
        assert r3 == [("thinking", "reasoning"), ("text", "done")]

    def test_think_content_across_chunks(self):
        """Thinking content streamed across multiple chunks."""
        parser = ThinkTagParser()
        r1 = parser.feed("<think>part1")
        r2 = parser.feed(" part2")
        r3 = parser.feed(" part3</think>answer")

        assert r1 == [("thinking", "part1")]
        assert r2 == [("thinking", " part2")]
        assert r3 == [("thinking", " part3"), ("text", "answer")]


class TestThinkTagParserFlush:
    """Tests for flush behavior at stream end."""

    def test_flush_remaining_text(self):
        """Flush emits remaining text buffer."""
        parser = ThinkTagParser()
        parser.feed("hello")
        result = parser.flush()
        # feed already returned the text, flush should be empty
        assert result == []

    def test_flush_partial_open_tag(self):
        """Flush emits partial open tag as text (not a real tag)."""
        parser = ThinkTagParser()
        r1 = parser.feed("hello <thi")
        r2 = parser.flush()

        assert r1 == [("text", "hello ")]
        # Partial "<thi" is not a real tag - flush as text
        assert r2 == [("text", "<thi")]

    def test_flush_unclosed_thinking(self):
        """Flush emits buffered thinking if </think> never arrives."""
        parser = ThinkTagParser()
        r1 = parser.feed("<think>reasoning without close")
        r2 = parser.flush()

        assert r1 == [("thinking", "reasoning without close")]
        assert r2 == []

    def test_flush_partial_close_tag(self):
        """Flush emits buffered content when partial </think> at end."""
        parser = ThinkTagParser()
        r1 = parser.feed("<think>reasoning</th")
        r2 = parser.flush()

        assert r1 == [("thinking", "reasoning")]
        # Partial "</th" is thinking (we're inside think block)
        assert r2 == [("thinking", "</th")]


class TestThinkTagParserEdgeCases:
    """Edge cases and corner cases."""

    def test_angle_bracket_not_think(self):
        """< that is not part of <think> passes through as text."""
        parser = ThinkTagParser()
        result = parser.feed("x < y and a > b")
        # The < might cause buffering, but > doesn't match
        all_results = result + parser.flush()
        text = "".join(t for k, t in all_results if k == "text")
        assert text == "x < y and a > b"

    def test_html_tags_pass_through(self):
        """Other HTML-like tags are not stripped."""
        parser = ThinkTagParser()
        result = parser.feed("<div>hello</div>")
        all_results = result + parser.flush()
        text = "".join(t for k, t in all_results if k == "text")
        assert text == "<div>hello</div>"

    def test_nested_angle_brackets_in_thinking(self):
        """Angle brackets inside think block (not </think>) pass through."""
        parser = ThinkTagParser()
        result = parser.feed("<think>x < y means x is smaller</think>done")
        assert result == [
            ("thinking", "x < y means x is smaller"),
            ("text", "done"),
        ]

    def test_think_tag_case_sensitive(self):
        """<THINK> (uppercase) is NOT treated as a think tag."""
        parser = ThinkTagParser()
        result = parser.feed("<THINK>not thinking</THINK>")
        all_results = result + parser.flush()
        text = "".join(t for k, t in all_results if k == "text")
        assert text == "<THINK>not thinking</THINK>"

    def test_empty_think_block(self):
        """Empty <think></think> produces no thinking output."""
        parser = ThinkTagParser()
        result = parser.feed("<think></think>answer")
        assert result == [("text", "answer")]

    def test_newlines_in_think_block(self):
        """Think block with newlines."""
        parser = ThinkTagParser()
        result = parser.feed("<think>line1\nline2\nline3</think>result")
        assert result == [
            ("thinking", "line1\nline2\nline3"),
            ("text", "result"),
        ]

    def test_back_to_back_think_blocks(self):
        """Two think blocks with no gap."""
        parser = ThinkTagParser()
        result = parser.feed("<think>first</think><think>second</think>")
        assert result == [
            ("thinking", "first"),
            ("thinking", "second"),
        ]

    def test_realistic_minimax_pattern(self):
        """Simulate realistic MiniMax streaming pattern."""
        parser = ThinkTagParser()
        chunks = [
            "<think>",
            "Let me analyze this problem.\n",
            "The user wants to know about Python.\n",
            "I should provide a clear answer.",
            "</think>",
            "\nPython is a versatile ",
            "programming language.",
        ]
        all_results = []
        for chunk in chunks:
            all_results.extend(parser.feed(chunk))
        all_results.extend(parser.flush())

        thinking = "".join(t for k, t in all_results if k == "thinking")
        text = "".join(t for k, t in all_results if k == "text")

        assert thinking == (
            "Let me analyze this problem.\n"
            "The user wants to know about Python.\n"
            "I should provide a clear answer."
        )
        assert text == "\nPython is a versatile programming language."
