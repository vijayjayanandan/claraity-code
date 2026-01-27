"""
Internal Textual Messages - Widget <-> App communication.

These are NOT part of the public contract. They're internal to the UI layer.
Use these for Textual's message-passing system between widgets and the App.
"""

from textual.message import Message


class ApprovalResponseMessage(Message):
    """
    User responded to a tool approval prompt.

    Posted by ToolApprovalOptions, handled by CodingAgentApp.
    """

    def __init__(
        self,
        call_id: str,
        action: str,
        feedback: str | None = None
    ):
        super().__init__()
        self.call_id = call_id
        self.action = action  # "yes", "yes_all", "no", "feedback"
        self.feedback = feedback  # User's modified instructions (if action == "feedback")


class StreamInterruptMessage(Message):
    """
    User requested stream interruption (Ctrl+C).

    Posted by keybinding handler, triggers cancellation.
    """
    pass


class RetryRequestMessage(Message):
    """
    User clicked retry after a recoverable error.
    """
    pass


class ScrollStateChangedMessage(Message):
    """
    User scroll position changed.

    Used to track whether auto-scroll should be enabled.
    """

    def __init__(self, at_bottom: bool):
        super().__init__()
        self.at_bottom = at_bottom


class InputSubmittedMessage(Message):
    """
    User submitted input with optional attachments.

    Decouples TextArea from submission logic.

    Attributes:
        content: Text content of the message
        attachments: List of Attachment objects (screenshots, files)
    """

    def __init__(self, content: str, attachments: list | None = None):
        super().__init__()
        self.content = content
        self.attachments = attachments or []


class PauseResponseMessage(Message):
    """
    User responded to a pause prompt.

    Posted by PausePromptWidget, handled by CodingAgentApp.
    Simple two options: continue_work=True (Continue) or continue_work=False (Stop).
    """

    def __init__(self, continue_work: bool):
        super().__init__()
        self.continue_work = continue_work


class ClarifyResponseMessage(Message):
    """
    User responded to a clarify prompt.

    Posted by ClarifyWidget, handled by CodingAgentApp.
    Contains the user's answers to all questions.
    """

    def __init__(
        self,
        call_id: str,
        submitted: bool,
        responses: dict | None = None,
        chat_instead: bool = False,
        chat_message: str | None = None
    ):
        super().__init__()
        self.call_id = call_id
        self.submitted = submitted
        self.responses = responses  # question_id -> selected_option_id(s)
        self.chat_instead = chat_instead
        self.chat_message = chat_message


class PlanApprovalResponseMessage(Message):
    """
    User responded to a plan approval prompt.

    Posted by PlanApprovalWidget, handled by CodingAgentApp.
    """

    def __init__(
        self,
        plan_hash: str,
        approved: bool,
        auto_accept_edits: bool = False,
        feedback: str | None = None
    ):
        super().__init__()
        self.plan_hash = plan_hash
        self.approved = approved
        self.auto_accept_edits = auto_accept_edits  # Auto-approve edit_file during implementation
        self.feedback = feedback  # User's feedback for revisions


# Export all message types
__all__ = [
    'ApprovalResponseMessage',
    'StreamInterruptMessage',
    'RetryRequestMessage',
    'ScrollStateChangedMessage',
    'InputSubmittedMessage',
    'PauseResponseMessage',
    'ClarifyResponseMessage',
    'PlanApprovalResponseMessage',
]
