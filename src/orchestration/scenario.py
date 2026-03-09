"""
Autonomous Test Scenario Models

Defines scenarios where a Testing LLM autonomously interacts with
the Coding Agent to validate behavior through realistic conversations.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class ValidationCheck:
    """
    Single validation check within a scenario.

    Represents one expectation being validated against reality.
    """
    expectation: str  # What we expected (e.g., "agent should ask clarifying questions")
    passed: bool  # Whether this check passed
    evidence: str  # Evidence collected (what actually happened)
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "expectation": self.expectation,
            "passed": self.passed,
            "evidence": self.evidence,
            "timestamp": self.timestamp.isoformat()
        }


@dataclass
class TurnResult:
    """
    Result from one conversation turn.

    Captures what the Testing Agent sent, what the Coding Agent responded,
    and the Testing Agent's assessment of that response.
    """
    turn_number: int
    user_message: str  # What Testing Agent said
    agent_response: str  # What Coding Agent responded
    files_generated: list[str]  # Files created this turn
    tools_called: list[str]  # Tools executed this turn
    assessment: str  # Testing Agent's evaluation
    should_continue: bool  # Whether Testing Agent wants to continue
    validation_checks: list[ValidationCheck] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def passed(self) -> bool:
        """All validation checks passed"""
        return all(check.passed for check in self.validation_checks)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "turn_number": self.turn_number,
            "user_message": self.user_message,
            "agent_response": self.agent_response[:200] + "..." if len(self.agent_response) > 200 else self.agent_response,
            "files_generated": self.files_generated,
            "tools_called": self.tools_called,
            "assessment": self.assessment,
            "should_continue": self.should_continue,
            "validation_checks": [check.to_dict() for check in self.validation_checks],
            "passed": self.passed,
            "timestamp": self.timestamp.isoformat()
        }


@dataclass
class ScenarioResult:
    """
    Complete result from running an autonomous test scenario.

    Contains all turn results, final verdict, and evidence collected.
    """
    scenario_id: str
    scenario_name: str
    passed: bool
    turn_results: list[TurnResult]
    final_verdict: str  # Testing Agent's final assessment
    final_checks: list[ValidationCheck]  # Final validation checks
    conversation_log_path: str | None = None
    workspace_path: str | None = None
    started_at: datetime = field(default_factory=datetime.now)
    ended_at: datetime | None = None
    total_turns: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "scenario_id": self.scenario_id,
            "scenario_name": self.scenario_name,
            "passed": self.passed,
            "turn_results": [turn.to_dict() for turn in self.turn_results],
            "final_verdict": self.final_verdict,
            "final_checks": [check.to_dict() for check in self.final_checks],
            "conversation_log_path": self.conversation_log_path,
            "workspace_path": self.workspace_path,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "total_turns": self.total_turns,
            "metadata": self.metadata
        }

    def to_json(self, pretty: bool = True) -> str:
        """Convert to JSON string"""
        indent = 2 if pretty else None
        return json.dumps(self.to_dict(), indent=indent)

    def save(self, output_path: str) -> str:
        """Save result to JSON file"""
        from pathlib import Path
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(self.to_json(pretty=True))

        return str(output_file)


@dataclass
class AutonomousScenario:
    """
    Test scenario where Testing LLM autonomously interacts with Coding Agent.

    Unlike scripted scenarios, this allows the Testing LLM to adapt its
    conversation based on the Coding Agent's responses - like a real user.

    Example:
        scenario = AutonomousScenario(
            scenario_id="vague_calculator",
            name="Vague Request -> Clarification -> Implementation",
            description="User starts vague, agent clarifies, then implements",
            testing_agent_prompt='''
                You are a user who wants a calculator but doesn't know technical terms.
                Start vague ("need help with numbers"), then clarify based on agent's questions.
            ''',
            success_criteria=[
                "Agent asked clarifying questions before implementing",
                "File 'calculator.py' was created",
                "Code contains arithmetic operations"
            ],
            max_turns=5
        )
    """
    scenario_id: str
    name: str
    description: str
    testing_agent_prompt: str  # System prompt for Testing LLM
    success_criteria: list[str]  # High-level expectations for success
    max_turns: int = 10
    timeout_seconds: int = 300
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "scenario_id": self.scenario_id,
            "name": self.name,
            "description": self.description,
            "testing_agent_prompt": self.testing_agent_prompt,
            "success_criteria": self.success_criteria,
            "max_turns": self.max_turns,
            "timeout_seconds": self.timeout_seconds,
            "metadata": self.metadata
        }

    def to_json(self, pretty: bool = True) -> str:
        """Convert to JSON string"""
        indent = 2 if pretty else None
        return json.dumps(self.to_dict(), indent=indent)
