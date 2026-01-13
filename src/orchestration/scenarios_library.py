"""
Scenarios Library

Pre-built test scenarios for validating Coding Agent behavior.
Each scenario tests a different aspect of agent capabilities.
"""

from .scenario import AutonomousScenario


def get_vague_calculator_scenario() -> AutonomousScenario:
    """
    Test: Vague Request → Clarification → Implementation

    Validates that the agent:
    - Handles vague initial requests gracefully
    - Asks clarifying questions before implementing
    - Gathers requirements incrementally
    - Creates working code based on clarified requirements
    """
    return AutonomousScenario(
        scenario_id="vague_calculator",
        name="Vague Calculator Request",
        description="User starts with vague request for 'help with numbers', agent should clarify requirements before implementing a calculator",

        testing_agent_prompt="""
You are a NON-TECHNICAL USER who needs help building a calculator, but you don't know how to explain it properly at first.

YOUR BEHAVIOR:
1. START VAGUE: Say something like "I need help with numbers" or "need something for math"
   - DO NOT say "calculator" immediately
   - Act like you're not sure what to ask for

2. RESPOND TO QUESTIONS: When the agent asks clarifying questions, answer them
   - If they ask what kind of math: say "basic calculator stuff"
   - If they ask about operations: gradually mention +, -, *, /
   - Be realistic - you might not know all technical terms

3. APPRECIATE CLARIFICATION: When agent asks good questions, acknowledge it
   - "Oh yes, that's what I meant!"
   - "Exactly, just basic math operations"

4. STOP WHEN DONE: When agent creates the calculator file, you can:
   - Thank them
   - Maybe ask to see the code
   - End the conversation naturally

BE REALISTIC: Real users start vague and clarify gradually. That's what you're testing!
""",

        success_criteria=[
            "Agent asked clarifying questions before implementing (didn't just guess)",
            "Agent created a calculator file (calculator.py, calc.py, or similar)",
            "Code contains basic arithmetic operations (add, subtract, multiply, divide)",
            "Agent handled the vague initial request professionally (didn't complain about lack of details)"
        ],

        max_turns=5,
        timeout_seconds=300
    )


def get_simple_bugfix_scenario() -> AutonomousScenario:
    """
    Test: Bug Report → Investigation → Fix

    Validates that the agent:
    - Understands bug reports from users
    - Asks for clarification when needed
    - Creates or fixes code to address the bug
    - Verifies the fix works
    """
    return AutonomousScenario(
        scenario_id="simple_bugfix",
        name="Simple Bug Report",
        description="User reports a bug in their code, agent should investigate and fix it",

        testing_agent_prompt="""
You are a DEVELOPER who found a bug in a simple Python script and needs help fixing it.

YOUR BEHAVIOR:
1. START WITH BUG REPORT: Describe a simple bug
   - "My calculator crashes when I divide by zero"
   - "I get an error when running my math script"
   - Be specific about the symptom, but maybe not the root cause

2. PROVIDE CONTEXT WHEN ASKED:
   - If agent asks for code: provide a simple buggy calculator
   - If agent asks about the error: describe it ("ZeroDivisionError")
   - If agent asks how to reproduce: explain the steps

3. TEST THE FIX: When agent provides a fix:
   - Acknowledge it
   - Maybe ask how it works
   - Confirm it solves the problem

4. BE COLLABORATIVE: You're asking for help, not demanding
   - "Can you help me fix this?"
   - "What do you think is wrong?"
   - "That makes sense, thank you!"

EXAMPLE BUG CODE you can provide if asked:
```python
def divide(a, b):
    return a / b

result = divide(10, 0)  # This crashes!
print(result)
```
""",

        success_criteria=[
            "Agent asked for the code or error details",
            "Agent identified the issue (division by zero or similar)",
            "Agent provided a fix (add error handling/validation)",
            "Agent explained the fix clearly"
        ],

        max_turns=5,
        timeout_seconds=300
    )


def get_requirement_change_scenario() -> AutonomousScenario:
    """
    Test: Initial Request → Mid-Task Requirement Change → Adaptation

    Validates that the agent:
    - Handles changing requirements gracefully
    - Doesn't get confused when user changes their mind
    - Adapts the implementation to new requirements
    - Maintains context across requirement changes
    """
    return AutonomousScenario(
        scenario_id="requirement_change",
        name="Mid-Task Requirement Change",
        description="User starts with one request, then changes requirements mid-conversation",

        testing_agent_prompt="""
You are a USER who isn't quite sure what they want and changes their mind mid-task.

YOUR BEHAVIOR:
1. START WITH INITIAL REQUEST:
   - "I need a simple text file reader"
   - Be clear about this initial requirement

2. LET AGENT START WORKING:
   - When agent asks clarifying questions, answer them
   - Let them start implementing or planning

3. CHANGE YOUR MIND (Turn 2 or 3):
   - "Actually, I also need it to write files, not just read"
   - "Oh wait, can it handle CSV files instead of plain text?"
   - Make it a realistic change, not complete reversal

4. APPRECIATE FLEXIBILITY:
   - "Sorry for changing the requirements!"
   - "Can you adapt what you've done?"
   - "Thanks for being flexible"

5. CONFIRM FINAL RESULT:
   - When agent adapts the code, confirm it works
   - End conversation when satisfied

GOAL: Test if agent handles requirement changes gracefully without getting confused or frustrated.
""",

        success_criteria=[
            "Agent handled the requirement change without complaint",
            "Agent adapted the implementation to new requirements",
            "Agent maintained context (didn't forget initial request)",
            "Final solution incorporates both initial and changed requirements"
        ],

        max_turns=6,
        timeout_seconds=300
    )


def get_checkpoint_feature_scenario() -> AutonomousScenario:
    """
    Test: Checkpoint Feature → Save → List → Understanding

    Validates that the agent:
    - Understands checkpoint feature requests
    - Can create checkpoints when asked
    - Can list/explain checkpoint functionality
    - Demonstrates knowledge of checkpoint commands
    """
    return AutonomousScenario(
        scenario_id="checkpoint_feature",
        name="Checkpoint Feature Test",
        description="User asks about checkpoint feature and wants to save work. Agent should demonstrate checkpoint functionality.",

        testing_agent_prompt="""
You are a USER working on a long-running project who wants to learn about and use the checkpoint feature.

YOUR BEHAVIOR:
1. START WITH QUESTION ABOUT CHECKPOINTS:
   - "I heard this agent has a checkpoint feature, can you tell me about it?"
   - "How do I save my progress in case I need to resume later?"
   - Be curious but not technical

2. ASK FOR DEMONSTRATION:
   - When agent explains checkpoints, ask them to show how to use it
   - "Can you create a checkpoint now?"
   - "How do I list saved checkpoints?"

3. REQUEST CHECKPOINT CREATION:
   - Ask agent to save current work to a checkpoint
   - "Can you save our current conversation as a checkpoint called 'initial setup'?"
   - Be specific about wanting to save progress

4. VERIFY UNDERSTANDING:
   - Ask follow-up questions about checkpoint features
   - "Can I restore a checkpoint later?"
   - "How many checkpoints can I have?"

5. END POSITIVELY:
   - Thank the agent when checkpoints are created/explained
   - "Great, that's helpful!"
   - End when you understand the feature

IMPORTANT:
- You're testing if the agent knows about and can use checkpoint functionality
- The agent should either use checkpoint commands or the create_checkpoint tool
- Act like a real user learning a new feature
""",

        success_criteria=[
            "Agent explained checkpoint feature clearly (save points for long sessions)",
            "Agent demonstrated checkpoint creation (via tool call)",
            "Agent successfully created at least one checkpoint with valid metadata"
        ],

        max_turns=5,
        timeout_seconds=300
    )


# Scenario registry
ALL_SCENARIOS = {
    "vague_calculator": get_vague_calculator_scenario,
    "simple_bugfix": get_simple_bugfix_scenario,
    "requirement_change": get_requirement_change_scenario,
    "checkpoint_feature": get_checkpoint_feature_scenario,
}


def get_scenario(scenario_id: str) -> AutonomousScenario:
    """
    Get a scenario by ID.

    Args:
        scenario_id: Scenario identifier

    Returns:
        AutonomousScenario instance

    Raises:
        KeyError: If scenario_id not found
    """
    if scenario_id not in ALL_SCENARIOS:
        available = ", ".join(ALL_SCENARIOS.keys())
        raise KeyError(f"Unknown scenario '{scenario_id}'. Available: {available}")

    return ALL_SCENARIOS[scenario_id]()


def list_scenarios() -> dict:
    """
    List all available scenarios.

    Returns:
        Dictionary mapping scenario IDs to their names/descriptions
    """
    return {
        scenario_id: {
            "name": factory().name,
            "description": factory().description,
            "max_turns": factory().max_turns
        }
        for scenario_id, factory in ALL_SCENARIOS.items()
    }
