# Hook Examples

This directory contains example hook implementations demonstrating common use cases for the AI Coding Agent hooks system.

## What are Hooks?

Hooks are custom Python functions that extend the agent's behavior without modifying core code. They can:
- Validate operations before execution
- Transform inputs and outputs
- Create audit trails
- Automate workflows
- Enforce policies and quotas

## Quick Start

1. **Choose an example** from this directory
2. **Copy to `.clarity/hooks.py`** in your project root:
   ```bash
   cp .clarity/examples/validation.py .clarity/hooks.py
   ```
3. **Customize** the hook functions for your needs
4. **Use the agent** - hooks will be loaded automatically!

## Available Examples

### 1. validation.py - Input Validation
**Use Case:** Prevent dangerous operations, enforce safety policies

**Features:**
- Block writes to critical files
- Deny operations outside project directory
- Validate shell commands
- Detect prompt injection attempts

**Example:**
```python
# Blocks dangerous commands like 'rm -rf /'
# Denies writes outside project directory
# Prevents prompt injection
```

### 2. backup.py - Automatic Backups
**Use Case:** Never lose work, maintain file history

**Features:**
- Timestamped backups before file modifications
- Organized in `.backups/` directory
- Automatic cleanup of old backups (keeps last 10)
- Works with write_file and edit_file operations

**Example:**
```python
# Creates: .backups/api.py.2025-10-18_143022.bak
# Cleanup on session end keeps only recent backups
```

### 3. audit.py - Audit Logging
**Use Case:** Compliance, debugging, understanding agent behavior

**Features:**
- Comprehensive JSONL audit trail
- Logs all tool calls with timestamps
- Session tracking and statistics
- Easy to parse and analyze

**Example:**
```python
# Creates: .opencodeagent/audit.jsonl
# Each line is a JSON event:
# {"timestamp": "2025-10-18T14:30:22", "event_type": "tool_call_start", ...}
```

**Reading logs:**
```python
import json

# Read all events
with open('.opencodeagent/audit.jsonl', 'r') as f:
    for line in f:
        event = json.loads(line)
        print(f"{event['timestamp']} - {event['event_type']}")

# Filter by session
session_events = [
    json.loads(line) for line in open('.opencodeagent/audit.jsonl')
    if json.loads(line).get('session_id') == 'your-session-id'
]
```

### 4. git_auto_commit.py - Git Auto-Commit
**Use Case:** Maintain detailed commit history of AI changes

**Features:**
- Two strategies: per-file or per-session
- Detailed commit messages with file lists
- Includes session metadata
- Safe: doesn't fail if git not available

**Example:**
```bash
# Strategy 1 (recommended): Commit all at session end
# Creates one commit with all changes

# Strategy 2: Commit after each file
# Very granular history
```

**Commit message format:**
```
AI Agent Session - 2025-10-18 14:30:22

Modified 3 file(s):
  - src/api.py
  - src/models.py
  - tests/test_api.py

Session ID: abc-123
Duration: 45.2s
Exit Reason: normal

Auto-committed by AI Coding Agent hooks system.
```

### 5. rate_limiting.py - Rate Limiting
**Use Case:** Prevent runaway operations, enforce quotas

**Features:**
- Simple window-based rate limiting
- Advanced token bucket algorithm
- Per-tool rate limits
- Helpful error messages with wait times

**Example:**
```python
# Simple: 20 write operations per minute
# Advanced: Burst of 10, sustained 30/minute
```

## Hook Events

Your hooks can respond to these events:

| Event | When | Use For |
|-------|------|---------|
| **PreToolUse** | Before tool execution | Validation, blocking, argument modification |
| **PostToolUse** | After tool execution | Logging, backups, result modification |
| **UserPromptSubmit** | User sends prompt | Filtering, sanitization, blocking |
| **SessionStart** | Agent initializes | Setup, logging, initialization |
| **SessionEnd** | Agent shutdown | Cleanup, final commits, statistics |
| **Notification** | Approval request | Custom approval logic |
| **PreCompact** | Before context compaction | Save state before compression |
| **Stop** | After each response | Post-processing, analytics |
| **SubagentStop** | Subagent completes | Coordinate multi-agent workflows |

## Hook Patterns

### Pattern Matching

```python
HOOKS = {
    'PreToolUse:write_file': [my_hook],      # Specific tool
    'PreToolUse:*': [my_hook],               # All tools
    'SessionStart': [my_hook],               # Session event
}
```

### Decision Types

```python
from src.hooks import HookResult, HookDecision, HookContinue

# For PreToolUse:
HookResult(decision=HookDecision.PERMIT)   # Allow
HookResult(decision=HookDecision.DENY)     # Deny with error
HookResult(decision=HookDecision.BLOCK)    # Deny with exception

# For UserPromptSubmit:
HookResult(decision=HookContinue.CONTINUE)  # Allow
HookResult(decision=HookContinue.BLOCK)     # Block

# For Notification:
HookResult(decision=HookApproval.APPROVE)   # Approve
HookResult(decision=HookApproval.DENY)      # Deny
```

### Modifying Arguments

```python
def modify_path_hook(context):
    """Rewrite paths to use absolute paths."""
    file_path = context.arguments.get('file_path', '')
    absolute_path = os.path.abspath(file_path)

    return HookResult(
        decision=HookDecision.PERMIT,
        modified_arguments={'file_path': absolute_path}
    )
```

### Modifying Results

```python
def sanitize_output_hook(context):
    """Remove sensitive data from tool output."""
    result = context.result

    if isinstance(result, str):
        # Remove API keys, passwords, etc.
        sanitized = remove_sensitive_data(result)
        return HookResult(modified_result=sanitized)

    return HookResult()
```

## Combining Hooks

You can combine multiple examples:

```python
# .clarity/hooks.py
from .examples.validation import validate_write_operations, validate_command_execution
from .examples.backup import backup_before_write
from .examples.audit import audit_tool_call, audit_tool_result

HOOKS = {
    'PreToolUse:write_file': [
        validate_write_operations,  # Validate first
        backup_before_write,        # Then backup
        audit_tool_call,            # Then log
    ],
    'PreToolUse:run_command': [validate_command_execution, audit_tool_call],
    'PostToolUse:*': [audit_tool_result],
}
```

## Performance

Hooks are **in-process Python functions** - very fast!

- **< 1ms overhead per hook** (100x faster than subprocess approach)
- Direct function calls (no serialization)
- Synchronous execution (no async complexity)
- Maintains agent's "10x faster" advantage

## Error Handling

Hooks are designed to **never crash the agent**:

```python
# Hook errors are logged and execution continues
try:
    result = hook_func(context)
except Exception as e:
    logger.warning(f"Hook error: {e}")
    # Execution continues normally
```

## Best Practices

1. **Keep hooks fast** - They run on every tool call
2. **Handle errors gracefully** - Return HookResult even on failure
3. **Use metadata** - Pass debugging info via metadata dict
4. **Log important events** - Use Python logging for diagnostics
5. **Test hooks** - Write unit tests for complex hook logic
6. **Document policies** - Explain why rules exist

## Advanced Examples

### Multi-Hook Coordination

```python
# State shared between hooks
shared_state = {'files_modified': set()}

def track_modifications(context):
    if context.success:
        file_path = context.arguments.get('file_path')
        shared_state['files_modified'].add(file_path)
    return HookResult()

def commit_on_session_end(context):
    files = shared_state['files_modified']
    # Commit all tracked files
    return HookResult()
```

### Conditional Hook Execution

```python
def smart_backup(context):
    """Only backup important files."""
    file_path = context.arguments.get('file_path', '')

    # Skip backups for temporary files
    if file_path.endswith('.tmp') or '/tmp/' in file_path:
        return HookResult(decision=HookDecision.PERMIT)

    # Backup important files
    return backup_file(file_path)
```

### Dynamic Policy Loading

```python
import yaml

def load_policy():
    """Load policy from YAML file."""
    with open('.clarity/policy.yaml', 'r') as f:
        return yaml.safe_load(f)

policy = load_policy()

def enforce_policy(context):
    """Enforce loaded policy."""
    tool = context.tool

    if tool in policy.get('blocked_tools', []):
        return HookResult(decision=HookDecision.DENY)

    return HookResult(decision=HookDecision.PERMIT)
```

## Troubleshooting

**Hooks not loading?**
- Check file location: `.clarity/hooks.py` in project root
- Verify `HOOKS = {...}` dictionary exists
- Check Python syntax errors

**Hook errors?**
- Check logs for warnings
- Ensure hook functions return HookResult
- Verify correct context attributes

**Performance issues?**
- Profile hook functions
- Avoid expensive operations in PreToolUse
- Use PostToolUse for heavy processing

## More Information

- **Architecture:** See `HOOKS_ARCHITECTURE_INPROCESS.md`
- **API Reference:** See `src/hooks/` source code
- **Tests:** See `tests/hooks/` for examples

## Contributing

Have a useful hook example? Share it!

1. Create a new example file
2. Document it in this README
3. Add tests if complex
4. Submit a pull request

## License

Same as main project (see LICENSE file).
