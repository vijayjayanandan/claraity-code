"""
Example Hook: Input Validation

This hook demonstrates how to validate tool calls before execution.
It can be used to prevent dangerous operations or enforce safety policies.

Usage:
    Copy this file to .claude/hooks.py and customize the validation rules.
"""

from src.hooks import HookResult, HookDecision
from pathlib import Path


def validate_write_operations(context):
    """
    Validate write operations to prevent accidental overwrites.

    Example policy:
    - Block writes to critical system files
    - Deny writes outside project directory
    - Warn about large file writes
    """
    file_path = context.arguments.get('file_path', '')

    # Block writes to critical files
    critical_files = [
        '/etc/passwd', '/etc/shadow', '/etc/hosts',
        'pyproject.toml', 'package.json', 'Cargo.toml'
    ]

    if any(file_path.endswith(critical) for critical in critical_files):
        return HookResult(
            decision=HookDecision.DENY,
            message=f"Blocked write to critical file: {file_path}"
        )

    # Deny writes outside project directory
    try:
        path = Path(file_path).resolve()
        project_root = Path.cwd().resolve()

        if not str(path).startswith(str(project_root)):
            return HookResult(
                decision=HookDecision.DENY,
                message=f"Write outside project directory denied: {file_path}"
            )
    except Exception:
        pass  # Allow if path resolution fails

    # Check file size for large writes
    content = context.arguments.get('content', '')
    if len(content) > 100000:  # 100KB
        return HookResult(
            decision=HookDecision.PERMIT,
            message=f"Warning: Large file write ({len(content)} bytes)",
            metadata={'warning': 'large_file', 'size': len(content)}
        )

    # Allow operation
    return HookResult(decision=HookDecision.PERMIT)


def validate_command_execution(context):
    """
    Validate shell commands before execution.

    Example policy:
    - Block destructive commands (rm -rf, dd, mkfs)
    - Block network commands without approval
    - Log all command executions
    """
    command = context.arguments.get('command', '')

    # Block dangerous commands
    dangerous_patterns = [
        'rm -rf /', 'dd if=', 'mkfs', '> /dev/',
        'chmod 777', 'chmod -R 777',
        ':(){ :|:& };:'  # Fork bomb
    ]

    if any(pattern in command for pattern in dangerous_patterns):
        return HookResult(
            decision=HookDecision.DENY,
            message=f"Dangerous command blocked: {command}"
        )

    # Deny network commands (examples)
    network_commands = ['curl', 'wget', 'nc', 'netcat', 'ssh']
    if any(cmd in command.split()[0] if command.split() else ''
           for cmd in network_commands):
        return HookResult(
            decision=HookDecision.DENY,
            message=f"Network command requires approval: {command}"
        )

    # Allow safe commands
    return HookResult(
        decision=HookDecision.PERMIT,
        metadata={'logged': True, 'command': command}
    )


def validate_user_prompts(context):
    """
    Validate and sanitize user prompts.

    Example policy:
    - Block prompts with potential injection attempts
    - Sanitize sensitive data in prompts
    """
    prompt = context.prompt

    # Block potential injection attempts
    injection_patterns = [
        'ignore previous instructions',
        'disregard all',
        'forget everything',
        'system prompt'
    ]

    if any(pattern in prompt.lower() for pattern in injection_patterns):
        return HookResult(
            decision=HookDecision.BLOCK,
            message="Prompt blocked: Potential injection attempt detected"
        )

    # Allow normal prompts
    return HookResult(decision=HookDecision.CONTINUE)


# Hook registry - map events to handler functions
HOOKS = {
    'PreToolUse:write_file': [validate_write_operations],
    'PreToolUse:run_command': [validate_command_execution],
    'UserPromptSubmit': [validate_user_prompts],
}
