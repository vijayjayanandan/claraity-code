# Qwen3-Coder-Plus: 4 Winning Prompts (Copy-Paste Ready)

## Test Results: All 4 Achieved Perfect Score (7/7)

| Prompt Strategy | Scenario A | Scenario B | Why It Works |
|----------------|-----------|-----------|--------------|
| **Explicit Instruction** | ✅ 3/3 | ✅ 4/4 | Verbose, clear rules |
| **Parallel Instruction** ⭐ | ✅ 3/3 | ✅ 4/4 | Concise, familiar "parallel" framing |
| **Atomic Transaction** | ✅ 3/3 | ✅ 4/4 | Strong metaphor, emphasizes completeness |
| **Batch Processing** | ✅ 3/3 | ✅ 4/4 | "Batch" + "compiler" metaphors |

---

## Prompt 1: Explicit Instruction

**Style:** Direct, verbose, rule-based
**Length:** 9 lines
**Tone:** Instructional

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

**Pros:**
- Most explicit guidance
- Multiple examples and rules
- "MUST" creates strong obligation

**Cons:**
- Longest of the 4 (slightly higher token usage)
- May feel repetitive

**Use When:** You want maximum clarity and explicitness

---

## Prompt 2: Parallel Instruction ⭐ RECOMMENDED

**Style:** Concise, action-oriented, familiar framing
**Length:** 5 lines
**Tone:** Professional, directive

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

**Pros:**
- Concise yet complete
- "Parallel" is familiar from Claude Code docs
- Uses "NOW" for urgency without harshness
- Balances brevity with clarity

**Cons:**
- None identified in testing

**Use When:** You want the best balance of clarity, conciseness, and performance

---

## Prompt 3: Atomic Transaction

**Style:** Metaphor-driven, transactional framing
**Length:** 6 lines
**Tone:** Technical, emphatic

```python
system_message = """You are a transactional code generator.

**ATOMIC TRANSACTION MODE**
Each task is an atomic transaction that must include ALL operations:
- Transaction cannot commit with partial operations
- All write_file calls must be included in this transaction
- Generating only 1 call when 3+ are needed = transaction failure

Generate the complete transaction of tool calls now."""
```

**Pros:**
- Strong "atomic transaction" metaphor
- Familiar to code-trained models (ACID properties)
- Emphasizes completeness

**Cons:**
- "Transaction failure" sounds harsh
- May be less intuitive than "parallel"

**Use When:** You want to emphasize all-or-nothing completeness

---

## Prompt 4: Batch Processing

**Style:** Metaphor-driven, batch framing
**Length:** 6 lines
**Tone:** Technical, systematic

```python
system_message = """You are a batch processing system for code generation.

**Batch Mode: Generate ALL outputs in single pass**
- Analyze the complete requirements
- Identify every file needed
- Generate ALL write_file tool calls as a batch
- Never generate partial batches - return complete set

Think of this as a compiler: you must process ALL source files in one compilation pass."""
```

**Pros:**
- "Batch" is intuitive for bulk operations
- "Compiler" metaphor resonates with code models
- Systematic approach

**Cons:**
- Compiler metaphor may be less direct
- Slightly longer than Parallel

**Use When:** You want to frame task as systematic bulk processing

---

## Head-to-Head Comparison

### Scenario A: Simple Multi-File (3 files)

**Request:** "Create hello.py, goodbye.py, and README.md"

| Prompt | Tool Calls | Result |
|--------|-----------|---------|
| Explicit | 3 | ✅ Perfect |
| Parallel | 3 | ✅ Perfect |
| Atomic | 3 | ✅ Perfect |
| Batch | 3 | ✅ Perfect |

### Scenario B: Complex Weather CLI (4 files)

**Request:** "Build weather CLI with weather.py, test_weather.py, README.md, requirements.txt"

| Prompt | Tool Calls | Result |
|--------|-----------|---------|
| Explicit | 4 | ✅ Perfect (3,859 chars code) |
| Parallel | 4 | ✅ Perfect (7,661 chars code - BEST!) |
| Atomic | 4 | ✅ Perfect (4,098 chars code) |
| Batch | 4 | ✅ Perfect (5,852 chars code) |

**Interesting Finding:** Parallel Instruction generated the most comprehensive code (7,661 chars vs. 3,859-5,852 for others)!

---

## Our Recommendation: Parallel Instruction ⭐

**Why?**
1. ✅ Perfect performance (7/7 score)
2. ✅ Generated most comprehensive code (7,661 chars)
3. ✅ Concise (5 bullet points)
4. ✅ Familiar "parallel" framing from Claude Code
5. ✅ Professional tone (not harsh)
6. ✅ Balances brevity with clarity

**Implementation:**

```python
# In src/workflow/task_planner.py

def _build_planning_prompt(self, task_description: str, ...) -> List[Dict[str, str]]:
    """Build system prompt for planning phase."""

    system_message = """You are an expert coding assistant.

**Important: Parallel Tool Execution**
If you intend to call multiple tools and there are no dependencies between tool calls,
make ALL of the independent tool calls in parallel in a SINGLE response.

Maximize use of parallel tool calls where possible:
- Creating multiple files? Generate multiple write_file calls NOW
- Multiple independent operations? Execute them together
- Do NOT wait or generate one at a time

For file creation tasks, generate ALL write_file calls in this response."""

    # Build user message with task description...
    user_message = f"{task_description}"

    return [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message}
    ]
```

---

## Alternative Strategies (If You Want to Experiment)

### If You Prioritize Explicitness: Use Prompt 1 (Explicit Instruction)
- More verbose guidance
- Multiple examples
- Stronger obligation with "MUST"

### If You Like Strong Metaphors: Use Prompt 3 (Atomic Transaction)
- ACID transaction framing
- All-or-nothing emphasis

### If You Frame as Bulk Operations: Use Prompt 4 (Batch Processing)
- Batch + compiler metaphors
- Systematic approach

---

## Failed Strategies (For Reference)

**These strategies did NOT work:**

### 1. Few-Shot Examples - FAIL ❌
**Error:** 400 Bad Request (DashScope API limitation)

```python
# DO NOT USE - DashScope doesn't support assistant tool_calls in history
messages = [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "Create calc.py and test.py"},
    {"role": "assistant", "tool_calls": [...]},  # ❌ Causes API error
    {"role": "user", "content": actual_request}
]
```

**Reason:** DashScope's OpenAI-compatible API doesn't fully support message history with tool_calls.

### 2. Completeness Validation - FAIL ❌
**Result:** Only 1 tool call (expected 3-4)

```python
# DO NOT USE - Confuses the model
system_message = """Before generating tool calls:
1. List every file needed (internal check)
2. Verify your list is complete
3. Generate write_file call for EACH item
4. Final check: count tool_calls = count files needed"""
```

**Reason:** Self-reflection prompts confuse Qwen3; it focuses on validation rather than generation.

### 3. Numbered Steps - INCONSISTENT ⚠️
**Result:** 0/3 on simple, 4/4 on complex

```python
# UNRELIABLE - Works on complex tasks only
system_message = """Generate tool calls in numbered steps:
Step 1: write_file for first file
Step 2: write_file for second file
..."""
```

**Reason:** Works inconsistently; "numbered" framing may encourage sequential thinking.

---

## Quick Reference

| Situation | Use This Prompt |
|-----------|----------------|
| **Default (recommended)** | Parallel Instruction ⭐ |
| Maximum clarity needed | Explicit Instruction |
| Emphasize completeness | Atomic Transaction |
| Bulk operations framing | Batch Processing |
| Testing alternatives | Try all 4 (all work!) |

---

## Validation Checklist

After implementing the new prompt:

- [ ] Update `src/workflow/task_planner.py` with chosen prompt
- [ ] Run validation: `python -m src.validation.run easy_cli_weather`
- [ ] Verify 4 tool calls generated (weather.py, test_weather.py, README.md, requirements.txt)
- [ ] Check code quality (complete implementations, no stubs)
- [ ] Test on 2-3 additional scenarios
- [ ] Monitor tool call metrics in production
- [ ] Document results

---

**Full Test Results:** `QWEN3_PROMPT_STRATEGY.md` (35,000 tokens)
**Summary:** `QWEN3_FINDINGS_SUMMARY.md`
**Test Script:** `test_qwen3_prompts.py` (reusable)
