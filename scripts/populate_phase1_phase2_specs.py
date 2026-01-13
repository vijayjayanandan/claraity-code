#!/usr/bin/env python3
"""
Populate Phase 1 & Phase 2 implementation specs into ClarAIty DB.

This script adds method signatures and acceptance criteria for:
- LONG_RUNNING_CONTROLLER (Phase 1)
- CHECKPOINT_MANAGER (Phase 1)
- ERROR_RECOVERY_SYSTEM (Phase 2)
- META_REASONING_ENGINE (Phase 2)
- SMART_CONTEXT_LOADER (Phase 2)

Source: PHASE1_PHASE2_IMPLEMENTATION_SPECS.md
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.tools.clarity_tools import add_method, add_acceptance_criterion


def populate_long_running_controller():
    """Populate LONG_RUNNING_CONTROLLER specs."""
    component_id = "LONG_RUNNING_CONTROLLER"
    print(f"\n[POPULATING] {component_id}")

    # Methods (8)
    methods = [
        {
            "method_name": "__init__",
            "signature": "__init__(self, agent, checkpoint_interval_seconds: int = 600, max_time_hours: Optional[float] = None, progress_callback: Optional[Callable[[ExecutionProgress], None]] = None)",
            "description": "Initialize the long-running execution controller",
            "parameters": [
                {"name": "agent", "type": "CodingAgent", "description": "The agent instance to control", "required": True},
                {"name": "checkpoint_interval_seconds", "type": "int", "description": "How often to save checkpoints in seconds", "required": False, "default": "600"},
                {"name": "max_time_hours", "type": "Optional[float]", "description": "Maximum execution time in hours, None for unlimited", "required": False, "default": "None"},
                {"name": "progress_callback", "type": "Optional[Callable]", "description": "Callback function for progress updates", "required": False, "default": "None"}
            ],
            "return_type": "None",
            "raises": [],
            "example_usage": 'controller = LongRunningController(agent=my_agent, max_time_hours=2.0, progress_callback=lambda p: print(p.format_progress()))'
        },
        {
            "method_name": "execute_autonomous",
            "signature": "execute_autonomous(self, task_description: str, initial_estimate_iterations: int = 50) -> Dict[str, Any]",
            "description": "Execute task autonomously until complete or stuck",
            "parameters": [
                {"name": "task_description", "type": "str", "description": "What to build/fix", "required": True},
                {"name": "initial_estimate_iterations", "type": "int", "description": "Initial guess for progress bar", "required": False, "default": "50"}
            ],
            "return_type": "Dict[str, Any]",
            "raises": [],
            "example_usage": 'result = controller.execute_autonomous("Build a REST API for user management", initial_estimate_iterations=100)\nprint(result["status"], result["success"])'
        },
        {
            "method_name": "_should_stop",
            "signature": "_should_stop(self) -> bool",
            "description": "Check if execution should stop based on time limit or stuck detection",
            "parameters": [],
            "return_type": "bool",
            "raises": [],
            "example_usage": "if self._should_stop():\n    break"
        },
        {
            "method_name": "_should_checkpoint",
            "signature": "_should_checkpoint(self) -> bool",
            "description": "Check if checkpoint should be saved based on elapsed time",
            "parameters": [],
            "return_type": "bool",
            "raises": [],
            "example_usage": "if self._should_checkpoint():\n    self._save_checkpoint()"
        },
        {
            "method_name": "_save_checkpoint",
            "signature": "_save_checkpoint(self) -> None",
            "description": "Save execution checkpoint to disk",
            "parameters": [],
            "return_type": "None",
            "raises": [],
            "example_usage": 'self._save_checkpoint()\nprint(f"[CHECKPOINT] Saved at iteration {self.progress.iteration}")'
        },
        {
            "method_name": "_handle_error",
            "signature": "_handle_error(self, error: Exception) -> None",
            "description": "Handle execution error by recording it and updating phase",
            "parameters": [
                {"name": "error", "type": "Exception", "description": "The error that occurred", "required": True}
            ],
            "return_type": "None",
            "raises": [],
            "example_usage": "try:\n    risky_operation()\nexcept Exception as e:\n    self._handle_error(e)"
        },
        {
            "method_name": "_handle_stuck_state",
            "signature": "_handle_stuck_state(self) -> None",
            "description": "Handle stuck execution state by requesting human assistance",
            "parameters": [],
            "return_type": "None",
            "raises": [],
            "example_usage": "if self.progress.is_stuck():\n    self._handle_stuck_state()"
        },
        {
            "method_name": "_generate_final_report",
            "signature": "_generate_final_report(self) -> Dict[str, Any]",
            "description": "Generate final execution report with metrics",
            "parameters": [],
            "return_type": "Dict[str, Any]",
            "raises": [],
            "example_usage": 'report = self._generate_final_report()\n# Returns: {"status": "done", "iterations": 42, "success": True, ...}'
        }
    ]

    for method in methods:
        add_method(component_id=component_id, **method)
        print(f"  [OK] {method['method_name']}")

    # Acceptance Criteria (5)
    criteria = [
        {
            "criteria_type": "functionality",
            "description": "Agent must run unlimited iterations with stuck detection (no hard iteration cap)",
            "target_value": "100+ iterations without artificial limits",
            "validation_method": "Run long-running task and verify no iteration cap error",
            "priority": "required"
        },
        {
            "criteria_type": "functionality",
            "description": "Display progress every iteration with phase, time, files, tests",
            "target_value": "Progress displayed every iteration with accurate metrics",
            "validation_method": "Manual verification of progress output format",
            "priority": "required"
        },
        {
            "criteria_type": "functionality",
            "description": "Automatically save checkpoints every 10 minutes",
            "target_value": "Checkpoints saved at configured interval",
            "validation_method": "Run for 30 min, verify 3 checkpoints created",
            "priority": "required"
        },
        {
            "criteria_type": "functionality",
            "description": "Detect stuck patterns (same phase 10+ iterations, repeated errors 3+)",
            "target_value": "Correctly identify stuck patterns with 85%+ accuracy",
            "validation_method": "Create artificial stuck scenarios, verify detection",
            "priority": "required"
        },
        {
            "criteria_type": "integration",
            "description": "Integration with CodingAgent and CheckpointManager",
            "target_value": "Works with real agent and checkpoint system",
            "validation_method": "End-to-end test with real LLM and checkpoints",
            "priority": "required"
        }
    ]

    for criterion in criteria:
        add_acceptance_criterion(component_id=component_id, **criterion)
        print(f"  [OK] Criterion: {criterion['description'][:50]}...")


def populate_checkpoint_manager():
    """Populate CHECKPOINT_MANAGER specs."""
    component_id = "CHECKPOINT_MANAGER"
    print(f"\n[POPULATING] {component_id}")

    # Methods (6)
    methods = [
        {
            "method_name": "__init__",
            "signature": "__init__(self, checkpoint_dir: Path, max_checkpoints: int = 10)",
            "description": "Initialize checkpoint manager with storage directory",
            "parameters": [
                {"name": "checkpoint_dir", "type": "Path", "description": "Directory to store checkpoints", "required": True},
                {"name": "max_checkpoints", "type": "int", "description": "Maximum number of checkpoints to keep", "required": False, "default": "10"}
            ],
            "return_type": "None",
            "raises": [],
            "example_usage": 'manager = CheckpointManager(checkpoint_dir=Path(".checkpoints"), max_checkpoints=5)'
        },
        {
            "method_name": "save_checkpoint",
            "signature": "save_checkpoint(self, agent, execution_progress, task_description: str) -> str",
            "description": "Save current execution state to checkpoint file",
            "parameters": [
                {"name": "agent", "type": "CodingAgent", "description": "Agent instance with current state", "required": True},
                {"name": "execution_progress", "type": "ExecutionProgress", "description": "Progress tracker", "required": True},
                {"name": "task_description", "type": "str", "description": "Original task description", "required": True}
            ],
            "return_type": "str",
            "raises": [],
            "example_usage": 'checkpoint_id = manager.save_checkpoint(agent=my_agent, execution_progress=controller.progress, task_description="Build REST API")\nprint(f"Saved: {checkpoint_id}")'
        },
        {
            "method_name": "load_checkpoint",
            "signature": "load_checkpoint(self, checkpoint_id: str) -> ExecutionCheckpoint",
            "description": "Load checkpoint from disk by ID",
            "parameters": [
                {"name": "checkpoint_id", "type": "str", "description": "Checkpoint to load (e.g., checkpoint_20250113_143022)", "required": True}
            ],
            "return_type": "ExecutionCheckpoint",
            "raises": ["FileNotFoundError"],
            "example_usage": 'try:\n    checkpoint = manager.load_checkpoint("checkpoint_20250113_143022")\n    print(f"Loaded checkpoint from iteration {checkpoint.iteration}")\nexcept FileNotFoundError:\n    print("Checkpoint not found")'
        },
        {
            "method_name": "restore_to_agent",
            "signature": "restore_to_agent(self, checkpoint: ExecutionCheckpoint, agent) -> None",
            "description": "Restore checkpoint state into agent (memory, context, tool history)",
            "parameters": [
                {"name": "checkpoint", "type": "ExecutionCheckpoint", "description": "Checkpoint to restore", "required": True},
                {"name": "agent", "type": "CodingAgent", "description": "Agent to restore state into", "required": True}
            ],
            "return_type": "None",
            "raises": [],
            "example_usage": 'checkpoint = manager.load_checkpoint("checkpoint_20250113_143022")\nmanager.restore_to_agent(checkpoint, my_agent)\nprint(f"Restored from iteration {checkpoint.iteration}")'
        },
        {
            "method_name": "list_checkpoints",
            "signature": "list_checkpoints(self) -> List[CheckpointMetadata]",
            "description": "List all available checkpoints with metadata",
            "parameters": [],
            "return_type": "List[CheckpointMetadata]",
            "raises": [],
            "example_usage": 'checkpoints = manager.list_checkpoints()\nfor cp in checkpoints:\n    print(f"{cp.checkpoint_id}: {cp.task_description} ({cp.iteration} iterations)")'
        },
        {
            "method_name": "_cleanup_old_checkpoints",
            "signature": "_cleanup_old_checkpoints(self) -> None",
            "description": "Keep only the N most recent checkpoints, delete older ones",
            "parameters": [],
            "return_type": "None",
            "raises": [],
            "example_usage": "# Called automatically after save_checkpoint\nself._cleanup_old_checkpoints()"
        }
    ]

    for method in methods:
        add_method(component_id=component_id, **method)
        print(f"  [OK] {method['method_name']}")

    # Acceptance Criteria (5)
    criteria = [
        {
            "criteria_type": "functionality",
            "description": "Successfully save complete execution state to JSON file",
            "target_value": "All state (memory, progress, tool history) saved correctly",
            "validation_method": "Save checkpoint, verify JSON contains all required fields",
            "priority": "required"
        },
        {
            "criteria_type": "functionality",
            "description": "Restore execution state with <5% context loss",
            "target_value": "95%+ of state restored accurately",
            "validation_method": "Save checkpoint, restore, compare state before/after",
            "priority": "required"
        },
        {
            "criteria_type": "integration",
            "description": "Resume work after crashes or restarts from checkpoint",
            "target_value": "Can continue execution from any saved checkpoint",
            "validation_method": "Run task, stop mid-execution, restart and resume",
            "priority": "required"
        },
        {
            "criteria_type": "functionality",
            "description": "Automatically delete old checkpoints keeping only N most recent",
            "target_value": "No more than max_checkpoints files in directory",
            "validation_method": "Create 15 checkpoints with max=10, verify only 10 remain",
            "priority": "required"
        },
        {
            "criteria_type": "test_coverage",
            "description": "Comprehensive unit tests for all checkpoint operations",
            "target_value": "90%+ test coverage",
            "validation_method": "pytest tests/test_checkpoint_manager.py --cov",
            "priority": "required"
        }
    ]

    for criterion in criteria:
        add_acceptance_criterion(component_id=component_id, **criterion)
        print(f"  [OK] Criterion: {criterion['description'][:50]}...")


def main():
    """Populate all Phase 1 & Phase 2 specs."""
    print("=" * 80)
    print("POPULATING PHASE 1 & PHASE 2 IMPLEMENTATION SPECS")
    print("=" * 80)

    # Phase 1
    print("\n[PHASE 1] Long-Running Execution & Checkpoints")
    populate_long_running_controller()
    populate_checkpoint_manager()

    # Phase 2 (TODO: Add remaining components)
    print("\n[PHASE 2] Error Recovery, Meta-Reasoning, Smart Context")
    print("\n[TODO] Add ERROR_RECOVERY_SYSTEM specs")
    print("[TODO] Add META_REASONING_ENGINE specs")
    print("[TODO] Add SMART_CONTEXT_LOADER specs")

    print("\n" + "=" * 80)
    print("POPULATION COMPLETE")
    print("=" * 80)
    print("\nNext steps:")
    print("1. Verify population: Run verification script from PHASE1_PHASE2_QUICK_REFERENCE.md")
    print("2. Test workflow: Call get_implementation_spec('LONG_RUNNING_CONTROLLER')")
    print("3. Start implementation: Begin Phase 1 with LONG_RUNNING_CONTROLLER")


if __name__ == "__main__":
    main()
