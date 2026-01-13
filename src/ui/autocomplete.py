"""
Fuzzy file autocomplete using fzy-style scoring algorithm.

Reference: https://github.com/jhawthorn/fzy/blob/master/ALGORITHM.md

The fzy algorithm uses dynamic programming to find the best match positions,
with bonuses for:
- Consecutive character matches
- Matches at word boundaries (after /, _, -, .)
- Matches on uppercase letters (CamelCase)
- Shorter paths (normalized by length)
"""

from pathlib import Path
from typing import List, Optional, Set
from dataclasses import dataclass
import asyncio


# Scoring constants (based on fzy algorithm)
SCORE_GAP_LEADING = -0.005
SCORE_GAP_TRAILING = -0.005
SCORE_GAP_INNER = -0.01
SCORE_MATCH_CONSECUTIVE = 1.0
SCORE_MATCH_SLASH = 0.9
SCORE_MATCH_WORD = 0.8
SCORE_MATCH_CAPITAL = 0.7
SCORE_MATCH_DOT = 0.6


@dataclass
class FileSuggestion:
    """
    Autocomplete suggestion with match info.

    Attributes:
        path: Relative path from project root
        filename: Just the filename (for display)
        score: Match score (higher = better match)
        match_positions: Character positions that matched (for highlighting)
    """
    path: str
    filename: str
    score: float
    match_positions: List[int]

    def __repr__(self) -> str:
        return f"FileSuggestion({self.path}, score={self.score:.2f})"


class FileAutocomplete:
    """
    Fuzzy file search using fzy-style scoring.

    Usage:
        autocomplete = FileAutocomplete(Path("."))
        await autocomplete.index()  # Lazy indexing on first @

        suggestions = autocomplete.suggest("app")
        for s in suggestions:
            print(f"{s.path} (score: {s.score:.2f})")
    """

    # Directories to ignore during indexing
    IGNORE_DIRS: Set[str] = {
        '.git', '__pycache__', '.venv', 'venv', 'node_modules',
        '.env', '.pytest_cache', 'dist', 'build', '.idea',
        '.mypy_cache', '.tox', 'eggs', '*.egg-info',
        '.checkpoints', '.screenshots',
    }

    # File extensions to ignore
    IGNORE_EXTENSIONS: Set[str] = {
        '.pyc', '.pyo', '.exe', '.dll', '.so', '.o', '.obj',
        '.class', '.jar', '.war', '.ear', '.db', '.sqlite',
        '.log', '.tmp', '.swp', '.swo', '.bak',
    }

    # Maximum files to index (prevents memory issues on huge repos)
    MAX_FILES = 10000

    def __init__(self, root: Path = Path(".")):
        """
        Initialize autocomplete.

        Args:
            root: Project root directory
        """
        self.root = root.resolve()
        self._files: List[str] = []
        self._indexed = False

    async def index(self) -> None:
        """
        Index files in project (lazy, called on first @).

        Runs in a thread to avoid blocking the UI.
        """
        if self._indexed:
            return

        def _scan() -> List[str]:
            files = []
            try:
                for path in self.root.rglob("*"):
                    try:
                        if path.is_file() and not self._should_ignore(path):
                            # Store relative path with forward slashes (consistent)
                            rel = path.relative_to(self.root)
                            files.append(str(rel).replace('\\', '/'))

                        if len(files) >= self.MAX_FILES:
                            break
                    except (PermissionError, OSError):
                        # Skip files we can't access (symlinks, junctions, etc)
                        pass
            except (PermissionError, OSError):
                pass  # Skip directories we can't access

            return files

        self._files = await asyncio.to_thread(_scan)
        self._indexed = True

    def _should_ignore(self, path: Path) -> bool:
        """Check if path should be ignored."""
        # Check directory parts
        for part in path.parts:
            if part in self.IGNORE_DIRS:
                return True
            # Handle wildcard patterns like *.egg-info
            for pattern in self.IGNORE_DIRS:
                if '*' in pattern and path.match(pattern):
                    return True

        # Check extension
        if path.suffix.lower() in self.IGNORE_EXTENSIONS:
            return True

        return False

    def suggest(self, query: str, limit: int = 8) -> List[FileSuggestion]:
        """
        Get fuzzy matches for query using fzy algorithm.

        Args:
            query: Search query (characters must appear in order)
            limit: Maximum number of suggestions

        Returns:
            List of FileSuggestion sorted by score (best first)
        """
        if not query:
            # Show first files when no query (most recently modified would be ideal)
            return [
                FileSuggestion(p, Path(p).name, 0.0, [])
                for p in self._files[:limit]
            ]

        query_lower = query.lower()
        results = []

        for path in self._files:
            score, positions = self._fzy_score(query_lower, path.lower())
            if score > float('-inf'):
                results.append(FileSuggestion(
                    path=path,
                    filename=Path(path).name,
                    score=score,
                    match_positions=positions
                ))

        # Sort by score (descending), then by path length (prefer shorter)
        results.sort(key=lambda x: (-x.score, len(x.path)))
        return results[:limit]

    def _fzy_score(self, query: str, target: str) -> tuple:
        """
        Calculate fzy-style fuzzy match score.

        Args:
            query: Lowercase search query
            target: Lowercase target path

        Returns:
            Tuple of (score, match_positions) or (float('-inf'), []) if no match
        """
        n, m = len(query), len(target)

        if n == 0:
            return 0.0, []
        if n > m:
            return float('-inf'), []

        # First pass: check if all query chars exist in target (in order)
        positions = []
        j = 0
        for i, char in enumerate(target):
            if j < n and char == query[j]:
                positions.append(i)
                j += 1

        if j < n:
            # Not all query chars matched
            return float('-inf'), []

        # Second pass: calculate score based on match positions
        score = 0.0
        prev_pos = -1

        for idx, pos in enumerate(positions):
            # Gap penalty (characters skipped between matches)
            if prev_pos >= 0:
                gap = pos - prev_pos - 1
                if gap > 0:
                    score += SCORE_GAP_INNER * gap

            # Match bonus based on position context
            if pos == 0:
                # Start of string - strong bonus
                score += SCORE_MATCH_SLASH
            elif target[pos - 1] == '/':
                # After path separator - strong bonus
                score += SCORE_MATCH_SLASH
            elif target[pos - 1] in '_- ':
                # Word boundary - good bonus
                score += SCORE_MATCH_WORD
            elif target[pos - 1] == '.':
                # After dot (extension) - moderate bonus
                score += SCORE_MATCH_DOT
            elif target[pos].isupper():
                # CamelCase - moderate bonus
                score += SCORE_MATCH_CAPITAL

            # Consecutive match bonus
            if prev_pos >= 0 and pos == prev_pos + 1:
                score += SCORE_MATCH_CONSECUTIVE

            prev_pos = pos

        # Leading gap penalty (matches that start late in the string)
        if positions and positions[0] > 0:
            score += SCORE_GAP_LEADING * positions[0]

        # Trailing gap penalty (unused characters after last match)
        if positions:
            trailing = m - positions[-1] - 1
            if trailing > 0:
                score += SCORE_GAP_TRAILING * trailing

        # Normalize by target length (prefer shorter paths)
        # Using sqrt to not penalize long paths too heavily
        if m > 0:
            score = score / (m ** 0.5)

        return score, positions

    @property
    def file_count(self) -> int:
        """Number of indexed files."""
        return len(self._files)

    @property
    def is_indexed(self) -> bool:
        """Whether indexing is complete."""
        return self._indexed

    def invalidate(self) -> None:
        """Invalidate index (call when files change)."""
        self._indexed = False
        self._files.clear()
