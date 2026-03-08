"""Command safety controls for RunCommandTool.

Provides a blocklist of dangerous command patterns that should NEVER execute
without explicit user approval, even in AUTO permission mode. This is a
safety floor that cannot be bypassed by permission settings.
"""

import re
from typing import Tuple

from src.observability import get_logger

logger = get_logger("tools.command_safety")

# Patterns that are ALWAYS blocked in AUTO mode (require explicit approval)
# These represent commands that can cause irreversible damage or data exfiltration.
DANGEROUS_PATTERNS: list[re.Pattern] = [
    # Destructive file operations
    re.compile(r'\brm\s+(-[^\s]*)?-[^\s]*r', re.IGNORECASE),        # rm -rf, rm -r
    re.compile(r'\brm\s+(-[^\s]*\s+)*/', re.IGNORECASE),            # rm /absolute/path
    re.compile(r'\bmkfs\b', re.IGNORECASE),                          # format filesystem
    re.compile(r'\bdd\s+', re.IGNORECASE),                           # disk overwrite
    re.compile(r'\b(shred|wipe)\b', re.IGNORECASE),                  # secure delete

    # Data exfiltration via network
    re.compile(r'\bcurl\b.*\|.*\b(bash|sh|zsh|python|perl)\b'),      # curl | bash
    re.compile(r'\bwget\b.*\|.*\b(bash|sh|zsh|python|perl)\b'),      # wget | bash
    re.compile(r'\bcurl\b.*[-][-]upload', re.IGNORECASE),             # curl --upload
    re.compile(r'\bcurl\b.*\s+-[^\s]*T\b', re.IGNORECASE),           # curl -T (upload)
    re.compile(r'\bcurl\b.*\s+-[^\s]*d\b.*\$\(', re.IGNORECASE),     # curl -d $(cmd)

    # Reverse shells and remote code execution
    re.compile(r'\b(nc|ncat|netcat)\b.*-[^\s]*e\b'),                  # nc -e
    re.compile(r'/dev/tcp/', re.IGNORECASE),                          # bash reverse shell
    re.compile(r'\bssh\b.*\b-R\b', re.IGNORECASE),                   # SSH reverse tunnel

    # Credential access
    re.compile(r'\bcat\b.*\.(ssh|gnupg|aws|azure)', re.IGNORECASE),  # cat ~/.ssh/
    re.compile(r'\bcat\b.*credentials', re.IGNORECASE),               # cat credentials
    re.compile(r'\bcat\b.*/etc/(shadow|passwd)', re.IGNORECASE),      # cat /etc/shadow

    # System modification
    re.compile(r'\bchmod\b.*777', re.IGNORECASE),                     # chmod 777
    re.compile(r'\bchown\b.*root', re.IGNORECASE),                    # chown root
    re.compile(r'\bcrontab\b', re.IGNORECASE),                        # crontab modification
    re.compile(r'\bsystemctl\b.*(enable|start|stop)', re.IGNORECASE), # service management
    re.compile(r'\bregistry\b|reg\s+(add|delete)', re.IGNORECASE),    # Windows registry

    # PowerShell dangerous patterns
    re.compile(r'Invoke-WebRequest.*-OutFile', re.IGNORECASE),        # Download file
    re.compile(r'Invoke-Expression', re.IGNORECASE),                  # IEX (code execution)
    re.compile(r'Start-Process', re.IGNORECASE),                      # Launch process
    re.compile(r'New-Service', re.IGNORECASE),                        # Install service
    re.compile(r'Set-ExecutionPolicy', re.IGNORECASE),                # Change PS policy
    re.compile(r'DownloadString\(', re.IGNORECASE),                   # Net.WebClient download

    # Package manager post-install script abuse
    re.compile(r'\bnpm\s+install\b.*--ignore-scripts\s*=\s*false', re.IGNORECASE),
    re.compile(r'\bpip\s+install\b.*--no-binary', re.IGNORECASE),

    # Environment variable exfiltration
    re.compile(r'\b(env|printenv|set)\b.*\|\s*(curl|wget|nc)', re.IGNORECASE),
]

# Maximum allowed timeout for commands (seconds)
MAX_COMMAND_TIMEOUT = 600


def check_command_safety(command: str) -> Tuple[bool, str]:
    """Check if a command matches any dangerous patterns.

    Args:
        command: The shell command to check.

    Returns:
        Tuple of (is_safe, reason). If is_safe is False, reason explains why.
    """
    command_stripped = command.strip()

    if not command_stripped:
        return False, "Empty command"

    for pattern in DANGEROUS_PATTERNS:
        match = pattern.search(command_stripped)
        if match:
            reason = f"Command matches dangerous pattern: {match.group()}"
            logger.warning(f"[COMMAND_SAFETY] Blocked: {reason} in command: {command_stripped[:100]}")
            return False, reason

    return True, ""


def clamp_timeout(timeout: int | float | None, default: int = 120) -> int:
    """Clamp timeout to safe bounds.

    Args:
        timeout: Requested timeout in seconds.
        default: Default if None.

    Returns:
        Clamped timeout value.
    """
    if timeout is None:
        return default
    return max(1, min(int(timeout), MAX_COMMAND_TIMEOUT))
