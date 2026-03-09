"""
LSP Cache - In-memory LRU cache for LSP query results.

Features:
- LRU eviction (removes least recently used entries when memory limit reached)
- File-change invalidation (automatically invalidates cache when files are edited)
- TTL expiration (entries expire after configured time)
- Memory management (configurable size limit, default 10MB)
"""

import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


@dataclass
class CacheEntry:
    """Single cache entry with metadata."""
    value: Any
    timestamp: float
    file_path: str | None
    file_mtime: float | None


class LSPCache:
    """
    In-memory LRU cache for LSP query results.

    Features:
    - LRU eviction (removes oldest entries when full)
    - File-change invalidation (auto-invalidates on file edits)
    - TTL expiration (entries expire after 5 minutes)
    - Memory limit (default 10MB)
    """

    def __init__(
        self,
        max_size_mb: int = 10,
        ttl_seconds: int = 300,
        repo_root: str | None = None
    ):
        """
        Initialize LSP cache.

        Args:
            max_size_mb: Maximum cache size in MB (default: 10MB)
            ttl_seconds: Time-to-live in seconds (default: 300s = 5 min)
            repo_root: Repository root path for security validation (optional)
        """
        self.max_size_mb = max_size_mb
        self.ttl_seconds = ttl_seconds
        self.repo_root = repo_root

        # OrderedDict maintains insertion order for LRU
        self.cache: OrderedDict[str, CacheEntry] = OrderedDict()

        # Thread-safe lock for concurrent access
        self._lock = threading.Lock()

        self.logger = logging.getLogger("code_intelligence.cache")

        # Log repo_root at init (helps debug path issues)
        if self.repo_root:
            from src.code_intelligence.path_utils import normalize_path
            self.logger.info(
                f"LSPCache init: repo_root={self.repo_root}, "
                f"normalized={normalize_path(self.repo_root)}"
            )

    def get(self, key: str) -> Any | None:
        """
        Get value from cache (thread-safe).

        Returns None if:
        - Key not in cache (cache miss)
        - Entry expired (TTL exceeded)
        - File modified since caching

        Args:
            key: Cache key (e.g., "def:auth.py:45:10")

        Returns:
            Cached value or None
        """
        with self._lock:
            if key not in self.cache:
                return None  # Cache miss

            entry = self.cache[key]

            # Check TTL expiration
            age = time.time() - entry.timestamp
            if age > self.ttl_seconds:
                self.logger.debug(f"Cache expired: {key} (age: {age:.1f}s)")
                del self.cache[key]
                return None

            # Check file modification
            if entry.file_path and entry.file_mtime:
                if self._file_modified(entry.file_path, entry.file_mtime):
                    self.logger.debug(f"File modified: {entry.file_path}, invalidating {key}")
                    # Call internal method to avoid nested lock
                    self._invalidate_file_internal(entry.file_path)
                    return None

            # Move to end (mark as recently used for LRU)
            self.cache.move_to_end(key)

            self.logger.debug(f"Cache hit: {key}")
            return entry.value

    def set(
        self,
        key: str,
        value: Any,
        file_path: str | None = None
    ) -> None:
        """
        Set cache entry (thread-safe).

        If cache size exceeds limit, evicts LRU entries.

        Args:
            key: Cache key
            value: Value to cache
            file_path: Optional file path (for invalidation on file change)
        """
        with self._lock:
            # Normalize file_path for consistent storage (avoids drift from mixed formats)
            normalized_file_path = None
            if file_path:
                from src.code_intelligence.path_utils import normalize_path
                normalized_file_path = str(normalize_path(file_path))

            # Get file modification time (for invalidation)
            file_mtime = None
            if normalized_file_path:
                try:
                    file_mtime = self._get_mtime(normalized_file_path)
                except FileNotFoundError:
                    # File doesn't exist (e.g., in tests) - cache without mtime
                    # Entry won't be automatically invalidated on file change
                    pass

            # Create entry
            entry = CacheEntry(
                value=value,
                timestamp=time.time(),
                file_path=normalized_file_path,
                file_mtime=file_mtime
            )

            # Add to cache
            self.cache[key] = entry

            # Move to end (mark as most recently used)
            self.cache.move_to_end(key)

            # Evict LRU entries if size limit exceeded
            while self._size_mb() > self.max_size_mb and len(self.cache) > 0:
                # Remove oldest entry (front of OrderedDict)
                evicted_key, evicted_entry = self.cache.popitem(last=False)
                self.logger.debug(f"Evicted (LRU): {evicted_key}")

    def invalidate_file(self, file_path: str) -> int:
        """
        Invalidate all cache entries for a file (thread-safe).

        Called when file is edited to ensure fresh data on next query.

        Args:
            file_path: Path to file

        Returns:
            Number of entries invalidated

        Raises:
            ValueError: If path is outside repo_root (security check)
        """
        with self._lock:
            return self._invalidate_file_internal(file_path)

    def _invalidate_file_internal(self, file_path: str) -> int:
        """
        Internal method to invalidate file entries (no lock, for use within locked context).

        Args:
            file_path: Path to file

        Returns:
            Number of entries invalidated

        Raises:
            ValueError: If path is outside repo_root (security check)
        """
        # Normalize path
        from src.code_intelligence.path_utils import is_within_repo, normalize_path

        normalized_path = normalize_path(file_path)

        # Security: Validate path is within repo_root (if configured)
        if self.repo_root and not is_within_repo(file_path, self.repo_root):
            self.logger.warning(f"[SECURITY] Rejected path outside repo: {file_path}")
            raise ValueError(f"Path outside repository: {file_path}")

        normalized_path_str = str(normalized_path)

        # Find all entries for this file
        keys_to_delete = [
            key for key, entry in self.cache.items()
            if entry.file_path and str(normalize_path(entry.file_path)) == normalized_path_str
        ]

        # Delete entries
        for key in keys_to_delete:
            del self.cache[key]

        if keys_to_delete:
            self.logger.info(f"Invalidated {len(keys_to_delete)} entries for {file_path}")

        return len(keys_to_delete)

    def clear(self) -> None:
        """Clear all cache entries (thread-safe)."""
        with self._lock:
            self.cache.clear()
            self.logger.info("Cache cleared")

    def _file_modified(self, file_path: str, cached_mtime: float) -> bool:
        """
        Check if file has been modified since caching.

        Args:
            file_path: Path to file
            cached_mtime: Modification time when cached

        Returns:
            True if file modified, False otherwise
        """
        try:
            current_mtime = self._get_mtime(file_path)
            return current_mtime > cached_mtime
        except FileNotFoundError:
            # File deleted - consider it modified
            return True

    def _get_mtime(self, file_path: str) -> float:
        """
        Get file modification time.

        Args:
            file_path: Path to file

        Returns:
            Modification time (seconds since epoch)

        Raises:
            FileNotFoundError: File does not exist
        """
        return Path(file_path).stat().st_mtime

    def _size_mb(self) -> float:
        """
        Estimate cache size in MB.

        Uses rough approximation:
        - Each string character: 1 byte
        - Each dict/list: 100 bytes overhead
        - Each cache entry: 200 bytes overhead

        Returns:
            Estimated size in MB
        """
        total_bytes = 0

        for key, entry in self.cache.items():
            # Key size
            total_bytes += len(key)

            # Entry overhead
            total_bytes += 200

            # Value size (rough estimate)
            total_bytes += self._estimate_size(entry.value)

        return total_bytes / (1024 * 1024)

    def _estimate_size(self, obj: Any) -> int:
        """
        Estimate object size in bytes.

        Args:
            obj: Object to estimate

        Returns:
            Estimated size in bytes
        """
        if isinstance(obj, str):
            return len(obj)
        elif isinstance(obj, int | float):
            return 8
        elif isinstance(obj, dict):
            return 100 + sum(
                self._estimate_size(k) + self._estimate_size(v)
                for k, v in obj.items()
            )
        elif isinstance(obj, list):
            return 100 + sum(self._estimate_size(item) for item in obj)
        else:
            return 100  # Default
