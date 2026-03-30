"""Pytest conftest for MCP integration tests.

Pre-loads the module tree to resolve a circular import that only manifests
when src.tools is the *first* package to be imported (which happens when
test_mcp_bridge.py imports bridge.py -> src.tools.base).

The circular chain:
  src.tools.__init__ -> ... -> src.claraity -> src.llm (partial)
      -> src.session -> src.core.__init__ -> agent.py
      -> from src.llm import LLMBackend  (fails: src.llm half-init'd)

Loading src.core first initializes the tree via a chain that succeeds
(its back-edge only needs src.core.events, a standalone submodule).
After that, all modules are in sys.modules and the problematic chain
never re-executes.
"""

import src.core  # noqa: F401
