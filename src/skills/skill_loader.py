"""Skill loader — reads .claraity/skills/*.md files with YAML frontmatter.

Skills are markdown files containing procedural instructions that get injected
into the agent's system prompt when a user explicitly selects them.

File format::

    ---
    name: Test-Driven Bug Fix
    description: Fix bugs by writing a failing test first
    category: development
    tags: [bug, fix, test]
    author: Vijay
    created: 2026-04-26
    ---

    # Instructions here...

The ``id`` is derived from the filename stem (e.g. ``test-driven-bugfix.md``
-> ``"test-driven-bugfix"``).  Frontmatter ``name`` and ``description`` are
required; all other fields are optional.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from src.observability import get_logger

logger = get_logger(__name__)


@dataclass
class SkillInfo:
    """Metadata + body for a single skill file."""

    id: str
    name: str
    description: str
    category: str = "general"
    tags: list[str] = field(default_factory=list)
    author: str = ""
    filepath: Path = field(default_factory=lambda: Path())
    body: str = ""


def _parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Parse Markdown file with YAML frontmatter.

    Returns (frontmatter_dict, markdown_body).
    Raises ValueError on invalid format.
    """
    pattern = r"^---\s*\n(.*?)\n---\s*\n(.*)$"
    match = re.match(pattern, content, re.DOTALL)
    if not match:
        raise ValueError("Expected YAML frontmatter between --- delimiters")

    frontmatter_yaml = match.group(1)
    markdown_body = match.group(2)

    try:
        frontmatter = yaml.safe_load(frontmatter_yaml)
        if frontmatter is None:
            frontmatter = {}
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML frontmatter: {e}")

    if not isinstance(frontmatter, dict):
        raise ValueError(f"Frontmatter must be a YAML dict, got {type(frontmatter)}")

    return frontmatter, markdown_body


class SkillLoader:
    """Loads skill definitions from ``.claraity/skills/*.md``."""

    def __init__(self, working_directory: Path | None = None) -> None:
        root = working_directory or Path.cwd()
        self.skills_dir = root / ".claraity" / "skills"

    def load_all(self) -> list[SkillInfo]:
        """Return all valid skills sorted by (category, name)."""
        if not self.skills_dir.is_dir():
            return []

        skills: list[SkillInfo] = []
        for path in sorted(self.skills_dir.glob("*.md")):
            try:
                skill = self._load_file(path)
                skills.append(skill)
            except Exception:
                logger.warning("skill_load_skipped", path=str(path))
        skills.sort(key=lambda s: (s.category, s.name))
        return skills

    def get_skill(self, skill_id: str) -> SkillInfo | None:
        """Load a single skill by ID (filename stem)."""
        path = self.skills_dir / f"{skill_id}.md"
        # Path traversal guard: resolved path must stay inside skills_dir
        try:
            path.resolve().relative_to(self.skills_dir.resolve())
        except ValueError:
            logger.warning("skill_path_traversal_blocked", skill_id=skill_id)
            return None
        if not path.is_file():
            return None
        try:
            return self._load_file(path)
        except Exception:
            logger.warning("skill_load_failed", skill_id=skill_id)
            return None

    def _load_file(self, path: Path) -> SkillInfo:
        """Parse one skill file. Raises on invalid format or missing fields."""
        content = path.read_text(encoding="utf-8-sig")
        fm, body = _parse_frontmatter(content)

        name = fm.get("name")
        description = fm.get("description")
        if not name or not description:
            raise ValueError(f"Skill {path.name} missing required 'name' or 'description'")

        tags_raw = fm.get("tags", [])
        if isinstance(tags_raw, str):
            tags_raw = [t.strip() for t in tags_raw.split(",") if t.strip()]

        return SkillInfo(
            id=path.stem,
            name=name,
            description=description,
            category=fm.get("category", "general"),
            tags=tags_raw,
            author=fm.get("author", ""),
            filepath=path,
            body=body,
        )
