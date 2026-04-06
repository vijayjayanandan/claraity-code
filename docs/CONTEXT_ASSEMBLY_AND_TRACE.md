# Context Assembly & Trace Viewer Enhancement

> Knowledge captured from investigation session (2026-04-03).
> Use this doc to implement trace viewer enhancements and caching optimization.

---

## Part 1: End-to-End Flow (How Context Is Built and Sent to LLM)

### The Single Orchestrator: ContextBuilder

`src/core/context_builder.py` — the `ContextBuilder` class — is the sole orchestrator of LLM context assembly. It is called from `agent.py:1662` via `self.context_builder.build_context()`.

### The 5 Sources of Context

ContextBuilder (and MemoryManager) pull from **5 distinct sources** to assemble the final `list[dict]` sent to the LLM:

| # | Source | File | Fetched By | When Loaded | Storage |
|---|--------|------|-----------|-------------|---------|
| 1 | System prompt template | `src/prompts/system_prompts.py` | ContextBuilder | Per turn (line 216) | Rebuilt from template each call |
| 2 | CLARAITY.md | `./CLARAITY.md` (project root) | ContextBuilder `_load_project_instructions()` (line 242) | Per turn — disk read | Not cached |
| 3 | Knowledge DB | `.claraity/claraity_knowledge.db` | ContextBuilder `_load_knowledge_brief()` (line 252) | Per turn — SQLite open/query/close | Not cached |
| 4 | Memory files | `.claraity/memory.md` hierarchy | MemoryManager `load_file_memories()` (line 91) | **Once at startup** | Cached in `self.file_memory_content` |
| 5 | MessageStore | In-memory `dict[str, Message]` | MemoryManager `get_context_for_llm()` (line 787) | Per turn — in-memory read | In-memory projection |

### Assembly Order (ContextBuilder.build_context, lines 216-376)

```
Step 1: system_prompt = get_system_prompt(language, task_type)     # template
Step 2: system_prompt += plan_mode_injection (if active)           # conditional
Step 3: system_prompt += director_injection (if active)            # conditional
Step 4: system_prompt += _load_project_instructions()              # CLARAITY.md disk read
Step 5: system_prompt += _load_knowledge_brief()                   # SQLite query
Step 6: Compress system_prompt if > 15% of context window
Step 7: memory_context = memory.get_context_for_llm()
        # Inside MemoryManager.get_context_for_llm (line 727):
        #   - Adds system_prompt as first message
        #   - Adds memory files as system message (if loaded)
        #   - Adds episodic memory summary (if no MessageStore)
        #   - Adds conversation from MessageStore.get_llm_context() (in-memory)
Step 8: Assemble final list:
        [0] system message (prompt + CLARAITY.md + knowledge brief)
        [1] system message (memory files)         # if loaded
        [2] system message (file references)       # if user attached files
        [3] system message (agent state/todos)     # if incomplete tasks
        [4..N] conversation history from MessageStore (user/assistant/tool messages)
```

### What MessageStore Contains

`src/session/store/memory_store.py` — an in-memory `dict[str, Message]` with indexes.

Each `Message` has a `role`:
- `system` — compaction summaries, permission mode changes, tool approvals
- `user` — user's typed input
- `assistant` — LLM's response (text + tool_calls)
- `tool` — tool execution results (keyed by tool_call_id)

**JSONL is the ledger, MessageStore is the projection.**
- New session: messages accumulate in-memory as generated. JSONL is append-only write.
- Resumed session: `SessionHydrator` replays JSONL into MessageStore at startup. After that, same in-memory reads.
- `get_llm_context()` filters: post-compaction only, mainline only, strips ClarAIty meta via `to_llm_dict()`.

### Memory Files Hierarchy

`src/memory/file_loader.py` loads from 3 levels:
```
Enterprise:  /etc/claraity/memory.md  (Linux) or C:/ProgramData/claraity/memory.md (Windows)
User:        ~/.claraity/memory.md
Project:     .claraity/memory.md  (traverses upward from cwd)
```
Supports `@import` syntax for including other files. Loaded once at `MemoryManager.__init__()`.

### Who Calls the LLM

**`CodingAgent`** (`agent.py`) calls `self.llm` directly (line 1824):

```python
llm_stream = self.llm.generate_provider_deltas_async(
    messages=current_context,      # assembled context list
    tools=self._get_tools(),       # tool schemas
    tool_choice="auto",
    **_llm_kwargs,                 # thinking_budget if configured
)
```

No intermediary between ContextBuilder output and LLM call. `self.llm` is one of:
- `OpenAIBackend` — OpenAI, OpenRouter, Kimi, any OpenAI-compatible
- `AnthropicBackend` — Claude/Anthropic API
- `OllamaBackend` — Local Ollama models

### The Tool Loop (agent.py lines 1700-2795)

```
current_context = context.copy()    # line 1698 — copy once

while True:                         # line 1700
    iteration += 1
    # Budget checks (iteration limit, wall time, user interrupt)

    # Fix orphaned tool_calls in current_context
    current_context = self._fix_orphaned_tool_calls(current_context)

    # Start assistant stream in MemoryManager
    self.memory.start_assistant_stream(provider, model)

    # Call LLM with current_context
    llm_stream = self.llm.generate_provider_deltas_async(current_context, tools)

    # Stream deltas:
    #   - memory.process_provider_delta(delta) → updates MessageStore + JSONL
    #   - yield TextDelta/ThinkingDelta → to TUI/UI

    # If no tool_calls → break (done)

    # For each tool_call:
    #   - ToolGatingService.evaluate() → ALLOW / DENY / NEEDS_APPROVAL / BLOCKED_REPEAT
    #   - If NEEDS_APPROVAL → await ui.wait_for_approval() (User ↔ Agent)
    #   - If ALLOWED → execute tool
    #   - memory.add_tool_result() → MessageStore + JSONL

    # Append to current_context (NOT rebuilt from MessageStore):
    current_context.append(assistant_message_with_tool_calls)
    current_context.extend(tool_result_messages)

    # Continue loop → next LLM call with updated context
```

**Key insight:** `current_context` is NOT rebuilt from MessageStore each iteration. It's mutated in-place by appending. It's only rebuilt from scratch:
1. After **compaction** (line 1947) — context too large
2. Never from the tool loop itself

So MessageStore and `current_context` are **two parallel representations** — MessageStore is durable truth, `current_context` is the working copy.

### Approval Flow (agent.py lines 2230-2388)

When `GateAction.NEEDS_APPROVAL`:
```
1. Set tool state → PENDING
2. Set tool state → AWAITING_APPROVAL
3. await ui.wait_for_approval(call_id, tool_name, timeout=None, force_approval=is_safety)
4. If APPROVED → set state APPROVED → continue to execution
5. If REJECTED → set state REJECTED → add synthetic rejection tool_result → break tool loop
6. If TIMEOUT → set state CANCELLED → add timeout tool_result
```

The 4-check pipeline in ToolGatingService.evaluate() (src/core/tool_gating.py:360):
```
1. Repeat detection (blocked_repeat)
2. Plan mode gate
3. Director gate
4. Command safety gate (SAFETY FLOOR, cannot be bypassed)
5. Category-based approval check → NEEDS_APPROVAL or ALLOW
```

### Compaction (agent.py lines 1918-1966)

Triggered when LLM reports input_tokens >= 85% of context window:
```
1. yield ContextCompacting event
2. memory.compact_conversation_async(input_tokens, llm_backend)
   # Asks the LLM to summarize old messages
   # Sets compaction boundary in MessageStore
3. If messages removed > 0:
   current_context = context_builder.build_context(...)   # FULL REBUILD from all 5 sources
4. yield ContextCompacted event
```

### Iteration Count

`iteration` variable exists at agent.py:1701 (`iteration += 1`). Used for budget checks and logging. Currently **NOT passed to any trace method** — TraceIntegration has no awareness of iteration number. Only `_llm_call_n` (LLM call counter) exists in trace.

---

## Part 2: Trace Viewer Enhancement Plan

### Current State (7 actors, working)

Actors: User, Agent, Memory, LLM, Gating, Tools, Persistence/JSONL
Events: 10 types covering basic flow
Missing: Context assembly detail, approval flow, iteration visibility, compaction

### Proposed Actors (7, renamed for clarity)

| Actor | Replaces | Character | Why |
|-------|----------|-----------|-----|
| You | User | Person at laptop | Same |
| Agent | Agent | Brain | The orchestrator |
| Context Builder | Memory | Assembler/factory | Honest — shows the 5-source assembly |
| LLM | LLM | AI symbol | Same |
| Gating | Gating | Checkpoint | Same |
| Tools | Tools | Wrench | Same |
| Store | Persistence/JSONL | Filing cabinet | Combined read + write (MessageStore + JSONL) |

### New Trace Events to Add

#### Context Assembly (5 sub-steps, shown on first turn; condensed on subsequent turns)

| Event | From → To | Type | Data |
|-------|-----------|------|------|
| `context_start` | Agent → Context Builder | context | "Building context for turn N" |
| `context_system_prompt` | Context Builder (internal) | context_source | System prompt template loaded |
| `context_claraity_md` | Context Builder (internal) | context_source | CLARAITY.md content (or "not found") |
| `context_knowledge_db` | Context Builder (internal) | context_source | Knowledge brief loaded (or "no DB") |
| `context_memory_files` | Context Builder (internal) | context_source | Memory files (or "none loaded") |
| `context_store_fetch` | Context Builder → Store | context_source | Conversation history (N messages, M tokens) |
| `context_assembled` | Context Builder → Agent | context | Final stats: total messages, token count, pressure |

On subsequent turns (turn > 1), collapse source steps into one:
`context_rebuilt` — "Context updated (same sources, N new conversation messages)"

#### Approval Flow (new events)

| Event | From → To | Type | Data |
|-------|-----------|------|------|
| `approval_request` | Gating → You | approval | Tool name, args, safety reason, permission mode |
| `approval_result` | You → Gating | approval | Approved/rejected, feedback, wait duration |

New SVG edge needed: Gating ↔ You

#### Iteration Markers

| Event | From → To | Type | Data |
|-------|-----------|------|------|
| `iteration_start` | Agent (internal) | iteration | "Iteration N of tool loop" |

#### Compaction

| Event | From → To | Type | Data |
|-------|-----------|------|------|
| `compaction_start` | Agent → Store | compaction | "Context at X% capacity, compacting" |
| `compaction_complete` | Store → Agent | compaction | "Removed N messages, rebuilt context" |

#### Store Writes (currently missing)

| Event | From → To | Type | Data |
|-------|-----------|------|------|
| `store_user_msg` | Agent → Store | persist | User message saved |
| `store_assistant_msg` | Agent → Store | persist | Assistant message saved (streaming) |
| `store_tool_result` | Agent → Store | persist | Tool result saved |

### Complete Animated Flow (Per Turn)

```
TURN START
  1. You → Agent                     user message
  2. Agent → Store                   save user message

CONTEXT ASSEMBLY (first turn: all steps; later turns: condensed)
  3. Agent → Context Builder         "build context"
  4. Context Builder: System Prompt   (template)
  5. Context Builder: CLARAITY.md     (disk)
  6. Context Builder: Knowledge DB    (SQLite)
  7. Context Builder: Memory Files    (cached)
  8. Context Builder → Store          fetch conversation history
  9. Context Builder → Agent          assembled (N msgs, M tokens)

ITERATION 1
  10. Agent → LLM                    context + tools (iter=1)
  11. LLM → Agent                    response + tool_calls
  12. Agent → Store                  save assistant message
  13. Agent → Gating                 evaluate tools
  14. Gating → Agent                 ALLOWED
  15. Agent → Tools                  execute
  16. Tools → Agent                  results
  17. Agent → Store                  save tool results

ITERATION 2 (with approval)
  18. Agent → LLM                    updated context (iter=2)
  19. LLM → Agent                    response + tool_calls[edit_file]
  20. Agent → Gating                 evaluate(edit_file)
  21. Gating → You                   NEEDS_APPROVAL
  22. You → Gating                   APPROVED
  23. Agent → Tools                  execute
  24. Tools → Agent                  results
  25. Agent → Store                  save tool results

ITERATION 3 (final)
  26. Agent → LLM                    updated context (iter=3)
  27. LLM → Agent                    final text response
  28. Agent → Store                  save response
  29. Agent → You                    display response

TURN END
```

### Files to Modify

**Python (trace emission):**
- `src/core/trace_integration.py` — Add new methods: `on_context_start()`, `on_context_source()`, `on_context_assembled()`, `on_approval_request()`, `on_approval_result()`, `on_iteration_start()`, `on_compaction_start()`, `on_compaction_complete()`, `on_store_write()`
- `src/core/agent.py` — Add ~10 one-liner `self._trace.*` calls at the right points
- `src/core/context_builder.py` — Pass trace integration through (or emit events via callback)

**TypeScript (trace rendering):**
- `claraity-vscode/webview-ui/src/components/TracePanel.tsx` — Update SVG layout, add Context Builder actor, add Gating↔You edge, handle new event types, update mock data
- `claraity-vscode/src/sidebar-provider.ts` — No changes needed (reads JSONL generically)

---

## Part 3: Caching Optimization

### Problem

Three static sources are re-fetched unnecessarily on every `build_context()` call:

| Source | Current behavior | Cost per call |
|--------|-----------------|---------------|
| `get_system_prompt()` | Rebuilds string from template | ~0.1ms (CPU only) |
| `_load_project_instructions()` | Reads CLARAITY.md from disk | ~1-3ms (disk I/O) |
| `_load_knowledge_brief()` | Opens SQLite, queries, closes | ~2-5ms (disk I/O) |

Total waste: ~3-8ms per turn. Not user-visible (LLM takes 2-30s), but architecturally wrong.

### Already Correct

- **Memory files**: Cached in `MemoryManager.file_memory_content` at startup. Done right.
- **MessageStore**: Must be fetched each time (conversation changes). Correct.

### Proposed Fix

Cache the three static sources in `ContextBuilder.__init__()` or on first `build_context()` call:

```python
class ContextBuilder:
    def __init__(self, ...):
        # ... existing init ...

        # Cache static sources (don't change during session)
        self._cached_system_prompt: str | None = None
        self._cached_project_instructions: str | None = None
        self._cached_knowledge_brief: str | None = None

    def build_context(self, ...):
        # 1. System prompt (cache on first call, varies by language/task_type)
        cache_key = (language, task_type)
        if self._cached_system_prompt_key != cache_key:
            self._cached_system_prompt = get_system_prompt(language, task_type)
            self._cached_system_prompt_key = cache_key
        system_prompt = self._cached_system_prompt

        # 2. Project instructions (cache on first call)
        if self._cached_project_instructions is None:
            self._cached_project_instructions = self._load_project_instructions()

        # 3. Knowledge brief (cache on first call)
        if self._cached_knowledge_brief is None:
            self._cached_knowledge_brief = self._load_knowledge_brief()

        # Rest unchanged — plan mode, director, memory context are dynamic
```

### Nuance: System Prompt Varies by Parameters

`get_system_prompt(language, task_type)` takes parameters. In practice, these are always `("python", "chat")` in the current codebase, but the cache key should include them for correctness.

### Nuance: Plan Mode & Director Injections Are Dynamic

These are correctly NOT cached — they change based on current state:
- `plan_mode_state.is_active` / `plan_mode_state.is_awaiting_approval()`
- `director_adapter.is_active` / `director_adapter.get_prompt_injection()`

### Invalidation

No invalidation needed during a session. If the user edits CLARAITY.md or updates the knowledge DB mid-session, they'd need to restart. This matches how memory files already work (loaded once at startup).

Optional: Add a `reload_context_cache()` method for explicit invalidation if needed later.

### Test Plan

1. Unit test: Verify `_load_project_instructions()` called once across multiple `build_context()` calls (mock the disk read)
2. Unit test: Verify `_load_knowledge_brief()` called once across multiple `build_context()` calls (mock the SQLite query)
3. Unit test: Verify system prompt cache key handles `(language, task_type)` changes
4. Integration test: Verify full context output is identical before and after caching change
