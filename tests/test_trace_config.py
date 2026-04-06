"""
Test suite for trace_enabled config loader and saver.

Coverage:
- load_trace_enabled: missing file, missing key, true value, false value
- save_trace_enabled: file creation, key preservation, round-trip

Total: 7 tests
"""

from __future__ import annotations

import pytest


class TestLoadTraceEnabled:
    """Tests for load_trace_enabled from config_loader."""

    def test_load_missing_file_returns_false(self, tmp_path):
        """No config file returns False."""
        from src.llm.config_loader import load_trace_enabled

        config_path = str(tmp_path / "nonexistent.yaml")
        assert load_trace_enabled(config_path) is False

    def test_load_no_trace_key_returns_false(self, tmp_path):
        """Config exists but has no trace_enabled key returns False."""
        from src.llm.config_loader import load_trace_enabled

        config_file = tmp_path / "config.yaml"
        config_file.write_text("llm:\n  model: test-model\n", encoding="utf-8")

        assert load_trace_enabled(str(config_file)) is False

    def test_load_trace_enabled_true(self, tmp_path):
        """Config has trace_enabled: true returns True."""
        from src.llm.config_loader import load_trace_enabled

        config_file = tmp_path / "config.yaml"
        config_file.write_text("trace_enabled: true\n", encoding="utf-8")

        assert load_trace_enabled(str(config_file)) is True

    def test_load_trace_enabled_false(self, tmp_path):
        """Config has trace_enabled: false returns False."""
        from src.llm.config_loader import load_trace_enabled

        config_file = tmp_path / "config.yaml"
        config_file.write_text("trace_enabled: false\n", encoding="utf-8")

        assert load_trace_enabled(str(config_file)) is False


class TestSaveTraceEnabled:
    """Tests for save_trace_enabled from config_loader."""

    def test_save_creates_file(self, tmp_path):
        """Save to non-existent file creates it with trace_enabled key."""
        from src.llm.config_loader import save_trace_enabled
        import yaml

        config_path = str(tmp_path / "new_config.yaml")
        result = save_trace_enabled(True, config_path)

        assert result is True
        data = yaml.safe_load((tmp_path / "new_config.yaml").read_text(encoding="utf-8"))
        assert data["trace_enabled"] is True

    def test_save_preserves_other_keys(self, tmp_path):
        """Save to existing config with llm section preserves that section."""
        from src.llm.config_loader import save_trace_enabled
        import yaml

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "llm:\n  model: my-model\n  temperature: 0.5\n",
            encoding="utf-8",
        )

        save_trace_enabled(True, str(config_file))

        data = yaml.safe_load(config_file.read_text(encoding="utf-8"))
        assert data["trace_enabled"] is True
        assert data["llm"]["model"] == "my-model"
        assert data["llm"]["temperature"] == 0.5

    def test_save_round_trip(self, tmp_path):
        """Save True then load returns True. Save False then load returns False."""
        from src.llm.config_loader import load_trace_enabled, save_trace_enabled

        config_path = str(tmp_path / "config.yaml")

        save_trace_enabled(True, config_path)
        assert load_trace_enabled(config_path) is True

        save_trace_enabled(False, config_path)
        assert load_trace_enabled(config_path) is False
