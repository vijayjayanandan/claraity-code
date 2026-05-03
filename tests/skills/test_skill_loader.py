"""Tests for the directory-based skill loader."""

from pathlib import Path

import pytest

from src.skills.skill_loader import (
    SkillInfo,
    SkillLoader,
    _parse_frontmatter,
    _split_args,
    substitute_arguments,
)


# ---------------------------------------------------------------------------
# Frontmatter parser
# ---------------------------------------------------------------------------


class TestParseFrontmatter:
    def test_valid_frontmatter(self):
        content = "---\nname: Test\ndescription: A test\n---\n\nBody here.\n"
        fm, body = _parse_frontmatter(content)
        assert fm["name"] == "Test"
        assert fm["description"] == "A test"
        assert "Body here." in body

    def test_missing_frontmatter_raises(self):
        with pytest.raises(ValueError, match="Expected YAML frontmatter"):
            _parse_frontmatter("No frontmatter at all")

    def test_empty_frontmatter(self):
        content = "---\n\n---\n\nBody\n"
        fm, body = _parse_frontmatter(content)
        assert fm == {}
        assert "Body" in body

    def test_invalid_yaml_raises(self):
        content = "---\n[invalid: yaml: here\n---\n\nBody\n"
        with pytest.raises(ValueError, match="Invalid YAML"):
            _parse_frontmatter(content)


# ---------------------------------------------------------------------------
# Argument splitting
# ---------------------------------------------------------------------------


class TestSplitArgs:
    def test_empty_string(self):
        assert _split_args("") == []
        assert _split_args("   ") == []

    def test_simple_args(self):
        assert _split_args("backend 42") == ["backend", "42"]

    def test_quoted_args(self):
        assert _split_args('hello "world foo" bar') == ["hello", "world foo", "bar"]

    def test_single_quoted(self):
        assert _split_args("hello 'world foo' bar") == ["hello", "world foo", "bar"]

    def test_single_arg(self):
        assert _split_args("backend") == ["backend"]


# ---------------------------------------------------------------------------
# Argument substitution
# ---------------------------------------------------------------------------


class TestSubstituteArguments:
    def test_arguments_placeholder(self):
        result = substitute_arguments("Review $ARGUMENTS", "backend src/", [])
        assert result == "Review backend src/"

    def test_positional_placeholders(self):
        result = substitute_arguments("File: $0, Line: $1", "main.py 42", [])
        assert result == "File: main.py, Line: 42"

    def test_named_arguments(self):
        result = substitute_arguments(
            "Scope: $scope, Issue: $issue",
            "backend 123",
            ["scope", "issue"],
        )
        assert result == "Scope: backend, Issue: 123"

    def test_no_args_no_crash(self):
        result = substitute_arguments("No placeholders here", "", [])
        assert result == "No placeholders here"

    def test_missing_positional_left_as_is(self):
        result = substitute_arguments("$0 and $1", "only-one", [])
        assert result == "only-one and $1"

    def test_missing_named_left_as_is(self):
        result = substitute_arguments("$scope and $issue", "backend", ["scope", "issue"])
        assert result == "backend and $issue"


# ---------------------------------------------------------------------------
# SkillLoader — directory-based
# ---------------------------------------------------------------------------


def _create_skill_dir(skills_dir: Path, name: str, content: str) -> Path:
    """Helper to create a skill directory with skill-<name>.md."""
    skill_dir = skills_dir / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skill_dir / f"skill-{name}.md"
    skill_file.write_text(content, encoding="utf-8")
    return skill_dir


class TestSkillLoader:
    def test_load_valid_skill(self, tmp_path: Path):
        skills_dir = tmp_path / ".claraity" / "skills"
        _create_skill_dir(
            skills_dir,
            "my-skill",
            "---\nname: My Skill\ndescription: Does things\ncategory: dev\ntags: [a, b]\n---\n\nInstructions here.\n",
        )

        loader = SkillLoader(working_directory=tmp_path)
        skills = loader.load_all()

        assert len(skills) == 1
        s = skills[0]
        assert s.id == "my-skill"
        assert s.name == "My Skill"
        assert s.description == "Does things"
        assert s.category == "dev"
        assert s.tags == ["a", "b"]
        assert "Instructions here." in s.body
        assert s.skill_dir == skills_dir / "my-skill"
        assert s.filepath == skills_dir / "my-skill" / "skill-my-skill.md"

    def test_empty_directory(self, tmp_path: Path):
        skills_dir = tmp_path / ".claraity" / "skills"
        skills_dir.mkdir(parents=True)

        loader = SkillLoader(working_directory=tmp_path)
        assert loader.load_all() == []

    def test_no_skills_directory(self, tmp_path: Path):
        loader = SkillLoader(working_directory=tmp_path)
        assert loader.load_all() == []

    def test_missing_skill_file_skipped(self, tmp_path: Path):
        skills_dir = tmp_path / ".claraity" / "skills"
        # Create directory without the expected skill-<name>.md
        (skills_dir / "bad-skill").mkdir(parents=True)

        loader = SkillLoader(working_directory=tmp_path)
        assert loader.load_all() == []

    def test_malformed_frontmatter_skipped(self, tmp_path: Path):
        skills_dir = tmp_path / ".claraity" / "skills"
        _create_skill_dir(
            skills_dir,
            "good",
            "---\nname: Good\ndescription: Valid\n---\n\nBody\n",
        )
        _create_skill_dir(skills_dir, "bad", "No frontmatter here")

        loader = SkillLoader(working_directory=tmp_path)
        skills = loader.load_all()
        assert len(skills) == 1
        assert skills[0].id == "good"

    def test_missing_name_skipped(self, tmp_path: Path):
        skills_dir = tmp_path / ".claraity" / "skills"
        _create_skill_dir(
            skills_dir,
            "no-name",
            "---\ndescription: Has description but no name\n---\n\nBody\n",
        )

        loader = SkillLoader(working_directory=tmp_path)
        assert loader.load_all() == []

    def test_missing_description_skipped(self, tmp_path: Path):
        skills_dir = tmp_path / ".claraity" / "skills"
        _create_skill_dir(
            skills_dir,
            "no-desc",
            "---\nname: Has name but no description\n---\n\nBody\n",
        )

        loader = SkillLoader(working_directory=tmp_path)
        assert loader.load_all() == []

    def test_id_from_directory_name(self, tmp_path: Path):
        skills_dir = tmp_path / ".claraity" / "skills"
        _create_skill_dir(
            skills_dir,
            "test-driven-bugfix",
            "---\nname: Test-Driven Bug Fix\ndescription: TDD bugfix\n---\n\nBody\n",
        )

        loader = SkillLoader(working_directory=tmp_path)
        skills = loader.load_all()
        assert skills[0].id == "test-driven-bugfix"

    def test_get_skill_by_id(self, tmp_path: Path):
        skills_dir = tmp_path / ".claraity" / "skills"
        _create_skill_dir(
            skills_dir,
            "review",
            "---\nname: Review\ndescription: Code review\n---\n\nReview steps.\n",
        )

        loader = SkillLoader(working_directory=tmp_path)
        skill = loader.get_skill("review")
        assert skill is not None
        assert skill.name == "Review"

    def test_get_skill_nonexistent(self, tmp_path: Path):
        skills_dir = tmp_path / ".claraity" / "skills"
        skills_dir.mkdir(parents=True)

        loader = SkillLoader(working_directory=tmp_path)
        assert loader.get_skill("nonexistent") is None

    def test_get_skill_path_traversal_blocked(self, tmp_path: Path):
        skills_dir = tmp_path / ".claraity" / "skills"
        skills_dir.mkdir(parents=True)

        loader = SkillLoader(working_directory=tmp_path)
        assert loader.get_skill("../../etc/passwd") is None
        assert loader.get_skill("../../../secrets") is None

    def test_default_category(self, tmp_path: Path):
        skills_dir = tmp_path / ".claraity" / "skills"
        _create_skill_dir(
            skills_dir,
            "simple",
            "---\nname: Simple\ndescription: No category\n---\n\nBody\n",
        )

        loader = SkillLoader(working_directory=tmp_path)
        assert loader.load_all()[0].category == "general"

    def test_tags_as_csv_string(self, tmp_path: Path):
        skills_dir = tmp_path / ".claraity" / "skills"
        _create_skill_dir(
            skills_dir,
            "csv-tags",
            "---\nname: CSV Tags\ndescription: Tags as string\ntags: bug, fix, test\n---\n\nBody\n",
        )

        loader = SkillLoader(working_directory=tmp_path)
        skill = loader.load_all()[0]
        assert skill.tags == ["bug", "fix", "test"]

    def test_sorted_by_category_then_name(self, tmp_path: Path):
        skills_dir = tmp_path / ".claraity" / "skills"
        _create_skill_dir(
            skills_dir,
            "z-skill",
            "---\nname: Z Skill\ndescription: Desc\ncategory: alpha\n---\n\nBody\n",
        )
        _create_skill_dir(
            skills_dir,
            "a-skill",
            "---\nname: A Skill\ndescription: Desc\ncategory: beta\n---\n\nBody\n",
        )
        _create_skill_dir(
            skills_dir,
            "m-skill",
            "---\nname: M Skill\ndescription: Desc\ncategory: alpha\n---\n\nBody\n",
        )

        loader = SkillLoader(working_directory=tmp_path)
        skills = loader.load_all()
        names = [s.name for s in skills]
        assert names == ["M Skill", "Z Skill", "A Skill"]

    def test_multiple_skills(self, tmp_path: Path):
        skills_dir = tmp_path / ".claraity" / "skills"
        for i in range(5):
            _create_skill_dir(
                skills_dir,
                f"skill-{i}",
                f"---\nname: Skill {i}\ndescription: Desc {i}\n---\n\nBody {i}\n",
            )

        loader = SkillLoader(working_directory=tmp_path)
        assert len(loader.load_all()) == 5

    def test_extended_frontmatter(self, tmp_path: Path):
        skills_dir = tmp_path / ".claraity" / "skills"
        _create_skill_dir(
            skills_dir,
            "advanced",
            (
                "---\n"
                "name: Advanced Skill\n"
                "description: Skill with all frontmatter\n"
                "arguments: [scope, issue]\n"
                "argument-hint: '[scope] [issue-number]'\n"
                "disable-model-invocation: true\n"
                "allowed-tools: read_file search_code run_command\n"
                "---\n\n"
                "Instructions for $scope issue $issue\n"
            ),
        )

        loader = SkillLoader(working_directory=tmp_path)
        skill = loader.load_all()[0]
        assert skill.arguments == ["scope", "issue"]
        assert skill.argument_hint == "[scope] [issue-number]"
        assert skill.disable_model_invocation is True
        assert skill.allowed_tools == ["read_file", "search_code", "run_command"]

    def test_plain_files_in_skills_dir_ignored(self, tmp_path: Path):
        """Plain .md files (old format) should be ignored — only directories matter."""
        skills_dir = tmp_path / ".claraity" / "skills"
        skills_dir.mkdir(parents=True)
        # Old-style plain file
        (skills_dir / "old-style.md").write_text(
            "---\nname: Old\ndescription: Old format\n---\n\nBody\n",
            encoding="utf-8",
        )
        # New-style directory
        _create_skill_dir(
            skills_dir,
            "new-style",
            "---\nname: New\ndescription: New format\n---\n\nBody\n",
        )

        loader = SkillLoader(working_directory=tmp_path)
        skills = loader.load_all()
        assert len(skills) == 1
        assert skills[0].id == "new-style"

    def test_skill_dir_with_subdirectories(self, tmp_path: Path):
        """Skill directories can contain scripts/, references/, agents/ subdirs."""
        skills_dir = tmp_path / ".claraity" / "skills"
        skill_dir = _create_skill_dir(
            skills_dir,
            "complex-skill",
            "---\nname: Complex\ndescription: Has subdirs\n---\n\nRead agents/grader.md\n",
        )
        (skill_dir / "scripts").mkdir()
        (skill_dir / "scripts" / "helper.py").write_text("print('hi')", encoding="utf-8")
        (skill_dir / "agents").mkdir()
        (skill_dir / "agents" / "grader.md").write_text("# Grade stuff", encoding="utf-8")

        loader = SkillLoader(working_directory=tmp_path)
        skill = loader.get_skill("complex-skill")
        assert skill is not None
        assert skill.skill_dir == skill_dir
        # Subdirectories don't affect skill loading
        assert "Read agents/grader.md" in skill.body
