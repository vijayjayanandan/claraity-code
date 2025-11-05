# Agentic Workflow Architecture - Comprehensive Design

**Date:** 2025-10-15
**Status:** Architecture Phase - Ultrathink Deep Research
**Goal:** Transform agent from basic tool executor to production-grade coding assistant

---

## 🔬 Research Foundation: Modern Coding Agent Patterns

### Analyzed Agents:
1. **Cursor** - Fast code changes with inline suggestions
2. **Claude Code** - Multi-step planning with verification
3. **Aider** - Git-aware with atomic commits
4. **Devin** - Autonomous multi-file refactoring
5. **GitHub Copilot Workspace** - Task decomposition with review

### Common Patterns Identified:

#### Pattern 1: **Plan-Execute-Verify Loop**
```
User Request → Plan Generation → User Approval → Execute → Verify → Report
```
- Used by: Claude Code, Devin, Copilot Workspace
- **Why:** Prevents premature execution, allows user control
- **Key:** Planning shows reasoning, builds trust

#### Pattern 2: **Progressive Disclosure**
```
High-Level Plan → Detailed Steps → Individual Actions → Results
```
- Used by: All modern agents
- **Why:** Users need visibility into agent thinking
- **Key:** Show what you're doing as you do it

#### Pattern 3: **Atomic Operations with Rollback**
```
Each change is: Isolated → Tested → Committable → Reversible
```
- Used by: Aider, Claude Code
- **Why:** Safety - users can undo mistakes
- **Key:** Git integration for change tracking

#### Pattern 4: **Context-Aware Tool Selection**
```
Analyze Task → Select Relevant Tools → Execute Minimal Set → Iterate
```
- Used by: Cursor, Claude Code
- **Why:** Efficiency - don't use unnecessary tools
- **Key:** Smart tool routing based on task type

#### Pattern 5: **Error Recovery with Alternatives**
```
Execute → Error → Analyze Root Cause → Try Alternative → Escalate if Failed
```
- Used by: Devin, Copilot Workspace
- **Why:** Resilience - don't give up on first failure
- **Key:** Multiple strategies per task type

---

## 🏗️ Workflow Architecture Design

### Core Principle: **State Machine with Checkpoints**

Every agent interaction flows through a state machine with explicit checkpoints where user can intervene.

```
┌─────────────┐
│   IDLE      │ ← Agent waiting
└──────┬──────┘
       │ User Request
       ▼
┌─────────────┐
│  ANALYZING  │ ← Understanding task
└──────┬──────┘
       │ Task classified
       ▼
┌─────────────┐
│  PLANNING   │ ← Creating execution plan
└──────┬──────┘
       │ Plan ready
       ▼
┌─────────────┐
│  APPROVAL   │ ⭐ CHECKPOINT - User confirms plan
└──────┬──────┘
       │ Approved
       ▼
┌─────────────┐
│  EXECUTING  │ ← Running tools, making changes
└──────┬──────┘
       │ Execution complete
       ▼
┌─────────────┐
│  VERIFYING  │ ← Checking changes, running tests
└──────┬──────┘
       │ Verified
       ▼
┌─────────────┐
│  REPORTING  │ ← Summarizing what was done
└──────┬──────┘
       │
       ▼
┌─────────────┐
│   IDLE      │
└─────────────┘

ERROR at any stage → RECOVERY state → Retry/Alternative/Escalate
```

---

## 📋 Phase 1: Task Analysis & Classification

### Purpose:
- Understand user intent
- Classify task type
- Determine workflow mode
- Estimate complexity

### Implementation:

```python
from enum import Enum
from typing import Optional, List, Dict
from dataclasses import dataclass

class TaskType(Enum):
    """Types of development tasks"""
    FEATURE = "feature"           # New feature implementation
    BUG_FIX = "bugfix"           # Fix a bug
    REFACTOR = "refactor"        # Code refactoring
    DOCUMENTATION = "docs"       # Add/update docs
    REVIEW = "review"            # Code review
    DEBUG = "debug"              # Debug investigation
    EXPLAIN = "explain"          # Code explanation (no changes)
    SEARCH = "search"            # Code search/exploration
    TEST = "test"                # Test creation/execution

class TaskComplexity(Enum):
    """Estimated complexity levels"""
    TRIVIAL = 1      # Single file, < 5 lines
    SIMPLE = 2       # Single file, < 50 lines
    MODERATE = 3     # 2-3 files, < 200 lines
    COMPLEX = 4      # 4+ files, refactoring
    VERY_COMPLEX = 5 # Architecture changes, many files

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
    risk_level: str  # low, medium, high
    key_concepts: List[str]
    affected_systems: List[str]

class TaskAnalyzer:
    """Analyzes user requests to determine task characteristics"""

    def __init__(self, llm_backend):
        self.llm = llm_backend

    def analyze(self, user_request: str, context: Dict) -> TaskAnalysis:
        """
        Analyze user request to determine task characteristics.

        Args:
            user_request: User's request
            context: Current conversation context

        Returns:
            TaskAnalysis with task characteristics
        """
        # Use LLM to classify task
        analysis_prompt = self._build_analysis_prompt(user_request, context)
        response = self.llm.generate(analysis_prompt)

        # Parse response into TaskAnalysis
        # (Could use JSON mode for structured output)

        return self._parse_analysis(response)

    def _build_analysis_prompt(self, request: str, context: Dict) -> List[Dict]:
        return [
            {"role": "system", "content": """You are a task analysis expert.
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

Guidelines:
- task_type: Primary type of work
- complexity: 1=trivial, 2=simple, 3=moderate, 4=complex, 5=very complex
- requires_planning: true if task needs explicit plan (complexity >= 3)
- requires_approval: true if changes are destructive or risky
- estimated_files: How many files will be affected
- estimated_iterations: How many tool execution loops needed
- requires_git: true if should commit changes
- requires_tests: true if tests should be written/run
- risk_level: Impact if task goes wrong
- key_concepts: Main concepts involved (for RAG retrieval)
- affected_systems: Which systems/modules are affected"""},
            {"role": "user", "content": request}
        ]

    def _parse_analysis(self, response: str) -> TaskAnalysis:
        """Parse LLM response into TaskAnalysis"""
        # Parse JSON response
        import json
        data = json.loads(response)

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
            key_concepts=data["key_concepts"],
            affected_systems=data["affected_systems"]
        )
```

### When to Skip Analysis:
- Trivial questions ("What is X?")
- Explanation requests
- Already classified in memory

---

## 📝 Phase 2: Planning & Decomposition

### Purpose:
- Break complex tasks into steps
- Show reasoning to user
- Get approval before execution
- Provide early estimate

### Planning Strategies by Task Type:

#### Strategy 1: **Sequential Planning** (for Features, Refactors)
```
Step 1 → Step 2 → Step 3 → ... → Step N
```
Each step depends on previous step completion.

#### Strategy 2: **Parallel Planning** (for Bug Fixes, Tests)
```
Investigation Phase:
  ├─ Read error logs
  ├─ Examine relevant code
  └─ Check test failures
  ↓
Fix Phase:
  ├─ Apply fix
  └─ Run tests
```
Some steps can run in parallel.

#### Strategy 3: **Iterative Planning** (for Exploration, Debugging)
```
Hypothesis 1 → Test → Refine → Hypothesis 2 → Test → ...
```
Plan evolves as information is discovered.

### Implementation:

```python
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

@dataclass
class PlanStep:
    """A single step in an execution plan"""
    id: int
    description: str
    action_type: str  # "read", "write", "edit", "search", "run", "git"
    tool: Optional[str] = None
    arguments: Dict[str, Any] = field(default_factory=dict)
    dependencies: List[int] = field(default_factory=list)  # IDs of steps that must complete first
    estimated_time: str = "< 1 min"
    risk: str = "low"  # low, medium, high
    reversible: bool = True
    status: str = "pending"  # pending, in_progress, completed, failed, skipped
    result: Optional[str] = None

@dataclass
class ExecutionPlan:
    """Complete execution plan for a task"""
    task_description: str
    task_type: TaskType
    steps: List[PlanStep]
    total_estimated_time: str
    overall_risk: str
    requires_approval: bool
    rollback_strategy: Optional[str] = None
    success_criteria: List[str] = field(default_factory=list)

class TaskPlanner:
    """Creates execution plans for tasks"""

    def __init__(self, llm_backend, memory_manager):
        self.llm = llm_backend
        self.memory = memory_manager

    def create_plan(
        self,
        user_request: str,
        task_analysis: TaskAnalysis,
        context: Dict
    ) -> ExecutionPlan:
        """
        Create detailed execution plan.

        Args:
            user_request: User's request
            task_analysis: Result of task analysis
            context: Conversation context

        Returns:
            ExecutionPlan with steps
        """
        # Generate plan using LLM
        plan_prompt = self._build_planning_prompt(
            user_request,
            task_analysis,
            context
        )

        response = self.llm.generate(plan_prompt)

        # Parse into ExecutionPlan
        plan = self._parse_plan(response, task_analysis)

        # Validate plan
        self._validate_plan(plan)

        return plan

    def _build_planning_prompt(
        self,
        request: str,
        analysis: TaskAnalysis,
        context: Dict
    ) -> List[Dict]:
        return [
            {"role": "system", "content": f"""You are an expert software architect creating execution plans.

Task Type: {analysis.task_type.value}
Complexity: {analysis.complexity.value}/5
Estimated Files: {analysis.estimated_files}
Risk Level: {analysis.risk_level}

Create a detailed, step-by-step execution plan.

Respond in JSON format:
{{
  "steps": [
    {{
      "id": 1,
      "description": "Clear description of what to do",
      "action_type": "read|write|edit|search|run|git",
      "tool": "tool_name or null",
      "arguments": {{}},
      "dependencies": [],
      "estimated_time": "< 1 min",
      "risk": "low|medium|high",
      "reversible": true/false
    }}
  ],
  "total_estimated_time": "X minutes",
  "overall_risk": "low|medium|high",
  "rollback_strategy": "How to undo changes if needed",
  "success_criteria": ["criterion1", "criterion2"]
}}

Guidelines:
1. Break task into atomic steps
2. Each step should be independently verifiable
3. Order steps by dependencies
4. Identify risky operations
5. Include verification steps
6. Add rollback strategy for destructive operations
7. Use available tools: read_file, write_file, edit_file, search_code, analyze_code, run_command, git_status, git_diff

Example for "Add a new tool":
{{
  "steps": [
    {{
      "id": 1,
      "description": "Read existing tool implementation to understand pattern",
      "action_type": "read",
      "tool": "read_file",
      "arguments": {{"file_path": "src/tools/file_operations.py"}},
      "dependencies": [],
      "estimated_time": "< 1 min",
      "risk": "low",
      "reversible": true
    }},
    {{
      "id": 2,
      "description": "Create new tool file following the pattern",
      "action_type": "write",
      "tool": "write_file",
      "arguments": {{"file_path": "src/tools/new_tool.py"}},
      "dependencies": [1],
      "estimated_time": "< 1 min",
      "risk": "medium",
      "reversible": true
    }},
    {{
      "id": 3,
      "description": "Register new tool in tool executor",
      "action_type": "edit",
      "tool": "edit_file",
      "arguments": {{"file_path": "src/tools/executor.py"}},
      "dependencies": [2],
      "estimated_time": "< 1 min",
      "risk": "medium",
      "reversible": true
    }},
    {{
      "id": 4,
      "description": "Verify tool is registered correctly",
      "action_type": "run",
      "tool": "run_command",
      "arguments": {{"command": "python -m pytest tests/tools/"}},
      "dependencies": [3],
      "estimated_time": "< 1 min",
      "risk": "low",
      "reversible": true
    }}
  ],
  "total_estimated_time": "3-4 minutes",
  "overall_risk": "medium",
  "rollback_strategy": "Delete new_tool.py and revert executor.py changes using git",
  "success_criteria": [
    "New tool file exists",
    "Tool is registered in executor",
    "Tests pass"
  ]
}}"""},
            {"role": "user", "content": request}
        ]

    def _parse_plan(self, response: str, analysis: TaskAnalysis) -> ExecutionPlan:
        """Parse LLM response into ExecutionPlan"""
        import json
        data = json.loads(response)

        steps = [PlanStep(**step_data) for step_data in data["steps"]]

        return ExecutionPlan(
            task_description=analysis.task_type.value,
            task_type=analysis.task_type,
            steps=steps,
            total_estimated_time=data["total_estimated_time"],
            overall_risk=data["overall_risk"],
            requires_approval=analysis.requires_approval,
            rollback_strategy=data.get("rollback_strategy"),
            success_criteria=data.get("success_criteria", [])
        )

    def _validate_plan(self, plan: ExecutionPlan) -> None:
        """Validate plan is well-formed"""
        # Check for circular dependencies
        step_ids = {step.id for step in plan.steps}
        for step in plan.steps:
            for dep_id in step.dependencies:
                if dep_id not in step_ids:
                    raise ValueError(f"Step {step.id} depends on non-existent step {dep_id}")
                if dep_id >= step.id:
                    raise ValueError(f"Step {step.id} has forward/circular dependency on {dep_id}")

    def format_plan_for_user(self, plan: ExecutionPlan) -> str:
        """Format plan for user approval"""
        output = [
            f"## Execution Plan: {plan.task_description.upper()}",
            f"",
            f"**Total Time:** {plan.total_estimated_time}",
            f"**Risk Level:** {plan.overall_risk.upper()}",
            f"**Requires Approval:** {'Yes' if plan.requires_approval else 'No'}",
            f"",
            f"### Steps:",
            f""
        ]

        for step in plan.steps:
            risk_emoji = {"low": "✅", "medium": "⚠️", "high": "🔴"}[step.risk]
            deps_str = f" (depends on: {', '.join(map(str, step.dependencies))})" if step.dependencies else ""

            output.append(
                f"{step.id}. {risk_emoji} **{step.description}**{deps_str}\n"
                f"   - Action: {step.action_type}\n"
                f"   - Time: {step.estimated_time}\n"
                f"   - Reversible: {'Yes' if step.reversible else 'No'}"
            )

        if plan.rollback_strategy:
            output.extend([
                f"",
                f"### Rollback Strategy:",
                f"{plan.rollback_strategy}"
            ])

        if plan.success_criteria:
            output.extend([
                f"",
                f"### Success Criteria:",
                *[f"- {criterion}" for criterion in plan.success_criteria]
            ])

        return "\n".join(output)
```

### User Approval Flow:

```python
def get_user_approval(plan: ExecutionPlan) -> bool:
    """
    Present plan to user and get approval.

    Returns:
        True if approved, False if rejected
    """
    print(format_plan_for_user(plan))
    print("\n" + "="*60)

    if not plan.requires_approval:
        print("This plan will execute automatically (low risk).")
        print("Press Ctrl+C within 3 seconds to cancel...")
        import time
        try:
            time.sleep(3)
            return True
        except KeyboardInterrupt:
            return False

    while True:
        response = input("\nApprove this plan? (yes/no/modify): ").lower()
        if response in ['yes', 'y']:
            return True
        elif response in ['no', 'n']:
            return False
        elif response in ['modify', 'm']:
            # Allow user to refine plan
            modification = input("What would you like to change? ")
            # Re-plan with modification as input
            return None  # Signal to re-plan
        else:
            print("Please answer 'yes', 'no', or 'modify'")
```

---

## ⚙️ Phase 3: Execution Engine

### Purpose:
- Execute plan steps in order
- Handle dependencies
- Show progress
- Handle errors gracefully

### Execution Strategies:

#### Strategy 1: **Sequential Execution** (default)
Execute steps one by one, respecting dependencies.

#### Strategy 2: **Parallel Execution** (optimization)
Execute independent steps in parallel (future enhancement).

#### Strategy 3: **Adaptive Execution** (smart)
Adjust iteration limits based on task complexity.

### Implementation:

```python
from typing import Optional, List, Callable
import time

class ExecutionEngine:
    """Executes plans with progress tracking and error handling"""

    def __init__(
        self,
        tool_executor,
        llm_backend,
        progress_callback: Optional[Callable] = None
    ):
        self.tools = tool_executor
        self.llm = llm_backend
        self.progress_callback = progress_callback or print

    def execute_plan(self, plan: ExecutionPlan) -> ExecutionResult:
        """
        Execute a complete plan.

        Args:
            plan: ExecutionPlan to execute

        Returns:
            ExecutionResult with outcomes
        """
        self.progress_callback(f"Starting execution: {plan.task_description}")
        self.progress_callback(f"Total steps: {len(plan.steps)}")

        results = []
        completed_steps = set()

        # Get adaptive iteration limit based on complexity
        max_iterations_per_step = self._get_iteration_limit(plan)

        for step in plan.steps:
            # Check dependencies
            if not self._dependencies_met(step, completed_steps):
                self.progress_callback(f"⏭️  Skipping step {step.id} - dependencies not met")
                step.status = "skipped"
                continue

            # Execute step
            self.progress_callback(f"\n{'='*60}")
            self.progress_callback(f"Step {step.id}/{len(plan.steps)}: {step.description}")
            self.progress_callback(f"{'='*60}")

            step.status = "in_progress"
            step_result = self._execute_step(step, max_iterations_per_step)

            if step_result.success:
                step.status = "completed"
                step.result = step_result.output
                completed_steps.add(step.id)
                self.progress_callback(f"✅ Step {step.id} completed")
            else:
                step.status = "failed"
                step.result = step_result.error
                self.progress_callback(f"❌ Step {step.id} failed: {step_result.error}")

                # Decide whether to continue or abort
                if self._should_abort(plan, step, step_result):
                    self.progress_callback(f"\n🛑 Aborting execution due to critical failure")
                    break
                else:
                    self.progress_callback(f"⚠️  Continuing despite failure (non-critical)")

            results.append(step_result)

        # Generate execution summary
        summary = self._generate_summary(plan, results)

        return ExecutionResult(
            plan=plan,
            step_results=results,
            summary=summary,
            success=all(r.success for r in results)
        )

    def _dependencies_met(self, step: PlanStep, completed: set) -> bool:
        """Check if all dependencies are met"""
        return all(dep_id in completed for dep_id in step.dependencies)

    def _get_iteration_limit(self, plan: ExecutionPlan) -> int:
        """Get adaptive iteration limit based on task complexity"""
        # Simple tasks: 3 iterations
        # Moderate tasks: 5 iterations
        # Complex tasks: 8 iterations
        complexity_map = {
            TaskComplexity.TRIVIAL: 3,
            TaskComplexity.SIMPLE: 3,
            TaskComplexity.MODERATE: 5,
            TaskComplexity.COMPLEX: 8,
            TaskComplexity.VERY_COMPLEX: 10
        }

        # Find max complexity in plan
        max_complexity = max(
            (TaskComplexity.MODERATE,),  # default
            key=lambda x: x.value
        )

        return complexity_map.get(max_complexity, 5)

    def _execute_step(self, step: PlanStep, max_iterations: int) -> StepResult:
        """
        Execute a single plan step.

        Args:
            step: PlanStep to execute
            max_iterations: Max tool calling iterations

        Returns:
            StepResult with outcome
        """
        start_time = time.time()

        try:
            if step.tool:
                # Direct tool execution
                result = self.tools.execute_tool(step.tool, **step.arguments)

                if result.is_success():
                    return StepResult(
                        step_id=step.id,
                        success=True,
                        output=result.output,
                        duration=time.time() - start_time
                    )
                else:
                    return StepResult(
                        step_id=step.id,
                        success=False,
                        error=result.error,
                        duration=time.time() - start_time
                    )
            else:
                # LLM-driven execution (agent figures out which tools to use)
                prompt = self._build_execution_prompt(step)

                # Use tool calling loop (like current agent)
                output = self._execute_with_tools(prompt, max_iterations)

                return StepResult(
                    step_id=step.id,
                    success=True,
                    output=output,
                    duration=time.time() - start_time
                )

        except Exception as e:
            return StepResult(
                step_id=step.id,
                success=False,
                error=str(e),
                duration=time.time() - start_time
            )

    def _build_execution_prompt(self, step: PlanStep) -> List[Dict]:
        """Build prompt for LLM to execute step"""
        return [
            {"role": "system", "content": "You are executing a step in a larger plan."},
            {"role": "user", "content": f"Execute this step: {step.description}"}
        ]

    def _should_abort(self, plan: ExecutionPlan, failed_step: PlanStep, result: StepResult) -> bool:
        """Decide if execution should abort after a failure"""
        # Abort if:
        # 1. Step is high risk and failed
        # 2. Other steps depend on this step
        # 3. Step is non-reversible

        if failed_step.risk == "high":
            return True

        dependent_steps = [s for s in plan.steps if failed_step.id in s.dependencies]
        if dependent_steps:
            return True

        if not failed_step.reversible:
            return True

        return False

    def _generate_summary(self, plan: ExecutionPlan, results: List[StepResult]) -> str:
        """Generate execution summary"""
        completed = sum(1 for r in results if r.success)
        failed = sum(1 for r in results if not r.success)
        total_time = sum(r.duration for r in results)

        summary = [
            f"## Execution Summary",
            f"",
            f"**Task:** {plan.task_description}",
            f"**Status:** {'✅ SUCCESS' if all(r.success for r in results) else '❌ FAILED'}",
            f"**Completed:** {completed}/{len(results)} steps",
            f"**Failed:** {failed}/{len(results)} steps",
            f"**Total Time:** {total_time:.1f}s",
            f""
        ]

        if failed > 0:
            summary.append("### Failed Steps:")
            for result in results:
                if not result.success:
                    step = plan.steps[result.step_id - 1]
                    summary.append(f"- Step {result.step_id}: {step.description}")
                    summary.append(f"  Error: {result.error}")

        return "\n".join(summary)

@dataclass
class StepResult:
    """Result of executing a single step"""
    step_id: int
    success: bool
    output: Optional[str] = None
    error: Optional[str] = None
    duration: float = 0.0

@dataclass
class ExecutionResult:
    """Result of executing a complete plan"""
    plan: ExecutionPlan
    step_results: List[StepResult]
    summary: str
    success: bool
```

---

## ✅ Phase 4: Verification & Validation

### Purpose:
- Verify changes are correct
- Run automated checks
- Suggest tests
- Provide diff summary

### Verification Strategies:

#### Strategy 1: **Pre-Change Analysis**
Before making changes, analyze what will be affected.

#### Strategy 2: **Post-Change Validation**
After changes, verify correctness.

#### Strategy 3: **Test Execution**
Run relevant tests to ensure nothing broke.

### Implementation:

```python
from typing import List, Dict, Any
from dataclasses import dataclass

@dataclass
class Change:
    """Represents a code change"""
    file_path: str
    change_type: str  # "create", "modify", "delete"
    before: Optional[str] = None
    after: Optional[str] = None
    line_numbers: Optional[tuple] = None

@dataclass
class VerificationResult:
    """Result of verification checks"""
    passed: bool
    checks_run: List[str]
    issues_found: List[str]
    suggestions: List[str]
    test_results: Optional[Dict] = None

class VerificationLayer:
    """Verifies changes are correct and safe"""

    def __init__(self, tool_executor):
        self.tools = tool_executor

    def pre_change_analysis(self, plan: ExecutionPlan) -> Dict[str, Any]:
        """
        Analyze what will be affected before making changes.

        Args:
            plan: ExecutionPlan to analyze

        Returns:
            Impact analysis
        """
        affected_files = self._extract_affected_files(plan)

        # Check current state
        current_state = {}
        for file_path in affected_files:
            try:
                result = self.tools.execute_tool("read_file", file_path=file_path)
                if result.is_success():
                    current_state[file_path] = result.output
            except:
                current_state[file_path] = None  # File doesn't exist

        # Find dependencies
        dependencies = self._find_dependencies(affected_files)

        return {
            "affected_files": affected_files,
            "current_state": current_state,
            "dependencies": dependencies,
            "risk_assessment": self._assess_risk(plan, dependencies)
        }

    def post_change_verification(self, changes: List[Change]) -> VerificationResult:
        """
        Verify changes after execution.

        Args:
            changes: List of changes made

        Returns:
            VerificationResult
        """
        checks_run = []
        issues_found = []
        suggestions = []

        # Check 1: Syntax validation
        for change in changes:
            if change.file_path.endswith('.py'):
                syntax_ok = self._check_python_syntax(change.file_path)
                checks_run.append(f"Python syntax check: {change.file_path}")
                if not syntax_ok:
                    issues_found.append(f"Syntax error in {change.file_path}")

        # Check 2: Import validation
        for change in changes:
            if change.change_type in ["create", "modify"]:
                import_issues = self._check_imports(change.file_path)
                checks_run.append(f"Import check: {change.file_path}")
                if import_issues:
                    issues_found.extend(import_issues)

        # Check 3: Git status (if in git repo)
        try:
            git_status = self.tools.execute_tool("git_status")
            if git_status.is_success():
                checks_run.append("Git status check")
                # Parse git status for useful info
        except:
            pass

        # Generate suggestions
        if changes:
            suggestions.append("Run tests to verify changes")
            suggestions.append(f"Review diff with: git diff {' '.join(c.file_path for c in changes)}")

            # Check if tests exist for modified files
            for change in changes:
                test_file = self._get_test_file(change.file_path)
                if test_file:
                    suggestions.append(f"Run tests: pytest {test_file}")

        return VerificationResult(
            passed=len(issues_found) == 0,
            checks_run=checks_run,
            issues_found=issues_found,
            suggestions=suggestions
        )

    def run_tests(self, test_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Run tests and return results.

        Args:
            test_path: Optional specific test path

        Returns:
            Test results
        """
        try:
            cmd = f"pytest {test_path}" if test_path else "pytest"
            result = self.tools.execute_tool("run_command", command=cmd, timeout=60)

            if result.is_success():
                # Parse pytest output
                return self._parse_pytest_output(result.output)
            else:
                return {
                    "success": False,
                    "error": result.error
                }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def _check_python_syntax(self, file_path: str) -> bool:
        """Check Python file syntax"""
        try:
            result = self.tools.execute_tool(
                "run_command",
                command=f"python -m py_compile {file_path}",
                timeout=5
            )
            return result.is_success()
        except:
            return False

    def _check_imports(self, file_path: str) -> List[str]:
        """Check if imports are valid"""
        issues = []
        try:
            # Read file
            result = self.tools.execute_tool("read_file", file_path=file_path)
            if not result.is_success():
                return issues

            content = result.output

            # Extract imports
            import re
            imports = re.findall(r'^(?:from|import)\s+(\S+)', content, re.MULTILINE)

            # Check if imports exist (basic check)
            # In production, would use actual import resolution

        except:
            pass

        return issues

    def _extract_affected_files(self, plan: ExecutionPlan) -> List[str]:
        """Extract list of files that will be affected"""
        files = set()
        for step in plan.steps:
            if step.action_type in ["write", "edit"]:
                if "file_path" in step.arguments:
                    files.add(step.arguments["file_path"])
        return list(files)

    def _find_dependencies(self, files: List[str]) -> Dict[str, List[str]]:
        """Find which files depend on given files"""
        # Simplified - would use actual dependency analysis
        return {}

    def _assess_risk(self, plan: ExecutionPlan, dependencies: Dict) -> str:
        """Assess risk level of planned changes"""
        if plan.overall_risk == "high":
            return "high"
        elif len(dependencies) > 5:
            return "high"
        elif plan.overall_risk == "medium":
            return "medium"
        else:
            return "low"

    def _get_test_file(self, source_file: str) -> Optional[str]:
        """Get corresponding test file"""
        import os

        # src/core/agent.py → tests/core/test_agent.py
        if source_file.startswith("src/"):
            test_path = source_file.replace("src/", "tests/", 1)
            test_path = test_path.replace(".py", "")
            test_file = f"test_{os.path.basename(test_path)}.py"
            test_dir = os.path.dirname(test_path)
            full_test_path = os.path.join(test_dir, test_file)

            # Check if exists
            try:
                result = self.tools.execute_tool("read_file", file_path=full_test_path)
                if result.is_success():
                    return full_test_path
            except:
                pass

        return None

    def _parse_pytest_output(self, output: str) -> Dict[str, Any]:
        """Parse pytest output"""
        # Simplified parsing
        passed = output.count(" passed")
        failed = output.count(" failed")

        return {
            "success": failed == 0,
            "passed": passed,
            "failed": failed,
            "output": output
        }
```

---

## 🔄 Phase 5: Error Recovery

### Purpose:
- Gracefully handle errors
- Provide alternatives
- Learn from failures
- Escalate when stuck

### Recovery Strategies:

#### Strategy 1: **Retry with Modification**
Try same approach with adjusted parameters.

#### Strategy 2: **Alternative Approach**
Try completely different method.

#### Strategy 3: **Escalate to User**
Ask for help when stuck.

### Implementation:

```python
from typing import Optional, List, Callable
from enum import Enum

class RecoveryStrategy(Enum):
    RETRY = "retry"           # Retry same approach
    MODIFY = "modify"         # Modify approach
    ALTERNATIVE = "alternative"  # Try different approach
    ESCALATE = "escalate"     # Ask user for help
    ABORT = "abort"           # Give up

@dataclass
class ErrorContext:
    """Context about an error"""
    error_message: str
    failed_step: PlanStep
    attempt_number: int
    previous_attempts: List[str]
    stack_trace: Optional[str] = None

class ErrorRecovery:
    """Handles error recovery with multiple strategies"""

    def __init__(self, llm_backend, max_attempts: int = 3):
        self.llm = llm_backend
        self.max_attempts = max_attempts

    def handle_error(
        self,
        error_context: ErrorContext,
        plan: ExecutionPlan
    ) -> Tuple[RecoveryStrategy, Optional[PlanStep]]:
        """
        Decide how to recover from an error.

        Args:
            error_context: Context about the error
            plan: Current execution plan

        Returns:
            (RecoveryStrategy, Optional modified step)
        """
        # Analyze error
        analysis = self._analyze_error(error_context)

        # Decide strategy
        strategy = self._select_strategy(error_context, analysis)

        # Generate recovery action
        if strategy == RecoveryStrategy.RETRY:
            return (strategy, error_context.failed_step)

        elif strategy == RecoveryStrategy.MODIFY:
            modified_step = self._modify_step(error_context, analysis)
            return (strategy, modified_step)

        elif strategy == RecoveryStrategy.ALTERNATIVE:
            alternative_step = self._generate_alternative(error_context, analysis)
            return (strategy, alternative_step)

        elif strategy == RecoveryStrategy.ESCALATE:
            self._escalate_to_user(error_context, analysis)
            return (strategy, None)

        else:  # ABORT
            return (strategy, None)

    def _analyze_error(self, context: ErrorContext) -> Dict[str, Any]:
        """Analyze error to understand root cause"""
        error_lower = context.error_message.lower()

        analysis = {
            "error_type": "unknown",
            "is_retriable": False,
            "likely_cause": "",
            "suggestions": []
        }

        # Common error patterns
        if "file not found" in error_lower or "no such file" in error_lower:
            analysis["error_type"] = "file_not_found"
            analysis["is_retriable"] = False
            analysis["likely_cause"] = "File path is incorrect or file doesn't exist"
            analysis["suggestions"] = [
                "Search for similar filenames",
                "List directory contents",
                "Ask user for correct path"
            ]

        elif "permission denied" in error_lower:
            analysis["error_type"] = "permission"
            analysis["is_retriable"] = False
            analysis["likely_cause"] = "Insufficient permissions"
            analysis["suggestions"] = ["Ask user to grant permissions", "Try alternative approach"]

        elif "syntax error" in error_lower:
            analysis["error_type"] = "syntax"
            analysis["is_retriable"] = True
            analysis["likely_cause"] = "Generated code has syntax errors"
            analysis["suggestions"] = ["Fix syntax", "Regenerate code"]

        elif "timeout" in error_lower:
            analysis["error_type"] = "timeout"
            analysis["is_retriable"] = True
            analysis["likely_cause"] = "Operation took too long"
            analysis["suggestions"] = ["Increase timeout", "Break into smaller operations"]

        elif "connection" in error_lower or "network" in error_lower:
            analysis["error_type"] = "network"
            analysis["is_retriable"] = True
            analysis["likely_cause"] = "Network or connection issue"
            analysis["suggestions"] = ["Retry after delay", "Check connectivity"]

        return analysis

    def _select_strategy(self, context: ErrorContext, analysis: Dict) -> RecoveryStrategy:
        """Select recovery strategy based on error analysis"""

        # Exceeded max attempts → escalate or abort
        if context.attempt_number >= self.max_attempts:
            return RecoveryStrategy.ESCALATE

        # Retriable errors → try again
        if analysis["is_retriable"] and context.attempt_number == 1:
            return RecoveryStrategy.RETRY

        # File not found → try alternative
        if analysis["error_type"] == "file_not_found":
            return RecoveryStrategy.ALTERNATIVE

        # Syntax errors → modify
        if analysis["error_type"] == "syntax":
            return RecoveryStrategy.MODIFY

        # Permission errors → escalate immediately
        if analysis["error_type"] == "permission":
            return RecoveryStrategy.ESCALATE

        # Default: try modification
        return RecoveryStrategy.MODIFY

    def _modify_step(self, context: ErrorContext, analysis: Dict) -> PlanStep:
        """Modify step based on error analysis"""
        modified = context.failed_step

        # Use LLM to suggest modification
        prompt = [
            {"role": "system", "content": "You are an error recovery expert."},
            {"role": "user", "content": f"""
A step failed with this error:
{context.error_message}

Original step:
{context.failed_step.description}

Error analysis:
- Type: {analysis['error_type']}
- Likely cause: {analysis['likely_cause']}
- Suggestions: {', '.join(analysis['suggestions'])}

How should we modify this step to avoid the error?
Respond with a modified step description.
"""}
        ]

        response = self.llm.generate(prompt)
        modified.description = response.content

        return modified

    def _generate_alternative(self, context: ErrorContext, analysis: Dict) -> PlanStep:
        """Generate alternative approach"""
        # Use LLM to generate alternative
        prompt = [
            {"role": "system", "content": "You are a problem-solving expert."},
            {"role": "user", "content": f"""
A step failed: {context.failed_step.description}
Error: {context.error_message}

Suggest a completely different approach to achieve the same goal.
Respond with an alternative step description.
"""}
        ]

        response = self.llm.generate(prompt)

        # Create new step
        alternative = PlanStep(
            id=context.failed_step.id,
            description=response.content,
            action_type=context.failed_step.action_type,
            dependencies=context.failed_step.dependencies
        )

        return alternative

    def _escalate_to_user(self, context: ErrorContext, analysis: Dict) -> None:
        """Escalate error to user for help"""
        print("\n" + "="*60)
        print("🆘 NEED HELP - Error Recovery")
        print("="*60)
        print(f"\nStep: {context.failed_step.description}")
        print(f"Error: {context.error_message}")
        print(f"\nAttempts made: {context.attempt_number}")
        print(f"Error type: {analysis['error_type']}")
        print(f"Likely cause: {analysis['likely_cause']}")

        if analysis['suggestions']:
            print(f"\nSuggestions:")
            for suggestion in analysis['suggestions']:
                print(f"  - {suggestion}")

        print("\nHow would you like to proceed?")
        print("1. Skip this step")
        print("2. Provide alternative approach")
        print("3. Abort execution")
        # In production, would actually get user input
```

---

## 🛠️ Essential New Tools

### Tools to Implement (Priority Order):

#### 1. **run_command** - Execute shell commands (HIGH)
```python
class RunCommandTool(Tool):
    """Execute shell commands with safety checks"""

    def execute(self, command: str, timeout: int = 30, **kwargs):
        # Safety checks: block dangerous commands
        dangerous = ["rm -rf", "dd if=", "> /dev/", "mkfs", ":(){ :|:& };:"]
        if any(danger in command for danger in dangerous):
            return ToolResult(
                success=False,
                error=f"Dangerous command blocked: {command}"
            )

        # Execute with timeout
        import subprocess
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            return ToolResult(
                success=result.returncode == 0,
                output=result.stdout if result.returncode == 0 else result.stderr
            )
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, error="Command timed out")
```

#### 2. **list_directory** - Browse directory structure (HIGH)
```python
class ListDirectoryTool(Tool):
    """List directory contents with filters"""

    def execute(self, path: str = ".", pattern: str = "*", recursive: bool = False, **kwargs):
        import os
        import glob

        try:
            if recursive:
                files = glob.glob(os.path.join(path, "**", pattern), recursive=True)
            else:
                files = glob.glob(os.path.join(path, pattern))

            return ToolResult(
                success=True,
                output="\n".join(sorted(files))
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))
```

#### 3. **git_status** - Git status (HIGH)
```python
class GitStatusTool(Tool):
    """Get git repository status"""

    def execute(self, **kwargs):
        import subprocess
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=5
            )
            return ToolResult(success=True, output=result.stdout)
        except Exception as e:
            return ToolResult(success=False, error=str(e))
```

#### 4. **git_diff** - Git diff (HIGH)
```python
class GitDiffTool(Tool):
    """Get git diff"""

    def execute(self, file_path: Optional[str] = None, staged: bool = False, **kwargs):
        import subprocess
        cmd = ["git", "diff"]
        if staged:
            cmd.append("--cached")
        if file_path:
            cmd.append(file_path)

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            return ToolResult(success=True, output=result.stdout)
        except Exception as e:
            return ToolResult(success=False, error=str(e))
```

#### 5. **git_commit** - Git commit (MEDIUM)
```python
class GitCommitTool(Tool):
    """Create git commit"""

    def execute(self, message: str, files: Optional[List[str]] = None, **kwargs):
        import subprocess
        try:
            # Stage files
            if files:
                for file in files:
                    subprocess.run(["git", "add", file], check=True)
            else:
                subprocess.run(["git", "add", "-A"], check=True)

            # Commit
            result = subprocess.run(
                ["git", "commit", "-m", message],
                capture_output=True,
                text=True,
                timeout=10
            )
            return ToolResult(success=True, output=result.stdout)
        except Exception as e:
            return ToolResult(success=False, error=str(e))
```

---

## 🔌 Integration with Existing Agent

### Modification Points in `src/core/agent.py`:

```python
class CodingAgent:
    def __init__(self, ...):
        # ... existing init ...

        # NEW: Add workflow components
        self.task_analyzer = TaskAnalyzer(self.llm)
        self.task_planner = TaskPlanner(self.llm, self.memory)
        self.execution_engine = ExecutionEngine(
            self.tool_executor,
            self.llm,
            progress_callback=self._progress_callback
        )
        self.verification_layer = VerificationLayer(self.tool_executor)
        self.error_recovery = ErrorRecovery(self.llm)

        # NEW: Register additional tools
        self._register_workflow_tools()

    def _register_workflow_tools(self):
        """Register workflow-specific tools"""
        self.tool_executor.register_tool(RunCommandTool())
        self.tool_executor.register_tool(ListDirectoryTool())
        self.tool_executor.register_tool(GitStatusTool())
        self.tool_executor.register_tool(GitDiffTool())
        self.tool_executor.register_tool(GitCommitTool())

    def execute_task(self, task_description: str, ...) -> AgentResponse:
        """
        Execute task with workflow support.

        MODIFIED to include workflow phases.
        """
        # Phase 1: Analyze task
        task_analysis = self.task_analyzer.analyze(task_description, context={})

        # Phase 2: Create plan (if needed)
        if task_analysis.requires_planning:
            plan = self.task_planner.create_plan(
                task_description,
                task_analysis,
                context={}
            )

            # Show plan to user
            print(self.task_planner.format_plan_for_user(plan))

            # Get approval (if needed)
            if task_analysis.requires_approval:
                approved = self._get_user_approval(plan)
                if not approved:
                    return AgentResponse(
                        content="Plan rejected by user",
                        metadata={"status": "rejected"}
                    )

            # Phase 3: Execute plan
            execution_result = self.execution_engine.execute_plan(plan)

            # Phase 4: Verify changes
            if execution_result.success:
                verification = self.verification_layer.post_change_verification(
                    self._extract_changes(execution_result)
                )

                print(f"\n{'='*60}")
                print("Verification Results:")
                print(f"{'='*60}")
                print(f"Passed: {verification.passed}")
                print(f"Checks: {', '.join(verification.checks_run)}")
                if verification.issues_found:
                    print(f"Issues: {', '.join(verification.issues_found)}")
                if verification.suggestions:
                    print(f"\nSuggestions:")
                    for s in verification.suggestions:
                        print(f"  - {s}")

            # Phase 5: Report results
            response_content = execution_result.summary
        else:
            # Simple task - use existing flow
            response_content = self._execute_with_tools(...)

        return AgentResponse(content=response_content)
```

---

## 📊 Testing Strategy for Workflows

### Test Scenarios:

#### Test 1: Simple Plan Execution
```python
def test_simple_workflow():
    """Test: Create a new tool"""
    agent = CodingAgent(...)
    response = agent.execute_task(
        "Create a new tool called ExampleTool in src/tools/example_tool.py"
    )

    assert response.metadata["plan_created"] == True
    assert response.metadata["steps_executed"] >= 2
    assert os.path.exists("src/tools/example_tool.py")
```

#### Test 2: Multi-File Refactoring
```python
def test_multi_file_workflow():
    """Test: Rename class across multiple files"""
    agent = CodingAgent(...)
    response = agent.execute_task(
        "Rename MemoryManager to MemorySystem across the entire codebase"
    )

    assert response.metadata["files_modified"] >= 3
    assert response.metadata["verification_passed"] == True
```

#### Test 3: Error Recovery
```python
def test_error_recovery():
    """Test: Agent recovers from file not found error"""
    agent = CodingAgent(...)
    response = agent.execute_task(
        "Read src/util/helper.py and explain it"  # Wrong path
    )

    assert response.metadata["errors_recovered"] >= 1
    assert response.metadata["alternative_found"] == True
```

#### Test 4: Approval Flow
```python
def test_approval_required():
    """Test: High-risk changes require approval"""
    agent = CodingAgent(...)
    response = agent.execute_task(
        "Delete all files in src/deprecated/"
    )

    assert response.metadata["approval_requested"] == True
    assert response.metadata["risk_level"] == "high"
```

---

## 🎯 Implementation Roadmap

### Week 1: Core Workflow Infrastructure
- [ ] Day 1-2: Implement TaskAnalyzer and TaskPlanner
- [ ] Day 3-4: Implement ExecutionEngine
- [ ] Day 5: Integration with CodingAgent
- [ ] Day 6-7: Testing and debugging

### Week 2: Essential Tools & Verification
- [ ] Day 1-2: Implement run_command, list_directory, git tools
- [ ] Day 3-4: Implement VerificationLayer
- [ ] Day 5: Add progress callbacks and UX
- [ ] Day 6-7: End-to-end testing

### Week 3: Error Recovery & Polish
- [ ] Day 1-3: Implement ErrorRecovery
- [ ] Day 4-5: Optimize prompts for planning
- [ ] Day 6-7: Performance testing and optimization

---

## 📈 Success Metrics

**After Implementation:**

1. **Planning Adoption:** 80%+ of complex tasks use planning phase
2. **Approval Flow:** 100% of high-risk tasks request approval
3. **Execution Success:** 85%+ of plans execute successfully
4. **Verification:** 90%+ of changes pass automated verification
5. **Error Recovery:** 70%+ of errors recover automatically
6. **User Satisfaction:** 4/5+ rating for workflow experience

---

## 🔍 Next Steps

**Immediate (Today):**
1. Review this architecture with stakeholders ✅
2. Prioritize implementation order ⏳
3. Create detailed implementation specs for Week 1 ⏳

**Short-term (Week 1):**
1. Implement TaskAnalyzer + TaskPlanner
2. Create execution engine
3. Integrate with existing agent
4. Write unit tests

**Medium-term (Weeks 2-3):**
1. Add essential tools
2. Implement verification
3. Add error recovery
4. Polish UX

---

**Document Status:** Architecture Complete - Ready for Implementation
**Last Updated:** 2025-10-15
**Next Review:** After Week 1 implementation
