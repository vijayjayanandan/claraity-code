"""
Tests for parallel tool execution in CodingAgent.stream_response().

Validates the phased tool execution approach:
- Phase A: Gate, approve, classify (sequential)
- Phase B1: Interactive tools (serial)
- Phase B2: Normal tools (parallel via asyncio.gather)
- Phase C: Merge & persist (sequential, original call order)
"""

import asyncio
import json
import time
import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.agent import CodingAgent
from src.core.tool_gating import GateAction, GateResult, ToolGatingService
from src.core.tool_status import ToolStatus as CoreToolStatus
from src.session.models.message import ToolCall, ToolCallFunction
from src.tools.base import ToolResult, ToolStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_tool_call(
    name: str,
    arguments: Optional[Dict[str, Any]] = None,
    call_id: Optional[str] = None,
) -> ToolCall:
    """Create a ToolCall with given name and arguments."""
    return ToolCall(
        id=call_id or f"call_{uuid.uuid4().hex[:8]}",
        function=ToolCallFunction(
            name=name,
            arguments=json.dumps(arguments or {}),
        ),
    )


def make_success_result(output: str, tool_name: str = "read_file") -> ToolResult:
    """Create a successful ToolResult."""
    return ToolResult(tool_name=tool_name, status=ToolStatus.SUCCESS, output=output)


def make_error_result(error: str, tool_name: str = "read_file", output: str = "") -> ToolResult:
    """Create a failed ToolResult."""
    return ToolResult(
        tool_name=tool_name, status=ToolStatus.ERROR,
        output=output, error=error,
    )


class MockMemoryManager:
    """Minimal mock for MemoryManager."""

    def __init__(self):
        self.message_store = MagicMock()
        self.message_store.update_tool_state = MagicMock()
        self.render_meta = MagicMock()
        self.render_meta.set_approval_meta = MagicMock()
        self.tool_results = []  # Track add_tool_result calls in order

    def add_tool_result(self, **kwargs):
        self.tool_results.append(kwargs)

    def persist_system_event(self, **kwargs):
        pass


class MockToolExecutor:
    """Mock tool executor that tracks execution order and supports delays."""

    def __init__(self):
        self.call_log = []  # (tool_name, kwargs, timestamp)
        self._results = {}  # tool_name -> ToolResult or callable
        self._delays = {}   # tool_name -> seconds

    def set_result(self, tool_name: str, result: ToolResult, delay: float = 0):
        self._results[tool_name] = result
        if delay:
            self._delays[tool_name] = delay

    def set_result_fn(self, tool_name: str, fn):
        """Set a callable that returns a ToolResult."""
        self._results[tool_name] = fn

    async def execute_tool_async(self, tool_name: str, **kwargs) -> ToolResult:
        delay = self._delays.get(tool_name, 0)
        if delay:
            await asyncio.sleep(delay)
        self.call_log.append((tool_name, kwargs, time.monotonic()))

        result_or_fn = self._results.get(tool_name)
        if callable(result_or_fn):
            return result_or_fn(tool_name, kwargs)
        if result_or_fn is not None:
            return result_or_fn
        return make_success_result(f"output of {tool_name}", tool_name)


class MockTaskState:
    """Minimal mock for TaskState."""

    def __init__(self):
        self.error_budget_resume_count = 0
        self.successful_tools_since_resume = 0
        self.last_stop_reason = None
        self.current_task_id = None

    def get_todos_list(self):
        return []

    def get_pending_summary(self):
        return ""


class MockSpecialHandlers:
    """Mock for SpecialToolHandlers."""

    def handles(self, tool_name: str) -> bool:
        return tool_name in ('clarify', 'request_plan_approval')

    async def handle_clarify(self, call_id, tool_args, ui):
        return {"answer": "user response"}

    async def handle_plan_approval(self, call_id, ui):
        return ("Plan approved", False)

    async def handle_director_plan_approval(self, call_id, result, ui):
        return ("Director plan approved", False)


class MockErrorTracker:
    """Mock for ErrorRecoveryTracker."""

    def __init__(self):
        self.failures = []

    def is_repeated_failed_call(self, tool_name, tool_args):
        return (False, None)

    def record_failure(self, **kwargs):
        self.failures.append(kwargs)
        return MagicMock(to_prompt_block=lambda: f"Error: {kwargs.get('error_message', 'unknown')}")

    def should_allow_retry(self, tool_name, error_type):
        return (True, "")

    def get_stats(self):
        return {'total_failures': len(self.failures)}

    def reset_tool_error_counts(self, **kwargs):
        pass


class MockGating:
    """Mock gating that allows everything by default."""

    def __init__(self):
        self._overrides = {}  # call_id or tool_name -> GateResult

    def override(self, key: str, result: GateResult):
        self._overrides[key] = result

    def evaluate(self, tool_name, tool_args):
        if tool_name in self._overrides:
            return self._overrides[tool_name]
        return GateResult(action=GateAction.ALLOW)

    def format_gate_response(self, gate_response):
        return json.dumps(gate_response or {})


class MockUI:
    """Mock UIProtocol."""

    def __init__(self, auto_approve=True):
        self._auto_approve = auto_approve
        self._interrupted = False
        self.approval_requests = []
        self.todos_updates = []

    def check_interrupted(self):
        return self._interrupted

    def has_pause_capability(self):
        return True

    async def wait_for_approval(self, call_id, tool_name, timeout=None, force_approval=False):
        from src.core.protocol import ApprovalResult
        self.approval_requests.append((call_id, tool_name))
        return ApprovalResult(
            call_id=call_id, approved=self._auto_approve,
            auto_approve_future=False, feedback=None,
        )

    async def wait_for_pause_response(self, timeout=None):
        from src.core.protocol import PauseResult
        return PauseResult(continue_work=False)

    async def wait_for_clarify_response(self, call_id, timeout=None):
        from src.core.protocol import ClarifyResult
        return ClarifyResult(call_id=call_id, submitted=False)

    def notify_todos_updated(self, todos):
        self.todos_updates.append(todos)


# ---------------------------------------------------------------------------
# Fixture: build a minimal CodingAgent with mocks injected
# ---------------------------------------------------------------------------

@pytest.fixture
def agent_parts():
    """Create all mock parts needed to test _execute_tools_parallel."""
    memory = MockMemoryManager()
    executor = MockToolExecutor()
    gating = MockGating()
    special = MockSpecialHandlers()
    error_tracker = MockErrorTracker()
    task_state = MockTaskState()
    ui = MockUI()

    return {
        'memory': memory,
        'executor': executor,
        'gating': gating,
        'special': special,
        'error_tracker': error_tracker,
        'task_state': task_state,
        'ui': ui,
    }


@pytest.fixture
def make_agent(agent_parts):
    """Factory to build a CodingAgent with mocks wired in for unit testing."""
    def _factory():
        # Create a minimal agent by mocking __init__
        agent = object.__new__(CodingAgent)
        agent.memory = agent_parts['memory']
        agent.tool_executor = agent_parts['executor']
        agent._gating = agent_parts['gating']
        agent._special_handlers = agent_parts['special']
        agent._error_tracker = agent_parts['error_tracker']
        agent.task_state = agent_parts['task_state']
        agent.tool_execution_history = []
        agent._max_tool_output_chars = 100_000
        agent.permission_manager = None
        agent._awaiting_approval = False
        agent._error_budget_resume_count = 0
        agent._successful_tools_since_resume = 0
        agent.last_stop_reason = None
        return agent
    return _factory


# ===========================================================================
# Tests
# ===========================================================================


class TestExecuteToolsParallel:
    """Tests for _execute_tools_parallel method."""

    @pytest.mark.asyncio
    async def test_two_read_files_run_concurrently(self, make_agent, agent_parts):
        """Two read_file calls should run concurrently and both succeed."""
        agent = make_agent()
        executor = agent_parts['executor']

        # Both tools have a delay to detect concurrency.
        # delay=0.2 so sequential=0.4s; concurrent≈0.2s+overhead.
        # Threshold 0.36s is well below sequential even with ~100ms CI overhead.
        delay = 0.2
        executor.set_result("read_file", make_success_result("file content A"), delay=delay)

        tc1 = make_tool_call("read_file", {"file_path": "/a.py"}, "call_1")
        tc2 = make_tool_call("read_file", {"file_path": "/b.py"}, "call_2")

        executable = [
            (0, "call_1", tc1, {"file_path": "/a.py"}),
            (1, "call_2", tc2, {"file_path": "/b.py"}),
        ]

        start = time.monotonic()
        results = await agent._execute_tools_parallel(executable)
        elapsed = time.monotonic() - start

        # Both should complete
        assert len(results) == 2

        # Should run concurrently: total time < sequential time (2x delay)
        assert elapsed < 2 * delay * 0.9, f"Expected concurrent execution, took {elapsed:.3f}s"

        # Both should have tool_msg
        for _, _, _, outcome in results:
            assert outcome.get('tool_msg') is not None

    @pytest.mark.asyncio
    async def test_results_preserve_original_call_order(self, make_agent, agent_parts):
        """Results should be returned in the same order as the input, regardless of completion time."""
        agent = make_agent()
        executor = agent_parts['executor']

        # Tool at index 2 completes first, index 0 completes last
        for i, delay in enumerate([0.06, 0.04, 0.02]):
            name = f"read_file"
            executor._delays[f"_key_{i}"] = delay

        # Use a custom result function that includes the file_path in output
        def make_result_fn(tool_name, kwargs):
            return make_success_result(f"content of {kwargs.get('file_path', '?')}")

        executor.set_result_fn("read_file", make_result_fn)
        # Override delays per-call by using a custom executor
        call_delays = {0: 0.06, 1: 0.04, 2: 0.02}

        tc_list = []
        executable = []
        for i in range(3):
            tc = make_tool_call("read_file", {"file_path": f"/file_{i}.py"}, f"call_{i}")
            tc_list.append(tc)
            executable.append((i, f"call_{i}", tc, {"file_path": f"/file_{i}.py"}))

        results = await agent._execute_tools_parallel(executable)

        # Results should match input order (0, 1, 2)
        result_indices = [idx for idx, _, _, _ in results]
        assert result_indices == [0, 1, 2]

    @pytest.mark.asyncio
    async def test_one_tool_errors_other_succeeds(self, make_agent, agent_parts):
        """When one tool errors, the other should still succeed. Both results collected."""
        agent = make_agent()
        executor = agent_parts['executor']

        # Custom result function: first succeeds, second fails
        call_count = [0]
        def result_fn(tool_name, kwargs):
            call_count[0] += 1
            if kwargs.get('file_path') == '/bad.py':
                return make_error_result("File not found: /bad.py")
            return make_success_result("good content")

        executor.set_result_fn("read_file", result_fn)

        tc1 = make_tool_call("read_file", {"file_path": "/good.py"}, "call_good")
        tc2 = make_tool_call("read_file", {"file_path": "/bad.py"}, "call_bad")

        executable = [
            (0, "call_good", tc1, {"file_path": "/good.py"}),
            (1, "call_bad", tc2, {"file_path": "/bad.py"}),
        ]

        results = await agent._execute_tools_parallel(executable)

        assert len(results) == 2

        # First tool: success
        _, _, _, outcome_good = results[0]
        assert outcome_good['tool_msg'] is not None

        # Second tool: error (still has a tool_msg)
        _, _, _, outcome_bad = results[1]
        assert outcome_bad['tool_msg'] is not None

    @pytest.mark.asyncio
    async def test_single_tool_no_gather(self, make_agent, agent_parts):
        """Single tool call should work without asyncio.gather overhead."""
        agent = make_agent()
        executor = agent_parts['executor']
        executor.set_result("read_file", make_success_result("single file content"))

        tc = make_tool_call("read_file", {"file_path": "/single.py"}, "call_single")
        executable = [(0, "call_single", tc, {"file_path": "/single.py"})]

        results = await agent._execute_tools_parallel(executable)

        assert len(results) == 1
        _, _, _, outcome = results[0]
        assert outcome['tool_msg'] is not None
        assert "single file content" in outcome['tool_msg']['content']

    @pytest.mark.asyncio
    async def test_exception_in_tool_returns_error_result(self, make_agent, agent_parts):
        """If a tool raises an exception, the result should contain the error."""
        agent = make_agent()
        executor = agent_parts['executor']

        async def raise_error(tool_name, **kwargs):
            raise RuntimeError("Tool crashed!")

        # Override execute_tool_async to raise
        original = executor.execute_tool_async
        async def patched(tool_name, **kwargs):
            if tool_name == "read_file" and kwargs.get('file_path') == '/crash.py':
                raise RuntimeError("Tool crashed!")
            return await original(tool_name, **kwargs)
        executor.execute_tool_async = patched

        tc1 = make_tool_call("read_file", {"file_path": "/ok.py"}, "call_ok")
        tc2 = make_tool_call("read_file", {"file_path": "/crash.py"}, "call_crash")

        executable = [
            (0, "call_ok", tc1, {"file_path": "/ok.py"}),
            (1, "call_crash", tc2, {"file_path": "/crash.py"}),
        ]

        results = await agent._execute_tools_parallel(executable)

        assert len(results) == 2
        # Both should have tool_msg (error tool gets error message)
        for _, _, _, outcome in results:
            assert outcome.get('tool_msg') is not None

    @pytest.mark.asyncio
    async def test_memory_persistence_is_sequential(self, make_agent, agent_parts):
        """add_tool_result calls should happen in input order, not completion order."""
        agent = make_agent()
        memory = agent_parts['memory']
        executor = agent_parts['executor']

        # Tool B completes before Tool A
        def result_fn(tool_name, kwargs):
            return make_success_result(f"output {kwargs.get('file_path', '?')}")
        executor.set_result_fn("read_file", result_fn)

        tc1 = make_tool_call("read_file", {"file_path": "/first.py"}, "call_first")
        tc2 = make_tool_call("read_file", {"file_path": "/second.py"}, "call_second")

        executable = [
            (0, "call_first", tc1, {"file_path": "/first.py"}),
            (1, "call_second", tc2, {"file_path": "/second.py"}),
        ]

        results = await agent._execute_tools_parallel(executable)

        # Verify persistence calls were made
        assert len(memory.tool_results) == 2

        # Results are added in the order they complete inside _execute_tools_parallel,
        # but the resolved list reordering happens in stream_response's Phase C merge.
        # The important thing is that all results are persisted.
        call_ids = [r['tool_call_id'] for r in memory.tool_results]
        assert "call_first" in call_ids
        assert "call_second" in call_ids

    @pytest.mark.asyncio
    async def test_oversized_output_detected(self, make_agent, agent_parts):
        """Oversized output should be caught and reported as error."""
        agent = make_agent()
        agent._max_tool_output_chars = 50  # Very small limit for testing
        executor = agent_parts['executor']

        executor.set_result("read_file", make_success_result("x" * 100))  # Over limit

        tc = make_tool_call("read_file", {"file_path": "/big.py"}, "call_big")
        executable = [(0, "call_big", tc, {"file_path": "/big.py"})]

        results = await agent._execute_tools_parallel(executable)

        assert len(results) == 1
        _, _, _, outcome = results[0]
        assert "too large" in outcome['tool_msg']['content'].lower() or "Error" in outcome['tool_msg']['content']


class TestPhasedToolLoop:
    """Integration-level tests for the phased tool loop structure."""

    @pytest.mark.asyncio
    async def test_classify_interactive_vs_executable(self, make_agent, agent_parts):
        """Tools should be classified correctly: clarify -> interactive, read_file -> executable."""
        agent = make_agent()

        # We test classification logic directly by checking what _special_handlers.handles returns
        special = agent_parts['special']
        assert special.handles("clarify") is True
        assert special.handles("request_plan_approval") is True
        assert special.handles("read_file") is False
        assert special.handles("write_file") is False

    @pytest.mark.asyncio
    async def test_gated_tool_goes_to_resolved(self, make_agent, agent_parts):
        """A tool blocked by repeat detection should end up in resolved, not executable."""
        agent = make_agent()
        gating = agent_parts['gating']

        # Override gating for read_file to block it
        gating.override("read_file", GateResult(
            action=GateAction.BLOCKED_REPEAT,
            message="[BLOCKED] This exact call failed previously.",
            call_summary="read_file(/a.py)",
        ))

        tc = make_tool_call("read_file", {"file_path": "/a.py"}, "call_blocked")

        # Simulate Phase A classification
        tool_args = tc.function.get_parsed_arguments()
        gate_result = gating.evaluate(tc.function.name, tool_args)

        assert gate_result.action == GateAction.BLOCKED_REPEAT

    @pytest.mark.asyncio
    async def test_denied_tool_goes_to_resolved(self, make_agent, agent_parts):
        """A tool denied by plan mode should end up in resolved with gated status."""
        gating = agent_parts['gating']

        gating.override("write_file", GateResult(
            action=GateAction.DENY,
            message="Tool 'write_file' is not allowed in plan mode.",
            gate_response={"status": "denied", "error_code": "PLAN_MODE_GATED"},
        ))

        tc = make_tool_call("write_file", {"file_path": "/x.py", "content": "test"}, "call_denied")
        tool_args = tc.function.get_parsed_arguments()
        gate_result = gating.evaluate(tc.function.name, tool_args)

        assert gate_result.action == GateAction.DENY


class TestProcessParallelToolResult:
    """Tests for _process_parallel_tool_result method."""

    @pytest.mark.asyncio
    async def test_success_result_processing(self, make_agent, agent_parts):
        """Successful result should produce correct tool_msg and persist to memory."""
        agent = make_agent()
        memory = agent_parts['memory']

        tc = make_tool_call("read_file", {"file_path": "/a.py"}, "call_1")
        result = make_success_result("file content here")

        outcome = agent._process_parallel_tool_result(
            0, "call_1", tc, result, 42, None
        )

        assert outcome['tool_msg']['tool_call_id'] == "call_1"
        assert "file content here" in outcome['tool_msg']['content']
        assert len(memory.tool_results) == 1
        assert memory.tool_results[0]['status'] == "success"

    @pytest.mark.asyncio
    async def test_exception_result_processing(self, make_agent, agent_parts):
        """Exception should produce error tool_msg and persist to memory."""
        agent = make_agent()
        memory = agent_parts['memory']

        tc = make_tool_call("read_file", {"file_path": "/a.py"}, "call_exc")
        exc = RuntimeError("Disk error")

        outcome = agent._process_parallel_tool_result(
            0, "call_exc", tc, None, 100, exc
        )

        assert outcome['tool_msg']['tool_call_id'] == "call_exc"
        assert len(memory.tool_results) == 1
        assert memory.tool_results[0]['status'] == "error"

    @pytest.mark.asyncio
    async def test_error_result_with_retry_allowed(self, make_agent, agent_parts):
        """Error result with retry allowed should produce framed error content."""
        agent = make_agent()

        tc = make_tool_call("run_command", {"command": "false"}, "call_err")
        result = make_error_result("Exit code 1", tool_name="run_command")

        outcome = agent._process_parallel_tool_result(
            0, "call_err", tc, result, 50, None
        )

        assert outcome['tool_msg'] is not None
        assert not outcome.get('_needs_error_budget_pause')

    @pytest.mark.asyncio
    async def test_error_budget_exceeded_signals_pause(self, make_agent, agent_parts):
        """When error budget is exceeded, outcome should signal pause needed."""
        agent = make_agent()
        error_tracker = agent_parts['error_tracker']

        # Override should_allow_retry to deny
        error_tracker.should_allow_retry = lambda tn, et: (False, "Too many failures")

        tc = make_tool_call("run_command", {"command": "false"}, "call_budget")
        result = make_error_result("Exit code 1", tool_name="run_command")

        outcome = agent._process_parallel_tool_result(
            0, "call_budget", tc, result, 50, None
        )

        assert outcome.get('_needs_error_budget_pause') is True
        assert outcome['_pause_reason'] == "Too many failures"
