"""
CI-level guard: Tool._get_parameters() must match tool_schemas.py.

For every Tool subclass that sets _SCHEMA_NAME, this test verifies:
1. The schema name exists in _SCHEMA_REGISTRY.
2. get_schema() returns parameters identical to the ToolDefinition in tool_schemas.
3. Every required parameter name in the schema is a named argument in execute().

This prevents silent parameter-name divergence between what the LLM is told to send
and what execute() actually receives.
"""

import inspect
import pytest

from src.tools.tool_schemas import _SCHEMA_REGISTRY
from src.tools.base import Tool
from src.tools.search_tools import GrepTool, GlobTool
from src.tools.file_operations import (
    ReadFileTool, WriteFileTool, EditFileTool, AppendToFileTool, ListDirectoryTool,
)
from src.tools.clarify_tool import ClarifyTool
from src.tools.checkpoint_tool import CreateCheckpointTool
from src.tools.plan_mode_tools import EnterPlanModeTool, RequestPlanApprovalTool

# All Tool subclasses that delegate via _SCHEMA_NAME.
# Add new tools here as they are migrated to the _SCHEMA_NAME pattern.
# Note: RunCommandTool, CheckBackgroundTaskTool, WebFetchTool, WebSearchTool,
# DelegateToSubagentTool have constructor args and are covered by TestNoInlineSchemasDiverge.
SCHEMA_DELEGATING_TOOLS = [
    GrepTool,
    GlobTool,
    ReadFileTool,
    WriteFileTool,
    EditFileTool,
    AppendToFileTool,
    ListDirectoryTool,
    ClarifyTool,
    CreateCheckpointTool,
    EnterPlanModeTool,
    RequestPlanApprovalTool,
]


class TestSchemaDelegation:
    """Verify _SCHEMA_NAME tools produce schemas identical to tool_schemas.py."""

    @pytest.mark.parametrize("tool_cls", SCHEMA_DELEGATING_TOOLS)
    def test_schema_name_exists_in_registry(self, tool_cls):
        assert tool_cls._SCHEMA_NAME is not None, f"{tool_cls.__name__} has no _SCHEMA_NAME"
        assert tool_cls._SCHEMA_NAME in _SCHEMA_REGISTRY, (
            f"{tool_cls.__name__}._SCHEMA_NAME='{tool_cls._SCHEMA_NAME}' "
            f"not found in _SCHEMA_REGISTRY"
        )

    @pytest.mark.parametrize("tool_cls", SCHEMA_DELEGATING_TOOLS)
    def test_get_parameters_matches_registry(self, tool_cls):
        tool = tool_cls()
        schema = tool.get_schema()
        registry_params = _SCHEMA_REGISTRY[tool_cls._SCHEMA_NAME].parameters
        assert schema["parameters"] == registry_params, (
            f"{tool_cls.__name__}.get_schema()['parameters'] does not match "
            f"_SCHEMA_REGISTRY['{tool_cls._SCHEMA_NAME}'].parameters"
        )

    # Tools whose execute() intentionally uses **kwargs instead of named params.
    # ClarifyTool is intercepted before execute() is called in TUI mode; it never
    # receives named params directly.
    _KWARGS_ONLY_TOOLS = {ClarifyTool}

    @pytest.mark.parametrize("tool_cls", SCHEMA_DELEGATING_TOOLS)
    def test_required_params_in_execute_signature(self, tool_cls):
        """Every 'required' param in the schema must appear in execute()'s signature."""
        if tool_cls in self._KWARGS_ONLY_TOOLS:
            pytest.skip(f"{tool_cls.__name__} uses **kwargs by design (intercepted tool)")
        tool = tool_cls()
        params = tool.get_schema()["parameters"]
        required = params.get("required", [])
        sig = inspect.signature(tool.execute)
        execute_params = set(sig.parameters.keys()) - {"self", "kwargs"}
        for req in required:
            assert req in execute_params, (
                f"{tool_cls.__name__}.execute() is missing required schema param '{req}'. "
                f"execute() params: {sorted(execute_params)}"
            )


class TestNoInlineSchemasDiverge:
    """
    Detect Tool subclasses in MIGRATED modules that still have an inline
    _get_parameters() AND a matching entry in _SCHEMA_REGISTRY.

    SCOPE: Only modules listed in _get_migrated_modules() are checked.
    Add a module here once all its tools have been migrated to _SCHEMA_NAME.
    Non-migrated modules are tracked in task bd-146dda6b.
    """

    def _get_migrated_modules(self):
        """Return modules whose tools have been fully migrated to _SCHEMA_NAME.

        Note: src.tools.delegation is intentionally excluded -- DelegateToSubagentTool
        keeps a _get_parameters() override to document the intentional split between
        its dynamic description (generated at __init__ time) and its canonical
        parameters (delegated from _SCHEMA_REGISTRY). This is a documented exception,
        not a violation.
        """
        import src.tools.search_tools
        import src.tools.file_operations
        import src.tools.clarify_tool
        import src.tools.checkpoint_tool
        import src.tools.plan_mode_tools
        import src.tools.web_tools
        import src.tools.background_tools
        return [
            src.tools.search_tools,
            src.tools.file_operations,
            src.tools.clarify_tool,
            src.tools.checkpoint_tool,
            src.tools.plan_mode_tools,
            src.tools.web_tools,
            src.tools.background_tools,
        ]

    def _get_tool_subclasses(self):
        subclasses = []
        for module in self._get_migrated_modules():
            for _, obj in inspect.getmembers(module, inspect.isclass):
                if issubclass(obj, Tool) and obj is not Tool:
                    subclasses.append(obj)
        return subclasses

    def test_no_inline_schema_when_registry_entry_exists(self):
        """All tools in migrated modules must use _SCHEMA_NAME, not inline _get_parameters()."""
        violations = []
        for tool_cls in self._get_tool_subclasses():
            if inspect.isabstract(tool_cls):
                continue
            has_override = "_get_parameters" in tool_cls.__dict__
            if not has_override:
                continue
            try:
                tool = tool_cls()
            except Exception:
                continue
            if tool.name in _SCHEMA_REGISTRY:
                violations.append(
                    f"{tool_cls.__name__} (tool='{tool.name}') has inline _get_parameters() "
                    f"but '{tool.name}' exists in _SCHEMA_REGISTRY -- use _SCHEMA_NAME instead"
                )
        assert not violations, "Tools with inline schemas that should delegate:\n" + "\n".join(violations)


class TestRegistryIntegrity:
    """Guard against _SCHEMA_REGISTRY corruption."""

    def test_no_duplicate_tool_names_in_all_tools(self):
        """ALL_TOOLS must not contain duplicate tool names -- dict comprehension would silently drop them."""
        from src.tools.tool_schemas import ALL_TOOLS
        names = [t.name for t in ALL_TOOLS]
        duplicates = [n for n in names if names.count(n) > 1]
        assert not duplicates, f"Duplicate tool names in ALL_TOOLS: {sorted(set(duplicates))}"

    def test_registry_covers_all_tools(self):
        """_SCHEMA_REGISTRY must have exactly one entry per tool in ALL_TOOLS."""
        from src.tools.tool_schemas import ALL_TOOLS
        assert len(_SCHEMA_REGISTRY) == len(ALL_TOOLS), (
            f"_SCHEMA_REGISTRY has {len(_SCHEMA_REGISTRY)} entries but ALL_TOOLS has {len(ALL_TOOLS)}"
        )


class TestConstructorArgTools:
    """
    Schema-equality tests for tools that require constructor args and therefore
    cannot be included in the SCHEMA_DELEGATING_TOOLS parametrize list.

    Each test instantiates the tool with a minimal stub and verifies:
    1. _SCHEMA_NAME is set correctly
    2. get_schema()['parameters'] matches _SCHEMA_REGISTRY exactly
    """

    def _assert_schema_matches_registry(self, tool):
        name = tool._SCHEMA_NAME
        assert name is not None, f"{type(tool).__name__} has no _SCHEMA_NAME"
        assert name in _SCHEMA_REGISTRY, f"'{name}' not in _SCHEMA_REGISTRY"
        assert tool.get_schema()["parameters"] == _SCHEMA_REGISTRY[name].parameters, (
            f"{type(tool).__name__}.get_schema()['parameters'] does not match "
            f"_SCHEMA_REGISTRY['{name}'].parameters"
        )

    def test_run_command_tool(self):
        from src.tools.file_operations import RunCommandTool
        tool = RunCommandTool(registry=None)
        self._assert_schema_matches_registry(tool)

    def test_check_background_task_tool(self):
        from src.tools.background_tools import CheckBackgroundTaskTool
        tool = CheckBackgroundTaskTool(registry=None)
        self._assert_schema_matches_registry(tool)

    def test_web_fetch_tool(self):
        from src.tools.web_tools import WebFetchTool
        tool = WebFetchTool()
        self._assert_schema_matches_registry(tool)

    def test_web_search_tool(self):
        from src.tools.web_tools import WebSearchTool
        tool = WebSearchTool(provider=None)
        self._assert_schema_matches_registry(tool)

    def test_delegate_to_subagent_tool(self):
        """DelegateToSubagentTool keeps a _get_parameters() override that still delegates
        to the registry -- verify parameters match even though description is dynamic."""
        from unittest.mock import MagicMock
        from src.tools.delegation import DelegateToSubagentTool
        tool = DelegateToSubagentTool(subagent_manager=MagicMock())
        self._assert_schema_matches_registry(tool)
