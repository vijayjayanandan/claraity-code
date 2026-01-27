"""
Textual widgets for the Coding Agent TUI.

This package contains the visual components:
- CodeBlock: Syntax-highlighted code with streaming support
- ThinkingBlock: Collapsible thinking/reasoning section
- ToolCard: Tool execution status with inline approval UI
- DiffWidget: Claude Code-style diff display with line numbers and colors
- MessageWidget: Container for conversation messages
- StatusBar: Bottom status bar with model info and shortcuts
- AutocompleteDropdown: Dropdown for @ file autocomplete suggestions
- AttachmentBar: Horizontal bar for managing attachments with navigation
- TodoBar: Collapsible todo list display for tracking agent tasks
- PausePromptWidget: Interactive pause/continue UI for budget limits
- ClarifyWidget: Multi-question clarification interview UI
- PlanApprovalWidget: Inline plan approval UI for plan mode
"""

from .code_block import CodeBlock
from .thinking import ThinkingBlock
from .tool_card import ToolCard, ToolApprovalOptions
from .diff_widget import DiffWidget, InlineDiffWidget
from .message import MessageWidget
from .status_bar import StatusBar
from .autocomplete_dropdown import AutocompleteDropdown
from .attachment_bar import AttachmentBar
from .todo_bar import TodoBar
from .pause_widget import PausePromptWidget
from .clarify_widget import ClarifyWidget
from .plan_approval_widget import PlanApprovalWidget

__all__ = [
    'CodeBlock',
    'ThinkingBlock',
    'ToolCard',
    'ToolApprovalOptions',
    'DiffWidget',
    'InlineDiffWidget',
    'MessageWidget',
    'StatusBar',
    'AutocompleteDropdown',
    'AttachmentBar',
    'TodoBar',
    'PausePromptWidget',
    'ClarifyWidget',
    'PlanApprovalWidget',
]
