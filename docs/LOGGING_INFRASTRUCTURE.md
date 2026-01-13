# Production-Grade Logging Infrastructure

## Overview

This document describes the production-grade logging infrastructure implemented for the AI Coding Agent. The system provides structured logging, error persistence, and queryable error history while maintaining non-blocking I/O for async safety.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            Application Code                                  │
│                                                                              │
│     logger = get_logger("component")                                         │
│     logger.info("event", key="value")     # Native key=value pattern        │
│     logger.exception("error", category=ErrorCategory.PROVIDER_TIMEOUT)       │
│                                                                              │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     structlog (stdlib backend)                               │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │ Processors: contextvars → log_level → timestamp → callsite →        │    │
│  │             add_context → redact_sensitive → format_exc → JSON      │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                   │                                          │
│                     LoggerFactory(stdlib) → logging.Logger                   │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   │
                                   ▼
                        ┌─────────────────────────┐
                        │     QueueHandler        │
                        │   (non-blocking)        │
                        └──────────┬──────────────┘
                                   │
                                   ▼
                        ┌─────────────────────────┐
                        │    QueueListener        │
                        │  (background thread)    │
                        └──────────┬──────────────┘
                                   │
         ┌─────────────────────────┼─────────────────────────┐
         │                         │                         │
         ▼                         ▼                         ▼
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│ RotatingFileHandler│   │  StreamHandler   │    │SQLiteErrorHandler│
│ (.clarity/logs/   │   │ CLI: stdout      │    │ (errors table)   │
│  app.jsonl)       │   │ TUI: WARN+stderr │    │ Non-recursive    │
└────────┬─────────┘    └──────────────────┘    └────────┬─────────┘
         │                                               │
         ▼                                               ▼
┌──────────────────┐                          ┌──────────────────┐
│   JSONL Files    │                          │  SQLite errors   │
│  (50MB x 5 max)  │                          │ (30 columns)     │
└──────────────────┘                          └──────────────────┘
```

## Key Design Principles

1. **Unified Pipeline**: ALL structlog events flow through stdlib → QueueHandler → handlers
2. **Non-Blocking I/O**: All file/database I/O happens in background threads
3. **Native Key=Value**: Use `logger.error("event", key=value)` not `extra={'event_dict': {}}`
4. **Error Persistence**: Errors stored in SQLite with rich debugging fields
5. **Context Propagation**: contextvars for correlating logs across async boundaries
6. **Crash Safety**: Exception hooks for sys, threading, and asyncio
7. **Signal Handling**: SIGINT/SIGTERM handlers flush logs before exit
8. **Non-Recursive Handler**: SQLite failures go to `sys.__stderr__`, never back through logging
9. **Bounded Queue with Drop Policy**: Queue drops messages when full instead of blocking
10. **Windows Compatibility**: No emojis, explicit UTF-8 encoding
11. **TUI Safe**: TUI mode uses WARN+ to stderr only, preserving terminal UI

## Components

### 1. `logging_config.py` - Core Configuration

**Location**: `src/observability/logging_config.py`

**Responsibilities**:
- Configure structlog with stdlib backend (LoggerFactory + BoundLogger)
- Set up QueueHandler/QueueListener for non-blocking I/O
- Install crash-safe exception hooks (sys, threading, asyncio)
- Provide context binding utilities

**Key Functions**:

```python
from src.observability import configure_logging, bind_context, get_logger

# Configure logging (call once at startup)
configure_logging(mode="cli")  # or "tui"

# Get a structured logger (returns structlog BoundLogger)
logger = get_logger("my_component")

# Bind context for correlation
bind_context(session="abc123", comp="core.agent", op="stream_response")

# Log with native key=value pattern
logger.info("event_name", key="value", another_key=123)
logger.error("provider_timeout",
    category=ErrorCategory.PROVIDER_TIMEOUT,
    model="gpt-4",
    elapsed_ms=60000,
    root_cause_type="ReadTimeout"
)
logger.exception("unexpected_error")  # Includes traceback automatically
```

**Configuration Options**:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `mode` | `"cli"` | `"cli"` for console+file, `"tui"` for WARN+ stderr only |
| `log_level` | `LOG_LEVEL` env or `"INFO"` | Minimum log level |
| `log_dir` | `".clarity/logs"` | Directory for log files |
| `max_bytes` | `52428800` (50MB) | Max size per log file |
| `backup_count` | `5` | Number of rotated files to keep |

**Mode Behavior**:

| Mode | Console | File | SQLite |
|------|---------|------|--------|
| `cli` | stdout @ configured level | Always | Always |
| `tui` | WARN+ to `sys.__stderr__` | Always | Always |

### 2. `error_store.py` - SQLite Error Persistence

**Location**: `src/observability/error_store.py`

**Responsibilities**:
- Persist errors to SQLite for queryable history
- Provide error taxonomy for classification
- Support time-based and category-based queries
- Store timeout debugging fields

**Schema** (31 columns with timeout debugging):

```sql
CREATE TABLE errors (
    -- Core fields
    id TEXT PRIMARY KEY,           -- UUID
    ts TEXT NOT NULL,              -- ISO8601 timestamp
    level TEXT NOT NULL,           -- ERROR, CRITICAL
    category TEXT NOT NULL,        -- Error taxonomy
    error_type TEXT NOT NULL,      -- Exception class name
    message TEXT NOT NULL,
    traceback TEXT,                -- Truncated to 32KB

    -- Context fields
    component TEXT,                -- e.g., core.agent, llm.openai_backend
    operation TEXT,                -- e.g., stream_response, execute_tool
    run_id TEXT,                   -- Process-level ID (set at startup)
    session_id TEXT,
    stream_id TEXT,
    request_id TEXT,

    -- LLM fields
    model TEXT,
    backend TEXT,
    payload_bytes INTEGER,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,

    -- Tool fields
    tool_name TEXT,
    tool_timeout_s REAL,
    tool_args_keys TEXT,           -- JSON list of argument keys
    elapsed_ms REAL,               -- Elapsed time in milliseconds

    -- Timeout debugging fields
    timeout_read_s REAL,           -- httpx read timeout config
    timeout_write_s REAL,          -- httpx write timeout config
    timeout_connect_s REAL,        -- httpx connect timeout config
    timeout_pool_s REAL,           -- httpx pool timeout config
    retry_attempt INTEGER,         -- Current retry attempt
    retry_max INTEGER,             -- Max retry attempts
    root_cause_type TEXT,          -- Root exception in chain
    root_cause_message TEXT,       -- Root exception message

    extra_json TEXT                -- JSON blob for additional context
);

-- Indexes for common queries
CREATE INDEX idx_errors_ts ON errors(ts);
CREATE INDEX idx_errors_session ON errors(session_id);
CREATE INDEX idx_errors_category ON errors(category);
CREATE INDEX idx_errors_component ON errors(component);
CREATE INDEX idx_errors_run ON errors(run_id);
```

**Usage**:

```python
from src.observability import get_error_store, ErrorCategory

store = get_error_store()

# Query errors
errors = store.query(
    session_id="abc123",
    category=ErrorCategory.PROVIDER_TIMEOUT,
    since_minutes=60,
    limit=100
)

# Get error counts by category
counts = store.count_by_category(since_minutes=60)

# Clean up old errors
deleted = store.clear_old(days=30)
```

### 3. `sqlite_error_handler.py` - Custom Logging Handler

**Location**: `src/observability/sqlite_error_handler.py`

**Responsibilities**:
- Intercept ERROR+ log records
- Extract structured fields from structlog `_structlog_event_dict`
- Write to SQLite via internal queue (non-blocking)
- **Non-recursive**: Failures write to `sys.__stderr__`, never back through logging

**Features**:
- Only processes ERROR level and above (or records with exc_info)
- Re-entry guard prevents recursive logging
- Internal queue prevents blocking the QueueListener thread
- Bounded queue (1000 items) prevents memory exhaustion
- Extracts timeout debugging fields from structlog events

**Field Extraction Priority**:
1. `_structlog_event_dict` (native structlog key=value)
2. `event_dict` attribute (legacy pattern, backwards compatible)
3. `exc_info` for exception details

### 4. `log_query.py` - CLI Query Tool

**Location**: `src/observability/log_query.py`

**Usage**:

```bash
# Query by session
python -m src.observability.log_query --session abc123

# Last N minutes
python -m src.observability.log_query --minutes 30

# By category
python -m src.observability.log_query --category provider_timeout

# By component
python -m src.observability.log_query --component llm.openai_backend

# Show error summary
python -m src.observability.log_query --summary

# JSON output
python -m src.observability.log_query --minutes 60 --json

# Verbose (full tracebacks)
python -m src.observability.log_query --minutes 60 --verbose
```

## Error Taxonomy

Controlled vocabulary for error classification:

| Category | Description | Examples |
|----------|-------------|----------|
| `provider_timeout` | LLM API timeouts | WriteTimeout, ReadTimeout, ConnectTimeout |
| `provider_error` | LLM API errors | HTTP 5xx, invalid response, rate limiting |
| `tool_timeout` | Tool execution timeouts | Tool exceeded timeout_s |
| `tool_error` | Tool execution failures | File not found, permission denied |
| `ui_guard_skipped` | UI safety checks skipped | Pause widget not mounted |
| `budget_pause` | Budget limits reached | Max wall time, max tool calls |
| `unexpected` | Uncategorized errors | Anything else |

## Context Variables

Context variables propagate across async boundaries:

| Variable | Description | Scope | Example |
|----------|-------------|-------|---------|
| `run_id` | Process-level identifier | Set once at startup | `"abc12345def6"` |
| `session_id` | User session identifier | Per session | `"abc12345"` |
| `stream_id` | Streaming response ID | Per stream | `"def67890"` |
| `request_id` | Unique request identifier | Per request | `"ghi11111"` |
| `component` | Source component | Per operation | `"core.agent"` |
| `operation` | Current operation | Per operation | `"stream_response"` |

**Usage**:

```python
from src.observability import bind_context, clear_context, new_request_id

# run_id is automatically set at startup by configure_logging()
# You can bind additional context at operation start
bind_context(
    session="abc123",
    stream="def456",
    request=new_request_id(),
    comp="core.agent",
    op="stream_response"
)

# All logs in this context will include these fields (including run_id)
logger.info("processing_started", tool_count=5)

# Clear context when done (run_id is NOT cleared)
clear_context()
```

## Log Output Formats

### JSONL File Format (`.clarity/logs/app.jsonl`)

```json
{"ts": "2026-01-06T00:03:02.498466+00:00", "level": "INFO", "logger": "core.agent", "event": "stream_started", "run_id": "abc12345def6", "session_id": "abc123", "model": "gpt-4", "iteration": 1, "source": {"file": "agent.py", "line": 1800, "function": "stream_response"}}
{"ts": "2026-01-06T00:03:58.123456+00:00", "level": "ERROR", "logger": "llm.openai_backend", "event": "openai_streaming_error", "run_id": "abc12345def6", "category": "provider_timeout", "error_type": "ReadTimeout", "model": "gpt-4", "elapsed_ms": 60000, "timeout_read_s": 60.0, "root_cause_type": "ReadTimeout", "source": {"file": "openai_backend.py", "line": 598}}
```

### Console Format (CLI mode)

```
[INFO] core.agent: stream_started
[ERROR] llm.openai_backend: openai_streaming_error
```

## Crash Safety and Signal Handling

The logging system installs exception hooks and signal handlers for robust shutdown:

**Exception Hooks**:
1. **`sys.excepthook`** - Uncaught exceptions in main thread
2. **`threading.excepthook`** - Uncaught exceptions in threads
3. **`asyncio.loop.set_exception_handler`** - Unhandled Task exceptions
4. **`atexit` handler** - Flush logs on normal exit

**Signal Handlers** (NEW):
5. **`SIGINT`** - Ctrl+C: Flushes logs, then raises KeyboardInterrupt
6. **`SIGTERM`** - kill: Flushes logs, then exits gracefully

**Flush Order**:
1. Stop QueueListener (flushes pending log records to handlers)
2. Close SQLiteErrorHandler (flushes internal queue to database)

**Asyncio Exception Handler** (NEW):

```python
from src.observability import install_asyncio_handler

# Install in TUI on_mount or after creating event loop
loop = asyncio.get_running_loop()
install_asyncio_handler(loop)

# Now unhandled Task exceptions are captured:
# - Logged via structlog
# - Recorded to SQLite error store
```

**Example crash log**:

```json
{
  "ts": "2026-01-06T00:20:00.000000Z",
  "level": "ERROR",
  "logger": "asyncio",
  "event": "task_exception",
  "category": "unexpected",
  "error_type": "RuntimeError",
  "message": "Task exception was never retrieved",
  "task_name": "Task-42",
  "traceback": "Traceback (most recent call last):..."
}
```

## Redaction

Sensitive data is automatically redacted:

**Redacted Keys**:
- `api_key`, `apikey`, `api-key`
- `authorization`, `auth_token`
- `secret`, `password`, `passwd`, `pwd`
- `bearer`

**Redacted Patterns**:
- `sk-*` (OpenAI API keys)
- `Bearer *` tokens
- Long strings (>500 chars) are truncated

**Example**:

```python
# Input
logger.info("api_call", api_key="sk-abc123xyz", prompt="Hello world...")

# Output (redacted)
{"event": "api_call", "api_key": "***REDACTED***", "prompt": "Hello world..."}
```

## Integration Points

### Agent (`src/core/agent.py`)

```python
# At stream start
bind_context(
    session=self.memory.session_id,
    stream=str(uuid.uuid4())[:8],
    request=new_request_id(),
    comp='core.agent',
    op='stream_response',
)

# On provider error - Native key=value pattern
logger.exception(
    "llm_provider_error",
    category=ErrorCategory.PROVIDER_TIMEOUT,
    error_type=error_type,
    model=self.model_name,
    backend=self.backend_name,
    iteration=iteration,
    elapsed_ms=elapsed_ms,
    root_cause_type=root_cause_type,
    root_cause_message=root_cause_message,
)
```

### Tool Executor (`src/tools/base.py`)

```python
# On tool timeout - Native key=value pattern
logger.error(
    "tool_timeout",
    category=ErrorCategory.TOOL_TIMEOUT,
    error_type="TimeoutError",
    tool_name=tool_name,
    tool_timeout_s=timeout_s,
    elapsed_ms=elapsed_ms,
    tool_args_keys=json.dumps(list(kwargs.keys())),
)
```

### OpenAI Backend (`src/llm/openai_backend.py`)

```python
# On streaming error - Native key=value pattern with timeout debugging
logger.exception(
    "openai_streaming_error",
    category=category,
    error_type=error_type,
    model=self.config.model_name,
    backend="openai",
    operation="generate_with_tools_stream",
    timeout_read_s=self.config.timeout,
    timeout_write_s=DEFAULT_WRITE_TIMEOUT,
    timeout_connect_s=DEFAULT_CONNECT_TIMEOUT,
    timeout_pool_s=DEFAULT_POOL_TIMEOUT,
    root_cause_type=root_cause_type,
    root_cause_message=root_cause_message,
)
```

## Bounded Queue with Drop Policy

The logging queue is bounded and uses a drop policy instead of blocking:

- **Queue Size**: 10,000 messages maximum
- **Drop Policy**: When full, new messages are dropped (not blocked)
- **Warning Rate**: Drops are logged to stderr at most every 10 seconds
- **Why**: Prevents log producers from being blocked by slow consumers

This is critical for non-blocking async code where a blocked logger could freeze the event loop.

```python
# When queue is full:
# [WARN] Log queue full, dropped 42 messages (to stderr)
```

## Timeout Debugging

When timeouts occur, the following fields are captured for debugging:

| Field | Description | Source |
|-------|-------------|--------|
| `timeout_read_s` | httpx read timeout configuration | LLMConfig.timeout |
| `timeout_write_s` | httpx write timeout configuration | DEFAULT_WRITE_TIMEOUT (10s) |
| `timeout_connect_s` | httpx connect timeout configuration | DEFAULT_CONNECT_TIMEOUT (10s) |
| `timeout_pool_s` | httpx pool timeout configuration | DEFAULT_POOL_TIMEOUT (10s) |
| `elapsed_ms` | Actual elapsed time before timeout (milliseconds) | Calculated |
| `retry_attempt` | Current retry attempt number | Failure handler |
| `retry_max` | Maximum retry attempts configured | Failure handler |
| `root_cause_type` | Exception class at root of chain | Exception chain walk |
| `root_cause_message` | Message from root exception | Exception chain walk |
| `tool_args_keys` | JSON list of tool argument keys | Tool executor |

**Querying Timeout Errors**:

```sql
-- Find timeout errors with debugging info
SELECT
    ts, error_type, root_cause_type,
    timeout_read_s, elapsed_ms,
    model, backend
FROM errors
WHERE category = 'provider_timeout'
ORDER BY ts DESC
LIMIT 10;
```

## Files

| File | LOC | Purpose |
|------|-----|---------|
| `src/observability/logging_config.py` | ~550 | Core configuration, context binding, crash hooks |
| `src/observability/error_store.py` | ~400 | SQLite error persistence (30 columns) |
| `src/observability/sqlite_error_handler.py` | ~340 | Non-recursive custom logging handler |
| `src/observability/log_query.py` | ~250 | CLI query tool |

## Dependencies

```
structlog>=24.1.0
```

## Quick Reference

```python
# Import
from src.observability import (
    configure_logging,
    bind_context,
    clear_context,
    new_request_id,
    get_logger,
    get_error_store,
    install_asyncio_handler,
    ErrorCategory,
)

# Configure (once at startup)
configure_logging(mode="cli")  # or "tui"

# Get logger (returns structlog BoundLogger)
logger = get_logger("my_component")

# Bind context
bind_context(session="abc", comp="my_component", op="my_operation")

# Log with native key=value pattern
logger.info("event_name", key="value", count=42)
logger.error("error_event",
    category=ErrorCategory.PROVIDER_TIMEOUT,
    error_type="ReadTimeout",
    elapsed_ms=60000,
)
logger.exception("unexpected_error")  # Includes traceback

# Install asyncio handler (in TUI or async code)
import asyncio
loop = asyncio.get_running_loop()
install_asyncio_handler(loop)

# Query errors
store = get_error_store()
errors = store.query(since_minutes=60, category=ErrorCategory.PROVIDER_TIMEOUT)
```

## Querying Errors

### Via Python

```python
from src.observability import get_error_store, ErrorCategory

store = get_error_store()

# Recent errors
recent = store.get_recent(count=10)

# By session
session_errors = store.query(session_id="abc123")

# By category
timeouts = store.query(category=ErrorCategory.PROVIDER_TIMEOUT)

# Time-based
last_hour = store.query(since_minutes=60)

# Combined
errors = store.query(
    session_id="abc123",
    category=ErrorCategory.TOOL_ERROR,
    since_minutes=30,
    limit=50
)

# Summary
counts = store.count_by_category(since_minutes=60)
# {'provider_timeout': 5, 'tool_error': 2, ...}
```

### Via CLI

```bash
# Summary view
python -m src.observability.log_query --summary

# Recent errors with full details
python -m src.observability.log_query --minutes 60 --verbose

# Export to JSON
python -m src.observability.log_query --minutes 60 --json > errors.json
```

### Via SQL (Direct)

```sql
-- Recent errors with timeout debugging
SELECT ts, category, error_type, root_cause_type,
       timeout_read_s, elapsed_ms, model, run_id
FROM errors
ORDER BY ts DESC LIMIT 10;

-- Errors by category
SELECT category, COUNT(*) FROM errors GROUP BY category;

-- Provider timeouts in last hour with debugging info
SELECT ts, error_type, root_cause_type,
       timeout_read_s, timeout_write_s, elapsed_ms, run_id
FROM errors
WHERE category = 'provider_timeout'
AND ts >= datetime('now', '-1 hour');

-- Tool timeouts with args info
SELECT ts, tool_name, tool_timeout_s, elapsed_ms, tool_args_keys
FROM errors
WHERE category = 'tool_timeout';

-- Errors by run_id (find all errors from a specific process run)
SELECT ts, category, error_type, message
FROM errors
WHERE run_id = 'abc12345def6'
ORDER BY ts;
```

## Validation

Run the logging infrastructure test:

```bash
python test_logging_infra.py
```

Expected output:
- Step 1: Logging configured
- Step 2: Info event found in JSONL
- Step 3: Error event found in SQLite
- Step 4: Asyncio exception handler captured task exception
- Step 5: Timeout debugging fields available in schema
