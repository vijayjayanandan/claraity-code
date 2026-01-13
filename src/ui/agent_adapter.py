"""
Agent Adapter - Bridges existing CodingAgent with the new Textual TUI.

This module provides:
1. AgentStreamAdapter: Wraps existing agent to yield UIEvents
2. create_stream_handler: Factory function to create stream handlers
3. Integration helpers for tool approval flow

Usage:
    from src.core.agent import CodingAgent
    from src.ui.agent_adapter import create_stream_handler
    from src.ui.app import run_app

    agent = CodingAgent()
    stream_handler = create_stream_handler(agent)
    run_app(stream_handler, model_name="claude-3-opus")
"""

from typing import AsyncIterator, Any, Callable
import asyncio
import time

from .events import (
    UIEvent, StreamStart, StreamEnd,
    TextDelta, CodeBlockStart, CodeBlockDelta, CodeBlockEnd,
    ToolCallStart, ToolCallStatus, ToolCallResult,
    ThinkingStart, ThinkingDelta, ThinkingEnd,
    ErrorEvent, ToolStatus,
)
from .protocol import UIProtocol, ApprovalResult
from .stream_processor import StreamProcessor


class AgentStreamAdapter:
    """
    Adapts an existing agent to work with the Textual TUI.

    This adapter:
    1. Wraps the agent's LLM calls to go through StreamProcessor
    2. Handles tool approval via UIProtocol
    3. Executes tools and yields result events

    Usage:
        adapter = AgentStreamAdapter(
            agent=my_agent,
            approval_checker=lambda name: name in {'bash', 'write_file'}
        )

        async for event in adapter.stream_response("Hello", ui_protocol):
            # Handle UIEvents
            pass
    """

    # Tools that always require approval
    DEFAULT_DANGEROUS_TOOLS = {
        'bash', 'execute_command', 'run_command',
        'write_file', 'create_file', 'delete_file', 'remove_file',
        'git_push', 'git_commit',
        'http_request', 'fetch_url',
    }

    def __init__(
        self,
        agent: Any,
        approval_checker: Callable[[str], bool] | None = None,
        idle_timeout_ms: int = 50,
        max_latency_ms: int = 150,
    ):
        """
        Initialize the adapter.

        Args:
            agent: Your existing CodingAgent instance
            approval_checker: Function to check if tool needs approval.
                             If None, uses DEFAULT_DANGEROUS_TOOLS.
            idle_timeout_ms: StreamProcessor idle timeout
            max_latency_ms: StreamProcessor max latency
        """
        self.agent = agent
        self.approval_checker = approval_checker or self._default_approval_checker

        self.processor = StreamProcessor(
            idle_timeout_ms=idle_timeout_ms,
            max_latency_ms=max_latency_ms,
            approval_checker=self.approval_checker,
        )

    def _default_approval_checker(self, tool_name: str) -> bool:
        """Default approval checker based on tool risk level."""
        return tool_name.lower() in self.DEFAULT_DANGEROUS_TOOLS

    async def stream_response(
        self,
        user_input: str,
        ui: UIProtocol,
    ) -> AsyncIterator[UIEvent]:
        """
        Stream response for a user input.

        This is the main entry point that:
        1. Sends user input to agent/LLM
        2. Processes raw stream through StreamProcessor
        3. Handles tool calls (approval + execution)
        4. Yields all UIEvents

        Args:
            user_input: The user's message
            ui: UIProtocol for approval coordination

        Yields:
            UIEvent instances
        """
        start_time = time.monotonic()

        try:
            # Get raw LLM stream from agent
            # This assumes your agent has a method like `stream_chat`
            raw_stream = await self._get_llm_stream(user_input)

            # Process through StreamProcessor
            async for event in self.processor.process(raw_stream):
                yield event

                # Handle tool calls
                if isinstance(event, ToolCallStart):
                    async for tool_event in self._handle_tool_call(event, ui):
                        yield tool_event

                # Check for interrupt
                if ui.check_interrupted():
                    break

        except Exception as e:
            yield ErrorEvent(
                error_type="agent_error",
                message=str(e),
                recoverable=False,
            )

    async def _get_llm_stream(self, user_input: str) -> AsyncIterator[Any]:
        """
        Get raw LLM stream from the agent.

        Override this method to integrate with your specific agent.
        """
        # This is a template - actual implementation depends on your agent
        # Example for OpenAI-style agent:
        if hasattr(self.agent, 'llm') and hasattr(self.agent.llm, 'stream'):
            messages = self._build_messages(user_input)
            async for chunk in self.agent.llm.stream(messages):
                yield chunk
        elif hasattr(self.agent, 'stream_chat'):
            async for chunk in self.agent.stream_chat(user_input):
                yield chunk
        else:
            # Fallback: simulate a simple response
            yield self._make_simple_chunk(f"Echo: {user_input}")

    def _build_messages(self, user_input: str) -> list[dict]:
        """Build messages array for LLM call."""
        messages = []

        # Add system prompt if agent has one
        if hasattr(self.agent, 'system_prompt'):
            messages.append({
                'role': 'system',
                'content': self.agent.system_prompt
            })

        # Add conversation history if available
        if hasattr(self.agent, 'conversation_history'):
            messages.extend(self.agent.conversation_history)

        # Add current user message
        messages.append({
            'role': 'user',
            'content': user_input
        })

        return messages

    def _make_simple_chunk(self, content: str) -> dict:
        """Create a simple chunk for testing."""
        return {
            'choices': [{
                'delta': {
                    'content': content
                }
            }]
        }

    async def _handle_tool_call(
        self,
        tool_call: ToolCallStart,
        ui: UIProtocol,
    ) -> AsyncIterator[UIEvent]:
        """
        Handle a tool call: approval + execution.

        Args:
            tool_call: The tool call to handle
            ui: UIProtocol for approval

        Yields:
            ToolCallStatus and ToolCallResult events
        """
        call_id = tool_call.call_id
        tool_name = tool_call.name
        args = tool_call.arguments

        # Wait for approval if required
        if tool_call.requires_approval:
            yield ToolCallStatus(call_id, ToolStatus.AWAITING_APPROVAL)

            try:
                result = await ui.wait_for_approval(call_id, tool_name)

                if not result.approved:
                    yield ToolCallStatus(
                        call_id,
                        ToolStatus.REJECTED,
                        message="User rejected"
                    )
                    return

                yield ToolCallStatus(call_id, ToolStatus.APPROVED)

            except asyncio.CancelledError:
                yield ToolCallStatus(call_id, ToolStatus.CANCELLED)
                return

        # Execute the tool
        yield ToolCallStatus(call_id, ToolStatus.RUNNING, message=f"Executing {tool_name}...")

        start_time = time.monotonic()

        try:
            result = await self._execute_tool(tool_name, args)
            duration_ms = int((time.monotonic() - start_time) * 1000)

            yield ToolCallResult(
                call_id=call_id,
                status=ToolStatus.SUCCESS,
                result=result,
                duration_ms=duration_ms,
            )

        except Exception as e:
            yield ToolCallResult(
                call_id=call_id,
                status=ToolStatus.FAILED,
                error=str(e),
            )

    async def _execute_tool(self, tool_name: str, args: dict) -> Any:
        """
        Execute a tool.

        Override this to integrate with your agent's tool system.
        """
        # This is a template - actual implementation depends on your agent
        if hasattr(self.agent, 'tools') and hasattr(self.agent.tools, 'execute'):
            return await self.agent.tools.execute(tool_name, args)
        elif hasattr(self.agent, 'execute_tool'):
            return await self.agent.execute_tool(tool_name, args)
        else:
            return f"[Tool {tool_name} executed with args: {args}]"


def create_stream_handler(
    agent: Any,
    approval_checker: Callable[[str], bool] | None = None,
) -> Callable[[str, UIProtocol], AsyncIterator[UIEvent]]:
    """
    Factory function to create a stream handler for the TUI.

    This is the recommended way to integrate your agent with the TUI.

    Args:
        agent: Your CodingAgent instance
        approval_checker: Optional function to check if tool needs approval

    Returns:
        A stream handler function suitable for CodingAgentApp

    Usage:
        agent = CodingAgent()
        stream_handler = create_stream_handler(agent)
        run_app(stream_handler, model_name="claude-3-opus")
    """
    adapter = AgentStreamAdapter(agent, approval_checker)
    return adapter.stream_response


async def demo_stream_handler(
    user_input: str,
    ui: UIProtocol,
) -> AsyncIterator[UIEvent]:
    """
    Demo stream handler for testing the TUI without a real agent.

    Shows various UI capabilities:
    - Text streaming
    - Code blocks
    - Tool calls with approval
    - Thinking blocks
    """
    yield StreamStart()

    # Simulate text response
    yield TextDelta(content=f"I received your message: **{user_input}**\n\n")
    await asyncio.sleep(0.1)

    # Simulate thinking
    yield ThinkingStart()
    yield ThinkingDelta(content="Let me analyze this request...\n")
    await asyncio.sleep(0.2)
    yield ThinkingDelta(content="Considering the best approach...\n")
    await asyncio.sleep(0.2)
    yield ThinkingEnd(token_count=50)

    yield TextDelta(content="Here's a code example:\n\n")

    # Simulate code block
    yield CodeBlockStart(language="python")
    code_lines = [
        "def greet(name):\n",
        "    \"\"\"Greet someone by name.\"\"\"\n",
        "    return f\"Hello, {name}!\"\n",
        "\n",
        "# Usage\n",
        "print(greet(\"World\"))\n",
    ]
    for line in code_lines:
        yield CodeBlockDelta(content=line)
        await asyncio.sleep(0.05)
    yield CodeBlockEnd()

    yield TextDelta(content="\nNow let me read a file:\n\n")

    # Simulate tool call with approval
    yield ToolCallStart(
        call_id="demo-1",
        name="read_file",
        arguments={"path": "example.py"},
        requires_approval=True,
    )

    # Wait for approval
    yield ToolCallStatus("demo-1", ToolStatus.AWAITING_APPROVAL)

    try:
        result = await ui.wait_for_approval("demo-1", "read_file", timeout=30.0)

        if result.approved:
            yield ToolCallStatus("demo-1", ToolStatus.APPROVED)
            yield ToolCallStatus("demo-1", ToolStatus.RUNNING, message="Reading file...")
            await asyncio.sleep(0.5)
            yield ToolCallResult(
                call_id="demo-1",
                status=ToolStatus.SUCCESS,
                result="# Example file contents\nprint('Hello!')",
                duration_ms=50,
            )
            yield TextDelta(content="\nFile read successfully!\n")
        else:
            yield ToolCallStatus("demo-1", ToolStatus.REJECTED)
            yield TextDelta(content="\nFile read was skipped.\n")

    except asyncio.CancelledError:
        yield ToolCallStatus("demo-1", ToolStatus.CANCELLED)
        return
    except asyncio.TimeoutError:
        yield ToolCallStatus("demo-1", ToolStatus.CANCELLED)
        yield TextDelta(content="\nApproval timed out.\n")

    yield StreamEnd(total_tokens=150, duration_ms=2000)
