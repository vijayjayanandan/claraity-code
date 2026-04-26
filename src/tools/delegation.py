"""Subagent delegation tool for LLM tool calling interface.

Uses async execution (TUI): execute_async() launches subprocess, reads JSON-line events.
The sync execute() exists only to satisfy the abstract base class.
"""

import asyncio
import json
import os
import sys
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from src.observability import get_logger

if TYPE_CHECKING:
    from src.subagents import SubAgentManager
    from src.subagents.ipc import ApprovalResponse

from .base import Tool, ToolResult, ToolStatus

logger = get_logger("tools.delegation")

# ClarAIty project root (where our src/ package lives).
# Used as subprocess cwd to prevent namespace collisions when the target
# project also has a src/ package (e.g., target's src/llm/ shadowing ours).
_AGENT_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)

# Maximum nesting depth for delegations (prevents infinite recursion)
MAX_DELEGATION_DEPTH = 2


class DelegateToSubagentTool(Tool):
    """Tool for delegating tasks to specialized subagents.

    Enables the LLM to invoke subagents for specialized tasks like code review,
    test writing, or documentation. Subagents operate with independent context
    windows, preventing pollution of the main conversation.

    Uses execute_async() to launch a subprocess so the event loop stays unblocked.
    """

    def __init__(self, subagent_manager: "SubAgentManager"):
        """Initialize delegation tool.

        Args:
            subagent_manager: SubAgentManager instance from main agent
        """
        self.subagent_manager = subagent_manager
        self._registry = None  # SubagentRegistry for TUI visibility
        self._ui_protocol = None  # UIProtocol for TUI approval relay
        self._trace = None  # TraceIntegration for subagent bookend events

        # Generate dynamic description with available subagents
        description = self._generate_description()

        super().__init__(name="delegate_to_subagent", description=description)

    def set_registry(self, registry) -> None:
        """Wire up SubagentRegistry for TUI visibility.

        Called by app.py during _setup_subagent_registry().
        """
        self._registry = registry
        logger.info("DelegateToSubagentTool: Registry wired")

    def set_ui_protocol(self, protocol) -> None:
        """Wire up UIProtocol for relaying subagent approval requests to TUI.

        Called by app.py during _setup_subagent_registry().
        """
        self._ui_protocol = protocol
        logger.info("DelegateToSubagentTool: UIProtocol wired")

    def set_trace(self, trace) -> None:
        """Wire up TraceIntegration for emitting subagent bookend events.

        Called alongside set_registry/set_ui_protocol during wiring.
        """
        self._trace = trace
        logger.info("DelegateToSubagentTool: Trace wired")

    def refresh_description(self) -> None:
        """Regenerate and apply the tool description from current subagent configs.

        Call this after subagents are added, removed, or reloaded so the LLM
        sees the up-to-date list on the next API call. The LLM backends read
        tool.description fresh on every request, so assigning here is sufficient.
        """
        self.description = self._generate_description()
        logger.info("DelegateToSubagentTool: description refreshed")

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

    def execute(self, **kwargs: Any) -> ToolResult:
        """Sync stub — delegation always runs via execute_async()."""
        return ToolResult(
            tool_name=self.name,
            status=ToolStatus.ERROR,
            output=None,
            error="delegate_to_subagent requires async execution (TUI mode).",
        )

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
            IPCEventType,
            SubprocessInput,
            deserialize_notification,
            deserialize_result,
        )

        parent_tool_call_id = kwargs.pop("_tool_call_id", "")
        logger.info(f"Tool [async]: Delegating to subagent '{subagent}': {task[:100]}...")

        # Check delegation depth limit (prevents infinite recursion)
        current_depth = getattr(self, "_delegation_depth", 0)
        if current_depth >= MAX_DELEGATION_DEPTH:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Delegation depth limit ({MAX_DELEGATION_DEPTH}) exceeded. Cannot delegate further.",
            )

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
                error=f"Subagent '{subagent}' not found. Available: {', '.join(available)}",
            )

        # Resolve LLM config and API key for the subprocess
        llm_config_dict, api_key = self._resolve_llm_config(config)

        # Determine working directory — MUST be absolute.
        # main_agent.working_directory is often Path(".") which is relative.
        # The subprocess starts with cwd=_AGENT_PROJECT_ROOT (for correct imports),
        # so a relative "." would resolve to the wrong directory in the subprocess.
        working_dir = getattr(self.subagent_manager.main_agent, "working_directory", Path.cwd())
        working_directory = str(Path(working_dir).resolve())

        # Build subprocess input
        session_id = str(uuid.uuid4())[:8]
        # transcript_path must also be absolute — after os.chdir in the subprocess
        # switches to the target project, a relative path would resolve there instead
        # of in the agent's own .claraity directory.
        transcript_path = str(
            Path(working_directory)
            / ".claraity"
            / "sessions"
            / "subagents"
            / f"{config.name}-{session_id}.jsonl"
        )

        # Resolve permission mode and auto-approve set from parent agent
        main_agent = self.subagent_manager.main_agent
        permission_mode = "normal"
        if hasattr(main_agent, "permission_manager") and main_agent.permission_manager:
            permission_mode = main_agent.permission_manager.get_mode().value
        # Don't forward parent's auto-approve to subagents (principle of least privilege)
        auto_approve_tools = []  # Subagents start with no auto-approvals

        # Resolve subagent budgets from main agent's limits config.
        web_search_limit = 2
        web_fetch_limit = 3
        iteration_limit_enabled = True
        max_iterations = 50
        main_agent = self.subagent_manager.main_agent
        if hasattr(main_agent, "get_limits"):
            limits = main_agent.get_limits()
            web_search_limit = limits.get("web_subagent_search_limit", 2)
            web_fetch_limit = limits.get("web_subagent_fetch_limit", 3)
            iteration_limit_enabled = limits.get("iteration_limit_enabled", True)
            max_iterations = limits.get("max_iterations", 50)

        # When iteration limit is disabled, use a high safety-net value.
        # SubAgent checks `iteration >= max_iterations` so 0 would trigger
        # immediately — use 200 (same as MAX_TOOL_CALLS safety cap).
        effective_max_iterations = max_iterations if iteration_limit_enabled else 200

        # Subagent trace file path (parallel to transcript, different extension)
        subagent_trace_path = str(Path(transcript_path).with_suffix(".trace.jsonl"))

        # Determine if trace is enabled on the parent
        trace_enabled = self._trace and self._trace.enabled

        subprocess_input = SubprocessInput(
            config=asdict(config),
            llm_config=llm_config_dict,
            api_key=api_key,
            task_description=task.strip(),
            working_directory=working_directory,
            max_iterations=effective_max_iterations,
            max_wall_time=None,
            transcript_path=transcript_path,
            permission_mode=permission_mode,
            auto_approve_tools=auto_approve_tools,
            delegation_depth=current_depth + 1,
            web_search_limit=web_search_limit,
            web_fetch_limit=web_fetch_limit,
            iteration_limit_enabled=iteration_limit_enabled,
            trace_enabled=trace_enabled,
        )

        # Launch subprocess
        input_json = subprocess_input.to_json()

        # Build subprocess command. In a PyInstaller bundle sys.executable
        # is the .exe itself, so we use `--subagent` flag handled by __main__.py.
        # In normal Python we use the standard `-m src.subagents.runner`.
        if getattr(sys, "_MEIPASS", None):
            # Bundled binary
            cmd = [sys.executable, "--subagent"]
        else:
            # Normal Python
            cmd = [sys.executable, "-m", "src.subagents.runner"]

        # Emit trace bookend: subagent starting
        if self._trace:
            self._trace.on_subagent_start(subagent, task.strip(), subagent_trace_path)

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=_AGENT_PROJECT_ROOT,
            # Default asyncio StreamReader limit is 64KB per line.
            # Subagent DONE events with large outputs (code reviews, etc.)
            # can easily exceed that as a single JSON line. 16MB is generous.
            limit=16 * 1024 * 1024,
        )

        # Send input (keep stdin open for approval responses)
        process.stdin.write(input_json.encode("utf-8") + b"\n")
        await process.stdin.drain()

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
        sa_execution_time = 0.0
        sa_success = False

        try:
            async for line in process.stdout:
                # Check for interrupt between lines — allows the Stop button
                # to terminate the subagent without waiting for it to finish
                if self._ui_protocol and self._ui_protocol.check_interrupted():
                    logger.info(
                        "Tool [async]: Interrupt detected — terminating subagent subprocess"
                    )
                    if process.returncode is None:
                        process.terminate()
                    result = ToolResult(
                        tool_name=self.name,
                        status=ToolStatus.ERROR,
                        output=None,
                        error="Subagent interrupted by user",
                    )
                    break

                line_str = line.decode("utf-8").strip()
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
                    context_window = event.get("context_window", 0)
                    # Register with TUI registry for SubAgentCard
                    if self._registry and parent_tool_call_id:
                        self._registry.register(
                            subagent_id=subagent_id,
                            store=None,  # No shared store in subprocess mode
                            transcript_path=Path(transcript_path),
                            parent_tool_call_id=parent_tool_call_id,
                            instance=process,  # asyncio.Process for cancel
                            model_name=model_name,
                            subagent_name=subagent,  # Pass subagent type (knowledge-builder, planner, etc.)
                            context_window=context_window,
                        )

                elif event_type == IPCEventType.NOTIFICATION:
                    if subagent_id and self._registry:
                        try:
                            notification = deserialize_notification(event.get("notification", {}))
                            self._registry.push_notification(subagent_id, notification)
                        except Exception as e:
                            logger.error(f"Failed to deserialize notification: {e}")

                elif event_type == IPCEventType.APPROVAL_REQUEST:
                    await self._handle_approval_request(event, process, subagent_id)

                elif event_type == IPCEventType.DONE:
                    result_data = event.get("result", {})
                    sa_result = deserialize_result(result_data)
                    sa_execution_time = sa_result.execution_time
                    sa_success = sa_result.success
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
            # Emit trace bookend: subagent finished
            if self._trace:
                self._trace.on_subagent_end(
                    subagent,
                    subagent_trace_path,
                    sa_success,
                    sa_execution_time,
                )

            # Close stdin (signals EOF to child if still waiting for approval)
            if not process.stdin.is_closing():
                process.stdin.close()
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
            stderr_output = b"".join(stderr_chunks).decode("utf-8", errors="replace")
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

    async def _handle_approval_request(
        self,
        event: dict,
        process: asyncio.subprocess.Process,
        subagent_id: str,
    ) -> None:
        """Relay an APPROVAL_REQUEST from subprocess to TUI, send response back.

        Dispatches on request_type:
        - "tool_approval": shows ToolApprovalOptions, returns approved/feedback
        - "clarify": shows ClarifyWidget, returns structured answers
        """
        from src.subagents.ipc import ApprovalRequest, ApprovalResponse

        request = ApprovalRequest.from_dict(event.get("request", {}))
        call_id = request.tool_call_id

        if request.request_type == "pause":
            response = await self._handle_pause_request(request)
        elif request.request_type == "clarify":
            response = await self._handle_clarify_request(request)
        else:
            response = await self._handle_tool_approval(request)

        try:
            process.stdin.write(response.to_json_line().encode("utf-8") + b"\n")
            await process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            logger.warning("Subprocess stdin closed before response could be sent")

    async def _handle_tool_approval(self, request) -> "ApprovalResponse":
        """Handle tool_approval request type."""
        from src.subagents.ipc import ApprovalResponse

        approved = True
        feedback = None
        auto_approve_future = False

        if self._ui_protocol:
            result = await self._ui_protocol.wait_for_approval(
                request.tool_call_id, request.tool_name, timeout=None
            )
            approved = result.approved
            feedback = result.feedback
            auto_approve_future = result.auto_approve_future
        else:
            logger.warning("No UIProtocol - auto-approving subagent tool call")

        return ApprovalResponse(
            tool_call_id=request.tool_call_id,
            approved=approved,
            auto_approve_future=auto_approve_future,
            feedback=feedback,
        )

    async def _handle_clarify_request(self, request) -> "ApprovalResponse":
        """Handle clarify request type."""
        from src.subagents.ipc import ApprovalResponse

        clarify_result = {"cancelled": True}

        if self._ui_protocol:
            # Send clarify form to client (stdio server only -- TUI uses SubAgentCard)
            if hasattr(self._ui_protocol, "send_clarify_request"):
                await self._ui_protocol.send_clarify_request(
                    call_id=request.tool_call_id,
                    questions=request.questions,
                    context=request.context,
                )
            result = await self._ui_protocol.wait_for_clarify_response(
                request.tool_call_id, timeout=None
            )
            if result.submitted:
                clarify_result = {"submitted": True, "responses": result.responses}
            elif result.chat_instead:
                clarify_result = {"mode": "chat", "message": result.chat_message}
            else:
                clarify_result = {"cancelled": True}
        else:
            logger.warning("No UIProtocol - returning cancelled for subagent clarify")

        return ApprovalResponse(
            tool_call_id=request.tool_call_id,
            approved=True,
            clarify_result=clarify_result,
        )

    async def _handle_pause_request(self, request) -> "ApprovalResponse":
        """Handle pause request type - relay to TUI PausePromptWidget."""
        from src.subagents.ipc import ApprovalResponse

        continue_work = False
        feedback = None

        if self._ui_protocol:
            pause_result = await self._ui_protocol.request_pause(
                reason=request.pause_reason or "Subagent limit reached",
                reason_code=request.pause_reason_code or "unknown",
                stats=request.pause_stats or {},
            )
            continue_work = pause_result.continue_work
            feedback = pause_result.feedback
            # Always clear the interrupt flag once the pause is resolved.
            # The flag was set by request_pause() for the subagent's prompt —
            # leaving it set would cause the parent agent to think *it* was
            # interrupted on its next iteration.
            self._ui_protocol.clear_interrupt()
        else:
            logger.warning("No UIProtocol - auto-stopping subagent pause")

        return ApprovalResponse(
            tool_call_id=request.tool_call_id,
            approved=continue_work,
            feedback=feedback,
        )

    def _validate_inputs(self, subagent: str, task: str) -> ToolResult | None:
        """Validate subagent and task inputs.

        Returns ToolResult error if invalid, None if valid.
        """
        if not subagent or not subagent.strip():
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error="Subagent name is required and cannot be empty",
            )

        if not task or not task.strip():
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error="Task description is required and cannot be empty",
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
        elif hasattr(main_llm, "api_key"):
            api_key = main_llm.api_key or ""
        else:
            # Fall back to environment
            api_key = os.environ.get("CLARAITY_API_KEY", "")

        return llm_config_dict, api_key

    def _build_tool_result(self, subagent_name: str, result) -> ToolResult:
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
                error=f"Subagent '{subagent_name}' execution failed. Check logs for details.",
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
                    ],
                },
            )
        else:
            logger.error(f"Tool: Subagent '{subagent_name}' failed: {result.error}")
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=result.error or f"Subagent '{subagent_name}' execution failed",
            )

    _SCHEMA_NAME = "delegate_to_subagent"

    def _get_parameters(self) -> dict[str, Any]:
        """Delegate to tool_schemas for parameter schema.

        Note: description is intentionally NOT pulled from _SCHEMA_REGISTRY here --
        DelegateToSubagentTool uses a dynamic description generated by
        _generate_description() at __init__ time to list available subagents.
        Only the parameters (subagent, task) are canonical and stable.
        """
        from src.tools.tool_schemas import _SCHEMA_REGISTRY

        return _SCHEMA_REGISTRY["delegate_to_subagent"].parameters
