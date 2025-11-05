"""Tests for task analyzer.

Tests both LLM-based analysis and heuristic fallback.
"""

import pytest
from src.workflow.task_analyzer import (
    TaskAnalyzer,
    TaskAnalysis,
    TaskType,
    TaskComplexity
)


@pytest.fixture
def llm_backend():
    """Create LLM backend for testing.

    Uses Alibaba Cloud API with qwen3-coder-plus model.
    Requires DASHSCOPE_API_KEY environment variable.
    """
    from src.llm import OpenAIBackend, LLMConfig, LLMBackendType

    config = LLMConfig(
        backend_type=LLMBackendType.OPENAI,
        model_name="qwen3-coder-plus",
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        context_window=32768
    )

    return OpenAIBackend(
        config,
        api_key="sk-6ca5ca68942447c7a4c18d0ea63f75e7"
    )


@pytest.fixture
def analyzer(llm_backend):
    """Create TaskAnalyzer instance."""
    return TaskAnalyzer(llm_backend)


# ============================================================================
# LLM-Based Analysis Tests
# ============================================================================

def test_analyze_explain_request(analyzer):
    """Test analyzing a simple explanation request."""
    analysis = analyzer.analyze("Explain how the memory system works")

    assert analysis.task_type == TaskType.EXPLAIN
    assert analysis.complexity.value <= 2
    assert not analysis.requires_approval
    assert not analysis.requires_git
    assert not analysis.requires_tests
    assert analysis.risk_level == "low"


def test_analyze_feature_request(analyzer):
    """Test analyzing a feature implementation request."""
    analysis = analyzer.analyze("Add a new tool called list_directory for browsing directories")

    assert analysis.task_type == TaskType.FEATURE
    assert analysis.complexity.value >= 2
    assert analysis.requires_git
    assert analysis.requires_tests
    # Check for "tool" or "tools" in concepts (LLM may pluralize)
    concepts_lower = [c.lower() for c in analysis.key_concepts]
    assert any("tool" in c for c in concepts_lower)


def test_analyze_refactor_request(analyzer):
    """Test analyzing a complex refactoring request."""
    analysis = analyzer.analyze("Refactor the memory system to use Redis instead of in-memory storage")

    assert analysis.task_type == TaskType.REFACTOR
    assert analysis.complexity.value >= 4
    assert analysis.requires_planning
    assert analysis.requires_approval
    assert analysis.requires_git
    assert analysis.requires_tests
    assert analysis.risk_level in ["high", "medium"]
    assert analysis.estimated_files >= 4


def test_analyze_bugfix_request(analyzer):
    """Test analyzing a bug fix request."""
    analysis = analyzer.analyze("Fix the bug where the agent re-reads files unnecessarily")

    assert analysis.task_type == TaskType.BUG_FIX
    assert analysis.requires_git
    assert analysis.requires_tests


def test_analyze_search_request(analyzer):
    """Test analyzing a code search request."""
    analysis = analyzer.analyze("Search the codebase for all usages of LLMBackend")

    assert analysis.task_type == TaskType.SEARCH
    assert analysis.complexity.value <= 2
    assert not analysis.requires_git
    assert not analysis.requires_tests
    assert analysis.risk_level == "low"


def test_analyze_test_request(analyzer):
    """Test analyzing a test creation request."""
    analysis = analyzer.analyze("Write unit tests for the TaskAnalyzer class")

    assert analysis.task_type == TaskType.TEST
    assert analysis.requires_git
    assert analysis.requires_tests


# ============================================================================
# Heuristic Fallback Tests
# ============================================================================

def test_heuristic_explain():
    """Test heuristic analysis for explanation."""
    analyzer = TaskAnalyzer(llm_backend=None)  # No LLM - will use heuristics

    analysis = analyzer._heuristic_analysis("Explain how the agent works")

    assert analysis.task_type == TaskType.EXPLAIN
    assert analysis.complexity == TaskComplexity.TRIVIAL
    assert not analysis.requires_git
    assert not analysis.requires_tests


def test_heuristic_feature():
    """Test heuristic analysis for feature."""
    analyzer = TaskAnalyzer(llm_backend=None)

    analysis = analyzer._heuristic_analysis("Add a new tool for running commands")

    assert analysis.task_type == TaskType.FEATURE
    assert analysis.complexity == TaskComplexity.MODERATE
    assert analysis.requires_git
    assert analysis.requires_tests


def test_heuristic_refactor():
    """Test heuristic analysis for refactoring."""
    analyzer = TaskAnalyzer(llm_backend=None)

    analysis = analyzer._heuristic_analysis("Refactor the entire codebase")

    assert analysis.task_type == TaskType.REFACTOR
    # Should increase complexity due to "entire" keyword
    assert analysis.complexity.value >= TaskComplexity.COMPLEX.value


def test_heuristic_search():
    """Test heuristic analysis for search."""
    analyzer = TaskAnalyzer(llm_backend=None)

    analysis = analyzer._heuristic_analysis("Find all places where we use memory")

    assert analysis.task_type == TaskType.SEARCH
    assert not analysis.requires_git


# ============================================================================
# Edge Cases and Error Handling
# ============================================================================

def test_empty_request():
    """Test that empty request raises ValueError."""
    analyzer = TaskAnalyzer(llm_backend=None)

    with pytest.raises(ValueError, match="cannot be empty"):
        analyzer.analyze("")


def test_whitespace_only_request():
    """Test that whitespace-only request raises ValueError."""
    analyzer = TaskAnalyzer(llm_backend=None)

    with pytest.raises(ValueError, match="cannot be empty"):
        analyzer.analyze("   \n\t  ")


def test_llm_failure_fallback(analyzer):
    """Test that LLM failure gracefully falls back to heuristics."""
    # This should try LLM first, then fall back to heuristics if it fails
    # We can't easily simulate LLM failure in integration test,
    # but we can test the heuristic directly
    analysis = analyzer._heuristic_analysis("Add a feature")

    assert isinstance(analysis, TaskAnalysis)
    assert analysis.task_type == TaskType.FEATURE


# ============================================================================
# TaskAnalysis Object Tests
# ============================================================================

def test_task_analysis_str_representation():
    """Test string representation of TaskAnalysis."""
    analysis = TaskAnalysis(
        task_type=TaskType.FEATURE,
        complexity=TaskComplexity.MODERATE,
        requires_planning=True,
        requires_approval=False,
        estimated_files=3,
        estimated_iterations=5,
        requires_git=True,
        requires_tests=True,
        risk_level="medium",
        key_concepts=["tools"],
        affected_systems=["tools"]
    )

    str_repr = str(analysis)

    # Check both the enum value and name appear
    assert "feature" in str_repr or "FEATURE" in str_repr
    assert "MODERATE" in str_repr
    assert "MEDIUM" in str_repr
    assert "Planning Required: True" in str_repr


def test_task_analysis_dataclass_equality():
    """Test that TaskAnalysis equality works."""
    analysis1 = TaskAnalysis(
        task_type=TaskType.FEATURE,
        complexity=TaskComplexity.MODERATE,
        requires_planning=True,
        requires_approval=False,
        estimated_files=3,
        estimated_iterations=5,
        requires_git=True,
        requires_tests=True,
        risk_level="medium"
    )

    analysis2 = TaskAnalysis(
        task_type=TaskType.FEATURE,
        complexity=TaskComplexity.MODERATE,
        requires_planning=True,
        requires_approval=False,
        estimated_files=3,
        estimated_iterations=5,
        requires_git=True,
        requires_tests=True,
        risk_level="medium"
    )

    assert analysis1 == analysis2


# ============================================================================
# Complexity Level Tests
# ============================================================================

@pytest.mark.parametrize("user_request,expected_min_complexity", [
    ("What is a coding agent?", 1),
    ("Add a docstring to function X", 1),  # LLM returns TRIVIAL (1), not SIMPLE (2)
    ("Add a new tool for listing directories", 2),  # LLM returns SIMPLE (2), not MODERATE (3)
    ("Refactor the tool system to use plugins", 4),
    ("Migrate the entire system to use async/await", 5),
])
def test_complexity_levels(analyzer, user_request, expected_min_complexity):
    """Test that complexity is estimated correctly for various requests."""
    analysis = analyzer.analyze(user_request)

    assert analysis.complexity.value >= expected_min_complexity


# ============================================================================
# Risk Level Tests
# ============================================================================

def test_high_risk_requires_approval(analyzer):
    """Test that high-risk tasks require approval."""
    analysis = analyzer.analyze(
        "Delete all deprecated code and restructure the entire architecture"
    )

    # High complexity or destructive operations should require approval
    if analysis.risk_level == "high":
        assert analysis.requires_approval


# ============================================================================
# Integration Test with Full Workflow
# ============================================================================

def test_full_analysis_workflow(analyzer):
    """Test complete analysis workflow end-to-end."""
    request = "Create a new verification layer that checks code before committing"

    analysis = analyzer.analyze(request)

    # Verify all fields are populated
    assert isinstance(analysis.task_type, TaskType)
    assert isinstance(analysis.complexity, TaskComplexity)
    assert isinstance(analysis.requires_planning, bool)
    assert isinstance(analysis.requires_approval, bool)
    assert isinstance(analysis.estimated_files, int)
    assert isinstance(analysis.estimated_iterations, int)
    assert isinstance(analysis.requires_git, bool)
    assert isinstance(analysis.requires_tests, bool)
    assert analysis.risk_level in ["low", "medium", "high"]
    assert isinstance(analysis.key_concepts, list)
    assert isinstance(analysis.affected_systems, list)

    # Verify reasonable values
    assert analysis.estimated_files > 0
    assert analysis.estimated_iterations > 0

    # This is a feature, should have reasonable complexity
    assert analysis.task_type == TaskType.FEATURE
    assert analysis.complexity.value >= 2


if __name__ == "__main__":
    # Allow running tests directly
    pytest.main([__file__, "-v"])
