"""
Example Hook: Audit Logging

This hook demonstrates how to create comprehensive audit trails.
It logs all tool calls, user prompts, and session events to a JSON log file.

Usage:
    Copy this file to .claude/hooks.py to enable audit logging.
    Logs are written to .opencodeagent/audit.jsonl (JSONL format for easy parsing)
"""

from src.hooks import HookResult, HookDecision
from datetime import datetime
from pathlib import Path
import json


def get_audit_log_path():
    """Get path to audit log file."""
    log_dir = Path('.opencodeagent')
    log_dir.mkdir(exist_ok=True)
    return log_dir / 'audit.jsonl'


def log_audit_event(event_type, event_data):
    """Write audit event to log file."""
    try:
        log_path = get_audit_log_path()

        audit_entry = {
            'timestamp': datetime.now().isoformat(),
            'event_type': event_type,
            **event_data
        }

        # Append to JSONL file (one JSON object per line)
        with open(log_path, 'a') as f:
            f.write(json.dumps(audit_entry) + '\n')

    except Exception as e:
        # Never fail the operation due to logging errors
        print(f"Audit log error: {e}")


def audit_session_start(context):
    """Log session start."""
    log_audit_event('session_start', {
        'session_id': context.session_id,
        'model_name': context.model_name,
        'working_directory': context.working_directory,
        'config': context.config
    })
    return HookResult()


def audit_user_prompt(context):
    """Log user prompts (sanitized for privacy)."""
    # Sanitize: Remove potential sensitive data
    prompt = context.prompt
    if len(prompt) > 1000:
        prompt = prompt[:1000] + '... (truncated)'

    log_audit_event('user_prompt', {
        'session_id': context.session_id,
        'prompt_length': len(context.prompt),
        'prompt_preview': prompt[:200],  # First 200 chars
        'metadata': context.metadata
    })

    return HookResult(decision=HookDecision.CONTINUE)


def audit_tool_call(context):
    """Log tool calls before execution."""
    log_audit_event('tool_call_start', {
        'session_id': context.session_id,
        'tool': context.tool,
        'arguments': context.arguments,
        'step_id': context.step_id
    })

    return HookResult(decision=HookDecision.PERMIT)


def audit_tool_result(context):
    """Log tool results after execution."""
    # Sanitize output (don't log full file contents)
    result_preview = str(context.result)[:500] if context.result else None

    log_audit_event('tool_call_end', {
        'session_id': context.session_id,
        'tool': context.tool,
        'success': context.success,
        'duration': context.duration,
        'result_preview': result_preview,
        'error': context.error
    })

    return HookResult()


def audit_session_end(context):
    """Log session end with statistics."""
    log_audit_event('session_end', {
        'session_id': context.session_id,
        'duration': context.duration,
        'statistics': context.statistics,
        'exit_reason': context.exit_reason
    })

    # Print summary
    log_path = get_audit_log_path()
    print(f"\nAudit log written to: {log_path}")

    # Count events in this session
    try:
        session_events = 0
        with open(log_path, 'r') as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    if entry.get('session_id') == context.session_id:
                        session_events += 1
                except:
                    pass

        print(f"Session events logged: {session_events}")
    except Exception:
        pass

    return HookResult()


# Hook registry
HOOKS = {
    'SessionStart': [audit_session_start],
    'UserPromptSubmit': [audit_user_prompt],
    'PreToolUse:*': [audit_tool_call],  # Log all tool calls
    'PostToolUse:*': [audit_tool_result],
    'SessionEnd': [audit_session_end],
}


# Example: How to read audit logs
"""
# Read audit logs
import json

log_path = '.opencodeagent/audit.jsonl'
with open(log_path, 'r') as f:
    for line in f:
        entry = json.loads(line)
        print(f"{entry['timestamp']} - {entry['event_type']}")

# Filter by session ID
session_id = 'abc-123'
with open(log_path, 'r') as f:
    session_events = [json.loads(line) for line in f
                      if json.loads(line).get('session_id') == session_id]

# Count events by type
from collections import Counter
with open(log_path, 'r') as f:
    events = [json.loads(line) for line in f]
    counts = Counter(e['event_type'] for e in events)
    print(counts)
"""
