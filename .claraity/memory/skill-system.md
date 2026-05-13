---
name: Skill System Architecture
description: Complete skill system implementation — directory-based skills, preprocessing, slash commands, built-in skill-creator toolkit with dual-directory SkillLoader.
type: project
---

# Skill System Implementation

## Core Architecture (v1.1.0)

Skills are directory-based markdown files with YAML frontmatter, injected as user messages.

**File layout:**
```
.claraity/skills/<name>/skill-<name>.md     # Project skills
src/skills/builtins/<name>/skill-<name>.md  # Built-in skills (ship with binary)
```

**SkillLoader** (`src/skills/skill_loader.py`):
- Dual-directory: scans `src/skills/builtins/` then `.claraity/skills/`
- Project skills override built-ins with same directory name
- `builtins_dir` param for test isolation (pass nonexistent path)
- Symlink guard in `_scan_dir()`, path traversal guard in `_get_from_dir()`
- PyInstaller spec bundles builtins via `datas` entry

**Invocation paths:**
1. Slash command: `/skill-name args` → `_parse_slash_command()` in stdio_server.py
2. Skill picker: UI sets `activeSkill` in chat message payload
3. "New Skill" button: sends `activeSkill: "skill-creator"` directly

**Injection flow** (agent.py ~lines 1630-1750):
1. Detect `active_skill` parameter
2. Load via SkillLoader.get_skill()
3. Shell preprocessing (commands require user approval, run async)
4. Argument substitution ($ARGUMENTS, $varname, $0/$1)
5. Inject as `<skill name="..." id="...">` XML wrapping user message

**Key rules:**
- Shell preprocessing runs BEFORE argument substitution (security)
- `allowed-tools` is informational only — does NOT bypass approval
- 30s timeout per command, 10KB output cap
- `disable-model-invocation: true` skips LLM call (analysis-only skills)

## Built-in Skill-Creator Toolkit

Ships at `src/skills/builtins/skill-creator/`:
- `skill-skill-creator.md` — 496-line guide for creating production-grade skills
- `agents/grader.md` — Evaluate assertions against outputs with evidence
- `agents/analyzer.md` — Surface benchmark patterns, post-hoc analysis
- `agents/comparator.md` — Blind A/B output comparison
- `references/schemas.md` — JSON schemas for all eval/benchmark data
- `references/description-optimization.md` — Trigger accuracy optimization
- `scripts/quick_validate.py` — Structural validator

## Frontmatter Schema

| Field | Required | Notes |
|-------|----------|-------|
| name | Yes | Human-readable |
| description | Yes | Primary trigger mechanism — be "pushy" |
| category | No | Default: "general" |
| tags | No | YAML list |
| arguments | No | Named placeholders |
| argument-hint | No | UI hint string |
| disable-model-invocation | No | Skip LLM |
| allowed-tools | No | Informational only |
| author | No | Maintainer |

## Phase 2/3 (Pending)

- eval-viewer/ (HTML browser for reviewing test results)
- assets/eval_review.html (trigger eval query editor)
- scripts/aggregate_benchmark.py, package_skill.py, generate_report.py
- scripts/run_eval.py, run_loop.py, improve_description.py (need subagent integration)
