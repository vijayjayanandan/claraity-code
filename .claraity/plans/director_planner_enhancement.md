# Director Plan Mode Enhancement: Planner Subagent Delegation

## Summary

Enhanced the Director mode PLAN phase to support delegating planning work to the specialized `planner` subagent. This allows the director to leverage the planner's expertise for complex implementation planning tasks.

## Changes Made

### 1. Updated PLAN Phase Tool Allowlist
**File:** `src/director/prompts.py`

Added `delegate_to_subagent` to the PLAN phase allowed tools:

```python
_PLAN_TOOLS = READ_ONLY_TOOLS | frozenset({
    "director_complete_plan",
    "clarify",
    "web_search",
    "web_fetch",
    "list_directory",
    "delegate_to_subagent",  # NEW: Allow delegation to planner subagent
    # NOTE: write_file is NOT in this set. The adapter handles it
    # with path-based gating (only .clarity/plans/ allowed).
})
```

### 2. Updated PLAN Phase Prompt
**File:** `src/director/prompts.py`

Enhanced the PLAN phase prompt to document two workflow options:

- **Option A (RECOMMENDED):** Delegate to planner subagent for complex tasks
  - Use `delegate_to_subagent` with `subagent="planner"`
  - Review planner's output
  - Write plan to `.clarity/plans/director_plan.md`
  - Call `director_complete_plan`

- **Option B:** Create plan directly for simple, well-understood tasks
  - Design implementation plan with full detail
  - Write plan document
  - Call `director_complete_plan`

### 3. Verified Planner Subagent Exists
**File:** `src/subagents/config.py`

Confirmed the planner subagent is already defined in the built-in subagent configs:

```python
{
    'name': 'planner',
    'description': 'Implementation planner that explores code and produces detailed step-by-step plans without writing any code',
    'prompt': PLANNER_PROMPT,
    'tools': PLANNER_TOOLS,
}
```

The planner subagent has:
- Read-only exploration tools (read_file, search_code, glob, etc.)
- Web research tools (web_search, web_fetch)
- Specialized prompt for evidence-based planning

### 4. Added Tests
**Files:** 
- `tests/director/test_prompts.py`
- `tests/director/test_adapter.py`

Added comprehensive tests to verify:
- `delegate_to_subagent` is in PLAN phase allowed tools
- PLAN prompt mentions the planner subagent
- Tool gating allows delegation in PLAN phase
- Path-based gating still works for write_file

## Test Results

All 307 director tests pass, including:
- 8 new tests for PLAN phase tool gating
- 2 new tests for PLAN prompt content
- All existing tests continue to pass

## Benefits

1. **Better Planning Quality:** The planner subagent is specialized for creating detailed, evidence-based implementation plans
2. **Separation of Concerns:** Director orchestrates, planner designs
3. **Flexibility:** Director can choose to delegate or plan directly based on task complexity
4. **Consistency:** Planner follows established patterns for plan structure and detail level

## Usage Example

When in PLAN phase, the director can now:

```python
# Delegate to planner subagent
delegate_to_subagent(
    subagent="planner",
    task="""
    Create a detailed implementation plan for adding user authentication.
    
    Context from UNDERSTAND phase:
    - Existing patterns: Flask blueprint pattern
    - Constraints: No emojis, maintain backward compatibility
    - Affected files: src/auth/, src/api/routes.py
    
    Please provide:
    - Step-by-step implementation plan
    - Vertical slices (3-5 recommended)
    - Test criteria for each slice
    - Risk assessment
    """
)
```

The planner will explore the codebase, research best practices, and return a detailed plan that the director can then write to `.clarity/plans/director_plan.md`.

## Backward Compatibility

This change is fully backward compatible:
- Existing director workflows continue to work
- The delegation option is recommended but not required
- All existing tests pass without modification
