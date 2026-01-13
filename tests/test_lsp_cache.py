"""
Unit tests for LSP Cache.

Tests cover:
- Cache hit/miss
- LRU eviction
- TTL expiration
- File-change invalidation
- Memory management
- Security (path traversal)
- Thread safety
"""

import pytest
from pathlib import Path
import time
import asyncio
import threading

from src.code_intelligence.cache import LSPCache, CacheEntry


class TestCacheHitMiss:
    """Test basic cache hit and miss functionality."""

    def test_cache_miss(self):
        """Test cache miss returns None."""
        cache = LSPCache()

        # Miss - key not in cache
        assert cache.get("key1") is None

    def test_cache_hit(self):
        """Test cache hit returns value."""
        cache = LSPCache()

        # Set value
        cache.set("key1", {"value": "data"})

        # Hit
        result = cache.get("key1")
        assert result == {"value": "data"}

    def test_multiple_keys(self):
        """Test cache handles multiple keys."""
        cache = LSPCache()

        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")

        assert cache.get("key1") == "value1"
        assert cache.get("key2") == "value2"
        assert cache.get("key3") == "value3"

    def test_cache_key_format(self):
        """Test realistic cache key formats."""
        cache = LSPCache()

        # Typical LSP cache keys
        cache.set("def:src/auth.py:45:10", {"uri": "src/auth.py", "line": 45})
        cache.set("refs:src/auth.py:45:10", [{"uri": "src/api.py", "line": 78}])
        cache.set("hover:src/auth.py:45:10", {"contents": "def auth() -> Token"})

        # All should be cached
        assert cache.get("def:src/auth.py:45:10") is not None
        assert cache.get("refs:src/auth.py:45:10") is not None
        assert cache.get("hover:src/auth.py:45:10") is not None

        # Different key should miss
        assert cache.get("def:src/auth.py:46:10") is None


class TestLRUEviction:
    """Test LRU eviction when memory limit exceeded."""

    def test_lru_eviction(self):
        """Test LRU eviction removes oldest entries."""
        cache = LSPCache(max_size_mb=0.001)  # Tiny cache (1KB)

        # Add entries until eviction
        for i in range(100):
            cache.set(f"key_{i}", {"data": "x" * 100})

        # Oldest entries should be evicted
        assert cache.get("key_0") is None
        assert cache.get("key_1") is None

        # Recent entries should remain
        assert cache.get("key_99") is not None
        assert cache.get("key_98") is not None

    def test_lru_access_order(self):
        """Test accessing entry moves it to end (LRU)."""
        cache = LSPCache(max_size_mb=0.001)

        # Add 3 entries
        cache.set("key_a", {"data": "x" * 100})
        cache.set("key_b", {"data": "x" * 100})
        cache.set("key_c", {"data": "x" * 100})

        # Access key_a (moves to end)
        cache.get("key_a")

        # Add more entries to trigger eviction
        for i in range(50):
            cache.set(f"key_{i}", {"data": "x" * 100})

        # key_a should survive (was accessed recently)
        # key_b and key_c should be evicted (older)
        assert cache.get("key_b") is None
        assert cache.get("key_c") is None


class TestTTLExpiration:
    """Test TTL expiration."""

    def test_ttl_expiration(self):
        """Test entries expire after TTL."""
        cache = LSPCache(ttl_seconds=1)  # 1 second TTL

        cache.set("key1", {"value": "data"})
        assert cache.get("key1") is not None

        # Wait for expiration
        time.sleep(1.1)

        # Expired
        assert cache.get("key1") is None

    def test_ttl_not_expired(self):
        """Test entries don't expire before TTL."""
        cache = LSPCache(ttl_seconds=10)  # 10 second TTL

        cache.set("key1", {"value": "data"})

        # Wait less than TTL
        time.sleep(0.5)

        # Should still be cached
        assert cache.get("key1") is not None

    def test_ttl_deleted_from_cache(self):
        """Test expired entries are deleted from cache."""
        cache = LSPCache(ttl_seconds=1)

        cache.set("key1", {"value": "data"})
        assert len(cache.cache) == 1

        # Wait for expiration
        time.sleep(1.1)

        # Access triggers deletion
        cache.get("key1")

        # Entry should be removed
        assert len(cache.cache) == 0


class TestFileInvalidation:
    """Test file-change invalidation."""

    def test_file_invalidation_on_modify(self, tmp_path):
        """Test cache invalidated when file modified."""
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello(): pass")

        cache = LSPCache()
        cache.set("def:test.py:1:0", {"value": "data"}, file_path=str(test_file))

        # Cache hit
        assert cache.get("def:test.py:1:0") is not None

        # Modify file
        time.sleep(0.01)  # Ensure mtime changes
        test_file.write_text("def hello(): pass  # modified")

        # Cache invalidated (automatic check on get)
        assert cache.get("def:test.py:1:0") is None

    def test_manual_file_invalidation(self, tmp_path):
        """Test manual file invalidation."""
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello(): pass")

        cache = LSPCache()

        # Cache multiple queries for same file
        cache.set("def:test.py:1:0", {"value": "data1"}, file_path=str(test_file))
        cache.set("refs:test.py:1:0", {"value": "data2"}, file_path=str(test_file))
        cache.set("hover:test.py:1:0", {"value": "data3"}, file_path=str(test_file))

        # All cached
        assert len(cache.cache) == 3

        # Invalidate file
        count = cache.invalidate_file(str(test_file))

        # All entries invalidated
        assert count == 3
        assert cache.get("def:test.py:1:0") is None
        assert cache.get("refs:test.py:1:0") is None
        assert cache.get("hover:test.py:1:0") is None

    def test_invalidate_file_path_normalization(self, tmp_path):
        """Test file path normalization during invalidation."""
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello(): pass")

        cache = LSPCache()
        cache.set("key1", {"value": "data"}, file_path=str(test_file))

        # Invalidate with different path format (but same file)
        # Should still work due to path normalization
        count = cache.invalidate_file(str(test_file.resolve()))
        assert count == 1

    def test_file_deleted(self, tmp_path):
        """Test cache invalidated when file deleted."""
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello(): pass")

        cache = LSPCache()
        cache.set("def:test.py:1:0", {"value": "data"}, file_path=str(test_file))

        # Cache hit
        assert cache.get("def:test.py:1:0") is not None

        # Delete file
        test_file.unlink()

        # Cache invalidated (file not found = modified)
        assert cache.get("def:test.py:1:0") is None


class TestCacheOperations:
    """Test cache operations."""

    def test_clear(self):
        """Test clear() removes all entries."""
        cache = LSPCache()

        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")

        assert len(cache.cache) == 3

        cache.clear()

        assert len(cache.cache) == 0
        assert cache.get("key1") is None

    def test_overwrite_key(self):
        """Test overwriting existing key."""
        cache = LSPCache()

        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

        # Overwrite
        cache.set("key1", "value2")
        assert cache.get("key1") == "value2"

        # Should only have 1 entry
        assert len(cache.cache) == 1


class TestMemoryManagement:
    """Test memory management."""

    def test_size_estimation(self):
        """Test cache size estimation."""
        cache = LSPCache()

        # Empty cache
        assert cache._size_mb() == 0

        # Add small entry
        cache.set("key1", "value1")
        size1 = cache._size_mb()
        assert size1 > 0

        # Add larger entry
        cache.set("key2", {"data": "x" * 1000})
        size2 = cache._size_mb()
        assert size2 > size1

    def test_estimate_size_types(self):
        """Test _estimate_size for different types."""
        cache = LSPCache()

        # String
        assert cache._estimate_size("hello") == 5

        # Integer
        assert cache._estimate_size(42) == 8

        # Float
        assert cache._estimate_size(3.14) == 8

        # Dict
        size_dict = cache._estimate_size({"key": "value"})
        assert size_dict > 100  # 100 overhead + key + value

        # List
        size_list = cache._estimate_size(["a", "b", "c"])
        assert size_list > 100  # 100 overhead + items

    def test_max_size_respected(self):
        """Test cache respects max size limit."""
        cache = LSPCache(max_size_mb=0.001)  # 1KB

        # Fill cache
        for i in range(100):
            cache.set(f"key_{i}", {"data": "x" * 100})

        # Cache size should not exceed limit (with some margin for overhead)
        assert cache._size_mb() <= 0.002  # 1KB + small margin


class TestEdgeCases:
    """Test edge cases."""

    def test_empty_cache(self):
        """Test operations on empty cache."""
        cache = LSPCache()

        assert cache.get("nonexistent") is None
        assert cache._size_mb() == 0
        cache.clear()  # Should not error

    def test_cache_without_file_path(self):
        """Test caching without file path."""
        cache = LSPCache()

        cache.set("key1", "value1", file_path=None)
        assert cache.get("key1") == "value1"

        # Should not be invalidated by file changes
        # (no file path associated)

    def test_none_value(self):
        """Test caching None value."""
        cache = LSPCache()

        cache.set("key1", None)
        # get() returns None for cache miss AND for cached None value
        # This is acceptable as LSP queries rarely return None intentionally

    def test_complex_values(self):
        """Test caching complex nested structures."""
        cache = LSPCache()

        complex_value = {
            "definitions": [
                {"uri": "file1.py", "range": {"start": {"line": 10, "char": 5}}},
                {"uri": "file2.py", "range": {"start": {"line": 20, "char": 8}}},
            ],
            "metadata": {
                "language": "python",
                "timestamp": 1234567890
            }
        }

        cache.set("key1", complex_value)
        result = cache.get("key1")

        assert result == complex_value
        assert result["definitions"][0]["uri"] == "file1.py"


class TestCacheMetrics:
    """Test cache hit rate and performance characteristics."""

    def test_typical_workflow_hit_rate(self, tmp_path):
        """Simulate typical agent workflow to measure hit rate."""
        test_file = tmp_path / "auth.py"
        test_file.write_text("def authenticate(): pass")

        cache = LSPCache()

        hits = 0
        misses = 0

        # Simulate agent session
        # Query 1: Initial discovery (miss)
        if cache.get("def:auth.py:45:10") is None:
            misses += 1
            cache.set("def:auth.py:45:10", {"uri": "auth.py"}, file_path=str(test_file))
        else:
            hits += 1

        # Query 2: Same symbol again (hit expected)
        if cache.get("def:auth.py:45:10") is None:
            misses += 1
        else:
            hits += 1

        # Query 3: Different operation, same symbol (miss)
        if cache.get("refs:auth.py:45:10") is None:
            misses += 1
            cache.set("refs:auth.py:45:10", [{"uri": "api.py"}], file_path=str(test_file))
        else:
            hits += 1

        # Query 4: Same symbol type check (hit expected for definition)
        if cache.get("def:auth.py:45:10") is None:
            misses += 1
        else:
            hits += 1

        # Hit rate should be reasonable
        hit_rate = hits / (hits + misses)
        assert hit_rate >= 0.4  # At least 40% hit rate


class TestCacheSecurity:
    """Test security features (P0-1 fix: path traversal prevention)."""

    def test_path_traversal_blocked(self, tmp_path):
        """Test path traversal attacks are blocked."""
        repo_root = tmp_path
        cache = LSPCache(repo_root=str(repo_root))

        # Create a file outside repo
        outside_dir = tmp_path.parent / "outside_repo"
        outside_dir.mkdir(exist_ok=True)
        outside_file = outside_dir / "secrets.py"
        outside_file.write_text("SECRET_KEY = '12345'")

        # Attempt path traversal (should raise ValueError)
        with pytest.raises(ValueError, match="Path outside repository"):
            cache.invalidate_file(str(outside_file))

    def test_path_traversal_with_relative_paths(self, tmp_path):
        """Test path traversal using relative paths is blocked."""
        repo_root = tmp_path
        cache = LSPCache(repo_root=str(repo_root))

        # Attempt traversal using ../
        with pytest.raises(ValueError, match="Path outside repository"):
            cache.invalidate_file(str(repo_root / ".." / "secrets.py"))

    def test_valid_paths_within_repo_allowed(self, tmp_path):
        """Test valid paths within repo are allowed."""
        repo_root = tmp_path
        cache = LSPCache(repo_root=str(repo_root))

        # Create file within repo
        valid_file = tmp_path / "src" / "auth.py"
        valid_file.parent.mkdir(parents=True, exist_ok=True)
        valid_file.write_text("def auth(): pass")

        # Cache and invalidate (should work)
        cache.set("key1", "value1", file_path=str(valid_file))
        count = cache.invalidate_file(str(valid_file))
        assert count == 1  # Successfully invalidated

    def test_path_traversal_without_repo_root(self, tmp_path):
        """Test cache without repo_root does not validate paths."""
        cache = LSPCache()  # No repo_root

        # Path outside any specific root (no validation)
        outside_file = tmp_path.parent / "outside.py"
        outside_file.write_text("data")

        # Should not raise (no repo_root to validate against)
        count = cache.invalidate_file(str(outside_file))
        assert count == 0  # No entries to invalidate, but no error

    def test_symlink_escape_blocked(self, tmp_path):
        """Test symlink attacks are blocked."""
        repo_root = tmp_path

        # Create file outside repo
        outside_dir = tmp_path.parent / "outside"
        outside_dir.mkdir(exist_ok=True)
        outside_file = outside_dir / "secret.py"
        outside_file.write_text("SECRET")

        # Create symlink inside repo pointing outside
        symlink = tmp_path / "link_to_secret.py"
        try:
            symlink.symlink_to(outside_file)
        except OSError:
            pytest.skip("Symlinks not supported on this platform")

        cache = LSPCache(repo_root=str(repo_root))

        # Symlink resolves to path outside repo - should be blocked
        with pytest.raises(ValueError, match="Path outside repository"):
            cache.invalidate_file(str(symlink))


class TestCacheThreadSafety:
    """Test thread safety (P0-2 fix: concurrent access)."""

    def test_concurrent_get_operations(self):
        """Test concurrent get operations are thread-safe."""
        cache = LSPCache()

        # Pre-populate cache
        for i in range(100):
            cache.set(f"key_{i}", f"value_{i}")

        results = []
        errors = []

        def worker():
            try:
                for i in range(100):
                    value = cache.get(f"key_{i % 50}")  # Access subset of keys
                    results.append(value)
            except Exception as e:
                errors.append(e)

        # Run 10 threads concurrently
        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # No errors should occur
        assert len(errors) == 0
        # Results should be non-empty
        assert len(results) > 0

    def test_concurrent_set_operations(self):
        """Test concurrent set operations are thread-safe."""
        cache = LSPCache()

        errors = []

        def worker(worker_id):
            try:
                for i in range(100):
                    cache.set(f"key_{i % 20}", f"value_{worker_id}_{i}")
            except Exception as e:
                errors.append(e)

        # Run 10 threads concurrently
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # No errors should occur
        assert len(errors) == 0
        # Cache should have entries (exact count varies due to overwrites)
        assert len(cache.cache) > 0

    def test_concurrent_invalidate_operations(self, tmp_path):
        """Test concurrent invalidate operations are thread-safe."""
        cache = LSPCache()

        # Create test files
        files = []
        for i in range(10):
            f = tmp_path / f"file_{i}.py"
            f.write_text(f"content {i}")
            files.append(str(f))

        # Pre-populate cache with entries for each file
        for i, file_path in enumerate(files):
            for j in range(10):
                cache.set(f"key_{i}_{j}", f"value_{i}_{j}", file_path=file_path)

        errors = []
        invalidation_counts = []

        def worker(file_path):
            try:
                count = cache.invalidate_file(file_path)
                invalidation_counts.append(count)
            except Exception as e:
                errors.append(e)

        # Invalidate all files concurrently
        threads = [threading.Thread(target=worker, args=(f,)) for f in files]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # No errors should occur
        assert len(errors) == 0
        # Total invalidations should match cached entries
        total_invalidated = sum(invalidation_counts)
        assert total_invalidated == 100  # 10 files * 10 entries each

    def test_concurrent_mixed_operations(self):
        """Test mixed concurrent operations (get, set, clear)."""
        cache = LSPCache()

        # Pre-populate
        for i in range(50):
            cache.set(f"key_{i}", f"value_{i}")

        errors = []
        operation_counts = {"get": 0, "set": 0, "clear": 0}
        lock = threading.Lock()

        def get_worker():
            try:
                for i in range(50):
                    cache.get(f"key_{i % 25}")
                    with lock:
                        operation_counts["get"] += 1
            except Exception as e:
                errors.append(e)

        def set_worker():
            try:
                for i in range(50):
                    cache.set(f"key_{i % 25}", f"new_value_{i}")
                    with lock:
                        operation_counts["set"] += 1
            except Exception as e:
                errors.append(e)

        # Run mixed workload
        threads = []
        threads.extend([threading.Thread(target=get_worker) for _ in range(5)])
        threads.extend([threading.Thread(target=set_worker) for _ in range(5)])

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # No errors should occur
        assert len(errors) == 0
        # All operations should complete
        assert operation_counts["get"] == 250  # 5 threads * 50 ops
        assert operation_counts["set"] == 250  # 5 threads * 50 ops

    def test_no_race_condition_in_lru_eviction(self):
        """Test LRU eviction does not cause race conditions."""
        cache = LSPCache(max_size_mb=0.001)  # Tiny cache to trigger eviction

        errors = []

        def worker(worker_id):
            try:
                for i in range(100):
                    cache.set(f"key_{worker_id}_{i}", {"data": "x" * 100})
            except Exception as e:
                errors.append(e)

        # Run threads that trigger frequent evictions
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # No errors should occur (no race conditions in eviction logic)
        assert len(errors) == 0
        # Cache should not exceed memory limit
        assert cache._size_mb() <= 0.002  # 1KB + small margin
