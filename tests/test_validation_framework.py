"""
Tests for Validation Framework

Tests the validation framework components without running full validation.
"""

import pytest
from pathlib import Path

from src.validation.scenario import (
    ValidationScenario,
    ValidationResult,
    DifficultyLevel,
    ValidationStep,
    StepType,
    SuccessCriteria
)
from src.validation.scenarios import (
    VALIDATION_SCENARIOS,
    get_scenario_by_id,
    get_scenarios_by_difficulty
)


def test_validation_scenarios_exist():
    """Test that pre-defined scenarios exist"""
    assert len(VALIDATION_SCENARIOS) == 3
    assert VALIDATION_SCENARIOS[0].id == "easy_cli_weather"
    assert VALIDATION_SCENARIOS[1].id == "medium_rest_api"
    assert VALIDATION_SCENARIOS[2].id == "hard_web_scraper"


def test_get_scenario_by_id():
    """Test scenario lookup by ID"""
    scenario = get_scenario_by_id("easy_cli_weather")
    assert scenario.name == "CLI Weather Tool with Caching"
    assert scenario.difficulty == DifficultyLevel.EASY

    with pytest.raises(ValueError):
        get_scenario_by_id("nonexistent")


def test_get_scenarios_by_difficulty():
    """Test filtering by difficulty"""
    easy = get_scenarios_by_difficulty(DifficultyLevel.EASY)
    assert len(easy) == 1
    assert easy[0].id == "easy_cli_weather"

    medium = get_scenarios_by_difficulty(DifficultyLevel.MEDIUM)
    assert len(medium) == 1

    hard = get_scenarios_by_difficulty(DifficultyLevel.HARD)
    assert len(hard) == 1


def test_scenario_validation():
    """Test scenario validates correctly"""

    # Valid scenario
    scenario = ValidationScenario(
        id="test",
        name="Test Scenario",
        difficulty=DifficultyLevel.EASY,
        estimated_hours=1.0,
        prompt="Test prompt",
        scoring_weights={
            "completeness": 0.3,
            "correctness": 0.3,
            "quality": 0.2,
            "autonomy": 0.2
        }
    )

    # Weights sum to 1.0
    assert abs(sum(scenario.scoring_weights.values()) - 1.0) < 0.01

    # Invalid scenario (weights don't sum to 1.0)
    with pytest.raises(ValueError):
        ValidationScenario(
            id="test",
            name="Test Scenario",
            difficulty=DifficultyLevel.EASY,
            estimated_hours=1.0,
            prompt="Test prompt",
            scoring_weights={
                "completeness": 0.5,
                "correctness": 0.3,
            }  # Sums to 0.8, not 1.0
        )


def test_validation_result_pass_fail():
    """Test result pass/fail logic"""

    # Passing result
    result = ValidationResult(
        scenario_id="test",
        scenario_name="Test",
        run_id="123",
        success=True,
        overall_score=0.75
    )
    assert result.passed()
    assert result.overall_score >= result.get_pass_threshold()

    # Failing result
    result.overall_score = 0.65
    assert not result.passed()


def test_validation_result_to_dict():
    """Test result serialization"""

    result = ValidationResult(
        scenario_id="test",
        scenario_name="Test Scenario",
        run_id="abc123",
        success=True,
        overall_score=0.85,
        files_created=["main.py", "test.py"],
        tests_passed=5,
        tests_failed=1
    )

    data = result.to_dict()

    assert data["scenario_id"] == "test"
    assert data["success"] is True
    assert data["overall_score"] == 0.85
    assert len(data["files_created"]) == 2
    assert data["tests_passed"] == 5


def test_success_criteria():
    """Test success criteria model"""

    criteria = SuccessCriteria(
        required_files=["main.py", "test.py"],
        tests_must_pass=True,
        min_test_count=5,
        must_have_readme=True
    )

    assert len(criteria.required_files) == 2
    assert criteria.tests_must_pass is True
    assert criteria.min_test_count == 5
    assert criteria.must_have_readme is True


def test_validation_step():
    """Test validation step model"""

    # Bash step
    step = ValidationStep(
        type=StepType.BASH,
        description="Run tests",
        command="pytest",
        expected_exit_code=0,
        timeout_seconds=60
    )

    assert step.type == StepType.BASH
    assert step.command == "pytest"

    # Inspect step
    step = ValidationStep(
        type=StepType.INSPECT,
        description="Check error handling",
        file_path="main.py",
        check_criteria="has_error_handling"
    )

    assert step.type == StepType.INSPECT
    assert step.file_path == "main.py"


def test_scenario_scoring_weights():
    """Test all scenarios have valid scoring weights"""

    for scenario in VALIDATION_SCENARIOS:
        # Check weights sum to 1.0
        total = sum(scenario.scoring_weights.values())
        assert 0.99 <= total <= 1.01, f"{scenario.id} weights sum to {total}"

        # Check all required weights present
        assert "completeness" in scenario.scoring_weights
        assert "correctness" in scenario.scoring_weights
        assert "quality" in scenario.scoring_weights
        assert "autonomy" in scenario.scoring_weights


def test_scenario_metadata():
    """Test scenario metadata is complete"""

    for scenario in VALIDATION_SCENARIOS:
        # Required fields
        assert scenario.id
        assert scenario.name
        assert scenario.prompt
        assert scenario.difficulty
        assert scenario.estimated_hours > 0

        # Success criteria
        assert len(scenario.success_criteria.required_files) > 0

        # At least one validation step
        # (Not strictly required, but good practice)
        # assert len(scenario.validation_steps) > 0


def test_easy_scenario_details():
    """Test EASY scenario has correct details"""

    scenario = get_scenario_by_id("easy_cli_weather")

    assert scenario.difficulty == DifficultyLevel.EASY
    assert scenario.estimated_hours == 2.0
    assert "cli" in scenario.tags
    assert "weather.py" in scenario.success_criteria.required_files
    assert scenario.success_criteria.tests_must_pass is True
    assert len(scenario.validation_steps) >= 2


def test_medium_scenario_details():
    """Test MEDIUM scenario has correct details"""

    scenario = get_scenario_by_id("medium_rest_api")

    assert scenario.difficulty == DifficultyLevel.MEDIUM
    assert scenario.estimated_hours == 4.0
    assert "api" in scenario.tags
    assert "app.py" in scenario.success_criteria.required_files
    assert scenario.success_criteria.min_test_count == 15


def test_hard_scenario_details():
    """Test HARD scenario has correct details"""

    scenario = get_scenario_by_id("hard_web_scraper")

    assert scenario.difficulty == DifficultyLevel.HARD
    assert scenario.estimated_hours == 6.0
    assert "scraping" in scenario.tags
    assert "scraper.py" in scenario.success_criteria.required_files
    assert scenario.success_criteria.min_test_count == 20
