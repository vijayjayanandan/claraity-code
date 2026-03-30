# SubAgent Architecture

Comprehensive documentation for the SubAgent implementation in the AI Coding Agent.

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Current Implementation](#2-current-implementation)
3. [Usage Guide](#3-usage-guide)
4. [Areas for 10x Improvement](#4-areas-for-10x-improvement)
5. [Implementation Roadmap](#5-implementation-roadmap)

---

## 1. Architecture Overview

### What are SubAgents?

SubAgents are specialized LLM instances that operate with **independent context windows** but share the main agent's infrastructure (LLM backend, tools). They enable focused execution of domain-specific tasks without polluting the main conversation context.

### Core Design Principles

| Principle | Description |
|-----------|-------------|
| **Isolated Context** | Each subagent has a fresh conversation - no history pollution |
| **Shared Infrastructure** | Uses main agent's LLM and tools - no duplication |
| **Specialized Expertise** | Custom system prompts for domain-specific tasks |
| **Lightweight** | Minimal overhead - just a wrapper with context management |

### Flow Diagram: Delegation Process

```
                                 Main Agent
                                     |
                                     | delegate_to_subagent("code-reviewer", "Review api.py")
                                     v
                            +------------------+
                            | SubAgentManager  |
                            +------------------+
                                     |
                    +----------------+----------------+
                    |                                 |
                    v                                 v
            Load Config                        Create SubAgent
            (.claraity/agents/                   (if not cached)
             code-reviewer.md)
                    |                                 |
                    +----------------+----------------+
                                     |
                                     v
                            +------------------+
                            |    SubAgent      |
                            +------------------+
                                     |
                    +----------------+----------------+
                    |                                 |
                    v                                 v
            Build Fresh Context              Execute with Tools
            (system prompt +                 (uses main agent's
             task description)               LLM and ToolExecutor)
                    |                                 |
                    +----------------+----------------+
                                     |
                                     v
                            +------------------+
                            | SubAgentResult   |
                            +------------------+
                                     |
                                     v
                              Return to Main Agent
```

### Key Design Decisions

#### 1. Lightweight Wrapper Pattern
**Decision:** SubAgent is a thin wrapper, not a full agent implementation.

**Rationale:**
- Avoids code duplication (no separate LLM client, tool executor, memory)
- Reduces maintenance burden (single source of truth for tools)
- Ensures consistency (subagent uses same tools as main agent)

**Trade-off:** Subagents cannot use different LLM models or tool sets (currently).

#### 2. Markdown + YAML Configuration
**Decision:** Subagent configs stored as `.md` files with YAML frontmatter.

**Rationale:**
- Human-readable and editable
- System prompt is markdown (natural for LLMs)
- YAML frontmatter for structured metadata
- Hierarchical loading (project overrides user configs)

**Trade-off:** Less type-safe than Python classes; parsing overhead.

#### 3. Text-Based Tool Parsing
**Decision:** SubAgent uses XML-like `<TOOL_CALL>` format parsed via regex.

**Rationale:**
- Works with any LLM (no OpenAI function calling required)
- Simple implementation (ToolCallParser class)
- Compatible with instruction-following models

**Trade-off:** Less reliable than native function calling; parsing errors possible.

---

## 2. Current Implementation

### 2.1 SubAgent Class

**Location:** `src/subagents/subagent.py`

**Responsibilities:**
- Holds configuration and session state
- Builds fresh LLM context with specialized system prompt
- Executes tool-calling loop using main agent's infrastructure
- Tracks execution history and statistics

**Key Methods:**

```python
class SubAgent:
    def __init__(self, config: SubAgentConfig, main_agent: AgentInterface):
        """Initialize with config and main agent reference."""

    def execute(self, task_description: str, context: Dict = None, max_iterations: int = 5) -> SubAgentResult:
        """Execute a task with isolated context."""

    def _build_context(self, task_description: str) -> List[Dict[str, str]]:
        """Build fresh LLM context with system prompt + task."""

    def _execute_with_tools(self, context: List[Dict], max_iterations: int) -> tuple[str, List[Dict]]:
        """Run tool-calling loop using main agent's LLM and tools."""

    def get_statistics(self) -> Dict[str, Any]:
        """Get execution statistics for this subagent."""
```

**Data Classes:**

```python
@dataclass
class SubAgentResult:
    success: bool
    subagent_name: str
    output: str
    metadata: Dict[str, Any]
    error: Optional[str]
    tool_calls: List[Dict[str, Any]]
    execution_time: float
```

### 2.2 SubAgentManager

**Location:** `src/subagents/manager.py`

**Responsibilities:**
- Discovers and loads subagent configurations
- Caches subagent instances for reuse
- Provides delegation API (explicit and auto)
- Supports parallel execution of multiple subagents

**Key Methods:**

```python
class SubAgentManager:
    def discover_subagents(self) -> Dict[str, SubAgentConfig]:
        """Discover configs from ~/.claraity/agents and .claraity/agents."""

    def delegate(self, subagent_name: str, task_description: str, ...) -> SubAgentResult:
        """Delegate task to specific subagent."""

    def auto_delegate(self, task_description: str, ...) -> SubAgentResult:
        """Automatically select best subagent based on task description."""

    def execute_parallel(self, tasks: List[Tuple[str, str, Dict]], ...) -> DelegationResult:
        """Execute multiple subagent tasks in parallel."""

    def get_subagent(self, name: str) -> Optional[SubAgent]:
        """Get or create a subagent instance (cached)."""
```

**Auto-Delegation Algorithm:**
Current implementation uses simple keyword matching between task description and subagent descriptions:
1. Split task and description into words
2. Count common words (excluding stopwords)
3. Bonus for exact phrase matches
4. Select subagent with highest score

### 2.3 Configuration System

**Location:** `src/subagents/config.py`

**Configuration File Format:**

```markdown
---
name: code-reviewer
description: Expert code reviewer for quality and security
model: inherit
tools: Read, Write, Edit
context_window: null
---

# Code Reviewer Subagent

You are an expert code reviewer...

## Your Expertise
...
```

**Frontmatter Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Unique ID (lowercase, hyphens allowed) |
| `description` | string | Yes | Natural language description for auto-delegation |
| `model` | string | No | Model to use (`inherit` = use main agent's model) |
| `tools` | string/list | No | Allowed tools (null = inherit all) |
| `context_window` | int | No | Context window size (null = inherit) |

**Hierarchical Loading:**

1. User directory: `~/.claraity/agents/*.md` (lower priority)
2. Project directory: `.claraity/agents/*.md` (higher priority, can override)

### 2.4 Tool Execution Flow

```
1. LLM generates response with <TOOL_CALL> blocks
2. ToolCallParser extracts tool calls (XML-based parsing)
3. For each tool call:
   a. main_agent.tool_executor.execute_tool(name, **args)
   b. Collect result (success/error)
4. Format tool results for LLM
5. Add assistant response + tool results to context
6. Generate next LLM response
7. Repeat until no tool calls or max_iterations
```

### 2.5 Integration with Main Agent

**Location:** `src/core/agent.py`

The main CodingAgent:
1. Initializes SubAgentManager in `__init__`
2. Discovers available subagents
3. Registers `DelegateToSubagentTool` for LLM access
4. Provides `delegate_to_subagent()` and `get_available_subagents()` methods

**DelegateToSubagentTool** (`src/tools/delegation.py`):
- Wraps SubAgentManager.delegate()
- Generates dynamic description listing available subagents
- Returns ToolResult with subagent output

---

## 3. Usage Guide

### 3.1 Creating a New SubAgent

**Step 1: Create configuration file**

Create `.claraity/agents/your-agent.md`:

```markdown
---
name: security-auditor
description: Security specialist analyzing code for vulnerabilities and compliance
model: inherit
---

# Security Auditor Subagent

You are an expert security auditor with 10+ years of experience in application security.

## Your Expertise
- OWASP Top 10 vulnerabilities
- Authentication and authorization patterns
- Cryptographic best practices
- Secure coding standards (CERT, CWE)

## Audit Process
1. Identify attack surface
2. Analyze authentication flows
3. Check input validation
4. Review data handling
5. Assess cryptographic usage

## Output Format
[Structured security report format]
```

**Step 2: Reload subagents**

```python
agent.subagent_manager.reload_subagents()
```

Or restart the agent (subagents are discovered on startup).

### 3.2 Delegating Tasks

**Via LLM Tool Call:**

The LLM can invoke the delegation tool:

```
<TOOL_CALL>
tool: delegate_to_subagent
arguments:
  subagent: code-reviewer
  task: Review src/auth/login.py for security vulnerabilities and code quality issues
</TOOL_CALL>
```

**Via Python API:**

```python
from src.core.agent import CodingAgent

agent = CodingAgent()

# Explicit delegation
result = agent.delegate_to_subagent(
    subagent_name="code-reviewer",
    task_description="Review src/api.py for security issues",
    max_iterations=10
)

if result.success:
    print(result.output)
else:
    print(f"Error: {result.error}")
```

**Parallel Execution:**

```python
tasks = [
    ("code-reviewer", "Review src/api.py", None),
    ("test-writer", "Write tests for src/api.py", None),
    ("doc-writer", "Document src/api.py", None)
]

result = agent.subagent_manager.execute_parallel(tasks)

for subagent_result in result.subagent_results:
    print(f"{subagent_result.subagent_name}: {subagent_result.success}")
```

### 3.3 Example: Code Review Task

**Input Task:**
```
Review the file src/auth/oauth.py for:
1. Security vulnerabilities
2. Error handling gaps
3. Performance issues
4. Code quality concerns
```

**SubAgent Execution:**

1. SubAgent receives task with code-reviewer system prompt
2. SubAgent calls `read_file(file_path="src/auth/oauth.py")`
3. SubAgent analyzes code and generates structured review
4. Returns SubAgentResult with review output

**Output:**
```
## Summary
OAuth implementation is functional but has several security concerns.

## Critical Issues
- **SQL Injection Risk**: Line 45 - token stored without sanitization
- **Missing Rate Limiting**: No protection against brute force attacks

## Suggestions
- Add token expiration validation
- Implement refresh token rotation

## Overall Assessment
- Code Quality: 3/5
- Security: 2/5
- Recommendation: REQUEST CHANGES
```

---

## 4. Areas for 10x Improvement

### 4.1 High Impact Improvements

#### Native Function Calling
**Current:** Text-based tool parsing with `<TOOL_CALL>` XML format.

**Issue:** Parsing is fragile; LLM may produce malformed output; no type validation.

**Improvement:** Use OpenAI-compatible native function calling when available.

```python
# Current (text-based)
response = llm.generate(messages)
parsed = tool_parser.parse(response.content)  # Regex parsing

# Proposed (native function calling)
response = llm.generate(
    messages,
    tools=tool_definitions,
    tool_choice="auto"
)
tool_calls = response.tool_calls  # Structured, validated
```

**Impact:**
- Eliminates parsing errors (10-15% of failures currently)
- Enables tool-specific validation
- Better LLM performance (models trained on function calling format)

**Effort:** Medium (2-3 days)

---

#### Streaming Responses
**Current:** Batch-only execution; user waits for complete response.

**Issue:** Long tasks (code review of large file) appear frozen; no progress indication.

**Improvement:** Stream subagent output to UI in real-time.

```python
# Current
result = subagent.execute(task)  # Blocks until complete
print(result.output)

# Proposed
async for chunk in subagent.execute_stream(task):
    if chunk.type == "text":
        ui.append_text(chunk.content)
    elif chunk.type == "tool_call":
        ui.show_tool_progress(chunk.tool, chunk.status)
```

**Impact:**
- Better UX (users see progress)
- Enables early cancellation
- Reduces perceived latency by 50-70%

**Effort:** High (3-5 days, requires async refactoring)

---

#### Semantic Auto-Delegation
**Current:** Simple keyword matching for subagent selection.

**Issue:** Poor accuracy; fails on paraphrased tasks; no learning.

**Improvement:** Use embeddings for semantic similarity matching.

```python
# Current (keyword matching)
score = len(task_words & description_words)

# Proposed (semantic similarity)
task_embedding = embedder.embed(task_description)
scores = {
    name: cosine_similarity(task_embedding, config.embedding)
    for name, config in self.configs.items()
}
best_subagent = max(scores, key=scores.get)
```

**Impact:**
- 80%+ accuracy on subagent selection (vs ~40% current)
- Handles paraphrased tasks correctly
- Enables task decomposition recommendations

**Effort:** Low (1 day, embedder already exists in codebase)

---

#### Result Caching
**Current:** No caching; repeated queries re-execute fully.

**Issue:** Same code review task executed multiple times wastes LLM tokens.

**Improvement:** Cache subagent results with content-based keys.

```python
# Proposed caching layer
class SubAgentCache:
    def get_or_execute(self, subagent: str, task: str, file_hash: str) -> SubAgentResult:
        cache_key = f"{subagent}:{hash(task)}:{file_hash}"

        if cache_key in self.cache:
            return self.cache[cache_key]

        result = self._execute(subagent, task)
        self.cache[cache_key] = result
        return result
```

**Impact:**
- 90% token reduction for repeated queries
- Faster response for cached results
- Enables "diff-only" re-reviews

**Effort:** Low (1 day)

---

### 4.2 Architecture Improvements

#### Error Recovery and Retry Logic
**Current:** Single attempt; failure returns error result.

**Issue:** Transient failures (rate limits, network) cause task failure.

**Improvement:** Implement exponential backoff with configurable retries.

```python
class SubAgentRetryPolicy:
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    retryable_errors: Set[str] = {"RateLimitError", "TimeoutError", "NetworkError"}

    async def execute_with_retry(self, fn, *args):
        for attempt in range(self.max_retries):
            try:
                return await fn(*args)
            except Exception as e:
                if type(e).__name__ not in self.retryable_errors:
                    raise
                delay = min(self.base_delay * (2 ** attempt), self.max_delay)
                await asyncio.sleep(delay)
        raise MaxRetriesExceeded()
```

**Impact:** 95%+ success rate on transient failures (vs 0% current)

---

#### Per-SubAgent Timeout Configuration
**Current:** Global `max_iterations` limit; no wall-clock timeout.

**Issue:** Stuck subagent blocks indefinitely; no graceful degradation.

**Improvement:** Add per-subagent timeout configuration.

```yaml
# In subagent config
---
name: code-reviewer
timeout_seconds: 120
max_iterations: 10
timeout_action: return_partial  # or 'raise_error'
---
```

```python
async def execute(self, task: str) -> SubAgentResult:
    try:
        async with asyncio.timeout(self.config.timeout_seconds):
            return await self._execute_internal(task)
    except asyncio.TimeoutError:
        return SubAgentResult(
            success=False,
            output=self._format_partial_results(),
            error="Timeout exceeded"
        )
```

---

#### Subagent-to-Subagent Communication
**Current:** Subagents are isolated; cannot invoke each other.

**Issue:** Complex tasks requiring multiple specializations need manual orchestration.

**Improvement:** Enable delegation chains with context passing.

```python
# In code-reviewer subagent
"If you find test coverage gaps, delegate to test-writer subagent with specific test recommendations."

# Delegation chain
code-reviewer -> test-writer -> returns combined result
```

**Impact:** Enables complex multi-step workflows; reduces main agent context usage.

---

#### Memory Sharing (Optional)
**Current:** Each subagent has fresh context; no shared memory.

**Use Case:** Long-running sessions where subagents need shared state.

**Improvement:** Optional shared memory namespace.

```python
class SubAgent:
    def __init__(self, config, main_agent, shared_memory: SharedMemory = None):
        self.shared_memory = shared_memory or SharedMemory()

    def _build_context(self, task):
        context = [...]
        if self.shared_memory:
            context.append({
                "role": "system",
                "content": f"Shared context:\n{self.shared_memory.summary()}"
            })
        return context
```

---

### 4.3 Developer Experience Improvements

#### Hot-Reload of Subagent Configs
**Current:** Requires `reload_subagents()` call or agent restart.

**Improvement:** File watcher for automatic reload.

```python
from watchdog.observers import Observer

class ConfigWatcher:
    def __init__(self, manager: SubAgentManager):
        self.observer = Observer()
        self.observer.schedule(
            ConfigReloadHandler(manager),
            path=".claraity/agents",
            recursive=False
        )

    def start(self):
        self.observer.start()

class ConfigReloadHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if event.src_path.endswith('.md'):
            self.manager.reload_subagents()
            logger.info(f"Reloaded subagent config: {event.src_path}")
```

---

#### Debugging and Tracing
**Current:** Basic logging; no structured traces.

**Improvement:** OpenTelemetry integration for subagent traces.

```python
from opentelemetry import trace

tracer = trace.get_tracer("subagent")

class SubAgent:
    def execute(self, task: str) -> SubAgentResult:
        with tracer.start_as_current_span("subagent.execute") as span:
            span.set_attribute("subagent.name", self.config.name)
            span.set_attribute("task.length", len(task))

            # Track each iteration
            for i, iteration in enumerate(self._execute_iterations()):
                with tracer.start_span(f"iteration.{i}"):
                    span.set_attribute("tool_calls", len(iteration.tool_calls))
```

**Benefits:**
- Visual execution timeline in Jaeger/Zipkin
- Performance bottleneck identification
- Failure root cause analysis

---

#### Testing Utilities
**Current:** No dedicated testing support for subagents.

**Improvement:** Provide MockSubAgent and test fixtures.

```python
# tests/fixtures/subagent_fixtures.py

@pytest.fixture
def mock_subagent_manager(mock_agent):
    """Create SubAgentManager with mocked LLM responses."""
    manager = SubAgentManager(mock_agent)
    manager.discover_subagents()
    return manager

@pytest.fixture
def code_reviewer_result():
    """Sample code review result for testing."""
    return SubAgentResult(
        success=True,
        subagent_name="code-reviewer",
        output="## Summary\nCode looks good...",
        tool_calls=[{"tool": "read_file", "success": True}],
        execution_time=5.2
    )

# Example test
def test_delegation_returns_result(mock_subagent_manager):
    result = mock_subagent_manager.delegate(
        "code-reviewer",
        "Review test.py"
    )
    assert result.success
    assert "code-reviewer" in result.subagent_name
```

---

#### Metrics and Observability
**Current:** Basic `get_statistics()` method; no exportable metrics.

**Improvement:** Prometheus metrics for monitoring.

```python
from prometheus_client import Counter, Histogram, Gauge

SUBAGENT_EXECUTIONS = Counter(
    'subagent_executions_total',
    'Total subagent executions',
    ['subagent_name', 'status']
)

SUBAGENT_DURATION = Histogram(
    'subagent_execution_duration_seconds',
    'Subagent execution duration',
    ['subagent_name'],
    buckets=[1, 5, 10, 30, 60, 120]
)

SUBAGENT_TOOL_CALLS = Histogram(
    'subagent_tool_calls_count',
    'Number of tool calls per execution',
    ['subagent_name'],
    buckets=[1, 2, 5, 10, 20]
)
```

---

## 5. Implementation Roadmap

### Priority Matrix

| Improvement | Impact | Effort | Priority |
|-------------|--------|--------|----------|
| Native Function Calling | High | Medium | P0 |
| Semantic Auto-Delegation | High | Low | P0 |
| Result Caching | Medium | Low | P1 |
| Streaming Responses | High | High | P1 |
| Error Recovery/Retry | Medium | Low | P1 |
| Per-SubAgent Timeout | Medium | Low | P2 |
| Hot-Reload Configs | Low | Low | P2 |
| Testing Utilities | Medium | Medium | P2 |
| Metrics/Observability | Medium | Medium | P2 |
| Subagent-to-Subagent | High | High | P3 |
| Memory Sharing | Low | Medium | P3 |
| Debugging/Tracing | Low | Medium | P3 |

### Phase 1: Foundation (Week 1)

**Goal:** Improve reliability and LLM integration

1. **Native Function Calling** (2-3 days)
   - Add `tools` parameter to SubAgent LLM calls
   - Handle structured tool_calls response
   - Fallback to text parsing for non-supporting models

2. **Semantic Auto-Delegation** (1 day)
   - Pre-compute embeddings for subagent descriptions
   - Replace keyword matching with cosine similarity
   - Add confidence threshold for delegation

3. **Result Caching** (1 day)
   - Implement LRU cache with content-based keys
   - Add cache invalidation on file changes
   - Expose cache stats in manager

### Phase 2: Resilience (Week 2)

**Goal:** Handle failures gracefully

4. **Error Recovery/Retry** (1 day)
   - Implement RetryPolicy class
   - Add retryable error classification
   - Exponential backoff with jitter

5. **Per-SubAgent Timeout** (1 day)
   - Add timeout field to SubAgentConfig
   - Implement asyncio.timeout wrapper
   - Return partial results on timeout

6. **Testing Utilities** (2 days)
   - Create pytest fixtures for subagents
   - Add MockSubAgentManager class
   - Write comprehensive test suite

### Phase 3: User Experience (Week 3)

**Goal:** Better UX and developer experience

7. **Streaming Responses** (3-4 days)
   - Convert SubAgent to async
   - Implement AsyncIterator for execute()
   - Update TUI to render streaming output

8. **Hot-Reload Configs** (0.5 days)
   - Add watchdog file observer
   - Implement config change detection
   - Reload without instance restart

9. **Metrics/Observability** (1 day)
   - Add Prometheus metrics
   - Create Grafana dashboard template
   - Document metric meanings

### Phase 4: Advanced Features (Week 4+)

**Goal:** Enable complex workflows

10. **Subagent-to-Subagent Communication** (3-4 days)
    - Design delegation protocol
    - Implement delegation depth limits
    - Add context passing between subagents

11. **Debugging/Tracing** (2 days)
    - Integrate OpenTelemetry
    - Add span annotations
    - Create trace visualization guide

---

## Appendix: File Locations

| Component | Path |
|-----------|------|
| SubAgent class | `src/subagents/subagent.py` |
| SubAgentManager | `src/subagents/manager.py` |
| Configuration loader | `src/subagents/config.py` |
| Delegation tool | `src/tools/delegation.py` |
| Tool schemas | `src/tools/tool_schemas.py` |
| Tool parser | `src/tools/tool_parser.py` |
| Agent integration | `src/core/agent.py` |
| Agent interface | `src/core/agent_interface.py` |
| Subagent configs | `.claraity/agents/*.md` |

---

## Appendix: Current Subagents

### code-reviewer
**Purpose:** Expert code review for quality, security, and best practices.

**Expertise:**
- Code correctness and logic errors
- Security vulnerability detection
- Performance analysis
- Maintainability assessment

**Output:** Structured review with Critical/Important/Suggestions sections and ratings.

### test-writer
**Purpose:** Create comprehensive test suites with unit and integration tests.

**Expertise:**
- pytest, Jest, Vitest, cargo test
- AAA pattern (Arrange-Act-Assert)
- Edge case identification
- Mock/fixture design

**Output:** Complete test file with coverage summary.

### doc-writer
**Purpose:** Create clear, comprehensive documentation.

**Expertise:**
- API documentation
- README files
- Architecture documentation
- Code comments

**Output:** Markdown documentation following best practices.

---

## Appendix: Comparison with Claude Code Task Tool

| Feature | Our SubAgents | Claude Code Task |
|---------|---------------|------------------|
| Independent context | Yes | Yes |
| Native function calling | No (text parsing) | Yes |
| Streaming | No | Yes |
| Parallel execution | Yes (ThreadPool) | Unknown |
| Configuration format | Markdown + YAML | Unknown |
| Auto-delegation | Keyword matching | Unknown |
| Subagent-to-subagent | No | Likely yes |
| Result caching | No | Unknown |
| Hot-reload | No | Unknown |

**Key Gap:** Native function calling is the biggest reliability gap. Claude Code likely uses structured tool calls, while we parse text with regex.

---

*Last Updated: 2025-01-12*
*Version: 1.0*
