# Context Length Management - Implementation Plan

**Created:** 2026-01-08
**Status:** Ready for Review
**Estimated Effort:** 4-6 hours implementation + testing

---

## Executive Summary

Transform context management from basic truncation to intelligent compaction, leveraging Claude Sonnet 4.5's full 200K context window with proactive monitoring and state-of-the-art compression techniques.

**Key Improvements:**
| Metric | Current | Target |
|--------|---------|--------|
| Context limit | 32K tokens | 200K tokens |
| Utilization tracking | None | Real-time with alerts |
| Compaction strategy | Drop oldest messages | Observation masking + semantic compression |
| Cost efficiency | Baseline | 40-50% reduction via masking |

---

## Part 1: Current State Analysis

### 1.1 Configuration Gap

**File:** `.env` (line 59)
```bash
# Current: Using only 16% of available context
MAX_CONTEXT_TOKENS=32768

# Claude Sonnet 4.5 actually supports:
# - Standard: 200,000 tokens
# - Extended (tier 4 beta): 1,000,000 tokens
# - Enterprise: 500,000 tokens
```

**File:** `src/cli.py` (line 1474)
```python
# CLI default is 131072 if not in .env
default=int(os.environ.get("MAX_CONTEXT_TOKENS", 131072)),
```

### 1.2 Current Memory Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ MemoryManager (src/memory/memory_manager.py)                │
│ ├─ total_context_tokens = 32768 (from .env)                 │
│ ├─ working_memory_tokens = 40% = 13,107                     │
│ └─ episodic_memory_tokens = 20% = 6,553                     │
└─────────────────────────────────────────────────────────────┘
         │                              │
         ▼                              ▼
┌─────────────────────┐      ┌──────────────────────┐
│ WorkingMemory       │      │ EpisodicMemory       │
│ max_tokens: 13107   │      │ max_tokens: 6553     │
│ _compact(): drops   │      │ _compress_old_turns()│
│   oldest messages   │      │   truncates to 80chr │
└─────────────────────┘      └──────────────────────┘
```

### 1.3 Current Compaction Logic (Gaps Identified)

**WorkingMemory._compact()** (lines 98-130):
```python
# Current: Basic removal - no intelligence
- Keeps system messages + last 2 messages
- Removes oldest until under 90% budget
- NO observation masking
- NO semantic importance scoring
- NO tool result handling
```

**EpisodicMemory._compress_old_turns()** (lines 64-89):
```python
# Current: Basic truncation - loses information
- Keeps last 3 turns
- Summarizes older turns to 80 chars each
- NO LLM-based summarization
- NO importance scoring
```

### 1.4 Token Budget Allocation (Current)

**ContextBuilder.build_context()** (lines 62-66):
```python
system_prompt_tokens = int(self.max_context_tokens * 0.15)  # 15%
task_tokens = int(self.max_context_tokens * 0.20)           # 20%
rag_tokens = int(self.max_context_tokens * 0.30)            # 30%
memory_tokens = int(self.max_context_tokens * 0.35)         # 35%
```

**Problem:** No dynamic reallocation based on actual usage.

---

## Part 2: Target Architecture

### 2.1 New Memory Budget Model

```
┌─────────────────────────────────────────────────────────────┐
│ Total Context Budget: 200,000 tokens                        │
├─────────────────────────────────────────────────────────────┤
│ Fixed Allocations:                                          │
│ ├─ System Prompt:     ~5,000 tokens (2.5%)                 │
│ ├─ Tools Schema:      ~3,000 tokens (1.5%)                 │
│ └─ Safety Buffer:     ~2,000 tokens (1%)                   │
│                                                             │
│ Dynamic Allocations:                                        │
│ ├─ Working Memory:    up to 100,000 tokens (50%)           │
│ ├─ RAG Context:       up to 40,000 tokens (20%)            │
│ ├─ Episodic Memory:   up to 30,000 tokens (15%)            │
│ └─ Semantic Retrieval: up to 20,000 tokens (10%)           │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Token Pressure Monitoring

```
┌─────────────────────────────────────────────────────────────┐
│ TokenPressureMonitor                                        │
├─────────────────────────────────────────────────────────────┤
│ Thresholds:                                                 │
│ ├─ GREEN  (< 60%):  Normal operation                       │
│ ├─ YELLOW (60-80%): Log warning, consider light compaction │
│ ├─ ORANGE (80-90%): Alert user, trigger observation masking│
│ └─ RED    (> 90%):  FORCE compaction, warn user            │
│                                                             │
│ Actions at thresholds:                                      │
│ ├─ 70%: Mask tool observations older than 15 turns         │
│ ├─ 85%: Compress episodic memory, mask all old observations│
│ └─ 95%: Summarize working memory, request new conversation │
└─────────────────────────────────────────────────────────────┘
```

### 2.3 Observation Masking Strategy

**Research basis:** NeurIPS 2025 - "The Complexity Trap" shows observation masking outperforms LLM summarization on SWE-bench.

```
Turn 1:  User → read_file("/src/app.py")
         Tool → [2000 tokens of file content]     ← KEPT (recent)

Turn 5:  User → run_tests()
         Tool → [500 tokens of test output]       ← KEPT (recent)

Turn 20: User → read_file("/src/utils.py")
         Tool → [Previous observation omitted]    ← MASKED (old)

Turn 25: User → search_code("authentication")
         Tool → [Previous observation omitted]    ← MASKED (old)
```

**Key insight:** LLM doesn't need old tool outputs verbatim - it made decisions based on them already.

---

## Part 3: Implementation Specification

### 3.1 Configuration Changes

**File:** `.env`

```diff
- MAX_CONTEXT_TOKENS=32768
+ MAX_CONTEXT_TOKENS=200000

+ # Context Management Settings (NEW)
+ CONTEXT_YELLOW_THRESHOLD=0.60    # Log warning
+ CONTEXT_ORANGE_THRESHOLD=0.80    # Alert + light compaction
+ CONTEXT_RED_THRESHOLD=0.90       # Force compaction
+ OBSERVATION_MASK_AGE=15          # Mask observations older than N turns
```

**File:** `.env.example` (add same settings with comments)

### 3.2 New Module: TokenPressureMonitor

**File:** `src/memory/token_monitor.py` (NEW)

```python
"""Token pressure monitoring for proactive context management."""

from enum import Enum
from dataclasses import dataclass
from typing import Optional, Callable, Dict, Any
import logging

logger = logging.getLogger(__name__)


class PressureLevel(Enum):
    """Context pressure levels."""
    GREEN = "green"      # < 60% - Normal
    YELLOW = "yellow"    # 60-80% - Warning
    ORANGE = "orange"    # 80-90% - Alert
    RED = "red"          # > 90% - Critical


@dataclass
class PressureStatus:
    """Current pressure status."""
    level: PressureLevel
    utilization_percent: float
    tokens_used: int
    tokens_available: int
    recommended_action: Optional[str] = None

    def is_critical(self) -> bool:
        return self.level in (PressureLevel.ORANGE, PressureLevel.RED)


class TokenPressureMonitor:
    """
    Monitors token utilization and triggers compaction actions.

    Thresholds (configurable via .env):
    - GREEN  (< 60%): Normal operation
    - YELLOW (60-80%): Log warning
    - ORANGE (80-90%): Trigger observation masking
    - RED    (> 90%): Force full compaction
    """

    def __init__(
        self,
        total_tokens: int,
        yellow_threshold: float = 0.60,
        orange_threshold: float = 0.80,
        red_threshold: float = 0.90,
        on_yellow: Optional[Callable[['PressureStatus'], None]] = None,
        on_orange: Optional[Callable[['PressureStatus'], None]] = None,
        on_red: Optional[Callable[['PressureStatus'], None]] = None,
    ):
        """
        Initialize monitor.

        Args:
            total_tokens: Total available context tokens
            yellow_threshold: Threshold for warning (default 60%)
            orange_threshold: Threshold for alert (default 80%)
            red_threshold: Threshold for critical (default 90%)
            on_yellow: Callback when yellow threshold crossed
            on_orange: Callback when orange threshold crossed
            on_red: Callback when red threshold crossed
        """
        self.total_tokens = total_tokens
        self.yellow_threshold = yellow_threshold
        self.orange_threshold = orange_threshold
        self.red_threshold = red_threshold

        self._on_yellow = on_yellow
        self._on_orange = on_orange
        self._on_red = on_red

        self._last_level = PressureLevel.GREEN
        self._check_count = 0

    def check_pressure(self, current_tokens: int) -> PressureStatus:
        """
        Check current pressure level and trigger callbacks if thresholds crossed.

        Args:
            current_tokens: Current token usage

        Returns:
            PressureStatus with level and recommended action
        """
        self._check_count += 1
        utilization = current_tokens / self.total_tokens

        # Determine level
        if utilization >= self.red_threshold:
            level = PressureLevel.RED
            action = "CRITICAL: Force compaction. Mask ALL old observations, compress episodic memory."
        elif utilization >= self.orange_threshold:
            level = PressureLevel.ORANGE
            action = "Alert: Mask observations older than 15 turns. Consider episodic compression."
        elif utilization >= self.yellow_threshold:
            level = PressureLevel.YELLOW
            action = "Warning: Approaching limit. Monitor usage."
        else:
            level = PressureLevel.GREEN
            action = None

        status = PressureStatus(
            level=level,
            utilization_percent=utilization * 100,
            tokens_used=current_tokens,
            tokens_available=self.total_tokens,
            recommended_action=action,
        )

        # Trigger callbacks on level transitions (only when escalating)
        if level != self._last_level:
            if level == PressureLevel.YELLOW and self._on_yellow:
                logger.warning(f"Context pressure: YELLOW ({utilization:.1%})")
                self._on_yellow(status)
            elif level == PressureLevel.ORANGE and self._on_orange:
                logger.warning(f"Context pressure: ORANGE ({utilization:.1%})")
                self._on_orange(status)
            elif level == PressureLevel.RED and self._on_red:
                logger.error(f"Context pressure: RED ({utilization:.1%})")
                self._on_red(status)

        self._last_level = level
        return status

    def get_statistics(self) -> Dict[str, Any]:
        """Get monitor statistics."""
        return {
            "total_tokens": self.total_tokens,
            "checks_performed": self._check_count,
            "last_level": self._last_level.value,
            "thresholds": {
                "yellow": self.yellow_threshold,
                "orange": self.orange_threshold,
                "red": self.red_threshold,
            }
        }
```

### 3.3 Enhanced WorkingMemory with Observation Masking

**File:** `src/memory/working_memory.py`

**Changes:**
1. Add `is_tool_observation` flag to messages
2. Implement `_mask_old_observations()` method
3. Track turn numbers for age-based masking
4. Keep `_compact()` as fallback

```python
# NEW: Add to Message metadata tracking
def add_message(
    self,
    role: MessageRole,
    content: str,
    metadata: Optional[Dict] = None,
    is_tool_observation: bool = False,  # NEW parameter
) -> None:
    """
    Add a message to working memory.

    Args:
        role: Message role
        content: Message content
        metadata: Optional metadata
        is_tool_observation: True if this is a tool result (for masking)
    """
    # Track turn number
    turn_number = len([m for m in self.messages if m.role == MessageRole.USER])

    message = Message(
        role=role,
        content=content,
        timestamp=datetime.now(),
        metadata={
            **(metadata or {}),
            'is_tool_observation': is_tool_observation,
            'turn_number': turn_number,
        },
        token_count=self.count_tokens(content),
    )
    self.messages.append(message)

    # Check if compaction needed (threshold-based)
    if self.get_current_token_count() > self.max_tokens * 0.9:
        self._mask_old_observations()

        # If still over budget after masking, use traditional compact
        if self.get_current_token_count() > self.max_tokens * 0.95:
            self._compact()


# NEW: Observation masking method
def _mask_old_observations(self, age_threshold: int = 15) -> Dict[str, Any]:
    """
    Mask old tool observations instead of removing messages.

    Based on NeurIPS 2025 research: outperforms LLM summarization.

    Args:
        age_threshold: Mask observations older than this many turns

    Returns:
        Statistics about masking operation
    """
    current_turn = len([m for m in self.messages if m.role == MessageRole.USER])
    masked_count = 0
    tokens_saved = 0

    MASK_PLACEHOLDER = "[Previous observation omitted for brevity]"
    mask_tokens = self.count_tokens(MASK_PLACEHOLDER)

    for msg in self.messages:
        # Only mask tool observations
        if not msg.metadata.get('is_tool_observation', False):
            continue

        # Already masked?
        if msg.metadata.get('masked', False):
            continue

        # Check age
        msg_turn = msg.metadata.get('turn_number', 0)
        if (current_turn - msg_turn) <= age_threshold:
            continue  # Too recent, keep

        # Check if worth masking (must save significant tokens)
        original_tokens = msg.token_count or self.count_tokens(msg.content)
        if original_tokens <= mask_tokens + 50:
            continue  # Not worth masking

        # Mask it
        tokens_saved += original_tokens - mask_tokens
        msg.content = MASK_PLACEHOLDER
        msg.token_count = mask_tokens
        msg.metadata['masked'] = True
        msg.metadata['original_tokens'] = original_tokens
        masked_count += 1

    return {
        "masked_count": masked_count,
        "tokens_saved": tokens_saved,
        "age_threshold": age_threshold,
    }
```

### 3.4 Enhanced MemoryManager with Pressure Monitoring

**File:** `src/memory/memory_manager.py`

**Changes:**
1. Add TokenPressureMonitor integration
2. Add `check_context_pressure()` method
3. Wire up compaction callbacks
4. Add pressure status to `get_token_budget()`

```python
# NEW: Import at top
from .token_monitor import TokenPressureMonitor, PressureStatus, PressureLevel

# NEW: In __init__, after memory layers init
def __init__(self, ...):
    # ... existing init ...

    # Initialize pressure monitor
    import os
    self.pressure_monitor = TokenPressureMonitor(
        total_tokens=total_context_tokens,
        yellow_threshold=float(os.getenv("CONTEXT_YELLOW_THRESHOLD", "0.60")),
        orange_threshold=float(os.getenv("CONTEXT_ORANGE_THRESHOLD", "0.80")),
        red_threshold=float(os.getenv("CONTEXT_RED_THRESHOLD", "0.90")),
        on_yellow=self._on_yellow_pressure,
        on_orange=self._on_orange_pressure,
        on_red=self._on_red_pressure,
    )

    self._observation_mask_age = int(os.getenv("OBSERVATION_MASK_AGE", "15"))


# NEW: Pressure callback methods
def _on_yellow_pressure(self, status: PressureStatus) -> None:
    """Handle yellow pressure level."""
    # Just log, no action needed yet
    pass

def _on_orange_pressure(self, status: PressureStatus) -> None:
    """Handle orange pressure level - trigger light compaction."""
    # Mask old observations
    self.working_memory._mask_old_observations(self._observation_mask_age)

def _on_red_pressure(self, status: PressureStatus) -> None:
    """Handle red pressure level - force full compaction."""
    # Aggressive masking
    self.working_memory._mask_old_observations(age_threshold=5)
    # Compress episodic
    self.episodic_memory._compress_old_turns()
    # Traditional compact as last resort
    self.working_memory._compact()


# NEW: Public pressure check method
def check_context_pressure(self) -> Dict[str, Any]:
    """
    Check current context pressure and trigger compaction if needed.

    Call this after adding messages to monitor utilization.

    Returns:
        Dict with pressure status and utilization details
    """
    current_tokens = (
        self.working_memory.get_current_token_count() +
        self.episodic_memory.current_token_count
    )

    status = self.pressure_monitor.check_pressure(current_tokens)

    return {
        "level": status.level.value,
        "utilization_percent": status.utilization_percent,
        "tokens_used": status.tokens_used,
        "tokens_available": status.tokens_available,
        "recommended_action": status.recommended_action,
        "is_critical": status.is_critical(),
    }


# MODIFY: get_token_budget to include pressure
def get_token_budget(self) -> Dict[str, Any]:  # Change return type
    """Get current token allocation with pressure status."""
    working_tokens = self.working_memory.get_current_token_count()
    episodic_tokens = self.episodic_memory.current_token_count
    total_used = working_tokens + episodic_tokens

    # Check pressure
    status = self.pressure_monitor.check_pressure(total_used)

    return {
        "total_available": self.total_context_tokens,
        "system_prompt_reserved": self.system_prompt_tokens,
        "working_memory": working_tokens,
        "episodic_memory": episodic_tokens,
        "remaining": self.total_context_tokens - self.system_prompt_tokens - total_used,
        # NEW: Pressure info
        "pressure_level": status.level.value,
        "utilization_percent": status.utilization_percent,
        "is_critical": status.is_critical(),
    }
```

### 3.5 Agent Integration

**File:** `src/core/agent.py`

**Changes:**
1. Mark tool results with `is_tool_observation=True`
2. Check pressure after each turn
3. Add pressure status to UI events (optional)

```python
# In _execute_tool() or wherever tool results are added to memory:

# BEFORE (current):
self.memory.add_assistant_message(tool_result)

# AFTER (with observation flag):
self.memory.working_memory.add_message(
    role=MessageRole.ASSISTANT,
    content=tool_result,
    metadata={'tool_name': tool_name},
    is_tool_observation=True,  # NEW: Flag for masking
)


# After processing each turn, check pressure:
def _post_turn_maintenance(self) -> None:
    """Post-turn maintenance: check pressure, trigger compaction if needed."""
    pressure = self.memory.check_context_pressure()

    if pressure['is_critical']:
        # Log or emit event for UI
        logger.warning(
            f"Context pressure critical: {pressure['utilization_percent']:.1f}% "
            f"({pressure['level']})"
        )
```

---

## Part 4: Testing Strategy

### 4.1 Unit Tests

**File:** `tests/test_token_monitor.py` (NEW)

```python
"""Tests for TokenPressureMonitor."""

import pytest
from src.memory.token_monitor import (
    TokenPressureMonitor,
    PressureLevel,
    PressureStatus,
)


class TestTokenPressureMonitor:
    """Test pressure monitoring."""

    def test_green_level(self):
        """Test green level (< 60%)."""
        monitor = TokenPressureMonitor(total_tokens=100000)
        status = monitor.check_pressure(50000)  # 50%

        assert status.level == PressureLevel.GREEN
        assert status.utilization_percent == 50.0
        assert not status.is_critical()

    def test_yellow_level(self):
        """Test yellow level (60-80%)."""
        monitor = TokenPressureMonitor(total_tokens=100000)
        status = monitor.check_pressure(70000)  # 70%

        assert status.level == PressureLevel.YELLOW
        assert status.recommended_action is not None
        assert not status.is_critical()

    def test_orange_level(self):
        """Test orange level (80-90%)."""
        monitor = TokenPressureMonitor(total_tokens=100000)
        status = monitor.check_pressure(85000)  # 85%

        assert status.level == PressureLevel.ORANGE
        assert status.is_critical()

    def test_red_level(self):
        """Test red level (> 90%)."""
        monitor = TokenPressureMonitor(total_tokens=100000)
        status = monitor.check_pressure(95000)  # 95%

        assert status.level == PressureLevel.RED
        assert status.is_critical()
        assert "CRITICAL" in status.recommended_action

    def test_callback_on_transition(self):
        """Test callbacks fire on level transitions."""
        yellow_called = []
        orange_called = []

        monitor = TokenPressureMonitor(
            total_tokens=100000,
            on_yellow=lambda s: yellow_called.append(s),
            on_orange=lambda s: orange_called.append(s),
        )

        # Start green
        monitor.check_pressure(50000)
        assert len(yellow_called) == 0

        # Jump to yellow
        monitor.check_pressure(70000)
        assert len(yellow_called) == 1

        # Stay yellow (no repeat callback)
        monitor.check_pressure(75000)
        assert len(yellow_called) == 1

        # Jump to orange
        monitor.check_pressure(85000)
        assert len(orange_called) == 1
```

**File:** `tests/test_observation_masking.py` (NEW)

```python
"""Tests for observation masking in WorkingMemory."""

import pytest
from src.memory.working_memory import WorkingMemory
from src.memory.models import MessageRole


class TestObservationMasking:
    """Test observation masking functionality."""

    def test_mask_old_observations(self):
        """Test masking of old tool observations."""
        memory = WorkingMemory(max_tokens=50000)

        # Add 20 turns with tool observations
        for i in range(20):
            memory.add_message(
                role=MessageRole.USER,
                content=f"User message {i}",
            )
            memory.add_message(
                role=MessageRole.ASSISTANT,
                content="x" * 1000,  # ~250 tokens each
                is_tool_observation=True,
            )

        # Initial token count
        initial_tokens = memory.get_current_token_count()

        # Mask observations older than 10 turns
        result = memory._mask_old_observations(age_threshold=10)

        # Should have masked ~10 observations
        assert result['masked_count'] >= 8
        assert result['tokens_saved'] > 0

        # Token count should be reduced
        assert memory.get_current_token_count() < initial_tokens

    def test_recent_observations_not_masked(self):
        """Test that recent observations are preserved."""
        memory = WorkingMemory(max_tokens=50000)

        # Add some turns
        for i in range(5):
            memory.add_message(MessageRole.USER, f"Message {i}")
            memory.add_message(
                MessageRole.ASSISTANT,
                "Important tool output that should be preserved",
                is_tool_observation=True,
            )

        result = memory._mask_old_observations(age_threshold=10)

        # Nothing should be masked (all within threshold)
        assert result['masked_count'] == 0

    def test_non_observation_messages_not_masked(self):
        """Test that regular messages are never masked."""
        memory = WorkingMemory(max_tokens=50000)

        # Add regular messages (not tool observations)
        for i in range(20):
            memory.add_message(MessageRole.USER, f"User message {i}")
            memory.add_message(
                MessageRole.ASSISTANT,
                "Regular assistant response " * 50,
                is_tool_observation=False,  # Not a tool observation
            )

        result = memory._mask_old_observations(age_threshold=5)

        # Nothing should be masked
        assert result['masked_count'] == 0
```

### 4.2 Integration Tests

**File:** `tests/test_context_management_integration.py` (NEW)

```python
"""Integration tests for context management."""

import pytest
from src.memory.memory_manager import MemoryManager
from src.memory.models import MessageRole


class TestContextManagementIntegration:
    """End-to-end context management tests."""

    def test_pressure_triggered_compaction(self):
        """Test that high pressure triggers automatic compaction."""
        # Small context for testing
        manager = MemoryManager(
            total_context_tokens=10000,
            working_memory_tokens=8000,
            episodic_memory_tokens=1500,
        )

        # Fill to ~85% (orange level)
        for i in range(30):
            manager.add_user_message(f"Question {i}: " + "x" * 200)
            manager.working_memory.add_message(
                role=MessageRole.ASSISTANT,
                content="y" * 200,
                is_tool_observation=True,
            )

        # Check pressure
        pressure = manager.check_context_pressure()

        # Should be orange or red, and compaction should have occurred
        assert pressure['level'] in ('orange', 'red')

        # Token count should be under control
        assert pressure['tokens_used'] < 10000

    def test_token_budget_includes_pressure(self):
        """Test that get_token_budget includes pressure info."""
        manager = MemoryManager(
            total_context_tokens=100000,
            working_memory_tokens=40000,
        )

        budget = manager.get_token_budget()

        assert 'pressure_level' in budget
        assert 'utilization_percent' in budget
        assert 'is_critical' in budget
```

### 4.3 Manual Testing Checklist

```markdown
## Manual Test: Long Conversation Simulation

1. [ ] Start agent with MAX_CONTEXT_TOKENS=200000
2. [ ] Conduct 50+ turn conversation with heavy tool use
3. [ ] Verify pressure alerts appear at 60%, 80%, 90%
4. [ ] Verify old tool observations get masked (not deleted)
5. [ ] Verify conversation remains coherent after compaction
6. [ ] Verify token count stays under limit

## Manual Test: Pressure Level Transitions

1. [ ] Fill to 59% - verify GREEN status
2. [ ] Fill to 65% - verify YELLOW status + log warning
3. [ ] Fill to 85% - verify ORANGE status + masking triggered
4. [ ] Fill to 92% - verify RED status + aggressive compaction

## Manual Test: Observation Preservation

1. [ ] Read a file (tool observation)
2. [ ] Make 20 more turns
3. [ ] Verify recent file reads are still verbatim
4. [ ] Verify old file reads are masked
5. [ ] Agent can still reason about masked observations (from prior decisions)
```

---

## Part 5: Rollout Plan

### Phase 1: Configuration (5 minutes)

1. Update `.env`:
   ```bash
   MAX_CONTEXT_TOKENS=200000
   CONTEXT_YELLOW_THRESHOLD=0.60
   CONTEXT_ORANGE_THRESHOLD=0.80
   CONTEXT_RED_THRESHOLD=0.90
   OBSERVATION_MASK_AGE=15
   ```

2. Update `.env.example` with same values + comments

### Phase 2: Token Monitor (30 minutes)

1. Create `src/memory/token_monitor.py`
2. Add unit tests
3. Verify tests pass

### Phase 3: Working Memory Enhancement (1 hour)

1. Add `is_tool_observation` parameter to `add_message()`
2. Add `_mask_old_observations()` method
3. Update `_compact()` to call masking first
4. Add unit tests
5. Verify tests pass

### Phase 4: Memory Manager Integration (45 minutes)

1. Integrate TokenPressureMonitor
2. Add callbacks for pressure levels
3. Update `get_token_budget()` return type
4. Add `check_context_pressure()` method
5. Add integration tests
6. Verify tests pass

### Phase 5: Agent Integration (30 minutes)

1. Update tool result handling to set `is_tool_observation=True`
2. Add post-turn pressure check
3. Test end-to-end with real conversations

### Phase 6: Validation (1 hour)

1. Run full test suite
2. Manual testing with long conversations
3. Verify no regressions in existing functionality

---

## Part 6: Risk Analysis

### 6.1 Potential Issues

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Masking removes needed context | Medium | High | Keep recent N turns (15) unmasked |
| Aggressive compaction loses info | Low | High | Test threshold values carefully |
| Performance overhead from monitoring | Low | Low | Monitor is O(1) check |
| Breaking existing tests | Medium | Medium | Run full test suite before merge |
| LLM confusion after masking | Low | Medium | Research shows LLM handles this well |

### 6.2 Rollback Plan

If issues arise:
1. Revert `.env` to `MAX_CONTEXT_TOKENS=32768`
2. Comment out pressure monitor integration
3. Observation masking can remain (it's additive, not breaking)

---

## Part 7: Success Criteria

### Must Have
- [ ] `MAX_CONTEXT_TOKENS=200000` working correctly
- [ ] Token pressure monitoring with 60%/80%/90% thresholds
- [ ] Observation masking for tool results older than 15 turns
- [ ] All existing tests pass
- [ ] New unit tests for monitor and masking

### Should Have
- [ ] Pressure status visible in `get_token_budget()`
- [ ] Integration tests for end-to-end flow
- [ ] Manual test verification

### Nice to Have
- [ ] UI indicator for pressure level
- [ ] Configurable masking placeholder text
- [ ] Metrics/logging for compaction events

---

## Appendix A: Research References

1. **NeurIPS 2025 - "The Complexity Trap"** (JetBrains Research)
   - Observation masking outperforms LLM summarization
   - 50% cost reduction on SWE-bench
   - Simple > Complex for tool-heavy workflows

2. **AgentFold (AI2, 2025)**
   - Context folding for long-horizon tasks
   - 92% context reduction over 100+ turns
   - Agent-controlled summarization points

3. **Late Chunking (Anthropic, 2025)**
   - Superior retrieval via contextual embedding
   - 8% improvement in Recall@5

4. **Claude Sonnet 4.5 Capabilities**
   - 200K standard context
   - Built-in context awareness (tracks token budget)
   - 64K output tokens max

---

## Appendix B: Alternative Approaches Considered

### B.1 LLM-based Summarization
**Rejected:** Research shows observation masking is simpler and performs equally well or better.

### B.2 Sliding Window (drop oldest)
**Rejected:** Loses too much context. Masking preserves message structure while reducing tokens.

### B.3 External Memory Store
**Deferred:** Good for multi-session continuity, but adds complexity. Can be added later.

### B.4 Context Folding
**Deferred:** Excellent for very long tasks (100+ turns), but requires more complex agent integration. Can be Phase 2.

---

## Appendix C: File Change Summary

| File | Action | Lines Changed |
|------|--------|---------------|
| `.env` | Modify | 5 lines |
| `.env.example` | Modify | 10 lines |
| `src/memory/token_monitor.py` | Create | ~150 lines |
| `src/memory/working_memory.py` | Modify | ~80 lines |
| `src/memory/memory_manager.py` | Modify | ~60 lines |
| `src/memory/__init__.py` | Modify | 2 lines |
| `src/core/agent.py` | Modify | ~15 lines |
| `tests/test_token_monitor.py` | Create | ~100 lines |
| `tests/test_observation_masking.py` | Create | ~80 lines |
| `tests/test_context_management_integration.py` | Create | ~60 lines |
| **Total** | | **~560 lines** |
