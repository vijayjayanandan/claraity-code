# Code Intelligence Configuration

**Status**: Ready for implementation
**Estimated Time**: 0.5 hours
**Lines of Code**: ~150 LOC
**Dependencies**: pathlib, os, json

---

## Overview

The **CodeIntelligenceConfig** provides hierarchical configuration loading with:

- **Auto-detection** - Detects languages from project files automatically
- **Hierarchical loading** - Repo config > User config > Environment variables > Defaults
- **Schema validation** - Validates .code-intelligence.json format
- **Language mappings** - Maps file extensions to LSP languages

### Why Configuration Matters

Different projects need different LSP configurations:
- **Language selection** - Python vs TypeScript vs Go
- **Resource limits** - Max concurrent LSP servers
- **Cache settings** - Cache size and TTL
- **Custom paths** - LSP server binary locations

**Expected Impact:**
- **Zero-config default** - Works out-of-box for 90% of projects
- **Flexible overrides** - Power users can customize everything
- **Portable** - Config files checked into git

---

## Architecture

```
CodeIntelligenceConfig
    │
    ├─> languages: List[str] (auto-detected or configured)
    ├─> max_servers: int (default: 3)
    ├─> cache_size_mb: int (default: 10)
    ├─> cache_ttl_seconds: int (default: 300)
    ├─> lsp_paths: Dict[str, str] (custom LSP binary paths)
    │
    └─> Methods:
        ├─> auto_detect() -> CodeIntelligenceConfig
        ├─> from_file(path) -> CodeIntelligenceConfig
        ├─> from_env() -> CodeIntelligenceConfig
        ├─> merge(other) -> CodeIntelligenceConfig
        └─> detect_languages(repo_root) -> List[str]

Configuration Hierarchy (priority order):
    1. Repo config: .code-intelligence.json (highest priority)
    2. User config: ~/.code-intelligence.json
    3. Environment variables: CODE_INTEL_*
    4. Defaults (lowest priority)
```

---

## Public Interface

### Class: CodeIntelligenceConfig

```python
from typing import List, Dict, Optional
from dataclasses import dataclass, field
from pathlib import Path

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
    languages: List[str] = field(default_factory=list)  # ["python", "typescript"]

    # Resource limits
    max_servers: int = 3  # Max concurrent LSP servers
    cache_size_mb: int = 10  # LSP cache size
    cache_ttl_seconds: int = 300  # Cache TTL (5 minutes)

    # Custom LSP paths (optional)
    lsp_paths: Dict[str, str] = field(default_factory=dict)
    # Example: {"python": "/custom/path/to/pyright"}

    # Enabled features
    enabled: bool = True  # Master enable/disable

    @classmethod
    def auto_detect(cls, repo_root: Optional[str] = None) -> "CodeIntelligenceConfig":
        """Auto-detect config from repo + env + defaults."""

    @classmethod
    def from_file(cls, config_path: str) -> "CodeIntelligenceConfig":
        """Load config from JSON file."""

    @classmethod
    def from_env(cls) -> "CodeIntelligenceConfig":
        """Load config from environment variables."""

    def merge(self, other: "CodeIntelligenceConfig") -> "CodeIntelligenceConfig":
        """Merge with another config (other takes priority)."""

    @staticmethod
    def detect_languages(repo_root: str) -> List[str]:
        """Detect languages from project files."""
```

---

## Implementation Details

### Method: auto_detect

```python
@classmethod
def auto_detect(cls, repo_root: Optional[str] = None) -> "CodeIntelligenceConfig":
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
    import os
    from pathlib import Path

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
```

**Example**:
```python
# Repo has .code-intelligence.json:
# {"languages": ["python"], "max_servers": 5}

# User has ~/.code-intelligence.json:
# {"cache_size_mb": 20}

# Environment has:
# export CODE_INTEL_ENABLED=true

config = CodeIntelligenceConfig.auto_detect()
# Result:
# languages=["python"] (from repo config)
# max_servers=5 (from repo config)
# cache_size_mb=20 (from user config)
# enabled=True (from env)
```

---

### Method: from_file

```python
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
    import json
    from pathlib import Path

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
```

**Example**:
```json
{
  "languages": ["python", "typescript"],
  "max_servers": 5,
  "cache_size_mb": 20,
  "lsp_paths": {
    "python": "/usr/local/bin/pyright-langserver"
  }
}
```

---

### Method: from_env

```python
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
    import os

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
```

---

### Method: merge

```python
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
        cache_ttl_seconds=other.cache_ttl_seconds if other.cache_ttl_seconds != 300 else self.cache_ttl_seconds,
        lsp_paths={**self.lsp_paths, **other.lsp_paths},  # Merge dicts
        enabled=other.enabled if hasattr(other, 'enabled') else self.enabled,
    )
```

---

### Method: detect_languages

```python
@staticmethod
def detect_languages(repo_root: str) -> List[str]:
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
        List of detected languages (e.g., ["python", "typescript"])

    Example:
        >>> langs = CodeIntelligenceConfig.detect_languages("/path/to/repo")
        >>> print(langs)
        ["python", "typescript"]
    """
    from pathlib import Path

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
```

**Example**:
```python
# Repo structure:
# /project
#   ├─ requirements.txt  (Python detected)
#   ├─ package.json      (JS/TS detected)
#   ├─ tsconfig.json     (TypeScript confirmed)
#   └─ src/
#      ├─ main.py
#      └─ app.ts

langs = CodeIntelligenceConfig.detect_languages("/project")
# Result: ["python", "typescript"]
```

---

## Acceptance Criteria

### Functional Requirements

- [ ] **Auto-detection** works for 9 languages
- [ ] **Hierarchical loading** respects priority (repo > user > env > defaults)
- [ ] **File loading** parses .code-intelligence.json correctly
- [ ] **Environment loading** reads CODE_INTEL_* variables
- [ ] **Merge** combines configs correctly (higher priority wins)

### Quality Metrics

- [ ] **Test coverage**: 90%+
- [ ] **All languages tested**: Python, TypeScript, JavaScript, Go, Rust, Java, C++, C#, Ruby
- [ ] **Edge cases**: Empty repo, missing config, invalid JSON

---

## Testing Strategy

### Unit Tests (tests/test_config.py)

```python
import pytest
from pathlib import Path
import json
import os

def test_auto_detect_python(tmp_path):
    """Test auto-detect for Python project."""
    # Create Python project
    (tmp_path / "requirements.txt").write_text("flask==2.0.0")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')")

    config = CodeIntelligenceConfig.auto_detect(repo_root=str(tmp_path))
    assert "python" in config.languages

def test_auto_detect_typescript(tmp_path):
    """Test auto-detect for TypeScript project."""
    (tmp_path / "package.json").write_text('{"name": "app"}')
    (tmp_path / "tsconfig.json").write_text('{}')

    config = CodeIntelligenceConfig.auto_detect(repo_root=str(tmp_path))
    assert "typescript" in config.languages

def test_hierarchical_loading(tmp_path):
    """Test repo config overrides user config."""
    # User config
    user_config = Path.home() / ".code-intelligence.json"
    user_config.write_text('{"max_servers": 10}')

    # Repo config
    repo_config = tmp_path / ".code-intelligence.json"
    repo_config.write_text('{"max_servers": 5, "languages": ["python"]}')

    config = CodeIntelligenceConfig.auto_detect(repo_root=str(tmp_path))

    assert config.max_servers == 5  # Repo overrides user
    assert config.languages == ["python"]  # From repo

    # Cleanup
    user_config.unlink()

def test_from_env():
    """Test environment variable loading."""
    os.environ["CODE_INTEL_LANGUAGES"] = "python,go"
    os.environ["CODE_INTEL_MAX_SERVERS"] = "7"

    config = CodeIntelligenceConfig.from_env()

    assert config.languages == ["python", "go"]
    assert config.max_servers == 7

    # Cleanup
    del os.environ["CODE_INTEL_LANGUAGES"]
    del os.environ["CODE_INTEL_MAX_SERVERS"]
```

---

## Implementation Patterns

### Pattern: Zero-Config Default

```python
# Works out-of-box with no configuration
config = CodeIntelligenceConfig.auto_detect()
# Auto-detects languages, uses sensible defaults
```

### Pattern: Repo-Level Customization

```json
// .code-intelligence.json (checked into git)
{
  "languages": ["python", "typescript"],
  "max_servers": 5
}
```

### Pattern: User-Level Customization

```json
// ~/.code-intelligence.json (user-specific)
{
  "cache_size_mb": 50,
  "lsp_paths": {
    "python": "/custom/pyright"
  }
}
```

### Antipattern: Hardcoding Paths

```python
# BAD: Hardcoded paths won't work across machines
config = CodeIntelligenceConfig(
    lsp_paths={"python": "/Users/alice/bin/pyright"}
)

# GOOD: Use auto-detect or repo config
config = CodeIntelligenceConfig.auto_detect()
```

---

## File Location

**Path**: `src/code_intelligence/config.py`

---

**Status**: ✅ Ready for implementation
**Next**: Read [05_TOOLS.md](05_TOOLS.md)
