# Knowledge Base System - Implementation Reference

> Target audience: LLM agents. Optimized for machine readability.
> Last verified against source: 2026-02-20

---

## Architecture Diagram

```
                          SESSION START
                              |
                              v
                    ContextBuilder.build_context()
                    (src/core/context_builder.py:176)
                              |
                              v
                    memory.get_knowledge_base()
                    (src/memory/memory_manager.py:1265)
                              |
                              v
                    _load_knowledge_base()
                    (src/memory/memory_manager.py:1215)
                              |
                    reads from _project_root / .claraity/knowledge/
                              |
         +--------+--------+--------+-----------+----------+----------+
         |        |        |        |           |          |
      core.md  arch.md  file-    conv.md   decisions.md  lessons.md
      (200L)   (no cap) guide.md (no cap)    (100L)       (100L)
                         (no cap)
                              |
                              v
                    Combined string (cached in _knowledge_core_content)
                              |
                              v
                    Appended to system_prompt in build_context()
                    (src/core/context_builder.py:248-256)
                              |
                              v
                    LLM receives knowledge as part of system prompt


    KNOWLEDGE-BUILDER SUBAGENT (separate session)
                              |
          +-------------------+-------------------+
          |                                       |
    kb_detect_changes                      kb_update_manifest
    (knowledge_tools.py:235)               (knowledge_tools.py:419)
          |                                       |
    reads .manifest.json                   writes .manifest.json
    scans project via git ls-files         records file stats + coverage
    compares file stats                    merges on incremental runs
          |
    reports changed/new/deleted files
```

---

## File Inventory

### Source Files

| File | Key Exports | Purpose |
|------|-------------|---------|
| `src/memory/memory_manager.py` | `MemoryManager._KNOWLEDGE_FILES`, `_load_knowledge_base()`, `get_knowledge_base()`, `reload_knowledge_base()` | Loads and caches KB files from disk |
| `src/core/context_builder.py` | `ContextBuilder.build_context()` | Injects KB content into system prompt |
| `src/prompts/system_prompts.py` | `KNOWLEDGE_MAINTENANCE` constant | System prompt guidance for main agent on experiential files |
| `src/tools/knowledge_tools.py` | `KBDetectChangesTool`, `KBUpdateManifestTool`, `_scan_project_files()`, `_apply_filters()`, `_ensure_scan_config()` | File scanning and manifest management for KB subagent |

### Knowledge Files (runtime)

| File | Line Cap | Owner | Purpose |
|------|----------|-------|---------|
| `.claraity/knowledge/core.md` | 200 | knowledge-builder subagent | Project overview, key components |
| `.claraity/knowledge/architecture.md` | none | knowledge-builder subagent | Module map, dependencies, data flow |
| `.claraity/knowledge/file-guide.md` | none | knowledge-builder subagent | Entry points, file purposes, navigation |
| `.claraity/knowledge/conventions.md` | none | knowledge-builder subagent | Coding standards, patterns, constraints |
| `.claraity/knowledge/decisions.md` | 100 | main agent | Significant design choices with rationale |
| `.claraity/knowledge/lessons.md` | 100 | main agent | Debugging lessons, gotchas, ALWAYS/NEVER rules |

### Configuration Files (runtime)

| File | Created By | Purpose |
|------|-----------|---------|
| `.claraity/knowledge/scan_config.yaml` | `_ensure_scan_config()` on first `kb_detect_changes` call | Include/exclude glob patterns for file scanning |
| `.claraity/knowledge/.manifest.json` | `KBUpdateManifestTool` | Tracks file stats and knowledge coverage for incremental updates |

### Test Files

| File | Test Count | Coverage |
|------|-----------|----------|
| `tests/memory/test_knowledge_base.py` | 19 tests (2 classes) | Loading, caching, truncation, ordering, context integration |
| `tests/tools/test_knowledge_tools.py` | 41 tests (8 classes) | Scanning, filtering, config, git integration, manifest CRUD |

---

## Data Flow: Context Loading (per session)

### Call Chain

```
1. ContextBuilder.build_context()                    context_builder.py:176
2.   knowledge_content = self.memory.get_knowledge_base()   context_builder.py:249
3.     MemoryManager.get_knowledge_base()             memory_manager.py:1265
4.       MemoryManager._load_knowledge_base()         memory_manager.py:1215
5.         reads self._project_root / ".claraity" / "knowledge" / <filename>
6.         for each (filename, max_lines) in _KNOWLEDGE_FILES:
7.           filepath.read_text(encoding='utf-8')
8.           if max_lines > 0 and len(lines) > max_lines: truncate
9.           sections.append(content)
10.        combined = "\n\n---\n\n".join(sections)
11.        self._knowledge_core_content = combined     # cached
12.  system_prompt += "\n\n" + label + "\n\n" + knowledge_content
                                                      context_builder.py:251-256
```

### Injection Format

The knowledge content is appended directly to the system prompt string at `context_builder.py:251-256`:

```python
system_prompt = (
    system_prompt
    + "\n\n"
    + "Contents of .claraity/knowledge/ (project knowledge base - auto-loaded each session):\n\n"
    + knowledge_content
)
```

This matches how Claude Code injects CLAUDE.md into its system prompt.

### Caching Behavior

- `_knowledge_core_content` (type: `Optional[str]`, initialized `None` at line 104)
- First call to `_load_knowledge_base()` reads all files, caches result
- Subsequent calls return cached string (line 1229-1230)
- `reload_knowledge_base()` calls `_load_knowledge_base(force_reload=True)` to bypass cache (line 1269-1277)

### Project Root Resolution

```python
# memory_manager.py:107
self._project_root: Path = Path(starting_directory).resolve() if starting_directory else Path.cwd()
```

`_project_root` is set once at construction. Knowledge directory is resolved as:
```python
# memory_manager.py:1232
knowledge_dir = self._project_root / ".claraity" / "knowledge"
```

**Bug fix**: Previously used `Path.cwd()` directly in `_load_knowledge_base()`, which failed when CWD differed from project root (e.g., subagent processes). Fixed by using `self._project_root`.

---

## Data Flow: Knowledge Builder Subagent

### File Scanning Pipeline

```
1. KBDetectChangesTool.execute()                     knowledge_tools.py:259
2.   _ensure_scan_config(root)                       knowledge_tools.py:54
3.     creates scan_config.yaml template if missing
4.   _read_manifest(manifest_path)                   knowledge_tools.py:212
5.     returns None if missing -> FULL mode
6.     returns dict if exists -> INCREMENTAL mode
7.   _scan_project_files(root)                       knowledge_tools.py:137
8.     _read_kb_config(root)                         knowledge_tools.py:63
9.       reads .claraity/knowledge/scan_config.yaml
10.      returns {include: [...], exclude: [...]}
11.    _git_ls_files(root)                           knowledge_tools.py:88
12.      runs: git ls-files (cwd=root, timeout=30s)
13.      returns list of paths or None on failure
14.    if git_files is None:
15.      os.walk fallback (skips _skip_dirs set)     knowledge_tools.py:160-180
16.    filter _SKIP_EXTENSIONS                       knowledge_tools.py:183-186
17.    _apply_filters(file_paths, include, exclude)  knowledge_tools.py:109
18.      fnmatch-based whitelist/blacklist
19.    stat each file -> {path: {size, mtime}}       knowledge_tools.py:195-207
```

### FULL Mode Output

When no manifest exists, `KBDetectChangesTool` returns:
- `output`: "Mode: FULL (no manifest found)" + sorted file list
- `metadata.mode`: `"full"`
- `metadata.total_files`: count
- `metadata.files`: sorted list of all source file paths

### INCREMENTAL Mode Output

When manifest exists, compares `stored_files` against current scan:
- `changed`: files where size or mtime differ
- `new_files`: in current scan but not in manifest
- `deleted`: in manifest but not in current scan
- `affected`: knowledge files whose coverage patterns match changed paths (via `_match_coverage()`)

### Manifest Update

```
1. KBUpdateManifestTool.execute()                    knowledge_tools.py:471
2.   for each analyzed_file:
3.     stat the file -> {size, mtime}                knowledge_tools.py:486-498
4.     normalize path separators (\ -> /)            knowledge_tools.py:493
5.   if mode == "incremental":
6.     merge with existing manifest                  knowledge_tools.py:502-518
7.     remove entries for deleted files              knowledge_tools.py:508-511
8.   write manifest as JSON                          knowledge_tools.py:528-533
```

### Manifest Schema

```json
{
  "last_run": "2026-01-15T12:00:00+00:00",
  "mode": "full|incremental",
  "source_files": {
    "src/main.py": {"size": 1234, "mtime": "2026-01-15T12:00:00+00:00"},
    ...
  },
  "knowledge_coverage": {
    "architecture.md": ["src/api/*", "src/core/*"],
    "file-guide.md": ["src/**"],
    ...
  }
}
```

---

## Knowledge File Loading Order

Defined at `memory_manager.py:1206-1213`:

```python
_KNOWLEDGE_FILES = [
    ("core.md", 200),        # 1st loaded, 200-line cap
    ("architecture.md", 0),  # 2nd loaded, no cap
    ("file-guide.md", 0),    # 3rd loaded, no cap
    ("conventions.md", 0),   # 4th loaded, no cap
    ("decisions.md", 100),   # 5th loaded, 100-line cap
    ("lessons.md", 100),     # 6th loaded, 100-line cap
]
```

- `0` means no line cap (knowledge-builder subagent is instructed to keep these concise)
- Files are joined with `"\n\n---\n\n"` separator (line 1261)
- Missing files are silently skipped (line 1241-1242)
- Empty/whitespace-only files are silently skipped (line 1246-1247)
- Truncation appends: `\n\n[... {filename} truncated to {max_lines} lines ...]` (line 1254)

---

## System Prompt Guidance

### KNOWLEDGE_MAINTENANCE Constant

Location: `src/prompts/system_prompts.py:827-844`

Included in every system prompt via `get_system_prompt()` at line 924.

Key directives to the main agent:
1. Agent owns `decisions.md` and `lessons.md` (experiential files)
2. Use `read_file`/`edit_file`/`write_file` to maintain them
3. Before delegating to `knowledge-builder`: run `git ls-files --others --exclude-standard`
4. If untracked files exist, ask user whether to commit first
5. Do NOT delegate until user confirms (only committed files are scanned)

### Entry Templates

| File | When | Template |
|------|------|----------|
| `decisions.md` | Significant design choice | `## Decision: <Title>` + Chosen, Alternatives, Rationale, Files affected |
| `lessons.md` | Non-obvious debugging lesson | `## <Title>` + Symptom, Root cause (file:line), Fix, ALWAYS/NEVER rule |

---

## File Scanning Configuration

### scan_config.yaml

Location: `.claraity/knowledge/scan_config.yaml`

Created automatically by `_ensure_scan_config()` (knowledge_tools.py:54) on first `kb_detect_changes` call.

```yaml
include:    # glob whitelist; empty = scan all
  # - "src/**"
exclude:    # glob blacklist; always applied
  # - "tests/fixtures/**"
```

### Binary Extension Filter

Constant: `_SKIP_EXTENSIONS` at `knowledge_tools.py:24-32`

```python
_SKIP_EXTENSIONS = {
    '.pyc', '.pyo', '.so', '.dll', '.dylib', '.exe', '.bin',
    '.db', '.sqlite', '.sqlite3',
    '.png', '.jpg', '.jpeg', '.gif', '.ico', '.svg', '.webp',
    '.woff', '.woff2', '.ttf', '.eot',
    '.zip', '.tar', '.gz', '.bz2', '.7z',
    '.pdf', '.doc', '.docx', '.xls', '.xlsx',
    '.lock',
}
```

Applied after git ls-files or os.walk, before include/exclude patterns.

### os.walk Skip Directories

Used only when `git ls-files` is unavailable (knowledge_tools.py:160-168):

```python
_skip_dirs = {
    '.git', '.hg', '.svn', '.claraity',
    '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache',
    'node_modules', '.next', 'dist', 'build', 'out',
    '.venv', 'venv', '.env', 'env',
    '.tox', '.nox', '.eggs',
    '.idea', '.vscode',
    '.benchmarks', '.checkpoints',
}
```

---

## Key Bug Fixes

### 1. Path.cwd() vs _project_root

**Symptom**: Knowledge files not loading when agent CWD differs from project root.

**Root cause**: `_load_knowledge_base()` used `Path.cwd()` to locate `.claraity/knowledge/`.

**Fix**: Introduced `self._project_root` (memory_manager.py:107), set at construction from `starting_directory` parameter. `_load_knowledge_base()` uses `self._project_root / ".claraity" / "knowledge"` (line 1232).

**Test**: `test_knowledge_uses_project_root_not_cwd` (test_knowledge_base.py:312-331).

### 2. System Message Filter Bypass

**Symptom**: Knowledge base content injected as separate system message by `MemoryManager.get_context_for_llm()` was being filtered out by `ContextBuilder.build_context()`.

**Root cause**: `context_builder.py:372` filters `if msg["role"] != "system"` -- this correctly removes memory-injected system messages to avoid duplicates, but also removed knowledge content when it was injected as a system message.

**Fix**: Knowledge is now injected directly into the system prompt string by `ContextBuilder.build_context()` (lines 248-256), not as a separate system message. The comment at `memory_manager.py:832-833` documents this decision:
```python
# 2b. Knowledge base is now injected by ContextBuilder directly
# into the system prompt (not as a separate system message).
```

**Test**: `test_knowledge_not_in_get_context_for_llm` (test_knowledge_base.py:297-310).

---

## Tool API Reference

### KBDetectChangesTool

```
Name: kb_detect_changes
Parameters: {} (none)
```

**Behavior**:
- No manifest exists: returns FULL mode with complete sorted file list
- Manifest exists, no changes: returns INCREMENTAL with `changes: False`
- Manifest exists, changes found: returns INCREMENTAL with changed/new/deleted lists and affected knowledge files

**Metadata keys** (FULL mode): `mode`, `total_files`, `files`
**Metadata keys** (INCREMENTAL, changes): `mode`, `changes`, `changed_count`, `new_count`, `deleted_count`, `unchanged_count`, `affected_knowledge_files`

### KBUpdateManifestTool

```
Name: kb_update_manifest
Parameters:
  analyzed_files: string[]      # relative paths analyzed this run
  knowledge_coverage: object    # {kb_filename: [source_patterns]}
  mode: "full" | "incremental"
```

**Behavior**:
- Stats each file for size/mtime (caller only passes paths)
- Full mode: writes manifest from scratch
- Incremental mode: merges with existing manifest, removes entries for deleted files
- Normalizes backslashes to forward slashes

**Metadata keys**: `manifest_path`, `source_files_count`, `knowledge_files_count`, `stat_errors`

---

## Method Signatures Quick Reference

### memory_manager.py (MemoryManager)

| Line | Method | Signature | Returns |
|------|--------|-----------|---------|
| 1206 | `_KNOWLEDGE_FILES` | class variable: `List[Tuple[str, int]]` | N/A |
| 1215 | `_load_knowledge_base` | `(self, force_reload: bool = False) -> str` | Combined content or `""` |
| 1265 | `get_knowledge_base` | `(self) -> str` | Cached combined content |
| 1269 | `reload_knowledge_base` | `(self) -> str` | Fresh combined content |

### context_builder.py (ContextBuilder)

| Line | Method | Relevant Logic |
|------|--------|---------------|
| 249 | `build_context` | `knowledge_content = self.memory.get_knowledge_base()` |
| 250-256 | `build_context` | Appends to `system_prompt` if non-empty |

### knowledge_tools.py (module-level functions)

| Line | Function | Signature |
|------|----------|-----------|
| 54 | `_ensure_scan_config` | `(root: Path) -> None` |
| 63 | `_read_kb_config` | `(root: Path) -> Dict[str, List[str]]` |
| 88 | `_git_ls_files` | `(root: Path) -> Optional[List[str]]` |
| 109 | `_apply_filters` | `(file_paths: List[str], include: List[str], exclude: List[str]) -> List[str]` |
| 137 | `_scan_project_files` | `(root: Path) -> Dict[str, Dict[str, Any]]` |
| 212 | `_read_manifest` | `(manifest_path: Path) -> Optional[Dict]` |
| 222 | `_match_coverage` | `(file_path: str, patterns: List[str]) -> bool` |

### knowledge_tools.py (Tool classes)

| Line | Class | Tool Name | Parameters |
|------|-------|-----------|------------|
| 235 | `KBDetectChangesTool` | `kb_detect_changes` | none |
| 419 | `KBUpdateManifestTool` | `kb_update_manifest` | `analyzed_files`, `knowledge_coverage`, `mode` |

---

## Test Coverage Summary

### tests/memory/test_knowledge_base.py (19 tests)

**TestKnowledgeBaseLoading** (14 tests):
- `test_load_with_core_only` -- single file loading
- `test_load_all_six_files` -- all 6 files combined with separators
- `test_load_preserves_file_order` -- order matches `_KNOWLEDGE_FILES`
- `test_load_skips_missing_files` -- graceful skip
- `test_load_skips_empty_files` -- whitespace-only ignored
- `test_no_knowledge_dir` -- missing `.claraity/knowledge/` returns `""`
- `test_core_truncation_at_200_lines` -- 250 lines truncated to 200
- `test_core_exactly_200_lines_not_truncated` -- boundary check
- `test_decisions_truncation_at_100_lines` -- decisions.md capped
- `test_lessons_truncation_at_100_lines` -- lessons.md capped
- `test_other_files_not_truncated` -- architecture.md has no cap
- `test_caching` -- second call returns cached content
- `test_reload_bypasses_cache` -- `reload_knowledge_base()` re-reads from disk
- `test_ignores_unlisted_files` -- only `_KNOWLEDGE_FILES` entries are loaded

**TestKnowledgeBaseContextIntegration** (5 tests):
- `test_knowledge_available_via_public_api` -- `get_knowledge_base()` returns content
- `test_all_files_in_single_string` -- multiple files combined
- `test_no_knowledge_when_no_files` -- empty string when no KB
- `test_knowledge_not_in_get_context_for_llm` -- KB not injected as system message
- `test_knowledge_uses_project_root_not_cwd` -- `_project_root` used instead of CWD

### tests/tools/test_knowledge_tools.py (41 tests)

**TestScanProjectFiles** (5 tests): file scanning, hidden dirs, pycache, binary extensions, stat output

**TestApplyFilters** (6 tests): no filters, include whitelist, multiple patterns, exclude blacklist, combined, double star

**TestEnsureScanConfig** (3 tests): creates template, no overwrite, auto-create on first detect run

**TestReadKBConfig** (4 tests): no file, empty config, include+exclude, exclude only

**TestGitLsFilesIntegration** (5 tests): git used when available, os.walk fallback, binary filter on git output, config exclude with git, config include with git

**TestMatchCoverage** (5 tests): exact, wildcard, double star, no match, multiple patterns

**TestKBDetectChanges** (6 tests): FULL mode (no manifest), no changes, changed file, new file, deleted file, affected knowledge files

**TestKBUpdateManifest** (7 tests): full write, accurate stats, incremental merge, delete cleanup, stat errors, directory creation, path normalization

---

## Constants Reference

| Constant | Location | Value |
|----------|----------|-------|
| `MANIFEST_PATH` | knowledge_tools.py:21 | `".claraity/knowledge/.manifest.json"` |
| `SCAN_CONFIG_PATH` | knowledge_tools.py:35 | `".claraity/knowledge/scan_config.yaml"` |
| `_SKIP_EXTENSIONS` | knowledge_tools.py:24-32 | Set of 27 binary/non-source extensions |
| `_KNOWLEDGE_FILES` | memory_manager.py:1206-1213 | 6-element list of (filename, max_lines) tuples |
| `KNOWLEDGE_MAINTENANCE` | system_prompts.py:827-844 | System prompt section for experiential file guidance |
