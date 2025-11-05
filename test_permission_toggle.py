"""
Quick test for permission mode toggling.
"""

import sys
sys.path.insert(0, '/workspaces/ai-coding-agent')

from src.cli import toggle_permission_mode
from src.core import CodingAgent

# Create agent with default mode
agent = CodingAgent(
    backend="ollama",
    model_name="qwen3-coder:30b",
)

print("Testing Permission Mode Toggle")
print("=" * 50)

# Test cycling through modes
modes_tested = []

for i in range(4):
    current = agent.get_permission_mode()
    modes_tested.append(current)
    print(f"\n{i+1}. Current mode: {current}")

    # Simulate toggle
    toggle_permission_mode(agent)

    new_mode = agent.get_permission_mode()
    print(f"   After toggle: {new_mode}")

print("\n" + "=" * 50)
print("Mode cycle tested:")
print(" → ".join(modes_tested))

# Verify cycle is correct
expected_cycle = ["normal", "auto", "plan", "normal"]
if modes_tested == expected_cycle:
    print("\n✅ Toggle cycle works correctly!")
else:
    print(f"\n❌ Expected: {expected_cycle}")
    print(f"   Got: {modes_tested}")
