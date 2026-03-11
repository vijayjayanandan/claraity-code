"""Subagent session registry for UI wiring."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


@dataclass
class SubAgentSessionInfo:
    """Public session info for a subagent, used by delegation tool and UI."""

    subagent_id: str
    store: Any  # MessageStore instance
    transcript_path: Path | None = None
