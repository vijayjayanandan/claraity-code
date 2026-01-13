# LSP Cache

**Status**: Ready for implementation
**Estimated Time**: 0.5 hours
**Lines of Code**: ~200 LOC
**Dependencies**: collections.OrderedDict, pathlib

---

## Overview

The **LSPCache** provides in-memory caching for LSP query results with:

- **LRU eviction** - Removes least recently used entries when memory limit reached
- **File-change invalidation** - Automatically invalidates cache when files are edited
- **TTL (Time To Live)** - Entries expire after configured time
- **Memory management** - Configurable size limit (default: 10MB)

### Why Caching Matters

LSP queries are relatively fast (5-50ms), but caching provides:
- **70%+ hit rate** for typical workflows (repeated queries to same symbols)
- **Reduced LSP server load** (fewer queries = less memory/CPU usage)
- **Improved responsiveness** (cache hits are <1ms)

---

## Architecture

```
LSPCache
    │
    ├─> cache: OrderedDict[str, CacheEntry]
    ├─> max_size_mb: int (10MB default)
    ├─> ttl_seconds: int (300s = 5 min default)
    │
    └─> Methods:
        ├─> get(key) -> Optional[Any]
        ├─> set(key, value, file_path)
        ├─> invalidate_file(file_path)
        ├─> clear()
        ├─> _file_modified(file_path, cached_mtime) -> bool
        ├─> _get_mtime(file_path) -> float
        └─> _size_mb() -> float
```

---

## Public Interface

### Class: LSPCache

```python
from collections import OrderedDict
from typing import Optional, Any
from dataclasses import dataclass
from pathlib import Path
import time

@dataclass
class CacheEntry:
    """Single cache entry with metadata."""
    value: Any
    timestamp: float
    file_path: Optional[str]
    file_mtime: Optional[float]

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
        ttl_seconds: int = 300
    ):
        """Initialize cache."""

    def get(self, key: str) -> Optional[Any]:
        """Get value from cache (None if miss or expired)."""

    def set(
        self,
        key: str,
        value: Any,
        file_path: Optional[str] = None
    ) -> None:
        """Set cache entry."""

    def invalidate_file(self, file_path: str) -> int:
        """Invalidate all entries for a file."""

    def clear(self) -> None:
        """Clear all cache entries."""
```

---

## Implementation Details

### Method: __init__

```python
def __init__(
    self,
    max_size_mb: int = 10,
    ttl_seconds: int = 300
):
    """
    Initialize LSP cache.

    Args:
        max_size_mb: Maximum cache size in MB (default: 10MB)
        ttl_seconds: Time-to-live in seconds (default: 300s = 5 min)
    """
    self.max_size_mb = max_size_mb
    self.ttl_seconds = ttl_seconds

    # OrderedDict maintains insertion order for LRU
    self.cache: OrderedDict[str, CacheEntry] = OrderedDict()

    import logging
    self.logger = logging.getLogger("code_intelligence.cache")
```

---

### Method: get

```python
def get(self, key: str) -> Optional[Any]:
    """
    Get value from cache.

    Returns None if:
    - Key not in cache (cache miss)
    - Entry expired (TTL exceeded)
    - File modified since caching

    Args:
        key: Cache key (e.g., "def:auth.py:45:10")

    Returns:
        Cached value or None
    """
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
            self.invalidate_file(entry.file_path)
            return None

    # Move to end (mark as recently used for LRU)
    self.cache.move_to_end(key)

    self.logger.debug(f"Cache hit: {key}")
    return entry.value
```

**Example**:
```python
cache = LSPCache(max_size_mb=10, ttl_seconds=300)

# Cache miss (not yet cached)
result = cache.get("def:auth.py:45:10")
assert result is None

# Set value
cache.set("def:auth.py:45:10", {"uri": "...", "range": {...}}, file_path="auth.py")

# Cache hit
result = cache.get("def:auth.py:45:10")
assert result is not None
```

---

### Method: set

```python
def set(
    self,
    key: str,
    value: Any,
    file_path: Optional[str] = None
) -> None:
    """
    Set cache entry.

    If cache size exceeds limit, evicts LRU entries.

    Args:
        key: Cache key
        value: Value to cache
        file_path: Optional file path (for invalidation on file change)
    """
    # Get file modification time (for invalidation)
    file_mtime = self._get_mtime(file_path) if file_path else None

    # Create entry
    entry = CacheEntry(
        value=value,
        timestamp=time.time(),
        file_path=file_path,
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
```

**Example**:
```python
cache = LSPCache(max_size_mb=0.001)  # Tiny cache for testing

# Fill cache
for i in range(100):
    cache.set(f"key_{i}", {"data": "x" * 100})  # Each entry ~100 bytes

# Oldest entries evicted automatically (LRU)
assert cache.get("key_0") is None  # Evicted
assert cache.get("key_99") is not None  # Still in cache
```

---

### Method: invalidate_file

```python
def invalidate_file(self, file_path: str) -> int:
    """
    Invalidate all cache entries for a file.

    Called when file is edited to ensure fresh data on next query.

    Args:
        file_path: Path to file

    Returns:
        Number of entries invalidated
    """
    # Normalize path
    file_path = str(Path(file_path).resolve())

    # Find all entries for this file
    keys_to_delete = [
        key for key, entry in self.cache.items()
        if entry.file_path and Path(entry.file_path).resolve() == Path(file_path)
    ]

    # Delete entries
    for key in keys_to_delete:
        del self.cache[key]

    if keys_to_delete:
        self.logger.info(f"Invalidated {len(keys_to_delete)} entries for {file_path}")

    return len(keys_to_delete)
```

**Example**:
```python
cache = LSPCache()

# Cache multiple queries for auth.py
cache.set("def:auth.py:45:10", {...}, file_path="auth.py")
cache.set("refs:auth.py:45:10", {...}, file_path="auth.py")
cache.set("hover:auth.py:45:10", {...}, file_path="auth.py")

# User edits auth.py
cache.invalidate_file("auth.py")

# All entries invalidated
assert cache.get("def:auth.py:45:10") is None
assert cache.get("refs:auth.py:45:10") is None
assert cache.get("hover:auth.py:45:10") is None
```

---

### Method: clear

```python
def clear(self) -> None:
    """Clear all cache entries."""
    self.cache.clear()
    self.logger.info("Cache cleared")
```

---

### Method: _file_modified (Private)

```python
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
```

---

### Method: _get_mtime (Private)

```python
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
```

---

### Method: _size_mb (Private)

```python
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
    """Estimate object size in bytes."""
    if isinstance(obj, str):
        return len(obj)
    elif isinstance(obj, (int, float)):
        return 8
    elif isinstance(obj, dict):
        return 100 + sum(self._estimate_size(k) + self._estimate_size(v) for k, v in obj.items())
    elif isinstance(obj, list):
        return 100 + sum(self._estimate_size(item) for item in obj)
    else:
        return 100  # Default
```

---

## Cache Key Format

**Convention**: `{operation}:{file_path}:{line}:{column}`

**Examples**:
- `def:src/auth.py:45:10` - Definition query
- `refs:src/auth.py:45:10` - References query
- `hover:src/auth.py:45:10` - Hover query
- `doc_symbols:src/auth.py` - Document symbols (no line/column)

**Why this format?**
- Unique per query (same params = same key)
- Human-readable (easy to debug)
- Supports file-level invalidation (all keys with same file_path)

---

## Acceptance Criteria

### Functional Requirements

- [ ] **Cache hit/miss** works correctly
- [ ] **LRU eviction** removes oldest entries when memory limit exceeded
- [ ] **TTL expiration** removes entries after configured time
- [ ] **File invalidation** clears entries when file modified
- [ ] **Memory limit** respected (cache size ≤ max_size_mb)

### Performance Targets

- [ ] **Cache hit**: <1ms
- [ ] **Cache miss**: <1ms (lookup time)
- [ ] **Hit rate**: >70% for typical workflows
- [ ] **Memory overhead**: <10MB for default config

### Quality Metrics

- [ ] **Test coverage**: 95%+
- [ ] **All paths tested**: Hit, miss, eviction, expiration, invalidation
- [ ] **Edge cases**: Empty cache, full cache, file deleted

---

## Testing Strategy

### Unit Tests (tests/test_lsp_cache.py)

```python
import pytest
from pathlib import Path
import time

def test_cache_hit_miss():
    """Test basic cache hit and miss."""
    cache = LSPCache()

    # Miss
    assert cache.get("key1") is None

    # Set
    cache.set("key1", {"value": "data"})

    # Hit
    assert cache.get("key1") == {"value": "data"}

def test_lru_eviction():
    """Test LRU eviction when memory limit exceeded."""
    cache = LSPCache(max_size_mb=0.001)  # Tiny cache

    # Add entries until eviction
    for i in range(100):
        cache.set(f"key_{i}", {"data": "x" * 100})

    # Oldest entries evicted
    assert cache.get("key_0") is None
    assert cache.get("key_99") is not None

def test_ttl_expiration():
    """Test TTL expiration."""
    cache = LSPCache(ttl_seconds=1)  # 1 second TTL

    cache.set("key1", {"value": "data"})
    assert cache.get("key1") is not None

    # Wait for expiration
    time.sleep(1.1)

    # Expired
    assert cache.get("key1") is None

def test_file_invalidation(tmp_path):
    """Test file-change invalidation."""
    test_file = tmp_path / "test.py"
    test_file.write_text("def hello(): pass")

    cache = LSPCache()
    cache.set("def:test.py:1:0", {"value": "data"}, file_path=str(test_file))

    # Cache hit
    assert cache.get("def:test.py:1:0") is not None

    # Modify file
    time.sleep(0.01)  # Ensure mtime changes
    test_file.write_text("def hello(): pass  # modified")

    # Cache invalidated
    assert cache.get("def:test.py:1:0") is None
```

---

## Implementation Patterns

### Pattern: Automatic Invalidation on File Edit

```python
# In LSPClientManager or tools
async def request_definition(self, file_path, line, column):
    # Check cache (handles TTL and file-change automatically)
    cache_key = f"def:{file_path}:{line}:{column}"
    cached = self.cache.get(cache_key)  # Returns None if file modified
    if cached:
        return cached

    # Query LSP
    result = await server.request_definition(file_path, line, column)

    # Cache with file path (enables invalidation)
    self.cache.set(cache_key, result, file_path=file_path)

    return result
```

### Pattern: Manual Invalidation After Edits

```python
# In edit_file tool
def execute(self, file_path, old_text, new_text):
    # Edit file
    content = Path(file_path).read_text()
    content = content.replace(old_text, new_text)
    Path(file_path).write_text(content)

    # Invalidate LSP cache for this file
    if hasattr(self, 'lsp_manager') and self.lsp_manager:
        self.lsp_manager.cache.invalidate_file(file_path)
        print(f"[INFO] Invalidated LSP cache for {file_path}")

    return ToolResult(success=True, output="File edited and cache invalidated")
```

### Antipattern: Caching Without File Path

```python
# BAD: No file_path means no auto-invalidation
cache.set("def:auth.py:45:10", result)  # File edits won't invalidate!

# GOOD: Include file_path for auto-invalidation
cache.set("def:auth.py:45:10", result, file_path="auth.py")
```

---

## File Location

**Path**: `src/code_intelligence/cache.py`

---

**Status**: ✅ Ready for implementation
**Next**: Read [03_ORCHESTRATOR.md](03_ORCHESTRATOR.md)
