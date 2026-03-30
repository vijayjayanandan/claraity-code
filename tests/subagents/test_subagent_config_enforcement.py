"""Tests for SubAgent config enforcement: tool filtering, LLM override, backend_type."""

import pytest
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

from src.subagents.subagent import SubAgent, SubAgentResult
from src.subagents.config import SubAgentConfig, SubAgentLLMConfig
from src.llm import LLMBackendType, LLMResponse


# =============================================================================
# FIXTURES
# =============================================================================

def _make_mock_tool(name):
    """Create a mock tool with get_schema() for SubAgent compatibility.

    SubAgent._execute_with_tools builds ToolDefinitions from tool_executor.tools,
    so each mock tool must return a valid schema dict from get_schema().
    """
    tool = Mock()
    tool.get_schema.return_value = {
        "name": name,
        "description": f"Mock {name} tool",
        "parameters": {"type": "object", "properties": {}, "required": []},
    }
    return tool


@pytest.fixture
def mock_main_agent():
    """Create a mock main agent with LLM and tool executor."""
    agent = Mock()
    agent.working_directory = Path("/test/project")

    # Mock LLM backend (OpenAI-compatible)
    agent.llm = Mock()
    agent.llm.config = Mock()
    agent.llm.config.backend_type = LLMBackendType.OPENAI
    agent.llm.config.model_name = "main-model"
    agent.llm.config.base_url = "http://localhost:8000/v1"
    agent.llm.config.context_window = 128000
    agent.llm.config.temperature = 0.2
    agent.llm.config.max_tokens = 16384
    agent.llm.config.top_p = 0.95
    agent.llm.api_key = "test-api-key-123"

    # Mock tool executor with several tools (each has get_schema())
    agent.tool_executor = Mock()
    agent.tool_executor.tools = {
        "read_file": _make_mock_tool("read_file"),
        "write_file": _make_mock_tool("write_file"),
        "edit_file": _make_mock_tool("edit_file"),
        "search_code": _make_mock_tool("search_code"),
        "run_command": _make_mock_tool("run_command"),
        "glob_files": _make_mock_tool("glob_files"),
    }

    return agent


@pytest.fixture
def mock_tool_definitions():
    """Create mock ToolDefinition objects matching the tool executor."""
    tools = []
    for name in ["read_file", "write_file", "edit_file", "search_code",
                  "run_command", "glob_files", "delegate_to_subagent",
                  "enter_plan_mode", "request_plan_approval"]:
        tool = Mock()
        tool.name = name
        tools.append(tool)
    return tools


def make_config(name="test-agent", tools=None, llm=None):
    """Helper to create SubAgentConfig with defaults."""
    return SubAgentConfig(
        name=name,
        description=f"Test subagent: {name}",
        system_prompt="You are a test subagent.",
        tools=tools,
        llm=llm,
    )


def make_llm_config(**kwargs):
    """Helper to create SubAgentLLMConfig with only the specified overrides."""
    return SubAgentLLMConfig(**kwargs)


# =============================================================================
# TOOL FILTERING TESTS
# =============================================================================

class TestToolFiltering:
    """Test that config.tools is honored during execution."""

    def test_tools_none_inherits_all(self, mock_main_agent, mock_tool_definitions):
        """config.tools=None should give access to all tools minus exclusions."""
        config = make_config(tools=None)
        subagent = SubAgent(config, mock_main_agent)

        resolved = subagent._resolve_tools(mock_tool_definitions)
        resolved_names = {t.name for t in resolved}

        # Should have all tools except the excluded ones
        assert "read_file" in resolved_names
        assert "write_file" in resolved_names
        assert "edit_file" in resolved_names
        assert "search_code" in resolved_names
        assert "run_command" in resolved_names
        assert "glob_files" in resolved_names

        # Excluded tools should never be present
        assert "delegate_to_subagent" not in resolved_names
        assert "enter_plan_mode" not in resolved_names
        assert "request_plan_approval" not in resolved_names

    def test_tools_specific_list(self, mock_main_agent, mock_tool_definitions):
        """config.tools with specific names should filter to only those."""
        config = make_config(tools=["read_file", "search_code"])
        subagent = SubAgent(config, mock_main_agent)

        resolved = subagent._resolve_tools(mock_tool_definitions)
        resolved_names = {t.name for t in resolved}

        assert resolved_names == {"read_file", "search_code"}

    def test_tools_empty_list(self, mock_main_agent, mock_tool_definitions):
        """config.tools=[] should result in no tools available."""
        config = make_config(tools=[])
        subagent = SubAgent(config, mock_main_agent)

        resolved = subagent._resolve_tools(mock_tool_definitions)
        assert len(resolved) == 0

    def test_excluded_tools_cannot_be_allowed(self, mock_main_agent, mock_tool_definitions):
        """Even if config.tools includes excluded tools, they should be filtered out."""
        config = make_config(tools=["read_file", "delegate_to_subagent"])
        subagent = SubAgent(config, mock_main_agent)

        resolved = subagent._resolve_tools(mock_tool_definitions)
        resolved_names = {t.name for t in resolved}

        # delegate_to_subagent is excluded first, then allowlist is applied
        assert "read_file" in resolved_names
        assert "delegate_to_subagent" not in resolved_names

    def test_unknown_tool_in_config_ignored(self, mock_main_agent, mock_tool_definitions):
        """config.tools with unknown names should not crash, just result in fewer tools."""
        config = make_config(tools=["read_file", "nonexistent_tool"])
        subagent = SubAgent(config, mock_main_agent)

        resolved = subagent._resolve_tools(mock_tool_definitions)
        resolved_names = {t.name for t in resolved}

        # Only read_file matches, nonexistent_tool is silently ignored
        assert resolved_names == {"read_file"}

    def test_tool_guard_blocks_unlisted_tool(self, mock_main_agent, mock_tool_definitions):
        """Defense-in-depth: tool execution should be blocked if not in allowlist."""
        config = make_config(tools=["read_file"])
        # Use auto mode so approval gate doesn't interfere with allowlist test
        subagent = SubAgent(config, mock_main_agent, permission_mode="auto")

        # Mock LLM to return a tool call for write_file (not in allowlist)
        mock_tool_call = Mock()
        mock_tool_call.id = "call_123"
        mock_tool_call.function = Mock()
        mock_tool_call.function.name = "write_file"
        mock_tool_call.function.arguments = '{"file_path": "test.txt", "content": "hello"}'
        mock_tool_call.function.get_parsed_arguments.return_value = {
            "file_path": "test.txt", "content": "hello"
        }

        # First LLM call returns tool call, second returns text (no tools)
        llm_response_with_tools = Mock(spec=LLMResponse)
        llm_response_with_tools.content = ""
        llm_response_with_tools.tool_calls = [mock_tool_call]
        llm_response_with_tools.total_tokens = 100
        llm_response_with_tools.prompt_tokens = 80

        llm_response_done = Mock(spec=LLMResponse)
        llm_response_done.content = "Done"
        llm_response_done.tool_calls = None
        llm_response_done.total_tokens = 50
        llm_response_done.prompt_tokens = 40

        mock_main_agent.llm.generate_with_tools.side_effect = [
            llm_response_with_tools,
            llm_response_done,
        ]

        with patch('src.subagents.subagent.SyncJSONLWriter'):
            result = subagent.execute("Test task")

        # The tool call should have resulted in an error (PermissionError caught
        # by the generic Exception handler in the tool loop)
        assert result.success is True  # Execution continues after tool error
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["success"] is False
        assert "not allowed" in result.tool_calls[0]["error"]


# =============================================================================
# LLM OVERRIDE TESTS (nested SubAgentLLMConfig)
# =============================================================================

class TestLLMOverride:
    """Test that config.llm creates a separate LLM backend."""

    def test_llm_none_uses_main_agent(self, mock_main_agent):
        """config.llm=None should use main agent's LLM."""
        config = make_config(llm=None)
        subagent = SubAgent(config, mock_main_agent)

        assert subagent.llm is mock_main_agent.llm
        assert subagent._override_llm is None

    def test_llm_all_none_fields_treated_as_inherit(self, mock_main_agent):
        """SubAgentLLMConfig with all None fields should not create override."""
        llm = make_llm_config()  # All fields are None
        assert not llm.has_overrides

        config = make_config(llm=llm)
        subagent = SubAgent(config, mock_main_agent)

        assert subagent._override_llm is None
        assert subagent.llm is mock_main_agent.llm

    @patch('src.subagents.subagent.SubAgent._create_override_llm')
    def test_model_override_calls_create(self, mock_create, mock_main_agent):
        """config.llm with model set should attempt to create override LLM."""
        mock_override = Mock()
        mock_override.config = Mock()
        mock_override.config.model_name = "gpt-4o"
        mock_override.config.backend_type = "openai"
        mock_create.return_value = mock_override

        config = make_config(llm=make_llm_config(model="gpt-4o"))
        subagent = SubAgent(config, mock_main_agent)

        mock_create.assert_called_once()
        assert subagent._override_llm is mock_override
        assert subagent.llm is mock_override

    def test_model_only_inherits_backend_and_base_url(self, mock_main_agent):
        """Setting only model should inherit backend_type, base_url, api_key."""
        config = make_config(llm=make_llm_config(model="gpt-4o"))

        with patch('src.llm.OpenAIBackend') as MockBackend:
            mock_instance = Mock()
            mock_instance.config = Mock()
            mock_instance.config.model_name = "gpt-4o"
            mock_instance.config.backend_type = "openai"
            MockBackend.return_value = mock_instance

            subagent = SubAgent(config, mock_main_agent)

            MockBackend.assert_called_once()
            call_kwargs = MockBackend.call_args
            # Inherits api_key from main agent
            assert call_kwargs.kwargs.get("api_key") == "test-api-key-123"
            # Inherits base_url and backend_type from main agent
            llm_config = call_kwargs.kwargs.get("config") or call_kwargs.args[0]
            assert llm_config.model_name == "gpt-4o"
            assert llm_config.base_url == "http://localhost:8000/v1"
            assert llm_config.context_window == 128000

    def test_different_base_url_for_different_backend(self, mock_main_agent):
        """Setting base_url should override the main agent's endpoint."""
        config = make_config(llm=make_llm_config(
            model="llama3",
            base_url="http://ollama-server:11434",
            backend_type="ollama",
        ))

        with patch('src.llm.OllamaBackend') as MockBackend:
            mock_instance = Mock()
            mock_instance.config = Mock()
            mock_instance.config.model_name = "llama3"
            mock_instance.config.backend_type = "ollama"
            MockBackend.return_value = mock_instance

            subagent = SubAgent(config, mock_main_agent)

            MockBackend.assert_called_once()
            llm_config = MockBackend.call_args.kwargs.get("config") or MockBackend.call_args.args[0]
            assert llm_config.model_name == "llama3"
            assert llm_config.base_url == "http://ollama-server:11434"
            assert llm_config.backend_type == "ollama"

    def test_custom_api_key_per_subagent(self, mock_main_agent):
        """Setting api_key should use subagent-specific credentials."""
        config = make_config(llm=make_llm_config(
            model="gpt-4o",
            api_key="subagent-specific-key",
        ))

        with patch('src.llm.OpenAIBackend') as MockBackend:
            mock_instance = Mock()
            mock_instance.config = Mock()
            mock_instance.config.model_name = "gpt-4o"
            mock_instance.config.backend_type = "openai"
            MockBackend.return_value = mock_instance

            subagent = SubAgent(config, mock_main_agent)

            call_kwargs = MockBackend.call_args
            assert call_kwargs.kwargs.get("api_key") == "subagent-specific-key"

    @patch('src.subagents.subagent.SubAgent._create_override_llm')
    def test_override_failure_falls_back(self, mock_create, mock_main_agent):
        """Failed override creation should fall back to main agent's LLM."""
        mock_create.return_value = None  # Simulate failure

        config = make_config(llm=make_llm_config(model="bad-model"))
        subagent = SubAgent(config, mock_main_agent)

        assert subagent._override_llm is None
        assert subagent.llm is mock_main_agent.llm

    @patch('src.subagents.subagent.SubAgent._create_override_llm')
    def test_override_llm_used_in_execution(self, mock_create, mock_main_agent):
        """Execution should use the override LLM, not main agent's."""
        mock_override_llm = Mock()
        mock_override_llm.config = Mock()
        mock_override_llm.config.model_name = "gpt-4o"
        mock_override_llm.config.backend_type = "openai"

        # LLM returns a text response with no tools
        llm_response = Mock(spec=LLMResponse)
        llm_response.content = "Override model response"
        llm_response.tool_calls = None
        llm_response.total_tokens = 100
        llm_response.prompt_tokens = 80
        mock_override_llm.generate_with_tools.return_value = llm_response

        mock_create.return_value = mock_override_llm

        config = make_config(llm=make_llm_config(model="gpt-4o"))
        subagent = SubAgent(config, mock_main_agent)

        with patch('src.subagents.subagent.SyncJSONLWriter'):
            result = subagent.execute("Test task")

        # Override LLM should have been called, NOT main agent's
        mock_override_llm.generate_with_tools.assert_called()
        mock_main_agent.llm.generate_with_tools.assert_not_called()

        assert result.success is True
        assert result.output == "Override model response"
        assert result.metadata["model"] == "gpt-4o"
        assert result.metadata["llm_override"] is True


# =============================================================================
# BACKEND TYPE TESTS
# =============================================================================

class TestBackendType:
    """Test backend_type selection and validation."""

    def test_openai_compatible_backends_use_openai_class(self, mock_main_agent):
        """vllm, localai, llamacpp should all create OpenAIBackend."""
        for backend in ["openai", "vllm", "localai", "llamacpp"]:
            config = make_config(llm=make_llm_config(
                backend_type=backend, model="test-model",
            ))

            with patch('src.llm.OpenAIBackend') as MockBackend:
                mock_instance = Mock()
                mock_instance.config = Mock()
                mock_instance.config.model_name = "test-model"
                mock_instance.config.backend_type = backend
                MockBackend.return_value = mock_instance

                subagent = SubAgent(config, mock_main_agent)

                MockBackend.assert_called_once(), f"OpenAIBackend not called for {backend}"
                assert subagent._override_llm is mock_instance

    def test_ollama_backend_uses_ollama_class(self, mock_main_agent):
        """backend_type='ollama' should create OllamaBackend."""
        config = make_config(llm=make_llm_config(
            backend_type="ollama",
            model="llama3",
            base_url="http://localhost:11434",
        ))

        with patch('src.llm.OllamaBackend') as MockBackend:
            mock_instance = Mock()
            mock_instance.config = Mock()
            mock_instance.config.model_name = "llama3"
            mock_instance.config.backend_type = "ollama"
            MockBackend.return_value = mock_instance

            subagent = SubAgent(config, mock_main_agent)

            MockBackend.assert_called_once()
            # OllamaBackend should NOT receive api_key
            call_kwargs = MockBackend.call_args
            assert "api_key" not in call_kwargs.kwargs

    def test_invalid_backend_type_rejected_at_config(self):
        """Invalid backend_type should raise ValueError during config creation."""
        with pytest.raises(ValueError, match="Invalid backend_type"):
            make_llm_config(backend_type="invalid-backend")

    def test_backend_type_case_insensitive(self):
        """backend_type should be normalized to lowercase."""
        llm = make_llm_config(backend_type="OpenAI", model="test")
        assert llm.backend_type == "openai"


# =============================================================================
# METADATA TESTS
# =============================================================================

class TestMetadata:
    """Test that metadata correctly reflects config state."""

    def test_metadata_no_overrides(self, mock_main_agent):
        """Metadata should indicate no overrides when config uses defaults."""
        config = make_config(tools=None, llm=None)
        subagent = SubAgent(config, mock_main_agent)

        # Mock simple execution
        llm_response = Mock(spec=LLMResponse)
        llm_response.content = "Done"
        llm_response.tool_calls = None
        llm_response.total_tokens = 100
        llm_response.prompt_tokens = 80
        mock_main_agent.llm.generate_with_tools.return_value = llm_response

        with patch('src.subagents.subagent.SyncJSONLWriter'):
            result = subagent.execute("Test")

        assert result.metadata["model"] == "main-model"
        assert result.metadata["llm_override"] is False
        assert result.metadata["tools_filtered"] is False

    @patch('src.subagents.subagent.SubAgent._create_override_llm')
    def test_metadata_with_overrides(self, mock_create, mock_main_agent):
        """Metadata should indicate active overrides."""
        mock_override = Mock()
        mock_override.config = Mock()
        mock_override.config.model_name = "gpt-4o"
        mock_override.config.backend_type = "openai"

        llm_response = Mock(spec=LLMResponse)
        llm_response.content = "Done"
        llm_response.tool_calls = None
        llm_response.total_tokens = 100
        llm_response.prompt_tokens = 80
        mock_override.generate_with_tools.return_value = llm_response

        mock_create.return_value = mock_override

        config = make_config(
            tools=["read_file"],
            llm=make_llm_config(model="gpt-4o"),
        )
        subagent = SubAgent(config, mock_main_agent)

        with patch('src.subagents.subagent.SyncJSONLWriter'):
            result = subagent.execute("Test")

        assert result.metadata["model"] == "gpt-4o"
        assert result.metadata["llm_override"] is True
        assert result.metadata["tools_filtered"] is True

    def test_statistics_reflect_config(self, mock_main_agent):
        """get_statistics() should show model, backend, and tool filter state."""
        config = make_config(tools=["read_file"], llm=None)
        subagent = SubAgent(config, mock_main_agent)

        stats = subagent.get_statistics()
        assert stats["model"] == "main-model"
        assert stats["backend_type"] == LLMBackendType.OPENAI
        assert stats["llm_override"] is False
        assert stats["tools_filtered"] is True


# =============================================================================
# CONTEXT WINDOW OVERRIDE TESTS
# =============================================================================

class TestContextWindowOverride:
    """Test that llm.context_window is wired into override LLM."""

    def test_context_window_passed_to_override_llm(self, mock_main_agent):
        """Custom context_window should be passed to the override backend."""
        config = make_config(llm=make_llm_config(
            model="custom-model", context_window=32000,
        ))

        with patch('src.llm.OpenAIBackend') as MockBackend:
            mock_instance = Mock()
            mock_instance.config = Mock()
            mock_instance.config.model_name = "custom-model"
            mock_instance.config.backend_type = "openai"
            MockBackend.return_value = mock_instance

            subagent = SubAgent(config, mock_main_agent)

            MockBackend.assert_called_once()
            llm_config = MockBackend.call_args.kwargs.get("config") or MockBackend.call_args.args[0]
            assert llm_config.context_window == 32000

    def test_context_window_none_inherits_main(self, mock_main_agent):
        """Omitting context_window should inherit main agent's."""
        config = make_config(llm=make_llm_config(model="custom-model"))

        with patch('src.llm.OpenAIBackend') as MockBackend:
            mock_instance = Mock()
            mock_instance.config = Mock()
            mock_instance.config.model_name = "custom-model"
            mock_instance.config.backend_type = "openai"
            MockBackend.return_value = mock_instance

            subagent = SubAgent(config, mock_main_agent)

            MockBackend.assert_called_once()
            llm_config = MockBackend.call_args.kwargs.get("config") or MockBackend.call_args.args[0]
            assert llm_config.context_window == 128000


# =============================================================================
# INIT LOGGING TESTS
# =============================================================================

class TestInitLogging:
    """Test that initialization logs correct config info."""

    def test_init_log_inherited_model(self, mock_main_agent):
        """Init should log 'main agent' when no LLM override."""
        config = make_config(llm=None, tools=None)

        with patch('src.subagents.subagent.logger') as mock_logger:
            subagent = SubAgent(config, mock_main_agent)

            info_calls = [
                str(c) for c in mock_logger.info.call_args_list
            ]
            init_log = info_calls[0]
            assert "main agent" in init_log
            assert "inherited" in init_log

    @patch('src.subagents.subagent.SubAgent._create_override_llm')
    def test_init_log_override_model(self, mock_create, mock_main_agent):
        """Init should log 'override' when LLM is overridden."""
        mock_override = Mock()
        mock_override.config = Mock()
        mock_override.config.model_name = "gpt-4o"
        mock_override.config.backend_type = "openai"
        mock_create.return_value = mock_override

        config = make_config(
            llm=make_llm_config(model="gpt-4o"),
            tools=["read_file"],
        )

        with patch('src.subagents.subagent.logger') as mock_logger:
            subagent = SubAgent(config, mock_main_agent)

            info_calls = [
                str(c) for c in mock_logger.info.call_args_list
            ]
            # At least one log should mention override
            assert any("override" in call for call in info_calls)

    def test_init_log_filtered_tools(self, mock_main_agent):
        """Init should log tool count when tools are filtered."""
        config = make_config(tools=["read_file", "search_code"])

        with patch('src.subagents.subagent.logger') as mock_logger:
            subagent = SubAgent(config, mock_main_agent)

            info_calls = [
                str(c) for c in mock_logger.info.call_args_list
            ]
            init_log = info_calls[0]
            assert "2 configured" in init_log


# =============================================================================
# SubAgentLLMConfig UNIT TESTS
# =============================================================================

class TestSubAgentLLMConfig:
    """Test SubAgentLLMConfig validation and behavior."""

    def test_has_overrides_all_none(self):
        """All None fields should return has_overrides=False."""
        llm = SubAgentLLMConfig()
        assert llm.has_overrides is False

    def test_has_overrides_with_model(self):
        """Setting model alone should return has_overrides=True."""
        llm = SubAgentLLMConfig(model="gpt-4o")
        assert llm.has_overrides is True

    def test_has_overrides_with_backend_type(self):
        """Setting backend_type alone should return has_overrides=True."""
        llm = SubAgentLLMConfig(backend_type="ollama")
        assert llm.has_overrides is True

    def test_has_overrides_with_base_url(self):
        """Setting base_url alone should return has_overrides=True."""
        llm = SubAgentLLMConfig(base_url="http://other:8000")
        assert llm.has_overrides is True

    def test_valid_backend_types(self):
        """All recognized backend types should be accepted."""
        for bt in ["openai", "ollama", "vllm", "localai", "llamacpp"]:
            llm = SubAgentLLMConfig(backend_type=bt)
            assert llm.backend_type == bt

    def test_invalid_backend_type_raises(self):
        """Unrecognized backend_type should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid backend_type"):
            SubAgentLLMConfig(backend_type="anthropic")

    def test_backend_type_normalized_to_lowercase(self):
        """backend_type should be case-insensitive."""
        llm = SubAgentLLMConfig(backend_type="OPENAI")
        assert llm.backend_type == "openai"


# =============================================================================
# CONFIG PARSING TESTS (from_file with llm section)
# =============================================================================

class TestConfigParsing:
    """Test that from_file correctly parses the llm section."""

    def test_llm_section_parsed(self, tmp_path):
        """YAML frontmatter with llm section should populate SubAgentLLMConfig."""
        md = tmp_path / "test-agent.md"
        md.write_text(
            "---\n"
            "name: test-agent\n"
            "description: Test agent\n"
            "llm:\n"
            "  backend_type: openai\n"
            "  model: gpt-4o\n"
            "  base_url: http://custom:8000/v1\n"
            "  context_window: 64000\n"
            "---\n"
            "\nYou are a test agent.\n",
            encoding="utf-8",
        )
        config = SubAgentConfig.from_file(md)

        assert config.llm is not None
        assert config.llm.backend_type == "openai"
        assert config.llm.model == "gpt-4o"
        assert config.llm.base_url == "http://custom:8000/v1"
        assert config.llm.context_window == 64000

    def test_llm_model_inherit_becomes_none(self, tmp_path):
        """model: inherit in YAML should be parsed as None."""
        md = tmp_path / "test-agent.md"
        md.write_text(
            "---\n"
            "name: test-agent\n"
            "description: Test agent\n"
            "llm:\n"
            "  model: inherit\n"
            "---\n"
            "\nYou are a test agent.\n",
            encoding="utf-8",
        )
        config = SubAgentConfig.from_file(md)

        # model=inherit -> None, and no other overrides, so llm should be None
        assert config.llm is None

    def test_no_llm_section_means_inherit_all(self, tmp_path):
        """Missing llm section should result in llm=None."""
        md = tmp_path / "test-agent.md"
        md.write_text(
            "---\n"
            "name: test-agent\n"
            "description: Test agent\n"
            "---\n"
            "\nYou are a test agent.\n",
            encoding="utf-8",
        )
        config = SubAgentConfig.from_file(md)
        assert config.llm is None

    def test_llm_section_partial_overrides(self, tmp_path):
        """Only setting model should leave other llm fields as None."""
        md = tmp_path / "test-agent.md"
        md.write_text(
            "---\n"
            "name: test-agent\n"
            "description: Test agent\n"
            "llm:\n"
            "  model: gemini-2.0-flash\n"
            "---\n"
            "\nYou are a test agent.\n",
            encoding="utf-8",
        )
        config = SubAgentConfig.from_file(md)

        assert config.llm is not None
        assert config.llm.model == "gemini-2.0-flash"
        assert config.llm.backend_type is None
        assert config.llm.base_url is None
        assert config.llm.api_key is None
        assert config.llm.context_window is None
