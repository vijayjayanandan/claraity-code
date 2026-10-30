"""
Pytest configuration for all tests.

This file is automatically loaded by pytest before running any tests.
"""

import os

import pytest

# Disable observability in all tests to prevent OTEL connection errors
# This must be set before any imports that trigger observability initialization
os.environ["OBSERVABILITY_ENABLED"] = "false"


@pytest.fixture(autouse=True)
def _isolate_global_skills(monkeypatch, tmp_path_factory):
    """Point the global skills dir (~/.claraity/skills/) at an empty temp dir.

    Without this, every test that builds a SkillLoader, ContextBuilder, or
    reminder reads the developer's real global skills. Tests that exercise the
    global tier pass ``global_dir`` explicitly.
    """
    empty = tmp_path_factory.mktemp("no-global-skills")
    monkeypatch.setattr("src.skills.skill_loader._default_global_dir", lambda: empty)
    return empty
