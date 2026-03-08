"""Tests for src.ui.slash_commands - slash command dispatcher."""

import pytest
from unittest.mock import AsyncMock

from src.ui.slash_commands import SlashCommandDispatcher


@pytest.fixture
def mock_handlers():
    return {
        "/resume": AsyncMock(),
        "/config-llm": AsyncMock(),
        "/disconnect-jira": AsyncMock(),
    }


@pytest.fixture
def mock_prefix_handlers():
    return {
        "/connect-jira": AsyncMock(),
    }


@pytest.fixture
def dispatcher(mock_handlers, mock_prefix_handlers):
    return SlashCommandDispatcher(
        commands=mock_handlers,
        prefix_commands=mock_prefix_handlers,
    )


class TestSlashCommandDispatcher:
    @pytest.mark.asyncio
    async def test_exact_match(self, dispatcher, mock_handlers):
        result = await dispatcher.dispatch("/resume")
        assert result is True
        mock_handlers["/resume"].assert_called_once()

    @pytest.mark.asyncio
    async def test_case_insensitive(self, dispatcher, mock_handlers):
        result = await dispatcher.dispatch("/RESUME")
        assert result is True
        mock_handlers["/resume"].assert_called_once()

    @pytest.mark.asyncio
    async def test_whitespace_stripped(self, dispatcher, mock_handlers):
        result = await dispatcher.dispatch("  /resume  ")
        assert result is True
        mock_handlers["/resume"].assert_called_once()

    @pytest.mark.asyncio
    async def test_unknown_command_returns_false(self, dispatcher):
        result = await dispatcher.dispatch("/unknown")
        assert result is False

    @pytest.mark.asyncio
    async def test_prefix_match_exact(self, dispatcher, mock_prefix_handlers):
        result = await dispatcher.dispatch("/connect-jira")
        assert result is True
        mock_prefix_handlers["/connect-jira"].assert_called_once()

    @pytest.mark.asyncio
    async def test_prefix_match_with_args(self, dispatcher, mock_prefix_handlers):
        result = await dispatcher.dispatch("/connect-jira corporate")
        assert result is True
        mock_prefix_handlers["/connect-jira"].assert_called_once_with("/connect-jira corporate")

    @pytest.mark.asyncio
    async def test_exact_match_takes_priority_over_prefix(self):
        """If same string is both exact and prefix, exact wins."""
        exact_handler = AsyncMock()
        prefix_handler = AsyncMock()
        dispatcher = SlashCommandDispatcher(
            commands={"/test": exact_handler},
            prefix_commands={"/test": prefix_handler},
        )
        await dispatcher.dispatch("/test")
        exact_handler.assert_called_once()
        prefix_handler.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_prefix_commands(self):
        handler = AsyncMock()
        dispatcher = SlashCommandDispatcher(commands={"/foo": handler})
        result = await dispatcher.dispatch("/foo")
        assert result is True
        handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_false_prefix_match(self, dispatcher):
        """'/connect-jira-extra' should not match '/connect-jira' prefix."""
        result = await dispatcher.dispatch("/connect-jira-extra")
        assert result is False
