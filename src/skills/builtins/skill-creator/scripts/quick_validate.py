"""Structural validator for ClarAIty skills.

Checks that a skill directory has valid structure, frontmatter, and
follows conventions. Run as:

    python scripts/quick_validate.py <path-to-skill-directory>

Exit code 0 = all checks pass, 1 = one or more failures.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml


def validate_skill(skill_dir: Path) -> list[str]:
    """Validate a skill directory and return list of issues (empty = OK)."""
    issues: list[str] = []

    # --- Directory structure ---
    if not skill_dir.is_dir():
        return [f"Not a directory: {skill_dir}"]

    dir_name = skill_dir.name

    # Main file naming convention
    main_file = skill_dir / f"skill-{dir_name}.md"
    if not main_file.is_file():
        issues.append(f"Missing main file 'skill-{dir_name}.md' (directory is '{dir_name}/')")
        return issues  # Can't continue without main file

    # --- Read and parse ---
    try:
        content = main_file.read_text(encoding="utf-8-sig")
    except Exception as e:
        issues.append(f"Cannot read {main_file.name}: {e}")
        return issues

    # Frontmatter presence
    if not content.startswith("---"):
        issues.append("Missing YAML frontmatter (file must start with ---)")
        return issues

    # Parse frontmatter
    import re

    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", content, re.DOTALL)
    if not fm_match:
        issues.append("Invalid frontmatter format (expected --- delimiters)")
        return issues

    try:
        fm = yaml.safe_load(fm_match.group(1))
    except yaml.YAMLError as e:
        issues.append(f"Invalid YAML in frontmatter: {e}")
        return issues

    if not isinstance(fm, dict):
        issues.append(f"Frontmatter must be a YAML dict, got {type(fm).__name__}")
        return issues

    body = fm_match.group(2)

    # --- Required fields ---
    if not fm.get("name"):
        issues.append("Missing required frontmatter field: name")
    if not fm.get("description"):
        issues.append("Missing required frontmatter field: description")

    # --- Description quality ---
    desc = fm.get("description", "")
    if isinstance(desc, str):
        word_count = len(desc.split())
        if word_count < 10:
            issues.append(
                f"Description is very short ({word_count} words). "
                f"Include trigger phrases for better accuracy."
            )
        if word_count > 100:
            issues.append(
                f"Description is very long ({word_count} words). "
                f"Keep under 100 words for effective triggering."
            )

    # --- File size ---
    line_count = content.count("\n") + 1
    if line_count > 500:
        issues.append(
            f"Main file is {line_count} lines (recommended max: 500). "
            f"Consider moving details to references/."
        )

    # --- Optional field types ---
    if "tags" in fm:
        tags = fm["tags"]
        if not isinstance(tags, (list, str)):
            issues.append(
                f"'tags' should be a list or comma-separated string, got {type(tags).__name__}"
            )

    if "arguments" in fm:
        args = fm["arguments"]
        if not isinstance(args, (list, str)):
            issues.append(
                f"'arguments' should be a list or comma-separated string, got {type(args).__name__}"
            )

    if "allowed-tools" in fm:
        tools = fm["allowed-tools"]
        if not isinstance(tools, (list, str)):
            issues.append(
                f"'allowed-tools' should be a list or space-separated string, got {type(tools).__name__}"
            )

    if "disable-model-invocation" in fm:
        val = fm["disable-model-invocation"]
        if not isinstance(val, bool):
            issues.append(f"'disable-model-invocation' should be boolean, got {type(val).__name__}")

    # --- Category ---
    category = fm.get("category", "general")
    if not isinstance(category, str):
        issues.append(f"'category' should be a string, got {type(category).__name__}")

    # --- Referenced subdirectories ---
    known_subdirs = ["scripts", "references", "agents", "assets"]
    for subdir_name in known_subdirs:
        # Check if the body references this subdirectory
        if f"{subdir_name}/" in body:
            subdir_path = skill_dir / subdir_name
            if not subdir_path.is_dir():
                issues.append(f"Body references '{subdir_name}/' but directory does not exist")

    # --- Shell command safety ---
    if "!`" in body or "```!" in body:
        # Check that arguments are not used inside shell commands
        # (shell runs BEFORE argument substitution)
        import re as _re

        # Extract shell commands
        shell_sections = []
        for m in _re.finditer(r"```!\s*\n(.*?)\n\s*```", body, _re.DOTALL):
            shell_sections.append(m.group(1))
        for m in _re.finditer(r"!`([^`]+)`", body):
            shell_sections.append(m.group(1))

        for section in shell_sections:
            # $ARGUMENTS or $varname (but not ${varname:-default} which is valid shell)
            if "$ARGUMENTS" in section:
                issues.append(
                    "Shell command uses $ARGUMENTS, but shell preprocessing "
                    "runs BEFORE argument substitution. Use ${var:-default} "
                    "shell syntax instead."
                )
                break

    return issues


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python quick_validate.py <path-to-skill-directory>")
        return 1

    skill_dir = Path(sys.argv[1]).resolve()
    issues = validate_skill(skill_dir)

    if not issues:
        print(f"[OK] {skill_dir.name}: All checks passed")
        return 0

    print(f"[ISSUES] {skill_dir.name}: {len(issues)} issue(s) found")
    for issue in issues:
        print(f"  - {issue}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
