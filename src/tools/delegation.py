"""Subagent delegation tool for LLM tool calling interface.

Supports two execution modes:
- Sync (CLI): execute() - uses in-process SubAgent via SubAgentManager
- Async (TUI): execute_async() - launches subprocess, reads JSON-line events
"""

import asyncio
import json
import os
import sys
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Dict, Any, Optional, TYPE_CHECKING

from src.observability import get_logger

if TYPE_CHECKING:
    from src.subagents import SubAgentManager

from .base import Tool, ToolResult, ToolStatus

logger = get_logger("tools.delegation")


class DelegateToSubagentTool(Tool):
    """Tool for delegating tasks to specialized subagents.

    Enables the LLM to invoke subagents for specialized tasks like code review,
    test writing, or documentation. Subagents operate with independent context
    windows, preventing pollution of the main conversation.

    In TUI mode, uses execute_async() to launch a subprocess so the event loop
    stays unblocked. In CLI mode, uses execute() with in-process SubAgent.
    """

    def __init__(self, subagent_manager: 'SubAgentManager'):
        """Initialize delegation tool.

        Args:
            subagent_manager: SubAgentManager instance from main agent
        """
        self.subagent_manager = subagent_manager
        self._registry = None  # SubagentRegistry for TUI visibility

        # Generate dynamic description with available subagents
        description = self._generate_description()

        super().__init__(
            name="delegate_to_subagent",
            description=description
        )

    def set_registry(self, registry) -> None:
        """Wire up SubagentRegistry for TUI visibility.

        Called by app.py during _setup_subagent_registry().
        """
        self._registry = registry
        logger.info("DelegateToSubagentTool: Registry wired")

    def _generate_description(self) -> str:
        """Generate dynamic tool description listing available subagents."""
        available = self.subagent_manager.get_available_subagents()

        if not available:
            return "Delegate task to specialized subagent. (No subagents currently available)"

        descriptions = []
        for name in available:
            info = self.subagent_manager.get_subagent_info(name)
            if info:
                descriptions.append(f"  - {name}: {info['description']}")

        subagent_list = "\n".join(descriptions)

        return f"""Delegate a task to a specialized subagent for focused execution.

Available subagents:
{subagent_list}

When to use:
- Task requires specialized expertise (code review, testing, documentation)
- Task can be isolated from main conversation context
- You need independent analysis without context pollution
- Complex task benefits from focused, specialized attention

Benefits:
- Independent context window (won't pollute main conversation)
- Specialized system prompts optimized for specific tasks
- Parallel execution possible (multiple subagents can run concurrently)

Use this tool proactively when appropriate!"""

    # =========================================================================
    # Sync execution (CLI mode - in-process)
    # =========================================================================

    def execute(self, subagent: str, task: str, **kwargs: Any) -> ToolResult:
        """Execute subagent delegation synchronously (CLI mode).

        Args:
            subagent: Name of the subagent to use (e.g., 'code-reviewer')
            task: Clear description of the task to delegate
            **kwargs: Additional arguments (_tool_call_id injected by agent)

        Returns:
            ToolResult with subagent output or error
        """
        parent_tool_call_id = kwargs.pop('_tool_call_id', '')
        logger.info(f"Tool: Delegating to subagent '{subagent}': {task[:100]}...")

        # Validate inputs
        validation_error = self._validate_inputs(subagent, task)
        if validation_error:
            return validation_error

        # Get subagent instance (so we can register before execute)
        subagent_instance = self.subagent_manager.get_subagent(subagent.strip())
        if not subagent_instance:
            available = self.subagent_manager.get_available_subagents()
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Subagent '{subagent}' not found. Available: {', '.join(available)}"
            )

        # Register with TUI registry for live visibility
        registered = False
        if self._registry and parent_tool_call_id:
            try:
                info = subagent_instance.get_session_info()
                model_name = subagent_instance.llm.config.model_name
                self._registry.register(
                    subagent_id=info.subagent_id,
                    store=info.store,
                    transcript_path=info.transcript_path,
                    parent_tool_call_id=parent_tool_call_id,
                    instance=subagent_instance,
                    model_name=model_name,
                )
                registered = True
                logger.info(
                    f"Registered subagent {info.subagent_id} "
                    f"with parent tool_call_id={parent_tool_call_id}"
                )
            except Exception as e:
                logger.error(f"Failed to register subagent with TUI: {e}")

        # Execute the task
        try:
            result = subagent_instance.execute(
                task_description=task.strip(),
            )
        finally:
            # Unregister from TUI when done
            if registered:
                try:
                    info = subagent_instance.get_session_info()
                    self._registry.unregister(info.subagent_id)
                except Exception as e:
                    logger.error(f"Failed to unregister subagent: {e}")

        return self._build_tool_result(subagent, result)

    # =========================================================================
    # Async execution (TUI mode - subprocess)
    # =========================================================================

    async def execute_async(self, subagent: str, task: str, **kwargs: Any) -> ToolResult:
        """Execute subagent delegation asynchronously via subprocess (TUI mode).

        Launches a subprocess running src.subagents.runner, communicates via
        JSON-line IPC over stdin/stdout. Runs entirely on the event loop -
        no threads, no call_from_thread, no blocking.

        Args:
            subagent: Name of the subagent to use
            task: Clear description of the task to delegate
            **kwargs: Additional arguments (_tool_call_id injected by agent)

        Returns:
            ToolResult with subagent output or error
        """
        from src.subagents.ipc import (
            SubprocessInput, IPCEventType,
            deserialize_notification, deserialize_result,
        )

        parent_tool_call_id = kwargs.pop('_tool_call_id', '')
        logger.info(f"Tool [async]: Delegating to subagent '{subagent}': {task[:100]}...")

        # Validate inputs
        validation_error = self._validate_inputs(subagent, task)
        if validation_error:
            return validation_error

        # Resolve config
        config = self.subagent_manager.configs.get(subagent.strip())
        if not config:
            available = self.subagent_manager.get_available_subagents()
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Subagent '{subagent}' not found. Available: {', '.join(available)}"
            )

        # Resolve LLM config and API key for the subprocess
        llm_config_dict, api_key = self._resolve_llm_config(config)

        # Determine working directory
        working_directory = str(
            getattr(self.subagent_manager.main_agent, 'working_directory', Path.cwd())
        )

        # Build subprocess input
        session_id = str(uuid.uuid4())[:8]
        transcript_path = str(
            Path(".clarity/sessions/subagents") / f"{config.name}-{session_id}.jsonl"
        )

        subprocess_input = SubprocessInput(
            config=asdict(config),
            llm_config=llm_config_dict,
            api_key=api_key,
            task_description=task.strip(),
            working_directory=working_directory,
            max_iterations=50,
            transcript_path=transcript_path,
        )

        # Launch subprocess
        input_json = subprocess_input.to_json()

        process = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "src.subagents.runner",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=working_directory,
            # Default asyncio StreamReader limit is 64KB per line.
            # Subagent DONE events with large outputs (code reviews, etc.)
            # can easily exceed that as a single JSON line. 16MB is generous.
            limit=16 * 1024 * 1024,
        )

        # Send input, close stdin
        process.stdin.write(input_json.encode('utf-8') + b'\n')
        await process.stdin.drain()
        process.stdin.close()

        # Drain stderr in background to prevent deadlock.
        # If the subprocess writes >64KB to stderr (tracebacks, stray prints),
        # the pipe buffer fills and the subprocess blocks on write, which
        # also blocks stdout → parent hangs waiting for stdout events.
        stderr_chunks: list[bytes] = []

        async def _drain_stderr():
            try:
                while True:
                    chunk = await process.stderr.read(4096)
                    if not chunk:
                        break
                    stderr_chunks.append(chunk)
            except Exception:
                pass

        stderr_task = asyncio.ensure_future(_drain_stderr())

        # Read stdout events asynchronously (on event loop - no blocking!)
        result = None
        subagent_id = None

        try:
            async for line in process.stdout:
                line_str = line.decode('utf-8').strip()
                if not line_str:
                    continue

                try:
                    event = json.loads(line_str)
                except json.JSONDecodeError:
                    logger.warning(f"Non-JSON line from subprocess: {line_str[:100]}")
                    continue

                event_type = event.get("type", "")

                if event_type == IPCEventType.REGISTERED:
                    subagent_id = event.get("subagent_id", session_id)
                    model_name = event.get("model_name", "")
                    # Register with TUI registry for SubAgentCard
                    if self._registry and parent_tool_call_id:
                        self._registry.register(
                            subagent_id=subagent_id,
                            store=None,  # No shared store in subprocess mode
                            transcript_path=Path(transcript_path),
                            parent_tool_call_id=parent_tool_call_id,
                            instance=process,  # asyncio.Process for cancel
                            model_name=model_name,
                        )

                elif event_type == IPCEventType.NOTIFICATION:
                    if subagent_id and self._registry:
                        try:
                            notification = deserialize_notification(
                                event.get("notification", {})
                            )
                            self._registry.push_notification(
                                subagent_id, notification
                            )
                        except Exception as e:
                            logger.error(
                                f"Failed to deserialize notification: {e}"
                            )

                elif event_type == IPCEventType.DONE:
                    result_data = event.get("result", {})
                    sa_result = deserialize_result(result_data)
                    result = self._build_tool_result(subagent, sa_result)
                    break  # Got result, stop reading

                elif event_type == IPCEventType.ERROR:
                    error_msg = event.get("error", "Unknown subprocess error")
                    result = ToolResult(
                        tool_name=self.name,
                        status=ToolStatus.ERROR,
                        output=None,
                        error=f"Subagent subprocess error: {error_msg}",
                    )
                    break  # Got error, stop reading

        except asyncio.CancelledError:
            # Cancellation: terminate subprocess with timeout
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
            raise

        except Exception as e:
            # Catch unexpected errors (e.g., StreamReader ValueError for oversized
            # lines) so they get logged and returned as a proper ToolResult instead
            # of propagating unhandled through execute_tool_async → agent loop.
            logger.error(
                f"Tool [async]: Unexpected error during subagent '{subagent}' "
                f"execution: {type(e).__name__}: {e}"
            )
            result = ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Subagent execution error: {type(e).__name__}: {e}",
            )

        finally:
            # Unregister from TUI
            if subagent_id and self._registry:
                self._registry.unregister(subagent_id)
            # Ensure process is cleaned up (with timeout escalation)
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
            else:
                await process.wait()
            # Let stderr drain finish (brief timeout to capture crash diagnostics)
            try:
                await asyncio.wait_for(stderr_task, timeout=2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                stderr_task.cancel()
                try:
                    await stderr_task
                except asyncio.CancelledError:
                    pass

        # If we never got a result (e.g., process crashed without emitting DONE)
        if result is None:
            stderr_output = b"".join(stderr_chunks).decode('utf-8', errors='replace')
            result = ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Subagent subprocess exited without result (code={process.returncode}). "
                      f"stderr: {stderr_output[:500]}",
            )

        return result

    # =========================================================================
    # Helpers
    # =========================================================================

    def _validate_inputs(self, subagent: str, task: str) -> Optional[ToolResult]:
        """Validate subagent and task inputs.

        Returns ToolResult error if invalid, None if valid.
        """
        if not subagent or not subagent.strip():
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error="Subagent name is required and cannot be empty"
            )

        if not task or not task.strip():
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error="Task description is required and cannot be empty"
            )

        return None

    def _resolve_llm_config(self, config) -> tuple:
        """Resolve LLM config dict and API key for subprocess.

        Merges SubAgentLLMConfig overrides with main agent's LLMConfig defaults.

        Args:
            config: SubAgentConfig instance

        Returns:
            Tuple of (llm_config_dict, api_key_string)
        """
        main_agent = self.subagent_manager.main_agent
        main_llm = main_agent.llm
        main_config = main_llm.config

        # Start with main agent's config as base
        llm_config_dict = main_config.model_dump()

        # Apply subagent-specific LLM overrides
        if config.llm and config.llm.has_overrides:
            overrides = config.llm
            if overrides.backend_type:
                llm_config_dict["backend_type"] = overrides.backend_type
            if overrides.model:
                llm_config_dict["model_name"] = overrides.model
            if overrides.base_url:
                llm_config_dict["base_url"] = overrides.base_url
            if overrides.context_window:
                llm_config_dict["context_window"] = overrides.context_window

        # Resolve API key
        api_key = ""
        if config.llm and config.llm.api_key:
            api_key = config.llm.api_key
        elif hasattr(main_llm, 'api_key'):
            api_key = main_llm.api_key or ""
        else:
            # Fall back to environment
            api_key = os.environ.get("OPENAI_API_KEY", "")

        return llm_config_dict, api_key

    def _build_tool_result(
        self, subagent_name: str, result
    ) -> ToolResult:
        """Build ToolResult from SubAgentResult.

        Args:
            subagent_name: Name of the subagent
            result: SubAgentResult from execution

        Returns:
            ToolResult with appropriate status
        """
        if not result:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Subagent '{subagent_name}' execution failed. Check logs for details."
            )

        if result.success:
            logger.info(
                f"Tool: Subagent '{subagent_name}' completed successfully "
                f"({result.execution_time:.2f}s, {len(result.tool_calls)} tools)"
            )
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=result.output,
                metadata={
                    "subagent": result.subagent_name,
                    "execution_time": result.execution_time,
                    "tools_used": len(result.tool_calls),
                    "tool_calls": [
                        {
                            "tool": tc.get("tool") if isinstance(tc, dict) else tc,
                            "success": tc.get("success") if isinstance(tc, dict) else True,
                        }
                        for tc in result.tool_calls
                    ]
                }
            )
        else:
            logger.error(f"Tool: Subagent '{subagent_name}' failed: {result.error}")
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=result.error or f"Subagent '{subagent_name}' execution failed"
            )

    def _get_parameters(self) -> Dict[str, Any]:
        """Get tool parameters schema."""
        return {
            "type": "object",
            "properties": {
                "subagent": {
                    "type": "string",
                    "description": "Name of the subagent to use (e.g., 'code-reviewer', 'test-writer', 'doc-writer')"
                },
                "task": {
                    "type": "string",
                    "description": "Clear, detailed description of the task to delegate to the subagent"
                }
            },
            "required": ["subagent", "task"]
        }
