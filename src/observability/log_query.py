"""
CLI tool for querying the error store.

Usage:
    # Query by session
    python -m src.observability.log_query --session abc123

    # Last N minutes
    python -m src.observability.log_query --minutes 30

    # By category
    python -m src.observability.log_query --category provider_timeout

    # By component
    python -m src.observability.log_query --component llm.openai_backend

    # Show error counts by category
    python -m src.observability.log_query --summary

    # Combine filters
    python -m src.observability.log_query --minutes 60 --category tool_timeout --limit 50

Engineering Principles:
- No emojis in code (Windows cp1252 compatibility)
- Simple CLI interface
- Human-readable output
"""

import argparse
import json
import sys
from datetime import datetime
from typing import List, Optional

from .error_store import ErrorStore, ErrorRecord, ErrorCategory, get_error_store


def format_error(error: ErrorRecord, verbose: bool = False) -> str:
    """
    Format an error record for display.

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
    lines.append(f"  Message: {error.message[:200]}{'...' if len(error.message) > 200 else ''}")

    # Context
    context_parts = []
    if error.session_id:
        context_parts.append(f"session={error.session_id[:8]}")
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

    # Timing
    if error.elapsed_s:
        lines.append(f"  Elapsed: {error.elapsed_s:.2f}s")

    # Traceback (truncated unless verbose)
    if error.traceback and verbose:
        lines.append(f"  Traceback:")
        for tb_line in error.traceback.split('\n')[:20]:
            lines.append(f"    {tb_line}")
        if error.traceback.count('\n') > 20:
            lines.append("    ... (truncated)")

    return '\n'.join(lines)


def query_errors(
    session_id: Optional[str] = None,
    category: Optional[str] = None,
    component: Optional[str] = None,
    minutes: Optional[int] = None,
    limit: int = 20,
    verbose: bool = False,
) -> List[ErrorRecord]:
    """
    Query errors and display results.

    Args:
        session_id: Filter by session
        category: Filter by category
        component: Filter by component
        minutes: Filter to last N minutes
        limit: Maximum results
        verbose: Show full traceback

    Returns:
        List of ErrorRecord
    """
    store = get_error_store()
    errors = store.query(
        session_id=session_id,
        category=category,
        component=component,
        since_minutes=minutes,
        limit=limit,
    )
    return errors


def show_summary(minutes: Optional[int] = None) -> None:
    """
    Show error summary by category.

    Args:
        minutes: Filter to last N minutes
    """
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


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Query the error store for debugging",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Query last 30 minutes of errors
  python -m src.observability.log_query --minutes 30

  # Query errors for a specific session
  python -m src.observability.log_query --session abc12345

  # Query provider timeouts
  python -m src.observability.log_query --category provider_timeout

  # Show error summary
  python -m src.observability.log_query --summary

  # Verbose output with full tracebacks
  python -m src.observability.log_query --minutes 60 --verbose

Error Categories:
  provider_timeout  - LLM API timeouts (WriteTimeout, ReadTimeout)
  provider_error    - LLM API errors (HTTP 5xx, invalid response)
  tool_timeout      - Tool execution timeouts
  tool_error        - Tool execution failures
  ui_guard_skipped  - UI guard not mounted
  budget_pause      - Budget limits reached
  unexpected        - Uncategorized errors
        """,
    )

    parser.add_argument(
        "--session", "-s",
        help="Filter by session ID (partial match supported)"
    )

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
        help="Filter by error category"
    )

    parser.add_argument(
        "--component",
        help="Filter by component (e.g., llm.openai_backend, core.agent)"
    )

    parser.add_argument(
        "--minutes", "-m",
        type=int,
        help="Filter to last N minutes"
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
        help="Show full tracebacks"
    )

    parser.add_argument(
        "--summary",
        action="store_true",
        help="Show error count summary by category"
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON"
    )

    args = parser.parse_args()

    # Summary mode
    if args.summary:
        show_summary(minutes=args.minutes)
        return

    # Query mode
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

    # JSON output
    if args.json:
        output = [e.to_dict() for e in errors]
        print(json.dumps(output, indent=2, default=str))
        return

    # Human-readable output
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


if __name__ == "__main__":
    main()
