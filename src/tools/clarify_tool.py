"""
Clarify Tool - Ask user clarifying questions before proceeding with ambiguous tasks.

This tool provides a CLI fallback for when TUI is not available.
In TUI mode, the ClarifyWidget handles the interactive UI.
"""

from typing import Any, Dict, List, Optional

from .base import Tool, ToolResult


class ClarifyTool(Tool):
    """
    Tool for asking structured clarifying questions.

    In TUI mode: Agent persists clarify_request, waits on UIProtocol,
    and the ClarifyWidget handles interaction.

    In CLI mode: This tool provides a simple numbered menu fallback.
    """

    def __init__(self):
        super().__init__(
            name="clarify",
            description="Ask the user clarifying questions before proceeding"
        )

    def _get_parameters(self) -> Dict[str, Any]:
        """Get parameter schema."""
        from .tool_schemas import CLARIFY_TOOL
        return CLARIFY_TOOL.parameters

    def execute(self, **kwargs) -> ToolResult:
        """
        Execute clarify tool in CLI mode (sync fallback).

        Returns:
            ToolResult with user responses or cancellation
        """
        questions = kwargs.get("questions", [])
        context = kwargs.get("context")

        # Validate
        if not questions:
            return ToolResult(
                success=False,
                output="",
                error="clarify.questions is empty"
            )

        if len(questions) > 4:
            return ToolResult(
                success=False,
                output="",
                error="clarify.questions has more than 4 questions (max: 4)"
            )

        # CLI prompt
        result = self._cli_prompt(questions, context)
        return ToolResult(
            success=True,
            output=str(result)
        )

    def _cli_prompt(
        self,
        questions: List[Dict[str, Any]],
        context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Simple CLI fallback for clarify tool.

        Args:
            questions: List of question dicts
            context: Optional context string

        Returns:
            Dict with responses or cancellation status
        """
        print("\n" + "=" * 60)
        print("? Clarification needed")
        print("=" * 60)

        if context:
            print(f"\nContext: {context}\n")

        responses: Dict[str, Any] = {}

        for i, question in enumerate(questions):
            q_id = question.get("id", f"q{i}")
            q_label = question.get("label", f"Question {i+1}")
            q_text = question.get("question", "")
            options = question.get("options", [])
            multi_select = question.get("multi_select", False)
            allow_custom = question.get("allow_custom", False)

            print(f"\n[{q_label}] {q_text}")
            print("-" * 40)

            for j, option in enumerate(options):
                opt_label = option.get("label", f"Option {j+1}")
                opt_desc = option.get("description", "")
                recommended = option.get("recommended", False)

                marker = " (Recommended)" if recommended else ""
                desc_text = f" - {opt_desc}" if opt_desc else ""
                print(f"  {j+1}. {opt_label}{marker}{desc_text}")

            if allow_custom:
                print(f"  {len(options)+1}. Type custom response...")

            print("  0. Cancel")

            # Get selection
            while True:
                try:
                    if multi_select:
                        raw = input(f"\nSelect options (comma-separated, e.g., 1,2): ").strip()
                        if raw == "0":
                            return {"cancelled": True}

                        selections = []
                        for part in raw.split(","):
                            num = int(part.strip())
                            if 1 <= num <= len(options):
                                selections.append(options[num-1].get("id", f"opt{num}"))
                            elif allow_custom and num == len(options) + 1:
                                custom = input("Enter custom response: ").strip()
                                selections.append(f"custom:{custom}")

                        if selections:
                            responses[q_id] = selections
                            break
                        print("Invalid selection. Try again.")
                    else:
                        raw = input(f"\nSelect an option: ").strip()
                        if raw == "0":
                            return {"cancelled": True}

                        num = int(raw)
                        if 1 <= num <= len(options):
                            responses[q_id] = options[num-1].get("id", f"opt{num}")
                            break
                        elif allow_custom and num == len(options) + 1:
                            custom = input("Enter custom response: ").strip()
                            responses[q_id] = f"custom:{custom}"
                            break
                        print("Invalid selection. Try again.")

                except (ValueError, IndexError):
                    print("Invalid input. Enter a number.")

        print("\n" + "=" * 60)
        print("Responses collected")
        print("=" * 60 + "\n")

        return {"submitted": True, "responses": responses}

    def cli_prompt_as_result(
        self,
        call_id: str,
        questions: List[Dict[str, Any]],
        context: Optional[str] = None
    ) -> "ClarifyResult":
        """
        CLI prompt that returns a ClarifyResult for protocol compatibility.

        Args:
            call_id: Tool call ID
            questions: List of question dicts
            context: Optional context string

        Returns:
            ClarifyResult dataclass
        """
        # Import here to avoid circular imports
        from src.core.protocol import ClarifyResult

        result = self._cli_prompt(questions, context)

        if result.get("cancelled"):
            return ClarifyResult(
                call_id=call_id,
                submitted=False,
                responses=None,
                chat_instead=False,
                chat_message=None
            )

        return ClarifyResult(
            call_id=call_id,
            submitted=True,
            responses=result.get("responses"),
            chat_instead=False,
            chat_message=None
        )


# Export
__all__ = ['ClarifyTool']
