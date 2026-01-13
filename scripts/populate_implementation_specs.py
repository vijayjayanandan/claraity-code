"""
Populate ClarAIty DB with detailed implementation specs for Phase 0 components.

Adds method signatures, acceptance criteria, and implementation patterns for:
- LLM_FAILURE_HANDLER (Phase 0.4)
- AGENT_INTERFACE (Phase 0.5)

Based on:
- Industry best practices (OpenAI retry logic, interface patterns)
- Architecture requirements from STATE_OF_THE_ART_AGENT_ARCHITECTURE.md
- Production-grade error handling patterns
"""

import sqlite3
import json
import uuid
from pathlib import Path
from datetime import datetime

DB_PATH = Path(".clarity/ai-coding-agent.db")


def generate_id(prefix: str) -> str:
    """Generate unique ID with prefix."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def insert_method(cursor, component_id: str, method_data: dict):
    """Insert method signature into component_methods table."""

    method_id = generate_id("method")

    cursor.execute("""
        INSERT INTO component_methods (
            id, component_id, method_name, signature, return_type,
            description, parameters, raises, example_usage, is_abstract
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        method_id,
        component_id,
        method_data["method_name"],
        method_data["signature"],
        method_data.get("return_type"),
        method_data.get("description"),
        json.dumps(method_data.get("parameters", [])),
        json.dumps(method_data.get("raises", [])),
        method_data.get("example_usage"),
        method_data.get("is_abstract", True)
    ))

    return method_id


def insert_acceptance_criterion(cursor, component_id: str, criterion_data: dict):
    """Insert acceptance criterion into component_acceptance_criteria table."""

    criterion_id = generate_id("criterion")

    cursor.execute("""
        INSERT INTO component_acceptance_criteria (
            id, component_id, criteria_type, description,
            target_value, validation_method, priority, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        criterion_id,
        component_id,
        criterion_data["criteria_type"],
        criterion_data["description"],
        criterion_data.get("target_value"),
        criterion_data.get("validation_method"),
        criterion_data.get("priority", "required"),
        criterion_data.get("status", "pending")
    ))

    return criterion_id


def insert_pattern(cursor, component_id: str, pattern_data: dict):
    """Insert implementation pattern into component_patterns table."""

    pattern_id = generate_id("pattern")

    cursor.execute("""
        INSERT INTO component_patterns (
            id, component_id, pattern_name, pattern_type,
            description, code_example, antipatterns, reference_links
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        pattern_id,
        component_id,
        pattern_data["pattern_name"],
        pattern_data["pattern_type"],
        pattern_data["description"],
        pattern_data.get("code_example"),
        pattern_data.get("antipatterns"),
        pattern_data.get("reference_links")
    ))

    return pattern_id


def populate_llm_failure_handler(cursor):
    """Populate LLM_FAILURE_HANDLER implementation specs."""

    component_id = "LLM_FAILURE_HANDLER"

    print(f"\n[POPULATE] {component_id}")
    print("=" * 80)

    # Method 1: handle_timeout
    methods_added = 0
    methods_added += 1
    insert_method(cursor, component_id, {
        "method_name": "handle_timeout",
        "signature": "handle_timeout(self, func: Callable, timeout_seconds: float = 30.0, max_retries: int = 3) -> Any",
        "return_type": "Any",
        "description": "Execute function with timeout and automatic retry on TimeoutError",
        "parameters": [
            {
                "name": "func",
                "type": "Callable",
                "description": "Function to execute (typically LLM call)",
                "required": True
            },
            {
                "name": "timeout_seconds",
                "type": "float",
                "description": "Maximum execution time in seconds",
                "required": False,
                "default": "30.0"
            },
            {
                "name": "max_retries",
                "type": "int",
                "description": "Maximum retry attempts on timeout",
                "required": False,
                "default": "3"
            }
        ],
        "raises": ["TimeoutError", "LLMError"],
        "example_usage": "result = handler.handle_timeout(lambda: llm.chat(messages), timeout_seconds=60.0)",
        "is_abstract": False
    })

    # Method 2: handle_rate_limit
    methods_added += 1
    insert_method(cursor, component_id, {
        "method_name": "handle_rate_limit",
        "signature": "handle_rate_limit(self, func: Callable, max_retries: int = 5) -> Any",
        "return_type": "Any",
        "description": "Execute function with automatic retry on rate limit errors using exponential backoff",
        "parameters": [
            {
                "name": "func",
                "type": "Callable",
                "description": "Function to execute (typically LLM call)",
                "required": True
            },
            {
                "name": "max_retries",
                "type": "int",
                "description": "Maximum retry attempts (rate limits may require longer waits)",
                "required": False,
                "default": "5"
            }
        ],
        "raises": ["RateLimitError", "LLMError"],
        "example_usage": "result = handler.handle_rate_limit(lambda: llm.chat(messages))",
        "is_abstract": False
    })

    # Method 3: handle_api_error
    methods_added += 1
    insert_method(cursor, component_id, {
        "method_name": "handle_api_error",
        "signature": "handle_api_error(self, error: Exception) -> tuple[bool, str]",
        "return_type": "tuple[bool, str]",
        "description": "Classify API error as retryable or fatal, return (is_retryable, error_message)",
        "parameters": [
            {
                "name": "error",
                "type": "Exception",
                "description": "API error to classify",
                "required": True
            }
        ],
        "raises": [],
        "example_usage": "is_retryable, msg = handler.handle_api_error(error)",
        "is_abstract": False
    })

    # Method 4: execute_with_retry
    methods_added += 1
    insert_method(cursor, component_id, {
        "method_name": "execute_with_retry",
        "signature": "execute_with_retry(self, func: Callable, max_attempts: int = 3, backoff_base: float = 2.0) -> Any",
        "return_type": "Any",
        "description": "Execute function with exponential backoff retry on failure (1s, 2s, 4s, 8s...)",
        "parameters": [
            {
                "name": "func",
                "type": "Callable",
                "description": "Function to execute",
                "required": True
            },
            {
                "name": "max_attempts",
                "type": "int",
                "description": "Maximum execution attempts",
                "required": False,
                "default": "3"
            },
            {
                "name": "backoff_base",
                "type": "float",
                "description": "Base for exponential backoff (delay = backoff_base ** attempt)",
                "required": False,
                "default": "2.0"
            }
        ],
        "raises": ["LLMError"],
        "example_usage": "result = handler.execute_with_retry(lambda: llm.chat(messages), max_attempts=5)",
        "is_abstract": False
    })

    # Method 5: validate_response
    methods_added += 1
    insert_method(cursor, component_id, {
        "method_name": "validate_response",
        "signature": "validate_response(self, response: str) -> bool",
        "return_type": "bool",
        "description": "Validate LLM response is well-formed (not empty, not truncated, valid content)",
        "parameters": [
            {
                "name": "response",
                "type": "str",
                "description": "LLM response to validate",
                "required": True
            }
        ],
        "raises": ["ValidationError"],
        "example_usage": "if handler.validate_response(response): process(response)",
        "is_abstract": False
    })

    print(f"[OK] Added {methods_added} method signatures")

    # Acceptance Criteria
    criteria_added = 0

    criteria_added += 1
    insert_acceptance_criterion(cursor, component_id, {
        "criteria_type": "test_coverage",
        "description": "Unit test coverage for all retry logic and error handling",
        "target_value": "90%+",
        "validation_method": "pytest tests/test_llm_failure_handler.py --cov=src.llm.failure_handler",
        "priority": "required"
    })

    criteria_added += 1
    insert_acceptance_criterion(cursor, component_id, {
        "criteria_type": "integration",
        "description": "Integration with LLMBackend (wrap all LLM calls with failure handler)",
        "target_value": "All LLM calls protected",
        "validation_method": "Manual verification: OpenAIBackend.chat() uses failure handler",
        "priority": "required"
    })

    criteria_added += 1
    insert_acceptance_criterion(cursor, component_id, {
        "criteria_type": "performance",
        "description": "Exponential backoff timing verification",
        "target_value": "1s, 2s, 4s, 8s progression",
        "validation_method": "Test measures actual delay times between retries",
        "priority": "required"
    })

    criteria_added += 1
    insert_acceptance_criterion(cursor, component_id, {
        "criteria_type": "error_classification",
        "description": "Correctly classify retryable vs fatal errors",
        "target_value": "100% accuracy",
        "validation_method": "Test suite with known error types (timeout=retryable, invalid_key=fatal)",
        "priority": "required"
    })

    criteria_added += 1
    insert_acceptance_criterion(cursor, component_id, {
        "criteria_type": "observability",
        "description": "All retry attempts logged with Langfuse instrumentation",
        "target_value": "100% trace coverage",
        "validation_method": "Verify @observe decorator on all methods",
        "priority": "recommended"
    })

    print(f"[OK] Added {criteria_added} acceptance criteria")

    # Implementation Patterns
    patterns_added = 0

    patterns_added += 1
    insert_pattern(cursor, component_id, {
        "pattern_name": "exponential_backoff",
        "pattern_type": "error_handling",
        "description": "Retry failed operations with exponentially increasing delays to handle transient failures",
        "code_example": """def execute_with_retry(self, func, max_attempts=3):
    for attempt in range(max_attempts):
        try:
            return func()
        except RetryableError as e:
            if attempt == max_attempts - 1:
                raise
            delay = 2 ** attempt  # 1s, 2s, 4s, 8s...
            time.sleep(delay)
            logger.info(f"[RETRY] Attempt {attempt + 1}/{max_attempts} after {delay}s")""",
        "antipatterns": """DON'T: Linear backoff (1s, 2s, 3s) - insufficient for rate limits
DON'T: No maximum attempts - risks infinite loops
DON'T: Retry non-retryable errors (invalid API key) - wastes time
DON'T: Same delay for all errors - use longer delays for rate limits""",
        "reference_links": "https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/"
    })

    patterns_added += 1
    insert_pattern(cursor, component_id, {
        "pattern_name": "error_classification",
        "pattern_type": "error_handling",
        "description": "Classify errors as retryable (transient) vs fatal (permanent) to avoid wasting retries",
        "code_example": """RETRYABLE_ERRORS = {
    "timeout": True,
    "rate_limit_exceeded": True,
    "service_unavailable": True,
    "connection_error": True
}

FATAL_ERRORS = {
    "invalid_api_key": True,
    "invalid_model": True,
    "context_length_exceeded": True,
    "content_policy_violation": True
}

def is_retryable(error: Exception) -> bool:
    error_type = type(error).__name__
    return error_type in RETRYABLE_ERRORS""",
        "antipatterns": """DON'T: Retry all errors blindly - wastes time on permanent failures
DON'T: Treat rate limits same as timeouts - rate limits need longer delays
DON'T: Ignore error messages - they contain retry-after hints""",
        "reference_links": "https://platform.openai.com/docs/guides/error-codes"
    })

    patterns_added += 1
    insert_pattern(cursor, component_id, {
        "pattern_name": "timeout_with_fallback",
        "pattern_type": "error_handling",
        "description": "Wrap LLM calls with timeout to prevent hanging, increase timeout on retry",
        "code_example": """def handle_timeout(self, func, timeout_seconds=30.0, max_retries=3):
    for attempt in range(max_retries):
        # Increase timeout on each retry
        current_timeout = timeout_seconds * (1.5 ** attempt)  # 30s, 45s, 67.5s

        try:
            with Timeout(current_timeout):
                return func()
        except TimeoutError:
            if attempt == max_retries - 1:
                raise
            logger.warning(f"[TIMEOUT] Retry with {current_timeout}s timeout")""",
        "antipatterns": """DON'T: Use same timeout for all retries - network may need more time
DON'T: Set timeout too low (<10s) - LLMs need time to process
DON'T: Set timeout too high (>5min) - user experience suffers""",
        "reference_links": "https://docs.python.org/3/library/signal.html#signal.alarm"
    })

    print(f"[OK] Added {patterns_added} implementation patterns")
    print(f"[COMPLETE] LLM_FAILURE_HANDLER: {methods_added} methods, {criteria_added} criteria, {patterns_added} patterns")


def populate_agent_interface(cursor):
    """Populate AGENT_INTERFACE implementation specs."""

    component_id = "AGENT_INTERFACE"

    print(f"\n[POPULATE] {component_id}")
    print("=" * 80)

    # Method 1: call_llm
    methods_added = 0
    methods_added += 1
    insert_method(cursor, component_id, {
        "method_name": "call_llm",
        "signature": "call_llm(self, messages: List[Dict[str, str]], **kwargs) -> str",
        "return_type": "str",
        "description": "Call LLM with conversation messages, returns response text",
        "parameters": [
            {
                "name": "messages",
                "type": "List[Dict[str, str]]",
                "description": "Conversation history in OpenAI format [{'role': 'user', 'content': '...'}]",
                "required": True
            },
            {
                "name": "temperature",
                "type": "float",
                "description": "Sampling temperature (0.0 = deterministic, 1.0 = creative)",
                "required": False,
                "default": "0.7"
            },
            {
                "name": "max_tokens",
                "type": "int",
                "description": "Maximum tokens in response",
                "required": False,
                "default": "4096"
            },
            {
                "name": "stream",
                "type": "bool",
                "description": "Enable streaming response (not supported in interface v1)",
                "required": False,
                "default": "False"
            }
        ],
        "raises": ["LLMError", "TimeoutError", "RateLimitError"],
        "example_usage": "response = agent.call_llm([{'role': 'user', 'content': 'hello'}], temperature=0.5)",
        "is_abstract": True
    })

    # Method 2: execute_tool
    methods_added += 1
    insert_method(cursor, component_id, {
        "method_name": "execute_tool",
        "signature": "execute_tool(self, tool_name: str, **params) -> Any",
        "return_type": "Any",
        "description": "Execute a tool by name with parameters, returns tool result",
        "parameters": [
            {
                "name": "tool_name",
                "type": "str",
                "description": "Tool name (e.g., 'write_file', 'run_command', 'search_code')",
                "required": True
            },
            {
                "name": "params",
                "type": "**kwargs",
                "description": "Tool-specific parameters (varies by tool)",
                "required": False
            }
        ],
        "raises": ["ToolNotFoundError", "ToolExecutionError"],
        "example_usage": "result = agent.execute_tool('write_file', file_path='test.py', content='print(1)')",
        "is_abstract": True
    })

    # Method 3: get_context
    methods_added += 1
    insert_method(cursor, component_id, {
        "method_name": "get_context",
        "signature": "get_context(self) -> Dict[str, Any]",
        "return_type": "Dict[str, Any]",
        "description": "Get current execution context (working directory, conversation history, active task)",
        "parameters": [],
        "raises": [],
        "example_usage": "context = agent.get_context(); print(context['working_directory'])",
        "is_abstract": True
    })

    # Method 4: update_memory
    methods_added += 1
    insert_method(cursor, component_id, {
        "method_name": "update_memory",
        "signature": "update_memory(self, key: str, value: Any) -> None",
        "return_type": "None",
        "description": "Update agent memory with key-value pair (for episodic or semantic memory)",
        "parameters": [
            {
                "name": "key",
                "type": "str",
                "description": "Memory key (e.g., 'last_test_result', 'validation_status')",
                "required": True
            },
            {
                "name": "value",
                "type": "Any",
                "description": "Value to store (any JSON-serializable type)",
                "required": True
            }
        ],
        "raises": ["MemoryError"],
        "example_usage": "agent.update_memory('test_result', {'passed': 10, 'failed': 2})",
        "is_abstract": True
    })

    print(f"[OK] Added {methods_added} method signatures")

    # Acceptance Criteria
    criteria_added = 0

    criteria_added += 1
    insert_acceptance_criterion(cursor, component_id, {
        "criteria_type": "test_coverage",
        "description": "Unit test coverage for interface methods and MockAgent implementation",
        "target_value": "90%+",
        "validation_method": "pytest tests/test_agent_interface.py --cov=src.core.agent_interface",
        "priority": "required"
    })

    criteria_added += 1
    insert_acceptance_criterion(cursor, component_id, {
        "criteria_type": "integration",
        "description": "At least 3 subsystems refactored to use AgentInterface instead of CodingAgent",
        "target_value": "3 subsystems",
        "validation_method": "Manual verification: ValidationSystem, MemoryManager, Observability use interface",
        "priority": "required"
    })

    criteria_added += 1
    insert_acceptance_criterion(cursor, component_id, {
        "criteria_type": "breaking_changes",
        "description": "Zero breaking changes to existing code (backwards compatible)",
        "target_value": "0 breaking changes",
        "validation_method": "All existing tests pass without modification",
        "priority": "required"
    })

    criteria_added += 1
    insert_acceptance_criterion(cursor, component_id, {
        "criteria_type": "mock_implementation",
        "description": "Working MockAgent implementation for testing subsystems in isolation",
        "target_value": "MockAgent passes interface tests",
        "validation_method": "MockAgent can run ValidationSystem tests without real LLM",
        "priority": "required"
    })

    criteria_added += 1
    insert_acceptance_criterion(cursor, component_id, {
        "criteria_type": "documentation",
        "description": "Comprehensive docstrings and integration guide",
        "target_value": "100% documented",
        "validation_method": "All interface methods have docstrings, README.md exists",
        "priority": "recommended"
    })

    print(f"[OK] Added {criteria_added} acceptance criteria")

    # Implementation Patterns
    patterns_added = 0

    patterns_added += 1
    insert_pattern(cursor, component_id, {
        "pattern_name": "interface_pattern",
        "pattern_type": "design_pattern",
        "description": "Abstract base class (ABC) defining contract between subsystems and agent implementation",
        "code_example": """from abc import ABC, abstractmethod
from typing import List, Dict, Any

class AgentInterface(ABC):
    '''Abstract interface for agent operations.'''

    @abstractmethod
    def call_llm(self, messages: List[Dict[str, str]], **kwargs) -> str:
        '''Call LLM with messages.'''
        pass

    @abstractmethod
    def execute_tool(self, tool_name: str, **params) -> Any:
        '''Execute tool by name.'''
        pass

# Concrete implementation
class CodingAgent(AgentInterface):
    def call_llm(self, messages, **kwargs):
        return self.llm_client.chat(messages, **kwargs)

    def execute_tool(self, tool_name, **params):
        return self.tools[tool_name].execute(**params)""",
        "antipatterns": """DON'T: Add implementation logic to interface (defeats purpose)
DON'T: Make interface too specific to CodingAgent (tight coupling)
DON'T: Skip abstractmethod decorator (no type safety)
DON'T: Change interface frequently (breaks subsystems)""",
        "reference_links": "https://docs.python.org/3/library/abc.html"
    })

    patterns_added += 1
    insert_pattern(cursor, component_id, {
        "pattern_name": "mock_testing",
        "pattern_type": "testing",
        "description": "Create MockAgent implementation for testing subsystems without real LLM/tools",
        "code_example": """class MockAgent(AgentInterface):
    '''Mock agent for testing subsystems in isolation.'''

    def __init__(self):
        self.call_history = []
        self.tool_history = []

    def call_llm(self, messages, **kwargs):
        self.call_history.append(messages)
        return "Mocked LLM response"

    def execute_tool(self, tool_name, **params):
        self.tool_history.append((tool_name, params))
        return {"status": "success", "mocked": True}

# Test subsystem with mock
def test_validation_system():
    mock_agent = MockAgent()
    validator = ValidationSystem(mock_agent)
    result = validator.validate()
    assert len(mock_agent.call_history) > 0  # Verify LLM was called""",
        "antipatterns": """DON'T: Test with real LLM (slow, expensive, non-deterministic)
DON'T: Hard-code responses (inflexible tests)
DON'T: Forget to track call history (can't verify behavior)""",
        "reference_links": "https://docs.python.org/3/library/unittest.mock.html"
    })

    print(f"[OK] Added {patterns_added} implementation patterns")
    print(f"[COMPLETE] AGENT_INTERFACE: {methods_added} methods, {criteria_added} criteria, {patterns_added} patterns")


def main():
    """Execute population."""

    print("\n" + "=" * 80)
    print("ClarAIty Data Population: Implementation Specs")
    print("=" * 80)

    # Connect to database
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # Populate both components
        populate_llm_failure_handler(cursor)
        populate_agent_interface(cursor)

        # Commit changes
        conn.commit()
        print("\n" + "=" * 80)
        print("[SUCCESS] All implementation specs populated")
        print("=" * 80)

        # Show summary
        cursor.execute("SELECT COUNT(*) FROM component_methods")
        method_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM component_acceptance_criteria")
        criteria_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM component_patterns")
        pattern_count = cursor.fetchone()[0]

        print(f"\n[SUMMARY]")
        print(f"  Methods added: {method_count}")
        print(f"  Acceptance criteria added: {criteria_count}")
        print(f"  Implementation patterns added: {pattern_count}")

        print(f"\n[NEXT STEP] Implement GetImplementationSpecTool")
        print(f"Add to: src/tools/clarity_tools.py")

        return 0

    except Exception as e:
        print(f"\n[ERROR] Population failed: {e}")
        conn.rollback()
        print("[ROLLBACK] Changes rolled back")
        raise

    finally:
        conn.close()


if __name__ == "__main__":
    exit(main())
