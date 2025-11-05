"""Unit tests for hook result classes."""

import pytest
from src.hooks.result import HookResult, UserPromptResult, NotificationResult
from src.hooks.events import HookDecision, HookContinue, HookApproval


class TestHookResult:
    """Test HookResult class."""

    def test_create_minimal_defaults_to_permit(self):
        """Test that default decision is PERMIT."""
        result = HookResult()

        assert result.decision == HookDecision.PERMIT
        assert result.message is None
        assert result.modified_arguments is None
        assert result.modified_result is None
        assert result.metadata == {}

    def test_create_deny_with_message(self):
        """Test creating DENY result with message."""
        result = HookResult(
            decision=HookDecision.DENY,
            message="Invalid file extension"
        )

        assert result.decision == HookDecision.DENY
        assert result.message == "Invalid file extension"

    def test_create_block_with_message(self):
        """Test creating BLOCK result."""
        result = HookResult(
            decision=HookDecision.BLOCK,
            message="Dangerous operation blocked"
        )

        assert result.decision == HookDecision.BLOCK
        assert result.message == "Dangerous operation blocked"

    def test_create_with_modified_arguments(self):
        """Test creating result with modified arguments."""
        result = HookResult(
            decision=HookDecision.PERMIT,
            modified_arguments={"file_path": "test.txt", "validated": True}
        )

        assert result.modified_arguments["file_path"] == "test.txt"
        assert result.modified_arguments["validated"] is True

    def test_create_with_modified_result(self):
        """Test creating result with modified result."""
        result = HookResult(
            decision=HookDecision.PERMIT,
            modified_result={"status": "success", "formatted": True}
        )

        assert result.modified_result["status"] == "success"
        assert result.modified_result["formatted"] is True

    def test_create_with_metadata(self):
        """Test creating result with metadata."""
        result = HookResult(
            decision=HookDecision.PERMIT,
            metadata={"hook_name": "validate_write", "execution_time_ms": 0.5}
        )

        assert result.metadata["hook_name"] == "validate_write"
        assert result.metadata["execution_time_ms"] == 0.5

    def test_result_serialization(self):
        """Test that result can be serialized to dict."""
        result = HookResult(
            decision=HookDecision.DENY,
            message="Test message",
            modified_arguments={"key": "value"}
        )

        result_dict = result.model_dump()

        assert result_dict["decision"] == HookDecision.DENY
        assert result_dict["message"] == "Test message"
        assert result_dict["modified_arguments"]["key"] == "value"


class TestUserPromptResult:
    """Test UserPromptResult class."""

    def test_create_minimal_defaults_to_continue(self):
        """Test that default decision is CONTINUE."""
        result = UserPromptResult()

        assert result.decision == HookContinue.CONTINUE
        assert result.modified_prompt is None
        assert result.message is None

    def test_create_continue_with_modified_prompt(self):
        """Test creating result with modified prompt."""
        result = UserPromptResult(
            decision=HookContinue.CONTINUE,
            modified_prompt="Sanitized prompt text"
        )

        assert result.decision == HookContinue.CONTINUE
        assert result.modified_prompt == "Sanitized prompt text"

    def test_create_block_with_message(self):
        """Test creating BLOCK result."""
        result = UserPromptResult(
            decision=HookContinue.BLOCK,
            message="Prompt contains sensitive data"
        )

        assert result.decision == HookContinue.BLOCK
        assert result.message == "Prompt contains sensitive data"

    def test_result_serialization(self):
        """Test serialization."""
        result = UserPromptResult(
            decision=HookContinue.CONTINUE,
            modified_prompt="Modified"
        )

        result_dict = result.model_dump()

        assert result_dict["decision"] == HookContinue.CONTINUE
        assert result_dict["modified_prompt"] == "Modified"


class TestNotificationResult:
    """Test NotificationResult class."""

    def test_create_minimal_defaults_to_approve(self):
        """Test that default decision is APPROVE."""
        result = NotificationResult()

        assert result.decision == HookApproval.APPROVE
        assert result.message is None

    def test_create_approve_with_message(self):
        """Test creating APPROVE result with message."""
        result = NotificationResult(
            decision=HookApproval.APPROVE,
            message="Auto-approved low-risk operation"
        )

        assert result.decision == HookApproval.APPROVE
        assert result.message == "Auto-approved low-risk operation"

    def test_create_deny_with_message(self):
        """Test creating DENY result."""
        result = NotificationResult(
            decision=HookApproval.DENY,
            message="High-risk operation requires manual approval"
        )

        assert result.decision == HookApproval.DENY
        assert result.message == "High-risk operation requires manual approval"

    def test_result_serialization(self):
        """Test serialization."""
        result = NotificationResult(
            decision=HookApproval.DENY,
            message="Denied"
        )

        result_dict = result.model_dump()

        assert result_dict["decision"] == HookApproval.DENY
        assert result_dict["message"] == "Denied"


class TestResultValidation:
    """Test Pydantic validation on result classes."""

    def test_hook_result_validates_decision_type(self):
        """Test that invalid decision type is rejected."""
        # This should work
        result = HookResult(decision=HookDecision.PERMIT)
        assert result.decision == HookDecision.PERMIT

        # Invalid decision type should raise error
        with pytest.raises(Exception):  # Pydantic ValidationError
            HookResult(decision="invalid")

    def test_user_prompt_result_validates_decision_type(self):
        """Test that invalid decision type is rejected."""
        result = UserPromptResult(decision=HookContinue.CONTINUE)
        assert result.decision == HookContinue.CONTINUE

        with pytest.raises(Exception):
            UserPromptResult(decision="invalid")

    def test_notification_result_validates_decision_type(self):
        """Test that invalid decision type is rejected."""
        result = NotificationResult(decision=HookApproval.APPROVE)
        assert result.decision == HookApproval.APPROVE

        with pytest.raises(Exception):
            NotificationResult(decision="invalid")
