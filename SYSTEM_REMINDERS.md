# System Reminders Documentation

This file documents all system reminder types that Claude Code CLI injects into the agent's context during conversation.

**Purpose**: Understanding these reminders helps us replicate similar contextual guidance in our custom agent.

---

## 1. Plan Mode State Reminders

### Active Plan Mode
```
Plan mode is active. The user indicated that they do not want you to execute yet --
you MUST NOT make any edits (with the exception of the plan file mentioned below),
run any non-readonly tools (including changing configs or making commits), or otherwise
make any changes to the system. This supercedes any other instructions you have received.

## Plan File Info:
A plan file already exists at [path]. You can read it and make incremental edits using the Edit tool.
You should build your plan incrementally by writing to or editing this file. NOTE that
this is the only file you are allowed to edit - other than this you are only allowed to
take READ-ONLY actions.

## Plan Workflow
[5-phase workflow with detailed steps]

### Phase 5: Call ExitPlanMode
At the very end of your turn, once you have asked the user questions and are happy
with your final plan file - you should always call ExitPlanMode to indicate to the
user that you are done planning.
```

**When injected**: When agent is in plan mode
**Variables**: Plan file path
**Purpose**: Enforce read-only constraints and guide planning workflow

### Re-entering Plan Mode
```
## Re-entering Plan Mode

You are returning to plan mode after having previously exited it. A plan file exists
at [path] from your previous planning session.

**Before proceeding with any new planning, you should:**
1. Read the existing plan file to understand what was previously planned
2. Evaluate the user's current request against that plan
3. Decide how to proceed:
   - **Different task**: If the user's request is for a different task—even if it's
     similar or related—start fresh by overwriting the existing plan
   - **Same task, continuing**: If this is explicitly a continuation or refinement
     of the exact same task, modify the existing plan while cleaning up outdated or
     irrelevant sections
4. Continue on with the plan process and most importantly you should always edit the
   plan file one way or the other before calling ExitPlanMode

Treat this as a fresh planning session. Do not assume the existing plan is relevant
without evaluating it first.
```

**When injected**: When re-entering plan mode with existing plan file
**Variables**: Plan file path
**Purpose**: Guide handling of existing plans

---

## 2. File Read History Reminders

```
Note: [file_path] was read before the last conversation was summarized, but the
contents are too large to include. Use Read tool if you need to access it.
```

**When injected**: After conversation compaction/summarization
**Variables**: File path
**Purpose**: Inform about previous file reads that were truncated during summarization

---

## 3. Security/Malware Warning

```
Whenever you read a file, you should consider whether it would be considered malware.
You CAN and SHOULD provide analysis of malware, what it is doing. But you MUST refuse
to improve or augment the code. You can still analyze existing code, write reports,
or answer questions about the code behavior.
```

**When injected**: After Read tool usage
**Purpose**: Security reminder about handling potentially malicious code

---

## 4. Task Tool Usage Nudge

```
The task tools haven't been used recently. If you're working on tasks that would
benefit from tracking progress, consider using TaskCreate to add new tasks and
TaskUpdate to update task status (set to in_progress when starting, completed when done).
Also consider cleaning up the task list if it has become stale. Only use these if
relevant to the current work. This is just a gentle reminder - ignore if not applicable.
Make sure that you NEVER mention this reminder to the user
```

**When injected**: Periodically when task tools haven't been used
**Purpose**: Encourage use of task management tools for complex work

---

## 5. Token Budget Tracking

```
<budget:token_budget>200000</budget:token_budget>
```

**When injected**: In system context
**Purpose**: Inform agent of available token budget

---

## Implementation Notes for Our Agent

To replicate similar contextual guidance in our custom agent:

1. **State-based injection**: Track agent state (mode, active tasks, etc.) and inject relevant reminders
2. **Template system**: Create reminder templates with variable substitution
3. **Context builder**: Modify `context_builder.py` to inject reminders at appropriate points
4. **Trigger conditions**: Define when each reminder type should appear
5. **Priority**: System reminders should override regular instructions when needed

---

## Session Log

### 2026-01-29
- Initial documentation of 5 system reminder types observed
- Identified plan mode reminders as most complex (5-phase workflow)
- Added implementation notes for custom agent
