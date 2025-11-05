"""
Validation Scenario Data Models

Defines the structure for validation test cases, execution results,
and success criteria.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from enum import Enum
from datetime import datetime


class DifficultyLevel(Enum):
    """Test difficulty levels"""
    EASY = "easy"           # 1-2 hours, single component
    MEDIUM = "medium"       # 3-4 hours, multiple components
    HARD = "hard"           # 5-8 hours, full application


class StepType(Enum):
    """Types of validation steps"""
    BASH = "bash"           # Run shell command
    PYTEST = "pytest"       # Run pytest tests
    INSPECT = "inspect"     # Inspect file contents
    API_CALL = "api_call"   # Test API endpoint


@dataclass
class ValidationStep:
    """A single validation check to perform"""

    type: StepType
    description: str

    # For BASH/PYTEST steps
    command: Optional[str] = None
    expected_exit_code: int = 0
    timeout_seconds: int = 60

    # For INSPECT steps
    file_path: Optional[str] = None
    check_criteria: Optional[str] = None  # e.g., "has_error_handling", "has_docstrings"

    # For API_CALL steps
    endpoint: Optional[str] = None
    method: Optional[str] = "GET"
    expected_status: int = 200


@dataclass
class SuccessCriteria:
    """Automated success criteria for validation"""

    # File existence checks
    required_files: List[str] = field(default_factory=list)

    # Test requirements
    tests_must_pass: bool = False
    min_test_count: int = 0

    # Execution requirements
    must_run_without_error: bool = False

    # Dependency requirements
    required_dependencies: List[str] = field(default_factory=list)

    # Documentation requirements
    must_have_readme: bool = False
    must_have_docstrings: bool = False


@dataclass
class ValidationScenario:
    """
    Complete definition of a validation test case.

    Represents a real-world coding task that the agent should complete
    autonomously. Used for end-to-end validation of agent capabilities.
    """

    # Identity
    id: str
    name: str
    difficulty: DifficultyLevel
    estimated_hours: float

    # Task definition
    prompt: str                          # What to ask the agent
    context_files: List[str] = field(default_factory=list)  # Starting files
    initial_setup: Optional[str] = None  # Setup commands (e.g., "mkdir project")

    # Success criteria
    success_criteria: SuccessCriteria = field(default_factory=SuccessCriteria)

    # Validation steps
    validation_steps: List[ValidationStep] = field(default_factory=list)

    # Scoring weights (must sum to 1.0)
    scoring_weights: Dict[str, float] = field(default_factory=lambda: {
        "completeness": 0.30,    # Did it finish all requirements?
        "correctness": 0.30,     # Does the code work?
        "quality": 0.25,         # Code quality (structure, docs, tests)
        "autonomy": 0.15         # How much human intervention needed?
    })

    # Metadata
    tags: List[str] = field(default_factory=list)  # e.g., ["cli", "api", "database"]
    created_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        """Validate scenario definition"""
        # Check scoring weights sum to 1.0
        total_weight = sum(self.scoring_weights.values())
        if not 0.99 <= total_weight <= 1.01:  # Allow small floating point errors
            raise ValueError(
                f"Scoring weights must sum to 1.0, got {total_weight}. "
                f"Weights: {self.scoring_weights}"
            )


@dataclass
class ValidationResult:
    """
    Results from executing a validation scenario.

    Contains detailed metrics, scores, and artifacts from the validation run.
    """

    # Identity
    scenario_id: str
    scenario_name: str
    run_id: str  # Unique ID for this run

    # Overall results
    success: bool
    overall_score: float  # 0.0 - 1.0

    # Detailed scores (0.0 - 1.0)
    scores: Dict[str, float] = field(default_factory=dict)
    # {
    #   "completeness": 0.85,
    #   "correctness": 0.90,
    #   "quality": 0.75,
    #   "autonomy": 0.95
    # }

    # Execution metrics
    duration_seconds: float = 0.0
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None

    # Cost tracking
    tokens_used: int = 0
    estimated_cost_usd: float = 0.0

    # Agent behavior
    tool_calls: Dict[str, int] = field(default_factory=dict)  # {tool_name: count}
    errors_encountered: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    # Code output
    files_created: List[str] = field(default_factory=list)
    lines_of_code: int = 0

    # Test results
    tests_passed: int = 0
    tests_failed: int = 0
    test_output: str = ""

    # Validation checks
    check_results: Dict[str, Any] = field(default_factory=dict)

    # Judge evaluation (from Claude API)
    judge_scores: Dict[str, float] = field(default_factory=dict)
    judge_feedback: str = ""
    strengths: List[str] = field(default_factory=list)
    weaknesses: List[str] = field(default_factory=list)

    # Autonomy metrics
    autonomous_percentage: float = 0.0  # % of time without human input
    human_interventions: int = 0

    # Artifacts
    workspace_path: str = ""
    transcript_path: str = ""
    agent_log_path: str = ""
    judge_report_path: str = ""

    # Failure analysis (if failed)
    failure_reason: Optional[str] = None
    failure_stage: Optional[str] = None  # "setup", "execution", "validation", "judging"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            "scenario_id": self.scenario_id,
            "scenario_name": self.scenario_name,
            "run_id": self.run_id,
            "success": self.success,
            "overall_score": self.overall_score,
            "scores": self.scores,
            "duration_seconds": self.duration_seconds,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "tokens_used": self.tokens_used,
            "estimated_cost_usd": self.estimated_cost_usd,
            "tool_calls": self.tool_calls,
            "errors_encountered": self.errors_encountered,
            "warnings": self.warnings,
            "files_created": self.files_created,
            "lines_of_code": self.lines_of_code,
            "tests_passed": self.tests_passed,
            "tests_failed": self.tests_failed,
            "judge_scores": self.judge_scores,
            "strengths": self.strengths,
            "weaknesses": self.weaknesses,
            "autonomous_percentage": self.autonomous_percentage,
            "human_interventions": self.human_interventions,
            "workspace_path": self.workspace_path,
            "failure_reason": self.failure_reason,
            "failure_stage": self.failure_stage,
        }

    def get_pass_threshold(self) -> float:
        """Get the score threshold for passing (0.70 = 70%)"""
        return 0.70

    def passed(self) -> bool:
        """Check if validation passed"""
        return self.overall_score >= self.get_pass_threshold()


@dataclass
class ValidationReport:
    """Aggregated report across multiple validation runs"""

    generated_at: datetime
    total_scenarios: int
    scenarios_passed: int
    scenarios_failed: int

    results: List[ValidationResult] = field(default_factory=list)

    # Aggregate metrics
    average_score: float = 0.0
    total_duration_seconds: float = 0.0
    total_cost_usd: float = 0.0

    # Key findings
    strengths: List[str] = field(default_factory=list)
    critical_gaps: List[str] = field(default_factory=list)
    recommended_priorities: List[str] = field(default_factory=list)

    def pass_rate(self) -> float:
        """Calculate overall pass rate"""
        if self.total_scenarios == 0:
            return 0.0
        return self.scenarios_passed / self.total_scenarios

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "generated_at": self.generated_at.isoformat(),
            "total_scenarios": self.total_scenarios,
            "scenarios_passed": self.scenarios_passed,
            "scenarios_failed": self.scenarios_failed,
            "pass_rate": self.pass_rate(),
            "average_score": self.average_score,
            "total_duration_seconds": self.total_duration_seconds,
            "total_cost_usd": self.total_cost_usd,
            "results": [r.to_dict() for r in self.results],
            "strengths": self.strengths,
            "critical_gaps": self.critical_gaps,
            "recommended_priorities": self.recommended_priorities,
        }
