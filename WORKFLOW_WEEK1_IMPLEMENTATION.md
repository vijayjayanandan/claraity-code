# Week 1 Implementation Guide - Workflow Foundation

**Goal:** Implement core workflow infrastructure (TaskAnalyzer, TaskPlanner, ExecutionEngine)
**Timeline:** 5-7 days
**Status:** Ready to Start

---

## 📋 Overview

This week we'll build the foundation:
```
User Request → TaskAnalyzer → TaskPlanner → ExecutionEngine → Response
```

**Deliverables:**
1. ✅ Task classification system
2. ✅ Plan generation with LLM
3. ✅ Execution engine with progress tracking
4. ✅ Integration with existing agent
5. ✅ Basic tests

---

## 🎯 Day 1-2: Task Analyzer

### File: `src/workflow/task_analyzer.py`

**Create this file:**

```python
"""Task analyzer for classifying and analyzing user requests."""

from enum import Enum
from typing import Dict, List, Any
from dataclasses import dataclass
import json


class TaskType(Enum):
    """Types of development tasks"""
    FEATURE = "feature"
    BUG_FIX = "bugfix"
    REFACTOR = "refactor"
    DOCUMENTATION = "docs"
    REVIEW = "review"
    DEBUG = "debug"
    EXPLAIN = "explain"
    SEARCH = "search"
    TEST = "test"


class TaskComplexity(Enum):
    """Estimated complexity levels"""
    TRIVIAL = 1
    SIMPLE = 2
    MODERATE = 3
    COMPLEX = 4
    VERY_COMPLEX = 5


@dataclass
class TaskAnalysis:
    """Result of analyzing a user request"""
    task_type: TaskType
    complexity: TaskComplexity
    requires_planning: bool
    requires_approval: bool
    estimated_files: int
    estimated_iterations: int
    requires_git: bool
    requires_tests: bool
    risk_level: str
    key_concepts: List[str]
    affected_systems: List[str]


class TaskAnalyzer:
    """Analyzes user requests to determine task characteristics"""

    def __init__(self, llm_backend):
        self.llm = llm_backend

    def analyze(self, user_request: str, context: Dict = None) -> TaskAnalysis:
        """
        Analyze user request to determine task characteristics.

        Args:
            user_request: User's request
            context: Optional conversation context

        Returns:
            TaskAnalysis with task characteristics
        """
        # Build analysis prompt
        analysis_prompt = self._build_analysis_prompt(user_request)

        # Get LLM response
        response = self.llm.generate(analysis_prompt)

        # Parse response
        try:
            return self._parse_analysis(response.content)
        except Exception as e:
            # Fallback to heuristic analysis
            print(f"Warning: LLM analysis failed ({e}), using heuristics")
            return self._heuristic_analysis(user_request)

    def _build_analysis_prompt(self, request: str) -> List[Dict]:
        """Build prompt for task analysis"""
        return [
            {"role": "system", "content": """You are a task analysis expert for a coding agent.
Analyze the user's request and classify it.

Respond in JSON format:
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

Request: "Refactor the memory system to use a database"
Response: {
  "task_type": "refactor",
  "complexity": 5,
  "requires_planning": true,
  "requires_approval": true,
  "estimated_files": 6,
  "estimated_iterations": 10,
  "requires_git": true,
  "requires_tests": true,
  "risk_level": "high",
  "key_concepts": ["memory", "database", "persistence"],
  "affected_systems": ["memory", "storage", "agent"]
}

Request: "Add a list_directory tool"
Response: {
  "task_type": "feature",
  "complexity": 2,
  "requires_planning": true,
  "requires_approval": false,
  "estimated_files": 2,
  "estimated_iterations": 4,
  "requires_git": true,
  "requires_tests": true,
  "risk_level": "low",
  "key_concepts": ["tools", "file_operations"],
  "affected_systems": ["tools"]
}"""},
            {"role": "user", "content": f"Analyze this request:\n{request}"}
        ]

    def _parse_analysis(self, response: str) -> TaskAnalysis:
        """Parse LLM response into TaskAnalysis"""
        # Extract JSON from response
        # LLM might include explanation before/after JSON
        import re

        # Find JSON block
        json_match = re.search(r'\{[\s\S]*\}', response)
        if not json_match:
            raise ValueError("No JSON found in response")

        data = json.loads(json_match.group(0))

        return TaskAnalysis(
            task_type=TaskType(data["task_type"]),
            complexity=TaskComplexity(data["complexity"]),
            requires_planning=data["requires_planning"],
            requires_approval=data["requires_approval"],
            estimated_files=data["estimated_files"],
            estimated_iterations=data["estimated_iterations"],
            requires_git=data["requires_git"],
            requires_tests=data["requires_tests"],
            risk_level=data["risk_level"],
            key_concepts=data.get("key_concepts", []),
            affected_systems=data.get("affected_systems", [])
        )

    def _heuristic_analysis(self, request: str) -> TaskAnalysis:
        """Fallback heuristic analysis if LLM fails"""
        request_lower = request.lower()

        # Determine task type
        if any(word in request_lower for word in ["explain", "what", "how", "why"]):
            task_type = TaskType.EXPLAIN
            complexity = TaskComplexity.TRIVIAL
        elif any(word in request_lower for word in ["add", "create", "implement", "new"]):
            task_type = TaskType.FEATURE
            complexity = TaskComplexity.MODERATE
        elif any(word in request_lower for word in ["fix", "bug", "error", "issue"]):
            task_type = TaskType.BUG_FIX
            complexity = TaskComplexity.SIMPLE
        elif any(word in request_lower for word in ["refactor", "restructure", "reorganize"]):
            task_type = TaskType.REFACTOR
            complexity = TaskComplexity.COMPLEX
        else:
            task_type = TaskType.FEATURE
            complexity = TaskComplexity.MODERATE

        return TaskAnalysis(
            task_type=task_type,
            complexity=complexity,
            requires_planning=complexity.value >= 3,
            requires_approval=complexity.value >= 4,
            estimated_files=complexity.value,
            estimated_iterations=complexity.value * 2,
            requires_git=task_type != TaskType.EXPLAIN,
            requires_tests=task_type in [TaskType.FEATURE, TaskType.BUG_FIX],
            risk_level="high" if complexity.value >= 4 else "medium" if complexity.value >= 3 else "low",
            key_concepts=[],
            affected_systems=[]
        )
```

### File: `src/workflow/__init__.py`

```python
"""Workflow management for the coding agent."""

from .task_analyzer import TaskAnalyzer, TaskAnalysis, TaskType, TaskComplexity

__all__ = [
    "TaskAnalyzer",
    "TaskAnalysis",
    "TaskType",
    "TaskComplexity",
]
```

### Test: `tests/workflow/test_task_analyzer.py`

```python
"""Tests for task analyzer."""

import pytest
from src.workflow.task_analyzer import TaskAnalyzer, TaskType, TaskComplexity
from src.llm import OllamaBackend, LLMConfig


@pytest.fixture
def llm_backend():
    """Create LLM backend for testing"""
    config = LLMConfig(
        backend_type="openai",
        model_name="qwen3-coder-plus",
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        context_window=32768
    )
    from src.llm import OpenAIBackend
    return OpenAIBackend(config, api_key_env="DASHSCOPE_API_KEY")


def test_analyze_simple_request(llm_backend):
    """Test analyzing a simple explanation request"""
    analyzer = TaskAnalyzer(llm_backend)

    analysis = analyzer.analyze("Explain how the memory system works")

    assert analysis.task_type == TaskType.EXPLAIN
    assert analysis.complexity.value <= 2
    assert not analysis.requires_approval
    assert analysis.risk_level == "low"


def test_analyze_complex_request(llm_backend):
    """Test analyzing a complex refactoring request"""
    analyzer = TaskAnalyzer(llm_backend)

    analysis = analyzer.analyze("Refactor the memory system to use Redis")

    assert analysis.task_type == TaskType.REFACTOR
    assert analysis.complexity.value >= 4
    assert analysis.requires_planning
    assert analysis.requires_approval
    assert analysis.risk_level in ["high", "medium"]


def test_heuristic_fallback():
    """Test heuristic analysis fallback"""
    # Create analyzer with broken LLM (will fallback to heuristics)
    analyzer = TaskAnalyzer(None)

    analysis = analyzer._heuristic_analysis("Add a new tool")

    assert analysis.task_type == TaskType.FEATURE
    assert isinstance(analysis.complexity, TaskComplexity)
```

### Integration Test:

```bash
# Create directory structure
mkdir -p src/workflow
mkdir -p tests/workflow

# Create files (copy code above)
# ... create task_analyzer.py, __init__.py, test_task_analyzer.py

# Run tests
python -m pytest tests/workflow/test_task_analyzer.py -v
```

---

## 🎯 Day 3-4: Task Planner

### File: `src/workflow/task_planner.py`

**Create this file** (see WORKFLOW_ARCHITECTURE.md lines 310-556 for full implementation)

Key points:
- Create `PlanStep` and `ExecutionPlan` dataclasses
- Implement `TaskPlanner.create_plan()` with LLM
- Add plan validation logic
- Add user-friendly plan formatting

### Test: `tests/workflow/test_task_planner.py`

```python
"""Tests for task planner."""

import pytest
from src.workflow.task_planner import TaskPlanner
from src.workflow.task_analyzer import TaskAnalyzer, TaskType, TaskComplexity


def test_create_simple_plan(llm_backend, memory_manager):
    """Test creating a simple plan"""
    planner = TaskPlanner(llm_backend, memory_manager)

    # Create mock analysis
    from src.workflow.task_analyzer import TaskAnalysis
    analysis = TaskAnalysis(
        task_type=TaskType.FEATURE,
        complexity=TaskComplexity.SIMPLE,
        requires_planning=True,
        requires_approval=False,
        estimated_files=1,
        estimated_iterations=3,
        requires_git=True,
        requires_tests=False,
        risk_level="low",
        key_concepts=["tools"],
        affected_systems=["tools"]
    )

    plan = planner.create_plan(
        "Add a list_directory tool",
        analysis,
        context={}
    )

    assert len(plan.steps) >= 2
    assert plan.overall_risk in ["low", "medium", "high"]
    assert all(step.id > 0 for step in plan.steps)


def test_plan_validation():
    """Test plan validation catches errors"""
    planner = TaskPlanner(None, None)

    # Create plan with circular dependency
    from src.workflow.task_planner import ExecutionPlan, PlanStep
    bad_plan = ExecutionPlan(
        task_description="test",
        task_type=TaskType.FEATURE,
        steps=[
            PlanStep(id=1, description="step 1", action_type="read", dependencies=[2]),
            PlanStep(id=2, description="step 2", action_type="read", dependencies=[1])
        ],
        total_estimated_time="1 min",
        overall_risk="low",
        requires_approval=False
    )

    with pytest.raises(ValueError):
        planner._validate_plan(bad_plan)
```

---

## 🎯 Day 5: Execution Engine

### File: `src/workflow/execution_engine.py`

**Create this file** (see WORKFLOW_ARCHITECTURE.md lines 661-877 for full implementation)

Key points:
- Implement `ExecutionEngine.execute_plan()`
- Add progress callback support
- Handle step dependencies
- Generate execution summary

---

## 🎯 Day 6: Integration with Agent

### Modifications to `src/core/agent.py`:

```python
# Add imports at top
from src.workflow import TaskAnalyzer, TaskPlanner
from src.workflow.execution_engine import ExecutionEngine

class CodingAgent:
    def __init__(self, ...):
        # ... existing init ...

        # NEW: Add workflow components
        self.task_analyzer = TaskAnalyzer(self.llm)
        self.task_planner = TaskPlanner(self.llm, self.memory)
        self.execution_engine = ExecutionEngine(
            tool_executor=self.tool_executor,
            llm_backend=self.llm,
            progress_callback=print  # Simple progress for now
        )

    def execute_task(self, task_description: str, ...) -> AgentResponse:
        """
        Execute task with workflow support.

        MODIFIED to include workflow phases.
        """
        print(f"\n{'='*60}")
        print(f"📋 Task: {task_description}")
        print(f"{'='*60}\n")

        # Phase 1: Analyze task
        print("🔍 Analyzing task...")
        task_analysis = self.task_analyzer.analyze(task_description)

        print(f"Task Type: {task_analysis.task_type.value}")
        print(f"Complexity: {task_analysis.complexity.value}/5")
        print(f"Risk Level: {task_analysis.risk_level}")
        print(f"Requires Planning: {task_analysis.requires_planning}")

        # Phase 2: Create plan (if needed)
        if task_analysis.requires_planning:
            print(f"\n📝 Creating execution plan...")
            plan = self.task_planner.create_plan(
                task_description,
                task_analysis,
                context={}
            )

            # Show plan
            print(self.task_planner.format_plan_for_user(plan))

            # Get approval (if needed)
            if task_analysis.requires_approval:
                print(f"\n⚠️  This is a high-risk operation requiring approval.")
                response = input("Approve this plan? (yes/no): ").lower()
                if response not in ['yes', 'y']:
                    return AgentResponse(
                        content="Plan rejected by user",
                        metadata={"status": "rejected"}
                    )

            # Phase 3: Execute plan
            print(f"\n⚙️  Executing plan...")
            execution_result = self.execution_engine.execute_plan(plan)

            # Phase 4: Report
            print(f"\n{'='*60}")
            print("📊 Execution Summary")
            print(f"{'='*60}")
            print(execution_result.summary)

            response_content = execution_result.summary
            metadata = {
                "task_analysis": task_analysis,
                "plan_created": True,
                "steps_executed": len(execution_result.step_results),
                "success": execution_result.success
            }
        else:
            # Simple task - use existing flow
            print(f"\n⚡ Executing directly (no planning needed)...")

            # Build context as before
            context = self.context_builder.build_context(
                user_query=task_description,
                task_type=task_type,
                language=language,
                use_rag=use_rag and len(self.indexed_chunks) > 0,
                available_chunks=self.indexed_chunks if use_rag else None,
            )

            # Execute with tool calling loop
            response_content = self._execute_with_tools(
                context=context,
                max_iterations=3,
                stream=stream
            )

            metadata = {
                "task_analysis": task_analysis,
                "plan_created": False
            }

        # Add to memory
        self.memory.add_user_message(task_description)
        self.memory.add_assistant_message(response_content)

        return AgentResponse(
            content=response_content,
            metadata=metadata
        )
```

---

## 🎯 Day 7: Testing & Polish

### Integration Test: `tests/test_workflow_integration.py`

```python
"""Integration tests for workflow system."""

import pytest
from src.core.agent import CodingAgent


def test_simple_workflow_integration():
    """Test complete workflow: analyze → plan → execute"""
    agent = CodingAgent(
        backend="openai",
        model_name="qwen3-coder-plus",
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        context_window=32768,
        api_key_env="DASHSCOPE_API_KEY"
    )

    # Simple task that should create a plan
    response = agent.execute_task(
        "Create a test file at tests/example_test.py with a simple test function"
    )

    assert response.metadata["plan_created"] == True
    assert response.metadata["success"] == True


def test_explain_workflow():
    """Test explanation task (no planning)"""
    agent = CodingAgent(...)

    response = agent.execute_task(
        "Explain what the CodingAgent class does"
    )

    assert response.metadata["plan_created"] == False
    assert "CodingAgent" in response.content


def test_high_risk_approval():
    """Test high-risk task requires approval"""
    # Would need mocking for automated testing
    pass
```

### Manual Testing:

```bash
# Test 1: Simple explanation (no planning)
python -m src.cli chat
> Explain how the memory system works

# Test 2: Feature implementation (with planning)
python -m src.cli chat
> Add a new tool called ExampleTool that prints hello world

# Test 3: View plan details
# Should show: task analysis, execution plan with steps, approval prompt (if high risk)
```

---

## 📊 Week 1 Checklist

### Day 1-2: Task Analyzer
- [ ] Create `src/workflow/` directory
- [ ] Implement `TaskAnalyzer` class
- [ ] Add `TaskType` and `TaskComplexity` enums
- [ ] Implement LLM-based analysis
- [ ] Add heuristic fallback
- [ ] Write unit tests
- [ ] Test with real requests

### Day 3-4: Task Planner
- [ ] Implement `PlanStep` and `ExecutionPlan` dataclasses
- [ ] Implement `TaskPlanner` class
- [ ] Add LLM-based plan generation
- [ ] Implement plan validation
- [ ] Add user-friendly formatting
- [ ] Write unit tests
- [ ] Test plan generation

### Day 5: Execution Engine
- [ ] Implement `ExecutionEngine` class
- [ ] Add step-by-step execution
- [ ] Handle dependencies
- [ ] Add progress callbacks
- [ ] Generate summaries
- [ ] Write unit tests

### Day 6: Integration
- [ ] Modify `agent.py` to use workflow
- [ ] Update `execute_task()` method
- [ ] Add approval flow
- [ ] Test integration
- [ ] Fix any issues

### Day 7: Testing & Polish
- [ ] Write integration tests
- [ ] Manual testing with CLI
- [ ] Fix bugs discovered
- [ ] Update documentation
- [ ] Prepare for Week 2

---

## 🚀 Quick Start Commands

```bash
# Day 1: Setup
mkdir -p src/workflow tests/workflow

# Day 2: Create task analyzer
# (Copy code from above)
python -m pytest tests/workflow/test_task_analyzer.py

# Day 4: Test planner
python -m pytest tests/workflow/test_task_planner.py

# Day 5: Test execution engine
python -m pytest tests/workflow/test_execution_engine.py

# Day 7: Integration test
python -m pytest tests/test_workflow_integration.py

# Manual testing
python -m src.cli chat
```

---

## 🎯 Success Criteria for Week 1

**Must Have:**
- ✅ Task analyzer classifies requests correctly (80%+ accuracy)
- ✅ Planner generates reasonable plans for moderate tasks
- ✅ Execution engine runs plans step-by-step
- ✅ Integration with existing agent works
- ✅ Basic tests pass

**Nice to Have:**
- Progress bars for long operations
- Better error messages
- Plan editing/refinement

**Out of Scope for Week 1:**
- Verification layer (Week 2)
- Error recovery (Week 3)
- Advanced tools (Week 2)

---

## 📝 Notes & Tips

**Tip 1: Start Simple**
- Don't over-engineer in Week 1
- Focus on getting the pipeline working
- Optimize later

**Tip 2: Test Continuously**
- Test each component as you build
- Use manual testing liberally
- Integration test early

**Tip 3: Use LLM for Planning**
- LLM is good at generating structured plans
- JSON mode helps with parsing
- Heuristics as fallback

**Tip 4: Progress Visibility**
- Print liberally during execution
- Users need to see progress
- Silent agents are scary

---

**Week 1 Goal:** Have a working workflow pipeline that takes requests, creates plans, and executes them. Polish and optimization can wait!

**Ready to Start?** Begin with Day 1 - Task Analyzer!
