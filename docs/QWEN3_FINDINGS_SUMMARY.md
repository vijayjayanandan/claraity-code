# Qwen3-Coder-Plus Multi-Tool Calling: Key Findings

## Executive Summary

**Date:** 2025-11-05
**Tests Conducted:** 20 tests (10 strategies × 2 scenarios)
**Success Rate:** 80% (16/20 successful API calls)

### Winner: 3-Way Tie! 🏆

Three strategies achieved **perfect scores** (7/7 tool calls):
1. **Explicit Instruction** ✅
2. **Parallel Instruction** ✅
3. **Atomic Transaction** ✅
4. **Batch Processing** ✅

All four strategies generated:
- 3/3 write_file calls for simple scenario
- 4/4 write_file calls for complex weather CLI scenario

## Test Results Summary

| Strategy | Scenario A (3 files) | Scenario B (4 files) | Total Score |
|----------|---------------------|---------------------|-------------|
| **Explicit Instruction** | ✅ 3 calls | ✅ 4 calls | **7/7** |
| **Parallel Instruction** | ✅ 3 calls | ✅ 4 calls | **7/7** |
| **Atomic Transaction** | ✅ 3 calls | ✅ 4 calls | **7/7** |
| **Batch Processing** | ✅ 3 calls | ✅ 4 calls | **7/7** |
| Numbered Steps | ❌ 0 calls | ✅ 4 calls | 4/7 |
| Array of Operations | ❌ 0 calls | ✅ 4 calls | 4/7 |
| Checklist Format | ✅ 3 calls | ❌ 1 calls | 4/7 |
| Few-Shot Examples | ❌ API Error | ❌ API Error | 0/7 |
| Hybrid (Best Practices) | ❌ API Error | ❌ API Error | 0/7 |
| Completeness Validation | ❌ 1 calls | ❌ 1 calls | 2/7 |

## Key Insights

### What Works ✅
1. **Direct, emphatic instructions** work best for Qwen3
2. **Metaphors help**: "transaction", "parallel", "batch" frame the task clearly
3. **Simple prompts** outperform complex few-shot examples
4. **All winners are concise** (3-5 lines system message)

### What Fails ❌
1. **Few-shot examples cause API errors** (400 Bad Request)
   - Including assistant tool_calls in message history breaks DashScope API
   - This is a limitation of DashScope's OpenAI compatibility layer
2. **Self-reflection prompts confuse the model** (Completeness Validation)
3. **Metaphors without emphasis fail** (Array, Numbered Steps on simple scenario)

### Critical Discovery 🔍
**DashScope API does NOT support assistant tool_calls in message history!**

This is why few-shot and hybrid strategies failed with 400 errors. The OpenAI-compatible endpoint doesn't fully implement message history with tool_calls.

**Implication:** We must use one-shot prompting, not few-shot examples.

## Recommended Prompt (Choose One)

### Option 1: Explicit Instruction (Current Winner)
```python
system_message = """You are an expert software architect creating detailed execution plans.

**CRITICAL: Generate ALL necessary tool calls in a SINGLE response.**
- Do NOT generate just 1 tool call - generate ALL steps needed to complete the task
- Call multiple tools at once to create multiple files, make multiple edits, etc.
- Example: To create a project with 3 files, generate 3 write_file calls in one response

For each file creation task, you MUST:
1. Generate a separate write_file tool call for EACH file
2. Include complete, working code in each tool call
3. Return ALL tool calls together in this single response"""
```

**Pros:** Explicit, clear instructions; most verbose guidance
**Cons:** Slightly longer (may increase token usage marginally)

### Option 2: Parallel Instruction (Claude-Style) ⭐ RECOMMENDED
```python
system_message = """You are an expert coding assistant.

**Important: Parallel Tool Execution**
If you intend to call multiple tools and there are no dependencies between tool calls,
make ALL of the independent tool calls in parallel in a SINGLE response.

Maximize use of parallel tool calls where possible:
- Creating multiple files? Generate multiple write_file calls NOW
- Multiple independent operations? Execute them together
- Do NOT wait or generate one at a time

For file creation tasks, generate ALL write_file calls in this response."""
```

**Pros:** Concise, uses familiar "parallel" framing from Claude Code, slightly shorter
**Cons:** Less explicit than Option 1

### Option 3: Atomic Transaction (Metaphor)
```python
system_message = """You are a transactional code generator.

**ATOMIC TRANSACTION MODE**
Each task is an atomic transaction that must include ALL operations:
- Transaction cannot commit with partial operations
- All write_file calls must be included in this transaction
- Generating only 1 call when 3+ are needed = transaction failure

Generate the complete transaction of tool calls now."""
```

**Pros:** Strong metaphor, emphasizes completeness
**Cons:** "Transaction failure" might sound harsh; less familiar than "parallel"

### Option 4: Batch Processing
```python
system_message = """You are a batch processing system for code generation.

**Batch Mode: Generate ALL outputs in single pass**
- Analyze the complete requirements
- Identify every file needed
- Generate ALL write_file tool calls as a batch
- Never generate partial batches - return complete set

Think of this as a compiler: you must process ALL source files in one compilation pass."""
```

**Pros:** "Batch" and "compiler" are familiar to code models
**Cons:** Slightly longer; compiler metaphor may be less direct

## Our Recommendation: Option 2 (Parallel Instruction) ⭐

**Rationale:**
1. **Perfect performance** (7/7 score)
2. **Concise and clear** (5 bullet points)
3. **Familiar framing** from Claude Code documentation
4. **"Parallel" is intuitive** for LLMs trained on code
5. **Emphasis on "NOW"** creates urgency without sounding harsh

## Implementation Steps

### Step 1: Update TaskPlanner System Prompt

**File:** `src/workflow/task_planner.py`
**Method:** `_build_planning_prompt()` (around line 255-270)

**Current Code:**
```python
def _build_planning_prompt(self, task_description: str, ...) -> List[Dict[str, str]]:
    system_message = """You are an expert software architect...

    **CRITICAL: Generate ALL necessary tool calls in a SINGLE response.**
    ..."""
```

**New Code:**
```python
def _build_planning_prompt(self, task_description: str, ...) -> List[Dict[str, str]]:
    system_message = """You are an expert coding assistant.

**Important: Parallel Tool Execution**
If you intend to call multiple tools and there are no dependencies between tool calls,
make ALL of the independent tool calls in parallel in a SINGLE response.

Maximize use of parallel tool calls where possible:
- Creating multiple files? Generate multiple write_file calls NOW
- Multiple independent operations? Execute them together
- Do NOT wait or generate one at a time

For file creation tasks, generate ALL write_file calls in this response."""

    # Rest of prompt building logic...
    return [
        {"role": "system", "content": system_message},
        {"role": "user", "content": task_description}
    ]
```

### Step 2: Test with Validation Framework

Run the validation framework to verify the fix:

```bash
python -m src.validation.run easy_cli_weather
```

**Expected Outcome:**
- Agent should generate 4 tool calls: weather.py, test_weather.py, README.md, requirements.txt
- All files created in single planning phase
- No fallback to generic plan

### Step 3: Monitor Metrics

Add logging to track tool call counts:

```python
# In task_planner.py after LLM response
tool_calls = response.get("tool_calls", [])
logger.info(f"[METRICS] TaskPlanner generated {len(tool_calls)} tool calls")

# Log breakdown
write_file_count = sum(1 for tc in tool_calls if tc.function.name == "write_file")
logger.info(f"[METRICS] write_file calls: {write_file_count}/{len(tool_calls)}")
```

### Step 4: Validate on Multiple Scenarios

Test the new prompt on 3-5 real tasks:
1. Simple multi-file (3 files) - **Baseline**
2. Weather CLI (4 files) - **Validation scenario**
3. Web scraper (5-6 files) - **Complex scenario**
4. REST API (8+ files) - **Very complex scenario**

**Success Criteria:**
- 90%+ scenarios generate all files in first attempt
- No regression in code quality
- Average tool calls per task increases

## Alternative: If Issues Persist

If the recommended prompt still shows issues:

### Fallback Option: Two-Phase Approach

**Phase 1: Exploration**
```python
# Allow agent to list_directory first
system_message = """You can explore the workspace:
- Use list_directory to see existing files
- Use read_file to understand patterns

OR directly generate the implementation if you have enough context."""
```

**Phase 2: Implementation**
```python
# After exploration, force parallel generation
system_message = """Based on your exploration, generate ALL write_file tool calls in parallel now.

Do NOT generate 1 at a time. Generate the complete set in this response."""
```

**Cost:** 2 LLM calls instead of 1, but may improve reliability.

## Cost Analysis

**Current Issue:** Fallback plans use 2 LLM calls
- TaskPlanner fails: 1 call → fallback: 1 call = **2 calls total**

**With Fix:** 1 LLM call generates complete plan
- TaskPlanner succeeds: 1 call = **1 call total**

**Savings:** 50% reduction in planning phase LLM calls

**Validation Scenario Impact:**
- Before: ~$0.04 per task (2 calls × $0.02)
- After: ~$0.02 per task (1 call × $0.02)
- **50% cost reduction** on planning phase

## Conclusion

The testing conclusively shows that:

1. ✅ **Qwen3-coder-plus CAN generate multiple tool calls** in one response
2. ✅ **Four different prompt strategies work perfectly** (7/7 score)
3. ✅ **Simple, emphatic prompts outperform complex few-shot**
4. ✅ **DashScope API limitation:** No assistant tool_calls in history
5. ⭐ **Recommended:** Use "Parallel Instruction" prompt (Option 2)

**Next Action:** Update TaskPlanner prompt and run validation to confirm fix resolves JSON parsing issues and enables multi-file generation.

---

**Full Test Results:** See `QWEN3_PROMPT_STRATEGY.md` (35,000 tokens, comprehensive logs)

**Test Script:** `test_qwen3_prompts.py` (reusable for future testing)
