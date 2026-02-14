# The Director Philosophy

How ClarAIty builds software — and why.

## Table of Contents

1. [The Problem](#1-the-problem)
2. [The Principles](#2-the-principles)
3. [The Director Protocol](#3-the-director-protocol)
4. [Vertical Slices](#4-vertical-slices)
5. [The Red-Green-Refactor Loop](#5-the-red-green-refactor-loop)
6. [The Hard Rules](#6-the-hard-rules)
7. [Why Slower is Faster](#7-why-slower-is-faster)
8. [The Director Role](#8-the-director-role)

---

## 1. The Problem

Most AI coding agents follow the same broken pattern:

```
User: "Build me X"
Agent: *generates 15 files in 3 minutes*
User: "It doesn't work"
Agent: *patches one thing, breaks two others*
User: "Still broken"
... 3 weeks of debugging ...
```

The agent optimizes for **output speed**, not **correctness**. It's a bricklayer who lays 1000 bricks an hour but doesn't check if the wall is straight. You end up tearing it all down.

The root cause: there is no systematic way to work. No discipline. No protocol.

ClarAIty takes a different approach.

---

## 2. The Principles

### 2.1 Understand Before You Build

The biggest source of failed software isn't bad code — it's **building the wrong thing**. Most agents jump to implementation too fast.

```
Wrong:  Requirements -> Code -> "Why doesn't this work?"
Right:  Problem -> Understanding -> Small experiment -> Feedback -> Iterate
```

Before touching any code, understand the landscape: what exists, what patterns are in place, what will be affected, what could go wrong.

### 2.2 Make It Work, Make It Right, Make It Fast

In that order. Never reverse it.

- **Make it work** — ugly, hacky, but functional. Now you understand the problem.
- **Make it right** — refactor with understanding. Now the code reflects reality.
- **Make it fast** — optimize with evidence, not intuition. Measure first.

### 2.3 Optimize for Change, Not for Perfection

Code will change. The question is: how painful will that change be?

- Small, focused modules over monoliths
- Clear boundaries between components
- Tests that verify behavior, not implementation
- Code that's easy to delete

The best code isn't clever code. It's **obvious code** that a tired developer at 2 AM can understand and safely modify.

### 2.4 Feedback Loops Are Everything

The fastest teams aren't the ones that write code fastest. They're the ones with the **tightest feedback loops**:

```
Seconds:    Type checker catches the error as you type
Minutes:    Unit test tells you the function is wrong
Hours:      Integration test catches the broken interaction
Days:       Code review catches the design flaw
Weeks:      Users tell you the feature misses the point
```

Every layer you can shift left saves exponential pain.

### 2.5 Simplicity is a Discipline

Complexity is the default. Every line of code, every abstraction, every dependency adds weight. Software doesn't die from one bad decision — it dies from a thousand small ones.

Before adding anything, ask:

- Can I solve this without new code?
- Can I solve this with less code?
- Will I understand this in 6 months?
- Can I delete this easily if I'm wrong?

### 2.6 Build for Humans, Not for Computers

Code is read 10x more than it's written. Your audience is the next developer.

```python
# "Smart"
result = {k: v for d in [defaults, config, overrides] for k, v in d.items()}

# Kind
result = {}
result.update(defaults)
result.update(config)
result.update(overrides)
```

Same output. The second one is debuggable, explainable, and modifiable by anyone.

### 2.7 Tests Are a Design Tool

If code is hard to test, the design is wrong. Tests force you to define clear inputs and outputs, isolate dependencies, and think about edge cases before users find them.

But test behavior, not implementation. Tests that break every time you refactor are worse than no tests.

### 2.8 Ship Early, Learn Fast

A half-finished product in users' hands teaches you more than a perfect product in your head.

```
Perfectionism kills projects.
Shipping teaches you what to build next.
```

Find the smallest useful thing and get it out there.

---

## 3. The Director Protocol

The Director Protocol is the systematic workflow that enforces these principles. It is a state machine:

```
UNDERSTAND -> PLAN -> EXECUTE (per slice) -> INTEGRATE -> COMPLETE
```

### 3.1 UNDERSTAND

**Goal:** Build a mental model of the problem and the codebase before writing any code.

The Director:
- Explores the codebase — what exists today?
- Identifies every file that will be affected
- Maps dependencies between components
- Reads existing patterns — how does the codebase handle similar concerns?
- Documents constraints and risks

**Output:** A Context Document — structured understanding of the problem space.

**Rule:** The Director refuses to delegate any coding until it understands the landscape.

### 3.2 PLAN

**Goal:** Decompose the task into vertical slices.

The Director does **not** plan horizontally:

```
BAD (Horizontal):
  Step 1: Create all the database models
  Step 2: Create all the API routes
  Step 3: Create all the frontend components
  Step 4: Wire everything together    <-- everything falls apart here
```

The Director plans in **vertical slices** — each slice is a thin, fully working feature:

```
GOOD (Vertical):
  Slice 1: User can register (one route, one model, one test)
           -> Build it. Test it. IT WORKS.

  Slice 2: User can log in (one route, token generation, one test)
           -> Build it. Test it. IT WORKS.

  Slice 3: Protected routes check the token
           -> Build it. Test it. IT WORKS.
```

Each slice:
- Touches all relevant layers but **minimally**
- Is **independently testable**
- Produces a **working system** at every step
- Integration happens **continuously**, not at the end

There is never a "wire everything together" step because it was always wired together.

**Output:** A Director Plan — ordered list of vertical slices, each with description, affected files, test criteria, and dependencies.

### 3.3 EXECUTE (Per Slice)

Each vertical slice follows the Red-Green-Refactor loop (see [Section 5](#5-the-red-green-refactor-loop)).

The Director:
1. Delegates test writing (RED)
2. Verifies the test fails
3. Delegates implementation (GREEN)
4. Verifies the test passes and ALL tests still pass
5. Delegates cleanup if needed (REFACTOR)
6. Delegates review for quality
7. Commits the working slice

**Rule:** The Director never moves to the next slice until the current one is green.

### 3.4 INTEGRATE

**Goal:** Verify the complete system works.

The Director:
- Runs the full test suite
- Reviews cross-cutting concerns (did changes from multiple slices conflict?)
- Checks conventions and constraints are respected
- Verifies the original task is satisfied

**Output:** A working, tested, reviewed implementation.

---

## 4. Vertical Slices

The vertical slice is the fundamental unit of work in the Director Protocol.

### What Makes a Good Slice

| Property | Description |
|----------|-------------|
| **Thin** | Touches all layers but minimally — just enough for one behavior |
| **Testable** | Has a clear test that proves it works |
| **Independent** | Can be built and verified without other slices being complete |
| **Working** | After this slice, the system is in a working state |
| **Ordered** | Has explicit dependencies on prior slices |

### Slice Anatomy

```
Slice N: [Title — what user-visible behavior this enables]
  Files to create:  [new files, if any]
  Files to modify:  [existing files]
  Test criteria:    [what tests prove this works]
  Depends on:       [which prior slices]
```

### Why Not Horizontal Layers?

Horizontal decomposition (all models, then all routes, then all UI) creates a **big bang integration** at the end. That's where 90% of bugs live — in the seams between layers.

Vertical slices integrate continuously. The seams are tested from slice 1.

---

## 5. The Red-Green-Refactor Loop

For each vertical slice:

```
+---------------------------------------------------+
|  1. RED: Write the test first                     |
|     "What does 'working' look like?"              |
|     -> Write a failing test                       |
|     -> Verify: test FAILS                         |
|                                                   |
|  2. GREEN: Write minimum code to pass             |
|     -> Write implementation                       |
|     -> Verify: test PASSES                        |
|     -> Verify: ALL tests still PASS               |
|                                                   |
|  3. REFACTOR: Clean up, but tests stay green      |
|     -> Only if needed                             |
|     -> ALL tests still PASS                       |
|                                                   |
|  4. COMMIT: Lock in the progress                  |
|     -> Working state is saved                     |
|     -> We can always roll back to here            |
+---------------------------------------------------+
```

### Why RED First?

Writing the test first forces you to think about **what** before **how**. It defines the contract. It creates the tightest possible feedback loop — you know immediately when the implementation works.

### Why Verify ALL Tests?

A change that makes its own test pass but breaks existing tests is not progress. It's lateral movement. Running the full suite after every GREEN step catches regressions immediately, when they're cheapest to fix.

---

## 6. The Hard Rules

These rules are non-negotiable. They are what make the protocol work.

### Rule 1: No Code Without Understanding

The Director does not write or delegate code until the UNDERSTAND phase produces a Context Document. Skipping understanding is how agents generate plausible-looking code that doesn't fit the codebase.

### Rule 2: No Horizontal Decomposition

Work is decomposed into vertical slices. Every slice produces a working system. There is no "integration phase" because integration is continuous.

### Rule 3: No Forward Movement on Red

If tests are failing, the protocol does not advance. The Director fixes or reverts. At no point should the system be in a broken state for more than one slice of work.

### Rule 4: Evidence Over Intuition

Don't assume code works because it looks right. Run the tests. Don't assume a design is good because it's elegant. Measure it. Don't assume a pattern fits because you've seen it before. Read the existing code.

### Rule 5: The Director Reviews, Not Just Delegates

Delegation without review is abdication. The Director checks every subagent's output against:
- Does it follow codebase conventions?
- Does it integrate with existing code?
- Does it pass all tests?
- Is it the simplest solution?

---

## 7. Why Slower is Faster

```
Typical AI coding:
  Generate: 10 minutes
  Debug:    3 weeks
  Total:    3 weeks

Director Protocol:
  Understand:  20 min (explore, map, document)
  Plan:        15 min (decompose into slices)
  Slice 1:     30 min (test + code + verify)
  Slice 2:     20 min (context established)
  Slice 3:     20 min
  Slice 4:     25 min (harder, but isolated)
  Slice 5:     15 min
  Total:       ~2.5 hours, and it works.
```

The "fast" approach isn't fast. It just **feels** fast for the first 10 minutes.

Discipline feels slow in the moment. But discipline is what separates a 2-hour implementation from a 3-week debugging marathon.

---

## 8. The Director Role

The Director is modeled after a film director — not the person who operates the camera, but the person who ensures every department's work serves the story.

| Film Role | Agent Role | Responsibility |
|-----------|-----------|----------------|
| **Director** | Architect/Orchestrator | Understands full codebase, decomposes tasks, reviews results, ensures coherence |
| **Screenwriter** | Planner | Creates detailed plans from high-level requirements |
| **Cinematographer** | Code Writer | Writes actual code following the plan |
| **Editor** | Code Reviewer | Reviews output for quality, consistency, bugs |
| **Script Supervisor** | Test Writer | Ensures changes don't break continuity (tests) |
| **Producer** | Project Manager | Tracks progress, manages scope, reports status |

### What the Director Knows

The Director holds the **architectural vision** — not every line of code, but:
- Architecture and key abstractions
- File responsibilities and dependencies
- Conventions and constraints
- Current state of the task

### What the Director Does

1. **Curates context** — gives each subagent exactly what they need, no more
2. **Enforces the protocol** — no shortcuts, no skipping phases
3. **Reviews all output** — delegation without review is abdication
4. **Maintains coherence** — ensures changes from multiple subagents fit together
5. **Makes judgment calls** — when to simplify, when to push back, when to pivot

### What the Director Does NOT Do

- Write all the code themselves (that's micromanagement)
- Skip understanding to move faster (that's recklessness)
- Accept subagent output without review (that's negligence)
- Over-engineer for hypothetical futures (that's waste)

---

## Summary

The Director Philosophy is simple:

> **Understand the problem. Plan in vertical slices. Build one slice at a time. Verify each one. Never move forward on red.**

It's not revolutionary. It's what good developers have always done. The Director Protocol just makes it systematic and enforceable — so that an AI agent can follow the same discipline that separates senior engineers from junior ones.

The goal isn't to write code faster. It's to **ship working software sooner**.
