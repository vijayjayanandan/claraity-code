# Chapter 6: When Memory Gets Full -- Context Compaction

> **The problem:** Every model has a context window -- a hard limit on how much text it can read at once. GPT-5.4 supports around 128K tokens. Claude's latest models up to 200K. Sounds enormous, but a serious coding session easily burns through it: system prompt, memory files, tool results, long files, back-and-forth conversation. After a few hours of deep work, the agent hits the wall. It can't see far enough back to understand what it's doing. What happens then?

---

## What Is a Context Window?

Think of the context window as the agent's **working desk**.

Everything the agent can currently "see" has to fit on that desk: the system prompt, all the memory files, the entire conversation so far, the tool results it just got back. If you pile too much on the desk, things start falling off the edge -- and those things are gone from the agent's view.

A token is roughly 3/4 of a word. A typical English paragraph is about 100 tokens. A 200K token context window is roughly 150,000 words -- about the length of two novels. That sounds like a lot. But tool results alone can dump thousands of tokens in a single call. Read ten files, run a few commands, have a long conversation -- and you're there.

---

## The Pressure System

ClarAIty doesn't wait for the wall. It monitors context usage after every LLM response and uses a four-color pressure system, just like a fuel gauge:

```
Green   (< 70%)  -- plenty of room, no action needed
Yellow  (70-85%) -- getting full, visible in the context bar
Orange  (85-95%) -- compaction triggered automatically
Red     (> 95%)  -- critically full
```

```python
# src/core/agent.py, line 3175
def _get_pressure_level(self, used_tokens: int) -> str:
    utilization = used_tokens / self.context_builder.max_context_tokens

    if utilization >= 0.95:
        return "red"
    elif utilization >= 0.85:
        return "orange"    # <-- compaction fires here
    elif utilization >= 0.70:
        return "yellow"
    else:
        return "green"
```

The token count comes directly from the LLM's response -- not estimated by ClarAIty, but reported by the model itself. This is the ground truth.

In the VS Code sidebar, you see this as a colored bar:

```
Context  [==========----]  85%
```

When it turns orange, compaction fires automatically -- silently, in the background, while the conversation continues.

---

## What Is Compaction?

Compaction is the agent's version of **taking notes before clearing the whiteboard**.

Imagine a meeting that has been running for three hours. The whiteboard is full -- diagrams, code sketches, decisions. You need space for the next phase. You don't photograph the whole board and keep everything. You write a crisp summary: what was decided, what code matters, what problems were solved, what comes next. Then you erase the board and continue with just the summary.

That's exactly what ClarAIty does:

1. **Read everything** -- the full conversation history
2. **Summarize it** -- using the LLM itself as the summarizer
3. **Replace the conversation** -- old messages evicted, summary inserted as the new starting point
4. **Rebuild the context** -- next LLM call gets a fresh, small context

The agent continues without interruption. You don't need to start a new session.

---

## The Trigger

Compaction fires at **85% utilization**, checked after every assistant response:

```python
# src/core/agent.py, line 1950
COMPACTION_THRESHOLD = 0.85
utilization = input_tokens / self.context_builder.max_context_tokens

if utilization >= COMPACTION_THRESHOLD and not self._compaction_failed:
    yield ContextCompacting(tokens_before=input_tokens)
    messages_removed = await self.memory.compact_conversation_async(
        current_input_tokens=input_tokens,
        llm_backend=self.llm,
    )
```

Two guardrails:
- **`_compaction_failed` cooldown** -- if compaction throws an error, the flag is set and compaction is skipped for the rest of that response. It resets on the next user message. This prevents a broken compaction from looping forever.
- **Minimum message count** -- if there are 4 or fewer messages in context, compaction is skipped (nothing meaningful to summarize yet).

---

## The Summarization: LLM Summarizes Itself

Here's the clever part: ClarAIty uses the **same LLM** to write the summary.

It sends the entire conversation history to the model with a special summarization system prompt:

```python
# src/memory/memory_manager.py, line 1180
summarize_system = {
    "role": "system",
    "content": (
        "You are a summarization assistant. You will receive a conversation "
        "between a user and an AI coding agent. Summarize it for continuation."
    ),
}
```

Then the conversation messages are passed in native format (not flattened to text -- that would waste tokens), followed by an instruction:

```python
summarize_instruction = {
    "role": "user",
    "content": (
        "Create a continuation summary with these sections IN ORDER OF IMPORTANCE:\n\n"
        "## Goal and Key Decisions\n"
        "## All User Messages\n"        # Preserved verbatim -- they're short, they matter
        "## Code Snippets\n"            # Actual code, not descriptions of code
        "## Errors and Fixes\n"         # What went wrong, what fixed it
        "## Files Modified\n"           # File context
        "## Current State\n"            # Where we are, what's next
    ),
}
```

The LLM writes a structured markdown summary. That summary becomes the new starting point for the conversation.

---

## Priority-Based Content Preservation

The summary isn't random -- it's **prioritized**. The most critical information survives even if the token budget is tight:

| Priority | Section | Token Budget | Why |
|----------|---------|-------------|-----|
| 1 | Goal and Key Decisions | 800 | What are we doing and why? |
| 2 | All User Messages | 2000 | Your exact words are ground truth |
| 3 | Code Snippets | 1500 | Code is what we're building |
| 4 | Errors and Fixes | 600 | Don't repeat the same mistakes |
| 5 | Files Modified | 400 | What was touched |
| 6 | Current State | 400 | Where we are right now |
| 7 | Tool Summary | 300 | What tools were used |

**Total soft budget: 6,000 tokens** (or `current_tokens / 6`, whichever is smaller).

A 128K token conversation compacts down to roughly 6,000 tokens -- a 95% reduction -- while preserving everything the agent needs to continue intelligently.

Notice priority 2: **all user messages are preserved verbatim**. They're short (you don't write novels in a chat box), and they're the source of truth for what you actually asked for. The agent can lose long tool outputs and intermediate reasoning. It must not lose your intent.

---

## Fallback: When the LLM Can't Summarize

What if the LLM itself fails? (Network error, API rate limit, model overloaded.)

ClarAIty has a **deterministic fallback** summarizer that runs entirely in Python -- no LLM call needed:

```python
# src/memory/compaction/summarizer.py, line 186
def _generate_deterministic_summary(self, messages):
    # Priority 1: Extract first user message as goal
    # Priority 2: Collect all user messages
    # Priority 3: Extract code blocks (```python, ```js, etc.)
    # Priority 4: Find error sentences using regex patterns
    # Priority 5: Extract file paths from tool calls
    # Priority 6: Take last few sentences from final assistant message
    # Priority 7: Count tool usage
```

It uses regex patterns to extract the same sections the LLM would write. It's less fluent, but it always works. The agent never crashes because the summarizer failed.

The fallback also filters intelligently -- it ignores diagram formats (`mermaid`, `plantuml`) and data formats (`json`, `yaml`, `csv`) in code blocks, because those waste token budget without helping continuation. Only executable code (`python`, `typescript`, `bash`, etc.) is preserved.

---

## What Happens in the MessageStore

When compaction completes, two things are written to the `MessageStore` (and persisted to JSONL):

```python
# src/session/store/memory_store.py, line 762
def compact(self, summary_content, evicted_count, pre_tokens):
    # 1. Insert a compact_boundary marker
    boundary_msg = Message.create_system(
        content="[Conversation compacted]",
        event_type="compact_boundary",
        include_in_llm_context=False,    # <- the LLM never sees this
    )

    # 2. Insert the summary as a user message
    summary_msg = Message.create_user(
        content="[Conversation summary - earlier messages were compacted "
                "to free context space]\n\n" + summary_content,
        is_compact_summary=True,
    )
```

The `compact_boundary` marker acts like a fence. `MessageStore.get_llm_context()` only returns messages **after** the boundary. All the old messages are still in the JSONL file (the ledger is never rewritten), but the LLM only sees the summary going forward.

This means:
- **You can scroll back** in the UI and see the full conversation history
- **The agent continues** with a lean context
- **Session resume** correctly applies the boundary -- old history stays hidden, the summary is the starting point

---

## The Full Compaction Flow

```
After each LLM response:
        |
        v
Agent checks input_tokens / context_window
        |
   >= 85%?  No --> continue normally
        |
       Yes
        |
        v
yield ContextCompacting event  <-- UI shows indicator
        |
        v
compact_conversation_async()
        |
        v
MessageStore.get_llm_context()  <-- get all current messages
        |
        v
[LLM summarizes conversation]
   fails? --> deterministic fallback
        |
        v
MessageStore.compact()
  - insert compact_boundary
  - insert summary as user message
  - old messages now excluded from get_llm_context()
        |
        v
Rebuild current_context from compacted MessageStore
        |
        v
yield ContextCompacted event  <-- UI clears indicator
        |
        v
Next LLM call uses fresh, small context
```

---

## What You See in the UI

When compaction fires, the VS Code status bar shows **"Compacting conversation..."** for the duration of the summarization call. Once complete, the indicator clears and the conversation continues normally. The context bar resets to a lower utilization level -- the visual confirmation that the desk has been cleared.

---

## The Big Picture So Far

We now have an agent that can:
- Call an LLM (Chapter 1)
- Build rich context from 6 memory layers (Chapter 2)
- Remember things across sessions (Chapter 2b)
- Call tools and loop until done (Chapter 3)
- Gate dangerous tools before execution (Chapter 4)
- Persist every conversation to a crash-safe JSONL ledger (Chapter 5)
- Run indefinitely without hitting the context wall (Chapter 6)

Next: how ClarAIty builds a structured knowledge graph of the codebase -- so the agent understands your project's architecture, not just individual files.

---

*Source files: `src/core/agent.py` (lines 1946-1995, 3175-3198), `src/memory/memory_manager.py` (lines 1141-1249), `src/memory/compaction/summarizer.py`, `src/session/store/memory_store.py` (lines 762-822)*
