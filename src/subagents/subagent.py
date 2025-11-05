"""SubAgent implementation with independent context and specialized capabilities.

A SubAgent is an independent AI assistant that:
- Operates with its own context window (no pollution of main agent)
- Has specialized system prompts for domain expertise
- Inherits and restricts tools from the main agent
- Can use a different model than the main agent
- Returns structured, aggregated results
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, TYPE_CHECKING
from pathlib import Path
import time
import logging
import uuid

if TYPE_CHECKING:
    from src.core.agent import CodingAgent
    from src.subagents.config import SubAgentConfig

from src.memory import MemoryManager, TaskContext
from src.tools import ToolExecutor
from src.llm import LLMBackend, OllamaBackend, OpenAIBackend, LLMConfig, LLMBackendType

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
        status = "✅ SUCCESS" if self.success else "❌ FAILED"
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
    """Independent subagent with specialized capabilities.

    A SubAgent operates independently from the main agent with:
    - Separate context window (no pollution)
    - Specialized system prompts
    - Restricted tool access
    - Optional different model
    - Focused execution

    Example:
        >>> config = SubAgentConfig.load("code-reviewer")
        >>> subagent = SubAgent(config, main_agent)
        >>> result = subagent.execute("Review src/auth.py for security")
        >>> print(result.output)
    """

    def __init__(
        self,
        config: 'SubAgentConfig',
        main_agent: 'CodingAgent',
        enable_verification: bool = True,
        enable_rollback: bool = False  # Subagents typically don't need rollback
    ):
        """Initialize subagent.

        Args:
            config: SubAgentConfig with name, description, tools, prompt
            main_agent: Main CodingAgent to inherit from
            enable_verification: Whether to verify outputs (default: True)
            enable_rollback: Whether to enable rollback (default: False)
        """
        self.config = config
        self.main_agent = main_agent
        self.enable_verification = enable_verification
        self.enable_rollback = enable_rollback

        # Generate unique session ID for this subagent
        self.session_id = str(uuid.uuid4())[:8]

        # Initialize LLM (can be different from main agent)
        self.llm = self._initialize_llm()

        # Initialize independent memory system
        self.memory = self._initialize_memory()

        # Initialize restricted tool executor
        self.tool_executor = self._initialize_tools()

        # Track execution history
        self.execution_history: List[SubAgentResult] = []

        logger.info(
            f"SubAgent [{self.config.name}] initialized "
            f"(model={self.config.model or 'inherit'}, "
            f"tools={len(self.tool_executor.tools)})"
        )

    def _initialize_llm(self) -> LLMBackend:
        """Initialize LLM backend for subagent.

        Returns:
            LLM backend (can be different from main agent)
        """
        # If config specifies a model, use it; otherwise inherit from main
        model_name = self.config.model or self.main_agent.model_name

        # Get backend type from main agent
        backend_type = self.main_agent.llm.config.backend_type

        # Create config
        llm_config = LLMConfig(
            backend_type=backend_type,
            model_name=model_name,
            base_url=self.main_agent.llm.config.base_url,
            context_window=self.config.context_window or self.main_agent.context_window,
            num_ctx=self.config.context_window or self.main_agent.context_window,
        )

        # Create backend
        if backend_type == LLMBackendType.OLLAMA:
            return OllamaBackend(llm_config)
        elif backend_type == LLMBackendType.OPENAI:
            # Get API key from main agent's backend
            api_key = getattr(self.main_agent.llm, 'api_key', None)
            api_key_env = getattr(self.main_agent.llm, 'api_key_env', 'OPENAI_API_KEY')
            return OpenAIBackend(llm_config, api_key=api_key, api_key_env=api_key_env)
        else:
            raise ValueError(f"Unsupported backend: {backend_type}")

    def _initialize_memory(self) -> MemoryManager:
        """Initialize independent memory system.

        Returns:
            MemoryManager with independent context
        """
        # Create independent memory with same token budget structure
        memory = MemoryManager(
            total_context_tokens=self.llm.config.context_window,
            working_memory_tokens=int(self.llm.config.context_window * 0.4),
            episodic_memory_tokens=int(self.llm.config.context_window * 0.2),
            load_file_memories=False,  # Subagents don't need file memories
            starting_directory=self.main_agent.working_directory
        )

        return memory

    def _initialize_tools(self) -> ToolExecutor:
        """Initialize restricted tool executor.

        Returns:
            ToolExecutor with only allowed tools
        """
        # Create new executor
        restricted_executor = ToolExecutor(hook_manager=self.main_agent.hook_manager)

        # If config specifies tools, only register those
        if self.config.tools:
            allowed_tool_names = set(self.config.tools)

            for tool_name, tool_instance in self.main_agent.tool_executor.tools.items():
                # Check if tool is allowed (case-insensitive matching)
                tool_class_name = tool_instance.__class__.__name__

                # Match by tool name or class name
                if (tool_name in allowed_tool_names or
                    tool_class_name in allowed_tool_names or
                    tool_class_name.replace('Tool', '') in allowed_tool_names):
                    restricted_executor.register_tool(tool_instance)
                    logger.debug(f"SubAgent [{self.config.name}]: Allowed tool {tool_class_name}")
        else:
            # If no tools specified, inherit all tools
            for tool_name, tool_instance in self.main_agent.tool_executor.tools.items():
                restricted_executor.register_tool(tool_instance)

        logger.info(
            f"SubAgent [{self.config.name}]: Initialized with {len(restricted_executor.tools)} tools"
        )

        return restricted_executor

    def execute(
        self,
        task_description: str,
        context: Optional[Dict[str, Any]] = None,
        max_iterations: int = 5
    ) -> SubAgentResult:
        """Execute a task with this subagent.

        Args:
            task_description: Description of task to execute
            context: Optional additional context
            max_iterations: Maximum tool-calling iterations (default: 5)

        Returns:
            SubAgentResult with execution details
        """
        start_time = time.time()

        logger.info(f"SubAgent [{self.config.name}]: Starting execution")
        logger.debug(f"Task: {task_description[:100]}...")

        try:
            # Create task context
            task_context = TaskContext(
                task_id=self.session_id,
                description=task_description,
                task_type="subagent",
                key_concepts=[]
            )
            self.memory.set_task_context(task_context)

            # Add user message to memory
            self.memory.add_user_message(task_description)

            # Build context with specialized system prompt
            llm_context = self._build_context(task_description, context or {})

            # Execute with tool calling loop
            output, tool_calls = self._execute_with_tools(
                llm_context,
                max_iterations=max_iterations
            )

            # Add assistant response to memory
            self.memory.add_assistant_message(output)

            # Create result
            execution_time = time.time() - start_time
            result = SubAgentResult(
                success=True,
                subagent_name=self.config.name,
                output=output,
                metadata={
                    "task_description": task_description,
                    "model": self.llm.config.model_name,
                    "context_window": self.llm.config.context_window,
                    "tools_available": list(self.tool_executor.tools.keys()),
                    "iterations": len(tool_calls)
                },
                tool_calls=tool_calls,
                execution_time=execution_time
            )

            # Track in history
            self.execution_history.append(result)

            logger.info(
                f"SubAgent [{self.config.name}]: ✅ Success "
                f"(time={execution_time:.2f}s, tools={len(tool_calls)})"
            )

            return result

        except Exception as e:
            execution_time = time.time() - start_time
            error_msg = f"SubAgent execution failed: {e}"
            logger.error(f"SubAgent [{self.config.name}]: ❌ {error_msg}")

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

    def _build_context(
        self,
        task_description: str,
        additional_context: Dict[str, Any]
    ) -> List[Dict[str, str]]:
        """Build LLM context with specialized system prompt.

        Args:
            task_description: Task to execute
            additional_context: Additional context to include

        Returns:
            List of messages for LLM
        """
        # Start with specialized system prompt from config
        system_message = self.config.system_prompt

        # Add available tools description
        tools_description = self.tool_executor.get_tools_description()
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

        # Build context messages
        context = [
            {"role": "system", "content": system_message}
        ]

        # Add conversation history from memory
        for msg in self.memory.working_memory.messages:
            context.append({
                "role": msg.role,
                "content": msg.content
            })

        return context

    def _execute_with_tools(
        self,
        context: List[Dict[str, str]],
        max_iterations: int
    ) -> tuple[str, List[Dict[str, Any]]]:
        """Execute with tool calling loop.

        Args:
            context: LLM context
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

            # Generate LLM response
            response = self.llm.generate(current_context)
            response_content = response.content

            # Parse for tool calls
            parsed = tool_parser.parse(response_content)

            if not parsed.has_tool_calls:
                # No tool calls - we're done
                logger.debug(f"SubAgent [{self.config.name}]: No tool calls, finishing")
                return response_content, all_tool_calls

            # Execute tool calls
            logger.debug(f"SubAgent [{self.config.name}]: Executing {len(parsed.tool_calls)} tool(s)")
            tool_results = []

            for tool_call in parsed.tool_calls:
                try:
                    result = self.tool_executor.execute_tool(
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

        final_response = self.llm.generate(current_context)
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
            if result["success"]:
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
            "model": self.llm.config.model_name,
            "context_window": self.llm.config.context_window,
            "tools_available": len(self.tool_executor.tools)
        }
