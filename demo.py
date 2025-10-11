"""
Demo script for the AI Coding Agent.
Shows end-to-end functionality with all components working together.
"""

from src.core import CodingAgent
from rich.console import Console
from rich.panel import Panel

console = Console()


def main():
    """Run comprehensive demo."""

    console.print(Panel.fit(
        "[bold cyan]AI Coding Agent - Full Demo[/bold cyan]\n"
        "Demonstrating memory, RAG, prompts, and LLM integration",
        border_style="cyan"
    ))

    # Step 1: Initialize Agent
    console.print("\n[bold]Step 1: Initializing Agent[/bold]")
    console.print("Creating agent with CodeLlama 7B...")

    agent = CodingAgent(
        model_name="codellama:7b-instruct",
        backend="ollama",
        context_window=4096,
    )

    console.print("[green]✓ Agent initialized![/green]")

    # Step 2: Index Codebase
    console.print("\n[bold]Step 2: Indexing Codebase[/bold]")
    console.print("Indexing project for RAG retrieval...")

    stats = agent.index_codebase(directory="./src")

    console.print(f"[green]✓ Indexed {stats['total_files']} files, {stats['total_chunks']} chunks[/green]")

    # Step 3: Execute Tasks
    console.print("\n[bold]Step 3: Executing Coding Tasks[/bold]\n")

    # Task 1: Code explanation
    console.print("[cyan]Task 1: Explain the memory system[/cyan]")
    response = agent.execute_task(
        task_description="Explain how the hierarchical memory system works",
        task_type="explain",
        use_rag=True,
        stream=False,
    )
    console.print(f"[dim]{response.content[:200]}...[/dim]\n")

    # Task 2: Code implementation
    console.print("[cyan]Task 2: Implement a helper function[/cyan]")
    response = agent.execute_task(
        task_description="Create a helper function to format token usage statistics",
        task_type="implement",
        use_rag=True,
        stream=False,
    )
    console.print(f"[dim]{response.content[:200]}...[/dim]\n")

    # Step 4: Show Statistics
    console.print("\n[bold]Step 4: Agent Statistics[/bold]")

    stats = agent.get_statistics()
    memory_stats = stats['memory']

    console.print(f"Model: {stats['model']}")
    console.print(f"Context Window: {stats['context_window']} tokens")
    console.print(f"Indexed Chunks: {stats['indexed_chunks']}")
    console.print(f"Working Memory: {memory_stats['working_memory']['tokens']} tokens")
    console.print(f"Episodic Turns: {memory_stats['episodic_memory']['total_turns']}")

    # Step 5: Save Session
    console.print("\n[bold]Step 5: Save Session[/bold]")
    session_path = agent.save_session("demo_session")
    console.print(f"[green]✓ Session saved to: {session_path}[/green]")

    # Summary
    console.print("\n[bold green]Demo Complete![/bold green]")
    console.print("\n[cyan]What we demonstrated:[/cyan]")
    console.print("  ✓ Memory management (hierarchical layers)")
    console.print("  ✓ RAG retrieval (code indexing and search)")
    console.print("  ✓ Prompt engineering (task-specific templates)")
    console.print("  ✓ LLM integration (Ollama backend)")
    console.print("  ✓ Tool execution (file operations)")
    console.print("  ✓ Session persistence")

    console.print("\n[yellow]Try the interactive mode:[/yellow]")
    console.print("  python -m src.cli chat")


if __name__ == "__main__":
    main()
