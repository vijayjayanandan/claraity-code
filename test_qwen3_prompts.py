"""
Test script to discover optimal prompt strategy for Qwen3-Coder-Plus multi-tool calling.
Tests multiple prompt strategies against two scenarios to find best approach.
"""

import os
import json
import requests
from typing import Dict, List, Any
from datetime import datetime

# API Configuration
API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
API_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions"

# Tool Definitions (OpenAI-compatible format)
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file. Use this to create new files or overwrite existing ones.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the file (relative or absolute)"
                    },
                    "content": {
                        "type": "string",
                        "description": "Complete content to write to the file"
                    }
                },
                "required": ["file_path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List files and directories in a given path",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory_path": {
                        "type": "string",
                        "description": "Path to directory to list"
                    }
                },
                "required": ["directory_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read content from a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to file to read"
                    }
                },
                "required": ["file_path"]
            }
        }
    }
]

# Test Scenarios
SCENARIO_A = """Create 3 Python files:
- hello.py: prints "Hello, World!"
- goodbye.py: prints "Goodbye, World!"
- README.md: describes the project"""

SCENARIO_B = """Build a command-line weather tool with:
- weather.py: main script with API call to OpenWeatherMap, response caching, and CLI argument parsing
- test_weather.py: unit tests with pytest for API calls and caching logic
- README.md: installation instructions and usage examples
- requirements.txt: dependencies (requests, pytest)

Include error handling, help text, and proper docstrings."""


class PromptStrategy:
    """Represents a prompt engineering strategy to test"""

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description

    def build_messages(self, user_request: str) -> List[Dict[str, Any]]:
        """Build messages array for this strategy"""
        raise NotImplementedError


class Strategy1_Explicit(PromptStrategy):
    """Explicit instruction emphasizing multiple tool calls"""

    def __init__(self):
        super().__init__(
            "Explicit Instruction",
            "Direct instruction to generate multiple tool calls in single response"
        )

    def build_messages(self, user_request: str) -> List[Dict[str, Any]]:
        system_message = """You are an expert software architect creating detailed execution plans.

**CRITICAL: Generate ALL necessary tool calls in a SINGLE response.**
- Do NOT generate just 1 tool call - generate ALL steps needed to complete the task
- Call multiple tools at once to create multiple files, make multiple edits, etc.
- Example: To create a project with 3 files, generate 3 write_file calls in one response

For each file creation task, you MUST:
1. Generate a separate write_file tool call for EACH file
2. Include complete, working code in each tool call
3. Return ALL tool calls together in this single response"""

        return [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_request}
        ]


class Strategy2_FewShot(PromptStrategy):
    """Few-shot examples demonstrating multi-tool responses"""

    def __init__(self):
        super().__init__(
            "Few-Shot Examples",
            "Provide examples of multi-tool responses in conversation history"
        )

    def build_messages(self, user_request: str) -> List[Dict[str, Any]]:
        system_message = """You are an expert coding assistant. Generate tool calls to complete programming tasks."""

        return [
            {"role": "system", "content": system_message},

            # Example 1: Simple multi-file
            {"role": "user", "content": "Create calculator.py with add/subtract functions and test_calculator.py with unit tests"},
            {"role": "assistant", "content": "", "tool_calls": [
                {
                    "id": "call_example_1",
                    "type": "function",
                    "function": {
                        "name": "write_file",
                        "arguments": json.dumps({
                            "file_path": "calculator.py",
                            "content": "def add(a, b):\n    return a + b\n\ndef subtract(a, b):\n    return a - b"
                        })
                    }
                },
                {
                    "id": "call_example_2",
                    "type": "function",
                    "function": {
                        "name": "write_file",
                        "arguments": json.dumps({
                            "file_path": "test_calculator.py",
                            "content": "from calculator import add, subtract\n\ndef test_add():\n    assert add(2, 3) == 5"
                        })
                    }
                }
            ]},

            # Example 2: Project with docs
            {"role": "user", "content": "Create utils.py, main.py, and README.md for a simple project"},
            {"role": "assistant", "content": "", "tool_calls": [
                {
                    "id": "call_example_3",
                    "type": "function",
                    "function": {
                        "name": "write_file",
                        "arguments": json.dumps({
                            "file_path": "utils.py",
                            "content": "def helper():\n    pass"
                        })
                    }
                },
                {
                    "id": "call_example_4",
                    "type": "function",
                    "function": {
                        "name": "write_file",
                        "arguments": json.dumps({
                            "file_path": "main.py",
                            "content": "from utils import helper\n\nif __name__ == '__main__':\n    helper()"
                        })
                    }
                },
                {
                    "id": "call_example_5",
                    "type": "function",
                    "function": {
                        "name": "write_file",
                        "arguments": json.dumps({
                            "file_path": "README.md",
                            "content": "# Simple Project\n\nA basic Python project."
                        })
                    }
                }
            ]},

            # Actual request
            {"role": "user", "content": user_request}
        ]


class Strategy3_Numbered(PromptStrategy):
    """Numbered steps approach"""

    def __init__(self):
        super().__init__(
            "Numbered Steps",
            "Request numbered steps with corresponding tool calls"
        )

    def build_messages(self, user_request: str) -> List[Dict[str, Any]]:
        system_message = """You are a coding assistant that generates execution plans.

When given a task, respond by generating tool calls in a numbered sequence:

Step 1: write_file for first file
Step 2: write_file for second file
Step 3: write_file for third file
...and so on

Generate ALL tool calls in this single response, one for each step needed."""

        return [
            {"role": "system", "content": system_message},
            {"role": "user", "content": f"{user_request}\n\nGenerate the numbered tool calls to complete this task."}
        ]


class Strategy4_Parallel(PromptStrategy):
    """Parallel instruction (Claude's approach)"""

    def __init__(self):
        super().__init__(
            "Parallel Instruction",
            "Emphasize parallel execution of independent tool calls"
        )

    def build_messages(self, user_request: str) -> List[Dict[str, Any]]:
        system_message = """You are an expert coding assistant.

**Important: Parallel Tool Execution**
If you intend to call multiple tools and there are no dependencies between tool calls,
make ALL of the independent tool calls in parallel in a SINGLE response.

Maximize use of parallel tool calls where possible:
- Creating multiple files? Generate multiple write_file calls NOW
- Multiple independent operations? Execute them together
- Do NOT wait or generate one at a time

For file creation tasks, generate ALL write_file calls in this response."""

        return [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_request}
        ]


class Strategy5_Checklist(PromptStrategy):
    """Checklist-based approach"""

    def __init__(self):
        super().__init__(
            "Checklist Format",
            "Request checklist of files then generate corresponding tool calls"
        )

    def build_messages(self, user_request: str) -> List[Dict[str, Any]]:
        system_message = """You are a coding assistant that creates complete project implementations.

For each task:
1. Identify ALL files needed (make a mental checklist)
2. Generate a write_file tool call for EACH file on your checklist
3. Return ALL tool calls together in this response

Example checklist approach:
Task: "Create calculator project"
Checklist: [calculator.py, test_calculator.py, README.md]
Action: Generate 3 write_file calls

Now apply this to the user's request."""

        return [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_request}
        ]


class Strategy6_Batch(PromptStrategy):
    """Batch processing emphasis"""

    def __init__(self):
        super().__init__(
            "Batch Processing",
            "Frame task as batch operation requiring all files at once"
        )

    def build_messages(self, user_request: str) -> List[Dict[str, Any]]:
        system_message = """You are a batch processing system for code generation.

**Batch Mode: Generate ALL outputs in single pass**
- Analyze the complete requirements
- Identify every file needed
- Generate ALL write_file tool calls as a batch
- Never generate partial batches - return complete set

Think of this as a compiler: you must process ALL source files in one compilation pass."""

        return [
            {"role": "system", "content": system_message},
            {"role": "user", "content": f"[BATCH REQUEST] {user_request}\n\nGenerate complete batch of tool calls."}
        ]


class Strategy7_Array(PromptStrategy):
    """Array/list metaphor"""

    def __init__(self):
        super().__init__(
            "Array of Operations",
            "Frame tool calls as array that must be filled completely"
        )

    def build_messages(self, user_request: str) -> List[Dict[str, Any]]:
        system_message = """You are a code generator that outputs arrays of operations.

Your response should be an ARRAY of tool_calls:
tool_calls = [
    write_file(file1),
    write_file(file2),
    write_file(file3),
    ...
]

Fill the entire array with ALL necessary operations. An incomplete array is a bug.

For the user's request, generate the complete array of write_file calls."""

        return [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_request}
        ]


class Strategy8_Atomic(PromptStrategy):
    """Atomic transaction approach"""

    def __init__(self):
        super().__init__(
            "Atomic Transaction",
            "Frame as atomic transaction requiring all operations together"
        )

    def build_messages(self, user_request: str) -> List[Dict[str, Any]]:
        system_message = """You are a transactional code generator.

**ATOMIC TRANSACTION MODE**
Each task is an atomic transaction that must include ALL operations:
- Transaction cannot commit with partial operations
- All write_file calls must be included in this transaction
- Generating only 1 call when 3+ are needed = transaction failure

Generate the complete transaction of tool calls now."""

        return [
            {"role": "system", "content": system_message},
            {"role": "user", "content": f"[TRANSACTION] {user_request}"}
        ]


class Strategy9_Complete(PromptStrategy):
    """Completeness validation"""

    def __init__(self):
        super().__init__(
            "Completeness Validation",
            "Ask model to validate completeness before responding"
        )

    def build_messages(self, user_request: str) -> List[Dict[str, Any]]:
        system_message = """You are a meticulous code generator with self-validation.

Before generating tool calls:
1. List every file needed (internal check)
2. Verify your list is complete
3. Generate write_file call for EACH item on your list
4. Final check: count tool_calls = count files needed

If counts don't match, you've made an error. Always generate complete set."""

        return [
            {"role": "system", "content": system_message},
            {"role": "user", "content": f"{user_request}\n\n(Remember: validate completeness before responding)"}
        ]


class Strategy10_Hybrid(PromptStrategy):
    """Hybrid: Explicit + Few-shot + Parallel"""

    def __init__(self):
        super().__init__(
            "Hybrid (Best Practices)",
            "Combines explicit instruction, few-shot, and parallel concepts"
        )

    def build_messages(self, user_request: str) -> List[Dict[str, Any]]:
        system_message = """You are an expert coding assistant that generates complete implementations.

**CRITICAL RULES:**
1. Generate ALL tool calls in a SINGLE response (no partial responses)
2. For independent operations (like creating multiple files), use parallel tool calls
3. Each file = one write_file call, all returned together

Study these examples of correct multi-tool responses:"""

        return [
            {"role": "system", "content": system_message},

            # Example showing 2 files
            {"role": "user", "content": "Create main.py and utils.py"},
            {"role": "assistant", "content": "", "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "write_file",
                        "arguments": json.dumps({
                            "file_path": "main.py",
                            "content": "from utils import helper\n\nif __name__ == '__main__':\n    print('Hello')"
                        })
                    }
                },
                {
                    "id": "call_2",
                    "type": "function",
                    "function": {
                        "name": "write_file",
                        "arguments": json.dumps({
                            "file_path": "utils.py",
                            "content": "def helper():\n    return 'help'"
                        })
                    }
                }
            ]},

            # Now the actual request
            {"role": "user", "content": f"{user_request}\n\nGenerate ALL write_file calls in parallel now."}
        ]


def make_api_call(messages: List[Dict[str, Any]], strategy_name: str) -> Dict[str, Any]:
    """Make API call to DashScope with given messages"""

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "qwen3-coder-plus",
        "messages": messages,
        "tools": TOOLS,
        "tool_choice": "auto",
        "temperature": 0.1  # Lower temperature for more consistent results
    }

    print(f"\n[TEST] Strategy: {strategy_name}")
    print(f"[REQUEST] Sending to DashScope...")

    try:
        response = requests.post(API_URL, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        result = response.json()

        # Extract tool calls
        tool_calls = result.get("choices", [{}])[0].get("message", {}).get("tool_calls", [])

        print(f"[RESPONSE] Received {len(tool_calls)} tool calls")

        return {
            "success": True,
            "tool_calls": tool_calls,
            "full_response": result
        }

    except requests.exceptions.RequestException as e:
        print(f"[ERROR] API call failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "tool_calls": []
        }


def test_strategy(strategy: PromptStrategy, scenario_name: str, scenario_request: str) -> Dict[str, Any]:
    """Test a single strategy on a single scenario"""

    print(f"\n{'='*80}")
    print(f"Testing: {strategy.name} on {scenario_name}")
    print(f"{'='*80}")

    messages = strategy.build_messages(scenario_request)
    result = make_api_call(messages, strategy.name)

    if result["success"]:
        tool_calls = result["tool_calls"]

        # Analyze tool calls
        write_file_calls = [tc for tc in tool_calls if tc.get("function", {}).get("name") == "write_file"]
        other_calls = [tc for tc in tool_calls if tc.get("function", {}).get("name") != "write_file"]

        print(f"\n[ANALYSIS]")
        print(f"  - Total tool calls: {len(tool_calls)}")
        print(f"  - write_file calls: {len(write_file_calls)}")
        print(f"  - Other calls: {len(other_calls)}")

        if write_file_calls:
            print(f"\n[FILES CREATED]")
            for tc in write_file_calls:
                args = json.loads(tc["function"]["arguments"])
                file_path = args.get("file_path", "unknown")
                content_len = len(args.get("content", ""))
                print(f"  - {file_path} ({content_len} chars)")

        return {
            "strategy": strategy.name,
            "scenario": scenario_name,
            "total_calls": len(tool_calls),
            "write_file_calls": len(write_file_calls),
            "other_calls": len(other_calls),
            "tool_calls": tool_calls,
            "success": True
        }
    else:
        print(f"\n[FAILURE] {result.get('error', 'Unknown error')}")
        return {
            "strategy": strategy.name,
            "scenario": scenario_name,
            "total_calls": 0,
            "write_file_calls": 0,
            "other_calls": 0,
            "success": False,
            "error": result.get("error")
        }


def run_all_tests():
    """Run all strategy tests on both scenarios"""

    strategies = [
        Strategy1_Explicit(),
        Strategy2_FewShot(),
        Strategy3_Numbered(),
        Strategy4_Parallel(),
        Strategy5_Checklist(),
        Strategy6_Batch(),
        Strategy7_Array(),
        Strategy8_Atomic(),
        Strategy9_Complete(),
        Strategy10_Hybrid()
    ]

    scenarios = [
        ("Scenario A (3 files)", SCENARIO_A),
        ("Scenario B (4 files)", SCENARIO_B)
    ]

    results = []

    for strategy in strategies:
        for scenario_name, scenario_request in scenarios:
            result = test_strategy(strategy, scenario_name, scenario_request)
            results.append(result)

            # Small delay between API calls
            import time
            time.sleep(2)

    return results


def generate_report(results: List[Dict[str, Any]]):
    """Generate markdown report from test results"""

    report = f"""# Qwen3-Coder-Plus Prompt Engineering Results

## Executive Summary

**Test Date:** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

**Objective:** Discover optimal prompt strategy for multi-tool calling with Qwen3-coder-plus

**Tests Conducted:** {len(results)} tests ({len(results)//2} strategies × 2 scenarios)

"""

    # Find best performers
    scenario_a_results = [r for r in results if r["scenario"] == "Scenario A (3 files)" and r["success"]]
    scenario_b_results = [r for r in results if r["scenario"] == "Scenario B (4 files)" and r["success"]]

    if scenario_a_results:
        best_a = max(scenario_a_results, key=lambda x: x["write_file_calls"])
        report += f"**Best for Scenario A:** {best_a['strategy']} ({best_a['write_file_calls']} write_file calls)\n\n"

    if scenario_b_results:
        best_b = max(scenario_b_results, key=lambda x: x["write_file_calls"])
        report += f"**Best for Scenario B:** {best_b['strategy']} ({best_b['write_file_calls']} write_file calls)\n\n"

    # Results table
    report += """## Test Results

| Strategy | Scenario A (3 files) | Scenario B (4 files) | Notes |
|----------|---------------------|---------------------|-------|
"""

    strategies = sorted(set(r["strategy"] for r in results))

    for strategy in strategies:
        a_result = next((r for r in results if r["strategy"] == strategy and "Scenario A" in r["scenario"]), None)
        b_result = next((r for r in results if r["strategy"] == strategy and "Scenario B" in r["scenario"]), None)

        a_calls = f"{a_result['write_file_calls']} calls" if a_result and a_result["success"] else "FAIL"
        b_calls = f"{b_result['write_file_calls']} calls" if b_result and b_result["success"] else "FAIL"

        # Determine notes
        notes = []
        if a_result and a_result["write_file_calls"] >= 3:
            notes.append("✅ A")
        if b_result and b_result["write_file_calls"] >= 4:
            notes.append("✅ B")

        notes_str = " ".join(notes) if notes else ""

        report += f"| {strategy} | {a_calls} | {b_calls} | {notes_str} |\n"

    # Find overall winner
    all_successful = [r for r in results if r["success"]]
    if all_successful:
        # Score: write_file_calls across both scenarios
        strategy_scores = {}
        for strategy in strategies:
            strategy_results = [r for r in all_successful if r["strategy"] == strategy]
            total_score = sum(r["write_file_calls"] for r in strategy_results)
            strategy_scores[strategy] = total_score

        winner = max(strategy_scores.items(), key=lambda x: x[1])
        winner_name, winner_score = winner

        report += f"""
## Winning Strategy: {winner_name}

**Total Score:** {winner_score} write_file calls across both scenarios

"""

        # Get the winning strategy object
        winner_obj = next(s for s in [
            Strategy1_Explicit(), Strategy2_FewShot(), Strategy3_Numbered(),
            Strategy4_Parallel(), Strategy5_Checklist(), Strategy6_Batch(),
            Strategy7_Array(), Strategy8_Atomic(), Strategy9_Complete(),
            Strategy10_Hybrid()
        ] if s.name == winner_name)

        # Show sample messages
        sample_messages = winner_obj.build_messages("Create file1.py, file2.py, file3.py")

        report += f"""### Prompt Text (Copy-Paste Ready)

**System Message:**
```
{sample_messages[0]["content"]}
```

"""

        if len(sample_messages) > 2:
            report += """**Note:** This strategy uses few-shot examples. See full implementation in test_qwen3_prompts.py

"""

        report += f"""### Why It Works

{winner_obj.description}

Based on test results:
"""

        winner_results = [r for r in results if r["strategy"] == winner_name]
        for r in winner_results:
            report += f"- {r['scenario']}: {r['write_file_calls']} write_file calls (expected: {3 if 'A' in r['scenario'] else 4})\n"

        report += """
### Recommended Implementation

**Approach:** One-shot with optimized prompt

**Code Changes Needed:**
1. Update `_build_planning_prompt()` in `src/workflow/task_planner.py`
2. Replace current system message with winning prompt text
3. Test with complex multi-file scenarios

**Example Integration:**
```python
def _build_planning_prompt(self, task_description: str, ...) -> List[Dict[str, str]]:
    system_message = '''
    # Copy winning prompt here
    '''

    return [
        {"role": "system", "content": system_message},
        {"role": "user", "content": task_description}
    ]
```

"""

    # Detailed logs
    report += """## Detailed Test Logs

"""

    for result in results:
        report += f"""### {result['strategy']} - {result['scenario']}

**Result:** {result['write_file_calls']} write_file calls

"""

        if result["success"] and result["tool_calls"]:
            report += """**Tool Calls:**
```json
"""
            for i, tc in enumerate(result["tool_calls"][:3], 1):  # Show first 3
                report += f"{json.dumps(tc, indent=2)}\n"

            if len(result["tool_calls"]) > 3:
                report += f"... and {len(result['tool_calls']) - 3} more\n"

            report += "```\n\n"
        elif not result["success"]:
            report += f"**Error:** {result.get('error', 'Unknown')}\n\n"

    # Conclusions
    report += """## Conclusions

### Key Findings

"""

    # Analyze patterns
    avg_by_strategy = {}
    for strategy in strategies:
        strategy_results = [r for r in results if r["strategy"] == strategy and r["success"]]
        if strategy_results:
            avg_calls = sum(r["write_file_calls"] for r in strategy_results) / len(strategy_results)
            avg_by_strategy[strategy] = avg_calls

    if avg_by_strategy:
        top_3 = sorted(avg_by_strategy.items(), key=lambda x: x[1], reverse=True)[:3]
        report += "**Top 3 Strategies by Average Performance:**\n"
        for strategy, avg in top_3:
            report += f"1. {strategy}: {avg:.1f} avg write_file calls\n"

    report += """
### Recommendations

1. **Immediate Action:** Implement winning strategy in TaskPlanner
2. **Testing:** Validate on production scenarios (weather CLI, web scraper)
3. **Monitoring:** Track tool call counts in production
4. **Iteration:** If issues persist, consider exploration mode (two-phase approach)

### Next Steps

1. Update `src/workflow/task_planner.py` with winning prompt
2. Run validation framework: `python -m src.validation.run easy_cli_weather`
3. Verify agent generates all 4 files (weather.py, test_weather.py, README.md, requirements.txt)
4. Document results in validation report

"""

    return report


def main():
    """Main execution function"""

    print("=" * 80)
    print("QWEN3-CODER-PLUS PROMPT STRATEGY TESTING")
    print("=" * 80)
    print("\nObjective: Find optimal prompt for multi-tool calling")
    print("Model: qwen3-coder-plus (DashScope API)")
    print("Scenarios: 2 (Simple 3-file + Complex 4-file)")
    print("Strategies: 10")
    print("\nStarting tests...\n")

    # Run all tests
    results = run_all_tests()

    # Generate report
    report = generate_report(results)

    # Save report
    report_path = "C:\\Vijay\\Learning\\AI\\ai-coding-agent\\QWEN3_PROMPT_STRATEGY.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"\n{'='*80}")
    print(f"TESTING COMPLETE")
    print(f"{'='*80}")
    print(f"\nReport saved to: {report_path}")
    print("\nSummary of results:")

    successful = [r for r in results if r["success"]]
    print(f"- Total tests: {len(results)}")
    print(f"- Successful: {len(successful)}")
    print(f"- Failed: {len(results) - len(successful)}")

    if successful:
        best = max(successful, key=lambda x: x["write_file_calls"])
        print(f"\nBest single result: {best['strategy']} on {best['scenario']}")
        print(f"  Generated: {best['write_file_calls']} write_file calls")


if __name__ == "__main__":
    main()
