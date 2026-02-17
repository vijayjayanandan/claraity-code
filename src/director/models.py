"""
Data models for the Director Protocol.

Pure data structures with no codebase dependencies.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Dict, List, Optional


class DirectorPhase(Enum):
    """States in the Director Protocol state machine."""
    IDLE = auto()
    UNDERSTAND = auto()
    PLAN = auto()
    AWAITING_APPROVAL = auto()
    EXECUTE = auto()
    INTEGRATE = auto()
    COMPLETE = auto()
    FAILED = auto()


class SliceStatus(Enum):
    """Status of an individual vertical slice."""
    PENDING = auto()
    IN_PROGRESS = auto()
    COMPLETED = auto()
    FAILED = auto()


@dataclass
class FileMapping:
    """A file identified during the UNDERSTAND phase."""
    path: str
    role: str
    description: str
    patterns: List[str] = field(default_factory=list)


@dataclass
class ContextDocument:
    """Output of the UNDERSTAND phase."""
    task_description: str
    affected_files: List[FileMapping] = field(default_factory=list)
    existing_patterns: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    created_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for persistence/display."""
        return {
            "task_description": self.task_description,
            "affected_files": [
                {
                    "path": f.path,
                    "role": f.role,
                    "description": f.description,
                    "patterns": f.patterns,
                }
                for f in self.affected_files
            ],
            "existing_patterns": self.existing_patterns,
            "dependencies": self.dependencies,
            "constraints": self.constraints,
            "risks": self.risks,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


@dataclass
class VerticalSlice:
    """A thin, independently testable increment of functionality."""
    id: int
    title: str
    description: str = ""
    files_to_create: List[str] = field(default_factory=list)
    files_to_modify: List[str] = field(default_factory=list)
    test_criteria: List[str] = field(default_factory=list)
    depends_on: List[int] = field(default_factory=list)
    status: SliceStatus = SliceStatus.PENDING

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for persistence/display."""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "files_to_create": self.files_to_create,
            "files_to_modify": self.files_to_modify,
            "test_criteria": self.test_criteria,
            "depends_on": self.depends_on,
            "status": self.status.name,
        }


@dataclass
class DirectorPlan:
    """Output of the PLAN phase."""
    slices: List[VerticalSlice] = field(default_factory=list)
    context: Optional[ContextDocument] = None
    summary: str = ""
    plan_document: str = ""  # Path to rich markdown plan file
    created_at: Optional[datetime] = None

    @property
    def total_slices(self) -> int:
        return len(self.slices)

    @property
    def completed_slices(self) -> int:
        return sum(1 for s in self.slices if s.status == SliceStatus.COMPLETED)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for persistence/display."""
        return {
            "summary": self.summary,
            "slices": [s.to_dict() for s in self.slices],
            "context": self.context.to_dict() if self.context else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


@dataclass
class PhaseResult:
    """Result from executing a phase."""
    phase: DirectorPhase
    success: bool
    output: Any = None
    error: Optional[str] = None
    duration_seconds: float = 0.0
