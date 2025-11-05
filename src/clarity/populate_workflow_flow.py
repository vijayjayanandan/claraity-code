"""
Populate Workflow Execution Flow

This script documents the complete Workflow Execution flow - the most complex
execution path in the AI Coding Agent. This flow is triggered when users request
complex tasks like implementing features, refactoring code, or debugging.

Based on code analysis from EXECUTION_FLOWS.md and actual implementation.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from clarity.core.database.clarity_db import ClarityDB


def populate_workflow_flow():
    """Populate the Workflow Execution flow with hierarchical steps"""

    db = ClarityDB(".clarity/ai-coding-agent.db")

    # Clear existing flow data if it exists
    flow_id = "WORKFLOW_EXECUTION_FLOW"
    with db._get_cursor() as cursor:
        cursor.execute("DELETE FROM flow_steps WHERE flow_id = ?", (flow_id,))
        cursor.execute("DELETE FROM execution_flows WHERE id = ?", (flow_id,))

    print(f"✓ Cleared existing flow data")

    # Create the flow
    db.add_flow(
        flow_id=flow_id,
        name="Workflow Execution Flow",
        description="Complete execution path for complex tasks (implement, refactor, debug, test). "
                    "Includes analysis, planning, approval, execution, and verification.",
        trigger="User requests complex task (implement/refactor/debug/test keywords)",
        flow_type="user-facing",
        complexity="complex",
        is_primary=True
    )

    print(f"✓ Created flow: {flow_id}")

    # ====================
    # HIGH-LEVEL STEPS (Level 0)
    # ====================

    steps_data = [
        # Step 1: Entry Point
        {
            "step_id": "STEP_1_USER_INPUT",
            "sequence": 0,
            "step_type": "normal",
            "title": "User Input → CLI",
            "description": "User types a complex task in the CLI (e.g., 'Implement feature X')",
            "component_id": None,  # CLI not documented as component
            "file_path": "src/cli.py",
            "line_start": 131,
            "line_end": 131,
            "function_name": "agent.chat(user_input)",
            "is_critical": True,
            "notes": "Entry point for all user interactions"
        },
        # Step 2: Agent Routes
        {
            "step_id": "STEP_2_AGENT_ROUTING",
            "sequence": 1,
            "step_type": "normal",
            "title": "Agent Routes Request",
            "description": "CodingAgent receives input, infers task type, and prepares for execution",
            "component_id": "CODINGAGENT",
            "file_path": "src/core/agent.py",
            "line_start": 916,
            "line_end": 934,
            "function_name": "chat() → execute_task()",
            "is_critical": True
        },
        # Step 3: Decision Point
        {
            "step_id": "STEP_3_WORKFLOW_DECISION",
            "sequence": 2,
            "step_type": "decision",
            "title": "Decision: Workflow or Direct?",
            "description": "Agent determines if this requires complex workflow or simple direct execution",
            "component_id": "CODINGAGENT",
            "file_path": "src/core/agent.py",
            "line_start": 467,
            "line_end": 514,
            "function_name": "_should_use_workflow()",
            "decision_question": "Does this task require structured workflow (analysis → plan → execute)?",
            "decision_logic": "Checks task type (implement/refactor/debug) and keywords (create/add/fix/modify)",
            "branches": [
                {"label": "Yes → Workflow", "target_step_id": "STEP_4_WORKFLOW_EXEC"},
                {"label": "No → Direct", "target_step_id": None, "notes": "Goes to Direct Execution Flow"}
            ],
            "is_critical": True,
            "notes": "This is the key decision point that routes to workflow execution"
        },
        # Step 4: Execute with Workflow
        {
            "step_id": "STEP_4_WORKFLOW_EXEC",
            "sequence": 3,
            "step_type": "normal",
            "title": "Execute with Workflow",
            "description": "Enters structured workflow: Analyze → Plan → Approve → Execute → Verify",
            "component_id": "CODINGAGENT",
            "file_path": "src/core/agent.py",
            "line_start": 555,
            "line_end": 641,
            "function_name": "_execute_with_workflow()",
            "is_critical": True,
            "notes": "Orchestrates 6 major substeps below"
        },
        # Step 5: Return Response
        {
            "step_id": "STEP_5_RETURN_RESPONSE",
            "sequence": 4,
            "step_type": "end",
            "title": "Return Response to User",
            "description": "Generate success/failure response and return to user via CLI",
            "component_id": "CODINGAGENT",
            "file_path": "src/core/agent.py",
            "line_start": 643,
            "line_end": 698,
            "function_name": "_generate_success_response() or _generate_failure_response()",
            "is_critical": True
        }
    ]

    # Add high-level steps
    for step_data in steps_data:
        db.add_flow_step(
            flow_id=flow_id,
            level=0,
            **step_data
        )

    print(f"✓ Added {len(steps_data)} high-level steps")

    # ====================
    # DETAILED SUBSTEPS (Level 1) for Step 4
    # ====================

    substeps_data = [
        # Substep 4.1: Analyze
        {
            "step_id": "SUBSTEP_4_1_ANALYZE",
            "parent_step_id": "STEP_4_WORKFLOW_EXEC",
            "sequence": 0,
            "step_type": "normal",
            "title": "Analyze Task",
            "description": "TaskAnalyzer determines task complexity, risk level, and affected systems",
            "component_id": "TASKANALYZER",
            "file_path": "src/workflow/task_analyzer.py",
            "line_start": 1,
            "line_end": 150,
            "function_name": "analyze()",
            "is_critical": True,
            "notes": "Classifies as: LOW/MEDIUM/HIGH complexity, Determines files affected"
        },
        # Substep 4.2: Plan
        {
            "step_id": "SUBSTEP_4_2_PLAN",
            "parent_step_id": "STEP_4_WORKFLOW_EXEC",
            "sequence": 1,
            "step_type": "normal",
            "title": "Create Execution Plan",
            "description": "TaskPlanner generates detailed step-by-step execution plan with tools and success criteria",
            "component_id": "TASKPLANNER",
            "file_path": "src/workflow/task_planner.py",
            "line_start": 1,
            "line_end": 200,
            "function_name": "create_plan()",
            "is_critical": True,
            "notes": "Generates steps, tool assignments, time estimates, success criteria"
        },
        # Substep 4.3: Approval
        {
            "step_id": "SUBSTEP_4_3_APPROVAL",
            "parent_step_id": "STEP_4_WORKFLOW_EXEC",
            "sequence": 2,
            "step_type": "decision",
            "title": "Get User Approval",
            "description": "PermissionManager checks mode (plan/normal/auto) and requests approval for risky changes",
            "component_id": "PERMISSIONMANAGER",
            "file_path": "src/workflow/permission_manager.py",
            "line_start": 1,
            "line_end": 100,
            "function_name": "get_approval()",
            "decision_question": "Should we ask user for approval?",
            "decision_logic": "Mode=plan → Always ask, Mode=normal → Ask if high risk, Mode=auto → Never ask",
            "branches": [
                {"label": "Approved → Continue", "target_step_id": "SUBSTEP_4_4_EXECUTE"},
                {"label": "Rejected → Abort", "target_step_id": "STEP_5_RETURN_RESPONSE"}
            ],
            "is_critical": True
        },
        # Substep 4.4: Execute
        {
            "step_id": "SUBSTEP_4_4_EXECUTE",
            "parent_step_id": "STEP_4_WORKFLOW_EXEC",
            "sequence": 3,
            "step_type": "normal",
            "title": "Execute Plan Steps",
            "description": "ExecutionEngine executes each step sequentially, calling tools as needed",
            "component_id": "EXECUTIONENGINE",
            "file_path": "src/workflow/execution_engine.py",
            "line_start": 1,
            "line_end": 459,
            "function_name": "execute_plan()",
            "is_critical": True,
            "notes": "Calls ToolExecutor for each tool, tracks progress, handles errors"
        },
        # Substep 4.5: Verify
        {
            "step_id": "SUBSTEP_4_5_VERIFY",
            "parent_step_id": "STEP_4_WORKFLOW_EXEC",
            "sequence": 4,
            "step_type": "normal",
            "title": "Verify Results",
            "description": "VerificationLayer checks if execution succeeded (3-tier: basic, tool-based, LLM-based)",
            "component_id": "VERIFICATIONLAYER",
            "file_path": "src/workflow/verification_layer.py",
            "line_start": 1,
            "line_end": 631,
            "function_name": "verify()",
            "is_critical": True,
            "notes": "Tier 1: Basic checks, Tier 2: Tool outputs, Tier 3: LLM validation"
        },
        # Substep 4.6: Generate Response
        {
            "step_id": "SUBSTEP_4_6_RESPONSE",
            "parent_step_id": "STEP_4_WORKFLOW_EXEC",
            "sequence": 5,
            "step_type": "normal",
            "title": "Generate Success/Failure Response",
            "description": "Create detailed response with what was done, verification results, and next steps",
            "component_id": "CODINGAGENT",
            "file_path": "src/core/agent.py",
            "line_start": 643,
            "line_end": 698,
            "function_name": "_generate_success_response() or _generate_failure_response()",
            "is_critical": False
        }
    ]

    # Add substeps
    for substep_data in substeps_data:
        db.add_flow_step(
            flow_id=flow_id,
            level=1,
            **substep_data
        )

    print(f"✓ Added {len(substeps_data)} detailed substeps")

    # ====================
    # DEEPER SUBSTEPS (Level 2) for Execute Step
    # ====================

    execute_substeps = [
        # Tool execution loop
        {
            "step_id": "SUBSTEP_4_4_1_TOOL_EXEC",
            "parent_step_id": "SUBSTEP_4_4_EXECUTE",
            "sequence": 0,
            "step_type": "loop",
            "title": "For Each Step: Execute Tools",
            "description": "ToolExecutor executes individual tools (read_file, write_file, edit_file, etc.)",
            "component_id": "TOOLEXECUTOR",
            "file_path": "src/tools/base.py",
            "line_start": 1,
            "line_end": 100,
            "function_name": "execute_tool()",
            "notes": "Loops through plan steps, executes tools, collects results"
        },
        # Memory update
        {
            "step_id": "SUBSTEP_4_4_2_MEMORY",
            "parent_step_id": "SUBSTEP_4_4_EXECUTE",
            "sequence": 1,
            "step_type": "normal",
            "title": "Update Memory Context",
            "description": "Store tool results and execution progress in WorkingMemory",
            "component_id": "MEMORYMANAGER",
            "file_path": "src/memory/memory_manager.py",
            "line_start": 1,
            "line_end": 200,
            "function_name": "add_to_working_memory()",
            "notes": "Keeps context for next steps and future reference"
        },
        # Error handling
        {
            "step_id": "SUBSTEP_4_4_3_ERROR",
            "parent_step_id": "SUBSTEP_4_4_EXECUTE",
            "sequence": 2,
            "step_type": "decision",
            "title": "Handle Errors",
            "description": "If tool fails, decide whether to retry, skip, or abort",
            "component_id": "EXECUTIONENGINE",
            "file_path": "src/workflow/execution_engine.py",
            "line_start": 300,
            "line_end": 350,
            "function_name": "_handle_step_error()",
            "decision_question": "Can we continue after this error?",
            "decision_logic": "Check if step is critical, if retryable, if alternative exists",
            "branches": [
                {"label": "Retry → Loop back", "target_step_id": "SUBSTEP_4_4_1_TOOL_EXEC"},
                {"label": "Skip → Continue", "target_step_id": "SUBSTEP_4_5_VERIFY"},
                {"label": "Abort → End", "target_step_id": "STEP_5_RETURN_RESPONSE"}
            ]
        }
    ]

    # Add deeper substeps
    for substep_data in execute_substeps:
        db.add_flow_step(
            flow_id=flow_id,
            level=2,
            **substep_data
        )

    print(f"✓ Added {len(execute_substeps)} deeper substeps")

    print("\n✅ Workflow Execution Flow populated successfully!")
    print(f"   - 1 flow")
    print(f"   - 5 high-level steps")
    print(f"   - 6 detailed substeps")
    print(f"   - 3 deeper substeps")
    print(f"   - Total: 14 steps across 3 levels")

    db.close()


if __name__ == "__main__":
    populate_workflow_flow()
