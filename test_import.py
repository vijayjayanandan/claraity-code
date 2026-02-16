#!/usr/bin/env python
"""Test circular import issue"""
import sys

print("Testing import of SubAgentManager...")
try:
    from src.subagents import SubAgentManager
    print("SUCCESS: SubAgentManager imported")
except ImportError as e:
    print(f"FAILED: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
