"""
Smoke test for CodingAgent construction.

Verifies that CodingAgent can be imported and constructed without errors.
This catches stale imports (e.g., deleted tool classes still referenced in
agent.py) that would otherwise only surface when running the live agent.

No API key needed -- uses a dummy config with a fake backend.
"""

import pytest
from pathlib import Path


class TestAgentSmoke:
    """Verify CodingAgent can be constructed without import errors."""

    def test_from_config_constructs_without_error(self, tmp_path):
        """CodingAgent.from_config should not raise ImportError or similar."""
        from src.llm.config_loader import LLMConfigData

        config = LLMConfigData(
            model="test-model",
            backend_type="openai",
            base_url="http://localhost:9999",
            context_window=4096,
            api_key="fake-key-for-smoke-test",
        )

        from src.core.agent import CodingAgent

        agent = CodingAgent.from_config(
            config,
            working_directory=str(tmp_path),
            permission_mode="normal",
            load_file_memories=False,
        )

        assert agent is not None
        assert agent.working_directory == tmp_path

    def test_all_tools_registered(self, tmp_path):
        """All expected tools should be registered in the executor."""
        from src.llm.config_loader import LLMConfigData
        from src.core.agent import CodingAgent

        config = LLMConfigData(
            model="test-model",
            backend_type="openai",
            base_url="http://localhost:9999",
            context_window=4096,
            api_key="fake-key-for-smoke-test",
        )

        agent = CodingAgent.from_config(
            config,
            working_directory=str(tmp_path),
            permission_mode="normal",
            load_file_memories=False,
        )

        registered = set(agent.tool_executor.tools.keys())

        # Core tools that must always be present
        expected = {
            "read_file", "write_file", "edit_file",
            "run_command", "list_directory",
            "grep", "glob",
            "knowledge_query", "knowledge_update",
        }
        missing = expected - registered
        assert not missing, f"Missing tools: {missing}"

    def test_deleted_tools_not_registered(self, tmp_path):
        """Consolidated tools should NOT appear as separate registrations."""
        from src.llm.config_loader import LLMConfigData
        from src.core.agent import CodingAgent

        config = LLMConfigData(
            model="test-model",
            backend_type="openai",
            base_url="http://localhost:9999",
            context_window=4096,
            api_key="fake-key-for-smoke-test",
        )

        agent = CodingAgent.from_config(
            config,
            working_directory=str(tmp_path),
            permission_mode="normal",
            load_file_memories=False,
        )

        registered = set(agent.tool_executor.tools.keys())

        # These were consolidated into knowledge_query
        deleted = {"knowledge_brief", "knowledge_module", "knowledge_file",
                   "knowledge_search", "knowledge_impact"}
        found = deleted & registered
        assert not found, f"Deleted tools still registered: {found}"
