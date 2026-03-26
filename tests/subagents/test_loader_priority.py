"""Tests for SubAgentConfigLoader priority ordering.

Verifies the load order introduced for configurable subagents:
  user ~/.clarity/agents/  (lowest)
  built-in Python constants
  project .clarity/agents/ (highest -- can override built-ins)
"""

import pytest
from pathlib import Path
from unittest.mock import patch

from src.subagents.config import SubAgentConfig, SubAgentConfigLoader


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_md(directory: Path, name: str, description: str, prompt: str) -> Path:
    """Write a minimal valid subagent .md file and return its path."""
    directory.mkdir(parents=True, exist_ok=True)
    content = f"""---
name: {name}
description: {description}
---

{prompt}
"""
    path = directory / f"{name}.md"
    path.write_text(content, encoding="utf-8")
    return path


def _builtin_names() -> set[str]:
    """Return the set of names loaded from Python constants."""
    loader = SubAgentConfigLoader()
    with patch.object(Path, "exists", return_value=False):
        configs = loader.discover_all()
    return set(configs.keys())


# ---------------------------------------------------------------------------
# Source stamping
# ---------------------------------------------------------------------------

class TestSourceStamping:
    """Every loaded config must carry a source field in metadata."""

    def test_builtin_source_is_stamped(self, tmp_path):
        loader = SubAgentConfigLoader(working_directory=tmp_path)
        configs = loader.discover_all()

        for name, config in configs.items():
            assert "source" in config.metadata, (
                f"Built-in subagent '{name}' missing 'source' in metadata"
            )
            assert config.metadata["source"] == "builtin", (
                f"Expected source='builtin' for '{name}', got {config.metadata['source']!r}"
            )

    def test_project_source_is_stamped(self, tmp_path):
        project_dir = tmp_path / ".clarity" / "agents"
        _make_md(project_dir, "custom-agent", "A custom agent", "You are custom.")

        loader = SubAgentConfigLoader(working_directory=tmp_path)
        configs = loader.discover_all()

        assert "custom-agent" in configs
        assert configs["custom-agent"].metadata["source"] == "project"

    def test_user_source_is_stamped(self, tmp_path):
        user_dir = tmp_path / "user_home" / ".clarity" / "agents"
        _make_md(user_dir, "user-agent", "A user agent", "You are a user agent.")

        loader = SubAgentConfigLoader(working_directory=tmp_path)
        with patch("src.subagents.config.Path.home", return_value=tmp_path / "user_home"):
            configs = loader.discover_all()

        assert "user-agent" in configs
        assert configs["user-agent"].metadata["source"] == "user"


# ---------------------------------------------------------------------------
# Priority: project overrides built-in
# ---------------------------------------------------------------------------

class TestProjectOverridesBuiltin:
    """Project .clarity/agents/ configs must win over built-in Python constants."""

    def test_project_overrides_builtin_code_reviewer(self, tmp_path):
        """Forking code-reviewer via .clarity/agents/ replaces the built-in."""
        project_dir = tmp_path / ".clarity" / "agents"
        _make_md(
            project_dir,
            "code-reviewer",
            "My custom code reviewer",
            "You are my custom reviewer.",
        )

        loader = SubAgentConfigLoader(working_directory=tmp_path)
        configs = loader.discover_all()

        assert "code-reviewer" in configs
        config = configs["code-reviewer"]
        assert config.metadata["source"] == "project", (
            "Project config should have source='project', not 'builtin'"
        )
        assert config.description == "My custom code reviewer"
        assert "my custom reviewer" in config.system_prompt.lower()

    def test_project_overrides_any_builtin(self, tmp_path):
        """Every built-in can be overridden by a project-level file."""
        builtin_names = _builtin_names()
        assert builtin_names, "No built-ins loaded -- test setup problem"

        # Pick the first built-in and override it
        target = sorted(builtin_names)[0]
        project_dir = tmp_path / ".clarity" / "agents"
        _make_md(project_dir, target, "Overridden agent", "You are overridden.")

        loader = SubAgentConfigLoader(working_directory=tmp_path)
        configs = loader.discover_all()

        assert configs[target].metadata["source"] == "project"
        assert configs[target].description == "Overridden agent"

    def test_non_overridden_builtins_still_load(self, tmp_path):
        """Overriding one built-in must not remove the others."""
        builtin_names = _builtin_names()
        assert len(builtin_names) > 1, "Need at least 2 built-ins for this test"

        target = sorted(builtin_names)[0]
        project_dir = tmp_path / ".clarity" / "agents"
        _make_md(project_dir, target, "Overridden", "Overridden prompt.")

        loader = SubAgentConfigLoader(working_directory=tmp_path)
        configs = loader.discover_all()

        remaining = builtin_names - {target}
        for name in remaining:
            assert name in configs, f"Built-in '{name}' disappeared after override"
            assert configs[name].metadata["source"] == "builtin"

    def test_project_adds_new_custom_subagent(self, tmp_path):
        """Project dir can also add brand-new subagents not in built-ins."""
        project_dir = tmp_path / ".clarity" / "agents"
        _make_md(project_dir, "my-custom-agent", "My custom agent", "You are custom.")

        loader = SubAgentConfigLoader(working_directory=tmp_path)
        configs = loader.discover_all()

        assert "my-custom-agent" in configs
        assert configs["my-custom-agent"].metadata["source"] == "project"


# ---------------------------------------------------------------------------
# Priority: built-in overrides user global
# ---------------------------------------------------------------------------

class TestBuiltinOverridesUser:
    """Built-in Python constants must win over user ~/.clarity/agents/."""

    def test_builtin_beats_user_global(self, tmp_path):
        user_home = tmp_path / "user_home"
        user_dir = user_home / ".clarity" / "agents"
        _make_md(
            user_dir,
            "code-reviewer",
            "User-level code reviewer",
            "You are a user-level reviewer.",
        )

        loader = SubAgentConfigLoader(working_directory=tmp_path)
        with patch("src.subagents.config.Path.home", return_value=user_home):
            configs = loader.discover_all()

        config = configs["code-reviewer"]
        assert config.metadata["source"] == "builtin", (
            "Built-in should win over user-global config"
        )

    def test_user_global_adds_new_agents(self, tmp_path):
        """User global dir can add new subagents not present in built-ins."""
        user_home = tmp_path / "user_home"
        user_dir = user_home / ".clarity" / "agents"
        _make_md(user_dir, "my-user-agent", "User agent", "You are a user agent.")

        loader = SubAgentConfigLoader(working_directory=tmp_path)
        with patch("src.subagents.config.Path.home", return_value=user_home):
            configs = loader.discover_all()

        assert "my-user-agent" in configs
        assert configs["my-user-agent"].metadata["source"] == "user"


# ---------------------------------------------------------------------------
# Priority: project overrides user global
# ---------------------------------------------------------------------------

class TestProjectOverridesUser:
    """Project configs must also win over user-global configs."""

    def test_project_beats_user_for_custom_agent(self, tmp_path):
        user_home = tmp_path / "user_home"
        user_dir = user_home / ".clarity" / "agents"
        project_dir = tmp_path / ".clarity" / "agents"

        _make_md(user_dir, "shared-agent", "User version", "User prompt.")
        _make_md(project_dir, "shared-agent", "Project version", "Project prompt.")

        loader = SubAgentConfigLoader(working_directory=tmp_path)
        with patch("src.subagents.config.Path.home", return_value=user_home):
            configs = loader.discover_all()

        assert configs["shared-agent"].metadata["source"] == "project"
        assert configs["shared-agent"].description == "Project version"


# ---------------------------------------------------------------------------
# Full three-tier stack
# ---------------------------------------------------------------------------

class TestFullPriorityStack:
    """Verify the complete three-tier ordering in one scenario."""

    def test_full_stack(self, tmp_path):
        """
        All three sources active simultaneously.
        Expected winners:
          - code-reviewer  -> project (overrides builtin)
          - user-only      -> user    (no competition)
          - project-only   -> project (no competition)
          - other builtins -> builtin (no override)
        """
        user_home = tmp_path / "user_home"
        user_dir = user_home / ".clarity" / "agents"
        project_dir = tmp_path / ".clarity" / "agents"

        _make_md(user_dir, "code-reviewer", "User reviewer", "User reviewer prompt.")
        _make_md(user_dir, "user-only-agent", "User only", "User only prompt.")
        _make_md(project_dir, "code-reviewer", "Project reviewer", "Project reviewer prompt.")
        _make_md(project_dir, "project-only-agent", "Project only", "Project only prompt.")

        loader = SubAgentConfigLoader(working_directory=tmp_path)
        with patch("src.subagents.config.Path.home", return_value=user_home):
            configs = loader.discover_all()

        # Project beats user AND builtin for code-reviewer
        assert configs["code-reviewer"].metadata["source"] == "project"
        assert configs["code-reviewer"].description == "Project reviewer"

        # User-only agent present with correct source
        assert configs["user-only-agent"].metadata["source"] == "user"

        # Project-only agent present
        assert configs["project-only-agent"].metadata["source"] == "project"

        # Other built-ins still present and untouched
        builtin_names = _builtin_names() - {"code-reviewer"}
        for name in builtin_names:
            assert name in configs, f"Built-in '{name}' missing from full-stack result"
            assert configs[name].metadata["source"] == "builtin"


# ---------------------------------------------------------------------------
# Reload clears cache
# ---------------------------------------------------------------------------

class TestReload:
    """reload() must pick up changes made after initial discovery."""

    def test_reload_picks_up_new_project_file(self, tmp_path):
        loader = SubAgentConfigLoader(working_directory=tmp_path)
        configs_before = loader.discover_all()
        assert "late-agent" not in configs_before

        # Add a new file after initial load
        project_dir = tmp_path / ".clarity" / "agents"
        _make_md(project_dir, "late-agent", "Late agent", "You arrived late.")

        configs_after = loader.reload()
        assert "late-agent" in configs_after
        assert configs_after["late-agent"].metadata["source"] == "project"

    def test_reload_picks_up_override_added_after_initial_load(self, tmp_path):
        loader = SubAgentConfigLoader(working_directory=tmp_path)
        configs_before = loader.discover_all()
        assert configs_before["code-reviewer"].metadata["source"] == "builtin"

        # Fork code-reviewer after initial load
        project_dir = tmp_path / ".clarity" / "agents"
        _make_md(project_dir, "code-reviewer", "Forked reviewer", "Forked prompt.")

        configs_after = loader.reload()
        assert configs_after["code-reviewer"].metadata["source"] == "project"
        assert configs_after["code-reviewer"].description == "Forked reviewer"
