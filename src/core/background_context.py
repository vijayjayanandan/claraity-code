"""
Background Context Injection - Injects completed task notifications into LLM context.

Follows the same pattern as inject_controller_constraint() in stream_phases.py:
appends a user-role message to the context list (mutates in-place).
"""

from typing import Any

from src.core.background_tasks import BackgroundTaskInfo, BackgroundTaskStatus

# Preview limit for stdout/stderr in the notification
OUTPUT_PREVIEW_CHARS = 500


def inject_background_task_completions(
    context: list[dict[str, Any]],
    completed_tasks: list[BackgroundTaskInfo],
) -> None:
    """Inject notifications for completed background tasks into LLM context.

    Appends a user-role message listing completed tasks with status,
    exit code, and an output preview (first 500 chars).

    No-op when the list is empty.

    Args:
        context: The LLM conversation context (mutated in-place).
        completed_tasks: list of newly-completed BackgroundTaskInfo objects.
    """
    if not completed_tasks:
        return

    parts = ["[BACKGROUND TASK UPDATE] The following background tasks have completed:\n"]

    for task in completed_tasks:
        status_label = task.status.value.upper()
        parts.append(f"--- {task.task_id}: {task.description} ---")
        parts.append(f"Status: {status_label}")
        parts.append(f"Command: {task.command}")

        if task.exit_code is not None:
            parts.append(f"Exit code: {task.exit_code}")

        if task.error:
            parts.append(f"Error: {task.error}")

        # Output preview (stdout first, then stderr if stdout is empty)
        output = task.stdout.strip() or task.stderr.strip()
        if output:
            preview = output[:OUTPUT_PREVIEW_CHARS]
            if len(output) > OUTPUT_PREVIEW_CHARS:
                preview += f"\n... ({len(output) - OUTPUT_PREVIEW_CHARS} more chars, use check_background_task for full output)"
            parts.append(f"Output preview:\n{preview}")

        parts.append("")  # blank line between tasks

    parts.append("Use check_background_task(task_id) to get the full output if needed.")

    context.append(
        {
            "role": "user",
            "content": "\n".join(parts),
        }
    )
