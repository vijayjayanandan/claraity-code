"""
Test suite for src.observability.log_config_loader.

Coverage:
- load_logging_config: valid full config, missing file, partial config,
  invalid YAML, empty file, non-dict root, invalid level, unknown component,
  valid components, negative retention values
- resolve_logging_config: env overrides, cli overrides, env beats cli,
  neither set, invalid env level
- apply_component_levels: sets Python logger levels, ignores unknown components
- generate_default_config: creates file, skips existing, content is valid YAML

Total: 20 tests

How to run:
    pytest tests/observability/test_log_config_loader.py -v
"""

import logging
from pathlib import Path

import pytest

from src.observability.log_config_loader import (
    COMPONENT_LOGGER_MAP,
    HandlerConfig,
    LoggingConfig,
    RetentionConfig,
    apply_component_levels,
    generate_default_config,
    load_logging_config,
    resolve_logging_config,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_yaml(path: Path, text: str) -> str:
    """Write YAML text to a file and return its string path."""
    path.write_text(text, encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------------------
# 1-10. load_logging_config
# ---------------------------------------------------------------------------

class TestLoadLoggingConfigFullConfig:
    """Test loading a complete, valid YAML configuration."""

    def test_load_full_config(self, tmp_path):
        """All fields set in YAML are reflected in the returned LoggingConfig."""
        config_file = tmp_path / "config.yaml"
        yaml_content = """\
logging:
  level: DEBUG
  components:
    agent: WARNING
    llm: ERROR
  handlers:
    jsonl: DEBUG
    logs_db: INFO
    errors_db: CRITICAL
  retention:
    logs_db_days: 14
    errors_db_days: 60
    jsonl_max_bytes: 104857600
    jsonl_backup_count: 10
"""
        config_path = _write_yaml(config_file, yaml_content)
        cfg = load_logging_config(config_path)

        # Global level
        assert cfg.level == "DEBUG"

        # Components
        assert cfg.components == {"agent": "WARNING", "llm": "ERROR"}

        # Handlers
        assert cfg.handlers.jsonl_level == "DEBUG"
        assert cfg.handlers.logs_db_level == "INFO"
        assert cfg.handlers.errors_db_level == "CRITICAL"

        # Retention
        assert cfg.retention.logs_db_days == 14
        assert cfg.retention.errors_db_days == 60
        assert cfg.retention.jsonl_max_bytes == 104_857_600
        assert cfg.retention.jsonl_backup_count == 10


class TestLoadLoggingConfigMissingFile:
    """Test behavior when config file does not exist."""

    def test_missing_file_returns_defaults(self, tmp_path):
        """Returns default LoggingConfig when file doesn't exist."""
        config_path = str(tmp_path / "nonexistent" / "config.yaml")
        cfg = load_logging_config(config_path)

        assert cfg.level == "INFO"
        assert cfg.components == {}
        assert cfg.handlers.jsonl_level == "INFO"
        assert cfg.handlers.logs_db_level == "DEBUG"
        assert cfg.handlers.errors_db_level == "ERROR"
        assert cfg.retention.logs_db_days == 7
        assert cfg.retention.errors_db_days == 30
        assert cfg.retention.jsonl_max_bytes == 52_428_800
        assert cfg.retention.jsonl_backup_count == 5


class TestLoadLoggingConfigPartial:
    """Test loading a config with only some fields set."""

    def test_partial_config_only_level(self, tmp_path):
        """Only level is set; handlers, retention, components get defaults."""
        config_file = tmp_path / "config.yaml"
        yaml_content = """\
logging:
  level: ERROR
"""
        config_path = _write_yaml(config_file, yaml_content)
        cfg = load_logging_config(config_path)

        assert cfg.level == "ERROR"
        assert cfg.components == {}
        assert cfg.handlers.jsonl_level == "INFO"
        assert cfg.handlers.logs_db_level == "DEBUG"
        assert cfg.handlers.errors_db_level == "ERROR"
        assert cfg.retention.logs_db_days == 7


class TestLoadLoggingConfigInvalidYaml:
    """Test behavior with corrupt YAML content."""

    def test_invalid_yaml_returns_defaults(self, tmp_path):
        """Corrupt YAML content returns defaults without crashing."""
        config_file = tmp_path / "config.yaml"
        yaml_content = """\
logging:
  level: [this is broken
    - not: valid: yaml: ::
  {{{{
"""
        config_path = _write_yaml(config_file, yaml_content)
        cfg = load_logging_config(config_path)

        # Should fall back to all defaults
        assert cfg.level == "INFO"
        assert cfg.components == {}
        assert isinstance(cfg.handlers, HandlerConfig)
        assert isinstance(cfg.retention, RetentionConfig)


class TestLoadLoggingConfigEmptyFile:
    """Test behavior with an empty config file."""

    def test_empty_file_returns_defaults(self, tmp_path):
        """Empty file returns defaults (yaml.safe_load returns None)."""
        config_file = tmp_path / "config.yaml"
        config_path = _write_yaml(config_file, "")
        cfg = load_logging_config(config_path)

        assert cfg.level == "INFO"
        assert cfg.components == {}


class TestLoadLoggingConfigNonDictRoot:
    """Test behavior when YAML root is not a dict."""

    def test_non_dict_root_returns_defaults(self, tmp_path):
        """YAML that parses to a list or scalar returns defaults."""
        config_file = tmp_path / "config.yaml"
        yaml_content = """\
- item1
- item2
- item3
"""
        config_path = _write_yaml(config_file, yaml_content)
        cfg = load_logging_config(config_path)

        assert cfg.level == "INFO"
        assert cfg.components == {}

    def test_scalar_root_returns_defaults(self, tmp_path):
        """YAML that parses to a plain string returns defaults."""
        config_file = tmp_path / "config.yaml"
        config_path = _write_yaml(config_file, "just a string")
        cfg = load_logging_config(config_path)

        assert cfg.level == "INFO"


class TestLoadLoggingConfigInvalidLevel:
    """Test behavior with an invalid global log level name."""

    def test_invalid_level_uses_default(self, tmp_path):
        """Invalid level like 'VERBOSE' is rejected; default 'INFO' is used."""
        config_file = tmp_path / "config.yaml"
        yaml_content = """\
logging:
  level: VERBOSE
"""
        config_path = _write_yaml(config_file, yaml_content)
        cfg = load_logging_config(config_path)

        assert cfg.level == "INFO"

    def test_invalid_handler_level_uses_default(self, tmp_path):
        """Invalid handler level leaves the default in place."""
        config_file = tmp_path / "config.yaml"
        yaml_content = """\
logging:
  handlers:
    jsonl: TRACE
"""
        config_path = _write_yaml(config_file, yaml_content)
        cfg = load_logging_config(config_path)

        assert cfg.handlers.jsonl_level == "INFO"  # default preserved


class TestLoadLoggingConfigUnknownComponent:
    """Test behavior with an unknown component name."""

    def test_unknown_component_is_skipped(self, tmp_path):
        """Unknown component warns but does not crash, and is not included."""
        config_file = tmp_path / "config.yaml"
        yaml_content = """\
logging:
  components:
    agent: DEBUG
    nonexistent_module: WARNING
    llm: ERROR
"""
        config_path = _write_yaml(config_file, yaml_content)
        cfg = load_logging_config(config_path)

        # Valid components are kept; unknown is skipped
        assert "agent" in cfg.components
        assert "llm" in cfg.components
        assert "nonexistent_module" not in cfg.components
        assert len(cfg.components) == 2


class TestLoadLoggingConfigValidComponents:
    """Test that valid component-level overrides are parsed correctly."""

    def test_valid_components_parsed(self, tmp_path):
        """Components with valid names and levels are correctly stored."""
        config_file = tmp_path / "config.yaml"
        yaml_content = """\
logging:
  components:
    agent: DEBUG
    llm: WARNING
    tools: ERROR
    memory: CRITICAL
"""
        config_path = _write_yaml(config_file, yaml_content)
        cfg = load_logging_config(config_path)

        assert cfg.components["agent"] == "DEBUG"
        assert cfg.components["llm"] == "WARNING"
        assert cfg.components["tools"] == "ERROR"
        assert cfg.components["memory"] == "CRITICAL"


class TestLoadLoggingConfigNegativeRetention:
    """Test behavior with negative or zero retention values."""

    def test_negative_retention_uses_defaults(self, tmp_path):
        """Negative retention values are rejected; defaults are preserved."""
        config_file = tmp_path / "config.yaml"
        yaml_content = """\
logging:
  retention:
    logs_db_days: -5
    errors_db_days: 0
    jsonl_max_bytes: -1
    jsonl_backup_count: 0
"""
        config_path = _write_yaml(config_file, yaml_content)
        cfg = load_logging_config(config_path)

        # All invalid -> defaults preserved
        assert cfg.retention.logs_db_days == 7
        assert cfg.retention.errors_db_days == 30
        assert cfg.retention.jsonl_max_bytes == 52_428_800
        assert cfg.retention.jsonl_backup_count == 5

    def test_mixed_valid_and_negative_retention(self, tmp_path):
        """Valid retention values are kept while invalid ones get defaults."""
        config_file = tmp_path / "config.yaml"
        yaml_content = """\
logging:
  retention:
    logs_db_days: 14
    errors_db_days: -1
"""
        config_path = _write_yaml(config_file, yaml_content)
        cfg = load_logging_config(config_path)

        assert cfg.retention.logs_db_days == 14  # valid, kept
        assert cfg.retention.errors_db_days == 30  # invalid, default preserved


# ---------------------------------------------------------------------------
# 11-15. resolve_logging_config
# ---------------------------------------------------------------------------

class TestResolveLoggingConfigEnvOverrides:
    """Test that environment-level override takes highest priority."""

    def test_env_overrides_config_level(self):
        """env_level='ERROR' overrides config.level='DEBUG'."""
        cfg = LoggingConfig(level="DEBUG")
        result = resolve_logging_config(
            env_level="ERROR", cli_level=None, config=cfg
        )
        assert result.level == "ERROR"

    def test_env_overrides_preserves_other_fields(self):
        """env override only affects global level; components/handlers unchanged."""
        cfg = LoggingConfig(
            level="DEBUG",
            components={"agent": "WARNING"},
            handlers=HandlerConfig(jsonl_level="DEBUG"),
        )
        result = resolve_logging_config(
            env_level="CRITICAL", cli_level=None, config=cfg
        )
        assert result.level == "CRITICAL"
        assert result.components == {"agent": "WARNING"}
        assert result.handlers.jsonl_level == "DEBUG"


class TestResolveLoggingConfigCliOverrides:
    """Test that CLI-level override beats config.yaml."""

    def test_cli_overrides_config_level(self):
        """cli_level='WARNING' overrides config.level='DEBUG'."""
        cfg = LoggingConfig(level="DEBUG")
        result = resolve_logging_config(
            env_level=None, cli_level="WARNING", config=cfg
        )
        assert result.level == "WARNING"


class TestResolveLoggingConfigEnvBeatsCli:
    """Test that env_level takes priority over cli_level."""

    def test_env_beats_cli(self):
        """When both env and CLI are set, env wins."""
        cfg = LoggingConfig(level="INFO")
        result = resolve_logging_config(
            env_level="ERROR", cli_level="DEBUG", config=cfg
        )
        assert result.level == "ERROR"


class TestResolveLoggingConfigNeitherSet:
    """Test behavior when neither env nor CLI level is provided."""

    def test_config_level_preserved(self):
        """Config level is preserved when no overrides are present."""
        cfg = LoggingConfig(level="WARNING")
        result = resolve_logging_config(
            env_level=None, cli_level=None, config=cfg
        )
        assert result.level == "WARNING"

    def test_default_level_preserved(self):
        """Default 'INFO' level is preserved when config has no override."""
        cfg = LoggingConfig()
        result = resolve_logging_config(
            env_level=None, cli_level=None, config=cfg
        )
        assert result.level == "INFO"


class TestResolveLoggingConfigInvalidEnvLevel:
    """Test that an invalid env level is ignored."""

    def test_invalid_env_level_ignored(self):
        """Invalid env level is ignored; config level preserved."""
        cfg = LoggingConfig(level="WARNING")
        result = resolve_logging_config(
            env_level="BOGUS", cli_level=None, config=cfg
        )
        assert result.level == "WARNING"

    def test_invalid_cli_level_ignored(self):
        """Invalid CLI level is also ignored; config level preserved."""
        cfg = LoggingConfig(level="ERROR")
        result = resolve_logging_config(
            env_level=None, cli_level="NOTAVALIDLEVEL", config=cfg
        )
        assert result.level == "ERROR"


# ---------------------------------------------------------------------------
# 16-17. apply_component_levels
# ---------------------------------------------------------------------------

class TestApplyComponentLevels:
    """Test that apply_component_levels sets Python logger levels correctly."""

    def test_sets_logger_levels_for_known_components(self):
        """Known components have their Python loggers set to the specified level."""
        components = {"agent": "DEBUG", "llm": "WARNING"}
        apply_component_levels(components)

        agent_logger = logging.getLogger("src.core.agent")
        llm_logger = logging.getLogger("src.llm")

        assert agent_logger.level == logging.DEBUG
        assert llm_logger.level == logging.WARNING

    def test_unknown_component_ignored(self):
        """Unknown component names are silently skipped without crashing."""
        components = {
            "tools": "ERROR",
            "fictional_module": "DEBUG",
        }
        # Should not raise
        apply_component_levels(components)

        tools_logger = logging.getLogger("src.tools")
        assert tools_logger.level == logging.ERROR

    def test_empty_components_dict(self):
        """Empty dict does nothing and does not crash."""
        apply_component_levels({})  # no-op, should not raise


# ---------------------------------------------------------------------------
# 18-20. generate_default_config
# ---------------------------------------------------------------------------

class TestGenerateDefaultConfig:
    """Test default config file generation."""

    def test_creates_file_when_missing(self, tmp_path):
        """Creates config file when it does not exist, returns True."""
        config_path = str(tmp_path / ".claraity" / "config.yaml")
        result = generate_default_config(config_path)

        assert result is True
        assert Path(config_path).exists()

        content = Path(config_path).read_text(encoding="utf-8")
        assert "logging:" in content
        assert "level:" in content

    def test_does_not_overwrite_existing(self, tmp_path):
        """Returns False and does not overwrite when file already exists."""
        config_file = tmp_path / "config.yaml"
        original_content = "# my custom config\nlogging:\n  level: ERROR\n"
        config_file.write_text(original_content, encoding="utf-8")

        result = generate_default_config(str(config_file))

        assert result is False
        # Content should be unchanged
        assert config_file.read_text(encoding="utf-8") == original_content

    def test_generated_content_is_valid_yaml(self, tmp_path):
        """Generated file can be loaded back as valid YAML and parsed."""
        config_path = str(tmp_path / "config.yaml")
        generate_default_config(config_path)

        # The generated file should load successfully
        cfg = load_logging_config(config_path)

        assert cfg.level == "INFO"
        assert cfg.handlers.jsonl_level == "INFO"
        assert cfg.handlers.logs_db_level == "DEBUG"
        assert cfg.handlers.errors_db_level == "ERROR"
        assert cfg.retention.logs_db_days == 7
        assert cfg.retention.errors_db_days == 30
        assert cfg.retention.jsonl_max_bytes == 52_428_800
        assert cfg.retention.jsonl_backup_count == 5

    def test_creates_parent_directories(self, tmp_path):
        """Creates intermediate parent directories if needed."""
        config_path = str(tmp_path / "deep" / "nested" / "dir" / "config.yaml")
        result = generate_default_config(config_path)

        assert result is True
        assert Path(config_path).exists()
