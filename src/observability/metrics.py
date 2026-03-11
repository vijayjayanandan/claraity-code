"""
Metrics collection for performance and cost tracking.

Provides local SQLite-based metrics storage for tracking:
- LLM latency and token usage
- Tool execution times
- Cost tracking (complementary to Langfuse)

Engineering Principles:
- No emojis in code (Windows cp1252 compatibility)
- Local persistence (SQLite)
- Fast writes (no blocking)
- Simple queries for analysis
"""

import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class MetricEntry:
    """Single metric entry."""

    timestamp: str
    metric_name: str
    value: float
    tags: str  # JSON string


class MetricsCollector:
    """
    Collect and store metrics in SQLite.

    Provides local metrics storage for:
    - Performance tracking (latency, duration)
    - Resource usage (tokens, API calls)
    - Cost estimation

    Thread-safe for concurrent writes.
    """

    def __init__(self, db_path: str = ".clarity/metrics.db"):
        """
        Initialize metrics collector.

        Args:
            db_path: Path to SQLite database
        """
        self.db_path = Path(db_path)
        self._lock = threading.RLock()  # Reentrant lock for thread-safe operations
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        logger.info(f"[OK] MetricsCollector initialized: {self.db_path}")

    @contextmanager
    def _get_connection(self):
        """Thread-safe context manager for database connections."""
        with self._lock:  # Acquire lock for thread-safe database access
            conn = sqlite3.connect(self.db_path)
            try:
                yield conn
            finally:
                conn.close()

    def _init_schema(self):
        """Initialize database schema."""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    metric_name TEXT NOT NULL,
                    value REAL NOT NULL,
                    tags TEXT
                )
            """)

            # Create index for faster queries
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_metric_name_timestamp
                ON metrics(metric_name, timestamp)
            """)

            conn.commit()

    def record(self, metric_name: str, value: float, tags: dict[str, Any] | None = None):
        """
        Record a metric.

        Args:
            metric_name: Metric identifier (e.g., "llm_latency_ms", "tool_duration_ms")
            value: Metric value (numeric)
            tags: Optional tags for filtering (e.g., {"model": "gpt-4", "tool": "write_file"})
        """
        try:
            with self._get_connection() as conn:
                conn.execute(
                    "INSERT INTO metrics (timestamp, metric_name, value, tags) VALUES (?, ?, ?, ?)",
                    (datetime.now().isoformat(), metric_name, value, json.dumps(tags or {})),
                )
                conn.commit()
        except Exception as e:
            logger.error(f"[FAIL] Failed to record metric {metric_name}: {e}")

    def query(
        self,
        metric_name: str,
        since: datetime | None = None,
        until: datetime | None = None,
        tags: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> list[MetricEntry]:
        """
        Query metrics.

        Args:
            metric_name: Metric to query
            since: Start time (inclusive)
            until: End time (inclusive)
            tags: Filter by tags (exact match)
            limit: Maximum number of results

        Returns:
            list of metric entries
        """
        try:
            with self._get_connection() as conn:
                query = (
                    "SELECT timestamp, metric_name, value, tags FROM metrics WHERE metric_name = ?"
                )
                params = [metric_name]

                if since:
                    query += " AND timestamp >= ?"
                    params.append(since.isoformat())

                if until:
                    query += " AND timestamp <= ?"
                    params.append(until.isoformat())

                query += " ORDER BY timestamp DESC"

                if limit:
                    query += " LIMIT ?"
                    params.append(limit)

                cursor = conn.execute(query, params)
                rows = cursor.fetchall()

                # Filter by tags if specified
                if tags:
                    filtered_rows = []
                    for row in rows:
                        row_tags = json.loads(row[3]) if row[3] else {}
                        if all(row_tags.get(k) == v for k, v in tags.items()):
                            filtered_rows.append(row)
                    rows = filtered_rows

                return [MetricEntry(*row) for row in rows]

        except Exception as e:
            logger.error(f"[FAIL] Failed to query metric {metric_name}: {e}")
            return []

    def aggregate(
        self,
        metric_name: str,
        aggregation: str = "avg",
        since: datetime | None = None,
        until: datetime | None = None,
        tags: dict[str, Any] | None = None,
    ) -> float | None:
        """
        Aggregate metrics.

        Args:
            metric_name: Metric to aggregate
            aggregation: Aggregation function (avg, sum, min, max, count)
            since: Start time (inclusive)
            until: End time (inclusive)
            tags: Filter by tags

        Returns:
            Aggregated value
        """
        valid_aggregations = ["avg", "sum", "min", "max", "count"]
        if aggregation not in valid_aggregations:
            raise ValueError(f"Invalid aggregation: {aggregation}")

        try:
            with self._get_connection() as conn:
                query = f"SELECT {aggregation}(value) FROM metrics WHERE metric_name = ?"
                params = [metric_name]

                if since:
                    query += " AND timestamp >= ?"
                    params.append(since.isoformat())

                if until:
                    query += " AND timestamp <= ?"
                    params.append(until.isoformat())

                cursor = conn.execute(query, params)
                result = cursor.fetchone()[0]

                # Filter by tags if needed (requires fetching all rows)
                if tags and result is not None:
                    entries = self.query(metric_name, since, until, tags=tags)
                    values = [float(e.value) for e in entries]

                    if not values:
                        return None

                    if aggregation == "avg":
                        return sum(values) / len(values)
                    elif aggregation == "sum":
                        return sum(values)
                    elif aggregation == "min":
                        return min(values)
                    elif aggregation == "max":
                        return max(values)
                    elif aggregation == "count":
                        return len(values)

                return result

        except Exception as e:
            logger.error(f"[FAIL] Failed to aggregate metric {metric_name}: {e}")
            return None

    def get_stats(self, metric_name: str, hours: int = 24) -> dict[str, Any]:
        """
        Get statistics for a metric over the last N hours.

        Args:
            metric_name: Metric to analyze
            hours: Time window in hours

        Returns:
            Dictionary with avg, min, max, count
        """
        since = datetime.now() - timedelta(hours=hours)

        return {
            "metric": metric_name,
            "period_hours": hours,
            "avg": self.aggregate(metric_name, "avg", since=since),
            "min": self.aggregate(metric_name, "min", since=since),
            "max": self.aggregate(metric_name, "max", since=since),
            "count": self.aggregate(metric_name, "count", since=since),
        }

    def clear_old_metrics(self, days: int = 30):
        """
        Delete metrics older than N days.

        Args:
            days: Keep metrics from last N days
        """
        try:
            cutoff = (datetime.now() - timedelta(days=days)).isoformat()
            with self._get_connection() as conn:
                cursor = conn.execute("DELETE FROM metrics WHERE timestamp < ?", (cutoff,))
                deleted = cursor.rowcount
                conn.commit()
                logger.info(f"[OK] Deleted {deleted} metrics older than {days} days")
        except Exception as e:
            logger.error(f"[FAIL] Failed to clear old metrics: {e}")


# =============================================================================
# GLOBAL INSTANCE
# =============================================================================

# Singleton metrics collector
_metrics_instance: MetricsCollector | None = None


def get_metrics_collector() -> MetricsCollector:
    """Get global metrics collector instance."""
    global _metrics_instance
    if _metrics_instance is None:
        _metrics_instance = MetricsCollector()
    return _metrics_instance


# Convenience alias
metrics = get_metrics_collector()


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def record_llm_latency(latency_ms: float, model: str, operation: str = "call"):
    """
    Record LLM latency.

    Args:
        latency_ms: Latency in milliseconds
        model: Model name (e.g., "gpt-4", "deepseek-coder")
        operation: Operation type (e.g., "call", "stream")
    """
    metrics.record("llm_latency_ms", latency_ms, tags={"model": model, "operation": operation})


def record_token_usage(prompt_tokens: int, completion_tokens: int, model: str):
    """
    Record token usage.

    Args:
        prompt_tokens: Number of prompt tokens
        completion_tokens: Number of completion tokens
        model: Model name
    """
    metrics.record("prompt_tokens", prompt_tokens, tags={"model": model})
    metrics.record("completion_tokens", completion_tokens, tags={"model": model})
    metrics.record("total_tokens", prompt_tokens + completion_tokens, tags={"model": model})


def record_tool_execution(tool: str, duration_ms: float, success: bool):
    """
    Record tool execution.

    Args:
        tool: Tool name (e.g., "write_file", "run_command")
        duration_ms: Execution time in milliseconds
        success: Whether execution succeeded
    """
    metrics.record("tool_duration_ms", duration_ms, tags={"tool": tool, "success": success})


def record_cost_estimate(cost_usd: float, model: str, operation: str = "llm_call"):
    """
    Record estimated cost.

    Args:
        cost_usd: Estimated cost in USD
        model: Model name
        operation: Operation type
    """
    metrics.record("cost_usd", cost_usd, tags={"model": model, "operation": operation})


def get_session_stats(hours: int = 24) -> dict[str, Any]:
    """
    Get statistics for the current session.

    Args:
        hours: Time window in hours

    Returns:
        Dictionary with performance stats
    """
    return {
        "llm_latency": metrics.get_stats("llm_latency_ms", hours),
        "tool_duration": metrics.get_stats("tool_duration_ms", hours),
        "prompt_tokens": metrics.get_stats("prompt_tokens", hours),
        "completion_tokens": metrics.get_stats("completion_tokens", hours),
        "total_tokens": metrics.get_stats("total_tokens", hours),
        "estimated_cost": metrics.get_stats("cost_usd", hours),
    }


# =============================================================================
# MAINTENANCE
# =============================================================================


def cleanup_old_metrics(days: int = 30):
    """
    Clean up old metrics (call periodically).

    Args:
        days: Keep metrics from last N days
    """
    metrics.clear_old_metrics(days)
