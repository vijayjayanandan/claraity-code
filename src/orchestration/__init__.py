"""
Agent-to-Agent Orchestration

Enables testing through natural conversations between a Testing LLM (acting as user)
and the Coding Agent (system under test).

Basic Usage:
    from src.orchestration import AgentOrchestrator

    # Initialize
    orchestrator = AgentOrchestrator()

    # Start conversation
    session = orchestrator.start_conversation()

    # Send message
    response = session.send_message("Build a calculator")

    # Check response
    if response.success:
        print(f"Files created: {response.files_generated}")

    # End conversation
    log = orchestrator.end_conversation(session.conversation_id)

Autonomous Testing Usage:
    from src.orchestration import (
        AutonomousScenarioRunner,
        AgentOrchestrator,
        get_scenario
    )

    # Initialize
    orchestrator = AgentOrchestrator()
    runner = AutonomousScenarioRunner(orchestrator)

    # Get a scenario
    scenario = get_scenario("vague_calculator")

    # Run autonomous test
    result = runner.run_scenario(scenario)

    # Check result
    if result.passed:
        print("Test PASSED!")
    else:
        print(f"Test FAILED: {result.final_verdict}")
"""

from .agent_orchestrator import AgentOrchestrator
from .conversation import ConversationSession
from .models import AgentMessage, AgentResponse, ConversationLog
from .scenario import (
    AutonomousScenario,
    ScenarioResult,
    TurnResult,
    ValidationCheck,
)
from .scenario_runner import AutonomousScenarioRunner
from .scenarios_library import (
    get_requirement_change_scenario,
    get_scenario,
    get_simple_bugfix_scenario,
    get_vague_calculator_scenario,
    list_scenarios,
)
from .testing_agent import TestingAgent

__all__ = [
    # Basic orchestration
    "AgentMessage",
    "AgentResponse",
    "ConversationLog",
    "ConversationSession",
    "AgentOrchestrator",
    # Autonomous testing
    "AutonomousScenario",
    "ScenarioResult",
    "TurnResult",
    "ValidationCheck",
    "TestingAgent",
    "AutonomousScenarioRunner",
    # Scenario library
    "get_scenario",
    "list_scenarios",
    "get_vague_calculator_scenario",
    "get_simple_bugfix_scenario",
    "get_requirement_change_scenario",
]
