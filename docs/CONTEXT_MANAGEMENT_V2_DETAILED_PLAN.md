# Context Management v2 — Detailed Implementation Plan (Actionable + Bite-Sized)

**Created:** 2026-01-08  
**Status:** Ready for Implementation  
**Estimated effort:** 6–10 hours implementation + tests (incremental PR-friendly)

---

## Executive Summary

We are upgrading context management from “truncate & pray” to a **brain-like memory system**:

- **Working context (conscious workspace)** stays small and relevant.
- **Long-term storage (ObservationStore)** keeps full tool outputs and large artifacts.
- **Indexing (OBS pointers)** allows exact recall (“rehydration”) when needed.
- **Salience (importance/pinning)** protects critical info (errors, diffs, constraints).
- **Consolidation (episodic capsules / folding)** compresses history into durable decisions/outcomes.

### Key Improvements (Targets)
| Capability | Current | Target |
|---|---:|---:|
| Token tracking | partial (working+episodic) | **post-assembly report** (system + tools + rag + memory + reserves) |
| Context limit use | static | dynamic + safe headroom |
| Compaction | drop/truncate | **mask (reversible) + consolidate** |
| Tool output handling | inline forever | store externally + pointers |
| Long sessions | brittle | stable 50–200+ turns |

### Model context reality check
Claude Sonnet 4.5 supports **200K context** and also **1M context (beta for eligible tiers)**; max output supports **up to 64K output tokens**. Keep defaults safe; allow config expansion.

---

## Part 1 — Current State (Observed from your plan)

### 1.1 Configuration
- `.env` defines `MAX_CONTEXT_TOKENS=32768` while CLI defaults to `131072`.
- Context budgets are allocated by percentages, but **no final assembled token accounting** exists (system/tools/RAG overhead not properly included).

### 1.2 Memory layers
- Working memory compacts by dropping old messages.
- Episodic truncates older turns to ~80 chars (information loss).
- Observation masking exists in v1 plan, but **not reversible** and no pinning.

---

## Part 2 — Target Architecture (v2)

### 2.1 “Assembled context” is the only truth
All pressure decisions must be based on the **final payload** we send to the model:

**AssembledContext =**
- system prompt
- tool schemas/definitions
- task/user prompt
- working memory
- episodic memory
- RAG inserts
- **safety buffer**
- **reserved output tokens** (headroom)

### 2.2 ObservationStore (external long-term memory)
Tool outputs and large artifacts are stored externally and referenced by pointers:

- Store full output:
  - `observation_id`, tool name, args hash, created_at, turn_id, importance, token_count, content
- In memory, keep:
  - inline recent critical stuff
  - pointer for old/large stuff:
    - `[[OBS#12345 tool=read_file path=/src/app.py tokens=2048 importance=normal]]`

### 2.3 Importance / pinning
Each message/observation has:
- `kind`: user | assistant | tool_observation | system
- `importance`: critical | normal | low
- `turn_id`: stable per user turn (not “count user messages in history”)

Mask `low` first, then `normal`, **never mask critical unless last resort** (then summarize + keep pointer).

### 2.4 Consolidation (episodic capsules)
Older history becomes structured capsules:
- goal, decisions, files_touched, commands_run, errors, current_state, next_steps, obs_ids (references)

Prefer deterministic extraction from agent events; LLM summarization only as fallback.

---

## Part 3 — Implementation (Phased, Bite-Sized)

### Phase 0 — Instrumentation First: ContextAssemblyReport (MUST DO FIRST)
**Objective:** Stop guessing token usage. Measure what we actually send.

**Files**
- `src/context/context_builder.py` (or wherever build_context() lives)
- `src/memory/token_counter.py` (if exists) or add helper
- `src/memory/memory_manager.py` (expose report)
- `tests/test_context_assembly_report.py` (NEW)

**Changes**
1) Create a dataclass `ContextAssemblyReport`:
   - `total_limit`
   - `reserved_output_tokens`
   - token counts per bucket:
     - system, tools_schema, task, rag, working, episodic, safety_buffer
   - `total_input_tokens` (sum of all included input buckets)
   - `utilization_percent = total_input_tokens / (total_limit - reserved_output_tokens)`

2) ContextBuilder returns both:
   - `assembled_messages`
   - `ContextAssemblyReport`

3) Update logging (debug flag) to print:
   - one line summary each turn:
     - `CTX: used=83,120 / budget=184,000 (45.2%) | sys=... tools=... rag=... work=... epi=... reserve_out=...`

**Acceptance Criteria**
- Token pressure monitoring uses **assembled report**, not working+episodic sums.
- Report includes tool schema tokens and reserved output tokens.

**Tests**
- Unit: known blocks -> exact bucket sums.
- Unit: utilization percent computed correctly.

**Rollback**
- Feature-flag instrumentation logging only; no behavior change yet.

---

### Phase 1 — Safe limits + output headroom (prevents mid-generation failures)
**Objective:** Ensure we always reserve output space.

**Files**
- `.env`, `.env.example`
- `src/config.py` (or your config module)
- `tests/test_output_headroom.py` (NEW)

**Add config**
```bash
MAX_CONTEXT_TOKENS=200000          # default safe
CONTEXT_WINDOW_MODE=standard       # standard|extended (extended = 1M if allowed)

RESERVED_OUTPUT_TOKENS=12000       # start safe (tune later)
RESERVED_TOOL_SCHEMA_TOKENS=3000   # measured from report, but keep guard
SAFETY_BUFFER_TOKENS=2000

CONTEXT_YELLOW_THRESHOLD=0.60
CONTEXT_ORANGE_THRESHOLD=0.80
CONTEXT_RED_THRESHOLD=0.90
OBSERVATION_MASK_AGE=15
```

**Logic changes**
- Refuse to assemble (or force compaction) if:
  - `total_input_tokens > (MAX_CONTEXT_TOKENS - RESERVED_OUTPUT_TOKENS - SAFETY_BUFFER_TOKENS)`

**Acceptance Criteria**
- No request is sent that violates headroom.
- RED pressure triggers compaction automatically.

**Tests**
- Integration: build_context refuses/compacts when headroom violated.

---

### Phase 2 — ObservationStore (reversible masking)
**Objective:** Mask old tool outputs without losing recoverability.

**New file**
- `src/memory/observation_store.py` (NEW)

**Suggested implementation**
- SQLite (simple + fast + structured) or append-only JSONL.
- API:
  - `save(tool_name, args, content, turn_id, importance, metadata) -> observation_id`
  - `get(observation_id) -> content`
  - `find(query_fields) -> [observation_id]` (optional for cue-based recall later)

**Modified files**
- `src/memory/models.py` (Message metadata additions)
- `src/memory/working_memory.py`
- `src/core/agent.py` (tool result ingestion)

**Changes**
1) When tool returns output:
   - save full output into ObservationStore
   - decide inline vs pointer:
     - inline if: recent AND critical OR small
     - pointer if: large OR non-critical OR old
2) Store pointer format in memory:
   - `[[OBS#id tool=name tokens=... importance=...]]`
3) Masking operation becomes:
   - replace inline content with pointer (if not already pointer)
   - never replace pointer with `[omitted]`

**Acceptance Criteria**
- Tool outputs older than N turns are converted to pointers, not deleted.
- Agent can rehydrate any observation by ID.

**Tests**
- `tests/test_observation_store.py` (NEW): save/get fidelity
- `tests/test_observation_pointer_format.py` (NEW): stable formatting
- Update masking tests accordingly (masking saves tokens and preserves pointer)

**Rollback**
- ObservationStore behind feature flag `ENABLE_OBSERVATION_STORE`. If off, fall back to old masking.

---

### Phase 3 — Importance / pinning (salience)
**Objective:** Protect critical context from being masked too early.

**Files**
- `src/memory/models.py`
- `src/memory/working_memory.py`
- `src/memory/memory_manager.py`
- `tests/test_importance_masking_policy.py` (NEW)

**Changes**
1) Extend message metadata:
   - `kind`
   - `importance`
   - `turn_id`
   - `is_pointer` (derived)
2) Auto-classify importance:
   - **critical**:
     - failing tests output
     - stack traces / exceptions
     - diffs/patch summaries
     - user constraints/requirements
     - “current file under edit” snapshot pointer
     - active TODO state capsule
   - **low**:
     - directory listings
     - long repetitive logs
     - large file reads not currently relevant
3) Masking policy order:
   - mask low first, then normal, critical last
   - critical can be compacted only if RED and still over limit:
     - convert to *short structured summary* + keep pointer

**Acceptance Criteria**
- A failing test log stays inline for at least `CRITICAL_PIN_TURNS` (add config; default 10).
- Under pressure, low/normal mask before critical.

**Tests**
- Construct memory with mixed importance; verify masking order.

---

### Phase 4 — TokenPressureMonitor v2 (assembled-context-driven)
**Objective:** Pressure monitor uses `ContextAssemblyReport`, not partial sums.

**Files**
- `src/memory/token_monitor.py` (modify)
- `src/memory/memory_manager.py` (modify)
- `tests/test_token_monitor.py` (update)

**Changes**
- `check_pressure(report: ContextAssemblyReport) -> PressureStatus`
- Trigger actions based on thresholds of:
  - `report.total_input_tokens / (limit - reserved_output_tokens - safety_buffer)`
- Callback actions:
  - YELLOW: log only
  - ORANGE: mask low/normal observations older than `OBSERVATION_MASK_AGE`
  - RED: force:
    1) aggressive masking (lower age threshold)
    2) episodic consolidation
    3) last resort: summarize pinned critical (keep pointers)

**Acceptance Criteria**
- Pressure computed from assembled truth.
- No repeated callbacks unless escalating.

**Rollback**
- If issues, disable automatic compaction actions but keep reporting.

---

### Phase 5 — Episodic memory upgrade: structured consolidation instead of 80-char truncation
**Objective:** Episodic memory becomes “what we learned/decided,” not chopped text.

**Files**
- `src/memory/episodic_memory.py` (modify)
- `src/memory/memory_manager.py` (modify)
- `tests/test_episodic_capsules.py` (NEW)

**Changes**
- Replace `_compress_old_turns()` truncation with capsule creation:
```json
{
  "turn_range": "12-24",
  "goal": "...",
  "decisions": ["..."],
  "files_touched": ["src/a.py", "src/b.py"],
  "commands_run": ["pytest -q", "ruff ..."],
  "errors": ["..."],
  "current_state": "...",
  "next_steps": ["..."],
  "obs_refs": ["OBS#123", "OBS#456"]
}
```
- Prefer deterministic extraction from:
  - tool events
  - patch/diff events
  - test runner events
- Only if missing, ask LLM to summarize (optional, later).

**Acceptance Criteria**
- After consolidation, agent can continue without “what were we doing?” failures.
- Episodic capsules reference tool outputs via `OBS#`.

**Tests**
- Create a simulated session -> consolidate -> verify capsule fields present and stable.

---

### Phase 6 — Agent integration (correct tagging + stable turn_id)
**Objective:** Ensure events are tagged correctly so memory policies work.

**Files**
- `src/core/agent.py`
- `src/memory/memory_manager.py`
- `src/memory/working_memory.py`

**Changes**
1) Introduce stable `turn_id` incremented once per user message.
2) Tool result ingestion must set:
   - `kind=tool_observation`
   - `importance` via classifier
   - `turn_id=current_turn_id`
   - store in ObservationStore and insert inline/pointer per policy
3) After each user turn:
   - call context builder
   - run pressure monitor
   - log ContextAssemblyReport summary

**Acceptance Criteria**
- Tool outputs consistently tagged and stored.
- turn_id does not drift across internal messages.

**Tests**
- Integration test: multiple tool calls within a turn keep the same turn_id.

---

### Phase 7 — Long-session “torture test” harness
**Objective:** Prove it holds for 50–200 turns.

**Files**
- `tests/test_long_session_context_stability.py` (NEW)

**Test scenario**
- Simulate:
  - many `read_file` outputs (large)
  - repeated `run_command` logs
  - failing tests and stack traces
  - several edits/diffs
- Assertions:
  - context never exceeds budget
  - critical pinned content remains available
  - old tool outputs become pointers
  - rehydration works
  - episodic capsules created and referenced

---

## Part 4 — Manual Validation Checklist

### 4.1 Long conversation
- [ ] 50+ turns, heavy tool usage
- [ ] Observe CTX report each turn
- [ ] Confirm YELLOW/ORANGE/RED thresholds fire correctly
- [ ] Old tool outputs become `OBS#` pointers
- [ ] Critical error logs remain inline for pin window
- [ ] Agent remains coherent after compaction

### 4.2 Recall / rehydration
- [ ] Create OBS pointer from a file read
- [ ] After many turns, force recall by referencing symbol/file
- [ ] Agent fetches OBS content (or tool rerun) correctly

---

## Part 5 — Risk Analysis + Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---:|---:|---|
| Masking removes needed details | Medium | High | **Reversible pointers + rehydration** |
| Token counting still wrong | Medium | High | **Post-assembly report** (single source of truth) |
| Critical info masked too early | Medium | High | Importance/pinning policy + tests |
| Performance overhead | Low | Medium | SQLite + pointer strategy is cheap; keep compaction O(n) only under pressure |
| Compaction loops | Low | High | idempotent actions + “max compaction passes per turn” guard |

Rollback plan:
1) Disable auto-compaction actions (keep reporting)  
2) Disable ObservationStore feature flag (keep masking placeholder)  
3) Revert MAX_CONTEXT_TOKENS if provider rejects large windows

---

## Appendix A — File Change Summary (v2)

| File | Action |
|---|---|
| `.env`, `.env.example` | Modify |
| `src/context/context_builder.py` | Modify (ContextAssemblyReport) |
| `src/memory/token_monitor.py` | Modify (assembled-report-driven) |
| `src/memory/observation_store.py` | **New** |
| `src/memory/models.py` | Modify (kind/importance/turn_id metadata) |
| `src/memory/working_memory.py` | Modify (pointer-based masking + policy order) |
| `src/memory/episodic_memory.py` | Modify (structured capsules) |
| `src/memory/memory_manager.py` | Modify (wiring + policies) |
| `src/core/agent.py` | Modify (tagging + turn_id + tool ingestion) |
| `tests/*` | Add/update multiple tests listed above |

---

## “Do this first” (the shortest safe execution path)
If Claude Code is going to implement this in PR-sized chunks, the highest ROI order is:

1) **Phase 0** (ContextAssemblyReport)  
2) **Phase 1** (output headroom + safe budgets)  
3) **Phase 2** (ObservationStore + pointers)  
4) **Phase 3** (importance/pinning)  
5) **Phase 4** (pressure monitor rewired to assembled truth)  
6) **Phase 5** (episodic capsules)  
7) **Phase 7** (torture test)

---
