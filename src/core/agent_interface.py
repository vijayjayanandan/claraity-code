"""
Agent Interface - Abstract base class for agent operations.

Provides a decoupling layer between subsystems and agent implementation.
Enables testing subsystems in isolation with MockAgent.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any
import threading


class AgentInterface(ABC):
    """
    Abstract interface for agent operations.

    Defines the contract between subsystems (ValidationSystem, MemoryManager,
    Observability) and the agent implementation (CodingAgent).

    Benefits:
    - Loose coupling: Subsystems depend on interface, not concrete implementation
    - Testability: MockAgent enables testing without real LLM/tools
    - Flexibility: Can swap agent implementations without changing subsystems
    - Clean architecture: Explicit contracts between layers

    Example:
        # Subsystem uses interface
        def __init__(self, agent: AgentInterface):
            self.agent = agent

        # Can use real agent
        validator = ValidationSystem(coding_agent)

        # Or mock agent for testing
        validator = ValidationSystem(mock_agent)
    """

    @abstractmethod
    def call_llm(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        stream: bool = False,
        **kwargs
    ) -> str:
        """
        Call LLM with conversation messages, returns response text.

        Args:
            messages: Conversation history in OpenAI format
                     [{'role': 'user', 'content': '...'}, ...]
            temperature: Sampling temperature (0.0 = deterministic, 1.0 = creative)
            max_tokens: Maximum tokens in response
            stream: Enable streaming response (not supported in interface v1)
            **kwargs: Additional LLM-specific parameters

        Returns:
            str: LLM response text

        Raises:
            LLMError: LLM API error (rate limit, network, etc.)
            TimeoutError: Request timeout
            RateLimitError: Rate limit exceeded

        Example:
            response = agent.call_llm(
                [{'role': 'user', 'content': 'Hello'}],
                temperature=0.5
            )
        """
        pass

    @abstractmethod
    def execute_tool(self, tool_name: str, **params) -> Any:
        """
        Execute a tool by name with parameters, returns tool result.

        Args:
            tool_name: Tool name (e.g., 'write_file', 'run_command', 'search_code')
            **params: Tool-specific parameters (varies by tool)

        Returns:
            Any: Tool result (structure varies by tool)

        Raises:
            ToolNotFoundError: Tool does not exist
            ToolExecutionError: Tool execution failed

        Example:
            result = agent.execute_tool(
                'write_file',
                file_path='test.py',
                content='print(1)'
            )
        """
        pass

    @abstractmethod
    def get_context(self) -> Dict[str, Any]:
        """
        Get current execution context.

        Returns context information needed by subsystems:
        - working_directory: Current working directory
        - conversation_history: Recent conversation messages
        - active_task: Current task being executed
        - session_id: Current session identifier

        Returns:
            Dict[str, Any]: Context dictionary

        Example:
            context = agent.get_context()
            print(context['working_directory'])
            print(context['active_task'])
        """
        pass

    @abstractmethod
    def update_memory(self, key: str, value: Any) -> None:
        """
        Update agent memory with key-value pair.

        Stores information in episodic or semantic memory for later retrieval.
        Used by subsystems to persist state across execution.

        Args:
            key: Memory key (e.g., 'last_test_result', 'validation_status')
            value: Value to store (any JSON-serializable type)

        Raises:
            MemoryError: Memory update failed

        Example:
            agent.update_memory('test_result', {'passed': 10, 'failed': 2})
            agent.update_memory('validation_status', 'passed')
        """
        pass


class MockAgent(AgentInterface):
    """
    Mock agent implementation for testing subsystems in isolation.

    Records all calls to interface methods, returns mocked responses.
    Enables fast, deterministic testing without real LLM/tools.

    Attributes:
        call_history: List of all call_llm invocations
        tool_history: List of all execute_tool invocations
        memory: Dictionary of memory updates
        context: Dictionary of context to return

    Example:
        # Test subsystem with mock
        mock_agent = MockAgent()
        validator = ValidationSystem(mock_agent)

        result = validator.validate()

        # Verify LLM was called
        assert len(mock_agent.call_history) > 0
        assert 'validate' in mock_agent.call_history[0][0][0]['content']

        # Verify tool was called
        assert len(mock_agent.tool_history) > 0
        assert mock_agent.tool_history[0][0] == 'run_command'
    """

    def __init__(
        self,
        mock_llm_response: str = "Mocked LLM response",
        mock_tool_result: Any = None,
        mock_context: Dict[str, Any] = None
    ):
        """
        Initialize MockAgent with configurable mock responses.

        Args:
            mock_llm_response: Default LLM response (can be overridden per call)
            mock_tool_result: Default tool result (can be overridden per call)
            mock_context: Context dictionary to return (default: minimal context)
        """
        # Thread safety: Lock for all mutable state
        self._lock = threading.RLock()  # Reentrant lock

        self.call_history: List[tuple] = []
        self.tool_history: List[tuple] = []
        self.memory: Dict[str, Any] = {}

        self._mock_llm_response = mock_llm_response
        self._mock_tool_result = mock_tool_result or {"status": "success", "mocked": True}
        self._mock_context = mock_context or {
            "working_directory": ".",
            "conversation_history": [],
            "active_task": None,
            "session_id": "mock_session"
        }

    def call_llm(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        stream: bool = False,
        **kwargs
    ) -> str:
        """
        Mock LLM call - records invocation, returns mocked response.

        Records all parameters for verification in tests.
        Thread-safe.
        """
        with self._lock:
            self.call_history.append((messages, temperature, max_tokens, stream, kwargs))
            return self._mock_llm_response

    def execute_tool(self, tool_name: str, **params) -> Any:
        """
        Mock tool execution - records invocation, returns mocked result.

        Records tool name and parameters for verification in tests.
        Thread-safe.
        """
        with self._lock:
            self.tool_history.append((tool_name, params))
            return self._mock_tool_result

    def get_context(self) -> Dict[str, Any]:
        """
        Return mock context.

        Returns configurable context dictionary (set in __init__).
        """
        return self._mock_context

    def update_memory(self, key: str, value: Any) -> None:
        """
        Mock memory update - stores in internal dictionary.

        Enables verification of memory updates in tests.
        Thread-safe.
        """
        with self._lock:
            self.memory[key] = value

    def reset(self) -> None:
        """
        Reset all history and memory.

        Useful for reusing MockAgent across multiple test cases.
        Thread-safe.
        """
        with self._lock:
            self.call_history.clear()
            self.tool_history.clear()
            self.memory.clear()

    def set_llm_response(self, response: str) -> None:
        """
        Change the mocked LLM response.

        Useful for simulating different LLM behaviors in tests.
        Thread-safe.
        """
        with self._lock:
            self._mock_llm_response = response

    def set_tool_result(self, result: Any) -> None:
        """
        Change the mocked tool result.

        Useful for simulating different tool behaviors in tests.
        Thread-safe.
        """
        with self._lock:
            self._mock_tool_result = result

    def set_context(self, context: Dict[str, Any]) -> None:
        """
        Change the mocked context.

        Useful for testing subsystems under different context conditions.
        Thread-safe.
        """
        with self._lock:
            self._mock_context = context
