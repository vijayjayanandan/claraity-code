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

The state machine that enforces the disciplined workflow. Pure logic — no LLM calls, no agent integration.

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
| `DirectorProtocol` | `protocol.py` | State machine — start, complete_understand, complete_plan, approve, reject, complete_integration, reset |
| `DirectorPhase` | `models.py` | Enum with 8 states: IDLE, UNDERSTAND, PLAN, AWAITING_APPROVAL, EXECUTE, INTEGRATE, COMPLETE, FAILED |
| `ContextDocument` | `models.py` | Output of UNDERSTAND — affected files, patterns, constraints, risks |
| `DirectorPlan` | `models.py` | Output of PLAN — ordered vertical slices with test criteria |
| `VerticalSlice` | `models.py` | One unit of work — files, test criteria, dependencies, status |
| `PhaseHandler` | `phases/base.py` | ABC — every phase checkpoint validates input and formats output |

---

### Phase 2: Director Adapter + Full Lifecycle (DONE)

**Commits:** `2509320`, `17a0415`, plus current uncommitted work
**Tests:** 297 passing (130 protocol + 167 adapter/tools/integration)
**Location:** `src/director/`, `src/core/agent.py`, `src/ui/app.py`

The adapter bridges the state machine to the living CodingAgent using three mechanisms:

```
System prompt injection -> controls what the LLM is TOLD to do
Tool gating            -> controls what the LLM CAN do
Director tools         -> checkpoints where the LLM signals "I'm done with this phase"
```

**Components built:**

| Component | File | Purpose |
|-----------|------|---------|
| `DirectorAdapter` | `src/director/adapter.py` | Holds protocol, manages prompt/gating per phase |
| Phase prompts | `src/director/prompts.py` | Phase-specific system prompt injection + tool allowlists |
| Director tools | `src/director/tools.py` | 4 checkpoint tools for phase transitions |
| Tool schemas | `src/tools/tool_schemas.py` | LLM-visible tool definitions |
| Agent integration | `src/core/agent.py` | Tool registration, gate checks, context injection |
| TUI integration | `src/ui/app.py` | Status bar phase display, plan approval widget, silent tool cards |

**Director checkpoint tools:**

| Tool | Phase | Transition |
|------|-------|-----------|
| `director_complete_understand` | UNDERSTAND | -> PLAN |
| `director_complete_plan` | PLAN | -> AWAITING_APPROVAL |
| `director_complete_slice` | EXECUTE | -> next slice or INTEGRATE |
| `director_complete_integration` | INTEGRATE | -> COMPLETE |

**How a full cycle works:**

```
1. User: /director Add authentication

2. UNDERSTAND phase:
   - Prompt: "Explore the codebase. Do NOT write code."
   - Tools: read-only + director_complete_understand
   - LLM explores, then calls director_complete_understand(context)

3. PLAN phase:
   - Prompt: "Write a plan to .clarity/plans/, then call director_complete_plan."
   - Tools: read-only + write_file (only .clarity/plans/) + director_complete_plan
   - LLM writes plan markdown, then calls director_complete_plan(plan_document, slices)

4. AWAITING_APPROVAL:
   - Plan displayed to user via PlanApprovalWidget
   - User approves -> EXECUTE / rejects with feedback -> back to PLAN

5. EXECUTE phase (per slice):
   - Prompt: "DELEGATE to subagents. Do NOT write code yourself."
   - Tools: all tools + director_complete_slice
   - For each slice:
     RED:    Director delegates to test-writer -> writes failing test
     GREEN:  Director delegates to code-writer -> writes implementation
     REVIEW: Director delegates to code-reviewer -> checks quality
   - Director calls director_complete_slice after each slice

6. INTEGRATE phase:
   - Prompt: "Run full test suite. Verify cross-slice coherence."
   - Tools: read-only + run_command + director_complete_integration
   - Director runs tests, then calls director_complete_integration

7. COMPLETE:
   - Director mode deactivates (is_active = False)
   - Normal agent behavior resumes
```

**Key design decisions:**
- File-based plan: LLM writes rich markdown to `.clarity/plans/`, tool references file path (avoids JSON escaping issues)
- Path-based gating: `write_file` allowed in PLAN phase only for `.clarity/plans/` paths
- Delegation-first EXECUTE: prompt instructs Director to delegate, not code directly (Approach A: prompt-driven, not enforced)
- Silent tool cards: Director checkpoint tools hidden from TUI (phase transitions are internal)
- Approval widget replay guard: skips mounting during session replay if tool result already exists

**Specialist subagents (7 total):**

| Subagent | Purpose | Director Phase |
|----------|---------|---------------|
| `code-writer` | Write minimum code to pass tests | EXECUTE (GREEN) |
| `test-writer` | Write comprehensive test suites | EXECUTE (RED) |
| `code-reviewer` | Review quality, security, patterns | EXECUTE (REVIEW) |
| `explore` | Read-only codebase exploration | UNDERSTAND |
| `planner` | Design step-by-step plans | PLAN |
| `doc-writer` | Technical documentation | Any |
| `general-purpose` | Multi-step research/implementation | Any |

---

## What's Next

### Phase 2.5: User-in-the-Loop (NEXT)

**Status:** Identified, not yet built
**Depends on:** Phase 2 (done)

The Director lifecycle works end-to-end but the user is only involved at plan approval. The Director Philosophy says "delegation without review is abdication" — this applies to the user-Director relationship too. The user should validate understanding, see progress during execution, and review the final result.

**Gap 1: Understanding alignment (UNDERSTAND -> PLAN)**

Currently the agent explores silently, calls `director_complete_understand`, and jumps to PLAN. The user never sees or validates the context document. The `clarify` tool exists but is optional.

*Fix:* Add an approval step after UNDERSTAND — similar to plan approval. Present the context document (affected files, patterns, constraints, risks) to the user for validation before planning begins. "Here's what I found. Does this match your expectations?"

**Gap 2: Code review enforcement (EXECUTE)**

The EXECUTE prompt tells the Director to delegate to `code-reviewer`, but nothing enforces it. The Director can skip review and call `director_complete_slice` immediately. No user visibility into what each slice produced.

*Fix options:*
- Require review delegation before `director_complete_slice` accepts (structural)
- Show user a per-slice summary (what was created/modified, test results) before advancing
- Add a per-slice approval step (heavier, but gives user full control)

**Gap 3: User checkpoint between slices (EXECUTE)**

Once the plan is approved, the Director runs autonomously through all slices. For a 4-slice plan, the user has zero visibility or control until INTEGRATE. This is a lot of unsupervised work.

*Fix:* Optional pause-between-slices mode. After each slice, show a brief summary and let the user approve or course-correct before the next slice begins.

**Gap 4: Final review (INTEGRATE)**

The Director runs tests and calls `director_complete_integration` but the user never sees a summary of what was built. The session just ends.

*Fix:* Before COMPLETE, present a final summary to the user: what was delivered, test results, any known limitations. Similar to a PR description.

---

### Phase 3: Codebase Survey (PARKED)

**Status:** Fully planned, parked
**Plan:** `docs/CODEBASE_SURVEY_PLAN.md`
**Depends on:** Phase 2 (done)

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
- Session persistence for Director state (survive app restart)
- Enforced delegation (Approach B: gate write tools in EXECUTE)
- ClarityDB backing store for queryable codebase intelligence

---

## Dependency Graph

```
Phase 1: Protocol MVP          <- DONE (130 tests, committed)
    |
    v
Phase 2: Adapter + Lifecycle   <- DONE (297 tests, full IDLE-to-COMPLETE cycle)
    |
    v
Phase 2.5: User-in-the-Loop   <- NEXT (understanding alignment, review enforcement, progress visibility)
    |
    v
Phase 3: Codebase Survey       <- PARKED (persistent project intelligence)
    |
    v
Phase 4: Full Integration      <- FUTURE (TUI, auto-detect, ClarityDB)
```

## Key Documents

| Document | Location | Purpose |
|----------|----------|---------|
| Director Philosophy | `docs/DIRECTOR_PHILOSOPHY.md` | Why — the principles and ideology |
| This Roadmap | `docs/DIRECTOR_ROADMAP.md` | What — built vs planned |
| Survey Plan | `docs/CODEBASE_SURVEY_PLAN.md` | Phase 3 detailed plan (parked) |
| Director Protocol | `src/director/` | State machine + adapter + tools |
| Director Tests | `tests/director/` | 297 tests, 12 files |
