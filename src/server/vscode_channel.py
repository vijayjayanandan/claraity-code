"""VS Code terminal execution channel.

Provides async interface for RunCommandTool to:
1. Detect if VS Code extension is connected
2. Send command to terminal for execution
3. Wait for command result (exit code + output)

This is a bidirectional bridge between the agent and VS Code terminal.
"""

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Optional

from src.observability import get_logger

logger = get_logger("server.vscode_channel")


@dataclass
class TerminalResult:
    """Result from terminal execution."""

    exit_code: int
    output: str
    error: str = ""


class VSCodeChannel:
    """Async channel for terminal execution in VS Code extension.

    Usage:
        channel = VSCodeChannel()
        # Set up result callback (called from handleServerMessage in extension)
        channel.set_result_handler(handle_terminal_result)

        # Send command to terminal
        result = await channel.execute_in_terminal(
            command="npm test",
            working_dir="/path/to/project",
            timeout=120
        )

    Design:
        - is_connected() checks if extension is actively listening
        - execute_in_terminal() is async—waits for result via asyncio.Future
        - Extension calls receive_result() when terminal execution completes
        - Supports concurrent commands (each gets unique task_id)
    """

    def __init__(self):
        self._connected = False
        self._pending_results: dict[str, asyncio.Future] = {}
        self._send_callback: Callable[[dict], None] | None = None

    def is_connected(self) -> bool:
        """Check if VS Code extension is connected and listening."""
        return self._connected

    def set_connected(self, connected: bool) -> None:
        """Called by WebSocket when client connects/disconnects."""
        self._connected = connected
        if not connected:
            logger.info("[VSCode] Extension disconnected, clearing pending terminals")
            # Clear any pending futures
            for future in self._pending_results.values():
                if not future.done():
                    future.set_exception(RuntimeError("VS Code extension disconnected"))
            self._pending_results.clear()
        else:
            logger.info("[VSCode] Extension connected")

    def set_send_callback(self, callback: Callable[[dict], None]) -> None:
        """Set callback to send messages to WebSocket.

        Args:
            callback: Function that takes {type, command, ...} dict and sends via WebSocket
        """
        self._send_callback = callback

    async def execute_in_terminal(
        self,
        command: str,
        working_dir: str | None = None,
        timeout: int = 120,
        description: str = "",
    ) -> TerminalResult:
        """Send command to terminal and wait for result.

        Args:
            command: Shell command to execute
            working_dir: Working directory (PowerShell/bash cwd)
            timeout: Timeout in seconds
            description: Brief description for logging

        Returns:
            TerminalResult with exit_code and output

        Raises:
            RuntimeError: If extension not connected or communication fails
        """
        if not self._connected:
            raise RuntimeError("VS Code extension not connected")

        task_id = str(uuid.uuid4())
        future: asyncio.Future[TerminalResult] = asyncio.Future()
        self._pending_results[task_id] = future

        try:
            # Send command to extension
            if self._send_callback:
                self._send_callback(
                    {
                        "type": "execute_in_terminal",
                        "task_id": task_id,
                        "command": command,
                        "working_dir": working_dir,
                        "timeout": timeout,
                        "description": description,
                    }
                )
                logger.info(f"[VSCode] Sent command to terminal (task_id={task_id})")
            else:
                raise RuntimeError("No send callback configured")

            # Wait for result (with timeout fallback)
            result = await asyncio.wait_for(future, timeout=timeout + 10)
            return result

        except asyncio.TimeoutError:
            logger.error(f"[VSCode] Terminal execution timeout (task_id={task_id})")
            raise RuntimeError(f"Terminal execution timed out after {timeout} seconds")
        finally:
            self._pending_results.pop(task_id, None)

    def receive_result(self, task_id: str, exit_code: int, output: str = "", error: str = "") -> None:
        """Called when extension sends back terminal result.

        Args:
            task_id: The task_id from execute_in_terminal
            exit_code: Process exit code
            output: stdout from command
            error: stderr from command (if any)
        """
        future = self._pending_results.get(task_id)
        if future and not future.done():
            logger.info(f"[VSCode] Received result (task_id={task_id}, exit_code={exit_code})")
            future.set_result(TerminalResult(exit_code=exit_code, output=output, error=error))
        else:
            logger.warning(f"[VSCode] Received result for unknown task (task_id={task_id})")
