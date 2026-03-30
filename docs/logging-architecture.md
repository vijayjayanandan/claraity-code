# ClarAIty Logging Architecture

**Purpose**: Production-grade observability for AI Coding Agent  
**Status**: Production Ready  
**Last Updated**: 2026-02-12

---

## Quick Start (30 seconds)

```python
from src.observability import configure_logging, get_logger, bind_context

# 1. Configure once at startup
configure_logging(mode="cli")

# 2. Get logger and bind context
logger = get_logger("my_component")
bind_context(session="session-123", component="my_component")

# 3. Log structured events
logger.info("task_started", file_count=5, language="python")
logger.error("task_failed", error="timeout", elapsed_ms=5000)

# 4. Query logs later
from src.observability import query_session_logs
errors = query_session_logs("session-123", level="ERROR")
```

---

## Architecture Overview

### Design Philosophy

**Non-blocking, structured, queryable logging with automatic context propagation.**

```
Application Code
    ↓ (structured events)
structlog Layer (context binding, JSON formatting, redaction)
    ↓ (non-blocking)
QueueHandler (10k capacity, drops when full)
    ↓ (background thread)
QueueListener
    ↓ (parallel writes)
    ├─→ app.jsonl (rotating, human-readable)
    ├─→ logs.db (SQLite, all levels, queryable)
    └─→ metrics.db (SQLite, errors only, categorized)
```

### Key Design Decisions

| Decision | Rationale | Trade-off |
|----------|-----------|-----------|
| **structlog + stdlib** | Structured logging with stdlib compatibility | Learning curve vs flexibility |
| **QueueHandler pattern** | Non-blocking I/O in hot paths | Memory overhead vs performance |
| **SQLite storage** | SQL queries without external DB | Single-node only vs simplicity |
| **ContextVars** | Async-safe context propagation | Python 3.7+ only vs correctness |
| **Dual storage** | JSONL (human) + SQLite (machine) | Disk space vs reliability |

### Storage Strategy

| Store | Purpose | Retention | Query Method | Location |
|-------|---------|-----------|--------------|----------|
| **logs.db** | All log levels | 7 days | SQL (indexed) | `.claraity/logs/logs.db` |
| **metrics.db** | Errors only | 30 days | SQL (categorized) | `.claraity/metrics.db` |
| **app.jsonl** | Human-readable | 50MB (5 files) | grep/jq | `.claraity/logs/app.jsonl` |

---

## Core Components

### 1. logging_config.py
**Location**: `src/observability/logging_config.py`

**What it does**: Main entry point - configures structlog + stdlib integration

**Key APIs**:
- `configure_logging(mode="cli")` - Call once at startup
- `get_logger(name)` - Get structured logger
- `bind_context(**kwargs)` - Set correlation IDs (session, request, component)
- `clear_context()` - Reset context between operations

**Context Variables** (async-safe via ContextVar):
```python
session_id   # Session correlation
request_id   # Request correlation  
component    # Component name
operation    # Operation name
run_id       # Process-level ID
stream_id    # Stream correlation
```

**Deep dive**: Read this file to understand structlog configuration, credential redaction, and QueueHandler setup.

---

### 2. log_store.py
**Location**: `src/observability/log_store.py`

**What it does**: SQLite persistence for all log levels

**Schema**:
```sql
CREATE TABLE logs (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,              -- ISO 8601 timestamp
    level TEXT NOT NULL,           -- DEBUG, INFO, WARNING, ERROR, CRITICAL
    event TEXT NOT NULL,           -- Event name
    session_id TEXT,               -- Correlation
    component TEXT,                -- Component name
    extra_json TEXT,               -- Additional fields as JSON
    -- ... (see file for complete schema)
);
-- Indexes: session_id, level, ts, event, component
```

**Key APIs**:
```python
from src.observability import get_log_store

store = get_log_store()
store.query(session_id="abc", level="ERROR", since_minutes=30)
store.count_by_level(session_id="abc")
store.cleanup_old_logs(days=7)
```

**Deep dive**: Read this file for SQL schema, indexing strategy, and batch insert logic.

---

### 3. error_store.py
**Location**: `src/observability/error_store.py`

**What it does**: Dedicated error tracking with categories

**Schema**:
```sql
CREATE TABLE errors (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    level TEXT NOT NULL,           -- ERROR or CRITICAL
    event TEXT NOT NULL,
    category TEXT,                 -- Error category (see below)
    error_type TEXT,               -- Exception class name
    error_message TEXT,            -- Exception message
    traceback TEXT,                -- Full traceback
    elapsed_ms REAL,               -- Operation duration
    -- ... (see file for complete schema)
);
```

**Error Categories**:
```python
PROVIDER_TIMEOUT   # LLM API timeouts
PROVIDER_ERROR     # LLM API errors (4xx, 5xx)
TOOL_ERROR         # File I/O, command failures
VALIDATION_ERROR   # Invalid parameters
SYSTEM_ERROR       # Unexpected exceptions
UNKNOWN            # Uncategorized
```

**Key APIs**:
```python
from src.observability import get_error_store, ErrorCategory

store = get_error_store()
store.query(session_id="abc", category=ErrorCategory.PROVIDER_TIMEOUT)
store.count_by_category(session_id="abc")
```

**Deep dive**: Read this file for error categorization logic and metrics tracking.

---

### 4. log_query.py
**Location**: `src/observability/log_query.py`

**What it does**: Unified query API + CLI tool

**Key APIs**:
```python
from src.observability import query_session_logs, query_session_errors

# Query logs
logs = query_session_logs(
    session_id="abc123",
    level="ERROR",           # Filter by level
    component="llm_client",  # Filter by component
    minutes=30,              # Last 30 minutes only
    limit=100                # Max results
)

# Query errors with categories
errors = query_session_errors(
    session_id="abc123",
    category=ErrorCategory.PROVIDER_TIMEOUT
)
```

**CLI Usage**:
```bash
# Query by session
python -m src.observability.log_query --session abc123 --level error

# Full-text search
python -m src.observability.log_query --text "timeout" --minutes 60

# JSON output
python -m src.observability.log_query --session abc123 --json
```

**Deep dive**: Read this file for query optimization and JSONL fallback logic.

---

### 5. sqlite_log_handler.py
**Location**: `src/observability/sqlite_log_handler.py`

**What it does**: Custom logging.Handler that writes to SQLite

**How it works**:
1. Receives log records from QueueListener (background thread)
2. Batches records (default: 50 records or 5 seconds)
3. Writes to logs.db via LogStore
4. Separate handler for errors → metrics.db

**Deep dive**: Read this file for batch write optimization and error handling.

---

## Common Usage Patterns

### Pattern 1: Component Initialization
```python
from src.observability import get_logger, bind_context

logger = get_logger(__name__)

class MyComponent:
    def __init__(self, session_id: str):
        bind_context(session=session_id, component="my_component")
        logger.info("component_initialized")
```

### Pattern 2: Structured Event Logging
```python
logger.info(
    "code_generated",
    language="python",
    lines=150,
    functions=5,
    test_coverage=0.85
)
# Stored as: {"event": "code_generated", "language": "python", "lines": 150, ...}
```

### Pattern 3: Error Tracking with Categories
```python
from src.observability import ErrorCategory

try:
    response = call_llm_api(prompt)
except TimeoutError as e:
    logger.error(
        "llm_timeout",
        category=ErrorCategory.PROVIDER_TIMEOUT,
        provider="openai",
        timeout_seconds=30,
        exc_info=True  # Include traceback
    )
```

### Pattern 4: Context Propagation
```python
# Bind once at request start
bind_context(session="session-123", request="req-456")

# All subsequent logs include context automatically
logger.info("step_1_complete")  # Includes session_id, request_id
logger.info("step_2_complete")  # Includes session_id, request_id

# Clear when done
clear_context()
```

### Pattern 5: Querying for Debugging
```python
# Get all errors from last session
errors = query_session_logs("session-123", level="ERROR")
for log in errors:
    print(f"{log.ts} - {log.event}: {log.extra_json}")

# Get provider timeout errors specifically
timeouts = query_session_errors(
    "session-123",
    category=ErrorCategory.PROVIDER_TIMEOUT
)
```

---

## Configuration

### Default Configuration
Located in `.claraity/config.yaml`:

```yaml
logging:
  level: INFO  # Global log level
  
  handlers:
    console:
      enabled: false  # No console spam
    file:
      enabled: true
      path: .claraity/logs/app.jsonl
      max_bytes: 10485760  # 10MB per file
      backup_count: 5
    sqlite:
      enabled: true
      path: .claraity/logs/logs.db
      batch_size: 50
      flush_interval: 5.0
  
  retention:
    logs_db_days: 7      # Keep logs for 7 days
    errors_db_days: 30   # Keep errors for 30 days
```

### Environment Variable Overrides
```bash
export CLARAITY_LOG_LEVEL=DEBUG
export CLARAITY_LOG_DB_PATH=.claraity/logs/logs.db
export CLARAITY_LOG_RETENTION_DAYS=14
```

---

## Threading & Async Safety

### Threading Model
- **Main Thread**: Application code, structlog processing (fast)
- **QueueListener Thread**: Background I/O (SQLite writes, file rotation)
- **Thread Safety**: RLock in LogStore/ErrorStore for concurrent access

### Async Safety
- **ContextVars**: Async-safe context propagation (unlike threading.local)
- **No blocking calls**: QueueHandler never blocks application code
- **Queue full behavior**: Drops logs when queue reaches 10k (logs to stderr)

### Critical Rule
**Never use `threading.local` for context** - use `ContextVar` instead. This ensures context propagates correctly across `await` boundaries.

---

## Performance Characteristics

| Metric | Value | Notes |
|--------|-------|-------|
| **Log call overhead** | ~50μs | Non-blocking queue enqueue |
| **Queue capacity** | 10,000 records | Drops when full (rare) |
| **Batch size** | 50 records | Configurable |
| **Flush interval** | 5 seconds | Configurable |
| **Query performance** | <100ms | For indexed queries (session_id, level) |
| **Disk usage** | ~1MB/day | Typical workload (INFO level) |

### When to Tune
- **High throughput**: Increase queue size, batch size
- **Low latency**: Decrease flush interval
- **Disk space**: Reduce retention, increase log level to WARNING

---

## Troubleshooting

### Logs not appearing in database
1. Check SQLite handler enabled: `config.yaml` → `logging.handlers.sqlite.enabled: true`
2. Verify database path writable: `.claraity/logs/` directory exists
3. Check stderr for "Queue full" messages (increase queue size)

### Context not appearing in logs
1. Call `bind_context()` before logging
2. In async code, bind context in same async context (not in different task)
3. Verify context: `from src.observability.logging_config import session_id; print(session_id.get())`

### Slow queries
1. Use indexed fields: `session_id`, `level`, `ts`, `component`
2. Add time filter: `since_minutes=30`
3. Limit results: `limit=100`
4. For full-text search, use JSONL files instead: `grep "timeout" .claraity/logs/app.jsonl`

### Database growing too large
1. Reduce retention: `store.cleanup_old_logs(days=3)`
2. Vacuum database: `sqlite3 .claraity/logs/logs.db "VACUUM;"`
3. Increase log level: `INFO` → `WARNING`

---

## Deep Dive References

### For LLMs
When you need to understand or modify logging behavior, read these files in order:

1. **`src/observability/logging_config.py`** - Start here for overall architecture
2. **`src/observability/log_store.py`** - Database schema and query logic
3. **`src/observability/error_store.py`** - Error categorization and metrics
4. **`src/observability/sqlite_log_handler.py`** - Handler implementation details
5. **`src/observability/log_query.py`** - Query API and CLI tool

### For Humans
- **Quick reference**: This document
- **API docs**: Docstrings in `src/observability/__init__.py`
- **Examples**: `tests/observability/` directory
- **Configuration**: `.claraity/config.yaml`

---

## Design Rationale

### Why SQLite instead of external DB?
- **Simplicity**: No external dependencies, works out of the box
- **Performance**: Local disk I/O is fast enough for single-agent workload
- **Queryability**: Full SQL support for debugging
- **Trade-off**: Single-node only (acceptable for coding agent use case)

### Why dual storage (JSONL + SQLite)?
- **JSONL**: Human-readable, works when SQLite unavailable, easy grep/jq
- **SQLite**: Fast indexed queries, structured data, retention management
- **Trade-off**: 2x disk space, but provides reliability and flexibility

### Why QueueHandler pattern?
- **Non-blocking**: Application code never waits for I/O
- **Async-safe**: Works correctly with asyncio
- **Backpressure**: Drops logs when overwhelmed (fail-safe)
- **Trade-off**: Possible log loss under extreme load (acceptable for observability)

### Why ContextVars instead of threading.local?
- **Async-safe**: Propagates across `await` boundaries
- **Correct**: Works with asyncio, threading, and multiprocessing
- **Trade-off**: Python 3.7+ only (acceptable for modern codebase)

---

**Document Version**: 2.0 (Condensed)  
**Lines**: ~400 (vs 1374 in v1.0)  
**Maintained By**: ClarAIty Development Team
