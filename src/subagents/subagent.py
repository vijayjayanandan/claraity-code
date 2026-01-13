"""SubAgent implementation with independent context and shared capabilities.

A SubAgent is a lightweight wrapper that:
- Operates with its own conversation context (no pollution of main agent)
- Has specialized system prompts for domain expertise
- Uses the main agent's LLM and tools (no duplication)
- Returns structured results
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, TYPE_CHECKING
import time
import logging
import uuid

if TYPE_CHECKING:
    from src.core.agent_interface import AgentInterface
    from src.subagents.config import SubAgentConfig

logger = logging.getLogger(__name__)


@dataclass
class SubAgentResult:
    """Result from a subagent execution.

    Attributes:
        success: Whether execution succeeded
        subagent_name: Name of the subagent
        output: Primary output content
        metadata: Additional information (tools used, time, etc.)
        error: Error message if failed
        tool_calls: Tools that were called
        execution_time: Time taken in seconds
    """
    success: bool
    subagent_name: str
    output: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    execution_time: float = 0.0

    def __str__(self) -> str:
        """Human-readable representation."""
        status = "[OK] SUCCESS" if self.success else "[FAIL] FAILED"
        lines = [
            f"SubAgent [{self.subagent_name}]: {status}",
            f"Execution Time: {self.execution_time:.2f}s",
        ]

        if self.tool_calls:
            lines.append(f"Tools Used: {len(self.tool_calls)}")

        if self.error:
            lines.append(f"Error: {self.error}")

        if self.output and not self.error:
            preview = self.output[:200] + "..." if len(self.output) > 200 else self.output
            lines.append(f"Output: {preview}")

        return "\n".join(lines)


class SubAgent:
    """Lightweight subagent with specialized capabilities.

    A SubAgent operates with isolated context but shares the main agent's
    infrastructure (LLM, tools). This ensures:
    - No context pollution between main agent and subagent
    - Specialized system prompts for domain expertise
    - Consistent tool behavior (same tools as main agent)
    - No infrastructure duplication (no separate LLM/memory/tools)

    Example:
        >>> config = SubAgentConfig.load("code-reviewer")
        >>> subagent = SubAgent(config, main_agent)
        >>> result = subagent.execute("Review src/auth.py for security")
        >>> print(result.output)
    """

    def __init__(
        self,
        config: 'SubAgentConfig',
        main_agent: 'AgentInterface',
    ):
        """Initialize subagent.

        Args:
            config: SubAgentConfig with name, description, system_prompt
            main_agent: Main agent (provides LLM and tools)
        """
        self.config = config
        self.main_agent = main_agent

        # Generate unique session ID for this subagent
        self.session_id = str(uuid.uuid4())[:8]

        # Track execution history
        self.execution_history: List[SubAgentResult] = []

        logger.info(
            f"SubAgent [{self.config.name}] initialized "
            f"(using main agent's LLM and {len(self.main_agent.tool_executor.tools)} tools)"
        )

    def execute(
        self,
        task_description: str,
        context: Optional[Dict[str, Any]] = None,
        max_iterations: int = 5
    ) -> SubAgentResult:
        """Execute a task with this subagent.

        Args:
            task_description: Description of task to execute
            context: Optional additional context (currently unused, for future extension)
            max_iterations: Maximum tool-calling iterations (default: 5)

        Returns:
            SubAgentResult with execution details
        """
        start_time = time.time()

        logger.info(f"SubAgent [{self.config.name}]: Starting execution")
        logger.debug(f"Task: {task_description[:100]}...")

        try:
            # Build fresh context with specialized system prompt
            messages = self._build_context(task_description)

            # Execute with tool calling loop (using main agent's infrastructure)
            output, tool_calls = self._execute_with_tools(
                messages,
                max_iterations=max_iterations
            )

            # Create result
            execution_time = time.time() - start_time
            result = SubAgentResult(
                success=True,
                subagent_name=self.config.name,
                output=output,
                metadata={
                    "task_description": task_description,
                    "model": self.main_agent.llm.config.model_name,
                    "tools_available": list(self.main_agent.tool_executor.tools.keys()),
                    "iterations": len(tool_calls)
                },
                tool_calls=tool_calls,
                execution_time=execution_time
            )

            # Track in history
            self.execution_history.append(result)

            logger.info(
                f"SubAgent [{self.config.name}]: [OK] Success "
                f"(time={execution_time:.2f}s, tools={len(tool_calls)})"
            )

            return result

        except Exception as e:
            execution_time = time.time() - start_time
            error_msg = f"SubAgent execution failed: {e}"
            logger.error(f"SubAgent [{self.config.name}]: [FAIL] {error_msg}")

            result = SubAgentResult(
                success=False,
                subagent_name=self.config.name,
                output="",
                metadata={
                    "task_description": task_description,
                    "error_type": type(e).__name__
                },
                error=str(e),
                execution_time=execution_time
            )

            self.execution_history.append(result)

            return result

    def _build_context(self, task_description: str) -> List[Dict[str, str]]:
        """Build fresh LLM context with specialized system prompt.

        Args:
            task_description: Task to execute

        Returns:
            List of messages for LLM (fresh context, no history)
        """
        # Start with specialized system prompt from config
        system_message = self.config.system_prompt

        # Add available tools description
        tools_description = self.main_agent.tool_executor.get_tools_description()
        system_message += f"\n\n## Available Tools:\n{tools_description}"

        # Add tool calling format instructions
        system_message += """

## Tool Calling Format:

To use a tool, respond with:
<TOOL_CALL>
tool: tool_name
arguments:
  arg1: value1
  arg2: value2
</TOOL_CALL>

You can call multiple tools in one response. After tool execution, you'll receive results and can call more tools or provide your final answer.
"""

        # Build fresh context (no conversation history - that's the point!)
        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": task_description}
        ]

        return messages

    def _execute_with_tools(
        self,
        context: List[Dict[str, str]],
        max_iterations: int
    ) -> tuple[str, List[Dict[str, Any]]]:
        """Execute with tool calling loop using main agent's infrastructure.

        Args:
            context: LLM context (messages)
            max_iterations: Maximum iterations

        Returns:
            Tuple of (final_output, tool_calls)
        """
        from src.tools.tool_parser import ToolCallParser

        tool_parser = ToolCallParser()
        current_context = context.copy()
        all_tool_calls = []

        for iteration in range(max_iterations):
            logger.debug(f"SubAgent [{self.config.name}]: Iteration {iteration + 1}/{max_iterations}")

            # Generate LLM response using MAIN AGENT's LLM
            response = self.main_agent.llm.generate(current_context)
            response_content = response.content

            # Parse for tool calls
            parsed = tool_parser.parse(response_content)

            if not parsed.has_tool_calls:
                # No tool calls - we're done
                logger.debug(f"SubAgent [{self.config.name}]: No tool calls, finishing")
                return response_content, all_tool_calls

            # Execute tool calls using MAIN AGENT's tool executor
            logger.debug(f"SubAgent [{self.config.name}]: Executing {len(parsed.tool_calls)} tool(s)")
            tool_results = []

            for tool_call in parsed.tool_calls:
                try:
                    result = self.main_agent.tool_executor.execute_tool(
                        tool_call.tool,
                        **tool_call.arguments
                    )

                    tool_result = {
                        "tool": tool_call.tool,
                        "arguments": tool_call.arguments,
                        "success": result.is_success(),
                        "result": result.output if result.is_success() else result.error
                    }
                    tool_results.append(tool_result)
                    all_tool_calls.append(tool_result)

                except Exception as e:
                    tool_result = {
                        "tool": tool_call.tool,
                        "arguments": tool_call.arguments,
                        "success": False,
                        "error": str(e)
                    }
                    tool_results.append(tool_result)
                    all_tool_calls.append(tool_result)

            # Format tool results for LLM
            tool_results_text = self._format_tool_results(tool_results)

            # Add to context
            current_context.append({"role": "assistant", "content": response_content})
            current_context.append({
                "role": "user",
                "content": f"Tool results:\n\n{tool_results_text}\n\nProvide your response based on these results."
            })

        # Max iterations reached - generate final summary
        logger.warning(f"SubAgent [{self.config.name}]: Max iterations reached")
        current_context.append({
            "role": "user",
            "content": "Provide a summary of what you've learned from the tools."
        })

        final_response = self.main_agent.llm.generate(current_context)
        return final_response.content, all_tool_calls

    def _format_tool_results(self, results: List[Dict[str, Any]]) -> str:
        """Format tool results for LLM.

        Args:
            results: List of tool results

        Returns:
            Formatted string
        """
        formatted = []
        for i, result in enumerate(results, 1):
            if result.get("success"):
                formatted.append(
                    f"Tool {i}: {result['tool']}\n"
                    f"Result: {result['result']}"
                )
            else:
                formatted.append(
                    f"Tool {i}: {result['tool']}\n"
                    f"Error: {result.get('error', 'Unknown error')}"
                )
        return "\n\n".join(formatted)

    def get_statistics(self) -> Dict[str, Any]:
        """Get subagent statistics.

        Returns:
            Statistics dictionary
        """
        total_executions = len(self.execution_history)
        successful = sum(1 for r in self.execution_history if r.success)
        failed = total_executions - successful

        total_time = sum(r.execution_time for r in self.execution_history)
        avg_time = total_time / total_executions if total_executions > 0 else 0

        total_tools = sum(len(r.tool_calls) for r in self.execution_history)
        avg_tools = total_tools / total_executions if total_executions > 0 else 0

        return {
            "subagent_name": self.config.name,
            "total_executions": total_executions,
            "successful": successful,
            "failed": failed,
            "success_rate": successful / total_executions if total_executions > 0 else 0,
            "total_execution_time": total_time,
            "average_execution_time": avg_time,
            "total_tool_calls": total_tools,
            "average_tool_calls": avg_tools,
            "model": self.main_agent.llm.config.model_name,
            "tools_available": len(self.main_agent.tool_executor.tools)
        }
