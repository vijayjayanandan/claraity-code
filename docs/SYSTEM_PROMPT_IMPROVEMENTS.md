# System Prompt Improvements

## Executive Summary

Comparison of our system prompts against Claude Code patterns identified **6 critical gaps** and **4 moderate gaps**. Addressing these will reduce bugs, improve token efficiency, and make the agent more reliable.

**Estimated effort:** 2-3 hours
**Expected impact:** ~50% reduction in safety-related bugs, ~10% token savings

---

## Current Prompt Files

| File | Lines | Purpose |
|------|-------|---------|
| `src/prompts/system_prompts.py` | 617 | Core identity, task management |
| `src/prompts/enhanced_prompts.py` | 1,388 | Tool guidance, error handling |
| `src/prompts/native_tools_prompt.py` | 122 | Simplified for native function calling |
| `CLAUDE.md` | 674 | Workflow-specific guidance |

---

## Critical Gaps (Priority 1)

### Gap 1: Missing Safety Invariants

**Problem:** No guidance on limits that must NEVER be bypassed.

**Issues this causes:**
- Infinite retry loops without backoff
- Tool approval spam bypassing user attention
- Memory exhaustion from large file operations
- Token budget overruns

**Fix:** Add to `src/prompts/system_prompts.py`:

```python
SAFETY_AND_LIMITS = """
## Safety Invariants (Never Bypass)

1. **Token budgets** - Warn at 80% utilization, stop at 95%
2. **Timeout limits** - 30s per tool operation, 5-10m per task
3. **File size caps** - Warn if file exceeds 10K lines
4. **Retry limits** - Max 3 attempts on same approach, then escalate
5. **Loop limits** - No unbounded loops; cap recursive calls

## Adversarial Scenario Protection

Prevent abuse patterns:
- User spams "continue" repeatedly → Enforce session-wide task limit
- LLM retries same failing tool → Break after 2 attempts, suggest alternative
- Tasks grow exponentially → Cap total tokens per session
- Tool requests huge files → Implement pagination/chunking

## Verification Before Completion

Before completing any task:
1. All loops terminate (not infinite)
2. All resources released (no leaks)
3. All exceptions handled (not suppressed)
4. All limits respected (budgets, timeouts)
"""
```

---

### Gap 2: Missing Async/Blocking Audit

**Problem:** No guidance on detecting blocking calls in async code.

**Issues this causes:**
- `input()` calls blocking message dispatch
- Event loop freezes during tool operations
- Deadlocks from holding locks across await points

**Fix:** Add to `src/prompts/system_prompts.py`:

```python
ASYNC_SAFETY = """
## Async & Concurrency Safety

### Blocking Call Audit

NEVER use blocking calls in async code:
- [BAD] input() in async function
- [BAD] time.sleep() in async handler
- [BAD] Synchronous db.query() in async context
- [GOOD] await asyncio.sleep()
- [GOOD] Use async-compatible I/O libraries

### Deadlock Prevention

- Don't hold locks while awaiting
- Don't await while holding message dispatch
- Pattern: Acquire lock → compute (sync) → release lock → then await

### Async Verification Checklist

Before deploying async code:
1. No blocking calls in async functions
2. No long-held locks across await points
3. Timeouts on all async operations (30s default)
4. Exception handling for all concurrent operations
"""
```

---

### Gap 3: Missing LLM Feedback Loop

**Problem:** No guidance ensuring LLM receives observations for every action.

**Issues this causes:**
- Tool succeeds but exception suppressed → LLM retries forever
- Agent modifies files → result not sent to LLM → stale context
- Silent failures create infinite loops

**Fix:** Add to `src/prompts/system_prompts.py`:

```python
LLM_FEEDBACK_LOOP = """
## Agent Reasoning Loop

### Critical Rule: Every Action Must Have Observation

For every tool called, the LLM MUST receive the result.

### Anti-Pattern (Forbidden)

```python
# LLM calls tool
result = execute(tool)
# Exception caught silently
except: pass
# Result never sent to LLM → LLM confused, retries forever
```

### Correct Pattern

```python
# LLM calls tool
try:
    result = execute(tool)
    send_observation(result)  # Success case
except Exception as e:
    send_observation(f"Error: {e}")  # Error case - still sent!
# LLM receives observation, adjusts reasoning
```

### Verification

Before task completion:
1. Every tool call has corresponding observation sent to LLM
2. Errors are reported, not suppressed
3. LLM receives enough context for next decision
4. No silent failures that could create infinite loops
"""
```

---

### Gap 4: Missing Security Guidance (OWASP)

**Problem:** No command injection, SQL injection, or XSS prevention guidance.

**Issues this causes:**
- Vulnerable code generated
- Security review failures
- Production incidents

**Fix:** Add to `src/prompts/enhanced_prompts.py` in CODE_QUALITY_PROMPT:

```python
SECURITY_STANDARDS = """
## Security Standards (OWASP Top 10)

### 1. Injection Prevention

**Command Execution:**
- [BAD] os.system(f"rm {user_path}")
- [GOOD] subprocess.run(["rm", user_path])

**SQL Queries:**
- [BAD] db.execute(f"SELECT * FROM users WHERE id={user_id}")
- [GOOD] db.execute("SELECT * FROM users WHERE id=?", (user_id,))

**Shell Commands:**
- Use subprocess with list arguments, never shell=True with user input

### 2. Authentication & Authorization

- Never hardcode credentials
- Use environment variables for secrets
- Validate user permissions before operations

### 3. Input Validation

- Validate all inputs (type, length, format)
- Whitelist allowed characters
- Reject suspicious patterns

### 4. Error Handling

- Don't expose system paths in error messages
- Log security events
- Fail closed (deny by default)

### 5. Output Encoding

- Escape HTML/JS for web output (XSS prevention)
- Sanitize file paths
- Avoid command injection through outputs
"""
```

---

### Gap 5: Missing Concrete Resource Budgets

**Problem:** No explicit timeout values or token budget guidance.

**Issues this causes:**
- Agents run indefinitely
- Token exhaustion without warning
- Poor user experience on failures

**Fix:** Add to `src/prompts/system_prompts.py`:

```python
RESOURCE_BUDGETS = """
## Resource Budgets

### Timeouts

| Operation | Timeout | Rationale |
|-----------|---------|-----------|
| Single tool (read, write, search) | 30 seconds | Most operations complete quickly |
| Complex tool (git, test runner) | 60 seconds | May need more processing |
| Multi-step task | 5-10 minutes | Respects user attention span |
| User decision (approval widget) | 5 minutes | User may be multitasking |

### Token Budgets

| Threshold | Action |
|-----------|--------|
| 70% context used | Proactively summarize old context |
| 80% context used | Warn user, compact aggressively |
| 90% context used | Stop adding, request new conversation |
| 95% context used | Hard stop, explain limitation |

### Retry Limits

| Scenario | Max Attempts | Then... |
|----------|--------------|---------|
| Same approach failing | 3 | Try different approach |
| Different approaches failing | 2 | Ask user for guidance |
| Transient errors (network) | 3 with backoff | Explain and stop |
| Permission errors | 1 | Ask user immediately |
"""
```

---

### Gap 6: Missing Backwards Compatibility Guidance

**Problem:** No guidance on deleting vs deprecating code.

**Issues this causes:**
- Half-dead code cluttering codebase
- Maintenance burden from unused functions
- Reader confusion

**Fix:** Add to `src/prompts/enhanced_prompts.py`:

```python
REFACTORING_GUIDANCE = """
## Refactoring: Delete Completely, Don't Half-Deprecate

When removing code:
- [BAD] Leave with "# TODO: remove after migration"
- [BAD] Keep unused functions "just in case"
- [BAD] Comment out instead of deleting
- [GOOD] Delete immediately when no longer needed
- [GOOD] Use version control for recovery if needed

### Pattern

1. Find all usages of old code (search_code)
2. Migrate all callers to new approach
3. Delete old code completely
4. Clean commit: "Remove [component], migrated to [new approach]"

### Reason

Half-dead code:
- Confuses future readers
- Increases maintenance burden
- Gets copy-pasted by mistake
- Bloats the codebase
"""
```

---

## Moderate Gaps (Priority 2)

### Gap 7: Conflicting Retry Limits

**Problem:** enhanced_prompts.py says "3 retries", system_prompts.py says "2 attempts".

**Fix:** Standardize across all files:

```
- Same approach: 3 retries max
- Different approaches: 2 attempts max
- Then: Ask user for guidance
```

---

### Gap 8: Fragmented Token Estimates

**Problem:** Different files give different token estimates.

**Fix:** Create single authoritative table in `system_prompts.py`:

```python
TOKEN_ESTIMATES = """
## Token Estimation Reference

| Lines of Code | Estimated Tokens | Confidence |
|---------------|------------------|------------|
| 100 | 600 | High |
| 500 | 3,000 | High |
| 1,000 | 6,000 | High |
| 2,000 | 12,000 | Medium |
| 5,000 | 30,000 | Low |

Note: Actual tokens vary by language and comment density.
Python typically has fewer tokens per line than verbose languages.
"""
```

---

### Gap 9: Missing Terminology Definitions

**Problem:** Key terms (iteration, cycle, turn) not formally defined.

**Fix:** Add to `CLAUDE.md` or `system_prompts.py`:

```python
TERMINOLOGY = """
## Key Terms

- **Turn**: One user message + one assistant response
- **Iteration**: One pass through plan-execute-verify cycle (may span turns)
- **Cycle**: Agent's full reasoning loop: perceive → think → plan → act
- **Tool operation**: Single tool invocation (read_file = 1 operation)
- **Task**: User's complete request (may need multiple iterations)
"""
```

---

### Gap 10: No Fail-Fast Philosophy

**Problem:** Focus on retries, not recognizing unrecoverable errors.

**Fix:** Add to `system_prompts.py`:

```python
FAIL_FAST = """
## Fail Fast Principle

If blocked after 2-3 attempts:
1. Explain the issue clearly
2. Ask user for clarification
3. Don't waste tokens on same failing approach
4. Provide specific next step needed:
   - "Need sudo access to modify this file"
   - "Need user decision on which approach to take"
   - "This API requires authentication credentials"
"""
```

---

## Implementation Checklist

### Session 1: Critical Safety (30 min)

- [ ] Add `SAFETY_AND_LIMITS` to `system_prompts.py`
- [ ] Add `ASYNC_SAFETY` to `system_prompts.py`
- [ ] Add `LLM_FEEDBACK_LOOP` to `system_prompts.py`
- [ ] Test agent still functions correctly

### Session 2: Security & Quality (45 min)

- [ ] Add `SECURITY_STANDARDS` to `enhanced_prompts.py`
- [ ] Add `REFACTORING_GUIDANCE` to `enhanced_prompts.py`
- [ ] Add `RESOURCE_BUDGETS` to `system_prompts.py`
- [ ] Run existing tests

### Session 3: Standardization (30 min)

- [ ] Standardize retry limits (3 same, 2 different)
- [ ] Add `TOKEN_ESTIMATES` table
- [ ] Add `TERMINOLOGY` definitions
- [ ] Add `FAIL_FAST` guidance
- [ ] Update `CLAUDE.md` with cross-references

---

## What We Already Do Well

These areas don't need changes:

| Strength | Why It Works |
|----------|--------------|
| Architecture-driven workflow | ClarAIty integration is unique and effective |
| Code review integration | Quality gates catch issues early |
| Windows compatibility | Explicit emoji policy prevents crashes |
| LLM decision making | Detailed routing reduces tool thrashing |

---

## Expected Outcomes

After implementing these improvements:

| Metric | Before | After |
|--------|--------|-------|
| Safety-related bugs | Baseline | -50% |
| Token waste | Baseline | -10% |
| Infinite loop incidents | Occasional | Rare |
| Security vulnerabilities | Not checked | Prevented |
| Agent confusion | Common | Reduced |

---

## Next Steps

1. Review this document
2. Prioritize which gaps to address first
3. Implement in order (critical → moderate)
4. Test after each change
5. Monitor agent behavior for improvements
