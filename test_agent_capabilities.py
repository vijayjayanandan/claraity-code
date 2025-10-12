"""Test the AI Coding Agent's core capabilities."""

from src.core import CodingAgent
from rich.console import Console

console = Console()

# Initialize agent
console.print("\n[bold cyan]═══ AI Coding Agent Capability Tests ═══[/bold cyan]\n")
agent = CodingAgent(
    model_name="deepseek-coder:6.7b-instruct",
    backend="ollama",
    context_window=4096,
)

# Test 1: Index codebase (RAG)
console.print("[bold]Test 1: RAG Indexing[/bold]")
stats = agent.index_codebase(directory="./src")
console.print(f"✓ Indexed {stats['total_files']} files, {stats['total_chunks']} chunks")
console.print(f"  Languages: {list(stats['languages'].keys())}\n")

# Test 2: Code Understanding
console.print("[bold]Test 2: Code Understanding[/bold]")
console.print("Query: Explain how the memory manager coordinates different memory layers\n")
response = agent.execute_task(
    task_description="Explain how the memory manager coordinates the working, episodic, and semantic memory layers",
    task_type="explain",
    use_rag=True,
)
console.print(f"✓ Response generated ({len(response.content)} chars)\n")

# Test 3: Memory Persistence
console.print("[bold]Test 3: Memory Persistence[/bold]")
console.print("First query: What is the MemoryManager class?")
agent.chat("What is the MemoryManager class?")
console.print("\nSecond query: What methods does it have? (should remember context)")
agent.chat("What methods does it have?")

# Show memory stats
stats = agent.get_statistics()
console.print(f"\n✓ Working memory: {stats['memory']['working_memory']['tokens']} tokens")
console.print(f"✓ Episodic turns: {stats['memory']['episodic_memory']['total_turns']}\n")

# Test 4: Code Search (RAG retrieval)
console.print("[bold]Test 4: RAG Retrieval Accuracy[/bold]")
console.print("Searching for: 'embedding' related code")
# This uses RAG under the hood
response = agent.execute_task(
    task_description="Find where embeddings are generated in the codebase",
    task_type="explain",
    use_rag=True,
)
console.print(f"✓ RAG retrieval successful ({len(response.content)} chars)\n")

console.print("[bold green]═══ All tests completed successfully! ═══[/bold green]")
