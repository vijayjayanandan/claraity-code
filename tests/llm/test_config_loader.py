"""Tests for src.llm.config_loader -- LLM configuration loading, saving, resolving."""

import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.llm.config_loader import (
    LLMConfigData,
    SubAgentLLMOverride,
    load_llm_config,
    save_llm_config,
    resolve_llm_config,
    is_llm_configured,
)


# ---------------------------------------------------------------------------
# Module-wide keyring mock (prevents tests from touching real OS credential store)
# ---------------------------------------------------------------------------

_mock_keyring_store = {}

@pytest.fixture(autouse=True)
def mock_keyring():
    """Prevent tests from touching the real OS credential store."""
    _mock_keyring_store.clear()
    with patch("src.llm.credential_store._get_keyring") as mock_get_kr:
        mock_kr = MagicMock()
        mock_kr.get_password.side_effect = lambda svc, usr: _mock_keyring_store.get((svc, usr))
        mock_kr.set_password.side_effect = lambda svc, usr, val: _mock_keyring_store.update({(svc, usr): val})
        mock_get_kr.return_value = mock_kr
        yield mock_kr


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def config_dir(tmp_path):
    """Create a temp .claraity directory with config.yaml."""
    claraity_dir = tmp_path / ".claraity"
    claraity_dir.mkdir()
    return claraity_dir


@pytest.fixture
def config_file(config_dir):
    """Return path to temp config.yaml."""
    return str(config_dir / "config.yaml")


@pytest.fixture
def sample_yaml(config_dir):
    """Write a sample config.yaml and return its path."""
    path = config_dir / "config.yaml"
    path.write_text(
        """\
logging:
  level: DEBUG

llm:
  backend_type: openai
  base_url: http://localhost:8000/v1
  api_key_env: OPENAI_API_KEY
  model: gpt-4o
  context_window: 131072
  temperature: 0.2
  max_tokens: 16384
  top_p: 0.95
  subagents:
    code-reviewer:
      model: gpt-4o
    test-writer:
      model: gemini-2.0-flash
      backend_type: openai
      base_url: http://other-host/v1
""",
        encoding="utf-8",
    )
    return str(path)


# ---------------------------------------------------------------------------
# load_llm_config
# ---------------------------------------------------------------------------

class TestLoadLLMConfig:
    """Tests for load_llm_config()."""

    def test_returns_defaults_when_file_missing(self, tmp_path):
        config = load_llm_config(str(tmp_path / "nonexistent.yaml"))
        assert config.backend_type == "openai"
        assert config.model == ""
        assert config.temperature == 0.2
        assert config.subagents == {}

    def test_returns_defaults_when_no_llm_section(self, config_dir):
        path = config_dir / "config.yaml"
        path.write_text("logging:\n  level: INFO\n", encoding="utf-8")
        config = load_llm_config(str(path))
        assert config.model == ""
        assert config.backend_type == "openai"

    def test_loads_full_config(self, sample_yaml):
        config = load_llm_config(sample_yaml)
        assert config.backend_type == "openai"
        assert config.base_url == "http://localhost:8000/v1"
        assert config.api_key_env == "OPENAI_API_KEY"
        assert config.model == "gpt-4o"
        assert config.context_window == 131072
        assert config.temperature == 0.2
        assert config.max_tokens == 16384
        assert config.top_p == 0.95

    def test_loads_subagent_overrides(self, sample_yaml):
        config = load_llm_config(sample_yaml)
        assert "code-reviewer" in config.subagents
        assert config.subagents["code-reviewer"].model == "gpt-4o"

        assert "test-writer" in config.subagents
        tw = config.subagents["test-writer"]
        assert tw.model == "gemini-2.0-flash"
        assert tw.backend_type == "openai"
        assert tw.base_url == "http://other-host/v1"

    def test_invalid_backend_type_ignored(self, config_dir):
        path = config_dir / "config.yaml"
        path.write_text(
            "llm:\n  backend_type: foobar\n  model: test\n",
            encoding="utf-8",
        )
        config = load_llm_config(str(path))
        # Stays as default because "foobar" is invalid
        assert config.backend_type == "openai"

    def test_invalid_numeric_field_ignored(self, config_dir):
        path = config_dir / "config.yaml"
        path.write_text(
            "llm:\n  model: test\n  temperature: not_a_float\n",
            encoding="utf-8",
        )
        config = load_llm_config(str(path))
        assert config.temperature == 0.2  # default

    def test_invalid_yaml_returns_defaults(self, config_dir):
        path = config_dir / "config.yaml"
        path.write_text("{{{{invalid yaml", encoding="utf-8")
        config = load_llm_config(str(path))
        assert config.model == ""

    def test_empty_file_returns_defaults(self, config_dir):
        path = config_dir / "config.yaml"
        path.write_text("", encoding="utf-8")
        config = load_llm_config(str(path))
        assert config.model == ""

    @patch("src.llm.credential_store.load_api_key", return_value="")
    def test_api_key_migrated_from_yaml_to_keyring(self, mock_load, config_dir):
        """api_key in config.yaml should be migrated to keyring and removed from YAML."""
        mock_kr = MagicMock()
        path = config_dir / "config.yaml"
        path.write_text(
            "llm:\n  api_key: test-secret-key-123\n  model: gpt-4o\n",
            encoding="utf-8",
        )
        with patch("src.llm.credential_store._get_keyring", return_value=mock_kr):
            load_llm_config(str(path))
        # Should have called keyring to migrate
        mock_kr.set_password.assert_called_once_with("claraity", "api_key", "test-secret-key-123")
        # api_key should be removed from the YAML file
        import yaml
        reloaded_yaml = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert "api_key" not in reloaded_yaml.get("llm", {})

    @patch("src.llm.credential_store.load_api_key", return_value="")
    def test_api_key_stays_in_yaml_without_keyring(self, mock_load, config_dir):
        """api_key should stay in config.yaml when keyring is unavailable."""
        path = config_dir / "config.yaml"
        path.write_text(
            "llm:\n  api_key: test-secret-key-123\n  model: gpt-4o\n",
            encoding="utf-8",
        )
        with patch("src.llm.credential_store._get_keyring", return_value=None):
            load_llm_config(str(path))
        # api_key should remain in the YAML file
        import yaml
        reloaded_yaml = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert reloaded_yaml["llm"]["api_key"] == "test-secret-key-123"

    @patch("src.llm.credential_store.save_api_key", return_value=True)
    @patch("src.llm.credential_store.load_api_key", return_value="my-secret-key")
    def test_api_key_loaded_from_keyring(self, mock_load, mock_save, config_dir):
        """api_key should be populated from keyring at load time."""
        path = config_dir / "config.yaml"
        path.write_text(
            "llm:\n  model: gpt-4o\n",
            encoding="utf-8",
        )
        config = load_llm_config(str(path))
        assert config.api_key == "my-secret-key"
        mock_load.assert_called_once()

    def test_api_key_not_saved_to_yaml(self, config_dir):
        """save_llm_config should never write api_key to YAML."""
        path = str(config_dir / "config.yaml")
        config = LLMConfigData(
            api_key="my-secret-key",
            model="gpt-4o",
            base_url="http://localhost:8000/v1",
        )
        save_llm_config(config, path)
        import yaml
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        assert "api_key" not in data.get("llm", {})


# ---------------------------------------------------------------------------
# save_llm_config
# ---------------------------------------------------------------------------

class TestSaveLLMConfig:
    """Tests for save_llm_config()."""

    def test_save_creates_file(self, config_file):
        config = LLMConfigData(model="gpt-4o", base_url="http://localhost:8000/v1")
        assert save_llm_config(config, config_file) is True
        assert Path(config_file).exists()

    def test_save_preserves_logging_section(self, sample_yaml):
        """Save should update llm: but keep logging: intact."""
        config = LLMConfigData(model="new-model", base_url="http://new-url/v1")
        save_llm_config(config, sample_yaml)

        # Re-read raw YAML to verify logging is preserved
        import yaml
        raw = Path(sample_yaml).read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
        assert "logging" in data
        assert data["logging"]["level"] == "DEBUG"
        assert data["llm"]["model"] == "new-model"

    def test_save_writes_subagent_overrides(self, config_file):
        config = LLMConfigData(
            model="gpt-4o",
            base_url="http://localhost:8000/v1",
            subagents={
                "code-reviewer": SubAgentLLMOverride(model="gpt-4o"),
                "test-writer": SubAgentLLMOverride(
                    model="gemini-flash", backend_type="openai"
                ),
            },
        )
        save_llm_config(config, config_file)

        import yaml
        data = yaml.safe_load(Path(config_file).read_text(encoding="utf-8"))
        subs = data["llm"]["subagents"]
        assert subs["code-reviewer"]["model"] == "gpt-4o"
        assert subs["test-writer"]["model"] == "gemini-flash"
        assert subs["test-writer"]["backend_type"] == "openai"

    def test_save_omits_none_subagent_fields(self, config_file):
        """SubAgentLLMOverride fields that are None should not appear in YAML."""
        config = LLMConfigData(
            model="gpt-4o",
            base_url="http://localhost:8000/v1",
            subagents={
                "code-reviewer": SubAgentLLMOverride(model="gpt-4o"),
            },
        )
        save_llm_config(config, config_file)

        import yaml
        data = yaml.safe_load(Path(config_file).read_text(encoding="utf-8"))
        cr = data["llm"]["subagents"]["code-reviewer"]
        assert "backend_type" not in cr
        assert "base_url" not in cr

    def test_roundtrip_load_save_load(self, sample_yaml):
        """Load -> modify -> save -> reload should produce consistent results."""
        config = load_llm_config(sample_yaml)
        config.model = "modified-model"
        config.temperature = 0.5
        save_llm_config(config, sample_yaml)

        reloaded = load_llm_config(sample_yaml)
        assert reloaded.model == "modified-model"
        assert reloaded.temperature == 0.5
        # Subagents should survive the roundtrip
        assert "code-reviewer" in reloaded.subagents


# ---------------------------------------------------------------------------
# resolve_llm_config
# ---------------------------------------------------------------------------

class TestResolveLLMConfig:
    """Tests for resolve_llm_config()."""

    def test_cli_args_override_env_vars(self):
        config = LLMConfigData(model="yaml-model")
        env = {"model": "env-model"}
        cli = {"model": "cli-model"}
        result = resolve_llm_config(env, cli, config)
        assert result.model == "cli-model"

    def test_env_vars_override_yaml(self):
        config = LLMConfigData(model="yaml-model")
        env = {"model": "env-model"}
        cli = {}
        result = resolve_llm_config(env, cli, config)
        assert result.model == "env-model"

    def test_yaml_defaults_used_when_no_overrides(self):
        config = LLMConfigData(model="yaml-model", temperature=0.7)
        result = resolve_llm_config({}, {}, config)
        assert result.model == "yaml-model"
        assert result.temperature == 0.7

    def test_none_values_are_skipped(self):
        config = LLMConfigData(model="yaml-model")
        env = {"model": None}
        cli = {"model": None}
        result = resolve_llm_config(env, cli, config)
        assert result.model == "yaml-model"

    def test_numeric_overrides_converted(self):
        config = LLMConfigData(temperature=0.2, max_tokens=1024)
        env = {"temperature": "0.8", "max_tokens": "4096"}
        result = resolve_llm_config(env, {}, config)
        assert result.temperature == 0.8
        assert result.max_tokens == 4096

    def test_invalid_numeric_ignored(self):
        config = LLMConfigData(temperature=0.2)
        env = {"temperature": "not_a_number"}
        result = resolve_llm_config(env, {}, config)
        assert result.temperature == 0.2  # unchanged

    def test_backend_validated(self):
        config = LLMConfigData(backend_type="openai")
        env = {"backend": "invalid_backend"}
        result = resolve_llm_config(env, {}, config)
        assert result.backend_type == "openai"  # unchanged (invalid ignored)


# ---------------------------------------------------------------------------
# is_llm_configured
# ---------------------------------------------------------------------------

class TestIsLLMConfigured:
    """Tests for is_llm_configured()."""

    def test_returns_true_when_env_var_set(self, tmp_path):
        with patch.dict(os.environ, {"LLM_MODEL": "some-model"}):
            assert is_llm_configured(str(tmp_path / "no-such-file.yaml")) is True

    def test_returns_true_when_config_has_model(self, sample_yaml):
        with patch.dict(os.environ, {}, clear=False):
            # Remove LLM_MODEL from env if present
            os.environ.pop("LLM_MODEL", None)
            assert is_llm_configured(sample_yaml) is True

    def test_returns_false_when_nothing_configured(self, tmp_path):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LLM_MODEL", None)
            assert is_llm_configured(str(tmp_path / "no-such.yaml")) is False


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

class TestDataModels:
    """Tests for LLMConfigData and SubAgentLLMOverride."""

    def test_default_values(self):
        config = LLMConfigData()
        assert config.backend_type == "openai"
        assert config.model == ""
        assert config.base_url == ""
        assert config.api_key == ""
        assert config.api_key_env == "OPENAI_API_KEY"
        assert config.context_window == 131072
        assert config.temperature == 0.2
        assert config.max_tokens == 16384
        assert config.top_p == 0.95
        assert config.subagents == {}

    def test_subagent_override_defaults(self):
        override = SubAgentLLMOverride()
        assert override.model is None
        assert override.backend_type is None
        assert override.base_url is None
        assert override.api_key_env is None
        assert override.context_window is None

    def test_subagent_override_with_values(self):
        override = SubAgentLLMOverride(
            model="gpt-4o",
            backend_type="openai",
            base_url="http://localhost:8000/v1",
        )
        assert override.model == "gpt-4o"
        assert override.backend_type == "openai"
