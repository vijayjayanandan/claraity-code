"""
ClarifyWidget - Multi-tab interactive question/answer UI.

Replicates the Claude Code AskUserQuestion pattern:
- Tab bar for navigating between questions + final Submit tab
- Single-select: Enter selects + auto-advances
- Multi-select: Enter toggles checkbox, Submit button to advance
- Review tab: summary of all answers before submitting
- Freeform text input on every question ("Type something")
- "Chat about this" escape hatch
"""

from typing import Any, Optional

from rich.console import RenderableType
from rich.text import Text
from textual.binding import Binding
from textual.containers import Container
from textual.reactive import reactive
from textual.widgets import Static

from ..messages import ClarifyResponseMessage


class _TabBar(Static):
    """Horizontal tab navigation bar."""

    def __init__(self, labels: list[str], **kwargs):
        super().__init__(**kwargs)
        self.labels = labels
        self.active_index = 0
        self.completed: set[int] = set()

    def set_active(self, index: int, completed: set[int] | None = None) -> None:
        self.active_index = index
        if completed is not None:
            self.completed = completed
        self.refresh()

    def render(self) -> RenderableType:
        t = Text()
        t.append("<- ", style="dim")
        for i, label in enumerate(self.labels):
            # Separator
            if i > 0:
                t.append("  ", style="dim")

            is_active = (i == self.active_index)
            is_done = (i in self.completed)

            if is_active:
                # Active tab: highlighted background
                t.append(f" {label} ", style="bold reverse")
            elif is_done:
                # Completed: checkmark + dimmed
                t.append(f"(x) {label}", style="dim green")
            else:
                t.append(f"( ) {label}", style="dim")

        t.append("  ->", style="dim")
        return t


class _QuestionPanel(Static):
    """Renders the current question with options."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._question: dict[str, Any] = {}
        self._option_index: int = 0
        self._multi_select: bool = False
        self._checked: set[int] = set()  # indices of checked options
        self._in_custom_mode: bool = False
        self._custom_text: str = ""
        self._total_options: int = 0  # includes Type something + Chat/Submit

    def set_question(
        self,
        question: dict[str, Any],
        option_index: int,
        checked: set[int],
        custom_text: str,
    ) -> None:
        self._question = question
        self._option_index = option_index
        self._multi_select = question.get("multi_select", False)
        self._checked = checked
        self._custom_text = custom_text

        options = question.get("options", [])
        # Options count: real options + "Type something" + "Submit"(multi) or nothing + "Chat about this"
        self._total_options = len(options) + 1  # +1 for "Type something"
        if self._multi_select:
            self._total_options += 1  # +1 for "Submit"
        self._total_options += 1  # +1 for "Chat about this"

        # Check if cursor is on the "Type something" row
        type_something_idx = len(options)
        self._in_custom_mode = (option_index == type_something_idx)

        self.refresh()

    def set_review(
        self,
        questions: list[dict[str, Any]],
        responses: dict[str, Any],
        option_index: int,
    ) -> None:
        """Set the review/submit tab content."""
        self._question = {"_review": True, "questions": questions, "responses": responses}
        self._option_index = option_index
        self._multi_select = False
        self._total_options = 2  # Submit / Cancel
        self._in_custom_mode = False
        self.refresh()

    def render(self) -> RenderableType:
        q = self._question
        if not q:
            return Text("(no question)")

        # Review tab
        if q.get("_review"):
            return self._render_review(q)

        t = Text()

        # Question text
        t.append(q.get("question", ""), style="bold white")
        t.append("\n\n")

        options = q.get("options", [])

        # Render each option
        for i, opt in enumerate(options):
            is_selected = (i == self._option_index)
            prefix = "> " if is_selected else "  "

            if self._multi_select:
                check = "[x]" if i in self._checked else "[ ]"
                label_str = f"{prefix}{i + 1}. {check} {opt.get('label', '')}"
            else:
                label_str = f"{prefix}{i + 1}. {opt.get('label', '')}"

            label_style = "bold white" if is_selected else "white"
            t.append(label_str + "\n", style=label_style)

            # Description
            desc = opt.get("description", "")
            if desc:
                t.append(f"     {desc}\n", style="dim")

        # "Type something" option — ghost placeholder when empty
        type_idx = len(options)
        is_type_selected = (self._option_index == type_idx)
        type_prefix = "> " if is_type_selected else "  "

        if self._multi_select:
            type_check = "[x]" if type_idx in self._checked else "[ ]"
            type_num = f"{type_prefix}{type_idx + 1}. {type_check} "
        else:
            type_num = f"{type_prefix}{type_idx + 1}. "

        type_style = "bold white" if is_type_selected else "white"
        t.append(type_num, style=type_style)

        if self._custom_text:
            # User has typed text — show it, no ghost label
            t.append(self._custom_text, style="bold cyan")
            if is_type_selected:
                t.append("_", style="blink bold cyan")
        elif is_type_selected:
            # Focused but empty — show cursor
            t.append("_", style="blink bold cyan")
        else:
            # Not focused, empty — show ghost placeholder
            t.append("Type something", style="dim italic")
        t.append("\n")

        # "Submit" button for multi-select
        if self._multi_select:
            submit_idx = type_idx + 1
            is_submit_selected = (self._option_index == submit_idx)
            submit_prefix = "> " if is_submit_selected else "  "
            submit_style = "bold white" if is_submit_selected else "white"
            t.append(f"     {submit_prefix}Submit\n", style=submit_style)
            chat_idx = submit_idx + 1
        else:
            chat_idx = type_idx + 1

        # "Chat about this" option
        t.append("\n")
        is_chat_selected = (self._option_index == chat_idx)
        chat_prefix = "> " if is_chat_selected else "  "
        chat_style = "bold white" if is_chat_selected else "dim"
        t.append(f"{chat_prefix}{chat_idx + 1}. Chat about this\n", style=chat_style)

        return t

    def _render_review(self, q: dict[str, Any]) -> RenderableType:
        t = Text()
        t.append("Review your answers\n\n", style="bold white")

        questions = q.get("questions", [])
        responses = q.get("responses", {})

        for question in questions:
            qid = question.get("id", "")
            t.append(f"  * {question.get('question', '')}\n", style="white")

            answer = responses.get(qid)
            if answer is None:
                t.append("    -> (no answer)\n", style="dim italic")
            elif isinstance(answer, list):
                # Multi-select: look up labels
                labels = []
                for aid in answer:
                    if aid.startswith("custom:"):
                        labels.append(aid[7:])
                    else:
                        for opt in question.get("options", []):
                            if opt.get("id") == aid:
                                labels.append(opt.get("label", aid))
                                break
                        else:
                            labels.append(aid)
                t.append(f"    -> {', '.join(labels)}\n", style="bold cyan")
            else:
                # Single-select: look up label
                label = answer
                if answer.startswith("custom:"):
                    label = answer[7:]
                else:
                    for opt in question.get("options", []):
                        if opt.get("id") == answer:
                            label = opt.get("label", answer)
                            break
                t.append(f"    -> {label}\n", style="bold cyan")

        t.append("\nReady to submit your answers?\n\n", style="white")

        # Submit / Cancel options
        submit_prefix = "> " if self._option_index == 0 else "  "
        cancel_prefix = "> " if self._option_index == 1 else "  "
        submit_style = "bold white" if self._option_index == 0 else "white"
        cancel_style = "bold white" if self._option_index == 1 else "white"
        t.append(f"{submit_prefix}1. Submit answers\n", style=submit_style)
        t.append(f"{cancel_prefix}2. Cancel\n", style=cancel_style)

        return t


class ClarifyWidget(Container, can_focus=True):
    """
    Multi-tab interactive question/answer widget.

    Architecture:
        ClarifyWidget (Container, can_focus)
        +-- _TabBar         -- horizontal tab navigation
        +-- _QuestionPanel  -- current question content + options
        +-- _HintBar (Static) -- keyboard hints

    Keyboard:
        Up/Down      Navigate options within current question
        Enter        Single-select: select + advance. Multi-select: toggle.
        Tab/Right    Next tab
        Shift+Tab/Left  Previous tab
        Esc          Cancel entire widget
        1-9          Quick-select option
        Printable    Type into freeform field
        Backspace    Delete char in freeform field
    """

    BINDINGS = [
        Binding("up", "move_up", "Up", show=False, priority=True),
        Binding("down", "move_down", "Down", show=False, priority=True),
        Binding("enter", "select", "Select", show=False, priority=True),
        Binding("escape", "cancel", "Cancel", show=False, priority=True),
        Binding("tab", "next_tab", "Next tab", show=False, priority=True),
        Binding("shift+tab", "prev_tab", "Prev tab", show=False, priority=True),
        Binding("right", "next_tab", "Next tab", show=False, priority=True),
        Binding("left", "prev_tab", "Prev tab", show=False, priority=True),
        Binding("backspace", "backspace", "Backspace", show=False, priority=True),
    ]

    current_tab = reactive(0)
    current_option = reactive(0)

    DEFAULT_CSS = """
    ClarifyWidget {
        height: auto;
        padding: 1;
        margin: 1 0;
        background: #1a1a2e;
        border: solid #4a9eff;
        color: #e0e0e0;
    }

    ClarifyWidget:focus-within {
        border: solid #6bb3ff;
        background: #16213e;
    }

    ClarifyWidget _TabBar {
        height: auto;
        margin-bottom: 1;
    }

    ClarifyWidget _QuestionPanel {
        height: auto;
        min-height: 5;
    }
    """

    def __init__(
        self,
        call_id: str,
        questions: list[dict[str, Any]],
        context: str | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.call_id = call_id
        self.questions = questions
        self.context = context

        # State per question
        self.responses: dict[str, Any] = {}  # qid -> selected option id(s)
        self.selections: dict[str, set] = {}  # qid -> set of checked option indices (multi-select)
        self.custom_texts: dict[str, str] = {}  # qid -> freeform text
        self.option_indices: dict[int, int] = {}  # tab_index -> current option index

        # Tab labels: one per question + "Submit"
        self._tab_labels = [q.get("label", f"Q{i+1}") for i, q in enumerate(questions)]
        self._tab_labels.append("Submit")
        self._tab_count = len(self._tab_labels)
        self._completed_tabs: set[int] = set()

    def compose(self):
        yield _TabBar(self._tab_labels, id="clarify-tabs")
        yield _QuestionPanel(id="clarify-panel")
        yield Static("Enter to select . Tab/Arrow keys to navigate . Esc to cancel", id="clarify-hints")

    def on_mount(self) -> None:
        self.call_after_refresh(self._ensure_focus)
        self.set_timer(0.1, self._ensure_focus)
        self._refresh_display()

    def _ensure_focus(self) -> None:
        if not self.has_focus:
            self.focus()
            self.scroll_visible()

    # -- Display refresh --

    def _refresh_display(self) -> None:
        """Refresh tab bar and question panel for current state."""
        try:
            tab_bar = self.query_one("#clarify-tabs", _TabBar)
            tab_bar.set_active(self.current_tab, self._completed_tabs)
        except Exception:
            pass

        try:
            panel = self.query_one("#clarify-panel", _QuestionPanel)
            if self.current_tab < len(self.questions):
                # Question tab
                q = self.questions[self.current_tab]
                qid = q.get("id", f"q_{self.current_tab}")
                panel.set_question(
                    question=q,
                    option_index=self.current_option,
                    checked=self.selections.get(qid, set()),
                    custom_text=self.custom_texts.get(qid, ""),
                )
            else:
                # Submit/review tab
                panel.set_review(
                    questions=self.questions,
                    responses=self.responses,
                    option_index=self.current_option,
                )
        except Exception:
            pass

    def watch_current_tab(self, value: int) -> None:
        self.current_option = self.option_indices.get(value, 0)
        self._refresh_display()

    def watch_current_option(self, value: int) -> None:
        # Save option index for this tab
        self.option_indices[self.current_tab] = value
        self._refresh_display()

    # -- Helpers --

    def _get_option_count(self) -> int:
        """Total selectable items for current tab."""
        if self.current_tab >= len(self.questions):
            return 2  # Submit / Cancel

        q = self.questions[self.current_tab]
        options = q.get("options", [])
        count = len(options) + 1  # +1 for "Type something"
        if q.get("multi_select", False):
            count += 1  # +1 for "Submit" button
        count += 1  # +1 for "Chat about this"
        return count

    def _is_on_type_something(self) -> bool:
        """Check if cursor is on the 'Type something' row."""
        if self.current_tab >= len(self.questions):
            return False
        q = self.questions[self.current_tab]
        options = q.get("options", [])
        return self.current_option == len(options)

    def _is_on_chat(self) -> bool:
        """Check if cursor is on 'Chat about this'."""
        return self.current_option == self._get_option_count() - 1

    def _is_on_multi_submit(self) -> bool:
        """Check if cursor is on the multi-select Submit button."""
        if self.current_tab >= len(self.questions):
            return False
        q = self.questions[self.current_tab]
        if not q.get("multi_select", False):
            return False
        options = q.get("options", [])
        return self.current_option == len(options) + 1  # After Type something

    # -- Key handling --

    def on_key(self, event) -> None:
        """Handle printable character input for freeform text and digit shortcuts."""
        if not event.is_printable or not event.character:
            return

        # Space toggles checkbox in multi-select (except on "Type something" row)
        if event.character == " " and not self._is_on_type_something():
            if self.current_tab < len(self.questions):
                q = self.questions[self.current_tab]
                if q.get("multi_select", False):
                    self._toggle_current_checkbox()
                    event.prevent_default()
                    event.stop()
                    return

        # If on "Type something" row, capture text (including space)
        if self._is_on_type_something():
            qid = self.questions[self.current_tab].get("id", f"q_{self.current_tab}")
            self.custom_texts[qid] = self.custom_texts.get(qid, "") + event.character
            self._refresh_display()
            event.prevent_default()
            event.stop()
            return

        # Digit shortcuts (not in text mode)
        if event.character.isdigit():
            num = int(event.character)
            max_opts = self._get_option_count()
            if 1 <= num <= max_opts:
                self.current_option = num - 1
                event.prevent_default()
                event.stop()
                return

    def action_backspace(self) -> None:
        """Delete last char in freeform text field."""
        if self._is_on_type_something() and self.current_tab < len(self.questions):
            qid = self.questions[self.current_tab].get("id", f"q_{self.current_tab}")
            text = self.custom_texts.get(qid, "")
            if text:
                self.custom_texts[qid] = text[:-1]
                self._refresh_display()

    def action_move_up(self) -> None:
        self.current_option = max(0, self.current_option - 1)

    def action_move_down(self) -> None:
        self.current_option = min(self._get_option_count() - 1, self.current_option + 1)

    def action_next_tab(self) -> None:
        if self.current_tab < self._tab_count - 1:
            self.current_tab += 1

    def action_prev_tab(self) -> None:
        if self.current_tab > 0:
            self.current_tab -= 1

    def _toggle_current_checkbox(self) -> None:
        """Toggle the checkbox for the current option in multi-select mode."""
        if self.current_tab >= len(self.questions):
            return
        q = self.questions[self.current_tab]
        qid = q.get("id", f"q_{self.current_tab}")
        options = q.get("options", [])
        idx = self.current_option

        # Only toggle real options and the "Type something" row
        if idx <= len(options):
            checked = self.selections.setdefault(qid, set())
            if idx in checked:
                checked.discard(idx)
            else:
                checked.add(idx)
            self._refresh_display()

    def action_cancel(self) -> None:
        """Cancel the entire clarify widget."""
        self.post_message(ClarifyResponseMessage(
            call_id=self.call_id,
            submitted=False,
        ))

    def action_select(self) -> None:
        """Handle Enter key."""
        # Review/submit tab
        if self.current_tab >= len(self.questions):
            if self.current_option == 0:
                # Submit answers
                self.post_message(ClarifyResponseMessage(
                    call_id=self.call_id,
                    submitted=True,
                    responses=dict(self.responses),
                ))
            else:
                # Cancel
                self.post_message(ClarifyResponseMessage(
                    call_id=self.call_id,
                    submitted=False,
                ))
            return

        q = self.questions[self.current_tab]
        qid = q.get("id", f"q_{self.current_tab}")
        options = q.get("options", [])
        is_multi = q.get("multi_select", False)

        # "Chat about this"
        if self._is_on_chat():
            # Use custom text as chat message if typed, otherwise empty
            chat_msg = self.custom_texts.get(qid, "")
            self.post_message(ClarifyResponseMessage(
                call_id=self.call_id,
                submitted=False,
                chat_instead=True,
                chat_message=chat_msg or None,
            ))
            return

        # Multi-select "Submit" button
        if self._is_on_multi_submit():
            self._finalize_question(qid, q)
            return

        # "Type something" row
        if self._is_on_type_something():
            if is_multi:
                # Toggle the custom text as a checked option
                type_idx = len(options)
                checked = self.selections.setdefault(qid, set())
                if type_idx in checked:
                    checked.discard(type_idx)
                else:
                    checked.add(type_idx)
                self._refresh_display()
            else:
                # Single-select: use custom text as response
                text = self.custom_texts.get(qid, "")
                if text:
                    self.responses[qid] = f"custom:{text}"
                    self._completed_tabs.add(self.current_tab)
                    self._advance_tab()
            return

        # Regular option
        opt_index = self.current_option
        if opt_index < len(options):
            opt = options[opt_index]
            opt_id = opt.get("id", f"opt_{opt_index}")

            if is_multi:
                # Toggle checkbox
                checked = self.selections.setdefault(qid, set())
                if opt_index in checked:
                    checked.discard(opt_index)
                else:
                    checked.add(opt_index)
                self._refresh_display()
            else:
                # Single-select: pick and advance
                self.responses[qid] = opt_id
                self._completed_tabs.add(self.current_tab)
                self._advance_tab()

    def _finalize_question(self, qid: str, question: dict[str, Any]) -> None:
        """Finalize multi-select question and advance."""
        options = question.get("options", [])
        checked = self.selections.get(qid, set())
        custom_text = self.custom_texts.get(qid, "").strip()

        selected_ids = []
        custom_included = False
        for idx in sorted(checked):
            if idx < len(options):
                selected_ids.append(options[idx].get("id", f"opt_{idx}"))
            elif idx == len(options):
                # "Type something" was explicitly checked
                if custom_text:
                    selected_ids.append(f"custom:{custom_text}")
                    custom_included = True

        # Auto-include custom text if user typed something, even without
        # explicitly toggling the checkbox — typing implies intent
        if custom_text and not custom_included:
            selected_ids.append(f"custom:{custom_text}")

        self.responses[qid] = selected_ids
        self._completed_tabs.add(self.current_tab)
        self._advance_tab()

    def _advance_tab(self) -> None:
        """Move to the next tab."""
        if self.current_tab < self._tab_count - 1:
            self.current_tab += 1


__all__ = ['ClarifyWidget']
