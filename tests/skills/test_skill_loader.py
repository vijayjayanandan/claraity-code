"""Tests for the skill loader."""

from pathlib import Path

import pytest

from src.skills.skill_loader import SkillInfo, SkillLoader, _parse_frontmatter


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
# SkillLoader
# ---------------------------------------------------------------------------


class TestSkillLoader:
    def _write_skill(self, skills_dir: Path, name: str, content: str) -> Path:
        """Helper to write a skill file."""
        path = skills_dir / f"{name}.md"
        path.write_text(content, encoding="utf-8")
        return path

    def test_load_valid_skill(self, tmp_path: Path):
        skills_dir = tmp_path / ".claraity" / "skills"
        skills_dir.mkdir(parents=True)
        self._write_skill(
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

    def test_empty_directory(self, tmp_path: Path):
        skills_dir = tmp_path / ".claraity" / "skills"
        skills_dir.mkdir(parents=True)

        loader = SkillLoader(working_directory=tmp_path)
        assert loader.load_all() == []

    def test_no_skills_directory(self, tmp_path: Path):
        loader = SkillLoader(working_directory=tmp_path)
        assert loader.load_all() == []

    def test_malformed_frontmatter_skipped(self, tmp_path: Path):
        skills_dir = tmp_path / ".claraity" / "skills"
        skills_dir.mkdir(parents=True)
        # Valid skill
        self._write_skill(
            skills_dir,
            "good",
            "---\nname: Good\ndescription: Valid\n---\n\nBody\n",
        )
        # Malformed skill (no frontmatter)
        self._write_skill(skills_dir, "bad", "No frontmatter here")

        loader = SkillLoader(working_directory=tmp_path)
        skills = loader.load_all()
        assert len(skills) == 1
        assert skills[0].id == "good"

    def test_missing_name_skipped(self, tmp_path: Path):
        skills_dir = tmp_path / ".claraity" / "skills"
        skills_dir.mkdir(parents=True)
        self._write_skill(
            skills_dir,
            "no-name",
            "---\ndescription: Has description but no name\n---\n\nBody\n",
        )

        loader = SkillLoader(working_directory=tmp_path)
        assert loader.load_all() == []

    def test_missing_description_skipped(self, tmp_path: Path):
        skills_dir = tmp_path / ".claraity" / "skills"
        skills_dir.mkdir(parents=True)
        self._write_skill(
            skills_dir,
            "no-desc",
            "---\nname: Has name but no description\n---\n\nBody\n",
        )

        loader = SkillLoader(working_directory=tmp_path)
        assert loader.load_all() == []

    def test_id_from_filename(self, tmp_path: Path):
        skills_dir = tmp_path / ".claraity" / "skills"
        skills_dir.mkdir(parents=True)
        self._write_skill(
            skills_dir,
            "test-driven-bugfix",
            "---\nname: Test-Driven Bug Fix\ndescription: TDD bugfix\n---\n\nBody\n",
        )

        loader = SkillLoader(working_directory=tmp_path)
        skills = loader.load_all()
        assert skills[0].id == "test-driven-bugfix"

    def test_get_skill_by_id(self, tmp_path: Path):
        skills_dir = tmp_path / ".claraity" / "skills"
        skills_dir.mkdir(parents=True)
        self._write_skill(
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
        skills_dir.mkdir(parents=True)
        self._write_skill(
            skills_dir,
            "simple",
            "---\nname: Simple\ndescription: No category\n---\n\nBody\n",
        )

        loader = SkillLoader(working_directory=tmp_path)
        assert loader.load_all()[0].category == "general"

    def test_tags_as_csv_string(self, tmp_path: Path):
        skills_dir = tmp_path / ".claraity" / "skills"
        skills_dir.mkdir(parents=True)
        self._write_skill(
            skills_dir,
            "csv-tags",
            "---\nname: CSV Tags\ndescription: Tags as string\ntags: bug, fix, test\n---\n\nBody\n",
        )

        loader = SkillLoader(working_directory=tmp_path)
        skill = loader.load_all()[0]
        assert skill.tags == ["bug", "fix", "test"]

    def test_sorted_by_category_then_name(self, tmp_path: Path):
        skills_dir = tmp_path / ".claraity" / "skills"
        skills_dir.mkdir(parents=True)
        self._write_skill(
            skills_dir,
            "z-skill",
            "---\nname: Z Skill\ndescription: Desc\ncategory: alpha\n---\n\nBody\n",
        )
        self._write_skill(
            skills_dir,
            "a-skill",
            "---\nname: A Skill\ndescription: Desc\ncategory: beta\n---\n\nBody\n",
        )
        self._write_skill(
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
        skills_dir.mkdir(parents=True)
        for i in range(5):
            self._write_skill(
                skills_dir,
                f"skill-{i}",
                f"---\nname: Skill {i}\ndescription: Desc {i}\n---\n\nBody {i}\n",
            )

        loader = SkillLoader(working_directory=tmp_path)
        assert len(loader.load_all()) == 5
