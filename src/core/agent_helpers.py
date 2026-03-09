"""
Agent Helper Utilities - Demonstrates AgentInterface usage patterns.

Provides utility classes that depend on AgentInterface instead of CodingAgent,
showing how to build loosely-coupled subsystems.
"""

from typing import Any, Optional

from .agent_interface import AgentInterface


class AgentContextProvider:
    """
    Provides execution context to subsystems via AgentInterface.

    Demonstrates how subsystems should depend on interface, not implementation.
    Used by observability, validation, and other monitoring subsystems.

    Example:
        # Subsystem uses interface
        context_provider = AgentContextProvider(agent)
        context = context_provider.get_full_context()

        # Works with real agent
        provider = AgentContextProvider(coding_agent)

        # Or mock agent for testing
        provider = AgentContextProvider(mock_agent)
    """

    def __init__(self, agent: AgentInterface):
        """
        Initialize context provider.

        Args:
            agent: Agent instance (implements AgentInterface)
        """
        self.agent = agent

    def get_full_context(self) -> dict[str, Any]:
        """
        Get complete execution context for monitoring/observability.

        Returns context including working directory, conversation history,
        session info, and active task.

        Returns:
            dict[str, Any]: Complete context dictionary
        """
        return self.agent.get_context()

    def get_conversation_length(self) -> int:
        """
        Get number of messages in conversation history.

        Returns:
            int: Number of messages
        """
        context = self.agent.get_context()
        return len(context.get('conversation_history', []))

    def get_working_directory(self) -> str:
        """
        Get current working directory.

        Returns:
            str: Working directory path
        """
        context = self.agent.get_context()
        return context.get('working_directory', '.')

    def get_session_id(self) -> str:
        """
        Get current session identifier.

        Returns:
            str: Session ID
        """
        context = self.agent.get_context()
        return context.get('session_id', 'unknown')


class AgentLLMProxy:
    """
    Proxy for LLM calls that adds observability and error handling.

    Demonstrates how to wrap AgentInterface methods for cross-cutting concerns
    like logging, metrics, retries, etc.

    Example:
        proxy = AgentLLMProxy(agent)
        response = proxy.call_with_retry(messages, max_retries=3)
    """

    def __init__(self, agent: AgentInterface):
        """
        Initialize LLM proxy.

        Args:
            agent: Agent instance (implements AgentInterface)
        """
        self.agent = agent
        self.call_count = 0
        self.error_count = 0

    def call_llm(
        self,
        messages: list[dict[str, str]],
        **kwargs
    ) -> str:
        """
        Call LLM with tracking.

        Wraps agent.call_llm() with call counting and error tracking.

        Args:
            messages: Conversation messages
            **kwargs: Additional LLM parameters

        Returns:
            str: LLM response

        Raises:
            RuntimeError: LLM call failed
        """
        try:
            self.call_count += 1
            return self.agent.call_llm(messages, **kwargs)
        except Exception as e:
            self.error_count += 1
            raise

    def call_with_retry(
        self,
        messages: list[dict[str, str]],
        max_retries: int = 3,
        **kwargs
    ) -> str | None:
        """
        Call LLM with automatic retry on failure.

        Args:
            messages: Conversation messages
            max_retries: Maximum retry attempts
            **kwargs: Additional LLM parameters

        Returns:
            str: LLM response, or None if all retries failed
        """
        for attempt in range(max_retries):
            try:
                return self.call_llm(messages, **kwargs)
            except Exception as e:
                if attempt == max_retries - 1:
                    # Last attempt failed
                    return None
                # Continue to next retry
                continue

        return None

    def get_statistics(self) -> dict[str, int]:
        """
        Get proxy statistics.

        Returns:
            dict[str, int]: Call count and error count
        """
        return {
            "call_count": self.call_count,
            "error_count": self.error_count,
            "success_rate": (
                (self.call_count - self.error_count) / self.call_count
                if self.call_count > 0
                else 0.0
            )
        }


class AgentToolProxy:
    """
    Proxy for tool execution that adds validation and logging.

    Demonstrates how to wrap AgentInterface.execute_tool() for additional
    functionality like input validation, output verification, etc.

    Example:
        proxy = AgentToolProxy(agent)
        result = proxy.execute_with_validation('write_file', file_path='test.py', content='...')
    """

    def __init__(self, agent: AgentInterface):
        """
        Initialize tool proxy.

        Args:
            agent: Agent instance (implements AgentInterface)
        """
        self.agent = agent
        self.execution_history: list[dict[str, Any]] = []

    def execute_tool(
        self,
        tool_name: str,
        **params
    ) -> Any:
        """
        Execute tool with tracking.

        Wraps agent.execute_tool() with execution history tracking.

        Args:
            tool_name: Tool name
            **params: Tool parameters

        Returns:
            Any: Tool result
        """
        result = self.agent.execute_tool(tool_name, **params)
        self.execution_history.append({
            "tool": tool_name,
            "params": params,
            "result": result
        })
        return result

    def execute_with_validation(
        self,
        tool_name: str,
        **params
    ) -> Any:
        """
        Execute tool with parameter validation.

        Args:
            tool_name: Tool name
            **params: Tool parameters

        Returns:
            Any: Tool result

        Raises:
            ValueError: Invalid parameters
        """
        # Example validation: check required params
        if tool_name == 'write_file':
            if 'file_path' not in params or 'content' not in params:
                raise ValueError("write_file requires file_path and content")

        return self.execute_tool(tool_name, **params)

    def get_execution_count(self) -> int:
        """
        Get number of tool executions.

        Returns:
            int: Execution count
        """
        return len(self.execution_history)

    def get_tool_usage(self) -> dict[str, int]:
        """
        Get tool usage statistics.

        Returns:
            dict[str, int]: Tool name -> execution count
        """
        usage = {}
        for entry in self.execution_history:
            tool = entry['tool']
            usage[tool] = usage.get(tool, 0) + 1
        return usage
