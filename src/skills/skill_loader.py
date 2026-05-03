"""Skill loader — reads directory-based skills from .claraity/skills/.

Each skill is a directory containing a main file named skill-<name>.md
with YAML frontmatter, plus optional bundled resources (scripts/, references/,
agents/, assets/).

Directory layout::

    .claraity/skills/
    +-- test-driven-bugfix/
    |   +-- skill-test-driven-bugfix.md   # main skill file (required)
    |   +-- scripts/                      # optional helper scripts
    |   +-- references/                   # optional reference docs
    |   +-- agents/                       # optional subagent prompts
    |   +-- assets/                       # optional templates/files
    +-- code-review/
        +-- skill-code-review.md

Frontmatter format::

    ---
    name: Test-Driven Bug Fix
    description: Fix bugs by writing a failing test first
    category: development
    tags: [bug, fix, test]
    author: Vijay
    arguments: [issue-number]
    argument-hint: [issue-number]
    disable-model-invocation: false
    allowed-tools: []
    ---

    # Instructions here...

The ``id`` is derived from the directory name (e.g. ``test-driven-bugfix/``
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
    """Metadata + body for a single skill."""

    id: str
    name: str
    description: str
    category: str = "general"
    tags: list[str] = field(default_factory=list)
    author: str = ""
    filepath: Path = field(default_factory=lambda: Path())
    body: str = ""
    # Extended frontmatter fields
    arguments: list[str] = field(default_factory=list)
    argument_hint: str = ""
    # Reserved for future use — parsed from frontmatter but not yet enforced.
    # disable_model_invocation: prevents auto-invocation by the LLM (Phase 3).
    # allowed_tools: restricts tool access during skill execution (Phase 3).
    disable_model_invocation: bool = False
    allowed_tools: list[str] = field(default_factory=list)
    # Directory containing the skill (for resolving scripts/, references/, etc.)
    skill_dir: Path = field(default_factory=lambda: Path())


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


def substitute_arguments(body: str, args_string: str, argument_names: list[str]) -> str:
    """Replace $ARGUMENTS, $0, $1, and named $varname placeholders.

    Args:
        body: The skill body text with placeholders.
        args_string: The raw arguments string (e.g. "backend 42").
        argument_names: Named argument list from frontmatter (e.g. ["scope", "issue"]).

    Returns:
        Body with all placeholders replaced.
    """
    # Split args by whitespace, preserving quoted strings
    parts = _split_args(args_string)

    # $ARGUMENTS -> full raw string
    result = body.replace("$ARGUMENTS", args_string)

    # Named arguments: $varname -> positional value
    for i, arg_name in enumerate(argument_names):
        if i < len(parts):
            result = result.replace(f"${arg_name}", parts[i])

    # Positional: $0, $1, $2, etc. — replace via regex to avoid $1 colliding with $10
    import re as _re

    def _replace_positional(match: "_re.Match[str]") -> str:
        idx = int(match.group(1))
        return parts[idx] if idx < len(parts) else match.group(0)

    result = _re.sub(r"\$(\d+)", _replace_positional, result)

    return result


def _split_args(args_string: str) -> list[str]:
    """Split argument string by whitespace, respecting quoted strings."""
    if not args_string.strip():
        return []

    parts: list[str] = []
    current = []
    in_quote = None

    for char in args_string:
        if char in ('"', "'") and in_quote is None:
            in_quote = char
        elif char == in_quote:
            in_quote = None
        elif char in (" ", "\t") and in_quote is None:
            if current:
                parts.append("".join(current))
                current = []
            continue
        else:
            current.append(char)

    if current:
        parts.append("".join(current))

    return parts


class SkillLoader:
    """Loads skill definitions from ``.claraity/skills/<name>/skill-<name>.md``."""

    def __init__(self, working_directory: Path | None = None) -> None:
        root = working_directory or Path.cwd()
        self.skills_dir = root / ".claraity" / "skills"

    def load_all(self) -> list[SkillInfo]:
        """Return all valid skills sorted by (category, name)."""
        if not self.skills_dir.is_dir():
            return []

        skills: list[SkillInfo] = []
        for skill_dir in sorted(self.skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            try:
                skill = self._load_skill_dir(skill_dir)
                skills.append(skill)
            except Exception:
                logger.warning("skill_load_skipped", path=str(skill_dir))
        skills.sort(key=lambda s: (s.category, s.name))
        return skills

    def get_skill(self, skill_id: str) -> SkillInfo | None:
        """Load a single skill by ID (directory name)."""
        skill_dir = self.skills_dir / skill_id
        # Path traversal guard
        try:
            skill_dir.resolve().relative_to(self.skills_dir.resolve())
        except ValueError:
            logger.warning("skill_path_traversal_blocked", skill_id=skill_id)
            return None
        if not skill_dir.is_dir():
            return None
        try:
            return self._load_skill_dir(skill_dir)
        except Exception:
            logger.warning("skill_load_failed", skill_id=skill_id)
            return None

    def _load_skill_dir(self, skill_dir: Path) -> SkillInfo:
        """Parse a skill directory. Raises on invalid format or missing fields."""
        dir_name = skill_dir.name
        skill_file = skill_dir / f"skill-{dir_name}.md"

        if not skill_file.is_file():
            raise ValueError(
                f"Skill directory '{dir_name}' missing main file 'skill-{dir_name}.md'"
            )

        content = skill_file.read_text(encoding="utf-8-sig")
        fm, body = _parse_frontmatter(content)

        name = fm.get("name")
        description = fm.get("description")
        if not name or not description:
            raise ValueError(f"Skill {dir_name} missing required 'name' or 'description'")

        tags_raw = fm.get("tags", [])
        if isinstance(tags_raw, str):
            tags_raw = [t.strip() for t in tags_raw.split(",") if t.strip()]

        # Parse arguments field (can be list or single string)
        arguments_raw = fm.get("arguments", [])
        if isinstance(arguments_raw, str):
            arguments_raw = [a.strip() for a in arguments_raw.split(",") if a.strip()]

        # Parse allowed-tools (can be space-separated string or list)
        allowed_raw = fm.get("allowed-tools", [])
        if isinstance(allowed_raw, str):
            allowed_raw = [t.strip() for t in allowed_raw.split() if t.strip()]

        return SkillInfo(
            id=dir_name,
            name=name,
            description=description,
            category=fm.get("category", "general"),
            tags=tags_raw,
            author=fm.get("author", ""),
            filepath=skill_file,
            body=body,
            arguments=arguments_raw,
            argument_hint=fm.get("argument-hint", ""),
            disable_model_invocation=bool(fm.get("disable-model-invocation", False)),
            allowed_tools=allowed_raw,
            skill_dir=skill_dir,
        )
