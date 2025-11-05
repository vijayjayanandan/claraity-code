"""
Example Hook: Automatic File Backup

This hook demonstrates how to automatically backup files before modifications.
It creates timestamped backups in a .backups/ directory.

Usage:
    Copy this file to .claude/hooks.py to enable automatic backups.
"""

from src.hooks import HookResult, HookDecision
from pathlib import Path
from datetime import datetime
import shutil


def backup_before_write(context):
    """
    Backup file before write operation.

    Creates a timestamped backup in .backups/ directory.
    Format: .backups/filename.ext.2025-10-18_143022.bak
    """
    file_path = context.arguments.get('file_path', '')

    if not file_path:
        return HookResult(decision=HookDecision.PERMIT)

    path = Path(file_path)

    # Only backup if file already exists
    if not path.exists():
        return HookResult(
            decision=HookDecision.PERMIT,
            message=f"New file, no backup needed: {file_path}"
        )

    # Create backup directory
    backup_dir = Path('.backups')
    backup_dir.mkdir(exist_ok=True)

    # Create timestamped backup filename
    timestamp = datetime.now().strftime('%Y-%m-%d_%H%M%S')
    backup_name = f"{path.name}.{timestamp}.bak"
    backup_path = backup_dir / backup_name

    try:
        # Copy file to backup
        shutil.copy2(path, backup_path)

        return HookResult(
            decision=HookDecision.PERMIT,
            message=f"Backed up {file_path} to {backup_path}",
            metadata={'backup_path': str(backup_path), 'timestamp': timestamp}
        )
    except Exception as e:
        # Don't block operation if backup fails
        return HookResult(
            decision=HookDecision.PERMIT,
            message=f"Backup failed but allowing operation: {e}",
            metadata={'backup_error': str(e)}
        )


def backup_before_edit(context):
    """
    Backup file before edit operation.

    Same as write, but for edit_file tool.
    """
    return backup_before_write(context)


def cleanup_old_backups(context):
    """
    Cleanup old backups when session ends.

    Keeps only the last 10 backups per file.
    """
    backup_dir = Path('.backups')

    if not backup_dir.exists():
        return HookResult()

    # Group backups by original filename
    backups_by_file = {}
    for backup_file in backup_dir.glob('*.bak'):
        # Extract original filename (before timestamp)
        # Format: filename.ext.2025-10-18_143022.bak
        parts = backup_file.name.rsplit('.', 2)  # Split from right
        if len(parts) >= 3:
            original_name = parts[0]
            if original_name not in backups_by_file:
                backups_by_file[original_name] = []
            backups_by_file[original_name].append(backup_file)

    # Keep only last 10 backups per file
    cleaned_count = 0
    for original_name, backups in backups_by_file.items():
        if len(backups) > 10:
            # Sort by modification time (oldest first)
            backups.sort(key=lambda p: p.stat().st_mtime)

            # Delete oldest backups
            to_delete = backups[:-10]  # Keep last 10
            for backup_file in to_delete:
                try:
                    backup_file.unlink()
                    cleaned_count += 1
                except Exception:
                    pass

    return HookResult(
        message=f"Cleaned up {cleaned_count} old backups",
        metadata={'cleaned': cleaned_count}
    )


# Hook registry
HOOKS = {
    'PreToolUse:write_file': [backup_before_write],
    'PreToolUse:edit_file': [backup_before_edit],
    'SessionEnd': [cleanup_old_backups],
}
