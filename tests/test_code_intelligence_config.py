"""
Unit tests for Code Intelligence Configuration.

Tests cover:
- Auto-detection of languages from project files
- Hierarchical configuration loading
- File-based configuration
- Environment variable configuration
- Configuration merging
"""

import json
import os
import pytest
from pathlib import Path

from src.code_intelligence.config import CodeIntelligenceConfig


class TestLanguageDetection:
    """Test automatic language detection from project files."""

    def test_detect_python_from_requirements(self, tmp_path):
        """Test Python detection from requirements.txt."""
        (tmp_path / "requirements.txt").write_text("flask==2.0.0")

        langs = CodeIntelligenceConfig.detect_languages(str(tmp_path))

        assert "python" in langs

    def test_detect_python_from_setup_py(self, tmp_path):
        """Test Python detection from setup.py."""
        (tmp_path / "setup.py").write_text("from setuptools import setup")

        langs = CodeIntelligenceConfig.detect_languages(str(tmp_path))

        assert "python" in langs

    def test_detect_python_from_pyproject(self, tmp_path):
        """Test Python detection from pyproject.toml."""
        (tmp_path / "pyproject.toml").write_text("[tool.poetry]")

        langs = CodeIntelligenceConfig.detect_languages(str(tmp_path))

        assert "python" in langs

    def test_detect_python_from_py_files(self, tmp_path):
        """Test Python detection from .py files."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("print('hello')")

        langs = CodeIntelligenceConfig.detect_languages(str(tmp_path))

        assert "python" in langs

    def test_detect_typescript(self, tmp_path):
        """Test TypeScript detection."""
        (tmp_path / "package.json").write_text('{"name": "app"}')
        (tmp_path / "tsconfig.json").write_text('{}')

        langs = CodeIntelligenceConfig.detect_languages(str(tmp_path))

        assert "typescript" in langs

    def test_detect_javascript_not_typescript(self, tmp_path):
        """Test JavaScript detection (without tsconfig.json)."""
        (tmp_path / "package.json").write_text('{"name": "app"}')
        # No tsconfig.json

        langs = CodeIntelligenceConfig.detect_languages(str(tmp_path))

        assert "javascript" in langs
        assert "typescript" not in langs

    def test_detect_go(self, tmp_path):
        """Test Go detection."""
        (tmp_path / "go.mod").write_text("module example.com/app")

        langs = CodeIntelligenceConfig.detect_languages(str(tmp_path))

        assert "go" in langs

    def test_detect_rust(self, tmp_path):
        """Test Rust detection."""
        (tmp_path / "Cargo.toml").write_text('[package]\nname = "app"')

        langs = CodeIntelligenceConfig.detect_languages(str(tmp_path))

        assert "rust" in langs

    def test_detect_java_from_pom(self, tmp_path):
        """Test Java detection from pom.xml."""
        (tmp_path / "pom.xml").write_text('<project></project>')

        langs = CodeIntelligenceConfig.detect_languages(str(tmp_path))

        assert "java" in langs

    def test_detect_java_from_gradle(self, tmp_path):
        """Test Java detection from build.gradle."""
        (tmp_path / "build.gradle").write_text('plugins { id "java" }')

        langs = CodeIntelligenceConfig.detect_languages(str(tmp_path))

        assert "java" in langs

    def test_detect_cpp(self, tmp_path):
        """Test C++ detection."""
        (tmp_path / "CMakeLists.txt").write_text('cmake_minimum_required(VERSION 3.0)')

        langs = CodeIntelligenceConfig.detect_languages(str(tmp_path))

        assert "cpp" in langs

    def test_detect_csharp(self, tmp_path):
        """Test C# detection."""
        (tmp_path / "App.csproj").write_text('<Project></Project>')

        langs = CodeIntelligenceConfig.detect_languages(str(tmp_path))

        assert "csharp" in langs

    def test_detect_ruby(self, tmp_path):
        """Test Ruby detection."""
        (tmp_path / "Gemfile").write_text('source "https://rubygems.org"')

        langs = CodeIntelligenceConfig.detect_languages(str(tmp_path))

        assert "ruby" in langs

    def test_detect_multiple_languages(self, tmp_path):
        """Test detection of multiple languages in same project."""
        (tmp_path / "requirements.txt").write_text("flask==2.0.0")
        (tmp_path / "package.json").write_text('{"name": "app"}')
        (tmp_path / "tsconfig.json").write_text('{}')

        langs = CodeIntelligenceConfig.detect_languages(str(tmp_path))

        assert "python" in langs
        assert "typescript" in langs
        assert len(langs) == 2

    def test_detect_prioritizes_supported_languages(self, tmp_path):
        """Test that multilspy-supported languages are prioritized."""
        (tmp_path / "requirements.txt").write_text("flask==2.0.0")
        (tmp_path / "Gemfile").write_text('source "https://rubygems.org"')

        langs = CodeIntelligenceConfig.detect_languages(str(tmp_path))

        # Python should come before Ruby (multilspy priority)
        assert langs.index("python") < langs.index("ruby")

    def test_detect_empty_repo(self, tmp_path):
        """Test detection on empty repository."""
        langs = CodeIntelligenceConfig.detect_languages(str(tmp_path))

        assert langs == []


class TestConfigFromFile:
    """Test loading configuration from JSON files."""

    def test_from_file_all_fields(self, tmp_path):
        """Test loading config with all fields specified."""
        config_file = tmp_path / ".code-intelligence.json"
        config_file.write_text(json.dumps({
            "languages": ["python", "typescript"],
            "max_servers": 5,
            "cache_size_mb": 20,
            "cache_ttl_seconds": 600,
            "lsp_paths": {"python": "/custom/pyright"},
            "enabled": True
        }))

        config = CodeIntelligenceConfig.from_file(str(config_file))

        assert config.languages == ["python", "typescript"]
        assert config.max_servers == 5
        assert config.cache_size_mb == 20
        assert config.cache_ttl_seconds == 600
        assert config.lsp_paths == {"python": "/custom/pyright"}
        assert config.enabled is True

    def test_from_file_partial_fields(self, tmp_path):
        """Test loading config with only some fields (uses defaults)."""
        config_file = tmp_path / ".code-intelligence.json"
        config_file.write_text(json.dumps({
            "languages": ["python"],
            "max_servers": 7
        }))

        config = CodeIntelligenceConfig.from_file(str(config_file))

        assert config.languages == ["python"]
        assert config.max_servers == 7
        assert config.cache_size_mb == 10  # Default
        assert config.cache_ttl_seconds == 300  # Default
        assert config.enabled is True  # Default

    def test_from_file_not_found(self, tmp_path):
        """Test loading non-existent config file."""
        with pytest.raises(FileNotFoundError, match="Config file not found"):
            CodeIntelligenceConfig.from_file(str(tmp_path / "nonexistent.json"))

    def test_from_file_invalid_json(self, tmp_path):
        """Test loading invalid JSON."""
        config_file = tmp_path / ".code-intelligence.json"
        config_file.write_text("not valid json{")

        with pytest.raises(json.JSONDecodeError):
            CodeIntelligenceConfig.from_file(str(config_file))

    def test_from_file_not_dict(self, tmp_path):
        """Test loading JSON that's not a dict."""
        config_file = tmp_path / ".code-intelligence.json"
        config_file.write_text('["not", "a", "dict"]')

        with pytest.raises(ValueError, match="Config must be a JSON object"):
            CodeIntelligenceConfig.from_file(str(config_file))


class TestConfigFromEnv:
    """Test loading configuration from environment variables."""

    def test_from_env_all_variables(self):
        """Test loading all environment variables."""
        os.environ["CODE_INTEL_LANGUAGES"] = "python,go"
        os.environ["CODE_INTEL_MAX_SERVERS"] = "7"
        os.environ["CODE_INTEL_CACHE_SIZE_MB"] = "50"
        os.environ["CODE_INTEL_CACHE_TTL_SECONDS"] = "1200"
        os.environ["CODE_INTEL_ENABLED"] = "true"

        config = CodeIntelligenceConfig.from_env()

        assert config.languages == ["python", "go"]
        assert config.max_servers == 7
        assert config.cache_size_mb == 50
        assert config.cache_ttl_seconds == 1200
        assert config.enabled is True

        # Cleanup
        for key in ["CODE_INTEL_LANGUAGES", "CODE_INTEL_MAX_SERVERS",
                    "CODE_INTEL_CACHE_SIZE_MB", "CODE_INTEL_CACHE_TTL_SECONDS",
                    "CODE_INTEL_ENABLED"]:
            del os.environ[key]

    def test_from_env_enabled_variations(self):
        """Test different variations of CODE_INTEL_ENABLED."""
        # Test "true"
        os.environ["CODE_INTEL_ENABLED"] = "true"
        assert CodeIntelligenceConfig.from_env().enabled is True

        # Test "1"
        os.environ["CODE_INTEL_ENABLED"] = "1"
        assert CodeIntelligenceConfig.from_env().enabled is True

        # Test "yes"
        os.environ["CODE_INTEL_ENABLED"] = "yes"
        assert CodeIntelligenceConfig.from_env().enabled is True

        # Test "false"
        os.environ["CODE_INTEL_ENABLED"] = "false"
        assert CodeIntelligenceConfig.from_env().enabled is False

        # Test "0"
        os.environ["CODE_INTEL_ENABLED"] = "0"
        assert CodeIntelligenceConfig.from_env().enabled is False

        del os.environ["CODE_INTEL_ENABLED"]

    def test_from_env_no_variables(self):
        """Test loading with no environment variables (uses defaults)."""
        config = CodeIntelligenceConfig.from_env()

        assert config.languages == []
        assert config.max_servers == 3
        assert config.cache_size_mb == 10
        assert config.cache_ttl_seconds == 300
        assert config.enabled is True

    def test_from_env_languages_with_spaces(self):
        """Test language parsing with spaces."""
        os.environ["CODE_INTEL_LANGUAGES"] = " python , typescript , go "

        config = CodeIntelligenceConfig.from_env()

        assert config.languages == ["python", "typescript", "go"]

        del os.environ["CODE_INTEL_LANGUAGES"]


class TestConfigMerge:
    """Test configuration merging."""

    def test_merge_languages(self):
        """Test merging languages (other takes priority)."""
        base = CodeIntelligenceConfig(languages=["python"])
        override = CodeIntelligenceConfig(languages=["typescript", "go"])

        merged = base.merge(override)

        assert merged.languages == ["typescript", "go"]

    def test_merge_languages_empty_other(self):
        """Test merging with empty languages in other (base wins)."""
        base = CodeIntelligenceConfig(languages=["python"])
        override = CodeIntelligenceConfig(languages=[])

        merged = base.merge(override)

        assert merged.languages == ["python"]

    def test_merge_max_servers(self):
        """Test merging max_servers."""
        base = CodeIntelligenceConfig(max_servers=3)
        override = CodeIntelligenceConfig(max_servers=7)

        merged = base.merge(override)

        assert merged.max_servers == 7

    def test_merge_cache_settings(self):
        """Test merging cache settings."""
        base = CodeIntelligenceConfig(cache_size_mb=10, cache_ttl_seconds=300)
        override = CodeIntelligenceConfig(cache_size_mb=50, cache_ttl_seconds=600)

        merged = base.merge(override)

        assert merged.cache_size_mb == 50
        assert merged.cache_ttl_seconds == 600

    def test_merge_lsp_paths(self):
        """Test merging LSP paths (dicts are merged)."""
        base = CodeIntelligenceConfig(lsp_paths={"python": "/base/pyright"})
        override = CodeIntelligenceConfig(lsp_paths={"typescript": "/override/tsserver"})

        merged = base.merge(override)

        assert merged.lsp_paths == {
            "python": "/base/pyright",
            "typescript": "/override/tsserver"
        }

    def test_merge_lsp_paths_override_same_key(self):
        """Test merging LSP paths with same key (override wins)."""
        base = CodeIntelligenceConfig(lsp_paths={"python": "/base/pyright"})
        override = CodeIntelligenceConfig(lsp_paths={"python": "/override/pyright"})

        merged = base.merge(override)

        assert merged.lsp_paths == {"python": "/override/pyright"}


class TestAutoDetect:
    """Test automatic configuration detection."""

    def test_auto_detect_with_repo_config(self, tmp_path):
        """Test auto-detect with repo config file."""
        # Create repo config
        config_file = tmp_path / ".code-intelligence.json"
        config_file.write_text(json.dumps({
            "languages": ["python"],
            "max_servers": 5
        }))

        config = CodeIntelligenceConfig.auto_detect(repo_root=str(tmp_path))

        assert config.languages == ["python"]
        assert config.max_servers == 5

    def test_auto_detect_without_config(self, tmp_path):
        """Test auto-detect without config (auto-detects languages)."""
        # Create Python project
        (tmp_path / "requirements.txt").write_text("flask==2.0.0")

        config = CodeIntelligenceConfig.auto_detect(repo_root=str(tmp_path))

        assert "python" in config.languages
        assert config.max_servers == 3  # Default

    def test_auto_detect_hierarchical(self, tmp_path):
        """Test hierarchical config loading (repo > user > env > defaults)."""
        # Create user config (if it doesn't interfere with real user config)
        # For this test, we'll just test that repo config overrides env

        # Set env
        os.environ["CODE_INTEL_MAX_SERVERS"] = "10"

        # Create repo config (should override env)
        config_file = tmp_path / ".code-intelligence.json"
        config_file.write_text(json.dumps({
            "max_servers": 5
        }))

        config = CodeIntelligenceConfig.auto_detect(repo_root=str(tmp_path))

        assert config.max_servers == 5  # Repo overrides env

        del os.environ["CODE_INTEL_MAX_SERVERS"]

    def test_auto_detect_empty_repo(self, tmp_path):
        """Test auto-detect on empty repo (uses all defaults)."""
        config = CodeIntelligenceConfig.auto_detect(repo_root=str(tmp_path))

        assert config.languages == []
        assert config.max_servers == 3
        assert config.cache_size_mb == 10
        assert config.enabled is True


class TestDefaultConfig:
    """Test default configuration values."""

    def test_default_values(self):
        """Test that default config has expected values."""
        config = CodeIntelligenceConfig()

        assert config.languages == []
        assert config.max_servers == 3
        assert config.cache_size_mb == 10
        assert config.cache_ttl_seconds == 300
        assert config.lsp_paths == {}
        assert config.enabled is True
