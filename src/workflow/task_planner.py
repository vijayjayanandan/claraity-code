"""Task planner for generating execution plans.

This module provides LLM-powered execution planning that breaks down
complex tasks into detailed, actionable steps with dependency management.

Uses OpenAI-compatible tool calling for structured plan generation,
eliminating JSON parsing errors and improving reliability.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum
import json
import re
import logging

from .task_analyzer import TaskAnalysis, TaskType
from src.llm.base import ToolCall
from src.tools.tool_schemas import ALL_TOOLS

logger = logging.getLogger(__name__)


class ActionType(Enum):
    """Types of actions a step can perform."""

    READ = "read"           # Read file or gather information
    WRITE = "write"         # Create new file
    EDIT = "edit"          # Modify existing file
    SEARCH = "search"      # Search code
    ANALYZE = "analyze"    # Analyze code
    RUN = "run"            # Run command/tests
    GIT = "git"            # Git operation
    VERIFY = "verify"      # Verification step


@dataclass
class PlanStep:
    """A single step in an execution plan.

    Attributes:
        id: Unique step identifier (1-indexed)
        description: Clear description of what to do
        action_type: Type of action (read, write, edit, etc.)
        tool: Optional specific tool to use
        arguments: Arguments for the tool
        dependencies: IDs of steps that must complete first
        estimated_time: Time estimate (e.g., "< 1 min")
        risk: Risk level (low, medium, high)
        reversible: Whether this step can be undone
        status: Current status (pending, in_progress, completed, failed, skipped)
        result: Result after execution (populated during execution)
    """

    id: int
    description: str
    action_type: str  # Will validate against ActionType
    tool: Optional[str] = None
    arguments: Dict[str, Any] = field(default_factory=dict)
    dependencies: List[int] = field(default_factory=list)
    estimated_time: str = "< 1 min"
    risk: str = "low"  # low, medium, high
    reversible: bool = True
    status: str = "pending"  # pending, in_progress, completed, failed, skipped
    result: Optional[str] = None

    def __str__(self) -> str:
        """Human-readable representation."""
        risk_emoji = {"low": "✅", "medium": "⚠️", "high": "🔴"}[self.risk]
        deps_str = f" (depends on: {', '.join(map(str, self.dependencies))})" if self.dependencies else ""

        return (
            f"{risk_emoji} Step {self.id}: {self.description}{deps_str}\n"
            f"   Action: {self.action_type} | Time: {self.estimated_time} | "
            f"Reversible: {'Yes' if self.reversible else 'No'}"
        )


@dataclass
class ExecutionPlan:
    """Complete execution plan for a task.

    Attributes:
        task_description: Original task description
        task_type: Type of task (from TaskAnalysis)
        steps: List of steps to execute
        total_estimated_time: Total time estimate
        overall_risk: Overall risk level (low, medium, high)
        requires_approval: Whether user approval is needed
        rollback_strategy: How to undo changes if needed
        success_criteria: List of criteria for success
        metadata: Additional metadata
    """

    task_description: str
    task_type: TaskType
    steps: List[PlanStep]
    total_estimated_time: str
    overall_risk: str
    requires_approval: bool
    rollback_strategy: Optional[str] = None
    success_criteria: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def get_step_by_id(self, step_id: int) -> Optional[PlanStep]:
        """Get step by ID."""
        for step in self.steps:
            if step.id == step_id:
                return step
        return None

    def get_next_pending_step(self, completed_ids: set) -> Optional[PlanStep]:
        """Get next step that can be executed (dependencies met)."""
        for step in self.steps:
            # Skip steps that are already completed
            if step.status == "pending" and step.id not in completed_ids:
                # Check if all dependencies are completed
                if all(dep_id in completed_ids for dep_id in step.dependencies):
                    return step
        return None


class TaskPlanner:
    """Creates detailed execution plans for tasks using LLM.

    Uses LLM to generate structured, step-by-step plans with:
    - Dependency management
    - Risk assessment per step
    - Time estimates
    - Rollback strategies
    - Success criteria
    """

    def __init__(self, llm_backend, memory_manager=None):
        """Initialize task planner.

        Args:
            llm_backend: LLM backend for generating plans
            memory_manager: Optional memory manager for context
        """
        self.llm = llm_backend
        self.memory = memory_manager
        logger.info("TaskPlanner initialized")

    def create_plan(
        self,
        user_request: str,
        task_analysis: TaskAnalysis,
        context: Optional[Dict[str, Any]] = None
    ) -> ExecutionPlan:
        """Create detailed execution plan.

        Args:
            user_request: User's original request
            task_analysis: Result from TaskAnalyzer
            context: Optional additional context

        Returns:
            ExecutionPlan with detailed steps

        Raises:
            ValueError: If plan generation fails or is invalid
        """
        if not user_request or not user_request.strip():
            raise ValueError("User request cannot be empty")

        logger.info(f"Creating plan for: {user_request[:100]}...")
        logger.info(f"Task type: {task_analysis.task_type.value}, Complexity: {task_analysis.complexity.value}")

        # Generate plan using LLM
        try:
            plan = self._llm_generate_plan(user_request, task_analysis, context or {})
            logger.info(f"Generated plan with {len(plan.steps)} steps")
        except Exception as e:
            logger.error(f"LLM plan generation failed: {e}")
            # Fall back to simple plan
            logger.info("Falling back to simple plan generation")
            plan = self._create_simple_plan(user_request, task_analysis)

        # Validate plan
        try:
            self._validate_plan(plan)
            logger.info("Plan validation passed")
        except ValueError as e:
            logger.error(f"Plan validation failed: {e}")
            raise

        return plan

    def _llm_generate_plan(
        self,
        request: str,
        analysis: TaskAnalysis,
        context: Dict[str, Any]
    ) -> ExecutionPlan:
        """Use LLM to generate execution plan with tool calling.

        Uses structured tool calling instead of JSON string parsing.
        This eliminates JSON escaping errors and provides validated responses.

        Supports two-phase planning:
        - Phase 1 (Exploration): LLM explores workspace with read-only tools
        - Phase 2 (Implementation): LLM generates implementation with exploration results

        Args:
            request: User request
            analysis: Task analysis
            context: Additional context

        Returns:
            ExecutionPlan from LLM tool calls

        Raises:
            Exception: If LLM generation fails or returns no tool calls
        """
        # Build planning prompt (focused on reasoning, not JSON format)
        planning_messages = self._build_planning_prompt(request, analysis)

        # Get LLM response with tool calling
        # The LLM will return structured ToolCall objects, not JSON strings!
        response = self.llm.generate_with_tools(
            messages=planning_messages,
            tools=ALL_TOOLS,
            tool_choice="auto"  # LLM decides which tools to call
        )

        # Log response for debugging
        if response.content:
            logger.debug(f"LLM reasoning: {response.content[:200]}...")
        logger.debug(f"Tool calls: {len(response.tool_calls) if response.tool_calls else 0}")

        # Verify we got tool calls
        if not response.tool_calls:
            raise ValueError(
                "LLM did not return any tool calls. "
                "This usually means the LLM responded with text instead of calling tools."
            )

        # Check if this is exploration phase (read-only tools)
        if self._is_exploration_phase(response.tool_calls):
            logger.info("[EXPLORATION] LLM wants to explore workspace first - executing exploration tools")

            # Execute exploration tools
            exploration_results = self._execute_exploration_tools(response.tool_calls)

            # Re-prompt with exploration results for implementation
            logger.info("[IMPLEMENTATION] Re-prompting with exploration results for implementation")
            implementation_messages = self._build_implementation_prompt(
                request, analysis, exploration_results
            )

            # Get implementation response
            impl_response = self.llm.generate_with_tools(
                messages=implementation_messages,
                tools=ALL_TOOLS,
                tool_choice="auto"
            )

            if not impl_response.tool_calls:
                raise ValueError(
                    "LLM did not return implementation tool calls after exploration phase"
                )

            logger.info(f"[IMPLEMENTATION] Generated {len(impl_response.tool_calls)} tool calls")
            return self._parse_tool_calls(impl_response.tool_calls, request, analysis)

        # Direct implementation (no exploration needed)
        logger.info(f"[DIRECT] Generated {len(response.tool_calls)} tool calls directly")
        return self._parse_tool_calls(response.tool_calls, request, analysis)

    def _is_exploration_phase(self, tool_calls: List[ToolCall]) -> bool:
        """Check if tool calls represent exploration phase (read-only operations).

        Exploration tools are read-only: list_directory, read_file, search_code, analyze_code
        Implementation tools modify state: write_file, edit_file, run_command, git_commit

        Args:
            tool_calls: List of tool calls from LLM

        Returns:
            True if tool calls are only exploration (no implementation)
        """
        exploration_tools = {"list_directory", "read_file", "search_code", "analyze_code", "git_status", "git_diff"}
        implementation_tools = {"write_file", "edit_file", "run_command", "git_commit"}

        has_exploration = any(tc.name in exploration_tools for tc in tool_calls)
        has_implementation = any(tc.name in implementation_tools for tc in tool_calls)

        # Exploration phase = has exploration tools AND no implementation tools
        return has_exploration and not has_implementation

    def _execute_exploration_tools(self, tool_calls: List[ToolCall]) -> str:
        """Execute exploration tools and return formatted results.

        Args:
            tool_calls: List of exploration tool calls to execute

        Returns:
            Formatted string with exploration results
        """
        results = []

        for tool_call in tool_calls:
            tool_name = tool_call.name
            args = tool_call.arguments

            try:
                if tool_name == "list_directory":
                    # Import tools here to avoid circular imports
                    from src.tools.file_operations import ListDirectoryTool
                    tool = ListDirectoryTool()
                    result = tool.execute(args.get("directory_path", "."))
                    results.append(f"[OK] list_directory: {args.get('directory_path', '.')}")
                    # ToolResult object - access output attribute
                    output = result.output if hasattr(result, 'output') else str(result)
                    results.append(str(output)[:500])  # Limit output

                elif tool_name == "read_file":
                    from src.tools.file_operations import ReadFileTool
                    tool = ReadFileTool()
                    result = tool.execute(args.get("file_path"))
                    results.append(f"[OK] read_file: {args.get('file_path')}")
                    output = result.output if hasattr(result, 'output') else str(result)
                    results.append(str(output)[:500])

                elif tool_name == "search_code":
                    from src.tools.code_operations import SearchCodeTool
                    tool = SearchCodeTool()
                    result = tool.execute(
                        args.get("query"),
                        args.get("file_pattern"),
                        args.get("context_lines", 2)
                    )
                    results.append(f"[OK] search_code: {args.get('query')}")
                    output = result.output if hasattr(result, 'output') else str(result)
                    results.append(str(output)[:500])

                elif tool_name == "analyze_code":
                    from src.tools.code_operations import AnalyzeCodeTool
                    tool = AnalyzeCodeTool()
                    result = tool.execute(args.get("file_path"))
                    results.append(f"[OK] analyze_code: {args.get('file_path')}")
                    output = result.output if hasattr(result, 'output') else str(result)
                    results.append(str(output)[:500])

                else:
                    results.append(f"[SKIP] {tool_name} (not an exploration tool)")

            except Exception as e:
                results.append(f"[FAIL] {tool_name}: {str(e)}")
                logger.warning(f"Exploration tool {tool_name} failed: {e}")

        return "\n\n".join(results)

    def _build_implementation_prompt(
        self,
        request: str,
        analysis: TaskAnalysis,
        exploration_results: str
    ) -> List[Dict[str, str]]:
        """Build Phase 2 prompt after exploration with results.

        Args:
            request: Original user request
            analysis: Task analysis
            exploration_results: Formatted results from exploration

        Returns:
            List of messages for implementation phase
        """
        return [
            {"role": "system", "content": f"""You are an expert coding assistant.

You've explored the workspace and gathered context. Now generate the COMPLETE implementation.

**CRITICAL: Generate ALL write_file calls in this single response**
- Do NOT generate one file at a time
- Call multiple write_file tools in parallel for ALL files needed
- Include complete, working code in each write_file call

**Task Information:**
- Type: {analysis.task_type.value}
- Complexity: {analysis.complexity.value}/5
- Estimated Files: {analysis.estimated_files}
- Risk Level: {analysis.risk_level}

**Exploration Results:**
{exploration_results}

**Your Task:**
Based on the exploration results above, generate ALL write_file tool calls needed to complete this task.
Generate the complete implementation NOW in this single response."""},
            {"role": "user", "content": request}
        ]

    def _build_planning_prompt(
        self,
        request: str,
        analysis: TaskAnalysis
    ) -> List[Dict[str, str]]:
        """Build prompt for plan generation using tool calling.

        The tool schemas are provided via the API, so this prompt focuses on
        planning strategy and reasoning, not JSON formatting.

        Args:
            request: User request
            analysis: Task analysis

        Returns:
            List of messages for LLM
        """
        # Add emphasis based on estimated files
        file_emphasis = ""
        if analysis.estimated_files >= 3:
            file_emphasis = f"""

**CRITICAL: This task requires approximately {analysis.estimated_files} files.**
You MUST generate {analysis.estimated_files} write_file calls (one for each file) in this single response.
DO NOT generate just 1 file - generate ALL {analysis.estimated_files} files NOW."""

        return [
            {"role": "system", "content": f"""You are an expert coding assistant.

**Important: Parallel Tool Execution**
If you intend to call multiple tools and there are no dependencies between tool calls,
make ALL of the independent tool calls in parallel in a SINGLE response.

Maximize use of parallel tool calls where possible:
- Creating multiple files? Generate multiple write_file calls NOW
- Multiple independent operations? Execute them together
- Do NOT wait or generate one at a time

For file creation tasks, generate ALL write_file calls in this response.{file_emphasis}

**Task Information:**
- Type: {analysis.task_type.value}
- Complexity: {analysis.complexity.value}/5
- Estimated Files: {analysis.estimated_files}
- Risk Level: {analysis.risk_level}

**Available Tools:**
You have access to file operations (read_file, write_file, edit_file, list_directory),
code tools (search_code, analyze_code), execution (run_command), and git operations
(git_status, git_diff, git_commit).

**Your Task:**
Analyze the request below and generate tool calls to complete it.
If the task requires multiple files, call write_file multiple times in parallel."""},
            {"role": "user", "content": request}
        ]

    def _parse_tool_calls(
        self,
        tool_calls: List[ToolCall],
        request: str,
        analysis: TaskAnalysis
    ) -> ExecutionPlan:
        """Parse LLM tool calls into ExecutionPlan.

        Converts structured ToolCall objects from LLM into PlanStep objects.
        This eliminates JSON parsing and provides validated, typed responses.

        Args:
            tool_calls: List of tool calls from LLM
            request: Original user request
            analysis: Task analysis

        Returns:
            ExecutionPlan with steps from tool calls

        Raises:
            ValueError: If tool calls are invalid
        """
        # Map tool names to action types
        TOOL_ACTION_MAP = {
            "read_file": "read",
            "write_file": "write",
            "edit_file": "edit",
            "list_directory": "read",
            "search_code": "search",
            "analyze_code": "analyze",
            "run_command": "run",
            "git_status": "git",
            "git_diff": "git",
            "git_commit": "git",
            "delegate_to_subagent": "delegate"
        }

        # Convert tool calls to plan steps
        steps = []
        for i, tool_call in enumerate(tool_calls, start=1):
            # Determine action type from tool name
            action_type = TOOL_ACTION_MAP.get(tool_call.name, "run")

            # Infer dependencies: each step depends on all previous steps
            # (Conservative approach - ExecutionEngine will optimize)
            dependencies = list(range(1, i))

            # Assess risk based on tool and action
            risk = "low"
            if tool_call.name in ["write_file", "edit_file", "git_commit"]:
                risk = "medium"
            elif tool_call.name == "run_command":
                # Check if command is destructive
                command = tool_call.arguments.get("command", "")
                if any(word in command.lower() for word in ["rm ", "del ", "delete", "drop"]):
                    risk = "high"

            # Determine reversibility
            reversible = True
            if tool_call.name in ["git_commit", "run_command"]:
                reversible = False

            # Create step with proper description
            description = self._generate_step_description(tool_call)

            step = PlanStep(
                id=i,
                description=description,
                action_type=action_type,
                tool=tool_call.name,
                arguments=tool_call.arguments,  # Already a dict!
                dependencies=dependencies,
                estimated_time="< 1 min",  # Conservative estimate
                risk=risk,
                reversible=reversible
            )
            steps.append(step)

        if not steps:
            raise ValueError("No tool calls to convert to plan steps")

        # Estimate total time based on number of steps
        total_time = f"{len(steps)} minutes" if len(steps) > 1 else "< 1 minute"

        # Determine overall risk (highest risk among steps)
        risk_levels = {"low": 1, "medium": 2, "high": 3}
        overall_risk = max(steps, key=lambda s: risk_levels[s.risk]).risk

        # Create plan
        return ExecutionPlan(
            task_description=request,
            task_type=analysis.task_type,
            steps=steps,
            total_estimated_time=total_time,
            overall_risk=overall_risk,
            requires_approval=analysis.requires_approval,
            rollback_strategy="Use git to revert changes if needed",
            success_criteria=[
                "All tool calls execute successfully",
                "Task requirements are met"
            ],
            metadata={
                "complexity": analysis.complexity.value,
                "estimated_files": analysis.estimated_files,
                "estimated_iterations": analysis.estimated_iterations,
                "tool_call_count": len(tool_calls)
            }
        )

    def _generate_step_description(self, tool_call: ToolCall) -> str:
        """Generate human-readable description for a tool call.

        Args:
            tool_call: Tool call to describe

        Returns:
            Clear, actionable description
        """
        tool_name = tool_call.name
        args = tool_call.arguments

        # Generate descriptions based on tool type
        if tool_name == "read_file":
            return f"Read file: {args.get('file_path', 'unknown')}"
        elif tool_name == "write_file":
            path = args.get('file_path', 'unknown')
            return f"Create new file: {path}"
        elif tool_name == "edit_file":
            path = args.get('file_path', 'unknown')
            return f"Edit file: {path}"
        elif tool_name == "list_directory":
            path = args.get('directory_path', '.')
            return f"List directory: {path}"
        elif tool_name == "search_code":
            query = args.get('query', 'unknown')
            return f"Search code for: {query}"
        elif tool_name == "analyze_code":
            path = args.get('file_path', 'unknown')
            return f"Analyze code structure: {path}"
        elif tool_name == "run_command":
            cmd = args.get('command', 'unknown')
            # Truncate long commands
            cmd_short = cmd[:50] + "..." if len(cmd) > 50 else cmd
            return f"Run command: {cmd_short}"
        elif tool_name == "git_status":
            return "Check git status"
        elif tool_name == "git_diff":
            staged = args.get('staged', False)
            return f"View {'staged' if staged else 'unstaged'} changes"
        elif tool_name == "git_commit":
            msg = args.get('message', 'unknown')
            msg_short = msg[:40] + "..." if len(msg) > 40 else msg
            return f"Commit changes: {msg_short}"
        elif tool_name == "delegate_to_subagent":
            task = args.get('task_description', 'unknown')
            task_short = task[:50] + "..." if len(task) > 50 else task
            return f"Delegate to subagent: {task_short}"
        else:
            return f"Execute {tool_name}"

    def _create_simple_plan(
        self,
        request: str,
        analysis: TaskAnalysis
    ) -> ExecutionPlan:
        """Create simple fallback plan without LLM.

        Args:
            request: User request
            analysis: Task analysis

        Returns:
            Simple ExecutionPlan
        """
        # Create basic plan based on task type
        if analysis.task_type == TaskType.EXPLAIN:
            steps = [
                PlanStep(
                    id=1,
                    description="Read relevant files to understand the code",
                    action_type="read",
                    estimated_time="< 1 min",
                    risk="low"
                ),
                PlanStep(
                    id=2,
                    description="Provide explanation based on code analysis",
                    action_type="analyze",
                    dependencies=[1],
                    estimated_time="< 1 min",
                    risk="low"
                )
            ]
        elif analysis.task_type == TaskType.SEARCH:
            steps = [
                PlanStep(
                    id=1,
                    description="Search codebase for relevant matches",
                    action_type="search",
                    estimated_time="< 1 min",
                    risk="low"
                )
            ]
        else:
            # Generic plan - Let agent figure out files during direct execution
            # Don't specify tools/arguments - ExecutionEngine will use direct mode
            steps = [
                PlanStep(
                    id=1,
                    description=f"Understand requirements for: {request[:100]}",
                    action_type="analyze",
                    tool=None,  # No tool - use direct LLM analysis
                    arguments={},
                    estimated_time="1-2 min",
                    risk="low"
                ),
                PlanStep(
                    id=2,
                    description="Implement solution based on requirements",
                    action_type="write",
                    tool=None,  # No tool - let agent decide
                    arguments={},
                    dependencies=[1],
                    estimated_time="2-3 min",
                    risk=analysis.risk_level
                ),
                PlanStep(
                    id=3,
                    description="Test and verify implementation works",
                    action_type="verify",
                    tool=None,  # No tool - let agent decide
                    arguments={},
                    dependencies=[2],
                    estimated_time="< 1 min",
                    risk="low"
                )
            ]

        return ExecutionPlan(
            task_description=request,
            task_type=analysis.task_type,
            steps=steps,
            total_estimated_time=f"{len(steps) * 2} minutes",
            overall_risk=analysis.risk_level,
            requires_approval=analysis.requires_approval,
            rollback_strategy="Revert changes using git" if analysis.requires_git else None,
            success_criteria=["Task completed successfully"]
        )

    def _validate_plan(self, plan: ExecutionPlan) -> None:
        """Validate plan is well-formed.

        Args:
            plan: ExecutionPlan to validate

        Raises:
            ValueError: If plan is invalid
        """
        if not plan.steps:
            raise ValueError("Plan must have at least one step")

        # Collect all step IDs
        step_ids = {step.id for step in plan.steps}

        # Check step IDs are unique and sequential
        expected_ids = set(range(1, len(plan.steps) + 1))
        if step_ids != expected_ids:
            raise ValueError(f"Step IDs must be sequential 1..{len(plan.steps)}, got {sorted(step_ids)}")

        # Validate each step
        for step in plan.steps:
            # Check dependencies exist
            for dep_id in step.dependencies:
                if dep_id not in step_ids:
                    raise ValueError(
                        f"Step {step.id} depends on non-existent step {dep_id}"
                    )
                if dep_id >= step.id:
                    raise ValueError(
                        f"Step {step.id} has forward dependency on step {dep_id} "
                        "(dependencies must be earlier steps)"
                    )

            # Validate action type
            valid_actions = {a.value for a in ActionType}
            if step.action_type not in valid_actions:
                raise ValueError(
                    f"Step {step.id} has invalid action_type '{step.action_type}', "
                    f"must be one of {valid_actions}"
                )

            # Validate risk level
            if step.risk not in ["low", "medium", "high"]:
                raise ValueError(
                    f"Step {step.id} has invalid risk '{step.risk}', "
                    "must be low, medium, or high"
                )

        # Check for circular dependencies using DFS
        def has_cycle(node: int, visited: set, rec_stack: set, graph: Dict[int, List[int]]) -> bool:
            visited.add(node)
            rec_stack.add(node)

            for neighbor in graph.get(node, []):
                if neighbor not in visited:
                    if has_cycle(neighbor, visited, rec_stack, graph):
                        return True
                elif neighbor in rec_stack:
                    return True

            rec_stack.remove(node)
            return False

        # Build dependency graph (reverse: step -> steps that depend on it)
        graph: Dict[int, List[int]] = {step.id: [] for step in plan.steps}
        for step in plan.steps:
            for dep_id in step.dependencies:
                graph[dep_id].append(step.id)

        # Check for cycles
        visited: set = set()
        for step in plan.steps:
            if step.id not in visited:
                if has_cycle(step.id, visited, set(), graph):
                    raise ValueError("Plan contains circular dependencies")

    def format_plan_for_user(self, plan: ExecutionPlan) -> str:
        """Format plan for user display.

        Args:
            plan: ExecutionPlan to format

        Returns:
            Formatted string for display
        """
        risk_emoji = {"low": "✅", "medium": "⚠️", "high": "🔴"}

        lines = [
            f"## Execution Plan: {plan.task_type.value.upper()}",
            "",
            f"**Task:** {plan.task_description}",
            f"**Total Time:** {plan.total_estimated_time}",
            f"**Risk Level:** {risk_emoji[plan.overall_risk]} {plan.overall_risk.upper()}",
            f"**Requires Approval:** {'Yes' if plan.requires_approval else 'No'}",
            "",
            "### Steps:",
            ""
        ]

        for step in plan.steps:
            lines.append(str(step))
            lines.append("")

        if plan.rollback_strategy:
            lines.extend([
                "### Rollback Strategy:",
                plan.rollback_strategy,
                ""
            ])

        if plan.success_criteria:
            lines.extend([
                "### Success Criteria:",
                *[f"- {criterion}" for criterion in plan.success_criteria],
                ""
            ])

        return "\n".join(lines)
