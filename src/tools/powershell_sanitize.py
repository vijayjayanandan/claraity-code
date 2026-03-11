"""Sanitize shell commands for PowerShell on Windows.

The LLM sometimes generates cmd.exe or bash syntax despite being told
to use PowerShell.  This module defensively converts common patterns
so commands still execute correctly.
"""

import platform
import re


def sanitize_for_powershell(command: str) -> str:
    """Convert common cmd.exe/bash patterns to PowerShell equivalents.

    Only runs on Windows. Returns command unchanged on other platforms.

    Conversions:
      - '&&' between commands  ->  '; '  (PowerShell statement separator)
      - '2>nul'                ->  '2>$null'
      - '2>&1'  (standalone)   ->  '2>&1'  (actually works in PS, kept as-is)

    Does NOT attempt to convert cmd.exe builtins like 'dir /s' -- those
    are too context-dependent. The system prompt handles that.
    """
    if platform.system() != "Windows":
        return command

    # Replace '&&' with '; ' but NOT inside quoted strings
    # Strategy: split on quotes, only replace in unquoted segments
    # Try ' && ' first (with spaces) for clean output, then bare '&&'
    result = _replace_outside_quotes(command, " && ", "; ")
    result = _replace_outside_quotes(result, "&&", "; ")

    # Replace '2>nul' with '2>$null' (cmd.exe null device)
    result = _replace_outside_quotes(result, "2>nul", "2>$null")
    result = _replace_outside_quotes(result, "2>NUL", "2>$null")

    return result


def _replace_outside_quotes(text: str, old: str, new: str) -> str:
    """Replace `old` with `new` only in unquoted portions of text.

    Respects both single and double quotes. Handles escaped quotes minimally
    (good enough for shell commands, not a full parser).
    """
    parts = []
    i = 0
    length = len(text)

    while i < length:
        # Check for quote start
        if text[i] in ('"', "'"):
            quote_char = text[i]
            # Find the matching close quote
            j = i + 1
            while j < length and text[j] != quote_char:
                if text[j] == "\\" and j + 1 < length:
                    j += 1  # skip escaped char
                j += 1
            if j < length:
                j += 1  # include closing quote
            parts.append(text[i:j])
            i = j
        else:
            # Unquoted segment - find next quote or end
            j = i
            while j < length and text[j] not in ('"', "'"):
                j += 1
            segment = text[i:j]
            parts.append(segment.replace(old, new))
            i = j

    return "".join(parts)
