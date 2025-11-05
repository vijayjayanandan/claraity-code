"""
Comprehensive Real-World Memory Testing Suite

This test suite validates the agent's memory system under realistic developer workflows.
Tests working memory, episodic memory, and semantic memory with measurable outcomes.

Author: AI Coding Agent Team
Date: 2025-10-15
"""

import time
import json
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum

from src.core.agent import CodingAgent


# =============================================================================
# TEST FRAMEWORK
# =============================================================================

class MemoryLayer(Enum):
    """Memory layers being tested."""
    WORKING = "working_memory"
    EPISODIC = "episodic_memory"
    SEMANTIC = "semantic_memory"


@dataclass
class TestStep:
    """Single step in a test scenario."""
    turn_number: int
    user_message: str
    expected_behaviors: List[str]  # What agent should demonstrate
    validation_keywords: List[str]  # Keywords that must appear in response
    avoid_keywords: List[str]  # Keywords that should NOT appear
    should_use_tools: Optional[List[str]] = None  # Tools agent should use
    should_not_reread: Optional[List[str]] = None  # Files agent shouldn't re-read


@dataclass
class TestResult:
    """Result of a single test step."""
    turn_number: int
    user_message: str
    agent_response: str
    expected_behaviors: List[str]
    validation_passed: bool
    validation_details: Dict[str, bool]
    tools_used: List[str]
    response_time: float
    memory_stats: Dict


@dataclass
class ScenarioResult:
    """Result of complete scenario."""
    scenario_name: str
    memory_layer: MemoryLayer
    total_turns: int
    passed_turns: int
    failed_turns: int
    test_results: List[TestResult]
    overall_score: float
    critical_failures: List[str]
    recommendations: List[str]


class MemoryTestFramework:
    """Framework for testing memory with real-world scenarios."""

    def __init__(self, agent: CodingAgent):
        """Initialize test framework with agent instance."""
        self.agent = agent
        self.test_results: List[TestResult] = []

    def execute_step(self, step: TestStep) -> TestResult:
        """
        Execute a single test step and validate response.

        Args:
            step: Test step to execute

        Returns:
            Test result with validation details
        """
        print(f"\n{'='*80}")
        print(f"TURN {step.turn_number}")
        print(f"{'='*80}")
        print(f"User: {step.user_message}")
        print(f"Expected Behaviors: {', '.join(step.expected_behaviors)}")

        # Track tool calls before execution
        tools_before = len(self.agent.tool_execution_history)

        # Execute query
        start_time = time.time()
        response = self.agent.chat(step.user_message, stream=False)
        response_time = time.time() - start_time

        # Track tool calls after execution
        tools_after = len(self.agent.tool_execution_history)
        tools_used_in_step = self.agent.tool_execution_history[tools_before:tools_after]

        print(f"\nAgent Response ({response_time:.2f}s):")
        print(f"{response.content[:300]}...")

        # Validate response
        validation_details = {}

        # Check for required keywords
        for keyword in step.validation_keywords:
            found = keyword.lower() in response.content.lower()
            validation_details[f"has_{keyword}"] = found
            if found:
                print(f"  ✓ Found expected keyword: '{keyword}'")
            else:
                print(f"  ✗ Missing expected keyword: '{keyword}'")

        # Check for keywords that shouldn't appear
        for keyword in step.avoid_keywords:
            found = keyword.lower() in response.content.lower()
            validation_details[f"avoids_{keyword}"] = not found
            if not found:
                print(f"  ✓ Correctly avoided: '{keyword}'")
            else:
                print(f"  ✗ Should not mention: '{keyword}'")

        # Check tool usage (from actual execution history)
        tools_used = [t["tool"] for t in tools_used_in_step]
        validation_details["tools_used"] = len(tools_used) > 0 if step.should_use_tools else len(tools_used) == 0

        if step.should_use_tools:
            for tool in step.should_use_tools:
                used = tool in tools_used
                validation_details[f"used_tool_{tool}"] = used
                if used:
                    print(f"  ✓ Correctly used tool: {tool}")
                else:
                    print(f"  ✗ Should have used tool: {tool}")
        elif step.should_use_tools == []:  # Explicitly should NOT use tools
            if tools_used:
                print(f"  ✗ Should not have used tools, but used: {tools_used}")
                validation_details["tools_used"] = False
            else:
                print(f"  ✓ Correctly did not use tools")
                validation_details["tools_used"] = True

        if step.should_not_reread:
            for file in step.should_not_reread:
                # Check if agent re-read a file it shouldn't have
                reread = self._check_if_reread(file, tools_used_in_step)
                validation_details[f"avoided_reread_{file}"] = not reread
                if not reread:
                    print(f"  ✓ Did not re-read: {file}")
                else:
                    print(f"  ✗ Unnecessarily re-read: {file}")

        # Overall validation
        validation_passed = all(validation_details.values())

        # Get memory stats
        memory_stats = self.agent.get_statistics()['memory']

        return TestResult(
            turn_number=step.turn_number,
            user_message=step.user_message,
            agent_response=response.content,
            expected_behaviors=step.expected_behaviors,
            validation_passed=validation_passed,
            validation_details=validation_details,
            tools_used=tools_used,
            response_time=response_time,
            memory_stats=memory_stats
        )

    def _check_if_reread(self, file_path: str, tools_in_step: List[Dict[str, Any]]) -> bool:
        """Check if agent re-read a file."""
        # Check if file appears in read_file tool calls during this step
        for tool_call in tools_in_step:
            if tool_call["tool"] == "read_file":
                # Check if the file path matches (handle partial matches)
                file_arg = tool_call["arguments"].get("file_path", "")
                if file_path in file_arg or file_arg in file_path:
                    return True
        return False

    def calculate_scenario_score(self, results: List[TestResult]) -> Tuple[float, List[str]]:
        """
        Calculate overall score for scenario.

        Returns:
            Tuple of (score, critical_failures)
        """
        if not results:
            return 0.0, ["No test results"]

        passed = sum(1 for r in results if r.validation_passed)
        total = len(results)
        score = (passed / total) * 100

        # Identify critical failures
        critical_failures = []
        for result in results:
            if not result.validation_passed:
                failed_checks = [k for k, v in result.validation_details.items() if not v]
                critical_failures.append(
                    f"Turn {result.turn_number}: Failed checks: {', '.join(failed_checks)}"
                )

        return score, critical_failures

    def generate_report(self, scenario_result: ScenarioResult) -> str:
        """Generate detailed test report."""
        report = []
        report.append("=" * 80)
        report.append(f"MEMORY TEST REPORT: {scenario_result.scenario_name}")
        report.append("=" * 80)
        report.append(f"Memory Layer: {scenario_result.memory_layer.value}")
        report.append(f"Total Turns: {scenario_result.total_turns}")
        report.append(f"Passed: {scenario_result.passed_turns}/{scenario_result.total_turns}")
        report.append(f"Failed: {scenario_result.failed_turns}/{scenario_result.total_turns}")
        report.append(f"Overall Score: {scenario_result.overall_score:.1f}%")
        report.append("")

        # Pass/Fail status
        if scenario_result.overall_score >= 80:
            report.append("✅ SCENARIO PASSED (Score >= 80%)")
        elif scenario_result.overall_score >= 60:
            report.append("⚠️  SCENARIO MARGINAL (60% <= Score < 80%)")
        else:
            report.append("❌ SCENARIO FAILED (Score < 60%)")
        report.append("")

        # Critical failures
        if scenario_result.critical_failures:
            report.append("Critical Failures:")
            for failure in scenario_result.critical_failures:
                report.append(f"  • {failure}")
            report.append("")

        # Recommendations
        if scenario_result.recommendations:
            report.append("Recommendations:")
            for rec in scenario_result.recommendations:
                report.append(f"  • {rec}")
            report.append("")

        # Detailed turn-by-turn
        report.append("Detailed Turn-by-Turn Results:")
        for result in scenario_result.test_results:
            status = "✓" if result.validation_passed else "✗"
            report.append(f"  Turn {result.turn_number} [{status}]: {result.user_message[:60]}...")
            report.append(f"    Response time: {result.response_time:.2f}s")

            # Show validation details
            for check, passed in result.validation_details.items():
                check_status = "✓" if passed else "✗"
                report.append(f"      [{check_status}] {check}")
            report.append("")

        report.append("=" * 80)
        return "\n".join(report)


# =============================================================================
# SCENARIO 1: CODEBASE EXPLORATION (Working Memory Test)
# =============================================================================

class Scenario1_CodebaseExploration:
    """
    Test working memory with multi-file exploration.

    Real-world scenario: Developer exploring unfamiliar codebase
    """

    @staticmethod
    def get_test_steps() -> List[TestStep]:
        """Define test steps for scenario."""
        return [
            # Turn 1: Initial file read
            TestStep(
                turn_number=1,
                user_message="Read the src/core/agent.py file and explain what the CodingAgent class does in 2-3 sentences.",
                expected_behaviors=[
                    "Read the file using read_file tool",
                    "Provide accurate summary of CodingAgent",
                    "Mention key components (LLM, memory, tools, RAG)"
                ],
                validation_keywords=["CodingAgent", "orchestrat", "memory"],
                avoid_keywords=["don't know", "can't find", "unclear"],
                should_use_tools=["read_file"]
            ),

            # Turn 2: Recall without re-reading
            TestStep(
                turn_number=2,
                user_message="What was the name of the main class in that file?",
                expected_behaviors=[
                    "Remember CodingAgent from Turn 1",
                    "Answer without re-reading file",
                    "Show memory retention"
                ],
                validation_keywords=["CodingAgent"],
                avoid_keywords=["don't recall", "don't remember", "which file"],
                should_use_tools=[],  # Should NOT use tools
                should_not_reread=["agent.py"]
            ),

            # Turn 3: Cross-reference with new file
            TestStep(
                turn_number=3,
                user_message="Now read src/memory/manager.py and tell me how it relates to the agent we just discussed.",
                expected_behaviors=[
                    "Read memory/manager.py",
                    "Recall agent.py structure from Turn 1",
                    "Compare and explain relationship"
                ],
                validation_keywords=["MemoryManager", "agent", "relationship"],
                avoid_keywords=["don't recall", "need to re-read"],
                should_use_tools=["read_file"]
            ),

            # Turn 4: Synthesize information
            TestStep(
                turn_number=4,
                user_message="Based on what you've seen in both files, how does the CodingAgent use the MemoryManager?",
                expected_behaviors=[
                    "Recall both agent.py and manager.py",
                    "Synthesize relationship",
                    "Answer without re-reading either file"
                ],
                validation_keywords=["CodingAgent", "MemoryManager", "initializ"],
                avoid_keywords=["don't remember", "need to check"],
                should_use_tools=[],  # Should synthesize from memory
                should_not_reread=["agent.py", "manager.py"]
            ),

            # Turn 5: Detailed recall test
            TestStep(
                turn_number=5,
                user_message="What were the three memory layers mentioned in the MemoryManager file?",
                expected_behaviors=[
                    "Recall specific details from manager.py",
                    "List three memory types",
                    "Show retention of details"
                ],
                validation_keywords=["working", "episodic", "semantic"],
                avoid_keywords=["don't remember", "can't recall"],
                should_use_tools=[],
                should_not_reread=["manager.py"]
            )
        ]

    @staticmethod
    def analyze_results(results: List[TestResult]) -> List[str]:
        """Analyze results and provide recommendations."""
        recommendations = []

        # Check for unnecessary re-reads
        reread_count = sum(
            1 for r in results
            if any("avoided_reread" in k and not v for k, v in r.validation_details.items())
        )
        if reread_count > 0:
            recommendations.append(
                f"Agent re-read files {reread_count} times unnecessarily. "
                "Working memory may not be retaining file contents."
            )

        # Check for memory recall failures
        recall_failures = sum(
            1 for r in results[1:]  # Skip first turn
            if not r.validation_passed and r.turn_number > 1
        )
        if recall_failures > 0:
            recommendations.append(
                f"Agent failed to recall information from previous turns {recall_failures} times. "
                "Working memory retention needs improvement."
            )

        # Check synthesis capability
        turn_4_result = next((r for r in results if r.turn_number == 4), None)
        if turn_4_result and not turn_4_result.validation_passed:
            recommendations.append(
                "Agent struggled to synthesize information from multiple files. "
                "Cross-file reasoning may be weak."
            )

        return recommendations


# =============================================================================
# SCENARIO 2: MULTI-FILE IMPLEMENTATION (Episodic Memory Test)
# =============================================================================

class Scenario2_MultiFileImplementation:
    """
    Test episodic memory with multi-step feature implementation.

    Real-world scenario: Developer implementing a new feature across multiple files
    """

    @staticmethod
    def get_test_steps() -> List[TestStep]:
        """Define test steps for scenario."""
        return [
            # Turn 1: Understand existing pattern
            TestStep(
                turn_number=1,
                user_message="I want to add a new tool called 'list_directory'. First, show me how existing tools are structured by reading one of the tool files.",
                expected_behaviors=[
                    "Read a tool file (e.g., src/tools/read_file_tool.py)",
                    "Explain tool structure",
                    "Identify pattern to follow"
                ],
                validation_keywords=["tool", "class", "execute"],
                avoid_keywords=["don't know", "can't find"],
                should_use_tools=["read_file"]
            ),

            # Turn 2: Plan implementation
            TestStep(
                turn_number=2,
                user_message="Good. Now outline the steps to create and integrate this new list_directory tool.",
                expected_behaviors=[
                    "Recall tool structure from Turn 1",
                    "Provide step-by-step plan",
                    "Mention: create tool file, register it, update prompts"
                ],
                validation_keywords=["create", "register", "tool_executor"],
                avoid_keywords=["don't remember", "need to check"],
                should_use_tools=[],  # Should plan from memory
                should_not_reread=[]
            ),

            # Turn 3: Create tool file
            TestStep(
                turn_number=3,
                user_message="Create the list_directory tool following the pattern you saw earlier.",
                expected_behaviors=[
                    "Recall tool pattern from Turn 1",
                    "Create tool file with proper structure",
                    "Follow naming conventions"
                ],
                validation_keywords=["class", "ListDirectoryTool", "execute", "import"],
                avoid_keywords=["what pattern", "need to review"],
                should_use_tools=["write_file"],
                should_not_reread=["tool"]  # Shouldn't need to re-read existing tool
            ),

            # Turn 4: Register tool
            TestStep(
                turn_number=4,
                user_message="Now register this tool in the tool executor like the other tools.",
                expected_behaviors=[
                    "Remember where tools are registered",
                    "Recall it's in agent.py _register_tools method",
                    "Add registration without being told location"
                ],
                validation_keywords=["register", "ListDirectoryTool"],
                avoid_keywords=["which file", "where do I"],
                should_use_tools=["read_file", "edit_file"],
                should_not_reread=[]
            ),

            # Turn 5: Update prompts
            TestStep(
                turn_number=5,
                user_message="Add the new tool to the system prompts so the agent knows about it.",
                expected_behaviors=[
                    "Remember prompt file location",
                    "Recall tool description format from Turn 1",
                    "Add tool documentation"
                ],
                validation_keywords=["list_directory", "prompt"],
                avoid_keywords=["which file", "what format"],
                should_use_tools=["read_file", "edit_file"],
                should_not_reread=[]
            ),

            # Turn 6: Verify implementation
            TestStep(
                turn_number=6,
                user_message="Summarize what we just built and where the changes were made.",
                expected_behaviors=[
                    "Recall all changes made",
                    "List files modified",
                    "Provide complete summary"
                ],
                validation_keywords=["ListDirectoryTool", "agent.py", "prompt"],
                avoid_keywords=["don't recall", "can't remember"],
                should_use_tools=[],
                should_not_reread=[]
            ),

            # Turn 7: Test episodic consolidation
            TestStep(
                turn_number=7,
                user_message="What was the structure of existing tools that we used as a pattern?",
                expected_behaviors=[
                    "Recall details from Turn 1 (6 turns ago)",
                    "Show episodic memory retention",
                    "Provide accurate details"
                ],
                validation_keywords=["class", "execute", "ToolResult"],
                avoid_keywords=["don't remember", "too long ago"],
                should_use_tools=[],
                should_not_reread=[]
            )
        ]

    @staticmethod
    def analyze_results(results: List[TestResult]) -> List[str]:
        """Analyze results and provide recommendations."""
        recommendations = []

        # Check episodic memory (Turn 7 recalls Turn 1)
        turn_7 = next((r for r in results if r.turn_number == 7), None)
        if turn_7 and not turn_7.validation_passed:
            recommendations.append(
                "Agent failed to recall information from 6 turns ago. "
                "Episodic memory consolidation is not working properly."
            )

        # Check task continuity
        failed_middle_turns = sum(
            1 for r in results[2:6]  # Turns 3-6
            if not r.validation_passed
        )
        if failed_middle_turns > 1:
            recommendations.append(
                f"Agent lost context {failed_middle_turns} times during multi-step task. "
                "Task context maintenance needs improvement."
            )

        # Check if agent knew where to make changes
        turn_4 = next((r for r in results if r.turn_number == 4), None)
        if turn_4:
            if "which file" in turn_4.agent_response.lower():
                recommendations.append(
                    "Agent asked where to register tool despite seeing agent.py earlier. "
                    "Project structure awareness is weak."
                )

        return recommendations


# =============================================================================
# MAIN TEST RUNNER
# =============================================================================

def run_scenario(
    agent: CodingAgent,
    scenario_name: str,
    memory_layer: MemoryLayer,
    steps: List[TestStep],
    analyzer_func
) -> ScenarioResult:
    """Run a complete test scenario."""
    print(f"\n{'#'*80}")
    print(f"# SCENARIO: {scenario_name}")
    print(f"# MEMORY LAYER: {memory_layer.value}")
    print(f"# TOTAL TURNS: {len(steps)}")
    print(f"{'#'*80}")

    framework = MemoryTestFramework(agent)
    test_results = []

    # Execute all steps
    for step in steps:
        result = framework.execute_step(step)
        test_results.append(result)
        time.sleep(1)  # Brief pause between turns

    # Calculate score
    score, critical_failures = framework.calculate_scenario_score(test_results)

    # Get recommendations
    recommendations = analyzer_func(test_results)

    # Create scenario result
    passed = sum(1 for r in test_results if r.validation_passed)
    failed = len(test_results) - passed

    scenario_result = ScenarioResult(
        scenario_name=scenario_name,
        memory_layer=memory_layer,
        total_turns=len(steps),
        passed_turns=passed,
        failed_turns=failed,
        test_results=test_results,
        overall_score=score,
        critical_failures=critical_failures,
        recommendations=recommendations
    )

    # Generate and print report
    report = framework.generate_report(scenario_result)
    print(f"\n{report}")

    return scenario_result


def main():
    """Run comprehensive memory tests."""
    print("=" * 80)
    print("COMPREHENSIVE REAL-WORLD MEMORY TESTING SUITE")
    print("=" * 80)
    print("Testing: Working Memory, Episodic Memory")
    print("Backend: Alibaba Cloud (qwen3-coder-plus)")
    print("=" * 80)

    # Initialize agent with Alibaba API
    print("\n📚 Initializing agent...")
    print("⚙️  Using production settings:")
    print("   - Context: 128K tokens (131,072)")
    print("   - Prompts: Full enhanced (production-grade)")
    agent = CodingAgent(
        backend="openai",
        model_name="qwen3-coder-plus",
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        context_window=131072,  # 128K - production setting
        api_key="sk-6ca5ca68942447c7a4c18d0ea63f75e7",
        api_key_env="DASHSCOPE_API_KEY"
    )

    # Index codebase for RAG
    print("📚 Indexing codebase...")
    try:
        stats = agent.index_codebase("./src")
        print(f"✓ Indexed {stats['total_files']} files, {stats['total_chunks']} chunks\n")
    except Exception as e:
        print(f"⚠ Warning: Could not index: {e}\n")

    all_results = []

    # Run Scenario 1: Codebase Exploration
    scenario1_result = run_scenario(
        agent=agent,
        scenario_name="Codebase Exploration (Working Memory)",
        memory_layer=MemoryLayer.WORKING,
        steps=Scenario1_CodebaseExploration.get_test_steps(),
        analyzer_func=Scenario1_CodebaseExploration.analyze_results
    )
    all_results.append(scenario1_result)

    # Clear memory between scenarios
    print("\n🧹 Clearing memory between scenarios...")
    agent.clear_memory()
    time.sleep(2)

    # Run Scenario 2: Multi-File Implementation
    scenario2_result = run_scenario(
        agent=agent,
        scenario_name="Multi-File Implementation (Episodic Memory)",
        memory_layer=MemoryLayer.EPISODIC,
        steps=Scenario2_MultiFileImplementation.get_test_steps(),
        analyzer_func=Scenario2_MultiFileImplementation.analyze_results
    )
    all_results.append(scenario2_result)

    # Generate final summary
    print("\n" + "=" * 80)
    print("FINAL SUMMARY")
    print("=" * 80)

    total_score = sum(r.overall_score for r in all_results) / len(all_results)
    print(f"Overall Score: {total_score:.1f}%")
    print(f"Scenarios Passed: {sum(1 for r in all_results if r.overall_score >= 80)}/{len(all_results)}")
    print("")

    if total_score >= 80:
        print("✅ MEMORY SYSTEM PASSED")
        print("The memory system is solid enough to build workflows on top of.")
    elif total_score >= 60:
        print("⚠️  MEMORY SYSTEM MARGINAL")
        print("Memory works but has issues. Consider fixes before building complex workflows.")
    else:
        print("❌ MEMORY SYSTEM FAILED")
        print("Critical memory issues found. Must fix before proceeding with workflows.")

    print("\n" + "=" * 80)
    print("CONSOLIDATED RECOMMENDATIONS:")
    print("=" * 80)
    for i, result in enumerate(all_results, 1):
        if result.recommendations:
            print(f"\nScenario {i}: {result.scenario_name}")
            for rec in result.recommendations:
                print(f"  • {rec}")

    # Save detailed results
    results_file = "memory_test_results.json"
    with open(results_file, 'w') as f:
        json.dump(
            {
                "total_score": total_score,
                "scenarios": [
                    {
                        "name": r.scenario_name,
                        "score": r.overall_score,
                        "passed_turns": r.passed_turns,
                        "failed_turns": r.failed_turns,
                        "recommendations": r.recommendations
                    }
                    for r in all_results
                ]
            },
            f,
            indent=2
        )
    print(f"\n📄 Detailed results saved to: {results_file}")


if __name__ == "__main__":
    main()
