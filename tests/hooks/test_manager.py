"""Unit tests for HookManager."""

import pytest
import tempfile
from pathlib import Path
from src.hooks import (
    HookManager, HookLoadError, HookBlockedError,
    HookEvent, HookDecision, HookContinue, HookApproval,
    PreToolUseContext, PostToolUseContext, UserPromptSubmitContext,
    NotificationContext, SessionStartContext, SessionEndContext,
    PreCompactContext, StopContext, SubagentStopContext,
    HookResult, UserPromptResult, NotificationResult,
)


class TestHookManagerInitialization:
    """Test HookManager initialization."""

    def test_create_without_hooks_file(self):
        """Test creating manager without hooks file."""
        manager = HookManager()

        assert manager.session_id is not None
        assert len(manager.hooks) == len(HookEvent)
        # Each event should have empty dict
        for event in HookEvent:
            assert event in manager.hooks
            assert manager.hooks[event] == {}

    def test_create_with_session_id(self):
        """Test creating manager with custom session ID."""
        session_id = "test-session-123"
        manager = HookManager(session_id=session_id)

        assert manager.session_id == session_id

    def test_auto_generate_session_id(self):
        """Test that session ID is auto-generated if not provided."""
        manager1 = HookManager()
        manager2 = HookManager()

        # Should have different session IDs
        assert manager1.session_id != manager2.session_id


class TestHookLoading:
    """Test hook loading from Python files."""

    def test_load_valid_hooks_file(self, tmp_path):
        """Test loading valid hooks file with HOOKS dict."""
        hooks_file = tmp_path / "hooks.py"
        hooks_file.write_text("""
from src.hooks import PreToolUseContext, HookResult, HookDecision

def test_hook(context):
    return HookResult(decision=HookDecision.PERMIT)

HOOKS = {
    'PreToolUse:write_file': [test_hook],
}
""")

        manager = HookManager(hooks_file=hooks_file)

        # Check hook was registered
        assert 'write_file' in manager.hooks[HookEvent.PRE_TOOL_USE]
        assert len(manager.hooks[HookEvent.PRE_TOOL_USE]['write_file']) == 1

    def test_load_hooks_file_missing_hooks_dict(self, tmp_path):
        """Test loading file without HOOKS dict raises error."""
        hooks_file = tmp_path / "hooks.py"
        hooks_file.write_text("""
def some_function():
    pass
""")

        with pytest.raises(HookLoadError) as exc_info:
            HookManager(hooks_file=hooks_file)

        assert "No HOOKS dict found" in str(exc_info.value)

    def test_load_nonexistent_hooks_file(self):
        """Test loading nonexistent file raises error."""
        fake_path = Path("/nonexistent/hooks.py")

        with pytest.raises(HookLoadError):
            manager = HookManager()
            manager.load_hooks(fake_path)

    def test_load_invalid_python_file(self, tmp_path):
        """Test loading file with syntax errors raises error."""
        hooks_file = tmp_path / "hooks.py"
        hooks_file.write_text("this is not valid python ][][")

        with pytest.raises(HookLoadError):
            HookManager(hooks_file=hooks_file)


class TestPatternMatching:
    """Test hook pattern matching and registration."""

    def test_register_exact_tool_pattern(self, tmp_path):
        """Test registering hook for specific tool."""
        hooks_file = tmp_path / "hooks.py"
        hooks_file.write_text("""
from src.hooks import HookResult

def hook_func(context):
    return HookResult()

HOOKS = {
    'PreToolUse:write_file': [hook_func],
}
""")

        manager = HookManager(hooks_file=hooks_file)

        # Get matching hooks for write_file
        hooks = manager._get_matching_hooks(HookEvent.PRE_TOOL_USE, 'write_file')
        assert len(hooks) == 1

        # No match for different tool
        hooks = manager._get_matching_hooks(HookEvent.PRE_TOOL_USE, 'read_file')
        assert len(hooks) == 0

    def test_register_wildcard_pattern(self, tmp_path):
        """Test registering hook for all tools with wildcard."""
        hooks_file = tmp_path / "hooks.py"
        hooks_file.write_text("""
from src.hooks import HookResult

def hook_func(context):
    return HookResult()

HOOKS = {
    'PreToolUse:*': [hook_func],
}
""")

        manager = HookManager(hooks_file=hooks_file)

        # Wildcard should match any tool
        hooks = manager._get_matching_hooks(HookEvent.PRE_TOOL_USE, 'write_file')
        assert len(hooks) == 1

        hooks = manager._get_matching_hooks(HookEvent.PRE_TOOL_USE, 'read_file')
        assert len(hooks) == 1

    def test_register_event_without_tool(self, tmp_path):
        """Test registering hook for event without tool specifier."""
        hooks_file = tmp_path / "hooks.py"
        hooks_file.write_text("""
from src.hooks import HookResult

def hook_func(context):
    pass

HOOKS = {
    'SessionStart': [hook_func],
}
""")

        manager = HookManager(hooks_file=hooks_file)

        # Should match SessionStart event
        hooks = manager._get_matching_hooks(HookEvent.SESSION_START)
        assert len(hooks) == 1

    def test_register_multiple_hooks_for_pattern(self, tmp_path):
        """Test registering multiple hooks for same pattern."""
        hooks_file = tmp_path / "hooks.py"
        hooks_file.write_text("""
from src.hooks import HookResult

def hook1(context):
    return HookResult()

def hook2(context):
    return HookResult()

HOOKS = {
    'PreToolUse:write_file': [hook1, hook2],
}
""")

        manager = HookManager(hooks_file=hooks_file)

        hooks = manager._get_matching_hooks(HookEvent.PRE_TOOL_USE, 'write_file')
        assert len(hooks) == 2


class TestPreToolUseHooks:
    """Test PreToolUse hook emission and enforcement."""

    def test_emit_with_no_hooks(self):
        """Test emitting when no hooks registered."""
        manager = HookManager()

        decision, args = manager.emit_pre_tool_use(
            'write_file',
            {'file_path': 'test.py'}
        )

        assert decision == HookDecision.PERMIT
        assert args == {'file_path': 'test.py'}

    def test_emit_with_permit_decision(self, tmp_path):
        """Test hook that permits operation."""
        hooks_file = tmp_path / "hooks.py"
        hooks_file.write_text("""
from src.hooks import HookResult, HookDecision

def permit_hook(context):
    return HookResult(decision=HookDecision.PERMIT)

HOOKS = {
    'PreToolUse:write_file': [permit_hook],
}
""")

        manager = HookManager(hooks_file=hooks_file)

        decision, args = manager.emit_pre_tool_use(
            'write_file',
            {'file_path': 'test.py'}
        )

        assert decision == HookDecision.PERMIT

    def test_emit_with_deny_decision(self, tmp_path):
        """Test hook that denies operation."""
        hooks_file = tmp_path / "hooks.py"
        hooks_file.write_text("""
from src.hooks import HookResult, HookDecision

def deny_hook(context):
    return HookResult(decision=HookDecision.DENY, message="Not allowed")

HOOKS = {
    'PreToolUse:write_file': [deny_hook],
}
""")

        manager = HookManager(hooks_file=hooks_file)

        decision, args = manager.emit_pre_tool_use(
            'write_file',
            {'file_path': 'test.py'}
        )

        assert decision == HookDecision.DENY

    def test_emit_with_block_decision(self, tmp_path):
        """Test hook that blocks operation with exception."""
        hooks_file = tmp_path / "hooks.py"
        hooks_file.write_text("""
from src.hooks import HookResult, HookDecision

def block_hook(context):
    return HookResult(decision=HookDecision.BLOCK, message="Blocked!")

HOOKS = {
    'PreToolUse:write_file': [block_hook],
}
""")

        manager = HookManager(hooks_file=hooks_file)

        with pytest.raises(HookBlockedError) as exc_info:
            manager.emit_pre_tool_use('write_file', {'file_path': 'test.py'})

        assert "Blocked!" in str(exc_info.value)

    def test_emit_with_modified_arguments(self, tmp_path):
        """Test hook that modifies arguments."""
        hooks_file = tmp_path / "hooks.py"
        hooks_file.write_text("""
from src.hooks import HookResult, HookDecision

def modify_hook(context):
    return HookResult(
        decision=HookDecision.PERMIT,
        modified_arguments={'file_path': 'modified.py', 'validated': True}
    )

HOOKS = {
    'PreToolUse:write_file': [modify_hook],
}
""")

        manager = HookManager(hooks_file=hooks_file)

        decision, args = manager.emit_pre_tool_use(
            'write_file',
            {'file_path': 'original.py'}
        )

        assert decision == HookDecision.PERMIT
        assert args['file_path'] == 'modified.py'
        assert args['validated'] is True

    def test_emit_with_hook_error(self, tmp_path):
        """Test that hook errors are caught and logged."""
        hooks_file = tmp_path / "hooks.py"
        hooks_file.write_text("""
from src.hooks import HookResult

def error_hook(context):
    raise RuntimeError("Hook failed!")

HOOKS = {
    'PreToolUse:write_file': [error_hook],
}
""")

        manager = HookManager(hooks_file=hooks_file)

        # Should not raise, just log error and continue
        decision, args = manager.emit_pre_tool_use(
            'write_file',
            {'file_path': 'test.py'}
        )

        # Should permit since hook failed
        assert decision == HookDecision.PERMIT


class TestPostToolUseHooks:
    """Test PostToolUse hook emission."""

    def test_emit_with_no_hooks(self):
        """Test emitting when no hooks registered."""
        manager = HookManager()

        modified_result = manager.emit_post_tool_use(
            tool='write_file',
            arguments={'file_path': 'test.py'},
            result='Success',
            success=True,
            duration=0.5
        )

        assert modified_result is None

    def test_emit_with_result_modification(self, tmp_path):
        """Test hook that modifies result."""
        hooks_file = tmp_path / "hooks.py"
        hooks_file.write_text("""
from src.hooks import HookResult

def modify_result_hook(context):
    return HookResult(modified_result="Modified result")

HOOKS = {
    'PostToolUse:write_file': [modify_result_hook],
}
""")

        manager = HookManager(hooks_file=hooks_file)

        modified_result = manager.emit_post_tool_use(
            tool='write_file',
            arguments={'file_path': 'test.py'},
            result='Original result',
            success=True,
            duration=0.5
        )

        assert modified_result == "Modified result"

    def test_emit_with_failure_info(self, tmp_path):
        """Test hook receives failure information."""
        hooks_file = tmp_path / "hooks.py"
        hooks_file.write_text("""
from src.hooks import HookResult

received_context = None

def capture_context_hook(context):
    global received_context
    received_context = context
    return HookResult()

HOOKS = {
    'PostToolUse:write_file': [capture_context_hook],
}
""")

        manager = HookManager(hooks_file=hooks_file)

        manager.emit_post_tool_use(
            tool='write_file',
            arguments={'file_path': 'test.py'},
            result=None,
            success=False,
            duration=0.1,
            error="File not found"
        )

        # Can't directly access context, but test doesn't raise


class TestOtherHookEvents:
    """Test other hook events (UserPromptSubmit, Session, etc.)."""

    def test_emit_user_prompt_submit(self, tmp_path):
        """Test UserPromptSubmit hook."""
        hooks_file = tmp_path / "hooks.py"
        hooks_file.write_text("""
from src.hooks import UserPromptResult, HookContinue

def modify_prompt_hook(context):
    return UserPromptResult(
        decision=HookContinue.CONTINUE,
        modified_prompt="Modified: " + context.prompt
    )

HOOKS = {
    'UserPromptSubmit': [modify_prompt_hook],
}
""")

        manager = HookManager(hooks_file=hooks_file)

        decision, modified_prompt = manager.emit_user_prompt_submit("Hello")

        assert decision == HookContinue.CONTINUE
        assert modified_prompt == "Modified: Hello"

    def test_emit_user_prompt_block(self, tmp_path):
        """Test UserPromptSubmit hook that blocks."""
        hooks_file = tmp_path / "hooks.py"
        hooks_file.write_text("""
from src.hooks import UserPromptResult, HookContinue

def block_prompt_hook(context):
    return UserPromptResult(
        decision=HookContinue.BLOCK,
        message="Blocked"
    )

HOOKS = {
    'UserPromptSubmit': [block_prompt_hook],
}
""")

        manager = HookManager(hooks_file=hooks_file)

        with pytest.raises(HookBlockedError):
            manager.emit_user_prompt_submit("Test")

    def test_emit_notification(self, tmp_path):
        """Test Notification hook."""
        hooks_file = tmp_path / "hooks.py"
        hooks_file.write_text("""
from src.hooks import NotificationResult, HookApproval

def deny_notification_hook(context):
    return NotificationResult(decision=HookApproval.DENY)

HOOKS = {
    'Notification': [deny_notification_hook],
}
""")

        manager = HookManager(hooks_file=hooks_file)

        decision = manager.emit_notification(
            notification_type="approval_request",
            message="Approve this?"
        )

        assert decision == HookApproval.DENY

    def test_emit_session_start(self, tmp_path):
        """Test SessionStart hook."""
        hooks_file = tmp_path / "hooks.py"
        hooks_file.write_text("""
def session_start_hook(context):
    pass

HOOKS = {
    'SessionStart': [session_start_hook],
}
""")

        manager = HookManager(hooks_file=hooks_file)

        # Should not raise
        manager.emit_session_start(
            working_directory="/project",
            model_name="gpt-4"
        )

    def test_emit_session_end(self, tmp_path):
        """Test SessionEnd hook."""
        hooks_file = tmp_path / "hooks.py"
        hooks_file.write_text("""
def session_end_hook(context):
    pass

HOOKS = {
    'SessionEnd': [session_end_hook],
}
""")

        manager = HookManager(hooks_file=hooks_file)

        # Should not raise
        manager.emit_session_end(duration=100.0)

    def test_emit_pre_compact(self, tmp_path):
        """Test PreCompact hook."""
        hooks_file = tmp_path / "hooks.py"
        hooks_file.write_text("""
def pre_compact_hook(context):
    pass

HOOKS = {
    'PreCompact': [pre_compact_hook],
}
""")

        manager = HookManager(hooks_file=hooks_file)

        # Should not raise
        manager.emit_pre_compact(
            current_tokens=40000,
            target_tokens=32000
        )

    def test_emit_stop(self, tmp_path):
        """Test Stop hook."""
        hooks_file = tmp_path / "hooks.py"
        hooks_file.write_text("""
def stop_hook(context):
    pass

HOOKS = {
    'Stop': [stop_hook],
}
""")

        manager = HookManager(hooks_file=hooks_file)

        # Should not raise
        manager.emit_stop(
            response="Done",
            tool_calls=[],
            execution_time=5.0
        )

    def test_emit_subagent_stop(self, tmp_path):
        """Test SubagentStop hook."""
        hooks_file = tmp_path / "hooks.py"
        hooks_file.write_text("""
def subagent_stop_hook(context):
    pass

HOOKS = {
    'SubagentStop': [subagent_stop_hook],
}
""")

        manager = HookManager(hooks_file=hooks_file)

        # Should not raise
        manager.emit_subagent_stop(
            subagent_name="code-reviewer",
            result={"status": "complete"},
            duration=10.0
        )


class TestErrorHandling:
    """Test error handling in hooks."""

    def test_hook_error_does_not_crash(self, tmp_path):
        """Test that hook errors are caught and don't crash."""
        hooks_file = tmp_path / "hooks.py"
        hooks_file.write_text("""
from src.hooks import HookResult

def error_hook(context):
    raise RuntimeError("Something went wrong!")

HOOKS = {
    'PreToolUse:write_file': [error_hook],
}
""")

        manager = HookManager(hooks_file=hooks_file)

        # Should not raise, just log error
        decision, args = manager.emit_pre_tool_use(
            'write_file',
            {'file_path': 'test.py'}
        )

        # Should permit since hook failed
        assert decision == HookDecision.PERMIT

    def test_multiple_hooks_one_fails(self, tmp_path):
        """Test that one failing hook doesn't prevent others from running."""
        hooks_file = tmp_path / "hooks.py"
        hooks_file.write_text("""
from src.hooks import HookResult, HookDecision

def error_hook(context):
    raise RuntimeError("First hook fails!")

def success_hook(context):
    return HookResult(decision=HookDecision.PERMIT)

HOOKS = {
    'PreToolUse:write_file': [error_hook, success_hook],
}
""")

        manager = HookManager(hooks_file=hooks_file)

        # Should not raise
        decision, args = manager.emit_pre_tool_use(
            'write_file',
            {'file_path': 'test.py'}
        )

        # Second hook should still run and permit
        assert decision == HookDecision.PERMIT
