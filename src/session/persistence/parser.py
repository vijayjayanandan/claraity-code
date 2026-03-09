"""JSONL file parser for session replay.

Features:
- Streaming: Uses iterator pattern, no readlines()
- Tolerant: Skips unknown types, handles truncated last line
- Seq assignment: Line number becomes seq during replay

The parser produces data for the Memory Store (projection), not a 1:1
mirror of the JSONL file. Assistant messages with same stream_id will
be collapsed by the store.

v2.1: Uses unified Message class with OpenAI-anchored format.
"""

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Optional, Union

from src.observability import get_logger

from ..models.message import FileHistorySnapshot, Message
from ..store.memory_store import MessageStore

logger = get_logger("session.persistence.parser")

# Valid roles for messages
VALID_ROLES = {"system", "user", "assistant", "tool"}

# Security: Maximum allowed line size (10 MB) to prevent DoS via huge JSON
MAX_LINE_SIZE = 10 * 1024 * 1024  # 10 MB


class ParseError(Exception):
    """Error during JSONL parsing."""

    def __init__(self, line_number: int, message: str, raw_line: str = ""):
        self.line_number = line_number
        self.raw_line = raw_line
        super().__init__(f"Line {line_number}: {message}")


def parse_line(line: str, line_number: int) -> Message | FileHistorySnapshot | None:
    """
    Parse a single JSONL line into the appropriate model.

    Tolerant parsing:
    - Unknown types/roles: return None (skip, don't raise)
    - Unknown fields: ignored by from_dict

    Args:
        line: Raw JSON line
        line_number: Line number (used as seq for messages)

    Returns:
        Parsed message/snapshot, or None for unknown types

    Raises:
        ParseError: Only for malformed JSON, missing required fields, or line too large
    """
    # Security: Check line size to prevent DoS via huge JSON
    if len(line) > MAX_LINE_SIZE:
        raise ParseError(
            line_number,
            f"Line exceeds maximum size ({len(line)} > {MAX_LINE_SIZE} bytes)",
            line[:100] + "..."  # Truncate for error message
        )

    try:
        data = json.loads(line)
    except json.JSONDecodeError as e:
        raise ParseError(line_number, f"Invalid JSON: {e}", line)

    # Check for file snapshot first (uses 'type' field)
    if data.get("type") == "file_snapshot":
        try:
            return FileHistorySnapshot.from_dict(data)
        except Exception as e:
            raise ParseError(line_number, f"FileHistorySnapshot parse error: {e}", line)

    # Regular message uses 'role' field
    role = data.get("role")
    if not role:
        raise ParseError(line_number, "Missing 'role' field", line)

    # Tolerant: unknown roles are skipped
    if role not in VALID_ROLES:
        logger.warning(f"Line {line_number}: Unknown role '{role}', skipping")
        return None

    try:
        # Pass line_number as seq for ordering
        return Message.from_dict(data, seq=line_number)
    except KeyError as e:
        raise ParseError(line_number, f"Missing required field: {e}", line)
    except Exception as e:
        raise ParseError(line_number, f"Parse error: {e}", line)


def parse_file_iter(
    file_path: str | Path,
    tolerant_last_line: bool = True
) -> Iterator[tuple[int, Message | FileHistorySnapshot]]:
    """
    Parse JSONL file lazily using streaming (no readlines()).

    Uses look-ahead pattern to detect last line for tolerant handling.

    Args:
        file_path: Path to JSONL file
        tolerant_last_line: If True, skip corrupted last line (crash recovery)

    Yields:
        tuple of (line_number, parsed message or snapshot)
        Skips None results from unknown types
    """
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"Session file not found: {path}")

    with open(path, encoding='utf-8') as f:
        prev_line: str | None = None
        prev_line_number: int = 0

        for line_number, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue

            # Process previous line (now we know it's not last)
            if prev_line is not None:
                try:
                    item = parse_line(prev_line, prev_line_number)
                    if item is not None:  # Skip None (unknown types)
                        yield (prev_line_number, item)
                except ParseError:
                    # Re-raise errors for non-last lines
                    raise

            prev_line = line
            prev_line_number = line_number

        # Handle last line with tolerance
        if prev_line is not None:
            try:
                item = parse_line(prev_line, prev_line_number)
                if item is not None:
                    yield (prev_line_number, item)
            except ParseError as e:
                if tolerant_last_line:
                    logger.warning(f"Truncated/invalid last line {prev_line_number}, skipping: {e}")
                else:
                    raise


def load_session(
    file_path: str | Path,
    store: MessageStore | None = None,
    on_progress: Callable[[int, int], None] | None = None
) -> MessageStore:
    """
    Load a complete session from JSONL file into memory store.

    The store is a PROJECTION:
    - Assistant messages are collapsed by stream_id (latest wins)
    - Messages are ordered by seq (line_number)
    - Indexes are built for fast lookups

    Projection ordering may differ from ledger (JSONL) ordering due to collapse.

    Args:
        file_path: Path to JSONL file
        store: Existing store to populate (creates new if None)
        on_progress: Optional callback(current, total) for progress updates

    Returns:
        Populated MessageStore
    """
    path = Path(file_path)
    store = store or MessageStore()

    # Count lines for progress (separate pass, but streaming)
    total_lines = 0
    if on_progress:
        with open(path, encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    total_lines += 1

    store.begin_bulk_load()

    try:
        current = 0
        for _line_number, item in parse_file_iter(path):
            if isinstance(item, FileHistorySnapshot):
                store.add_snapshot(item)
            else:
                # Message - add to store (handles collapse internally)
                store.add_message(item)

            current += 1
            if on_progress and total_lines:
                on_progress(current, total_lines)
    finally:
        store.end_bulk_load()

    return store


def validate_session_file(file_path: str | Path) -> tuple[bool, list[str]]:
    """
    Validate a JSONL session file without loading into memory.

    Uses strict mode (no tolerant last line).

    Returns:
        tuple of (is_valid, list of error messages)
    """
    errors: list[str] = []
    path = Path(file_path)

    if not path.exists():
        return False, [f"File not found: {path}"]

    try:
        for _line_number, _ in parse_file_iter(path, tolerant_last_line=False):
            pass  # Just iterate to check for errors
    except ParseError as e:
        errors.append(str(e))
    except Exception as e:
        errors.append(f"File read error: {e}")

    return len(errors) == 0, errors


def get_session_info(file_path: str | Path) -> dict | None:
    """
    Get basic session info from the first few lines without full load.

    Returns:
        Dict with session_id, first_timestamp, message_count (estimated)
        or None if file is invalid
    """
    path = Path(file_path)

    if not path.exists():
        return None

    session_id = None
    first_timestamp = None
    line_count = 0

    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                line_count += 1

                # Only parse first line for session info
                if line_count == 1:
                    try:
                        data = json.loads(line)
                        # v2.1: session_id is in meta
                        meta = data.get("meta", {})
                        session_id = meta.get("session_id")
                        first_timestamp = meta.get("timestamp")
                    except json.JSONDecodeError:
                        pass

        return {
            "session_id": session_id,
            "first_timestamp": first_timestamp,
            "line_count": line_count
        }
    except Exception:
        return None
