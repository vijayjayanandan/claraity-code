# Compaction Trigger Redesign

## CURRENT: Why It Never Fires

```
  stream_response() tool loop
  ============================

  iteration 1:
      current_context -----> LLM call
                               |
                               v
                          response + usage.prompt_tokens = 8,432
                               |
                               v
                          ContextUpdated(used=8432, limit=131072)
                          --> status bar turns GREEN
                          --> nothing else happens

  iteration 2:
      current_context grows (+ assistant msg + tool results)
                       |
                       v
      DEAD CHECK (line 2794):
      memory.needs_compaction(threshold=0.85)
        |
        +---> measures WorkingMemory tokens   <--- WRONG: not what we sent
        +---> compares vs total_context       <--- WRONG: WM is capped at 40%
        +---> result: always False            <--- NEVER TRIGGERS
                       |
                       v
      current_context -----> LLM call
                               |
                               v
                          response + usage.prompt_tokens = 14,201
                               |
                               v
                          ContextUpdated(used=14201, limit=131072)
                          --> status bar turns GREEN
                          --> nothing else happens

  ... keeps growing until LLM rejects with "context length exceeded" ...
```

**Problem:** We have the real token count (`usage.prompt_tokens`) but only use
it to color the status bar. The compaction check uses a different, wrong number.


## AFTER: Use What the LLM Tells Us

```
  stream_response() tool loop
  ============================

  iteration N:
      current_context -----> LLM call
                               |
                               v
                          response + usage.prompt_tokens
                               |
                               v
                      +------------------+
                      | prompt_tokens    |
                      | -----------  ?   |
                      | context_window   |
                      +--------+---------+
                               |
                  < 80%        |          >= 80%
                  (GREEN)      |          (COMPACT)
                     |         |             |
                     v         |             v
                  continue     |    +-----------------------+
                  normally     |    | 1. compact()          |
                               |    |    (details TBD)      |
                               |    |                       |
                               |    | 2. rebuild            |
                               |    |    current_context    |
                               |    |    from build_context |
                               |    |                       |
                               |    | 3. yield              |
                               |    |    ContextCompacted   |
                               |    |    event to UI        |
                               |    +-----------+-----------+
                               |                |
                               |                v
                               |         next iteration uses
                               |         smaller context
                               |
                               v

  Key: ONE threshold, ONE action, ONE source of truth
       (the LLM's own usage.prompt_tokens)
```


## Exact Code Change Location

```
  src/core/agent.py  stream_response()
  ===================================================

  CURRENT (line ~2860):
  ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
  |  # Emit context usage update with real token count |
  |  if (last_usage and ...):                          |
  |      yield ContextUpdated(                         |
  |          used=last_usage.get("input_tokens"),      |
  |          limit=...,                                |
  |          pressure_level=...,                       |
  |      )                                             |
  |                                                    |
  |  # ^^^ We know the real number here                |
  |  #     but we just display it and move on          |
  ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

  REMOVE (line ~2794):
  ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
  |  # Old dead check - measures wrong thing           |
  |  if iteration > 1 and                              |
  |      self.memory.needs_compaction(threshold=0.85): |
  |      ...                                           |
  ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

  ADD (after ContextUpdated yield):
  ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
  |  # Check if compaction needed using REAL tokens    |
  |  if pressure_level in ("orange", "red"):           |
  |      #                                             |
  |      # --- compact (implementation TBD) ---        |
  |      #                                             |
  |      # Rebuild current_context from                |
  |      # build_context() so next LLM call            |
  |      # sees fewer messages                         |
  |      current_context = (                           |
  |          self.context_builder.build_context(...)    |
  |      )                                             |
  |      yield ContextCompacted(...)                   |
  ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
```


## What We Keep vs. Remove

```
  KEEP (already works)            REMOVE (dead/wrong)
  ====================            ===================

  usage.prompt_tokens             memory.needs_compaction()
  from LLM response               (checks WorkingMemory,
  (ground truth)                    not what LLM sees)

  _get_pressure_level()           Old compaction check at
  (already computes               line 2794-2805
  green/yellow/orange/red)         (uses wrong method)

  ContextUpdated event            build_context_with_
  (already emitted)               headroom_guard()
                                   (dead code, never called)
  MessageStore
  ._last_compact_boundary_seq     WorkingMemory.compact()
  (already filters in              (operates on wrong data)
   get_llm_context)
                                  MemoryManager
  PrioritizedSummarizer            .optimize_context()
  (reuse later for                 (delegates to wrong compact)
   compaction implementation)

  build_context()
  (rebuilds from MessageStore
   which respects boundary_seq)
```


## Single Threshold Decision

```
  prompt_tokens / context_window

      0%         70%        80%        100%
      |-----------|----------|----------|
      |   GREEN   |  YELLOW  | COMPACT  |
      |           |          |          |
      | do        | do       | trigger  |
      | nothing   | nothing  | compact  |
      |           | (status  | + rebuild|
      |           |  bar     | context  |
      |           |  only)   |          |
```

Threshold = 80% of context_window.
One check. One action.
