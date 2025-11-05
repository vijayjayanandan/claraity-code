"""
Blueprint Data Structures for ClarAIty Generate Mode

Represents the architecture plan generated before code execution.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional
from enum import Enum


class ComponentType(Enum):
    """Types of components in the architecture."""
    CLASS = "class"
    FUNCTION = "function"
    MODULE = "module"
    API = "api"
    DATABASE = "database"
    UI = "ui"
    SERVICE = "service"
    COMPONENT = "component"  # React/Vue/Angular components
    HOOK = "hook"            # React hooks
    STORE = "store"          # State management stores
    UTIL = "util"            # Utility modules
    CONFIG = "config"        # Configuration files
    TYPE = "type"            # TypeScript types/interfaces
    TYPES = "types"          # TypeScript types/interfaces (plural)


class FileActionType(Enum):
    """Types of file operations."""
    CREATE = "create"
    MODIFY = "modify"
    DELETE = "delete"


class RelationType(Enum):
    """Types of relationships between components."""
    CALLS = "calls"
    IMPORTS = "imports"
    INHERITS = "inherits"
    USES = "uses"
    DEPENDS_ON = "depends_on"
    RENDERS = "renders"          # Component renders another component
    PROVIDES = "provides"        # Provides context/data
    CONSUMES = "consumes"        # Consumes context/data
    SUBSCRIBES = "subscribes"    # Subscribes to store/events
    MANAGES = "manages"          # Manages state
    ROUTES_TO = "routes_to"      # Routing relationship
    UPDATES = "updates"          # Updates/modifies state or data


@dataclass
class Component:
    """A component in the architecture blueprint."""
    name: str
    type: ComponentType
    purpose: str
    responsibilities: List[str]
    file_path: str
    layer: Optional[str] = None
    key_methods: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)


@dataclass
class DesignDecision:
    """A design decision with rationale."""
    decision: str
    rationale: str
    alternatives_considered: List[str] = field(default_factory=list)
    trade_offs: Optional[str] = None
    category: Optional[str] = None  # e.g., "architecture", "technology", "pattern"


@dataclass
class FileAction:
    """An action to be performed on a file."""
    file_path: str
    action: FileActionType
    description: str
    estimated_lines: Optional[int] = None
    components_affected: List[str] = field(default_factory=list)


@dataclass
class Relationship:
    """A relationship between components."""
    source: str
    target: str
    type: RelationType
    description: Optional[str] = None


@dataclass
class Blueprint:
    """
    Complete architecture blueprint for a code generation task.

    This is the "plan" that gets shown to the user BEFORE any code is generated.
    """
    task_description: str
    components: List[Component] = field(default_factory=list)
    design_decisions: List[DesignDecision] = field(default_factory=list)
    file_actions: List[FileAction] = field(default_factory=list)
    relationships: List[Relationship] = field(default_factory=list)
    estimated_complexity: Optional[str] = None  # e.g., "low", "medium", "high"
    estimated_time: Optional[str] = None  # e.g., "5 minutes", "30 minutes"
    prerequisites: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        """Convert blueprint to dictionary for JSON serialization."""
        return {
            'task_description': self.task_description,
            'components': [
                {
                    'name': c.name,
                    'type': c.type.value,
                    'purpose': c.purpose,
                    'responsibilities': c.responsibilities,
                    'file_path': c.file_path,
                    'layer': c.layer,
                    'key_methods': c.key_methods,
                    'dependencies': c.dependencies,
                }
                for c in self.components
            ],
            'design_decisions': [
                {
                    'decision': d.decision,
                    'rationale': d.rationale,
                    'alternatives_considered': d.alternatives_considered,
                    'trade_offs': d.trade_offs,
                    'category': d.category,
                }
                for d in self.design_decisions
            ],
            'file_actions': [
                {
                    'file_path': f.file_path,
                    'action': f.action.value,
                    'description': f.description,
                    'estimated_lines': f.estimated_lines,
                    'components_affected': f.components_affected,
                }
                for f in self.file_actions
            ],
            'relationships': [
                {
                    'source': r.source,
                    'target': r.target,
                    'type': r.type.value,
                    'description': r.description,
                }
                for r in self.relationships
            ],
            'estimated_complexity': self.estimated_complexity,
            'estimated_time': self.estimated_time,
            'prerequisites': self.prerequisites,
            'risks': self.risks,
        }

    def summary(self) -> str:
        """Generate a text summary of the blueprint."""
        lines = [
            f"Blueprint for: {self.task_description}",
            f"",
            f"Components: {len(self.components)}",
            f"Design Decisions: {len(self.design_decisions)}",
            f"File Actions: {len(self.file_actions)}",
            f"Relationships: {len(self.relationships)}",
            f"",
            f"Complexity: {self.estimated_complexity or 'Unknown'}",
            f"Estimated Time: {self.estimated_time or 'Unknown'}",
        ]

        if self.prerequisites:
            lines.append(f"\nPrerequisites:")
            for prereq in self.prerequisites:
                lines.append(f"  - {prereq}")

        if self.risks:
            lines.append(f"\nRisks:")
            for risk in self.risks:
                lines.append(f"  - {risk}")

        return "\n".join(lines)
