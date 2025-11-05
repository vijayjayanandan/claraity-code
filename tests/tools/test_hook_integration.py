"""Integration tests for ToolExecutor with HookManager."""

import pytest
import tempfile
from pathlib import Path
from src.tools.base import ToolExecutor, Tool, ToolResult, ToolStatus
from src.hooks import (
    HookManager, HookDecision, HookResult,
    PreToolUseContext, PostToolUseContext
)


class DummyTool(Tool):
    """Simple test tool."""

    def __init__(self):
        super().__init__("dummy_tool", "A test tool")
        self.executed_with = None

    def execute(self, **kwargs):
        """Execute with test data."""
        self.executed_with = kwargs
        return ToolResult(
            tool_name=self.name,
            status=ToolStatus.SUCCESS,
            output=f"Executed with: {kwargs}",
            error=None
        )

    def _get_parameters(self):
        return {"type": "object", "properties": {}}


class FailingTool(Tool):
    """Tool that always fails."""

    def __init__(self):
        super().__init__("failing_tool", "A tool that fails")

    def execute(self, **kwargs):
        """Always fail."""
        raise RuntimeError("Tool execution failed!")

    def _get_parameters(self):
        return {"type": "object", "properties": {}}


class TestToolExecutorBackwardCompatibility:
    """Test that ToolExecutor works without hook_manager (backward compatibility)."""

    def test_executor_without_hooks(self):
        """Test ToolExecutor works without hook_manager."""
        executor = ToolExecutor()
        tool = DummyTool()
        executor.register_tool(tool)

        result = executor.execute_tool("dummy_tool", arg1="value1")

        assert result.is_success()
        assert "value1" in result.output

    def test_executor_with_none_hook_manager(self):
        """Test ToolExecutor with explicit None hook_manager."""
        executor = ToolExecutor(hook_manager=None)
        tool = DummyTool()
        executor.register_tool(tool)

        result = executor.execute_tool("dummy_tool", arg1="value1")

        assert result.is_success()


class TestPreToolUseHookIntegration:
    """Test PreToolUse hook integration."""

    def test_hook_permits_execution(self, tmp_path):
        """Test hook that permits operation."""
        hooks_file = tmp_path / "hooks.py"
        hooks_file.write_text("""
from src.hooks import HookResult, HookDecision

def permit_hook(context):
    return HookResult(decision=HookDecision.PERMIT)

HOOKS = {
    'PreToolUse:dummy_tool': [permit_hook],
}
""")

        manager = HookManager(hooks_file=hooks_file)
        executor = ToolExecutor(hook_manager=manager)
        tool = DummyTool()
        executor.register_tool(tool)

        result = executor.execute_tool("dummy_tool", arg1="value1")

        assert result.is_success()
        assert "value1" in result.output

    def test_hook_denies_execution(self, tmp_path):
        """Test hook that denies operation."""
        hooks_file = tmp_path / "hooks.py"
        hooks_file.write_text("""
from src.hooks import HookResult, HookDecision

def deny_hook(context):
    return HookResult(decision=HookDecision.DENY, message="Not allowed")

HOOKS = {
    'PreToolUse:dummy_tool': [deny_hook],
}
""")

        manager = HookManager(hooks_file=hooks_file)
        executor = ToolExecutor(hook_manager=manager)
        tool = DummyTool()
        executor.register_tool(tool)

        result = executor.execute_tool("dummy_tool", arg1="value1")

        assert not result.is_success()
        assert result.status == ToolStatus.ERROR
        assert "denied by hook" in result.error.lower()

    def test_hook_blocks_execution(self, tmp_path):
        """Test hook that blocks operation with exception."""
        hooks_file = tmp_path / "hooks.py"
        hooks_file.write_text("""
from src.hooks import HookResult, HookDecision

def block_hook(context):
    return HookResult(decision=HookDecision.BLOCK, message="Blocked!")

HOOKS = {
    'PreToolUse:dummy_tool': [block_hook],
}
""")

        manager = HookManager(hooks_file=hooks_file)
        executor = ToolExecutor(hook_manager=manager)
        tool = DummyTool()
        executor.register_tool(tool)

        result = executor.execute_tool("dummy_tool", arg1="value1")

        assert not result.is_success()
        assert result.status == ToolStatus.ERROR
        assert "blocked by hook" in result.error.lower()

    def test_hook_modifies_arguments(self, tmp_path):
        """Test hook that modifies tool arguments."""
        hooks_file = tmp_path / "hooks.py"
        hooks_file.write_text("""
from src.hooks import HookResult, HookDecision

def modify_args_hook(context):
    return HookResult(
        decision=HookDecision.PERMIT,
        modified_arguments={'arg1': 'modified_value', 'arg2': 'added_arg'}
    )

HOOKS = {
    'PreToolUse:dummy_tool': [modify_args_hook],
}
""")

        manager = HookManager(hooks_file=hooks_file)
        executor = ToolExecutor(hook_manager=manager)
        tool = DummyTool()
        executor.register_tool(tool)

        result = executor.execute_tool("dummy_tool", arg1="original_value")

        assert result.is_success()
        # Check that tool received modified arguments
        assert tool.executed_with['arg1'] == 'modified_value'
        assert tool.executed_with['arg2'] == 'added_arg'


class TestPostToolUseHookIntegration:
    """Test PostToolUse hook integration."""

    def test_hook_modifies_result(self, tmp_path):
        """Test hook that modifies tool result."""
        hooks_file = tmp_path / "hooks.py"
        hooks_file.write_text("""
from src.hooks import HookResult

def modify_result_hook(context):
    return HookResult(modified_result="Modified output")

HOOKS = {
    'PostToolUse:dummy_tool': [modify_result_hook],
}
""")

        manager = HookManager(hooks_file=hooks_file)
        executor = ToolExecutor(hook_manager=manager)
        tool = DummyTool()
        executor.register_tool(tool)

        result = executor.execute_tool("dummy_tool", arg1="value1")

        assert result.is_success()
        assert result.output == "Modified output"

    def test_hook_receives_failure_info(self, tmp_path):
        """Test hook receives failure information when tool fails."""
        hooks_file = tmp_path / "hooks.py"
        hooks_file.write_text("""
from src.hooks import HookResult

received_context = None

def capture_failure_hook(context):
    global received_context
    received_context = context
    return HookResult()

HOOKS = {
    'PostToolUse:failing_tool': [capture_failure_hook],
}
""")

        manager = HookManager(hooks_file=hooks_file)
        executor = ToolExecutor(hook_manager=manager)
        tool = FailingTool()
        executor.register_tool(tool)

        result = executor.execute_tool("failing_tool", arg1="value1")

        # Tool should fail
        assert not result.is_success()
        assert "failed" in result.error.lower()


class TestWildcardHooks:
    """Test wildcard hook patterns."""

    def test_wildcard_hook_matches_all_tools(self, tmp_path):
        """Test wildcard hook matches all tools."""
        hooks_file = tmp_path / "hooks.py"
        hooks_file.write_text("""
from src.hooks import HookResult, HookDecision

executed_for = []

def log_all_hook(context):
    executed_for.append(context.tool)
    return HookResult(decision=HookDecision.PERMIT)

HOOKS = {
    'PreToolUse:*': [log_all_hook],
}
""")

        manager = HookManager(hooks_file=hooks_file)
        executor = ToolExecutor(hook_manager=manager)

        # Register multiple tools
        executor.register_tool(DummyTool())

        # Execute - wildcard should match
        result1 = executor.execute_tool("dummy_tool", arg1="value1")

        assert result1.is_success()


class TestHookErrorHandling:
    """Test error handling in hooks."""

    def test_hook_error_does_not_crash_execution(self, tmp_path):
        """Test that hook errors don't prevent tool execution."""
        hooks_file = tmp_path / "hooks.py"
        hooks_file.write_text("""
from src.hooks import HookResult

def error_hook(context):
    raise RuntimeError("Hook failed!")

HOOKS = {
    'PreToolUse:dummy_tool': [error_hook],
}
""")

        manager = HookManager(hooks_file=hooks_file)
        executor = ToolExecutor(hook_manager=manager)
        tool = DummyTool()
        executor.register_tool(tool)

        # Should not crash, should execute tool anyway
        result = executor.execute_tool("dummy_tool", arg1="value1")

        # Tool should still execute successfully
        assert result.is_success()

    def test_post_hook_error_does_not_affect_result(self, tmp_path):
        """Test that PostToolUse hook errors don't break result."""
        hooks_file = tmp_path / "hooks.py"
        hooks_file.write_text("""
from src.hooks import HookResult

def error_hook(context):
    raise RuntimeError("PostHook failed!")

HOOKS = {
    'PostToolUse:dummy_tool': [error_hook],
}
""")

        manager = HookManager(hooks_file=hooks_file)
        executor = ToolExecutor(hook_manager=manager)
        tool = DummyTool()
        executor.register_tool(tool)

        result = executor.execute_tool("dummy_tool", arg1="value1")

        # Tool should still return success
        assert result.is_success()


class TestToolNotFound:
    """Test that tool not found error still works with hooks."""

    def test_tool_not_found_with_hooks(self, tmp_path):
        """Test tool not found error when hooks are enabled."""
        hooks_file = tmp_path / "hooks.py"
        hooks_file.write_text("""
from src.hooks import HookResult

def some_hook(context):
    return HookResult()

HOOKS = {
    'PreToolUse:*': [some_hook],
}
""")

        manager = HookManager(hooks_file=hooks_file)
        executor = ToolExecutor(hook_manager=manager)

        result = executor.execute_tool("nonexistent_tool", arg1="value1")

        assert not result.is_success()
        assert "not found" in result.error.lower()


class TestMultipleHooks:
    """Test multiple hooks in sequence."""

    def test_multiple_hooks_execute_in_order(self, tmp_path):
        """Test that multiple hooks execute sequentially."""
        hooks_file = tmp_path / "hooks.py"
        hooks_file.write_text("""
from src.hooks import HookResult, HookDecision

execution_order = []

def hook1(context):
    execution_order.append('hook1')
    return HookResult(
        decision=HookDecision.PERMIT,
        modified_arguments={'arg1': 'modified_by_hook1'}
    )

def hook2(context):
    execution_order.append('hook2')
    # Hook2 sees modifications from hook1
    assert context.arguments['arg1'] == 'modified_by_hook1'
    return HookResult(
        decision=HookDecision.PERMIT,
        modified_arguments={'arg1': 'modified_by_hook2'}
    )

HOOKS = {
    'PreToolUse:dummy_tool': [hook1, hook2],
}
""")

        manager = HookManager(hooks_file=hooks_file)
        executor = ToolExecutor(hook_manager=manager)
        tool = DummyTool()
        executor.register_tool(tool)

        result = executor.execute_tool("dummy_tool", arg1="original")

        assert result.is_success()
        # Tool should receive final modified arguments
        assert tool.executed_with['arg1'] == 'modified_by_hook2'
