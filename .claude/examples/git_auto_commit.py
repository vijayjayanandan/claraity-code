"""
Example Hook: Git Auto-Commit

This hook demonstrates how to automatically commit changes after successful
file modifications. It can be used to maintain a detailed commit history
of all AI-generated changes.

Usage:
    Copy this file to .claude/hooks.py to enable auto-commit.
    Requires git repository to be initialized.
"""

from src.hooks import HookResult
from pathlib import Path
import subprocess
from datetime import datetime


# Track modified files in this session
modified_files = set()


def is_git_repo():
    """Check if current directory is a git repository."""
    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--git-dir'],
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False


def track_file_modification(context):
    """Track files that have been modified."""
    # Only track successful operations
    if not context.success:
        return HookResult()

    file_path = context.arguments.get('file_path')
    if file_path:
        modified_files.add(file_path)

    return HookResult(
        metadata={'tracked_files': len(modified_files)}
    )


def auto_commit_on_session_end(context):
    """
    Automatically commit all modified files when session ends.

    Creates a detailed commit message with:
    - List of modified files
    - Timestamp
    - Session statistics
    """
    if not is_git_repo():
        return HookResult(message="Not a git repository, skipping auto-commit")

    if not modified_files:
        return HookResult(message="No files modified, skipping auto-commit")

    try:
        # Stage all modified files
        for file_path in modified_files:
            subprocess.run(
                ['git', 'add', file_path],
                check=True,
                capture_output=True,
                timeout=10
            )

        # Create detailed commit message
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        file_list = '\n'.join(f"  - {f}" for f in sorted(modified_files))

        commit_message = f"""AI Agent Session - {timestamp}

Modified {len(modified_files)} file(s):
{file_list}

Session ID: {context.session_id}
Duration: {context.duration:.1f}s
Exit Reason: {context.exit_reason}

Auto-committed by AI Coding Agent hooks system.
"""

        # Create commit
        result = subprocess.run(
            ['git', 'commit', '-m', commit_message],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            # Get commit hash
            hash_result = subprocess.run(
                ['git', 'rev-parse', '--short', 'HEAD'],
                capture_output=True,
                text=True,
                timeout=5
            )
            commit_hash = hash_result.stdout.strip()

            return HookResult(
                message=f"Auto-committed {len(modified_files)} files (commit: {commit_hash})",
                metadata={
                    'commit_hash': commit_hash,
                    'files_committed': len(modified_files)
                }
            )
        else:
            return HookResult(
                message=f"Commit failed: {result.stderr}",
                metadata={'error': result.stderr}
            )

    except subprocess.TimeoutExpired:
        return HookResult(message="Git command timed out")
    except Exception as e:
        return HookResult(message=f"Auto-commit failed: {e}")
    finally:
        # Clear tracked files for next session
        modified_files.clear()


# Alternative: Commit after each file modification (more granular)
def auto_commit_per_file(context):
    """
    Commit immediately after each successful file modification.

    This creates a very detailed history but may result in many commits.
    """
    if not context.success:
        return HookResult()

    if not is_git_repo():
        return HookResult()

    file_path = context.arguments.get('file_path')
    if not file_path:
        return HookResult()

    try:
        # Stage the file
        subprocess.run(
            ['git', 'add', file_path],
            check=True,
            capture_output=True,
            timeout=10
        )

        # Create commit message
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        tool_name = context.tool

        commit_message = f"""AI: Modified {file_path}

Tool: {tool_name}
Timestamp: {timestamp}
Session: {context.session_id}

Auto-committed by AI Coding Agent.
"""

        # Commit
        result = subprocess.run(
            ['git', 'commit', '-m', commit_message],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            hash_result = subprocess.run(
                ['git', 'rev-parse', '--short', 'HEAD'],
                capture_output=True,
                text=True,
                timeout=5
            )
            commit_hash = hash_result.stdout.strip()

            return HookResult(
                message=f"Auto-committed {file_path} (commit: {commit_hash})",
                metadata={'commit_hash': commit_hash}
            )

    except Exception as e:
        # Don't fail the tool operation if commit fails
        return HookResult(message=f"Auto-commit failed: {e}")

    return HookResult()


# Hook registry
# Choose one strategy:

# Strategy 1: Commit all changes at session end (recommended)
HOOKS = {
    'PostToolUse:write_file': [track_file_modification],
    'PostToolUse:edit_file': [track_file_modification],
    'SessionEnd': [auto_commit_on_session_end],
}

# Strategy 2: Commit after each file modification (very granular)
# Uncomment to use this strategy instead:
# HOOKS = {
#     'PostToolUse:write_file': [auto_commit_per_file],
#     'PostToolUse:edit_file': [auto_commit_per_file],
# }
