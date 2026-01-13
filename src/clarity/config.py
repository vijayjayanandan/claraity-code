"""
ClarAIty Configuration

Centralized configuration for all ClarAIty components.
Supports environment variables, config files, and programmatic configuration.
"""

import os
import json
import logging
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


@dataclass
class ClarityConfig:
    """
    Configuration for ClarAIty system.

    Can be loaded from:
    1. Environment variables (CLARITY_*)
    2. Config file (.clarity/config.json)
    3. Programmatic defaults
    """

    # === Core Settings ===
    enabled: bool = True
    """Whether ClarAIty is enabled (can be disabled without removing code)"""

    mode: str = "auto"
    """Mode: 'auto' (smart routing), 'always' (all tasks), 'manual' (explicit only)"""

    # === Database Settings ===
    db_path: str = ".clarity/project.db"
    """Path to SQLite database (relative to working directory)"""

    # === Sync Settings ===
    auto_sync: bool = True
    """Automatically sync filesystem changes to database"""

    watch_patterns: List[str] = field(default_factory=lambda: ["*.py", "*.md", "*.txt"])
    """File patterns to watch for changes"""

    ignore_patterns: List[str] = field(default_factory=lambda: [
        "__pycache__", ".git", ".venv", "venv", "node_modules",
        ".pytest_cache", ".mypy_cache", "*.pyc", "*.pyo", ".DS_Store"
    ])
    """Patterns to ignore when watching"""

    sync_debounce_seconds: float = 2.0
    """Debounce delay for file changes (seconds)"""

    # === Generate Mode Settings ===
    blueprint_timeout_seconds: int = 300
    """Timeout for blueprint approval (5 minutes)"""

    show_approval_ui: bool = True
    """Show browser-based approval UI (if False, CLI summary only)"""

    approval_ui_port: int = 8765
    """Port for approval UI server"""

    auto_open_browser: bool = True
    """Automatically open browser for approval UI"""

    # === API Settings ===
    api_enabled: bool = True
    """Enable FastAPI server"""

    api_host: str = "localhost"
    """API server host"""

    api_port: int = 8766
    """API server port"""

    api_cors_origins: List[str] = field(default_factory=lambda: [
        "http://localhost:3000",
        "http://localhost:8766",
    ])
    """CORS allowed origins for React development"""

    # === LLM Settings ===
    llm_model: str = "qwen-plus"
    """Model for blueprint generation"""

    llm_base_url: Optional[str] = None
    """LLM API base URL (None = use env var or default)"""

    llm_api_key_env: str = "OPENAI_API_KEY"
    """Environment variable for LLM API key (default: OPENAI_API_KEY, can override to DASHSCOPE_API_KEY)"""

    # === Feature Flags ===
    enable_document_mode: bool = True
    """Enable Document Existing mode"""

    enable_generate_mode: bool = True
    """Enable Generate New mode"""

    enable_file_watcher: bool = True
    """Enable filesystem watching"""

    enable_websocket: bool = True
    """Enable WebSocket for real-time updates"""

    # === Logging ===
    log_level: str = "INFO"
    """Logging level (DEBUG, INFO, WARNING, ERROR)"""

    log_file: Optional[str] = None
    """Optional log file path"""

    # === Performance ===
    max_file_size_mb: int = 10
    """Maximum file size to analyze (MB)"""

    max_components_per_file: int = 100
    """Maximum components to extract from single file"""

    parallel_analysis: bool = False
    """Analyze multiple files in parallel (experimental)"""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ClarityConfig':
        """Create from dictionary."""
        return cls(**data)

    @classmethod
    def from_json(cls, json_str: str) -> 'ClarityConfig':
        """Create from JSON string."""
        data = json.loads(json_str)
        return cls.from_dict(data)

    @classmethod
    def from_file(cls, file_path: str) -> 'ClarityConfig':
        """
        Load from config file.

        Args:
            file_path: Path to JSON config file

        Returns:
            ClarityConfig instance
        """
        path = Path(file_path)
        if not path.exists():
            logger.warning(f"Config file not found: {file_path}, using defaults")
            return cls()

        try:
            with open(path, 'r') as f:
                data = json.load(f)
            logger.info(f"Loaded config from {file_path}")
            return cls.from_dict(data)
        except Exception as e:
            logger.error(f"Error loading config from {file_path}: {e}")
            return cls()

    def save_to_file(self, file_path: str):
        """
        Save configuration to file.

        Args:
            file_path: Path to save JSON config
        """
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(path, 'w') as f:
                f.write(self.to_json())
            logger.info(f"Saved config to {file_path}")
        except Exception as e:
            logger.error(f"Error saving config to {file_path}: {e}")

    @classmethod
    def from_env(cls) -> 'ClarityConfig':
        """
        Load from environment variables.

        Environment variables:
        - CLARITY_ENABLED=true/false
        - CLARITY_MODE=auto/always/manual
        - CLARITY_DB_PATH=path/to/db
        - CLARITY_AUTO_SYNC=true/false
        - CLARITY_API_PORT=8766
        - ... etc

        Returns:
            ClarityConfig instance
        """
        config = cls()

        # Parse environment variables
        env_mapping = {
            'CLARITY_ENABLED': ('enabled', lambda x: x.lower() == 'true'),
            'CLARITY_MODE': ('mode', str),
            'CLARITY_DB_PATH': ('db_path', str),
            'CLARITY_AUTO_SYNC': ('auto_sync', lambda x: x.lower() == 'true'),
            'CLARITY_APPROVAL_UI_PORT': ('approval_ui_port', int),
            'CLARITY_API_PORT': ('api_port', int),
            'CLARITY_API_HOST': ('api_host', str),
            'CLARITY_LLM_MODEL': ('llm_model', str),
            'CLARITY_LLM_BASE_URL': ('llm_base_url', str),
            'CLARITY_LLM_API_KEY_ENV': ('llm_api_key_env', str),
            'CLARITY_LOG_LEVEL': ('log_level', str),
        }

        for env_var, (attr_name, converter) in env_mapping.items():
            value = os.getenv(env_var)
            if value is not None:
                try:
                    setattr(config, attr_name, converter(value))
                    logger.debug(f"Loaded {attr_name} from {env_var}")
                except Exception as e:
                    logger.warning(f"Error parsing {env_var}: {e}")

        return config

    @classmethod
    def load(
        cls,
        config_file: Optional[str] = None,
        use_env: bool = True
    ) -> 'ClarityConfig':
        """
        Load configuration with priority:
        1. Config file (if provided)
        2. Environment variables (if use_env=True)
        3. Defaults

        Args:
            config_file: Optional config file path
            use_env: Whether to load from environment variables

        Returns:
            ClarityConfig instance
        """
        # Start with defaults
        config = cls()

        # Load from file if provided
        if config_file:
            file_config = cls.from_file(config_file)
            # Merge (file overrides defaults)
            for key, value in file_config.to_dict().items():
                if value != getattr(cls(), key):  # Only if different from default
                    setattr(config, key, value)

        # Load from env (overrides file and defaults)
        if use_env:
            env_config = cls.from_env()
            for key, value in env_config.to_dict().items():
                if value != getattr(cls(), key):  # Only if different from default
                    setattr(config, key, value)

        logger.info(f"ClarityConfig loaded: enabled={config.enabled}, mode={config.mode}")
        return config

    def validate(self) -> List[str]:
        """
        Validate configuration.

        Returns:
            List of validation errors (empty if valid)
        """
        errors = []

        # Check mode
        if self.mode not in ['auto', 'always', 'manual']:
            errors.append(f"Invalid mode: {self.mode} (must be auto/always/manual)")

        # Check paths
        db_path = Path(self.db_path)
        if db_path.is_absolute() and not db_path.parent.exists():
            errors.append(f"Database parent directory does not exist: {db_path.parent}")

        # Check ports
        if not (1024 <= self.api_port <= 65535):
            errors.append(f"Invalid API port: {self.api_port} (must be 1024-65535)")

        if not (1024 <= self.approval_ui_port <= 65535):
            errors.append(f"Invalid approval UI port: {self.approval_ui_port}")

        # Check log level
        valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        if self.log_level.upper() not in valid_levels:
            errors.append(f"Invalid log level: {self.log_level} (must be one of {valid_levels})")

        # Check performance limits
        if self.max_file_size_mb <= 0:
            errors.append(f"max_file_size_mb must be positive: {self.max_file_size_mb}")

        if self.max_components_per_file <= 0:
            errors.append(f"max_components_per_file must be positive: {self.max_components_per_file}")

        return errors


# Global configuration instance
_global_config: Optional[ClarityConfig] = None


def get_config(
    config_file: Optional[str] = None,
    use_env: bool = True,
    force_reload: bool = False
) -> ClarityConfig:
    """
    Get global configuration instance.

    Args:
        config_file: Optional config file path
        use_env: Whether to load from environment variables
        force_reload: Force reload configuration

    Returns:
        Global ClarityConfig instance
    """
    global _global_config

    if _global_config is None or force_reload:
        _global_config = ClarityConfig.load(config_file, use_env)

        # Validate
        errors = _global_config.validate()
        if errors:
            logger.warning(f"Configuration validation errors: {errors}")

    return _global_config


def set_config(config: ClarityConfig):
    """
    Set global configuration instance.

    Args:
        config: ClarityConfig instance
    """
    global _global_config
    _global_config = config
    logger.info("Global configuration updated")
