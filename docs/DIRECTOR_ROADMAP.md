# Director Protocol — Roadmap

What's been built, what's next, and how it all connects.

---

## The Vision

The CodingAgent evolves from a "solo developer that wings it" into a **Director** — an architect that understands the codebase, plans in vertical slices, delegates to specialist subagents, and verifies every step. Two operating modes:

- **Direct mode** (current) — simple tasks, just do it
- **Director mode** (new) — complex tasks, follow the protocol: UNDERSTAND -> PLAN -> EXECUTE -> INTEGRATE -> COMPLETE

---

## What's Been Built

### Phase 1: Director Protocol MVP (DONE)

**Commit:** `9926b7e` on `develop` branch
**Tests:** 130 passing
**Location:** `src/director/`

The state machine that enforces the disciplined workflow. Pure logic — no LLM calls, no agent integration yet.

```
src/director/
    __init__.py          # Public API — all exports
    models.py            # Data shapes (DirectorPhase, ContextDocument, VerticalSlice, etc.)
    errors.py            # Error hierarchy (DirectorError, InvalidTransitionError, PhaseError)
    protocol.py          # State machine (VALID_TRANSITIONS dict, transition methods)
    phases/
        __init__.py
        base.py          # PhaseHandler ABC (validate_input, format_output)
        understand.py    # UnderstandPhaseHandler
        plan.py          # PlanPhaseHandler
```

**Key classes:**

| Class | File | Purpose |
|-------|------|---------|
| `DirectorProtocol` | `protocol.py` | State machine — start, complete_understand, complete_plan, approve, reject, reset |
| `DirectorPhase` | `models.py` | Enum with 8 states: IDLE, UNDERSTAND, PLAN, AWAITING_APPROVAL, EXECUTE, INTEGRATE, COMPLETE, FAILED |
| `ContextDocument` | `models.py` | Output of UNDERSTAND — affected files, patterns, constraints, risks |
| `DirectorPlan` | `models.py` | Output of PLAN — ordered vertical slices with test criteria |
| `VerticalSlice` | `models.py` | One unit of work — files, test criteria, dependencies, status |
| `PhaseHandler` | `phases/base.py` | ABC — every phase checkpoint validates input and formats output |

**How it works:**

```python
from src.director import DirectorProtocol, ContextDocument, DirectorPlan, VerticalSlice

protocol = DirectorProtocol()
protocol.start("Add user authentication")          # IDLE -> UNDERSTAND
protocol.complete_understand(context_document)       # UNDERSTAND -> PLAN
protocol.complete_plan(plan)                         # PLAN -> AWAITING_APPROVAL
protocol.approve_plan()                              # AWAITING_APPROVAL -> EXECUTE
# or
protocol.reject_plan("needs more slices")            # AWAITING_APPROVAL -> PLAN (revision cycle)
```

**Design decisions:**
- Transition table is a dict — adding new phases is 3 lines of code
- Errors are pure data (no logging) — the protocol logs with full context via `get_logger`
- Phase handlers validate input/output but don't call LLMs — that's the adapter's job
- State machine is sync — async is the adapter's concern

**Tests:** `tests/director/` — 6 test files, 130 tests covering models, errors, protocol transitions, phase handlers, and end-to-end lifecycle.

---

## What's Next

### Phase 2: Director Adapter + EXECUTE (NEXT)

**Status:** Designed, not yet built
**Depends on:** Phase 1 (done)
**Enables:** Full end-to-end Director cycle — from task to working code

The adapter bridges the state machine to the living CodingAgent. It follows the exact same architecture as the existing `plan_mode.py` — system prompt injection + tool gating. Includes the EXECUTE phase so the full value is visible: UNDERSTAND -> PLAN -> APPROVE -> EXECUTE (RED-GREEN-REFACTOR).

**Approach: System prompt injection + tool gating + Director tools**

```
System prompt injection → controls what the LLM is TOLD to do
Tool gating             → controls what the LLM CAN do
Director tools          → checkpoints where the LLM signals "I'm done with this phase"
```

**How a full cycle works:**

```
1. Director activates for "Add authentication"

2. UNDERSTAND phase:
   - System prompt: "Explore the codebase. Do NOT write code.
     When you understand enough, call director_complete_understand."
   - Tool gating: only read tools + director_complete_understand
   - LLM uses read_file, search_code, glob naturally
   - LLM calls director_complete_understand(context)
   - Protocol validates → transitions to PLAN

3. PLAN phase:
   - System prompt: "Create vertical slices for this task.
     When done, call director_complete_plan."
   - Tool gating: only read tools + director_complete_plan
   - LLM thinks and produces slices
   - LLM calls director_complete_plan(plan)
   - Protocol validates → transitions to AWAITING_APPROVAL

4. AWAITING_APPROVAL:
   - Plan presented to user (reuses plan_mode approval pattern)
   - User approves → EXECUTE
   - User rejects with feedback → back to PLAN

5. EXECUTE phase (per slice):
   - System prompt: "Execute slice N using RED-GREEN-REFACTOR.
     Delegate to subagents. Verify with tests."
   - Tool gating: all tools + delegation + director_complete_slice

   For each vertical slice:
     RED:
       Director delegates to Test Writer subagent → writes failing test
       Director runs pytest                       → confirms test FAILS

     GREEN:
       Director delegates to Code Writer subagent → writes implementation
       Director runs pytest                       → confirms test PASSES
       Director runs full test suite              → confirms NO REGRESSIONS

     REVIEW:
       Director delegates to Code Reviewer        → checks quality

     COMMIT:
       Director commits the slice                 → progress locked in

   After all slices → transitions to INTEGRATE

6. INTEGRATE phase:
   - Director runs full test suite
   - Director reviews cross-slice coherence
   - All green → COMPLETE
```

**Components to build:**

| Component | File | Purpose |
|-----------|------|---------|
| `DirectorAdapter` | `src/director/adapter.py` | Holds protocol, manages prompt/gating per phase |
| Phase prompts | `src/director/prompts.py` | "You are in UNDERSTAND mode..." per phase |
| Director tools | `src/director/tools.py` | `director_complete_understand`, `director_complete_plan`, `director_complete_slice` |
| Code Writer prompt | `src/prompts/subagents/__init__.py` | New CODE_WRITER_PROMPT (test-writer and code-reviewer already exist) |
| Tool gating | Inside adapter | Like `plan_mode.gate_tool()` but phase-aware |
| Agent integration | `src/core/agent.py` | ~15 lines: init adapter, hook into tool loop |

**Key pattern to follow:** `src/core/plan_mode.py` (393 lines) — PlanModeState with enter/exit/approve/reject/reset and gate_tool() for controlling available tools per state.

**Agent.py touch points (minimal):**
- `__init__` (~line 398): Add `self.director_adapter = DirectorAdapter(self)` — 2 lines
- `_execute_with_tools_async` (~line 900): Check director phase for prompt injection — ~10 lines
- Tool registration: Register director tools — ~3 lines

**New subagent needed: Code Writer**
- test-writer and code-reviewer already exist in `src/prompts/subagents/__init__.py`
- Add CODE_WRITER_PROMPT following the same pattern
- Focus: "Write the minimum code to make the failing test pass. Follow existing patterns."

**Test verification tooling:**
- Director needs to run `pytest` and interpret pass/fail
- Could be a dedicated tool (`run_tests`) or use existing `execute_command` tool
- Must parse pytest output to determine: all passed, which failed, error messages

---

### Phase 3: Codebase Survey (PARKED)

**Status:** Fully planned, parked until Phase 2 is done
**Plan:** `docs/CODEBASE_SURVEY_PLAN.md`
**Depends on:** Phase 2 (adapter must exist to load the survey)

A codebase surveyor that scans the project and generates `.clarity/codebase_context.md` — a persistent, LLM-consumable document loaded into every session.

**Two scenarios:**
- **Existing project:** Survey first, then work. Agent refuses to work without context.
- **Greenfield project:** Document the vision first, build incrementally.

**5 vertical slices planned:** Survey models, file scanner, project detector, markdown generator, survey manager with staleness detection.

---

### Phase 4: Full Integration (FUTURE)

**Status:** Vision
**Depends on:** All above

- `/code-survey` TUI command
- Auto-detect complex tasks and suggest Director mode
- Incremental survey updates on git changes
- Director progress visible in TUI (phase indicator, slice progress)
- ClarityDB backing store for queryable codebase intelligence

---

## Dependency Graph

```
Phase 1: Protocol MVP          ← DONE (130 tests, committed)
    |
    v
Phase 2: Adapter + EXECUTE     ← NEXT (full end-to-end Director cycle)
    |
    v
Phase 3: Codebase Survey       ← PARKED (persistent project intelligence)
    |
    v
Phase 4: Full Integration      ← FUTURE (TUI, auto-detect, ClarityDB)
```

## Key Documents

| Document | Location | Purpose |
|----------|----------|---------|
| Director Philosophy | `docs/DIRECTOR_PHILOSOPHY.md` | Why — the principles and ideology |
| This Roadmap | `docs/DIRECTOR_ROADMAP.md` | What — built vs planned |
| Survey Plan | `docs/CODEBASE_SURVEY_PLAN.md` | Phase 3 detailed plan (parked) |
| Plan Mode (reference) | `src/core/plan_mode.py` | Pattern to follow for adapter |
| Director Protocol | `src/director/` | Phase 1 implementation |
| Director Tests | `tests/director/` | 130 tests, 6 files |

## How to Resume

To continue building in a new session:

1. Read this roadmap for full context
2. Read `docs/DIRECTOR_PHILOSOPHY.md` for principles
3. The next task is **Phase 2: Director Adapter + EXECUTE**
4. Follow the protocol: UNDERSTAND (read plan_mode.py and existing subagent prompts) -> PLAN (vertical slices) -> EXECUTE (RED-GREEN-REFACTOR per slice)
5. Key patterns to follow:
   - `src/core/plan_mode.py` — system prompt injection + tool gating
   - `src/prompts/subagents/__init__.py` — existing subagent prompt patterns (for new code-writer prompt)
   - `src/tools/delegation.py` — how tools delegate to subagents
6. The full cycle to demo: UNDERSTAND -> PLAN -> APPROVE -> EXECUTE (RED-GREEN-REFACTOR per slice) -> INTEGRATE -> COMPLETE
7. The value proof: run the Director on a real task on the ClarAIty codebase itself and watch it plan, delegate, verify, and commit — slice by slice
