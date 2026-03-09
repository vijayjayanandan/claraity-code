"""
Centralized logging configuration loader.

Loads logging settings from `.clarity/config.yaml` and resolves them
against environment variables and CLI flags using a layered priority:

    Environment variables  (highest priority)
        > CLI flags
        > config.yaml
        > code defaults    (lowest priority)

Engineering Principles:
- No emojis in code (Windows cp1252 compatibility)
- Graceful degradation: invalid/missing config falls back to defaults
- Never crashes the app on bad config -- warn and continue
"""

import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# =============================================================================
# CONSTANTS
# =============================================================================

DEFAULT_CONFIG_PATH = ".clarity/config.yaml"

VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}

# Map short component names to Python logger hierarchy prefixes.
# Users write "agent: DEBUG" in config; we translate to "src.core.agent".
COMPONENT_LOGGER_MAP: dict[str, str] = {
    "agent": "src.core.agent",
    "tools": "src.tools",
    "llm": "src.llm",
    "ui": "src.ui",
    "memory": "src.memory",
    "subagents": "src.subagents",
    "observability": "src.observability",
    "session": "src.session",
    "integrations": "src.integrations",
}


# =============================================================================
# DATA MODEL
# =============================================================================

@dataclass
class HandlerConfig:
    """Per-handler log level configuration."""
    jsonl_level: str = "INFO"
    logs_db_level: str = "DEBUG"
    errors_db_level: str = "ERROR"


@dataclass
class RetentionConfig:
    """Log retention settings."""
    logs_db_days: int = 7
    errors_db_days: int = 30
    jsonl_max_bytes: int = 52_428_800   # 50 MB
    jsonl_backup_count: int = 5


@dataclass
class LoggingConfig:
    """Complete logging configuration loaded from config.yaml."""
    level: str = "INFO"
    components: dict[str, str] = field(default_factory=dict)
    handlers: HandlerConfig = field(default_factory=HandlerConfig)
    retention: RetentionConfig = field(default_factory=RetentionConfig)


# =============================================================================
# LOADER
# =============================================================================

def _safe_stderr(message: str) -> None:
    """Write warning to stderr without going through logging (avoids recursion)."""
    try:
        print(f"[LogConfigLoader] {message}", file=sys.__stderr__)
    except Exception:
        pass


def _validate_level(level: str, context: str) -> str | None:
    """Validate a log level string. Returns uppercase level or None if invalid."""
    upper = level.upper()
    if upper in VALID_LEVELS:
        return upper
    _safe_stderr(f"Invalid log level '{level}' in {context}, ignoring")
    return None


def load_logging_config(
    config_path: str = DEFAULT_CONFIG_PATH,
) -> LoggingConfig:
    """
    Load logging configuration from YAML file.

    Returns defaults if the file doesn't exist or is invalid.
    Never raises -- always returns a valid LoggingConfig.

    Args:
        config_path: Path to the YAML config file

    Returns:
        LoggingConfig with loaded or default values
    """
    config = LoggingConfig()
    path = Path(config_path)

    if not path.exists():
        return config

    try:
        import yaml
    except ImportError:
        _safe_stderr("PyYAML not installed, using default logging config")
        return config

    try:
        raw = path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
    except Exception as e:
        _safe_stderr(f"Failed to parse {config_path}: {e}, using defaults")
        return config

    if not isinstance(data, dict):
        return config

    log_data = data.get("logging")
    if not isinstance(log_data, dict):
        return config

    # -- Global level --
    if "level" in log_data:
        validated = _validate_level(str(log_data["level"]), "logging.level")
        if validated:
            config.level = validated

    # -- Per-component overrides --
    components = log_data.get("components")
    if isinstance(components, dict):
        for comp_name, comp_level in components.items():
            comp_name = str(comp_name).lower()
            if comp_name not in COMPONENT_LOGGER_MAP:
                _safe_stderr(
                    f"Unknown component '{comp_name}' in config, ignoring. "
                    f"Valid: {', '.join(sorted(COMPONENT_LOGGER_MAP))}"
                )
                continue
            validated = _validate_level(
                str(comp_level), f"components.{comp_name}"
            )
            if validated:
                config.components[comp_name] = validated

    # -- Handler levels --
    handlers = log_data.get("handlers")
    if isinstance(handlers, dict):
        for key, attr in [
            ("jsonl", "jsonl_level"),
            ("logs_db", "logs_db_level"),
            ("errors_db", "errors_db_level"),
        ]:
            if key in handlers:
                validated = _validate_level(
                    str(handlers[key]), f"handlers.{key}"
                )
                if validated:
                    setattr(config.handlers, attr, validated)

    # -- Retention --
    retention = log_data.get("retention")
    if isinstance(retention, dict):
        for key, attr, type_fn in [
            ("logs_db_days", "logs_db_days", int),
            ("errors_db_days", "errors_db_days", int),
            ("jsonl_max_bytes", "jsonl_max_bytes", int),
            ("jsonl_backup_count", "jsonl_backup_count", int),
        ]:
            if key in retention:
                try:
                    val = type_fn(retention[key])
                    if val > 0:
                        setattr(config.retention, attr, val)
                    else:
                        _safe_stderr(
                            f"retention.{key} must be positive, ignoring"
                        )
                except (TypeError, ValueError):
                    _safe_stderr(
                        f"Invalid value for retention.{key}, ignoring"
                    )

    return config


def resolve_logging_config(
    env_level: str | None,
    cli_level: str | None,
    config: LoggingConfig,
) -> LoggingConfig:
    """
    Apply priority layering to resolve the final logging config.

    Priority: env_level > cli_level > config.level > default ("INFO")

    The env/cli overrides only affect the global level.
    Component and handler levels from config.yaml are preserved.

    Note: Mutates and returns the input ``config`` object in-place.

    Args:
        env_level: Value from LOG_LEVEL environment variable (or None)
        cli_level: Value from --log-level CLI flag (or None)
        config: Config loaded from YAML (mutated in-place)

    Returns:
        The same LoggingConfig instance with resolved global level
    """
    # CLI overrides config.yaml
    if cli_level:
        validated = _validate_level(cli_level, "--log-level CLI flag")
        if validated:
            config.level = validated

    # ENV overrides everything
    if env_level:
        validated = _validate_level(env_level, "LOG_LEVEL env var")
        if validated:
            config.level = validated

    return config


def apply_component_levels(components: dict[str, str]) -> None:
    """
    Apply per-component log levels to Python loggers.

    Maps short component names (e.g. "agent") to logger hierarchy
    prefixes (e.g. "src.core.agent") and sets their level.

    Args:
        components: dict of component name -> log level
    """
    for comp_name, level_str in components.items():
        logger_prefix = COMPONENT_LOGGER_MAP.get(comp_name)
        if not logger_prefix:
            continue

        level = getattr(logging, level_str.upper(), None)
        if level is None:
            continue

        logging.getLogger(logger_prefix).setLevel(level)


# =============================================================================
# DEFAULT CONFIG GENERATION
# =============================================================================

_DEFAULT_CONFIG_TEMPLATE = """\
# ClarAIty Logging Configuration
# Edit this file to control logging behavior.
# Priority: Environment variables > CLI flags > this file > code defaults
#
# Environment variable overrides:
#   LOG_LEVEL=DEBUG python -m src.cli --tui
#
# CLI flag overrides:
#   python -m src.cli --tui --log-level debug

logging:
  # Global log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
  level: INFO

  # Per-component overrides (uncomment to customize)
  # components:
  #   agent: DEBUG        # Agent control loop (src.core.agent)
  #   tools: INFO         # Tool execution (src.tools)
  #   llm: WARNING        # LLM backend (src.llm) - suppress streaming noise
  #   ui: INFO            # TUI interface (src.ui)
  #   memory: INFO        # Memory management (src.memory)
  #   subagents: INFO     # Sub-agent execution (src.subagents)
  #   session: INFO       # Session persistence (src.session)
  #   integrations: INFO  # External integrations (src.integrations)
  #   observability: WARNING  # Logging/metrics internals (src.observability)

  # Per-handler level control (what gets written WHERE)
  handlers:
    jsonl: INFO           # JSONL file (.clarity/logs/app.jsonl)
    logs_db: DEBUG        # SQLite queryable store (.clarity/logs/logs.db)
    errors_db: ERROR      # Errors only (.clarity/metrics.db)

  # Retention settings
  retention:
    logs_db_days: 7              # Days to keep logs in logs.db
    errors_db_days: 30           # Days to keep errors in metrics.db
    jsonl_max_bytes: 52428800    # 50MB per JSONL file before rotation
    jsonl_backup_count: 5        # Number of rotated JSONL files to keep
"""


def generate_default_config(config_path: str = DEFAULT_CONFIG_PATH) -> bool:
    """
    Generate default config.yaml if it doesn't exist.

    Args:
        config_path: Path to write the config file

    Returns:
        True if file was created, False if it already exists
    """
    path = Path(config_path)
    if path.exists():
        return False

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_DEFAULT_CONFIG_TEMPLATE, encoding="utf-8")
        return True
    except Exception as e:
        _safe_stderr(f"Failed to generate default config: {e}")
        return False
