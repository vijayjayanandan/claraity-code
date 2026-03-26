"""Tests for built-in subagent definitions: discovery, tool allowlists, and enforcement."""

import os
import re
import tempfile

import pytest
from unittest.mock import Mock, patch

from src.subagents.config import SubAgentConfig, SubAgentConfigLoader
from src.subagents.subagent import SubAgent
from src.prompts.subagents import EXPLORE_TOOLS, PLANNER_TOOLS, SUBAGENT_BASE_PROMPT


# =============================================================================
# FIXTURES
# =============================================================================

EXPECTED_BUILTINS = {
    "code-reviewer",
    "test-writer",
    "doc-writer",
    "code-writer",
    "explore",
    "planner",
    "general-purpose",
}

# Tools that should NEVER appear in read-only subagents
WRITE_TOOLS = {"write_file", "edit_file", "append_to_file"}
EXECUTE_TOOLS = {"run_command", "run_tests"}
GIT_WRITE_TOOLS = {"git_commit"}
DANGEROUS_TOOLS = WRITE_TOOLS | EXECUTE_TOOLS | GIT_WRITE_TOOLS

KEBAB_CASE_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _make_mock_tool(name):
    """Create a mock tool with .name attribute for _resolve_tools compatibility."""
    tool = Mock()
    tool.name = name
    return tool


@pytest.fixture
def all_configs():
    """Discover all built-in subagent configs."""
    loader = SubAgentConfigLoader()
    return loader.discover_all()


@pytest.fixture
def mock_tool_definitions():
    """Create mock tool definitions matching a realistic tool set."""
    tool_names = [
        # File tools
        "read_file", "write_file", "edit_file", "append_to_file", "list_directory",
        # Code tools
        "search_code", "analyze_code", "grep", "glob",
        "get_file_outline", "get_symbol_context",
        # Git tools
        "git_status", "git_diff", "git_commit",
        # Execution tools
        "run_command", "run_tests", "detect_test_framework",
        # Web tools
        "web_search", "web_fetch",
        # Task tools
        "task_create", "task_update", "task_list", "task_get",
        # Other
        "create_checkpoint", "clarify",
        # Excluded tools (should always be filtered out)
        "delegate_to_subagent", "enter_plan_mode", "request_plan_approval",
    ]
    return [_make_mock_tool(name) for name in tool_names]


@pytest.fixture
def mock_main_agent():
    """Minimal mock main agent for SubAgent instantiation."""
    from src.llm import LLMBackendType

    agent = Mock()
    agent.working_directory = None
    agent.llm = Mock()
    agent.llm.config = Mock()
    agent.llm.config.backend_type = LLMBackendType.OPENAI
    agent.llm.config.model_name = "test-model"
    agent.llm.config.base_url = "http://localhost:8000/v1"
    agent.llm.config.context_window = 128000
    agent.llm.config.temperature = 0.2
    agent.llm.config.max_tokens = 16384
    agent.llm.config.top_p = 0.95
    agent.llm.api_key = "test-key"
    agent.tool_executor = Mock()
    agent.tool_executor.tools = {}
    agent.hook_manager = None
    return agent


# =============================================================================
# DISCOVERY TESTS
# =============================================================================

class TestBuiltinSubagentDiscovery:
    """Verify all built-in subagents are discovered correctly."""

    def test_all_builtins_discovered(self, all_configs):
        """All 7 built-in subagents should be loaded."""
        assert set(all_configs.keys()) >= EXPECTED_BUILTINS

    def test_builtin_count(self, all_configs):
        """Should have at least 7 subagents total (built-in or project overrides).

        Project .clarity/agents/ files take priority over built-ins (by design),
        so the source may be 'project' for forked built-ins.
        """
        # Count all configs that correspond to expected built-in names
        covered = {k for k in all_configs if k in EXPECTED_BUILTINS}
        assert len(covered) >= 7

    def test_builtin_metadata_source(self, all_configs):
        """All built-in names should be present; source is 'builtin' or 'project' (fork)."""
        for name in EXPECTED_BUILTINS:
            config = all_configs[name]
            source = config.metadata.get("source")
            assert source in ("builtin", "project"), (
                f"{name} has unexpected source '{source}' (expected 'builtin' or 'project')"
            )

    def test_builtin_names_are_kebab_case(self, all_configs):
        """All built-in names must pass the kebab-case regex."""
        for name in EXPECTED_BUILTINS:
            assert KEBAB_CASE_RE.match(name), (
                f"'{name}' does not match kebab-case pattern"
            )

    def test_builtin_descriptions_not_empty(self, all_configs):
        """All built-ins must have non-empty descriptions."""
        for name in EXPECTED_BUILTINS:
            config = all_configs[name]
            assert config.description and len(config.description.strip()) > 0, (
                f"{name} has empty description"
            )

    def test_builtin_prompts_not_empty(self, all_configs):
        """All built-ins must have non-empty system prompts."""
        for name in EXPECTED_BUILTINS:
            config = all_configs[name]
            assert config.system_prompt and len(config.system_prompt.strip()) > 10, (
                f"{name} has empty or trivial system prompt"
            )


# =============================================================================
# EXPLORE SUBAGENT TESTS
# =============================================================================

class TestExploreSubagent:
    """Verify explore subagent configuration."""

    def test_explore_has_tool_allowlist(self, all_configs):
        """explore must have tools != None (enforced read-only)."""
        config = all_configs["explore"]
        assert config.tools is not None
        assert len(config.tools) > 0

    def test_explore_tools_are_read_only(self, all_configs):
        """explore tools must not include any write/execute tools."""
        config = all_configs["explore"]
        explore_set = set(config.tools)
        overlap = explore_set & DANGEROUS_TOOLS
        assert len(overlap) == 0, (
            f"explore has dangerous tools: {overlap}"
        )

    def test_explore_includes_search_tools(self, all_configs):
        """explore should include core search tools."""
        config = all_configs["explore"]
        explore_set = set(config.tools)
        assert "grep" in explore_set
        assert "glob" in explore_set
        assert "search_code" in explore_set
        assert "read_file" in explore_set

    def test_explore_excludes_web_tools(self, all_configs):
        """explore should not include web tools (planner has those)."""
        config = all_configs["explore"]
        explore_set = set(config.tools)
        assert "web_search" not in explore_set
        assert "web_fetch" not in explore_set

    def test_explore_prompt_mentions_read_only(self, all_configs):
        """Prompt should emphasize read-only nature."""
        config = all_configs["explore"]
        prompt_lower = config.system_prompt.lower()
        assert "read-only" in prompt_lower or "read only" in prompt_lower


# =============================================================================
# PLANNER SUBAGENT TESTS
# =============================================================================

class TestPlannerSubagent:
    """Verify planner subagent configuration."""

    def test_planner_has_tool_allowlist(self, all_configs):
        """planner must have tools != None."""
        config = all_configs["planner"]
        assert config.tools is not None
        assert len(config.tools) > 0

    def test_planner_tools_are_read_only_plus_web(self, all_configs):
        """planner tools must not include write/execute tools but should have web tools."""
        config = all_configs["planner"]
        planner_set = set(config.tools)
        overlap = planner_set & DANGEROUS_TOOLS
        assert len(overlap) == 0, (
            f"planner has dangerous tools: {overlap}"
        )
        assert "web_search" in planner_set
        assert "web_fetch" in planner_set

    def test_planner_is_superset_of_explore(self, all_configs):
        """All explore tools should also be in planner tools."""
        explore_set = set(all_configs["explore"].tools)
        planner_set = set(all_configs["planner"].tools)
        missing = explore_set - planner_set
        assert len(missing) == 0, (
            f"Planner is missing explore tools: {missing}"
        )

    def test_planner_prompt_mentions_no_code_writing(self, all_configs):
        """Prompt should emphasize that planner does not write code."""
        config = all_configs["planner"]
        prompt_lower = config.system_prompt.lower()
        assert "must not write" in prompt_lower or "read-only" in prompt_lower


# =============================================================================
# GENERAL PURPOSE SUBAGENT TESTS
# =============================================================================

class TestGeneralPurposeSubagent:
    """Verify general-purpose subagent configuration."""

    def test_general_purpose_inherits_all_tools(self, all_configs):
        """general-purpose must have tools=None (inherit all)."""
        config = all_configs["general-purpose"]
        assert config.tools is None

    def test_general_purpose_name_valid(self, all_configs):
        """'general-purpose' must pass kebab-case validation."""
        assert KEBAB_CASE_RE.match("general-purpose")
        assert "general-purpose" in all_configs


# =============================================================================
# CODE WRITER SUBAGENT TESTS
# =============================================================================

class TestCodeWriterSubagent:
    """Verify code-writer subagent is now registered."""

    def test_code_writer_registered(self, all_configs):
        """code-writer should be present in discovered configs."""
        assert "code-writer" in all_configs

    def test_code_writer_inherits_all_tools(self, all_configs):
        """code-writer needs full tool access for implementation."""
        config = all_configs["code-writer"]
        assert config.tools is None

    def test_code_writer_is_builtin(self, all_configs):
        """code-writer should have builtin metadata."""
        config = all_configs["code-writer"]
        assert config.metadata.get("source") == "builtin"


# =============================================================================
# TOOL ALLOWLIST CONSTANTS TESTS
# =============================================================================

class TestToolAllowlistConstants:
    """Verify the exported tool allowlist constants."""

    def test_explore_tools_is_list(self):
        """EXPLORE_TOOLS should be a list."""
        assert isinstance(EXPLORE_TOOLS, list)
        assert len(EXPLORE_TOOLS) > 0

    def test_planner_tools_is_list(self):
        """PLANNER_TOOLS should be a list."""
        assert isinstance(PLANNER_TOOLS, list)
        assert len(PLANNER_TOOLS) > 0

    def test_planner_tools_superset_of_explore(self):
        """PLANNER_TOOLS should contain all EXPLORE_TOOLS."""
        assert set(EXPLORE_TOOLS).issubset(set(PLANNER_TOOLS))

    def test_planner_tools_has_web(self):
        """PLANNER_TOOLS should include web_search and web_fetch."""
        assert "web_search" in PLANNER_TOOLS
        assert "web_fetch" in PLANNER_TOOLS

    def test_explore_tools_no_write_tools(self):
        """EXPLORE_TOOLS should not contain any write tools."""
        overlap = set(EXPLORE_TOOLS) & DANGEROUS_TOOLS
        assert len(overlap) == 0, f"EXPLORE_TOOLS has dangerous tools: {overlap}"


# =============================================================================
# TOOL ALLOWLIST ENFORCEMENT TESTS
# =============================================================================

class TestToolAllowlistEnforcement:
    """Verify tool filtering works end-to-end for new subagents."""

    def test_explore_filters_to_read_only_tools(
        self, all_configs, mock_main_agent, mock_tool_definitions
    ):
        """explore SubAgent should only resolve read-only tools."""
        config = all_configs["explore"]
        subagent = SubAgent(config, mock_main_agent)

        resolved = subagent._resolve_tools(mock_tool_definitions)
        resolved_names = {t.name for t in resolved}

        # Should only contain EXPLORE_TOOLS
        assert resolved_names == set(EXPLORE_TOOLS)

    def test_explore_blocks_write_file(
        self, all_configs, mock_main_agent, mock_tool_definitions
    ):
        """write_file should not be in explore's resolved tools."""
        config = all_configs["explore"]
        subagent = SubAgent(config, mock_main_agent)

        resolved = subagent._resolve_tools(mock_tool_definitions)
        resolved_names = {t.name for t in resolved}

        assert "write_file" not in resolved_names
        assert "edit_file" not in resolved_names
        assert "run_command" not in resolved_names

    def test_planner_allows_web_search(
        self, all_configs, mock_main_agent, mock_tool_definitions
    ):
        """web_search should be in planner's resolved tools."""
        config = all_configs["planner"]
        subagent = SubAgent(config, mock_main_agent)

        resolved = subagent._resolve_tools(mock_tool_definitions)
        resolved_names = {t.name for t in resolved}

        assert "web_search" in resolved_names
        assert "web_fetch" in resolved_names
        assert "read_file" in resolved_names

    def test_planner_blocks_write_tools(
        self, all_configs, mock_main_agent, mock_tool_definitions
    ):
        """planner should not have any write or execute tools."""
        config = all_configs["planner"]
        subagent = SubAgent(config, mock_main_agent)

        resolved = subagent._resolve_tools(mock_tool_definitions)
        resolved_names = {t.name for t in resolved}

        overlap = resolved_names & DANGEROUS_TOOLS
        assert len(overlap) == 0, f"Planner resolved dangerous tools: {overlap}"

    def test_general_purpose_allows_all_minus_exclusions(
        self, all_configs, mock_main_agent, mock_tool_definitions
    ):
        """general-purpose should have all tools except subagent exclusions."""
        config = all_configs["general-purpose"]
        subagent = SubAgent(config, mock_main_agent)

        resolved = subagent._resolve_tools(mock_tool_definitions)
        resolved_names = {t.name for t in resolved}

        # Should have write, execute, and everything
        assert "write_file" in resolved_names
        assert "run_command" in resolved_names
        assert "web_search" in resolved_names

        # But not the always-excluded tools
        assert "delegate_to_subagent" not in resolved_names
        assert "enter_plan_mode" not in resolved_names
        assert "request_plan_approval" not in resolved_names


# =============================================================================
# SUBAGENT BASE PROMPT TESTS
# =============================================================================

class TestSubagentBasePrompt:
    """Verify the shared base prompt constant and its injection."""

    def test_base_prompt_exists_and_nonempty(self):
        """SUBAGENT_BASE_PROMPT should be a non-empty string."""
        assert isinstance(SUBAGENT_BASE_PROMPT, str)
        assert len(SUBAGENT_BASE_PROMPT.strip()) > 100

    def test_base_prompt_has_identity(self):
        """Base prompt should contain identity section."""
        assert "ClarAIty" in SUBAGENT_BASE_PROMPT
        assert "subagent" in SUBAGENT_BASE_PROMPT.lower()

    def test_base_prompt_has_no_emojis_rule(self):
        """Base prompt should warn about emojis and cp1252."""
        lower = SUBAGENT_BASE_PROMPT.lower()
        assert "emoji" in lower
        assert "cp1252" in lower or "windows" in lower

    def test_base_prompt_has_verification_rule(self):
        """Base prompt should require read-before-claim."""
        lower = SUBAGENT_BASE_PROMPT.lower()
        assert "read before" in lower or "read before you claim" in lower

    def test_base_prompt_has_code_reference_format(self):
        """Base prompt should specify file_path:line_number format."""
        assert "file_path:line_number" in SUBAGENT_BASE_PROMPT

    def test_base_prompt_no_project_specific_rules(self):
        """Base prompt should NOT contain project-specific rules like get_logger."""
        assert "get_logger" not in SUBAGENT_BASE_PROMPT
        assert "StoreAdapter" not in SUBAGENT_BASE_PROMPT

    def test_base_prompt_injected_into_context(
        self, all_configs, mock_main_agent
    ):
        """_build_context should prepend SUBAGENT_BASE_PROMPT to system message."""
        config = all_configs["explore"]
        subagent = SubAgent(config, mock_main_agent)

        messages, _ = subagent._build_context("Test task")
        system_content = messages[0]["content"]

        # Base prompt should appear before the role-specific prompt
        base_pos = system_content.find("# Identity")
        role_pos = system_content.find(config.system_prompt[:50])
        assert base_pos >= 0, "Base prompt not found in system message"
        assert role_pos > base_pos, "Base prompt should appear before role prompt"

    def test_base_prompt_injected_for_all_subagents(
        self, all_configs, mock_main_agent
    ):
        """Every built-in subagent should get the base prompt."""
        for name in EXPECTED_BUILTINS:
            config = all_configs[name]
            subagent = SubAgent(config, mock_main_agent)
            messages, _ = subagent._build_context(f"Test task for {name}")
            system_content = messages[0]["content"]

            assert "# Identity" in system_content, (
                f"{name} missing base prompt identity section"
            )
            assert "# Universal Rules" in system_content, (
                f"{name} missing base prompt universal rules"
            )


# =============================================================================
# CLARAITY.MD INJECTION TESTS
# =============================================================================

class TestClaraityMdInjection:
    """Verify CLARAITY.md project instructions are loaded into subagent context."""

    def test_claraity_md_loaded_when_present(self, all_configs):
        """Subagent should include CLARAITY.md content when file exists."""
        from src.llm import LLMBackendType

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a CLARAITY.md in the temp directory
            claraity_path = os.path.join(tmpdir, "CLARAITY.md")
            with open(claraity_path, "w", encoding="utf-8") as f:
                f.write("# Project Rules\n\nUse get_logger() not logging.getLogger().\n")

            # Create agent with working_directory pointing to tmpdir
            agent = Mock()
            agent.working_directory = tmpdir
            agent.llm = Mock()
            agent.llm.config = Mock()
            agent.llm.config.backend_type = LLMBackendType.OPENAI
            agent.llm.config.model_name = "test-model"
            agent.llm.config.base_url = "http://localhost:8000/v1"
            agent.llm.config.context_window = 128000
            agent.llm.config.temperature = 0.2
            agent.llm.config.max_tokens = 16384
            agent.llm.config.top_p = 0.95
            agent.llm.api_key = "test-key"
            agent.tool_executor = Mock()
            agent.tool_executor.tools = {}
            agent.hook_manager = None

            config = all_configs["explore"]
            subagent = SubAgent(config, agent)

            messages, _ = subagent._build_context("Test task")
            system_content = messages[0]["content"]

            assert "Project Instructions (from CLARAITY.md)" in system_content
            assert "get_logger()" in system_content

    def test_no_claraity_md_graceful(self, all_configs, mock_main_agent):
        """Subagent should work fine when CLARAITY.md does not exist."""
        # mock_main_agent has working_directory=None, so no file lookup
        config = all_configs["explore"]
        subagent = SubAgent(config, mock_main_agent)

        messages, _ = subagent._build_context("Test task")
        system_content = messages[0]["content"]

        # Should still have base prompt and role prompt, just no project instructions
        assert "# Identity" in system_content
        assert "Project Instructions (from CLARAITY.md)" not in system_content

    def test_claraity_md_case_insensitive(self, all_configs):
        """Should find claraity.md with lowercase naming."""
        from src.llm import LLMBackendType

        with tempfile.TemporaryDirectory() as tmpdir:
            # Use lowercase filename
            claraity_path = os.path.join(tmpdir, "claraity.md")
            with open(claraity_path, "w", encoding="utf-8") as f:
                f.write("# Lowercase Project Rules\n\nTest content.\n")

            agent = Mock()
            agent.working_directory = tmpdir
            agent.llm = Mock()
            agent.llm.config = Mock()
            agent.llm.config.backend_type = LLMBackendType.OPENAI
            agent.llm.config.model_name = "test-model"
            agent.llm.config.base_url = "http://localhost:8000/v1"
            agent.llm.config.context_window = 128000
            agent.llm.config.temperature = 0.2
            agent.llm.config.max_tokens = 16384
            agent.llm.config.top_p = 0.95
            agent.llm.api_key = "test-key"
            agent.tool_executor = Mock()
            agent.tool_executor.tools = {}
            agent.hook_manager = None

            config = all_configs["explore"]
            subagent = SubAgent(config, agent)

            messages, _ = subagent._build_context("Test task")
            system_content = messages[0]["content"]

            assert "Lowercase Project Rules" in system_content

    def test_empty_claraity_md_ignored(self, all_configs):
        """Empty CLARAITY.md should not inject a section."""
        from src.llm import LLMBackendType

        with tempfile.TemporaryDirectory() as tmpdir:
            claraity_path = os.path.join(tmpdir, "CLARAITY.md")
            with open(claraity_path, "w", encoding="utf-8") as f:
                f.write("   \n\n  ")  # whitespace only

            agent = Mock()
            agent.working_directory = tmpdir
            agent.llm = Mock()
            agent.llm.config = Mock()
            agent.llm.config.backend_type = LLMBackendType.OPENAI
            agent.llm.config.model_name = "test-model"
            agent.llm.config.base_url = "http://localhost:8000/v1"
            agent.llm.config.context_window = 128000
            agent.llm.config.temperature = 0.2
            agent.llm.config.max_tokens = 16384
            agent.llm.config.top_p = 0.95
            agent.llm.api_key = "test-key"
            agent.tool_executor = Mock()
            agent.tool_executor.tools = {}
            agent.hook_manager = None

            config = all_configs["explore"]
            subagent = SubAgent(config, agent)

            messages, _ = subagent._build_context("Test task")
            system_content = messages[0]["content"]

            assert "Project Instructions (from CLARAITY.md)" not in system_content
