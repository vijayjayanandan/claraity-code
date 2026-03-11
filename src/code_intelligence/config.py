"""
Code Intelligence Configuration.

Provides hierarchical configuration loading with:
- Auto-detection of languages from project files
- Hierarchical loading (Repo > User > Environment > Defaults)
- Schema validation for .code-intelligence.json
- Language mappings for file extensions
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class CodeIntelligenceConfig:
    """
    Configuration for Code Intelligence system.

    Supports hierarchical loading:
    - Repo config (.code-intelligence.json in repo root)
    - User config (~/.code-intelligence.json)
    - Environment variables (CODE_INTEL_*)
    - Defaults
    """

    # Language configuration
    languages: list[str] = field(default_factory=list)  # ["python", "typescript"]

    # Resource limits
    max_servers: int = 3  # Max concurrent LSP servers
    cache_size_mb: int = 10  # LSP cache size
    cache_ttl_seconds: int = 300  # Cache TTL (5 minutes)

    # Custom LSP paths (optional)
    lsp_paths: dict[str, str] = field(default_factory=dict)
    # Example: {"python": "/custom/path/to/pyright"}

    # Enabled features
    enabled: bool = True  # Master enable/disable

    @classmethod
    def auto_detect(cls, repo_root: str | None = None) -> "CodeIntelligenceConfig":
        """
        Auto-detect configuration from multiple sources.

        Priority (highest to lowest):
        1. Repo config (.code-intelligence.json in repo root)
        2. User config (~/.code-intelligence.json)
        3. Environment variables (CODE_INTEL_*)
        4. Defaults

        Args:
            repo_root: Optional repository root (auto-detected if None)

        Returns:
            Merged configuration

        Example:
            >>> config = CodeIntelligenceConfig.auto_detect()
            >>> print(config.languages)  # ["python", "typescript"]
            >>> print(config.max_servers)  # 3
        """
        # Find repo root if not provided
        if repo_root is None:
            # Walk up from cwd to find git root
            current = Path.cwd()
            while current != current.parent:
                if (current / ".git").exists():
                    repo_root = str(current)
                    break
                current = current.parent
            else:
                repo_root = str(Path.cwd())  # Fallback to cwd

        # Start with defaults
        config = cls()

        # Layer 1: Environment variables
        env_config = cls.from_env()
        config = config.merge(env_config)

        # Layer 2: User config (~/.code-intelligence.json)
        user_config_path = Path.home() / ".code-intelligence.json"
        if user_config_path.exists():
            user_config = cls.from_file(str(user_config_path))
            config = config.merge(user_config)

        # Layer 3: Repo config (.code-intelligence.json in repo root)
        repo_config_path = Path(repo_root) / ".code-intelligence.json"
        if repo_config_path.exists():
            repo_config = cls.from_file(str(repo_config_path))
            config = config.merge(repo_config)

        # Auto-detect languages if not specified
        if not config.languages:
            config.languages = cls.detect_languages(repo_root)

        return config

    @classmethod
    def from_file(cls, config_path: str) -> "CodeIntelligenceConfig":
        """
        Load configuration from JSON file.

        Expected format (.code-intelligence.json):
        {
            "languages": ["python", "typescript"],
            "max_servers": 3,
            "cache_size_mb": 10,
            "cache_ttl_seconds": 300,
            "lsp_paths": {
                "python": "/custom/pyright"
            },
            "enabled": true
        }

        Args:
            config_path: Path to JSON config file

        Returns:
            Configuration loaded from file

        Raises:
            FileNotFoundError: Config file not found
            ValueError: Invalid JSON or schema

        Example:
            >>> config = CodeIntelligenceConfig.from_file(".code-intelligence.json")
            >>> print(config.languages)
            ["python", "typescript"]
        """
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with path.open("r") as f:
            data = json.load(f)

        # Validate schema (basic)
        if not isinstance(data, dict):
            raise ValueError("Config must be a JSON object")

        # Extract fields (use defaults for missing fields)
        return cls(
            languages=data.get("languages", []),
            max_servers=data.get("max_servers", 3),
            cache_size_mb=data.get("cache_size_mb", 10),
            cache_ttl_seconds=data.get("cache_ttl_seconds", 300),
            lsp_paths=data.get("lsp_paths", {}),
            enabled=data.get("enabled", True),
        )

    @classmethod
    def from_env(cls) -> "CodeIntelligenceConfig":
        """
        Load configuration from environment variables.

        Supported variables:
        - CODE_INTEL_LANGUAGES: Comma-separated languages (e.g., "python,typescript")
        - CODE_INTEL_MAX_SERVERS: Max concurrent servers (e.g., "5")
        - CODE_INTEL_CACHE_SIZE_MB: Cache size in MB (e.g., "20")
        - CODE_INTEL_CACHE_TTL_SECONDS: Cache TTL (e.g., "600")
        - CODE_INTEL_ENABLED: Enable/disable (e.g., "true", "false")

        Returns:
            Configuration from environment variables

        Example:
            >>> import os
            >>> os.environ["CODE_INTEL_LANGUAGES"] = "python,go"
            >>> os.environ["CODE_INTEL_MAX_SERVERS"] = "5"
            >>> config = CodeIntelligenceConfig.from_env()
            >>> print(config.languages)
            ["python", "go"]
            >>> print(config.max_servers)
            5
        """
        config = cls()  # Start with defaults

        # Languages
        if "CODE_INTEL_LANGUAGES" in os.environ:
            langs = os.environ["CODE_INTEL_LANGUAGES"]
            config.languages = [lang.strip() for lang in langs.split(",") if lang.strip()]

        # Max servers
        if "CODE_INTEL_MAX_SERVERS" in os.environ:
            config.max_servers = int(os.environ["CODE_INTEL_MAX_SERVERS"])

        # Cache size
        if "CODE_INTEL_CACHE_SIZE_MB" in os.environ:
            config.cache_size_mb = int(os.environ["CODE_INTEL_CACHE_SIZE_MB"])

        # Cache TTL
        if "CODE_INTEL_CACHE_TTL_SECONDS" in os.environ:
            config.cache_ttl_seconds = int(os.environ["CODE_INTEL_CACHE_TTL_SECONDS"])

        # Enabled
        if "CODE_INTEL_ENABLED" in os.environ:
            config.enabled = os.environ["CODE_INTEL_ENABLED"].lower() in ("true", "1", "yes")

        return config

    def merge(self, other: "CodeIntelligenceConfig") -> "CodeIntelligenceConfig":
        """
        Merge with another config (other takes priority).

        Used for hierarchical config loading:
        defaults.merge(env).merge(user).merge(repo)

        Args:
            other: Config to merge (higher priority)

        Returns:
            New merged config

        Example:
            >>> base = CodeIntelligenceConfig(languages=["python"], max_servers=3)
            >>> override = CodeIntelligenceConfig(max_servers=5)
            >>> merged = base.merge(override)
            >>> print(merged.languages)  # ["python"] (from base)
            >>> print(merged.max_servers)  # 5 (from override)
        """
        return CodeIntelligenceConfig(
            languages=other.languages if other.languages else self.languages,
            max_servers=other.max_servers if other.max_servers != 3 else self.max_servers,
            cache_size_mb=other.cache_size_mb if other.cache_size_mb != 10 else self.cache_size_mb,
            cache_ttl_seconds=other.cache_ttl_seconds
            if other.cache_ttl_seconds != 300
            else self.cache_ttl_seconds,
            lsp_paths={**self.lsp_paths, **other.lsp_paths},  # Merge dicts
            enabled=other.enabled if hasattr(other, "enabled") else self.enabled,
        )

    @staticmethod
    def detect_languages(repo_root: str) -> list[str]:
        """
        Detect languages from project files.

        Detection logic:
        - Scans repo root for common files (package.json, requirements.txt, go.mod, etc.)
        - Maps files to languages
        - Returns unique list of detected languages

        Supported languages:
        - python: requirements.txt, setup.py, pyproject.toml, *.py
        - typescript: package.json + tsconfig.json
        - javascript: package.json (no tsconfig.json)
        - go: go.mod, *.go
        - rust: Cargo.toml, *.rs
        - java: pom.xml, build.gradle, *.java
        - cpp: CMakeLists.txt, *.cpp, *.h
        - csharp: *.csproj, *.cs
        - ruby: Gemfile, *.rb

        Args:
            repo_root: Repository root path

        Returns:
            list of detected languages (e.g., ["python", "typescript"])

        Example:
            >>> langs = CodeIntelligenceConfig.detect_languages("/path/to/repo")
            >>> print(langs)
            ["python", "typescript"]
        """
        repo = Path(repo_root)
        detected = set()

        # Language detection rules
        detection_rules = {
            "python": [
                lambda: (repo / "requirements.txt").exists(),
                lambda: (repo / "setup.py").exists(),
                lambda: (repo / "pyproject.toml").exists(),
                lambda: len(list(repo.rglob("*.py"))) > 0,
            ],
            "typescript": [
                lambda: (repo / "package.json").exists() and (repo / "tsconfig.json").exists(),
                lambda: len(list(repo.rglob("*.ts"))) > 0,
            ],
            "javascript": [
                lambda: (repo / "package.json").exists() and not (repo / "tsconfig.json").exists(),
                lambda: len(list(repo.rglob("*.js"))) > 0,
            ],
            "go": [
                lambda: (repo / "go.mod").exists(),
                lambda: len(list(repo.rglob("*.go"))) > 0,
            ],
            "rust": [
                lambda: (repo / "Cargo.toml").exists(),
                lambda: len(list(repo.rglob("*.rs"))) > 0,
            ],
            "java": [
                lambda: (repo / "pom.xml").exists(),
                lambda: (repo / "build.gradle").exists(),
                lambda: len(list(repo.rglob("*.java"))) > 0,
            ],
            "cpp": [
                lambda: (repo / "CMakeLists.txt").exists(),
                lambda: len(list(repo.rglob("*.cpp"))) > 0 or len(list(repo.rglob("*.h"))) > 0,
            ],
            "csharp": [
                lambda: len(list(repo.rglob("*.csproj"))) > 0,
                lambda: len(list(repo.rglob("*.cs"))) > 0,
            ],
            "ruby": [
                lambda: (repo / "Gemfile").exists(),
                lambda: len(list(repo.rglob("*.rb"))) > 0,
            ],
        }

        # Run detection rules
        for language, rules in detection_rules.items():
            for rule in rules:
                try:
                    if rule():
                        detected.add(language)
                        break  # Language detected, no need to check other rules
                except Exception:
                    continue  # Ignore errors (e.g., permission denied)

        # Prioritize by multilspy support
        # (Python, TypeScript, JavaScript, Go, Rust first)
        priority = ["python", "typescript", "javascript", "go", "rust"]
        result = [lang for lang in priority if lang in detected]
        result.extend([lang for lang in detected if lang not in priority])

        return result
