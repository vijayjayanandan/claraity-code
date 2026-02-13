# Prime the src.core import chain first to avoid circular import errors.
# See memory/circular-imports.md for full explanation.
#
# Chain: src.subagents.__init__ -> subagent.py -> src.core.tool_status
#        -> src.core.__init__ -> agent.py -> src.subagents (partial) -> FAIL
#
# By loading src.core first, all modules are in sys.modules before
# subagent tests try to import from src.subagents.
import src.core  # noqa: F401
