"""Subprocess entry point for subagent execution.

Usage: python -m src.subagents.runner

Bootstrap sequence:
1. Read single JSON line from stdin -> SubprocessInput
2. Create LLMConfig + OpenAIBackend
3. Create ToolExecutor with registered tool instances
4. Create SubAgent with direct dependency injection
5. Emit "registered" event
6. Subscribe to subagent's MessageStore -> emit "notification" events
7. Execute task
8. Emit "done" event with SubAgentResult
9. Exit(0)

Stdout is exclusively for IPC events (JSON lines).
All logging goes to JSONL file via get_logger() framework.
"""

import json
import os
import signal
import sys
import traceback
from pathlib import Path

# Ensure project root is on sys.path for imports.
# Derive from module location (runner.py is at src/subagents/runner.py,
# so project root is 3 levels up). Using __file__ instead of os.getcwd()
# ensures correctness even when working_directory != project root.
_project_root = str(Path(__file__).resolve().parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from src.observability import get_logger
from src.subagents.ipc import (
    ApprovalRequest,
    IPCEventType,
    emit_event,
    read_approval_response_from_stdin,
    read_input_from_stdin,
    serialize_notification,
    serialize_result,
)

logger = get_logger("subagents.runner")


def _create_llm_backend(llm_config_dict, api_key):
    """Create an LLM backend from config dict.

    Args:
        llm_config_dict: LLMConfig fields as dict
        api_key: API key for the backend

    Returns:
        LLMBackend instance
    """
    from src.llm import LLMConfig, OpenAIBackend

    config = LLMConfig.model_validate(llm_config_dict)
    backend_type = config.backend_type

    OPENAI_COMPATIBLE = {"openai", "vllm", "localai", "llamacpp"}
    if backend_type in OPENAI_COMPATIBLE:
        return OpenAIBackend(config=config, api_key=api_key)
    elif backend_type == "anthropic":
        from src.llm.anthropic_backend import AnthropicBackend

        return AnthropicBackend(config=config, api_key=api_key)
    else:
        raise ValueError(f"Unsupported backend_type: {backend_type}")


def _create_tool_executor(tools_allowlist=None, tools_blocklist=None):
    """Create a ToolExecutor with standard tool instances.

    Registers parameterless tool constructors only. Tools requiring
    state (PlanModeState, etc.) are excluded.

    Args:
        tools_allowlist: Optional list of tool names to register.
                        If None, all standard tools are registered.
        tools_blocklist: Optional list of tool names to exclude.
                        Applied after allowlist filtering.

    Returns:
        ToolExecutor instance with registered tools
    """
    from src.tools.base import ToolExecutor
    from src.tools.registry import get_stateless_tools

    executor = ToolExecutor(hook_manager=None)

    # All standard parameterless tools (from central registry)
    all_tools = get_stateless_tools()

    # Apply allowlist filter if specified
    if tools_allowlist:
        allowed = set(tools_allowlist)
        all_tools = [t for t in all_tools if t.name in allowed]

    # Apply blocklist filter if specified
    if tools_blocklist:
        blocked = set(tools_blocklist)
        all_tools = [t for t in all_tools if t.name not in blocked]

    for tool in all_tools:
        executor.register_tool(tool)

    return executor


def _create_subagent_config(config_dict):
    """Reconstruct SubAgentConfig from dict.

    Args:
        config_dict: SubAgentConfig fields as dict

    Returns:
        SubAgentConfig instance
    """
    from src.subagents.config import SubAgentConfig, SubAgentLLMConfig

    # Reconstruct LLM config if present
    llm_config = None
    llm_data = config_dict.get("llm")
    if isinstance(llm_data, dict):
        llm_config = SubAgentLLMConfig(**llm_data)
        if not llm_config.has_overrides:
            llm_config = None

    return SubAgentConfig(
        name=config_dict["name"],
        description=config_dict["description"],
        system_prompt=config_dict["system_prompt"],
        tools=config_dict.get("tools"),
        llm=llm_config,
        config_path=Path(config_dict["config_path"]) if config_dict.get("config_path") else None,
        metadata=config_dict.get("metadata", {}),
    )


def _create_ipc_approval_callback(subagent_name, auto_approve_set):
    """Create a callback that talks to the parent via IPC for user interaction.

    Handles both tool approval and clarify requests through the same
    IPC channel (APPROVAL_REQUEST event), dispatching on tool_name.

    Args:
        subagent_name: Subagent name (shown in parent's UI)
        auto_approve_set: Mutable set of auto-approved tool names.

    Returns:
        Callable(tool_name, tool_args, tool_call_id) -> (bool, Any)
        - Tool approval: (approved, feedback_or_None)
        - Clarify: (True, result_dict)
    """

    def _callback(tool_name, tool_args, tool_call_id):
        is_clarify = tool_name == "clarify"
        args_summary = ", ".join(
            f'{k}="{v}"' if isinstance(v, str) else f"{k}={v}"
            for k, v in list(tool_args.items())[:3]
        )
        request = ApprovalRequest(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            tool_args=tool_args,
            subagent_name=subagent_name,
            args_summary=args_summary,
            request_type="clarify" if is_clarify else "tool_approval",
            questions=tool_args.get("questions") if is_clarify else None,
            context=tool_args.get("context") if is_clarify else None,
        )
        emit_event(IPCEventType.APPROVAL_REQUEST, request=request.to_dict())

        try:
            response = read_approval_response_from_stdin()
            if is_clarify:
                return (True, response.clarify_result or {"cancelled": True})
            if response.auto_approve_future and response.approved:
                auto_approve_set.add(tool_name)
            return (response.approved, response.feedback)
        except (EOFError, ValueError, json.JSONDecodeError) as e:
            logger.warning(f"IPC read failed: {e} - treating as rejection/cancel")
            if is_clarify:
                return (True, {"cancelled": True, "reason": str(e)})
            return (False, None)

    return _callback


def _create_ipc_pause_callback(subagent_name):
    """Create a callback that talks to the parent via IPC for pause decisions.

    Sends an ApprovalRequest with request_type="pause" and waits for the
    parent's ApprovalResponse. The parent relays this to the user via
    PausePromptWidget (TUI) or input() prompt (CLI).

    Args:
        subagent_name: Subagent name (shown in parent's UI)

    Returns:
        Callable(reason, reason_code, stats) -> (continue_work, feedback)
    """

    def _callback(reason, reason_code, stats):
        request = ApprovalRequest(
            tool_call_id="pause-request",
            tool_name="pause-request",
            tool_args={},
            subagent_name=subagent_name,
            args_summary=reason,
            request_type="pause",
            pause_reason=reason,
            pause_reason_code=reason_code,
            pause_stats=stats,
        )
        emit_event(IPCEventType.APPROVAL_REQUEST, request=request.to_dict())

        try:
            response = read_approval_response_from_stdin()
            return (response.approved, response.feedback)
        except (EOFError, ValueError, json.JSONDecodeError) as e:
            logger.warning(f"IPC pause read failed: {e} - treating as Stop")
            return (False, None)

    return _callback


def main():
    """Subprocess entry point.

    Reads input from stdin, bootstraps the subagent, executes the task,
    and emits results to stdout as JSON lines.
    """
    subagent = None

    try:
        # 1. Read input from stdin
        input_data = read_input_from_stdin()
        logger.info(
            f"Runner: received task for config={input_data.config.get('name', '?')}, "
            f"max_iterations={input_data.max_iterations}"
        )

        # 2. Create LLM backend
        llm = _create_llm_backend(input_data.llm_config, input_data.api_key)

        # 3. Create ToolExecutor with appropriate tools
        tools_allowlist = input_data.config.get("tools")
        # Knowledge write tools are restricted to knowledge-builder only
        subagent_name = input_data.config.get("name", "")
        if subagent_name != "knowledge-builder":
            from src.prompts.subagents import KNOWLEDGE_WRITE_TOOLS

            tools_blocklist = KNOWLEDGE_WRITE_TOOLS
        else:
            tools_blocklist = None
        tool_executor = _create_tool_executor(tools_allowlist, tools_blocklist)

        # 3b. Set workspace roots on file operation tools for path validation.
        # Without this, _workspace_roots stays None and validate_path_security
        # falls back to Path.cwd() which is fragile if any tool changes cwd.
        # Subagents inherit the parent's workspace roots if available.
        from src.tools.file_operations import FileOperationTool

        workspace_roots = getattr(input_data, "workspace_roots", None)
        if workspace_roots:
            FileOperationTool._workspace_roots = [Path(r) for r in workspace_roots]
        else:
            FileOperationTool._workspace_roots = [Path(input_data.working_directory)]

        # 3c. Switch process cwd to the target project's working directory.
        # The subprocess starts with cwd=ClarAIty root (for correct src.* imports).
        # Now that all imports are done, set cwd to the target project so tools
        # like run_command default to the correct directory.
        os.chdir(input_data.working_directory)

        # 4. Reconstruct SubAgentConfig
        config = _create_subagent_config(input_data.config)

        # 5. Create SubAgent with direct dependency injection
        # Build approval callback if permission mode requires it
        permission_mode = input_data.permission_mode
        auto_approve_set = set(input_data.auto_approve_tools)
        approval_cb = None
        if permission_mode != "auto":
            approval_cb = _create_ipc_approval_callback(config.name, auto_approve_set)

        # Only create pause callback when iteration limit is enabled.
        # When disabled, subagent runs to completion (pause_callback=None
        # triggers auto-summarize in SubAgent as a safety fallback).
        pause_cb = None
        if input_data.iteration_limit_enabled:
            pause_cb = _create_ipc_pause_callback(config.name)

        # Resolve max_wall_time from input (None disables wall-clock limit)
        max_wall_time = input_data.max_wall_time

        from src.subagents.subagent import SubAgent

        subagent = SubAgent(
            config=config,
            llm=llm,
            tool_executor=tool_executor,
            working_directory=input_data.working_directory,
            transcript_dir=Path(input_data.transcript_path).parent
            if input_data.transcript_path
            else None,
            permission_mode=permission_mode,
            approval_callback=approval_cb,
            auto_approve_tools=auto_approve_set,
            pause_callback=pause_cb,
            max_wall_time=max_wall_time,
        )

        # 5b. Wire trace integration if enabled
        if input_data.trace_enabled:
            from src.core.trace_integration import TraceIntegration

            trace = TraceIntegration(enabled=True)
            # Derive trace session ID from transcript filename stem
            # e.g., "code-reviewer-abc12345" from the transcript path
            trace_session_id = Path(input_data.transcript_path).stem
            trace_sessions_dir = Path(input_data.transcript_path).parent
            trace.init_session(trace_session_id, trace_sessions_dir)
            subagent.set_trace(trace)
            logger.info(f"Runner: Trace enabled (session={trace_session_id})")

        # 6. Set up cancellation signal handler
        def _on_sigterm(signum, frame):
            logger.info("Runner: SIGTERM received, cancelling subagent")
            if subagent:
                subagent.cancel()

        signal.signal(signal.SIGTERM, _on_sigterm)
        # On Windows, also handle SIGBREAK if available
        if hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, _on_sigterm)

        # 7. Emit "registered" event
        emit_event(
            IPCEventType.REGISTERED,
            subagent_id=subagent.session_id,
            model_name=llm.config.model_name,
            context_window=llm.config.context_window,
        )

        # 8. Subscribe to subagent's MessageStore -> emit notifications
        def _on_notification(notification):
            try:
                serialized = serialize_notification(notification)
                emit_event(
                    IPCEventType.NOTIFICATION,
                    subagent_id=subagent.session_id,
                    notification=serialized,
                )
            except Exception as e:
                logger.error(f"Runner: Failed to serialize notification: {e}")

        unsub = subagent._message_store.subscribe(_on_notification)

        # 9. Execute the task
        try:
            result = subagent.execute(
                task_description=input_data.task_description,
                max_iterations=input_data.max_iterations,
            )
        finally:
            unsub()

        # 10. Emit "done" event
        emit_event(
            IPCEventType.DONE,
            result=serialize_result(result),
        )

        logger.info(
            f"Runner: task completed (success={result.success}, time={result.execution_time:.2f}s)"
        )
        sys.exit(0)

    except Exception as e:
        # Emit error event and exit (sanitize traceback to avoid leaking secrets)
        error_msg = traceback.format_exc()
        logger.error(f"Runner: fatal error: {error_msg}")
        # Redact potential API keys from traceback before sending over IPC
        import re

        sanitized = re.sub(
            r"(sk-[a-zA-Z0-9]{2})[a-zA-Z0-9-]+",
            r"\1***REDACTED***",
            error_msg,
        )
        emit_event(
            IPCEventType.ERROR,
            error=str(e),
            traceback=sanitized,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
