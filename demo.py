"""
Demo script for the AI Coding Agent.

The agent now runs exclusively through the TUI (Textual UI).
Use: python -m src.cli
"""

from rich.console import Console
from rich.panel import Panel

console = Console()


def main():
    """Run demo - launch TUI."""
    console.print(Panel.fit(
        "[bold cyan]AI Coding Agent[/bold cyan]\n"
        "Launch the TUI with: python -m src.cli",
        border_style="cyan"
    ))

    console.print("\nThe agent runs exclusively through the Textual TUI.")
    console.print("All interactions use the async stream_response() path.")
    console.print("\n[yellow]Launch:[/yellow]")
    console.print("  python -m src.cli")


if __name__ == "__main__":
    main()
