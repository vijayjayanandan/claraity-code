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

## 6. Completed Background Task Notifications

```
Task [task_id] (type: local_agent) (status: completed) (description: [short description])
You can check its output using the TaskOutput tool.
```

**When injected**: After a background Task agent completes
**Variables**: `task_id` (hex string), task type, status, description
**Purpose**: Notify agent that a previously launched background task has finished, prompt to read results

---

## 7. Plan File Persistence Reminder

```
A plan file exists from plan mode at: [path]

Plan contents:

[full plan markdown content]

If this plan is relevant to the current work and not already complete, continue working on it.
```

**When injected**: At start of continued/new session when a plan file exists from a previous session
**Variables**: Plan file path, full plan contents
**Purpose**: Provide continuity across sessions by surfacing previously created plans

---

## 8. CLAUDE.md / Memory Context Injection

```
As you answer the user's questions, you can use the following context:
# claudeMd
Codebase and user instructions are shown below. Be sure to adhere to these instructions.
IMPORTANT: These instructions OVERRIDE any default behavior and you MUST follow them exactly as written.

Contents of [project_path]\CLAUDE.md (project instructions, checked into the codebase):
[full CLAUDE.md content]

Contents of [memory_path]\MEMORY.md (user's private global instructions for all projects):
[full MEMORY.md content]

IMPORTANT: this context may or may not be relevant to your tasks. You should not respond to
this context unless it is highly relevant to your task.
```

**When injected**: At conversation start and after context compaction
**Variables**: CLAUDE.md path and content, MEMORY.md path and content
**Purpose**: Inject project-specific instructions and persistent user preferences into agent context

---

## 9. Skill Availability Reminder

```
The following skills are available for use with the Skill tool:

- [skill-name]: [description of when to use it]. Examples: [example triggers].
```

**When injected**: At conversation start (first user message) and periodically during conversation alongside tool results
**Variables**: List of available skill names with descriptions and trigger examples
**Purpose**: Remind agent of available slash command skills that can be invoked via the Skill tool

---

## 10. Pre-Read File Results (Session Continuation)

When a session is continued from a previous conversation, the system injects prior Read tool calls and their results as system reminders:

```
Called the Read tool with the following input: {"file_path":"[path]"}
```
```
Result of calling the Read tool: "[numbered file content]"
```

**When injected**: At the start of a continued session, for files read before context compaction
**Variables**: File path, full file content with line numbers
**Purpose**: Restore file read context from the previous session so the agent doesn't need to re-read files

---

## 11. Git Status Snapshot

```
gitStatus: This is the git status at the start of the conversation. Note that this status
is a snapshot in time, and will not update during the conversation.
Current branch: [branch]

Main branch (you will usually use this for PRs): [main_branch]

Status:
[git status output]

Recent commits:
[git log output]
```

**When injected**: At conversation start, in environment context
**Variables**: Current branch, main branch, git status output, recent commits
**Purpose**: Give agent awareness of repository state without running git commands

---

## 12. Existing Task List in Nudge

When tasks exist, the task tool nudge includes the current task list:

```
Here are the existing tasks:

#[id]. [[status]] [subject]
#[id]. [[status]] [subject]
...
```

**When injected**: Alongside the task tool usage nudge (Type 4)
**Variables**: Task IDs, statuses, subjects
**Purpose**: Show current task state so agent can update or clean up stale tasks

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

### 2026-02-12
- Added 7 new system reminder types (Types 6-12) observed during LLM config wizard session
- Type 6: Background task completion notifications with task IDs
- Type 7: Plan file persistence across sessions with full content injection
- Type 8: CLAUDE.md and MEMORY.md context injection with override semantics
- Type 9: Skill availability reminders for slash command invocation
- Type 10: Pre-read file results carried over during session continuation
- Type 11: Git status snapshot at conversation start (branch, status, recent commits)
- Type 12: Existing task list appended to task tool nudge
- Total documented types: 12

### 2026-02-13
- Verified injection timing through direct observation in live session:
  - Skills reminder: confirmed injected with the very first user message (not just periodically)
  - CLAUDE.md + MEMORY.md: confirmed injected at conversation start, before first turn
  - Malware check: confirmed injected in every Read tool result (observed twice)
  - Task tools nudge: confirmed injected after several turns without TaskCreate/TaskUpdate usage
  - Git status: confirmed injected at conversation start in environment context
- Updated Type 9 (Skills) to clarify it appears at conversation start, not just periodically
- Key architectural insight: CLAUDE.md is injected as a **separate context block** alongside the system prompt, not baked into the system prompt string itself. This keeps the base system prompt stable and cacheable across different projects. Important design consideration for ClarAIty's CLARAITY.md implementation.
- The task tools nudge (Type 4) includes explicit instruction "Make sure that you NEVER mention this reminder to the user" — demonstrates stealth nudging pattern
