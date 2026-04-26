"""Two-tier command safety controls for RunCommandTool.

Tier 1 - HARD BLOCK: Patterns that can NEVER execute, no user override.
    Reverse shells, remote code execution, data exfiltration, disk destruction.

Tier 2 - NEEDS APPROVAL: Patterns that require explicit user confirmation,
    even when auto-approve is enabled for the "execute" category.
    Destructive file ops, credential access, system modification.

This safety floor cannot be bypassed by permission settings or auto-approve.
"""

import re
from dataclasses import dataclass
from enum import Enum, auto

from src.observability import get_logger

logger = get_logger("tools.command_safety")


class CommandSafety(Enum):
    """Safety classification for a command."""

    SAFE = auto()
    NEEDS_APPROVAL = auto()
    BLOCK = auto()


@dataclass
class CommandSafetyResult:
    """Result of a command safety check.

    Attributes:
        safety: Classification level (SAFE, NEEDS_APPROVAL, BLOCK).
        reason: Human-readable explanation (empty for SAFE).
        pattern_name: Short name for the matched pattern (for logging/UI).
    """

    safety: CommandSafety
    reason: str = ""
    pattern_name: str = ""


# ---------------------------------------------------------------------------
# Tier 1: HARD BLOCK - no user override, ever
# ---------------------------------------------------------------------------

_HARD_BLOCK_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Disk destruction (irreversible)
    (re.compile(r"\bmkfs\b", re.IGNORECASE), "filesystem format"),
    (re.compile(r"(?:^|\||;|&&)\s*dd\s+", re.IGNORECASE), "disk overwrite"),
    (re.compile(r"\b(shred|wipe)\b", re.IGNORECASE), "secure delete"),
    # Remote code execution (pipe to shell)
    (re.compile(r"\bcurl\b.*\|.*\b(bash|sh|zsh|python|perl)\b"), "curl pipe to shell"),
    (re.compile(r"\bwget\b.*\|.*\b(bash|sh|zsh|python|perl)\b"), "wget pipe to shell"),
    # Data exfiltration via upload
    (re.compile(r"\bcurl\b.*[-][-]upload", re.IGNORECASE), "curl upload"),
    (re.compile(r"\bcurl\b.*\s+-[^\s]*T\b", re.IGNORECASE), "curl -T upload"),
    (
        re.compile(r"\bcurl\b.*\s+-[^\s]*d\b.*\$\(", re.IGNORECASE),
        "curl -d with command substitution",
    ),
    # Reverse shells
    (re.compile(r"\b(nc|ncat|netcat)\b.*-[^\s]*e\b"), "netcat reverse shell"),
    (re.compile(r"/dev/tcp/", re.IGNORECASE), "bash reverse shell"),
    (re.compile(r"\bssh\b.*\s-R\s", re.IGNORECASE), "SSH reverse tunnel"),
    # PowerShell code execution
    (re.compile(r"Invoke-Expression", re.IGNORECASE), "PowerShell Invoke-Expression"),
    (re.compile(r"DownloadString\(", re.IGNORECASE), "PowerShell DownloadString"),
    (re.compile(r"Set-ExecutionPolicy", re.IGNORECASE), "PowerShell Set-ExecutionPolicy"),
    (re.compile(r"New-Service", re.IGNORECASE), "PowerShell New-Service"),
    # Windows registry modification
    (
        re.compile(r"\breg\s+(add|delete|import|export)\b", re.IGNORECASE),
        "Windows registry modification",
    ),
    # Environment variable exfiltration
    (re.compile(r"\b(env|printenv|set)\b.*\|\s*(curl|wget|nc)", re.IGNORECASE), "env exfiltration"),
    # Encoded payload execution
    (
        re.compile(r"base64\s+(-d|--decode).*\|.*\b(bash|sh|zsh|python|perl)\b", re.IGNORECASE),
        "base64 decode pipe to shell",
    ),
    # Inline Python with network access
    (
        re.compile(r"python[23]?\s+-c\s+.*\b(socket|urllib|requests)\b", re.IGNORECASE),
        "python -c with network access",
    ),
]

# ---------------------------------------------------------------------------
# Tier 2: NEEDS APPROVAL - user must confirm, auto-approve bypassed
# ---------------------------------------------------------------------------

_NEEDS_APPROVAL_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Destructive file operations
    (re.compile(r"\brm\s+(-[^\s]*)?-[^\s]*r", re.IGNORECASE), "recursive delete (rm -r)"),
    (re.compile(r"\brm\s+(-[^\s]*\s+)*/", re.IGNORECASE), "delete absolute path"),
    # Credential access
    (re.compile(r"\bcat\b.*\.(ssh|gnupg|aws|azure)", re.IGNORECASE), "credential file access"),
    (re.compile(r"\bcat\b.*credentials", re.IGNORECASE), "credentials file access"),
    (re.compile(r"\bcat\b.*/etc/(shadow|passwd)", re.IGNORECASE), "system credential access"),
    # Permission/ownership changes
    (re.compile(r"\bchmod\b.*777", re.IGNORECASE), "chmod 777"),
    (re.compile(r"\bchown\b.*root", re.IGNORECASE), "chown to root"),
    # System modification
    (re.compile(r"\bcrontab\b", re.IGNORECASE), "crontab modification"),
    (re.compile(r"\bsystemctl\b.*(enable|start|stop)", re.IGNORECASE), "service management"),
    # PowerShell risky operations
    (re.compile(r"Start-Process", re.IGNORECASE), "PowerShell Start-Process"),
    (re.compile(r"Invoke-WebRequest.*-OutFile", re.IGNORECASE), "PowerShell file download"),
    # Package manager risky flags
    (
        re.compile(r"\bnpm\s+install\b.*--ignore-scripts\s*=\s*false", re.IGNORECASE),
        "npm install with scripts enabled",
    ),
    (re.compile(r"\bpip\s+install\b.*--no-binary", re.IGNORECASE), "pip install from source"),
    # --- NEW: Structural attack patterns ---
    # Compound cd && git (bare repository attack vector)
    (re.compile(r"\bcd\s+.*&&\s*git\b", re.IGNORECASE), "compound cd && git"),
    (re.compile(r"\bcd\s+.*;.*\bgit\b", re.IGNORECASE), "compound cd ; git"),
    # Windows registry query (read-only but still sensitive)
    (re.compile(r"\breg\s+query\b", re.IGNORECASE), "Windows registry query"),
]


def _check_newline_comment_injection(command: str) -> bool:
    """Detect quoted newline followed by #-prefixed line.

    This pattern can hide arguments from line-based permission checks.
    Example: echo 'safe\n# --force --delete-all' looks innocent on line 1.
    """
    # Look for literal \n or actual newlines inside quotes followed by #
    # Check for actual embedded newlines (from multi-line strings)
    if "\n" in command:
        lines = command.split("\n")
        for line in lines[1:]:
            stripped = line.strip()
            if stripped.startswith("#"):
                return True

    # Check for escaped \n inside quotes followed by # on a "logical" next line
    # Pattern: quote...backslash-n...#  inside single or double quotes
    if re.search(r"""(['"]).*?\\n\s*#.*?\1""", command):
        return True

    return False


# Maximum allowed timeout for commands (seconds)
MAX_COMMAND_TIMEOUT = 600


def check_command_safety(command: str) -> CommandSafetyResult:
    """Check command against two-tier safety patterns.

    Priority: BLOCK > NEEDS_APPROVAL > SAFE.
    The safety floor is enforced regardless of auto-approve settings.

    Args:
        command: The shell command to check.

    Returns:
        CommandSafetyResult with safety level, reason, and pattern name.
    """
    command_stripped = command.strip()

    if not command_stripped:
        return CommandSafetyResult(
            safety=CommandSafety.BLOCK,
            reason="Empty command",
            pattern_name="empty",
        )

    # Tier 1: Hard block
    for pattern, name in _HARD_BLOCK_PATTERNS:
        match = pattern.search(command_stripped)
        if match:
            reason = f"Command matches blocked pattern: {match.group()} ({name})"
            logger.warning(
                f"[COMMAND_SAFETY] Hard block: {reason} in command: {command_stripped[:100]}"
            )
            return CommandSafetyResult(
                safety=CommandSafety.BLOCK,
                reason=reason,
                pattern_name=name,
            )

    # Tier 2: Needs approval
    for pattern, name in _NEEDS_APPROVAL_PATTERNS:
        match = pattern.search(command_stripped)
        if match:
            reason = f"Command requires approval: {match.group()} ({name})"
            logger.info(
                f"[COMMAND_SAFETY] Needs approval: {reason} in command: {command_stripped[:100]}"
            )
            return CommandSafetyResult(
                safety=CommandSafety.NEEDS_APPROVAL,
                reason=reason,
                pattern_name=name,
            )

    # Structural check: newline + # injection
    if _check_newline_comment_injection(command_stripped):
        reason = "Command contains quoted newline followed by #-prefixed line (argument hiding)"
        logger.info(f"[COMMAND_SAFETY] Needs approval: {reason}")
        return CommandSafetyResult(
            safety=CommandSafety.NEEDS_APPROVAL,
            reason=reason,
            pattern_name="newline comment injection",
        )

    return CommandSafetyResult(safety=CommandSafety.SAFE)


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
