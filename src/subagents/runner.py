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

import os
import sys
import signal
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
    IPCEventType,
    emit_event,
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
    from src.llm import LLMConfig, OpenAIBackend, OllamaBackend

    config = LLMConfig.model_validate(llm_config_dict)
    backend_type = config.backend_type

    OPENAI_COMPATIBLE = {"openai", "vllm", "localai", "llamacpp"}
    if backend_type in OPENAI_COMPATIBLE:
        return OpenAIBackend(config=config, api_key=api_key)
    elif backend_type == "ollama":
        return OllamaBackend(config=config)
    else:
        raise ValueError(f"Unsupported backend_type: {backend_type}")


def _create_tool_executor(tools_allowlist=None):
    """Create a ToolExecutor with standard tool instances.

    Registers parameterless tool constructors only. Tools requiring
    state (TaskState, PlanModeState, etc.) are excluded.

    Args:
        tools_allowlist: Optional list of tool names to register.
                        If None, all standard tools are registered.

    Returns:
        ToolExecutor instance with registered tools
    """
    from src.tools.base import ToolExecutor
    from src.tools.file_operations import (
        ReadFileTool, WriteFileTool, EditFileTool,
        AppendToFileTool, ListDirectoryTool, RunCommandTool,
    )
    from src.tools.code_search import SearchCodeTool, AnalyzeCodeTool
    from src.tools.search_tools import GrepTool, GlobTool
    from src.tools.git_operations import GitStatusTool, GitDiffTool, GitCommitTool
    from src.tools.lsp_tools import GetFileOutlineTool, GetSymbolContextTool

    executor = ToolExecutor(hook_manager=None)

    # All standard parameterless tools
    all_tools = [
        ReadFileTool(),
        WriteFileTool(),
        EditFileTool(),
        AppendToFileTool(),
        ListDirectoryTool(),
        SearchCodeTool(),
        AnalyzeCodeTool(),
        GrepTool(),
        GlobTool(),
        RunCommandTool(),
        GitStatusTool(),
        GitDiffTool(),
        GitCommitTool(),
        GetFileOutlineTool(),
        GetSymbolContextTool(),
    ]

    # Apply allowlist filter if specified
    if tools_allowlist:
        allowed = set(tools_allowlist)
        all_tools = [t for t in all_tools if t.name in allowed]

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
        tool_executor = _create_tool_executor(tools_allowlist)

        # 3b. Set workspace root on file operation tools for path validation
        # Without this, _workspace_root stays None and validate_path_security
        # falls back to Path.cwd() which is fragile if any tool changes cwd.
        from src.tools.file_operations import FileOperationTool
        FileOperationTool._workspace_root = Path(input_data.working_directory)

        # 4. Reconstruct SubAgentConfig
        config = _create_subagent_config(input_data.config)

        # 5. Create SubAgent with direct dependency injection
        from src.subagents.subagent import SubAgent
        subagent = SubAgent(
            config=config,
            llm=llm,
            tool_executor=tool_executor,
            working_directory=input_data.working_directory,
            transcript_dir=Path(input_data.transcript_path).parent if input_data.transcript_path else None,
        )

        # 6. Set up cancellation signal handler
        def _on_sigterm(signum, frame):
            logger.info("Runner: SIGTERM received, cancelling subagent")
            if subagent:
                subagent.cancel()

        signal.signal(signal.SIGTERM, _on_sigterm)
        # On Windows, also handle SIGBREAK if available
        if hasattr(signal, 'SIGBREAK'):
            signal.signal(signal.SIGBREAK, _on_sigterm)

        # 7. Emit "registered" event
        emit_event(
            IPCEventType.REGISTERED,
            subagent_id=subagent.session_id,
            model_name=llm.config.model_name,
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
            f"Runner: task completed (success={result.success}, "
            f"time={result.execution_time:.2f}s)"
        )
        sys.exit(0)

    except Exception as e:
        # Emit error event and exit (sanitize traceback to avoid leaking secrets)
        error_msg = traceback.format_exc()
        logger.error(f"Runner: fatal error: {error_msg}")
        # Redact potential API keys from traceback before sending over IPC
        import re
        sanitized = re.sub(
            r'(sk-[a-zA-Z0-9]{2})[a-zA-Z0-9-]+',
            r'\1***REDACTED***',
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
