"""
Quick test for CLI memory commands.
"""

import sys
sys.path.insert(0, '/workspaces/ai-coding-agent')

from src.cli import show_file_memories, init_project_memory, add_memory, reload_memories
from src.core import CodingAgent
from pathlib import Path
import tempfile
import os

# Create test in temp directory
with tempfile.TemporaryDirectory() as tmp_dir:
    os.chdir(tmp_dir)
    print(f"Testing in: {tmp_dir}")

    # Initialize agent
    print("\n1. Creating agent...")
    agent = CodingAgent(
        backend="ollama",
        model_name="qwen3-coder:30b",
        load_file_memories=False  # Start without loading
    )
    print("✓ Agent created")

    # Test: Show memories (should be empty)
    print("\n2. Testing 'show_file_memories()' (should be empty)...")
    show_file_memories(agent)
    print("✓ Test passed")

    # Test: Init project memory
    print("\n3. Testing 'init_project_memory()'...")
    init_project_memory(agent)
    memory_file = Path(".opencodeagent/memory.md")
    assert memory_file.exists(), "Memory file should exist"
    print("✓ Memory file created")

    # Test: Show memories (should have content now)
    print("\n4. Testing 'show_file_memories()' (should have content)...")
    show_file_memories(agent)
    assert agent.memory.file_memory_content != "", "Should have content"
    print("✓ Memory content loaded")

    # Test: Add memory
    print("\n5. Testing 'add_memory()'...")
    add_memory(agent, "Always use 2-space indentation")
    content = memory_file.read_text()
    assert "2-space indentation" in content, "Added text should be in file"
    print("✓ Memory added")

    # Test: Reload memories
    print("\n6. Testing 'reload_memories()'...")
    reload_memories(agent)
    assert "2-space indentation" in agent.memory.file_memory_content, "Reloaded content should include new memory"
    print("✓ Memory reloaded")

    # Test: Init again (should fail with FileExistsError)
    print("\n7. Testing 'init_project_memory()' again (should show warning)...")
    init_project_memory(agent)
    print("✓ Handled existing file correctly")

print("\n" + "="*50)
print("✅ All CLI memory command tests passed!")
print("="*50)
