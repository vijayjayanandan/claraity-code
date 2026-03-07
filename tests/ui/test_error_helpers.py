"""Tests for src.ui.error_helpers - user-friendly error handling."""

import pytest

from src.ui.error_helpers import (
    classify_error,
    generate_error_reference,
    extract_user_content_text,
    format_user_error,
)


# ---- classify_error ----

class TestClassifyError:
    def test_timeout(self):
        msg, cat = classify_error(TimeoutError("Connection timed out"))
        assert cat == "timeout"
        assert "timed out" in msg.lower()

    def test_timeout_by_type_name(self):
        msg, cat = classify_error(TimeoutError("something"))
        assert cat == "timeout"

    def test_rate_limit_429(self):
        msg, cat = classify_error(Exception("Error 429 too many requests"))
        assert cat == "rate_limit"

    def test_rate_limit_explicit(self):
        msg, cat = classify_error(Exception("rate_limit exceeded"))
        assert cat == "rate_limit"

    def test_auth_401(self):
        msg, cat = classify_error(Exception("HTTP 401 Unauthorized"))
        assert cat == "auth"

    def test_auth_invalid_key(self):
        msg, cat = classify_error(Exception("Invalid API key provided"))
        assert cat == "auth"

    def test_service_500(self):
        msg, cat = classify_error(Exception("HTTP 500 Internal Server Error"))
        assert cat == "service"

    def test_service_overloaded(self):
        msg, cat = classify_error(Exception("Model is overloaded"))
        assert cat == "service"

    def test_network_connection_refused(self):
        msg, cat = classify_error(ConnectionRefusedError("Connection refused"))
        assert cat == "network"

    def test_network_dns(self):
        msg, cat = classify_error(Exception("DNS resolution failed"))
        assert cat == "network"

    def test_context_too_long(self):
        msg, cat = classify_error(Exception("Context window exceeded, too long"))
        assert cat == "context"

    def test_invalid_request_400(self):
        msg, cat = classify_error(Exception("400 Bad Request: invalid JSON"))
        assert cat == "invalid"

    def test_unexpected_fallback(self):
        msg, cat = classify_error(Exception("something completely unknown"))
        assert cat == "unexpected"
        assert "unexpected" in msg.lower()


# ---- generate_error_reference ----

class TestGenerateErrorReference:
    def test_returns_8_char_hex(self):
        ref = generate_error_reference()
        assert len(ref) == 8
        assert all(c in "0123456789abcdef" for c in ref)

    def test_unique(self):
        refs = {generate_error_reference() for _ in range(100)}
        assert len(refs) == 100  # Extremely unlikely to collide


# ---- extract_user_content_text ----

class TestExtractUserContentText:
    def test_string_content(self):
        assert extract_user_content_text("hello world") == "hello world"

    def test_none_content(self):
        assert extract_user_content_text(None) == ""

    def test_int_content(self):
        assert extract_user_content_text(42) == "42"

    def test_empty_list(self):
        assert extract_user_content_text([]) == ""

    def test_text_part(self):
        content = [{"type": "text", "text": "Hello"}]
        assert extract_user_content_text(content) == "Hello"

    def test_multiple_text_parts(self):
        content = [
            {"type": "text", "text": "Line 1"},
            {"type": "text", "text": "Line 2"},
        ]
        assert extract_user_content_text(content) == "Line 1\nLine 2"

    def test_image_data_url(self):
        content = [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}}
        ]
        assert extract_user_content_text(content) == "[IMAGE]"

    def test_image_regular_url(self):
        content = [
            {"type": "image_url", "image_url": {"url": "https://example.com/img.png"}}
        ]
        assert extract_user_content_text(content) == "[IMAGE: https://example.com/img.png]"

    def test_file_part(self):
        content = [{"type": "file", "filename": "readme.md"}]
        assert extract_user_content_text(content) == "[FILE: readme.md]"

    def test_mixed_parts(self):
        content = [
            {"type": "text", "text": "Look at this:"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
        ]
        result = extract_user_content_text(content)
        assert "Look at this:" in result
        assert "[IMAGE]" in result

    def test_non_dict_items_skipped(self):
        content = ["just a string", {"type": "text", "text": "valid"}]
        assert extract_user_content_text(content) == "valid"

    def test_empty_text_skipped(self):
        content = [{"type": "text", "text": ""}]
        assert extract_user_content_text(content) == ""


# ---- format_user_error ----

class TestFormatUserError:
    def test_includes_reference(self):
        result = format_user_error(TimeoutError("timed out"), include_reference=True)
        assert "(ref:" in result

    def test_no_reference(self):
        result = format_user_error(TimeoutError("timed out"), include_reference=False)
        assert "(ref:" not in result
        assert "timed out" in result.lower()

    def test_uses_classify_error(self):
        result = format_user_error(Exception("429 rate_limit"), include_reference=False)
        assert "wait" in result.lower()
