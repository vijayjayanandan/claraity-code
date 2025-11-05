"""Task analyzer for classifying and analyzing user requests.

This module provides intelligent task classification using LLM-based analysis
with heuristic fallbacks for robustness.
"""

from enum import Enum
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
import json
import re
import logging

logger = logging.getLogger(__name__)


class TaskType(Enum):
    """Types of development tasks the agent can handle."""

    FEATURE = "feature"           # New feature implementation
    BUG_FIX = "bugfix"           # Fix a bug
    REFACTOR = "refactor"        # Code refactoring
    DOCUMENTATION = "docs"       # Add/update documentation
    REVIEW = "review"            # Code review
    DEBUG = "debug"              # Debug investigation
    EXPLAIN = "explain"          # Code explanation (no changes)
    SEARCH = "search"            # Code search/exploration
    TEST = "test"                # Test creation/execution


class TaskComplexity(Enum):
    """Estimated complexity levels for tasks."""

    TRIVIAL = 1      # Single file, < 5 lines (e.g., "What does X do?")
    SIMPLE = 2       # Single file, < 50 lines (e.g., "Add a docstring")
    MODERATE = 3     # 2-3 files, < 200 lines (e.g., "Add a new tool")
    COMPLEX = 4      # 4+ files, refactoring (e.g., "Refactor module X")
    VERY_COMPLEX = 5 # Architecture changes, many files (e.g., "Migrate to DB")


@dataclass
class TaskAnalysis:
    """Result of analyzing a user request.

    Attributes:
        task_type: Primary type of work to be done
        complexity: Estimated complexity level (1-5)
        requires_planning: Whether explicit planning phase is needed
        requires_approval: Whether user approval is required before execution
        estimated_files: Number of files that will be affected
        estimated_iterations: Number of tool execution loops needed
        requires_git: Whether git operations will be needed
        requires_tests: Whether tests should be written/run
        risk_level: Impact if task goes wrong (low/medium/high)
        key_concepts: Main concepts involved (for RAG retrieval)
        affected_systems: Which systems/modules are affected
    """

    task_type: TaskType
    complexity: TaskComplexity
    requires_planning: bool
    requires_approval: bool
    estimated_files: int
    estimated_iterations: int
    requires_git: bool
    requires_tests: bool
    risk_level: str  # "low", "medium", "high"
    key_concepts: List[str] = field(default_factory=list)
    affected_systems: List[str] = field(default_factory=list)

    def __str__(self) -> str:
        """Human-readable representation of analysis."""
        return (
            f"TaskAnalysis(\n"
            f"  Type: {self.task_type.value}\n"
            f"  Complexity: {self.complexity.value}/5 ({self.complexity.name})\n"
            f"  Risk: {self.risk_level.upper()}\n"
            f"  Planning Required: {self.requires_planning}\n"
            f"  Approval Required: {self.requires_approval}\n"
            f"  Estimated Files: {self.estimated_files}\n"
            f"  Estimated Iterations: {self.estimated_iterations}\n"
            f")"
        )


class TaskAnalyzer:
    """Analyzes user requests to determine task characteristics.

    Uses LLM-based analysis with heuristic fallback for robustness.
    """

    def __init__(self, llm_backend):
        """Initialize task analyzer.

        Args:
            llm_backend: LLM backend for generating analysis
        """
        self.llm = llm_backend
        logger.info("TaskAnalyzer initialized")

    def analyze(
        self,
        user_request: str,
        context: Optional[Dict[str, Any]] = None
    ) -> TaskAnalysis:
        """Analyze user request to determine task characteristics.

        Args:
            user_request: User's request to analyze
            context: Optional conversation context (not currently used)

        Returns:
            TaskAnalysis with task characteristics

        Raises:
            ValueError: If user_request is empty
        """
        if not user_request or not user_request.strip():
            raise ValueError("User request cannot be empty")

        logger.info(f"Analyzing task: {user_request[:100]}...")

        # Try LLM-based analysis first
        try:
            analysis = self._llm_analysis(user_request)
            logger.info(f"LLM analysis successful: {analysis.task_type.value}, complexity {analysis.complexity.value}")
            return analysis
        except Exception as e:
            logger.warning(f"LLM analysis failed ({e}), falling back to heuristics")
            # Fall back to heuristic analysis
            analysis = self._heuristic_analysis(user_request)
            logger.info(f"Heuristic analysis: {analysis.task_type.value}, complexity {analysis.complexity.value}")
            return analysis

    def _llm_analysis(self, request: str) -> TaskAnalysis:
        """Use LLM to analyze the request.

        Args:
            request: User request to analyze

        Returns:
            TaskAnalysis from LLM

        Raises:
            Exception: If LLM analysis fails or returns invalid JSON
        """
        # Build analysis prompt
        analysis_prompt = self._build_analysis_prompt(request)

        # Get LLM response
        response = self.llm.generate(analysis_prompt)

        # Parse response
        return self._parse_analysis(response.content)

    def _build_analysis_prompt(self, request: str) -> List[Dict[str, str]]:
        """Build prompt for task analysis.

        Args:
            request: User request to analyze

        Returns:
            List of messages for LLM
        """
        return [
            {"role": "system", "content": """You are a task analysis expert for a coding agent.
Analyze the user's request and classify it according to the schema below.

Respond ONLY with valid JSON (no markdown, no explanation):
{
  "task_type": "feature|bugfix|refactor|docs|review|debug|explain|search|test",
  "complexity": 1-5,
  "requires_planning": true/false,
  "requires_approval": true/false,
  "estimated_files": number,
  "estimated_iterations": number,
  "requires_git": true/false,
  "requires_tests": true/false,
  "risk_level": "low|medium|high",
  "key_concepts": ["concept1", "concept2"],
  "affected_systems": ["system1", "system2"]
}

Guidelines:
- task_type: Primary type of work (explain=read-only, feature=add new, bugfix=fix existing, etc.)
- complexity: 1=trivial question, 2=simple 1-file change, 3=multi-file feature, 4=refactoring, 5=architecture change
- requires_planning: true if complexity >= 3 (needs step-by-step plan)
- requires_approval: true if risk is high or changes are destructive
- estimated_files: How many files will be read/modified (0 for explanations)
- estimated_iterations: Tool execution loops needed (1-2 for simple, 5-10 for complex)
- requires_git: true if changes should be committed (false for read-only)
- requires_tests: true if feature/bugfix (should write/run tests)
- risk_level: low=safe/reversible, medium=multi-file changes, high=destructive/irreversible
- key_concepts: Main technical concepts (for RAG retrieval)
- affected_systems: Which modules/systems are touched

Examples:

Request: "Explain how the memory system works"
Response: {
  "task_type": "explain",
  "complexity": 1,
  "requires_planning": false,
  "requires_approval": false,
  "estimated_files": 2,
  "estimated_iterations": 2,
  "requires_git": false,
  "requires_tests": false,
  "risk_level": "low",
  "key_concepts": ["memory", "architecture"],
  "affected_systems": []
}

Request: "Add a list_directory tool"
Response: {
  "task_type": "feature",
  "complexity": 3,
  "requires_planning": true,
  "requires_approval": false,
  "estimated_files": 3,
  "estimated_iterations": 5,
  "requires_git": true,
  "requires_tests": true,
  "risk_level": "low",
  "key_concepts": ["tools", "file_operations"],
  "affected_systems": ["tools"]
}

Request: "Refactor the memory system to use Redis instead of in-memory storage"
Response: {
  "task_type": "refactor",
  "complexity": 5,
  "requires_planning": true,
  "requires_approval": true,
  "estimated_files": 8,
  "estimated_iterations": 12,
  "requires_git": true,
  "requires_tests": true,
  "risk_level": "high",
  "key_concepts": ["memory", "redis", "database", "persistence"],
  "affected_systems": ["memory", "storage", "agent", "tests"]
}

Request: "Fix the bug where the agent re-reads files unnecessarily"
Response: {
  "task_type": "bugfix",
  "complexity": 3,
  "requires_planning": true,
  "requires_approval": false,
  "estimated_files": 2,
  "estimated_iterations": 6,
  "requires_git": true,
  "requires_tests": true,
  "risk_level": "medium",
  "key_concepts": ["memory", "caching", "file_operations"],
  "affected_systems": ["agent", "context_builder"]
}

Request: "Search the codebase for all usages of LLMBackend"
Response: {
  "task_type": "search",
  "complexity": 1,
  "requires_planning": false,
  "requires_approval": false,
  "estimated_files": 10,
  "estimated_iterations": 2,
  "requires_git": false,
  "requires_tests": false,
  "risk_level": "low",
  "key_concepts": ["LLMBackend", "search"],
  "affected_systems": []
}"""},
            {"role": "user", "content": f"Analyze this request:\n{request}"}
        ]

    def _parse_analysis(self, response: str) -> TaskAnalysis:
        """Parse LLM response into TaskAnalysis.

        Args:
            response: LLM response containing JSON

        Returns:
            Parsed TaskAnalysis

        Raises:
            ValueError: If response doesn't contain valid JSON
            KeyError: If required fields are missing
        """
        # Extract JSON from response (LLM might include explanation)
        json_match = re.search(r'\{[\s\S]*\}', response)
        if not json_match:
            raise ValueError("No JSON found in LLM response")

        try:
            data = json.loads(json_match.group(0))
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in response: {e}")

        # Validate and construct TaskAnalysis
        try:
            return TaskAnalysis(
                task_type=TaskType(data["task_type"]),
                complexity=TaskComplexity(data["complexity"]),
                requires_planning=bool(data["requires_planning"]),
                requires_approval=bool(data["requires_approval"]),
                estimated_files=int(data["estimated_files"]),
                estimated_iterations=int(data["estimated_iterations"]),
                requires_git=bool(data["requires_git"]),
                requires_tests=bool(data["requires_tests"]),
                risk_level=str(data["risk_level"]),
                key_concepts=list(data.get("key_concepts", [])),
                affected_systems=list(data.get("affected_systems", []))
            )
        except (KeyError, ValueError) as e:
            raise ValueError(f"Invalid analysis data: {e}")

    def _heuristic_analysis(self, request: str) -> TaskAnalysis:
        """Fallback heuristic analysis if LLM fails.

        Uses simple keyword matching to classify the request.

        Args:
            request: User request to analyze

        Returns:
            TaskAnalysis based on heuristics
        """
        request_lower = request.lower()

        # Determine task type and base complexity
        if any(word in request_lower for word in ["explain", "what is", "how does", "why", "describe"]):
            task_type = TaskType.EXPLAIN
            complexity = TaskComplexity.TRIVIAL
            requires_git = False
            requires_tests = False

        elif any(word in request_lower for word in ["search", "find", "look for", "grep", "where"]):
            task_type = TaskType.SEARCH
            complexity = TaskComplexity.SIMPLE
            requires_git = False
            requires_tests = False

        elif any(word in request_lower for word in ["add", "create", "implement", "new", "build"]):
            task_type = TaskType.FEATURE
            complexity = TaskComplexity.MODERATE
            requires_git = True
            requires_tests = True

        elif any(word in request_lower for word in ["fix", "bug", "error", "issue", "broken"]):
            task_type = TaskType.BUG_FIX
            complexity = TaskComplexity.SIMPLE
            requires_git = True
            requires_tests = True

        elif any(word in request_lower for word in ["refactor", "restructure", "reorganize", "migrate"]):
            task_type = TaskType.REFACTOR
            complexity = TaskComplexity.COMPLEX
            requires_git = True
            requires_tests = True

        elif any(word in request_lower for word in ["test", "unittest", "pytest"]):
            task_type = TaskType.TEST
            complexity = TaskComplexity.SIMPLE
            requires_git = True
            requires_tests = True

        elif any(word in request_lower for word in ["document", "docstring", "comment", "readme"]):
            task_type = TaskType.DOCUMENTATION
            complexity = TaskComplexity.SIMPLE
            requires_git = True
            requires_tests = False

        elif any(word in request_lower for word in ["review", "check", "analyze code"]):
            task_type = TaskType.REVIEW
            complexity = TaskComplexity.SIMPLE
            requires_git = False
            requires_tests = False

        elif any(word in request_lower for word in ["debug", "investigate", "trace"]):
            task_type = TaskType.DEBUG
            complexity = TaskComplexity.MODERATE
            requires_git = False
            requires_tests = False

        else:
            # Default to feature
            task_type = TaskType.FEATURE
            complexity = TaskComplexity.MODERATE
            requires_git = True
            requires_tests = True

        # Adjust complexity based on keywords
        if any(word in request_lower for word in ["entire", "all", "whole", "every"]):
            complexity = TaskComplexity(min(complexity.value + 1, 5))

        if any(word in request_lower for word in ["simple", "quick", "just", "only"]):
            complexity = TaskComplexity(max(complexity.value - 1, 1))

        # Determine risk level
        if complexity.value >= 4:
            risk_level = "high"
        elif complexity.value >= 3:
            risk_level = "medium"
        else:
            risk_level = "low"

        # Estimate files and iterations
        estimated_files = complexity.value
        estimated_iterations = complexity.value * 2

        return TaskAnalysis(
            task_type=task_type,
            complexity=complexity,
            requires_planning=complexity.value >= 3,
            requires_approval=risk_level == "high",
            estimated_files=estimated_files,
            estimated_iterations=estimated_iterations,
            requires_git=requires_git,
            requires_tests=requires_tests,
            risk_level=risk_level,
            key_concepts=[],  # Can't infer from heuristics
            affected_systems=[]  # Can't infer from heuristics
        )
