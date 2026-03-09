"""
CLI and programmatic API for querying logs, errors, and JSONL files.

Three query sources with automatic fallback:

    --source logs    (default) Query logs.db - all log levels, SQL-indexed
    --source errors  Query metrics.db errors table - ERROR+ only
    --source jsonl   Scan JSONL files - fallback when SQLite unavailable

Usage:
    # Show last 50 log entries (from logs.db)
    python -m src.observability.log_query --tail 50

    # Query by session
    python -m src.observability.log_query --session abc123

    # Query errors only
    python -m src.observability.log_query --source errors --session abc123

    # Query by level
    python -m src.observability.log_query --level error --minutes 30

    # Full-text search
    python -m src.observability.log_query --text "timeout" --minutes 60

    # JSONL fallback
    python -m src.observability.log_query --source jsonl --session abc123

    # Show summary counts
    python -m src.observability.log_query --summary

    # JSON output for programmatic consumption
    python -m src.observability.log_query --session abc123 --json

    # Error category filter (errors source only)
    python -m src.observability.log_query --source errors --category provider_timeout

Programmatic API:
    from src.observability.log_query import query_session_logs, query_session_errors
    logs = query_session_logs("session-id", level="error", limit=50)
    errors = query_session_errors("session-id")

Engineering Principles:
- No emojis in code (Windows cp1252 compatibility)
- Simple CLI interface with human-readable and JSON output
- Graceful fallback: logs.db -> JSONL scanning
"""

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from .error_store import ErrorCategory, ErrorRecord, ErrorStore, get_error_store
from .log_store import LogRecord, get_log_store

# =============================================================================
# JSONL SCANNER
# =============================================================================

@dataclass
class JsonlEntry:
    """Parsed JSONL log entry."""
    ts: str = ""
    level: str = ""
    event: str = ""
    logger: str | None = None
    session_id: str | None = None
    component: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return self.raw


def scan_jsonl_files(
    log_dir: str = ".clarity/logs",
    session_id: str | None = None,
    level: str | None = None,
    component: str | None = None,
    event: str | None = None,
    text: str | None = None,
    minutes: int | None = None,
    limit: int = 100,
) -> list[JsonlEntry]:
    """
    Scan JSONL log files (app.jsonl + rotated backups).

    Uses a two-pass approach for performance:
    1. Fast string pre-filter (like grep) to skip non-matching lines
    2. JSON parse only on matching lines for detailed filtering

    Reads files: app.jsonl (current), app.jsonl.1 through app.jsonl.5

    Args:
        log_dir: Directory containing JSONL files
        session_id: Filter by session ID (substring match)
        level: Filter by log level (case-insensitive)
        component: Filter by component/logger (substring)
        event: Filter by event name (substring)
        text: Full-text search across entire JSON line
        minutes: Filter to last N minutes
        limit: Maximum results

    Returns:
        list of JsonlEntry, sorted by timestamp descending
    """
    log_path = Path(log_dir)

    # Collect JSONL files (current + rotated)
    files = []
    main_file = log_path / "app.jsonl"
    if main_file.exists():
        files.append(main_file)
    for i in range(1, 6):
        rotated = log_path / f"app.jsonl.{i}"
        if rotated.exists():
            files.append(rotated)

    if not files:
        return []

    results = []
    corrupted_count = 0
    level_filter = level.upper() if level else None
    text_lower = text.lower() if text else None

    # Time cutoff
    cutoff_ts = None
    if minutes:
        cutoff_ts = (
            datetime.utcnow() - timedelta(minutes=minutes)
        ).isoformat() + 'Z'

    for file_path in files:
        try:
            with open(file_path, encoding='utf-8') as f:
                for line in f:
                    if not line.strip():
                        continue

                    # Pass 1: Fast string pre-filter (avoids JSON parse)
                    if session_id and session_id not in line:
                        continue
                    if text_lower and text_lower not in line.lower():
                        continue

                    # Pass 2: JSON parse for structured filtering
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        corrupted_count += 1
                        continue

                    entry_level = data.get('level', '').upper()
                    entry_ts = data.get('timestamp', data.get('ts', ''))
                    entry_event = data.get('event', '')
                    entry_session = data.get('session_id', '')
                    entry_component = data.get(
                        'component', data.get('logger', '')
                    )

                    # Apply structured filters
                    if level_filter and entry_level != level_filter:
                        continue
                    if cutoff_ts and entry_ts < cutoff_ts:
                        continue
                    if session_id and session_id not in (entry_session or ''):
                        continue
                    if component and component not in (entry_component or ''):
                        continue
                    if event and event not in (entry_event or ''):
                        continue

                    results.append(JsonlEntry(
                        ts=entry_ts,
                        level=entry_level,
                        event=entry_event,
                        logger=data.get('logger'),
                        session_id=entry_session or None,
                        component=entry_component or None,
                        raw=data,
                    ))

        except Exception:
            corrupted_count += 1
            continue

    # Sort by timestamp descending, take limit
    results.sort(key=lambda e: e.ts, reverse=True)

    if corrupted_count > 0:
        print(
            f"[WARN] Skipped {corrupted_count} corrupted "
            f"lines/files during JSONL scan"
        )

    return results[:limit]


# =============================================================================
# FORMATTERS
# =============================================================================

def format_log(log: LogRecord, verbose: bool = False) -> str:
    """
    Format a LogRecord for human-readable display.

    Args:
        log: LogRecord to format
        verbose: Include extra_json details

    Returns:
        Formatted string
    """
    lines = []

    # Header
    ts = log.ts[:19].replace('T', ' ') if log.ts else 'Unknown'
    lines.append(f"[{log.level}] {ts} - {log.event}")

    # Logger
    if log.logger:
        lines.append(f"  Logger: {log.logger}")

    # Context
    ctx_parts = []
    if log.session_id:
        ctx_parts.append(f"session={log.session_id[:12]}")
    if log.component:
        ctx_parts.append(f"component={log.component}")
    if log.operation:
        ctx_parts.append(f"op={log.operation}")
    if log.stream_id:
        ctx_parts.append(f"stream={log.stream_id}")
    if log.request_id:
        ctx_parts.append(f"request={log.request_id}")
    if ctx_parts:
        lines.append(f"  Context: {', '.join(ctx_parts)}")

    # Source location
    if log.source_file:
        loc = log.source_file
        if log.source_line:
            loc += f":{log.source_line}"
        if log.source_function:
            loc += f" ({log.source_function})"
        lines.append(f"  Source: {loc}")

    # Extra JSON (verbose only)
    if verbose and log.extra_json:
        try:
            extra = json.loads(log.extra_json)
            for key, value in extra.items():
                val_str = str(value)
                if len(val_str) > 200:
                    val_str = val_str[:200] + '...'
                lines.append(f"  {key}: {val_str}")
        except (json.JSONDecodeError, TypeError):
            lines.append(f"  extra: {log.extra_json[:200]}")

    return '\n'.join(lines)


def format_error(error: ErrorRecord, verbose: bool = False) -> str:
    """
    Format an ErrorRecord for display.

    Args:
        error: ErrorRecord to format
        verbose: Include full traceback

    Returns:
        Formatted string
    """
    lines = []

    # Header with timestamp and level
    ts = error.ts[:19].replace('T', ' ') if error.ts else 'Unknown'
    lines.append(f"[{error.level}] {ts} - {error.category}")

    # Error type and message
    lines.append(f"  Type: {error.error_type}")
    msg = error.message
    if len(msg) > 200:
        msg = msg[:200] + '...'
    lines.append(f"  Message: {msg}")

    # Context
    context_parts = []
    if error.session_id:
        context_parts.append(f"session={error.session_id[:12]}")
    if error.component:
        context_parts.append(f"component={error.component}")
    if error.operation:
        context_parts.append(f"op={error.operation}")
    if context_parts:
        lines.append(f"  Context: {', '.join(context_parts)}")

    # LLM context
    llm_parts = []
    if error.model:
        llm_parts.append(f"model={error.model}")
    if error.backend:
        llm_parts.append(f"backend={error.backend}")
    if error.payload_bytes:
        llm_parts.append(f"payload={error.payload_bytes}B")
    if llm_parts:
        lines.append(f"  LLM: {', '.join(llm_parts)}")

    # Tool context
    if error.tool_name:
        tool_info = f"  Tool: {error.tool_name}"
        if error.tool_timeout_s:
            tool_info += f" (timeout={error.tool_timeout_s}s)"
        lines.append(tool_info)

    # Timing (FIXED: was error.elapsed_s, now error.elapsed_ms)
    if error.elapsed_ms:
        lines.append(f"  Elapsed: {error.elapsed_ms:.0f}ms")

    # Traceback (truncated unless verbose)
    if error.traceback and verbose:
        lines.append("  Traceback:")
        for tb_line in error.traceback.split('\n')[:20]:
            lines.append(f"    {tb_line}")
        if error.traceback.count('\n') > 20:
            lines.append("    ... (truncated)")

    return '\n'.join(lines)


def format_jsonl(entry: JsonlEntry, verbose: bool = False) -> str:
    """
    Format a JsonlEntry for human-readable display.

    Args:
        entry: JsonlEntry to format
        verbose: Include full raw JSON

    Returns:
        Formatted string
    """
    lines = []

    # Header
    ts = entry.ts[:19].replace('T', ' ') if entry.ts else 'Unknown'
    lines.append(f"[{entry.level}] {ts} - {entry.event}")

    # Logger
    if entry.logger:
        lines.append(f"  Logger: {entry.logger}")

    # Context
    ctx_parts = []
    if entry.session_id:
        ctx_parts.append(f"session={entry.session_id[:12]}")
    if entry.component:
        ctx_parts.append(f"component={entry.component}")
    if ctx_parts:
        lines.append(f"  Context: {', '.join(ctx_parts)}")

    # Verbose: show all raw fields
    if verbose:
        skip_keys = {
            'event', 'level', 'logger', 'timestamp', 'ts',
            'session_id', 'component',
        }
        for key, value in entry.raw.items():
            if key in skip_keys:
                continue
            val_str = str(value)
            if len(val_str) > 200:
                val_str = val_str[:200] + '...'
            lines.append(f"  {key}: {val_str}")

    return '\n'.join(lines)


# =============================================================================
# PROGRAMMATIC API
# =============================================================================

def query_session_logs(
    session_id: str,
    level: str | None = None,
    limit: int = 100,
) -> list[LogRecord]:
    """
    Query logs for a specific session from logs.db.

    Falls back to JSONL scanning if logs.db is unavailable.

    Args:
        session_id: Session ID to filter by
        level: Optional level filter (DEBUG, INFO, WARNING, ERROR)
        limit: Maximum results

    Returns:
        list of LogRecord objects
    """
    try:
        store = get_log_store()
        return store.query(session_id=session_id, level=level, limit=limit)
    except Exception:
        # Fallback to JSONL scanning
        entries = scan_jsonl_files(
            session_id=session_id, level=level, limit=limit
        )
        return [_jsonl_to_log_record(e) for e in entries]


def query_session_errors(
    session_id: str,
    category: str | None = None,
    limit: int = 100,
) -> list[ErrorRecord]:
    """
    Query errors for a specific session from metrics.db.

    Args:
        session_id: Session ID to filter by
        category: Optional error category filter
        limit: Maximum results

    Returns:
        list of ErrorRecord objects
    """
    store = get_error_store()
    return store.query(
        session_id=session_id, category=category, limit=limit
    )


def _jsonl_to_log_record(entry: JsonlEntry) -> LogRecord:
    """Convert a JsonlEntry to a LogRecord for consistent API."""
    raw = entry.raw

    # Extract source location
    source = raw.get('source', {})
    source_file = source.get('file') if isinstance(source, dict) else None
    source_line = source.get('line') if isinstance(source, dict) else None
    source_func = source.get('function') if isinstance(source, dict) else None

    # Fallback to flat fields
    if not source_file:
        source_file = raw.get('filename')
    if not source_line:
        source_line = raw.get('lineno')
    if not source_func:
        source_func = raw.get('func_name')

    # Build extra_json from remaining fields
    skip_keys = {
        'event', 'level', 'logger', 'timestamp', 'ts',
        'run_id', 'session_id', 'stream_id', 'request_id',
        'component', 'operation',
        'source', 'filename', 'lineno', 'func_name',
    }
    extras = {k: v for k, v in raw.items() if k not in skip_keys}
    extra_json = json.dumps(extras, default=str) if extras else None

    return LogRecord(
        id=None,
        ts=entry.ts,
        level=entry.level,
        event=entry.event,
        logger=entry.logger,
        run_id=raw.get('run_id'),
        session_id=entry.session_id,
        stream_id=raw.get('stream_id'),
        request_id=raw.get('request_id'),
        component=entry.component,
        operation=raw.get('operation'),
        source_file=source_file,
        source_line=source_line,
        source_function=source_func,
        extra_json=extra_json,
    )


# =============================================================================
# LEGACY QUERY FUNCTIONS (preserved for backward compatibility)
# =============================================================================

def query_errors(
    session_id: str | None = None,
    category: str | None = None,
    component: str | None = None,
    minutes: int | None = None,
    limit: int = 20,
    verbose: bool = False,
) -> list[ErrorRecord]:
    """Query errors from metrics.db."""
    store = get_error_store()
    return store.query(
        session_id=session_id,
        category=category,
        component=component,
        since_minutes=minutes,
        limit=limit,
    )


def show_summary(minutes: int | None = None) -> None:
    """Show error summary by category."""
    store = get_error_store()
    counts = store.count_by_category(since_minutes=minutes)

    if not counts:
        print("No errors found.")
        return

    print("\n[ERROR SUMMARY]")
    if minutes:
        print(f"Time range: Last {minutes} minutes")
    print("-" * 40)

    total = 0
    for category, count in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {category:25s} {count:5d}")
        total += count

    print("-" * 40)
    print(f"  {'TOTAL':25s} {total:5d}")


# =============================================================================
# CLI DISPATCH
# =============================================================================

def _query_logs_db(args) -> None:
    """Query logs.db (all logs)."""
    try:
        store = get_log_store()
    except Exception as e:
        print(f"[WARN] Cannot open logs.db: {e}")
        print("Falling back to JSONL scanner...")
        _query_jsonl(args)
        return

    if args.summary:
        counts = store.count_by_level(since_minutes=args.minutes)
        _show_level_summary(counts, args.minutes)
        return

    logs = store.query(
        session_id=args.session,
        level=args.level,
        component=args.component,
        event=args.event,
        text=args.text,
        since_minutes=args.minutes,
        limit=args.limit,
    )

    if not logs:
        print("No logs found matching criteria.")
        return

    if args.json:
        output = [l.to_dict() for l in logs]
        print(json.dumps(output, indent=2, default=str))
        return

    print(f"\n[LOGS] Found {len(logs)} log(s)")
    if args.minutes:
        print(f"Time range: Last {args.minutes} minutes")
    print("=" * 60)

    for i, log in enumerate(logs, 1):
        if i > 1:
            print("-" * 60)
        print(f"\n#{i}")
        print(format_log(log, verbose=args.verbose))

    print("\n" + "=" * 60)
    print(f"Showing {len(logs)} of {args.limit} max results")


def _query_errors_db(args) -> None:
    """Query metrics.db errors table."""
    if args.summary:
        show_summary(minutes=args.minutes)
        return

    errors = query_errors(
        session_id=args.session,
        category=args.category,
        component=args.component,
        minutes=args.minutes,
        limit=args.limit,
        verbose=args.verbose,
    )

    if not errors:
        print("No errors found matching criteria.")
        return

    if args.json:
        output = [e.to_dict() for e in errors]
        print(json.dumps(output, indent=2, default=str))
        return

    print(f"\n[ERRORS] Found {len(errors)} error(s)")
    if args.minutes:
        print(f"Time range: Last {args.minutes} minutes")
    print("=" * 60)

    for i, error in enumerate(errors, 1):
        if i > 1:
            print("-" * 60)
        print(f"\n#{i}")
        print(format_error(error, verbose=args.verbose))

    print("\n" + "=" * 60)
    print(f"Showing {len(errors)} of {args.limit} max results")


def _query_jsonl(args) -> None:
    """Scan JSONL files."""
    entries = scan_jsonl_files(
        session_id=args.session,
        level=args.level,
        component=args.component,
        event=args.event,
        text=args.text,
        minutes=args.minutes,
        limit=args.limit,
    )

    if not entries:
        print("No log entries found in JSONL files.")
        return

    if args.json:
        output = [e.to_dict() for e in entries]
        print(json.dumps(output, indent=2, default=str))
        return

    print(f"\n[JSONL] Found {len(entries)} entry/entries")
    if args.minutes:
        print(f"Time range: Last {args.minutes} minutes")
    print("=" * 60)

    for i, entry in enumerate(entries, 1):
        if i > 1:
            print("-" * 60)
        print(f"\n#{i}")
        print(format_jsonl(entry, verbose=args.verbose))

    print("\n" + "=" * 60)
    print(f"Showing {len(entries)} of {args.limit} max results")


def _show_level_summary(
    counts: dict[str, int], minutes: int | None = None
) -> None:
    """Show log summary by level."""
    if not counts:
        print("No logs found.")
        return

    print("\n[LOG SUMMARY]")
    if minutes:
        print(f"Time range: Last {minutes} minutes")
    print("-" * 40)

    # Order by severity
    level_order = ['CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG']
    total = 0

    for level in level_order:
        if level in counts:
            print(f"  {level:25s} {counts[level]:5d}")
            total += counts[level]

    # Any remaining levels not in the standard order
    for level, count in sorted(counts.items(), key=lambda x: -x[1]):
        if level not in level_order:
            print(f"  {level:25s} {count:5d}")
            total += count

    print("-" * 40)
    print(f"  {'TOTAL':25s} {total:5d}")


# =============================================================================
# CLI ENTRY POINT
# =============================================================================

def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Query logs, errors, and JSONL files for debugging",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Show last 50 log entries
  python -m src.observability.log_query --tail 50

  # Query logs for a session
  python -m src.observability.log_query --session abc12345

  # Query only errors
  python -m src.observability.log_query --source errors --session abc12345

  # Filter by level
  python -m src.observability.log_query --level error --minutes 30

  # Full-text search
  python -m src.observability.log_query --text "timeout" --minutes 60

  # JSONL fallback (when logs.db unavailable)
  python -m src.observability.log_query --source jsonl --session abc12345

  # Error category filter
  python -m src.observability.log_query --source errors --category provider_timeout

  # Show log level summary
  python -m src.observability.log_query --summary

  # JSON output
  python -m src.observability.log_query --session abc12345 --json --verbose

Sources:
  logs    (default) Query logs.db - all log levels, SQL-indexed
  errors  Query metrics.db errors table - ERROR+ only
  jsonl   Scan JSONL files - fallback

Error Categories (--source errors only):
  provider_timeout  - LLM API timeouts
  provider_error    - LLM API errors (HTTP 5xx, invalid response)
  tool_timeout      - Tool execution timeouts
  tool_error        - Tool execution failures
  ui_guard_skipped  - UI guard not mounted
  budget_pause      - Budget limits reached
  unexpected        - Uncategorized errors
        """,
    )

    # Source selection
    parser.add_argument(
        "--source",
        choices=["logs", "errors", "jsonl"],
        default="logs",
        help="Query source: logs (all levels), errors (ERROR+), jsonl (fallback)"
    )

    # Common filters
    parser.add_argument(
        "--session", "-s",
        help="Filter by session ID"
    )

    parser.add_argument(
        "--level",
        choices=["debug", "info", "warning", "error", "critical"],
        help="Filter by log level"
    )

    parser.add_argument(
        "--component",
        help="Filter by component/logger (substring match)"
    )

    parser.add_argument(
        "--event",
        help="Filter by event name (substring match)"
    )

    parser.add_argument(
        "--text", "-t",
        help="Full-text search in event/message content"
    )

    parser.add_argument(
        "--minutes", "-m",
        type=int,
        help="Filter to last N minutes"
    )

    # Error-source-specific
    parser.add_argument(
        "--category", "-c",
        choices=[
            ErrorCategory.PROVIDER_TIMEOUT,
            ErrorCategory.PROVIDER_ERROR,
            ErrorCategory.TOOL_TIMEOUT,
            ErrorCategory.TOOL_ERROR,
            ErrorCategory.UI_GUARD_SKIPPED,
            ErrorCategory.BUDGET_PAUSE,
            ErrorCategory.UNEXPECTED,
        ],
        help="Error category filter (--source errors only)"
    )

    # Output controls
    parser.add_argument(
        "--tail", "-n",
        type=int,
        help="Show last N entries (alias for --limit)"
    )

    parser.add_argument(
        "--limit", "-l",
        type=int,
        default=20,
        help="Maximum number of results (default: 20)"
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show full details (tracebacks, extra fields)"
    )

    parser.add_argument(
        "--summary",
        action="store_true",
        help="Show count summary by level or category"
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON"
    )

    args = parser.parse_args()

    # --tail is an alias for --limit
    if args.tail:
        args.limit = args.tail

    # Dispatch based on source
    if args.source == "logs":
        _query_logs_db(args)
    elif args.source == "errors":
        _query_errors_db(args)
    elif args.source == "jsonl":
        _query_jsonl(args)


if __name__ == "__main__":
    main()
