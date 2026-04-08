"""Tests for subagent CRUD server handlers.

Covers:
- list_subagents: returns all configs with correct source/path
- save_subagent: creates .md file, validates inputs, hot-reloads
- delete_subagent: removes file, protects built-ins, hot-reloads
- reload_subagents: reloads manager and returns fresh list
"""

import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_md(directory: Path, name: str, description: str = "Test agent", prompt: str = "You are a test agent.") -> Path:
    """Write a minimal valid subagent .md file."""
    directory.mkdir(parents=True, exist_ok=True)
    content = f"---\nname: {name}\ndescription: {description}\n---\n\n{prompt}\n"
    path = directory / f"{name}.md"
    path.write_text(content, encoding="utf-8")
    return path


def _make_handler(tmp_path: Path) -> "StdioProtocol":
    """Create a StdioProtocol instance with mocked internals for unit testing."""
    from src.server.stdio_server import StdioProtocol

    # Patch the constructor dependencies so we can build one without a real event loop
    store = MagicMock()
    agent = MagicMock()
    agent.subagent_manager = MagicMock()
    agent.subagent_manager.reload_subagents = MagicMock(return_value={})
    agent.tool_executor = MagicMock()
    agent.tool_executor.get_tool = MagicMock(return_value=None)

    with patch("asyncio.get_running_loop"):
        handler = StdioProtocol.__new__(StdioProtocol)
        handler._store = store
        handler._agent = agent
        handler._working_directory = str(tmp_path)
        handler._data_port = 0
        handler._send_lock = asyncio.Lock()
        handler._closed = False
        handler._session_id = ""
        handler._session_writer = None
        handler._streaming_task = None
        handler._stdin_queue = asyncio.Queue()
        handler._chat_queue = asyncio.Queue()
        handler._tcp_writer = None
        handler._unsubscribe = None

    return handler


def run(coro):
    """Run a coroutine in a fresh event loop."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# list_subagents
# ---------------------------------------------------------------------------

class TestHandleListSubagents:

    def test_returns_all_subagents(self, tmp_path):
        handler = _make_handler(tmp_path)
        sent = []
        handler._send_json = AsyncMock(side_effect=lambda d: sent.append(d))

        run(handler._handle_list_subagents({}))

        assert len(sent) == 1
        response = sent[0]
        assert response["type"] == "subagents_list"
        assert isinstance(response["subagents"], list)
        assert len(response["subagents"]) > 0

    def test_each_subagent_has_required_fields(self, tmp_path):
        handler = _make_handler(tmp_path)
        sent = []
        handler._send_json = AsyncMock(side_effect=lambda d: sent.append(d))

        run(handler._handle_list_subagents({}))

        for subagent in sent[0]["subagents"]:
            assert "name" in subagent
            assert "description" in subagent
            assert "system_prompt" in subagent
            assert "source" in subagent
            assert "config_path" in subagent
            assert subagent["source"] in ("builtin", "project", "user")

    def test_builtin_subagents_have_null_config_path(self, tmp_path):
        handler = _make_handler(tmp_path)
        sent = []
        handler._send_json = AsyncMock(side_effect=lambda d: sent.append(d))

        run(handler._handle_list_subagents({}))

        builtins = [s for s in sent[0]["subagents"] if s["source"] == "builtin"]
        assert len(builtins) > 0
        for b in builtins:
            assert b["config_path"] is None

    def test_project_subagent_appears_in_list(self, tmp_path):
        project_dir = tmp_path / ".claraity" / "agents"
        _make_md(project_dir, "my-custom-agent", "My custom agent", "You are custom.")

        handler = _make_handler(tmp_path)
        sent = []
        handler._send_json = AsyncMock(side_effect=lambda d: sent.append(d))

        run(handler._handle_list_subagents({}))

        names = {s["name"] for s in sent[0]["subagents"]}
        assert "my-custom-agent" in names

        custom = next(s for s in sent[0]["subagents"] if s["name"] == "my-custom-agent")
        assert custom["source"] == "project"
        assert custom["config_path"] is not None

    def test_returns_empty_list_on_error(self, tmp_path):
        handler = _make_handler(tmp_path)
        sent = []
        handler._send_json = AsyncMock(side_effect=lambda d: sent.append(d))

        with patch("src.subagents.config.SubAgentConfigLoader.discover_all", side_effect=RuntimeError("boom")):
            run(handler._handle_list_subagents({}))

        assert sent[0]["type"] == "subagents_list"
        assert sent[0]["subagents"] == []


# ---------------------------------------------------------------------------
# save_subagent
# ---------------------------------------------------------------------------

class TestHandleSaveSubagent:

    def test_creates_md_file(self, tmp_path):
        handler = _make_handler(tmp_path)
        handler._send_json = AsyncMock()

        run(handler._handle_save_subagent({
            "name": "new-agent",
            "description": "A new agent",
            "system_prompt": "You are a new agent.",
        }))

        target = tmp_path / ".claraity" / "agents" / "new-agent.md"
        assert target.exists()

    def test_file_content_is_valid_subagent_config(self, tmp_path):
        handler = _make_handler(tmp_path)
        handler._send_json = AsyncMock()

        run(handler._handle_save_subagent({
            "name": "valid-agent",
            "description": "Valid agent",
            "system_prompt": "You are valid.",
        }))

        from src.subagents.config import SubAgentConfig
        config = SubAgentConfig.from_file(tmp_path / ".claraity" / "agents" / "valid-agent.md")
        assert config.name == "valid-agent"
        assert config.description == "Valid agent"
        assert "You are valid." in config.system_prompt

    def test_saves_tools_in_frontmatter(self, tmp_path):
        handler = _make_handler(tmp_path)
        handler._send_json = AsyncMock()

        run(handler._handle_save_subagent({
            "name": "tool-agent",
            "description": "Agent with tools",
            "system_prompt": "You use tools.",
            "tools": ["read_file", "write_file"],
        }))

        from src.subagents.config import SubAgentConfig
        config = SubAgentConfig.from_file(tmp_path / ".claraity" / "agents" / "tool-agent.md")
        assert config.tools is not None
        assert "read_file" in config.tools
        assert "write_file" in config.tools

    def test_returns_success_response(self, tmp_path):
        handler = _make_handler(tmp_path)
        sent = []
        handler._send_json = AsyncMock(side_effect=lambda d: sent.append(d))

        run(handler._handle_save_subagent({
            "name": "ok-agent",
            "description": "OK agent",
            "system_prompt": "You are OK.",
        }))

        assert sent[0]["type"] == "subagent_saved"
        assert sent[0]["success"] is True
        assert sent[0]["name"] == "ok-agent"

    def test_rejects_invalid_name(self, tmp_path):
        handler = _make_handler(tmp_path)
        sent = []
        handler._send_json = AsyncMock(side_effect=lambda d: sent.append(d))

        for bad_name in ["Bad Agent", "bad agent", "bad_agent", "BAD", "bad!", ""]:
            sent.clear()
            run(handler._handle_save_subagent({
                "name": bad_name,
                "description": "Test",
                "system_prompt": "Test.",
            }))
            assert sent[0]["success"] is False, f"Expected failure for name {bad_name!r}"

    def test_rejects_empty_description(self, tmp_path):
        handler = _make_handler(tmp_path)
        sent = []
        handler._send_json = AsyncMock(side_effect=lambda d: sent.append(d))

        run(handler._handle_save_subagent({
            "name": "ok-name",
            "description": "",
            "system_prompt": "You are OK.",
        }))

        assert sent[0]["success"] is False
        assert "description" in sent[0]["message"].lower()

    def test_rejects_empty_system_prompt(self, tmp_path):
        handler = _make_handler(tmp_path)
        sent = []
        handler._send_json = AsyncMock(side_effect=lambda d: sent.append(d))

        run(handler._handle_save_subagent({
            "name": "ok-name",
            "description": "OK description",
            "system_prompt": "",
        }))

        assert sent[0]["success"] is False
        assert "prompt" in sent[0]["message"].lower()

    def test_hot_reloads_agent_subagent_manager(self, tmp_path):
        handler = _make_handler(tmp_path)
        handler._send_json = AsyncMock()

        run(handler._handle_save_subagent({
            "name": "reload-agent",
            "description": "Reload test",
            "system_prompt": "You test reloads.",
        }))

        handler._agent.subagent_manager.reload_subagents.assert_called_once()

    def test_can_overwrite_existing_file(self, tmp_path):
        """Save to same name twice -- second write wins."""
        handler = _make_handler(tmp_path)
        sent = []
        handler._send_json = AsyncMock(side_effect=lambda d: sent.append(d))

        run(handler._handle_save_subagent({
            "name": "overwrite-agent",
            "description": "First version",
            "system_prompt": "First prompt.",
        }))
        sent.clear()
        run(handler._handle_save_subagent({
            "name": "overwrite-agent",
            "description": "Second version",
            "system_prompt": "Second prompt.",
        }))

        assert sent[0]["success"] is True
        from src.subagents.config import SubAgentConfig
        config = SubAgentConfig.from_file(tmp_path / ".claraity" / "agents" / "overwrite-agent.md")
        assert config.description == "Second version"


# ---------------------------------------------------------------------------
# delete_subagent
# ---------------------------------------------------------------------------

class TestHandleDeleteSubagent:

    def test_deletes_existing_project_file(self, tmp_path):
        project_dir = tmp_path / ".claraity" / "agents"
        _make_md(project_dir, "deletable-agent")

        handler = _make_handler(tmp_path)
        sent = []
        handler._send_json = AsyncMock(side_effect=lambda d: sent.append(d))

        run(handler._handle_delete_subagent({"name": "deletable-agent"}))

        assert sent[0]["success"] is True
        assert not (project_dir / "deletable-agent.md").exists()

    def test_returns_failure_for_builtin(self, tmp_path):
        """code-reviewer has no project .md file -- should fail gracefully."""
        handler = _make_handler(tmp_path)
        sent = []
        handler._send_json = AsyncMock(side_effect=lambda d: sent.append(d))

        run(handler._handle_delete_subagent({"name": "code-reviewer"}))

        assert sent[0]["success"] is False
        assert "code-reviewer" in sent[0]["message"]

    def test_returns_failure_for_nonexistent_name(self, tmp_path):
        handler = _make_handler(tmp_path)
        sent = []
        handler._send_json = AsyncMock(side_effect=lambda d: sent.append(d))

        run(handler._handle_delete_subagent({"name": "does-not-exist"}))

        assert sent[0]["success"] is False

    def test_returns_failure_for_empty_name(self, tmp_path):
        handler = _make_handler(tmp_path)
        sent = []
        handler._send_json = AsyncMock(side_effect=lambda d: sent.append(d))

        run(handler._handle_delete_subagent({"name": ""}))

        assert sent[0]["success"] is False

    def test_hot_reloads_after_delete(self, tmp_path):
        project_dir = tmp_path / ".claraity" / "agents"
        _make_md(project_dir, "hot-reload-agent")

        handler = _make_handler(tmp_path)
        handler._send_json = AsyncMock()

        run(handler._handle_delete_subagent({"name": "hot-reload-agent"}))

        handler._agent.subagent_manager.reload_subagents.assert_called_once()

    def test_delete_then_builtin_restored(self, tmp_path):
        """After deleting a forked built-in, the original built-in is visible again."""
        project_dir = tmp_path / ".claraity" / "agents"
        _make_md(project_dir, "code-reviewer", "Forked reviewer", "Forked prompt.")

        handler = _make_handler(tmp_path)
        sent = []
        handler._send_json = AsyncMock(side_effect=lambda d: sent.append(d))

        run(handler._handle_delete_subagent({"name": "code-reviewer"}))
        assert sent[0]["success"] is True

        # After deletion, list should show the built-in again
        sent.clear()
        run(handler._handle_list_subagents({}))
        code_reviewer = next(
            (s for s in sent[0]["subagents"] if s["name"] == "code-reviewer"), None
        )
        assert code_reviewer is not None
        assert code_reviewer["source"] == "builtin"


# ---------------------------------------------------------------------------
# reload_subagents
# ---------------------------------------------------------------------------

class TestHandleReloadSubagents:

    def test_calls_reload_on_agent_manager(self, tmp_path):
        handler = _make_handler(tmp_path)
        sent = []
        handler._send_json = AsyncMock(side_effect=lambda d: sent.append(d))

        run(handler._handle_reload_subagents({}))

        handler._agent.subagent_manager.reload_subagents.assert_called_once()

    def test_returns_subagents_list_after_reload(self, tmp_path):
        handler = _make_handler(tmp_path)
        sent = []
        handler._send_json = AsyncMock(side_effect=lambda d: sent.append(d))

        run(handler._handle_reload_subagents({}))

        assert sent[0]["type"] == "subagents_list"
        assert isinstance(sent[0]["subagents"], list)

    def test_reload_without_agent_still_returns_list(self, tmp_path):
        handler = _make_handler(tmp_path)
        handler._agent = None  # Simulate no agent running
        sent = []
        handler._send_json = AsyncMock(side_effect=lambda d: sent.append(d))

        run(handler._handle_reload_subagents({}))

        assert sent[0]["type"] == "subagents_list"

    def test_delegation_tool_description_refreshed_on_reload(self, tmp_path):
        """If delegation tool is present, refresh_description() must be called."""
        delegation_tool = MagicMock()

        handler = _make_handler(tmp_path)
        handler._agent.tool_executor.get_tool = MagicMock(return_value=delegation_tool)
        handler._send_json = AsyncMock()

        run(handler._handle_reload_subagents({}))

        delegation_tool.refresh_description.assert_called_once()
