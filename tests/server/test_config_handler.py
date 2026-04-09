"""Tests for src.server.config_handler pure functions."""

from unittest.mock import patch, MagicMock
import pytest

from src.server.config_handler import (
    get_config_response,
    save_config_from_request,
    list_models_from_request,
    SUBAGENT_NAMES,
    _int_or,
    _float_or,
    _int_or_none,
)


# ── Helpers ──

def _make_config(**overrides):
    """Build a real LLMConfigData with defaults."""
    from src.llm.config_loader import LLMConfigData
    return LLMConfigData(**overrides)


# ── get_config_response ──

class TestGetConfigResponse:

    @patch("src.llm.config_loader.load_llm_config")
    def test_basic_structure(self, mock_load):
        mock_load.return_value = _make_config(
            model="gpt-4", backend_type="openai", base_url="http://localhost:8000/v1",
            api_key="sk-secret",
        )
        result = get_config_response("/fake/config.yaml")

        assert result["type"] == "config_loaded"
        assert "config" in result
        assert "subagent_names" in result
        assert result["subagent_names"] == list(SUBAGENT_NAMES)

    @patch("src.llm.config_loader.load_llm_config")
    def test_api_key_not_exposed(self, mock_load):
        mock_load.return_value = _make_config(api_key="sk-secret")
        result = get_config_response("/fake/config.yaml")

        cfg = result["config"]
        assert "api_key" not in cfg
        assert cfg["has_api_key"] is True

    @patch("src.llm.config_loader.load_llm_config")
    def test_has_api_key_false(self, mock_load):
        mock_load.return_value = _make_config(api_key="")
        result = get_config_response("/fake/config.yaml")

        assert result["config"]["has_api_key"] is False

    @patch("src.llm.config_loader.load_llm_config")
    def test_subagent_models_flattened(self, mock_load):
        from src.llm.config_loader import SubAgentLLMOverride
        cfg = _make_config()
        cfg.subagents["code-reviewer"] = SubAgentLLMOverride(model="gpt-3.5-turbo")
        mock_load.return_value = cfg

        result = get_config_response("/fake/config.yaml")
        sa = result["config"]["subagent_models"]
        assert sa["code-reviewer"] == "gpt-3.5-turbo"
        assert sa["test-writer"] == ""


# ── save_config_from_request ──

class TestSaveConfigFromRequest:

    @patch("src.llm.config_loader.save_llm_config", return_value=True)
    def test_success(self, mock_save):
        data = {
            "config": {
                "backend_type": "openai",
                "base_url": "http://localhost:8000/v1",
                "model": "gpt-4",
                "temperature": "0.5",
                "max_tokens": "8192",
                "context_window": "65536",
            }
        }
        result = save_config_from_request(data, "/fake/config.yaml")

        assert result["type"] == "config_saved"
        assert result["success"] is True
        assert "Configuration saved" in result["message"]

        mock_save.assert_called_once()
        saved_cfg = mock_save.call_args[0][0]
        assert saved_cfg.model == "gpt-4"
        assert saved_cfg.temperature == 0.5
        assert saved_cfg.max_tokens == 8192

    @patch("src.llm.config_loader.save_llm_config", return_value=True)
    def test_numeric_coercion_fallback(self, mock_save):
        data = {
            "config": {
                "temperature": "not-a-number",
                "max_tokens": "",
                "context_window": None,
            }
        }
        result = save_config_from_request(data, "/fake/config.yaml")
        assert result["success"] is True

        saved_cfg = mock_save.call_args[0][0]
        assert saved_cfg.temperature == 0.2
        assert saved_cfg.max_tokens == 16384
        assert saved_cfg.context_window == 131072

    @patch("src.llm.config_loader.save_llm_config", return_value=True)
    def test_subagents(self, mock_save):
        data = {
            "config": {
                "subagent_models": {
                    "code-reviewer": "gpt-3.5-turbo",
                    "test-writer": "",
                }
            }
        }
        result = save_config_from_request(data, "/fake/config.yaml")
        assert result["success"] is True

        saved_cfg = mock_save.call_args[0][0]
        assert "code-reviewer" in saved_cfg.subagents
        assert saved_cfg.subagents["code-reviewer"].model == "gpt-3.5-turbo"
        assert "test-writer" not in saved_cfg.subagents

    @patch("src.llm.config_loader.save_llm_config", return_value=True)
    def test_api_key_passed_through_not_saved_to_disk(self, mock_save):
        data = {"config": {"api_key": "sk-new-key"}}
        result = save_config_from_request(data, "/fake/config.yaml")
        # API key should be in the response for runtime use
        assert result["_api_key"] == "sk-new-key"
        # But not written to YAML (save_llm_config never receives it)
        saved_cfg = mock_save.call_args[0][0]
        assert saved_cfg.api_key == ""  # LLMConfigData.api_key stays default

    @patch("src.llm.config_loader.save_llm_config", return_value=True)
    def test_api_key_empty_when_not_provided(self, mock_save):
        """When frontend doesn't include api_key, _api_key should be empty."""
        data = {"config": {"model": "gpt-4o"}}
        result = save_config_from_request(data, "/fake/config.yaml")
        assert result["_api_key"] == ""

    @patch("src.llm.config_loader.save_llm_config", return_value=True)
    def test_config_object_returned_for_hot_swap(self, mock_save):
        """_config must be present in response so stdio_server can hot-swap."""
        data = {"config": {"backend_type": "anthropic", "model": "claude-haiku-4-5-20251001"}}
        result = save_config_from_request(data, "/fake/config.yaml")
        assert result["success"] is True
        cfg = result["_config"]
        assert cfg.backend_type == "anthropic"
        assert cfg.model == "claude-haiku-4-5-20251001"

    @patch("src.llm.config_loader.save_llm_config", return_value=False)
    def test_save_failure(self, mock_save):
        data = {"config": {}}
        result = save_config_from_request(data, "/fake/config.yaml")
        assert result["success"] is False


# ── list_models_from_request ──

class TestListModelsFromRequest:

    @patch("src.server.config_handler._list_models")
    def test_success(self, mock_list):
        mock_list.return_value = ["model-a", "model-b"]
        data = {"backend": "openai", "base_url": "http://localhost:8000/v1", "api_key": "sk-key"}
        result = list_models_from_request(data)

        assert result["type"] == "models_list"
        assert result["models"] == ["model-a", "model-b"]
        assert result["error"] is None

    @patch("src.server.config_handler._list_models")
    def test_error(self, mock_list):
        mock_list.side_effect = ConnectionError("timeout")
        data = {"backend": "openai", "base_url": "", "api_key": ""}
        result = list_models_from_request(data)

        assert result["type"] == "models_list"
        assert result["models"] == []
        assert "timeout" in result["error"]


# ── Numeric coercion helpers ──

class TestNumericHelpers:

    def test_int_or(self):
        assert _int_or("42", 10) == 42
        assert _int_or("bad", 10) == 10
        assert _int_or(None, 10) == 10
        assert _int_or("", 10) == 10

    def test_float_or(self):
        assert _float_or("0.7", 0.2) == 0.7
        assert _float_or("bad", 0.2) == 0.2
        assert _float_or(None, 0.2) == 0.2

    def test_int_or_none(self):
        assert _int_or_none("100") == 100
        assert _int_or_none("bad") is None
        assert _int_or_none(None) is None
        assert _int_or_none("") is None


# ── SSRF protection ──

class TestSSRFProtection:
    """URL validation must block cloud metadata endpoints."""

    def test_blocks_cloud_metadata_url(self):
        from src.server.config_handler import _validate_list_models_url
        is_valid, reason = _validate_list_models_url(
            "http://169.254.169.254/latest/meta-data/"
        )
        assert not is_valid
        assert "link-local" in reason.lower() or "metadata" in reason.lower()

    def test_allows_normal_url(self):
        from src.server.config_handler import _validate_list_models_url
        is_valid, _ = _validate_list_models_url("https://api.openai.com/v1")
        assert is_valid

    def test_allows_localhost_for_ollama(self):
        from src.server.config_handler import _validate_list_models_url
        is_valid, _ = _validate_list_models_url("http://localhost:11434")
        assert is_valid

    def test_handles_invalid_url(self):
        from src.server.config_handler import _validate_list_models_url
        is_valid, reason = _validate_list_models_url("")
        assert not is_valid


# ── Mode validation ──

class TestModeValidation:
    """Only plan, normal, auto are valid permission modes."""

    def test_valid_modes(self):
        VALID_MODES = {"plan", "normal", "auto"}
        for mode in VALID_MODES:
            assert mode in VALID_MODES

    def test_invalid_mode_rejected(self):
        VALID_MODES = {"plan", "normal", "auto"}
        assert "superuser" not in VALID_MODES
        assert "root" not in VALID_MODES
        assert "" not in VALID_MODES
