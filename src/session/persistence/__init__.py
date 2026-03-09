"""Session persistence layer for JSONL files.

Parser:
- parse_line(): Parse single JSONL line
- parse_file_iter(): Streaming iterator over JSONL file
- load_session(): Load complete session into MessageStore
- validate_session_file(): Validate JSONL file without loading

Writer:
- SessionWriter: Thread-safe async writer with drain-on-close
- WriteResult: Result of write operations
- create_session_file(): Create new empty session file
- append_to_session(): One-off async append

Key features:
- Streaming: No readlines(), memory efficient
- Tolerant: Skips unknown types, handles truncated last line
- Seq assignment: Line number becomes seq during replay
- Thread-safe: run_coroutine_threadsafe() with captured loop
- Drain-on-close: Waits for pending writes before closing
"""

from .parser import (
    ParseError,
    get_session_info,
    load_session,
    parse_file_iter,
    parse_line,
    validate_session_file,
)
from .writer import (
    SessionWriter,
    WriteResult,
    append_to_session,
    create_session_file,
)

__all__ = [
    # Parser
    "ParseError",
    "parse_line",
    "parse_file_iter",
    "load_session",
    "validate_session_file",
    "get_session_info",
    # Writer
    "WriteResult",
    "SessionWriter",
    "create_session_file",
    "append_to_session",
]
