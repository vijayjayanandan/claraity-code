#!/usr/bin/env python3
"""Manual test script for hooks CLI commands."""

from pathlib import Path
from unittest.mock import Mock
from src.cli import show_hooks_status, reload_hooks, list_hook_examples

# Create mock agent without hooks
print("=" * 60)
print("TEST 1: Show hooks status (no hooks loaded)")
print("=" * 60)

# Create a minimal mock agent
agent = Mock()
agent.hook_manager = None
agent.tool_executor = Mock()

show_hooks_status(agent)

print("\n" + "=" * 60)
print("TEST 2: List hook examples")
print("=" * 60)

list_hook_examples()

print("\n" + "=" * 60)
print("TEST 3: Copy example and reload hooks")
print("=" * 60)

# Copy validation example to .claude/hooks.py
import shutil

hooks_path = Path(".claude/hooks.py")
example_path = Path(".claude/examples/validation.py")

if example_path.exists():
    print(f"Copying {example_path} to {hooks_path}")
    shutil.copy(example_path, hooks_path)
    print("✓ Copied example file")

    # Reload hooks (this will actually create a real HookManager)
    reload_hooks(agent)

    print("\n" + "=" * 60)
    print("TEST 4: Show hooks status (hooks loaded)")
    print("=" * 60)

    show_hooks_status(agent)
else:
    print(f"❌ Example not found: {example_path}")
    print("Skipping reload and status tests")

print("\n" + "=" * 60)
print("TEST 5: Clean up")
print("=" * 60)

# Remove test hooks file
if hooks_path.exists():
    hooks_path.unlink()
    print("✓ Removed test hooks file")

print("\n✅ All CLI hooks tests completed!")
