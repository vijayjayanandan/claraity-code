"""Command-line interface for the AI coding agent."""

import sys
from pathlib import Path
from typing import Optional
import argparse

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt

from src.core import CodingAgent


console = Console()


def chat_mode(agent: CodingAgent) -> None:
    """Interactive chat mode."""
    console.print(Panel.fit(
        "[bold cyan]AI Coding Agent - Interactive Mode[/bold cyan]\n"
        f"Model: {agent.model_name}\n"
        f"Context: {agent.context_window} tokens\n"
        "Type 'exit' or 'quit' to leave, 'help' for commands",
        border_style="cyan"
    ))

    while True:
        try:
            # Get user input
            user_input = Prompt.ask("\n[bold green]You[/bold green]")

            if not user_input.strip():
                continue

            # Handle commands
            if user_input.lower() in ["exit", "quit", "q"]:
                console.print("[yellow]Goodbye![/yellow]")
                break

            if user_input.lower() == "help":
                show_help()
                continue

            if user_input.lower() == "stats":
                show_stats(agent)
                continue

            if user_input.lower().startswith("save"):
                parts = user_input.split(maxsplit=1)
                session_name = parts[1] if len(parts) > 1 else None
                path = agent.save_session(session_name)
                console.print(f"[green]Session saved to: {path}[/green]")
                continue

            if user_input.lower() == "clear":
                agent.clear_memory()
                console.print("[green]Memory cleared![/green]")
                continue

            # Process with agent
            console.print("\n[bold blue]Agent[/bold blue]")
            response = agent.chat(user_input, stream=True)

        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted. Type 'exit' to quit.[/yellow]")
            continue
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")


def show_help() -> None:
    """Show help information."""
    help_text = """
**Available Commands:**
- `exit/quit` - Exit the chat
- `help` - Show this help
- `stats` - Show agent statistics
- `save [name]` - Save current session
- `clear` - Clear memory

**Available Tools:**
- read_file - Read a file
- write_file - Write to a file
- edit_file - Edit a file
- search_code - Search in code
- analyze_code - Analyze code structure
"""
    console.print(Markdown(help_text))


def show_stats(agent: CodingAgent) -> None:
    """Show agent statistics."""
    stats = agent.get_statistics()

    console.print("\n[bold cyan]Agent Statistics:[/bold cyan]")
    console.print(f"  Model: {stats['model']}")
    console.print(f"  Context Window: {stats['context_window']} tokens")
    console.print(f"  Indexed Chunks: {stats['indexed_chunks']}")

    memory_stats = stats['memory']
    console.print(f"\n[bold cyan]Memory:[/bold cyan]")
    console.print(f"  Working Memory: {memory_stats['working_memory']['tokens']} tokens")
    console.print(f"  Episodic Turns: {memory_stats['episodic_memory']['total_turns']}")
    console.print(f"  Session Duration: {memory_stats['session_duration_minutes']:.1f} min")


def task_mode(agent: CodingAgent, task: str, task_type: str = "implement") -> None:
    """Single task execution mode."""
    console.print(f"\n[bold cyan]Executing task:[/bold cyan] {task}\n")

    try:
        response = agent.execute_task(
            task_description=task,
            task_type=task_type,
            stream=True,
        )

        console.print(f"\n[green]Task completed![/green]")

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def index_mode(agent: CodingAgent, directory: str) -> None:
    """Index codebase mode."""
    console.print(f"\n[bold cyan]Indexing codebase:[/bold cyan] {directory}\n")

    try:
        stats = agent.index_codebase(directory=directory)

        console.print("\n[green]Indexing complete![/green]")
        console.print(f"  Files indexed: {stats['total_files']}")
        console.print(f"  Chunks created: {stats['total_chunks']}")
        console.print(f"  Languages: {', '.join(stats['languages'].keys())}")

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="AI Coding Agent - Optimized for small open-source LLMs"
    )

    parser.add_argument(
        "--model",
        default="deepseek-coder:6.7b-instruct",
        help="Model name (default: deepseek-coder:6.7b-instruct)"
    )

    parser.add_argument(
        "--backend",
        default="ollama",
        choices=["ollama", "vllm", "localai"],
        help="LLM backend (default: ollama)"
    )

    parser.add_argument(
        "--url",
        default="http://localhost:11434",
        help="Backend API URL (default: http://localhost:11434)"
    )

    parser.add_argument(
        "--context",
        type=int,
        default=4096,
        help="Context window size (default: 4096)"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Chat command
    subparsers.add_parser("chat", help="Interactive chat mode")

    # Task command
    task_parser = subparsers.add_parser("task", help="Execute a single task")
    task_parser.add_argument("description", help="Task description")
    task_parser.add_argument(
        "--type",
        default="implement",
        choices=["implement", "debug", "refactor", "explain", "test", "review"],
        help="Task type"
    )

    # Index command
    index_parser = subparsers.add_parser("index", help="Index codebase for RAG")
    index_parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to index (default: current)"
    )

    args = parser.parse_args()

    # Initialize agent
    console.print(f"\n[cyan]Initializing AI Coding Agent...[/cyan]")
    console.print(f"Model: {args.model}")
    console.print(f"Backend: {args.backend}")

    try:
        agent = CodingAgent(
            model_name=args.model,
            backend=args.backend,
            base_url=args.url,
            context_window=args.context,
        )

        # Check if backend is available
        if not agent.llm.is_available():
            console.print(f"[red]Error: {args.backend} backend not available at {args.url}[/red]")
            console.print(f"[yellow]Make sure {args.backend} is running and accessible[/yellow]")
            sys.exit(1)

        console.print(f"[green]Agent initialized successfully![/green]\n")

        # Execute command
        if args.command == "chat":
            chat_mode(agent)
        elif args.command == "task":
            task_mode(agent, args.description, args.type)
        elif args.command == "index":
            index_mode(agent, args.directory)
        else:
            # Default to chat mode
            chat_mode(agent)

    except Exception as e:
        console.print(f"[red]Failed to initialize agent: {e}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
