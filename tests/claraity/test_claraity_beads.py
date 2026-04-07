"""Tests for ClarAIty Beads task tracker (claraity_beads.py)."""

import json
import sqlite3
import tempfile
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from src.claraity.claraity_beads import (
    BeadStore, render_tasks_md, render_bead_detail,
    VALID_STATUSES, VALID_ISSUE_TYPES, VALID_DEP_TYPES,
    BLOCKING_DEP_TYPES, ASSOCIATION_DEP_TYPES,
)


@pytest.fixture
def temp_beads():
    """Create a BeadStore with a temporary DB."""
    temp_dir = tempfile.mkdtemp()
    db_path = Path(temp_dir) / "test_beads.db"
    store = BeadStore(str(db_path))
    yield store
    store.close()
    shutil.rmtree(temp_dir)


# =============================================================================
# Bead CRUD Tests
# =============================================================================

class TestBeadCRUD:
    def test_create_bead(self, temp_beads):
        bid = temp_beads.add_bead(title="Test task", description="A test", priority=3)
        assert bid.startswith("bd-")
        assert len(bid) == 11  # bd- + 8 hex

    def test_create_bead_hash_deterministic(self, temp_beads):
        bid1 = temp_beads.add_bead(title="Same title")
        # Second call with same title should replace (INSERT OR REPLACE)
        bid2 = temp_beads.add_bead(title="Same title")
        assert bid1 == bid2

    def test_create_bead_different_titles(self, temp_beads):
        bid1 = temp_beads.add_bead(title="Task A")
        bid2 = temp_beads.add_bead(title="Task B")
        assert bid1 != bid2

    def test_get_bead(self, temp_beads):
        bid = temp_beads.add_bead(title="Fetch me", description="desc", priority=2, tags=["bug"])
        bead = temp_beads.get_bead(bid)
        assert bead is not None
        assert bead["title"] == "Fetch me"
        assert bead["description"] == "desc"
        assert bead["priority"] == 2
        assert bead["status"] == "open"
        assert json.loads(bead["tags"]) == ["bug"]

    def test_get_nonexistent_bead(self, temp_beads):
        assert temp_beads.get_bead("bd-nope") is None

    def test_get_all_beads(self, temp_beads):
        temp_beads.add_bead(title="A", priority=2)
        temp_beads.add_bead(title="B", priority=1)
        temp_beads.add_bead(title="C", priority=3)
        beads = temp_beads.get_all_beads()
        assert len(beads) == 3
        # Should be sorted by priority
        assert beads[0]["priority"] <= beads[1]["priority"]

    def test_get_all_beads_filter_status(self, temp_beads):
        b1 = temp_beads.add_bead(title="Open task")
        b2 = temp_beads.add_bead(title="Closed task")
        temp_beads.update_status(b2, "closed")
        open_beads = temp_beads.get_all_beads(status="open")
        assert len(open_beads) == 1
        assert open_beads[0]["title"] == "Open task"


# =============================================================================
# Status Lifecycle Tests
# =============================================================================

class TestStatusLifecycle:
    def test_start_task(self, temp_beads):
        bid = temp_beads.add_bead(title="Start me")
        temp_beads.update_status(bid, "in_progress")
        bead = temp_beads.get_bead(bid)
        assert bead["status"] == "in_progress"

    def test_close_task(self, temp_beads):
        bid = temp_beads.add_bead(title="Close me")
        temp_beads.update_status(bid, "closed", summary="Done!")
        bead = temp_beads.get_bead(bid)
        assert bead["status"] == "closed"
        assert bead["summary"] == "Done!"
        assert bead["closed_at"] is not None

    def test_close_without_summary(self, temp_beads):
        bid = temp_beads.add_bead(title="Close no summary")
        temp_beads.update_status(bid, "closed")
        bead = temp_beads.get_bead(bid)
        assert bead["status"] == "closed"
        assert bead["summary"] is None


# =============================================================================
# Dependency Tests
# =============================================================================

class TestDependencies:
    def test_add_dependency(self, temp_beads):
        a = temp_beads.add_bead(title="Blocker")
        b = temp_beads.add_bead(title="Blocked")
        did = temp_beads.add_dependency(a, b, "blocks")
        assert did.startswith("bd-")

    def test_get_dependencies(self, temp_beads):
        a = temp_beads.add_bead(title="Blocker")
        b = temp_beads.add_bead(title="Blocked")
        temp_beads.add_dependency(a, b, "blocks")
        deps = temp_beads.get_dependencies(b)
        assert len(deps["blockers"]) == 1
        assert deps["blockers"][0]["title"] == "Blocker"

    def test_get_blocking(self, temp_beads):
        a = temp_beads.add_bead(title="Blocker")
        b = temp_beads.add_bead(title="Blocked")
        temp_beads.add_dependency(a, b, "blocks")
        deps = temp_beads.get_dependencies(a)
        assert len(deps["blocking"]) == 1
        assert deps["blocking"][0]["title"] == "Blocked"

    def test_duplicate_dependency_ignored(self, temp_beads):
        a = temp_beads.add_bead(title="A")
        b = temp_beads.add_bead(title="B")
        temp_beads.add_dependency(a, b, "blocks")
        temp_beads.add_dependency(a, b, "blocks")  # duplicate
        deps = temp_beads.get_dependencies(b)
        assert len(deps["blockers"]) == 1


# =============================================================================
# Ready Queue Tests
# =============================================================================

class TestReadyQueue:
    def test_all_open_are_ready(self, temp_beads):
        temp_beads.add_bead(title="A")
        temp_beads.add_bead(title="B")
        ready = temp_beads.get_ready()
        assert len(ready) == 2

    def test_blocked_not_ready(self, temp_beads):
        a = temp_beads.add_bead(title="Blocker")
        b = temp_beads.add_bead(title="Blocked")
        temp_beads.add_dependency(a, b, "blocks")
        ready = temp_beads.get_ready()
        ready_ids = {r["id"] for r in ready}
        assert a in ready_ids
        assert b not in ready_ids

    def test_unblocked_after_close(self, temp_beads):
        a = temp_beads.add_bead(title="Blocker")
        b = temp_beads.add_bead(title="Blocked")
        temp_beads.add_dependency(a, b, "blocks")

        # B is blocked
        ready = temp_beads.get_ready()
        assert b not in {r["id"] for r in ready}

        # Close A -> B becomes ready
        temp_beads.update_status(a, "closed")
        ready = temp_beads.get_ready()
        assert b in {r["id"] for r in ready}

    def test_chain_dependency(self, temp_beads):
        """A blocks B blocks C. Only A should be ready."""
        a = temp_beads.add_bead(title="First")
        b = temp_beads.add_bead(title="Second")
        c = temp_beads.add_bead(title="Third")
        temp_beads.add_dependency(a, b, "blocks")
        temp_beads.add_dependency(b, c, "blocks")

        ready = temp_beads.get_ready()
        ready_ids = {r["id"] for r in ready}
        assert a in ready_ids
        assert b not in ready_ids
        assert c not in ready_ids

        # Close A -> B ready, C still blocked
        temp_beads.update_status(a, "closed")
        ready = temp_beads.get_ready()
        ready_ids = {r["id"] for r in ready}
        assert b in ready_ids
        assert c not in ready_ids

        # Close B -> C ready
        temp_beads.update_status(b, "closed")
        ready = temp_beads.get_ready()
        ready_ids = {r["id"] for r in ready}
        assert c in ready_ids

    def test_multiple_blockers(self, temp_beads):
        """Task with multiple blockers is ready only when ALL are closed."""
        a = temp_beads.add_bead(title="Blocker A")
        b = temp_beads.add_bead(title="Blocker B")
        c = temp_beads.add_bead(title="Needs both")
        temp_beads.add_dependency(a, c, "blocks")
        temp_beads.add_dependency(b, c, "blocks")

        # Close only A -> C still blocked by B
        temp_beads.update_status(a, "closed")
        ready = temp_beads.get_ready()
        assert c not in {r["id"] for r in ready}

        # Close B -> C ready
        temp_beads.update_status(b, "closed")
        ready = temp_beads.get_ready()
        assert c in {r["id"] for r in ready}

    def test_ready_sorted_by_priority(self, temp_beads):
        temp_beads.add_bead(title="Low", priority=5)
        temp_beads.add_bead(title="High", priority=1)
        temp_beads.add_bead(title="Medium", priority=3)
        ready = temp_beads.get_ready()
        priorities = [r["priority"] for r in ready]
        assert priorities == sorted(priorities)

    def test_closed_not_in_ready(self, temp_beads):
        a = temp_beads.add_bead(title="Already done")
        temp_beads.update_status(a, "closed")
        ready = temp_beads.get_ready()
        assert len(ready) == 0

    def test_circular_dependency_excludes_both(self, temp_beads):
        """A blocks B and B blocks A. Neither should be ready."""
        a = temp_beads.add_bead(title="Circular A")
        b = temp_beads.add_bead(title="Circular B")
        temp_beads.add_dependency(a, b, "blocks")
        temp_beads.add_dependency(b, a, "blocks")
        ready = temp_beads.get_ready()
        ready_ids = {r["id"] for r in ready}
        assert a not in ready_ids
        assert b not in ready_ids


# =============================================================================
# Input Validation Tests
# =============================================================================

class TestInputValidation:
    """Test store-level validation of dep_type and issue_type."""

    def test_invalid_dep_type_raises(self, temp_beads):
        a = temp_beads.add_bead(title="A")
        b = temp_beads.add_bead(title="B")
        with pytest.raises(ValueError, match="Invalid dep_type"):
            temp_beads.add_dependency(a, b, "blokcs")  # typo

    def test_valid_dep_types_accepted(self, temp_beads):
        a = temp_beads.add_bead(title="Source")
        b = temp_beads.add_bead(title="Target")
        for dep_type in VALID_DEP_TYPES:
            temp_beads.add_dependency(a, b, dep_type)

    def test_invalid_issue_type_raises(self, temp_beads):
        with pytest.raises(ValueError, match="Invalid issue_type"):
            temp_beads.add_bead(title="Bad type", issue_type="feature-request")

    def test_valid_issue_types_accepted(self, temp_beads):
        for i, issue_type in enumerate(VALID_ISSUE_TYPES):
            temp_beads.add_bead(title=f"Type test {i}", issue_type=issue_type)


# =============================================================================
# Notes & Refs Tests
# =============================================================================

class TestNotesAndRefs:
    def test_add_note(self, temp_beads):
        bid = temp_beads.add_bead(title="Notable")
        temp_beads.add_note(bid, "Progress update", author="agent")
        notes = temp_beads.get_notes(bid)
        assert len(notes) == 1
        assert notes[0]["content"] == "Progress update"
        assert notes[0]["author"] == "agent"

    def test_add_ref(self, temp_beads):
        bid = temp_beads.add_bead(title="Linked")
        temp_beads.add_ref(bid, "comp-engine", "modifies")
        refs = temp_beads.get_refs(bid)
        assert len(refs) == 1
        assert refs[0]["component_id"] == "comp-engine"
        assert refs[0]["ref_type"] == "modifies"

    def test_parent_child(self, temp_beads):
        parent = temp_beads.add_bead(title="Epic")
        child = temp_beads.add_bead(title="Subtask", parent_id=parent)
        children = temp_beads.get_children(parent)
        assert len(children) == 1
        assert children[0]["title"] == "Subtask"


# =============================================================================
# Stats Tests
# =============================================================================

class TestValidation:
    """Test input validation (from code review fixes)."""

    def test_invalid_status_raises(self, temp_beads):
        bid = temp_beads.add_bead(title="Validate me")
        with pytest.raises(ValueError, match="Invalid status"):
            temp_beads.update_status(bid, "done")  # not a valid status

    def test_update_nonexistent_raises(self, temp_beads):
        with pytest.raises(ValueError, match="not found"):
            temp_beads.update_status("bd-nonexistent", "closed")

    def test_insert_ignore_preserves_existing(self, temp_beads):
        """INSERT OR IGNORE should not overwrite existing bead."""
        bid = temp_beads.add_bead(title="Original task", priority=1)
        temp_beads.update_status(bid, "in_progress")

        # Re-add with same title (same hash = same ID)
        bid2 = temp_beads.add_bead(title="Original task", priority=5)
        assert bid == bid2

        # Status should still be in_progress, not reset to open
        bead = temp_beads.get_bead(bid)
        assert bead["status"] == "in_progress"
        assert bead["priority"] == 1  # original priority preserved


class TestStats:
    def test_stats_empty(self, temp_beads):
        stats = temp_beads.get_stats()
        assert stats["total"] == 0
        assert stats["dependencies"] == 0

    def test_stats_populated(self, temp_beads):
        a = temp_beads.add_bead(title="A")
        b = temp_beads.add_bead(title="B")
        temp_beads.add_dependency(a, b, "blocks")
        temp_beads.update_status(a, "closed")

        stats = temp_beads.get_stats()
        assert stats["total"] == 2
        assert stats["dependencies"] == 1
        assert stats["by_status"]["open"] == 1
        assert stats["by_status"]["closed"] == 1


# =============================================================================
# Markdown Renderer Tests
# =============================================================================

class TestRenderTasksMd:
    def test_empty_tasks(self, temp_beads):
        md = render_tasks_md(temp_beads)
        assert "No tasks found" in md

    def test_renders_ready_section(self, temp_beads):
        temp_beads.add_bead(title="Ready task", priority=1, tags=["feature"])
        md = render_tasks_md(temp_beads)
        assert "## Ready" in md
        assert "Ready task" in md
        assert "feature" in md

    def test_renders_blocked_section(self, temp_beads):
        a = temp_beads.add_bead(title="Blocker")
        b = temp_beads.add_bead(title="Blocked task")
        temp_beads.add_dependency(a, b, "blocks")
        md = render_tasks_md(temp_beads)
        assert "## Blocked" in md
        assert "Blocked task" in md
        assert "Blocker" in md  # shows what blocks it

    def test_renders_closed_section(self, temp_beads):
        a = temp_beads.add_bead(title="Done task")
        temp_beads.update_status(a, "closed", summary="Completed successfully")
        md = render_tasks_md(temp_beads)
        assert "## Closed" in md
        assert "Done task" in md

    def test_renders_in_progress(self, temp_beads):
        a = temp_beads.add_bead(title="Working on it")
        temp_beads.update_status(a, "in_progress")
        md = render_tasks_md(temp_beads)
        assert "## In Progress" in md
        assert "Working on it" in md

    def test_renders_stats(self, temp_beads):
        temp_beads.add_bead(title="A")
        temp_beads.add_bead(title="B")
        md = render_tasks_md(temp_beads)
        assert "2 tasks" in md
        assert "2 open" in md


# =============================================================================
# Phase 1 Schema Expansion Tests
# =============================================================================


class TestExpandedStatuses:
    """Test the 7 statuses: open, in_progress, blocked, deferred, closed, pinned, hooked."""

    def test_all_valid_statuses_accepted(self, temp_beads):
        for status in VALID_STATUSES:
            bid = temp_beads.add_bead(title=f"Task for {status}")
            temp_beads.update_status(bid, status)
            bead = temp_beads.get_bead(bid)
            assert bead["status"] == status

    def test_blocked_status(self, temp_beads):
        bid = temp_beads.add_bead(title="Manually blocked")
        temp_beads.update_status(bid, "blocked")
        bead = temp_beads.get_bead(bid)
        assert bead["status"] == "blocked"

    def test_deferred_status(self, temp_beads):
        bid = temp_beads.add_bead(title="Park this")
        temp_beads.update_status(bid, "deferred")
        bead = temp_beads.get_bead(bid)
        assert bead["status"] == "deferred"

    def test_pinned_status(self, temp_beads):
        bid = temp_beads.add_bead(title="Always visible")
        temp_beads.update_status(bid, "pinned")
        bead = temp_beads.get_bead(bid)
        assert bead["status"] == "pinned"

    def test_hooked_status(self, temp_beads):
        bid = temp_beads.add_bead(title="Claimed by worker")
        temp_beads.update_status(bid, "hooked")
        bead = temp_beads.get_bead(bid)
        assert bead["status"] == "hooked"

    def test_invalid_status_still_raises(self, temp_beads):
        bid = temp_beads.add_bead(title="Bad status")
        with pytest.raises(ValueError, match="Invalid status"):
            temp_beads.update_status(bid, "completed")


class TestNewBeadFields:
    """Test new columns added to the beads table."""

    def test_issue_type(self, temp_beads):
        bid = temp_beads.add_bead(title="Login bug", issue_type="bug")
        bead = temp_beads.get_bead(bid)
        assert bead["issue_type"] == "bug"

    def test_issue_type_default(self, temp_beads):
        bid = temp_beads.add_bead(title="Default type")
        bead = temp_beads.get_bead(bid)
        assert bead["issue_type"] == "task"

    def test_external_ref(self, temp_beads):
        bid = temp_beads.add_bead(title="Jira linked", external_ref="jira-CC-42")
        bead = temp_beads.get_bead(bid)
        assert bead["external_ref"] == "jira-CC-42"

    def test_due_at(self, temp_beads):
        bid = temp_beads.add_bead(title="Has deadline", due_at="2026-04-15T00:00:00+00:00")
        bead = temp_beads.get_bead(bid)
        assert bead["due_at"] == "2026-04-15T00:00:00+00:00"

    def test_defer_until(self, temp_beads):
        bid = temp_beads.add_bead(title="Future work", defer_until="2026-05-01T00:00:00+00:00")
        bead = temp_beads.get_bead(bid)
        assert bead["defer_until"] == "2026-05-01T00:00:00+00:00"

    def test_estimated_minutes(self, temp_beads):
        bid = temp_beads.add_bead(title="Quick fix", estimated_minutes=30)
        bead = temp_beads.get_bead(bid)
        assert bead["estimated_minutes"] == 30

    def test_metadata_json(self, temp_beads):
        meta = {"complexity": "high", "files": ["agent.py", "app.py"]}
        bid = temp_beads.add_bead(title="Rich metadata", metadata=meta)
        bead = temp_beads.get_bead(bid)
        assert json.loads(bead["metadata"]) == meta

    def test_design_and_acceptance(self, temp_beads):
        bid = temp_beads.add_bead(
            title="Well-specified task",
            design="Use compare-and-swap pattern",
            acceptance_criteria="Concurrent claims must not both succeed",
        )
        bead = temp_beads.get_bead(bid)
        assert bead["design"] == "Use compare-and-swap pattern"
        assert bead["acceptance_criteria"] == "Concurrent claims must not both succeed"

    def test_last_activity_set_on_create(self, temp_beads):
        bid = temp_beads.add_bead(title="Track activity")
        bead = temp_beads.get_bead(bid)
        assert bead["last_activity"] is not None

    def test_close_reason(self, temp_beads):
        bid = temp_beads.add_bead(title="Close with reason")
        temp_beads.update_status(bid, "closed", summary="Done", close_reason="wontfix")
        bead = temp_beads.get_bead(bid)
        assert bead["close_reason"] == "wontfix"
        assert bead["summary"] == "Done"


class TestAtomicClaim:
    """Test compare-and-swap claim operation."""

    def test_claim_unassigned(self, temp_beads):
        bid = temp_beads.add_bead(title="Unclaimed task")
        ok = temp_beads.claim(bid, "claraity:session-abc")
        assert ok is True
        bead = temp_beads.get_bead(bid)
        assert bead["assignee"] == "claraity:session-abc"
        assert bead["status"] == "in_progress"

    def test_claim_idempotent(self, temp_beads):
        bid = temp_beads.add_bead(title="Claim twice")
        temp_beads.claim(bid, "claraity:session-abc")
        ok = temp_beads.claim(bid, "claraity:session-abc")
        assert ok is True  # idempotent, no error

    def test_claim_rejected_if_taken(self, temp_beads):
        bid = temp_beads.add_bead(title="Contested task")
        temp_beads.claim(bid, "claraity:session-aaa")
        ok = temp_beads.claim(bid, "claraity:session-bbb")
        assert ok is False
        # Original claimant still owns it
        bead = temp_beads.get_bead(bid)
        assert bead["assignee"] == "claraity:session-aaa"

    def test_claim_nonexistent_raises(self, temp_beads):
        with pytest.raises(ValueError, match="not found"):
            temp_beads.claim("bd-nope", "agent")

    def test_claim_records_event(self, temp_beads):
        bid = temp_beads.add_bead(title="Event tracked claim")
        temp_beads.claim(bid, "claraity:session-xyz")
        events = temp_beads.get_events(bid)
        claim_events = [e for e in events if e["event_type"] == "claimed"]
        assert len(claim_events) == 1
        assert claim_events[0]["new_value"] == "claraity:session-xyz"


class TestReopen:
    """Test reopening closed and deferred tasks."""

    def test_reopen_closed(self, temp_beads):
        bid = temp_beads.add_bead(title="Reopen me")
        temp_beads.update_status(bid, "closed", summary="Done")
        temp_beads.reopen(bid)
        bead = temp_beads.get_bead(bid)
        assert bead["status"] == "open"

    def test_reopen_deferred(self, temp_beads):
        bid = temp_beads.add_bead(title="Undefer me")
        temp_beads.defer(bid, until="2026-12-31T00:00:00+00:00")
        temp_beads.reopen(bid)
        bead = temp_beads.get_bead(bid)
        assert bead["status"] == "open"
        assert bead["defer_until"] is None  # cleared

    def test_reopen_nonexistent_raises(self, temp_beads):
        with pytest.raises(ValueError, match="not found"):
            temp_beads.reopen("bd-nope")

    def test_reopen_records_event(self, temp_beads):
        bid = temp_beads.add_bead(title="Event tracked reopen")
        temp_beads.update_status(bid, "closed")
        temp_beads.reopen(bid)
        events = temp_beads.get_events(bid)
        reopen_events = [e for e in events if e["event_type"] == "reopened"]
        assert len(reopen_events) == 1
        assert reopen_events[0]["old_value"] == "closed"
        assert reopen_events[0]["new_value"] == "open"


class TestDefer:
    """Test defer operation with optional until date."""

    def test_defer_without_date(self, temp_beads):
        bid = temp_beads.add_bead(title="Park indefinitely")
        temp_beads.defer(bid)
        bead = temp_beads.get_bead(bid)
        assert bead["status"] == "deferred"
        assert bead["defer_until"] is None

    def test_defer_with_date(self, temp_beads):
        bid = temp_beads.add_bead(title="Park until April")
        temp_beads.defer(bid, until="2026-04-15T00:00:00+00:00")
        bead = temp_beads.get_bead(bid)
        assert bead["status"] == "deferred"
        assert bead["defer_until"] == "2026-04-15T00:00:00+00:00"

    def test_defer_nonexistent_raises(self, temp_beads):
        with pytest.raises(ValueError, match="not found"):
            temp_beads.defer("bd-nope")


class TestTypedDependencies:
    """Test blocking and non-blocking dependency types."""

    def test_blocking_dep_types(self, temp_beads):
        a = temp_beads.add_bead(title="Blocker")
        b = temp_beads.add_bead(title="Blocked")
        for dep_type in BLOCKING_DEP_TYPES:
            temp_beads.add_dependency(a, b, dep_type)
        deps = temp_beads.get_dependencies(b)
        assert len(deps["blockers"]) == len(BLOCKING_DEP_TYPES)

    def test_non_blocking_dep_types(self, temp_beads):
        a = temp_beads.add_bead(title="Source")
        b = temp_beads.add_bead(title="Related")
        temp_beads.add_dependency(a, b, "discovered-from")
        temp_beads.add_dependency(a, b, "related")
        deps = temp_beads.get_dependencies(b)
        assert len(deps["blockers"]) == 0
        assert len(deps["associations"]) == 2

    def test_non_blocking_deps_dont_affect_ready(self, temp_beads):
        a = temp_beads.add_bead(title="Source")
        b = temp_beads.add_bead(title="Related task")
        temp_beads.add_dependency(a, b, "related")
        ready = temp_beads.get_ready()
        ready_ids = {r["id"] for r in ready}
        assert b in ready_ids  # non-blocking, so b is still ready

    def test_conditional_blocks_affects_ready(self, temp_beads):
        a = temp_beads.add_bead(title="Must fail first")
        b = temp_beads.add_bead(title="Runs on failure")
        temp_beads.add_dependency(a, b, "conditional-blocks")
        ready = temp_beads.get_ready()
        ready_ids = {r["id"] for r in ready}
        assert a in ready_ids
        assert b not in ready_ids

    def test_dependency_created_by(self, temp_beads):
        a = temp_beads.add_bead(title="A")
        b = temp_beads.add_bead(title="B")
        temp_beads.add_dependency(a, b, "blocks", created_by="claraity:session-xyz")
        with temp_beads._cursor() as cur:
            cur.execute("SELECT created_by FROM dependencies WHERE from_id=? AND to_id=?", (a, b))
            row = cur.fetchone()
            assert row["created_by"] == "claraity:session-xyz"

    def test_dependency_metadata(self, temp_beads):
        a = temp_beads.add_bead(title="Gate")
        b = temp_beads.add_bead(title="Waiter")
        temp_beads.add_dependency(a, b, "waits-for", metadata={"gate": "all-children"})
        with temp_beads._cursor() as cur:
            cur.execute("SELECT metadata FROM dependencies WHERE from_id=? AND to_id=?", (a, b))
            row = cur.fetchone()
            assert json.loads(row["metadata"])["gate"] == "all-children"


class TestReadyQueueExpanded:
    """Test ready queue with new features: defer_until, pinned, typed deps."""

    def test_deferred_excluded_from_ready(self, temp_beads):
        a = temp_beads.add_bead(title="Deferred task")
        temp_beads.update_status(a, "deferred")
        ready = temp_beads.get_ready()
        assert a not in {r["id"] for r in ready}

    def test_pinned_excluded_from_ready(self, temp_beads):
        bid = temp_beads.add_bead(title="Pinned context")
        temp_beads.update_status(bid, "pinned")
        ready = temp_beads.get_ready()
        assert bid not in {r["id"] for r in ready}

    def test_future_defer_until_excluded(self, temp_beads):
        future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        bid = temp_beads.add_bead(title="Future task", defer_until=future)
        ready = temp_beads.get_ready()
        assert bid not in {r["id"] for r in ready}

    def test_past_defer_until_included(self, temp_beads):
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        bid = temp_beads.add_bead(title="Past deferred", defer_until=past)
        ready = temp_beads.get_ready()
        assert bid in {r["id"] for r in ready}


class TestEvents:
    """Test event audit trail."""

    def test_status_change_records_event(self, temp_beads):
        bid = temp_beads.add_bead(title="Track me")
        temp_beads.update_status(bid, "in_progress")
        events = temp_beads.get_events(bid)
        # Should have 'created' + 'status_changed'
        types = [e["event_type"] for e in events]
        assert "created" in types
        assert "status_changed" in types

    def test_event_captures_old_and_new(self, temp_beads):
        bid = temp_beads.add_bead(title="Transition me")
        temp_beads.update_status(bid, "in_progress")
        temp_beads.update_status(bid, "closed")
        events = temp_beads.get_events(bid)
        status_events = [e for e in events if e["event_type"] == "status_changed"]
        assert status_events[0]["old_value"] == "open"
        assert status_events[0]["new_value"] == "in_progress"
        assert status_events[1]["old_value"] == "in_progress"
        assert status_events[1]["new_value"] == "closed"

    def test_get_events_empty(self, temp_beads):
        # Bead that doesn't exist returns empty
        events = temp_beads.get_events("bd-nope")
        assert events == []

    def test_add_event_public_api(self, temp_beads):
        bid = temp_beads.add_bead(title="Manual event")
        eid = temp_beads.add_event(bid, "custom_action", comment="Did something")
        assert eid.startswith("ev-")
        events = temp_beads.get_events(bid)
        custom = [e for e in events if e["event_type"] == "custom_action"]
        assert len(custom) == 1
        assert custom[0]["comment"] == "Did something"


class TestUpdateMetadata:
    """Test metadata merge operation."""

    def test_merge_metadata(self, temp_beads):
        bid = temp_beads.add_bead(title="Meta task", metadata={"a": 1})
        temp_beads.update_metadata(bid, {"b": 2})
        bead = temp_beads.get_bead(bid)
        meta = json.loads(bead["metadata"])
        assert meta == {"a": 1, "b": 2}

    def test_overwrite_metadata_key(self, temp_beads):
        bid = temp_beads.add_bead(title="Overwrite", metadata={"x": "old"})
        temp_beads.update_metadata(bid, {"x": "new"})
        bead = temp_beads.get_bead(bid)
        assert json.loads(bead["metadata"])["x"] == "new"

    def test_metadata_nonexistent_raises(self, temp_beads):
        with pytest.raises(ValueError, match="not found"):
            temp_beads.update_metadata("bd-nope", {"a": 1})


class TestJSONLRoundTrip:
    """Test export/import preserves new columns."""

    def test_round_trip_new_fields(self, temp_beads):
        bid = temp_beads.add_bead(
            title="Full featured",
            issue_type="bug",
            external_ref="jira-CC-99",
            due_at="2026-06-01T00:00:00+00:00",
            estimated_minutes=120,
            metadata={"severity": "high"},
            design="Use retry pattern",
            acceptance_criteria="No data loss",
        )
        temp_beads.update_status(bid, "closed", summary="Fixed", close_reason="resolved")
        temp_beads.add_event(bid, "reviewed", comment="LGTM")

        # Export
        jsonl_path = str(temp_beads.db_path.with_suffix(".jsonl"))
        temp_beads.export_jsonl(jsonl_path)

        # Import into new DB
        new_db = str(temp_beads.db_path.parent / "reimported.db")
        store2 = BeadStore.import_jsonl(jsonl_path, new_db)
        try:
            bead = store2.get_bead(bid)
            assert bead["issue_type"] == "bug"
            assert bead["external_ref"] == "jira-CC-99"
            assert bead["due_at"] == "2026-06-01T00:00:00+00:00"
            assert bead["estimated_minutes"] == 120
            assert json.loads(bead["metadata"])["severity"] == "high"
            assert bead["design"] == "Use retry pattern"
            assert bead["acceptance_criteria"] == "No data loss"
            assert bead["close_reason"] == "resolved"

            events = store2.get_events(bid)
            reviewed = [e for e in events if e["event_type"] == "reviewed"]
            assert len(reviewed) == 1
        finally:
            store2.close()

    def test_import_old_format_backward_compat(self, temp_beads):
        """Old JSONL files without new columns should import with defaults."""
        jsonl_path = str(temp_beads.db_path.parent / "old_format.jsonl")
        # Write a minimal old-format record
        with open(jsonl_path, "w") as f:
            rec = {
                "_t": "bead",
                "id": "bd-oldstyle",
                "title": "Old bead",
                "description": "From old version",
                "status": "open",
                "priority": 3,
                "parent_id": None,
                "assignee": "agent",
                "tags": "[]",
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
                "closed_at": None,
                "summary": None,
            }
            f.write(json.dumps(rec) + "\n")

        new_db = str(temp_beads.db_path.parent / "from_old.db")
        store2 = BeadStore.import_jsonl(jsonl_path, new_db)
        try:
            bead = store2.get_bead("bd-oldstyle")
            assert bead is not None
            assert bead["title"] == "Old bead"
            assert bead["issue_type"] == "task"  # default
            assert bead["pinned"] == 0  # default
            assert bead["metadata"] == "{}"  # default
        finally:
            store2.close()


class TestMigration:
    """Test that existing DBs get migrated with new columns."""

    def test_old_db_gets_new_columns(self):
        """Simulate an old DB (only original columns) and verify migration adds new ones."""
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / "old.db"
            # Create DB with old schema only
            conn = sqlite3.connect(str(db_path))
            conn.execute("""
                CREATE TABLE beads (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT,
                    status TEXT NOT NULL DEFAULT 'open', priority INTEGER NOT NULL DEFAULT 5,
                    parent_id TEXT, assignee TEXT DEFAULT 'agent', tags TEXT DEFAULT '[]',
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    closed_at TEXT, summary TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE dependencies (
                    id TEXT PRIMARY KEY, from_id TEXT NOT NULL, to_id TEXT NOT NULL,
                    dep_type TEXT NOT NULL DEFAULT 'blocks', created_at TEXT NOT NULL,
                    UNIQUE(from_id, to_id, dep_type)
                )
            """)
            conn.execute("""
                CREATE TABLE bead_refs (
                    id TEXT PRIMARY KEY, bead_id TEXT NOT NULL,
                    component_id TEXT NOT NULL, ref_type TEXT NOT NULL DEFAULT 'modifies'
                )
            """)
            conn.execute("""
                CREATE TABLE notes (
                    id TEXT PRIMARY KEY, bead_id TEXT NOT NULL, content TEXT NOT NULL,
                    author TEXT DEFAULT 'agent', created_at TEXT NOT NULL
                )
            """)
            # Insert an old-style bead
            conn.execute(
                "INSERT INTO beads (id, title, status, priority, tags, created_at, updated_at) "
                "VALUES ('bd-old1', 'Old task', 'open', 3, '[]', '2026-01-01', '2026-01-01')"
            )
            conn.commit()
            conn.close()

            # Open with new BeadStore (should trigger migration)
            store = BeadStore(str(db_path))
            try:
                bead = store.get_bead("bd-old1")
                assert bead is not None
                assert bead["title"] == "Old task"
                # New columns should exist with defaults
                assert bead["issue_type"] == "task"
                assert bead["pinned"] == 0
                assert bead["metadata"] == "{}"

                # Should be able to use new features on old data
                store.update_metadata("bd-old1", {"migrated": True})
                bead = store.get_bead("bd-old1")
                assert json.loads(bead["metadata"])["migrated"] is True
            finally:
                store.close()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestTouch:
    """Test last_activity heartbeat."""

    def test_touch_updates_last_activity(self, temp_beads):
        bid = temp_beads.add_bead(title="Touch me")
        bead_before = temp_beads.get_bead(bid)
        import time; time.sleep(0.05)  # ensure timestamp differs
        temp_beads.touch(bid)
        bead_after = temp_beads.get_bead(bid)
        assert bead_after["last_activity"] > bead_before["last_activity"]

    def test_touch_nonexistent_no_error(self, temp_beads):
        # touch is fire-and-forget; nonexistent ID just updates 0 rows
        temp_beads.touch("bd-nope")  # should not raise


class TestSessionWork:
    """Test session-scoped task queries."""

    def test_get_session_work(self, temp_beads):
        bid = temp_beads.add_bead(title="Session task")
        temp_beads.claim(bid, "claraity:session-abc")
        work = temp_beads.get_session_work("abc")
        assert len(work) == 1
        assert work[0]["id"] == bid

    def test_get_session_work_excludes_other_sessions(self, temp_beads):
        a = temp_beads.add_bead(title="Task A")
        b = temp_beads.add_bead(title="Task B")
        temp_beads.claim(a, "claraity:session-aaa")
        temp_beads.claim(b, "claraity:session-bbb")
        work_a = temp_beads.get_session_work("aaa")
        assert len(work_a) == 1
        assert work_a[0]["id"] == a
        work_b = temp_beads.get_session_work("bbb")
        assert len(work_b) == 1
        assert work_b[0]["id"] == b

    def test_get_session_work_empty(self, temp_beads):
        temp_beads.add_bead(title="Unclaimed")
        assert temp_beads.get_session_work("xyz") == []


class TestReleaseSession:
    """Test graceful session cleanup."""

    def test_release_returns_to_pool(self, temp_beads):
        bid = temp_beads.add_bead(title="Release me")
        temp_beads.claim(bid, "claraity:session-abc")
        count = temp_beads.release_session("abc")
        assert count == 1
        bead = temp_beads.get_bead(bid)
        assert bead["status"] == "open"
        assert bead["assignee"] == "agent"

    def test_release_records_event(self, temp_beads):
        bid = temp_beads.add_bead(title="Release event")
        temp_beads.claim(bid, "claraity:session-abc")
        temp_beads.release_session("abc")
        events = temp_beads.get_events(bid)
        released = [e for e in events if e["event_type"] == "released"]
        assert len(released) == 1
        assert "session abc ended" in released[0]["comment"]

    def test_release_only_affects_own_session(self, temp_beads):
        a = temp_beads.add_bead(title="A")
        b = temp_beads.add_bead(title="B")
        temp_beads.claim(a, "claraity:session-aaa")
        temp_beads.claim(b, "claraity:session-bbb")
        temp_beads.release_session("aaa")
        # A released, B still claimed
        assert temp_beads.get_bead(a)["status"] == "open"
        assert temp_beads.get_bead(b)["status"] == "in_progress"
        assert temp_beads.get_bead(b)["assignee"] == "claraity:session-bbb"

    def test_release_no_tasks_returns_zero(self, temp_beads):
        assert temp_beads.release_session("nonexistent") == 0

    def test_release_does_not_touch_closed(self, temp_beads):
        bid = temp_beads.add_bead(title="Already closed")
        temp_beads.claim(bid, "claraity:session-abc")
        temp_beads.update_status(bid, "closed", summary="Done")
        count = temp_beads.release_session("abc")
        assert count == 0  # closed tasks not released
        assert temp_beads.get_bead(bid)["status"] == "closed"


class TestEpicGuard:
    """Test that epics cannot be claimed."""

    def test_claim_epic_raises(self, temp_beads):
        bid = temp_beads.add_bead(title="Big initiative", issue_type="epic")
        with pytest.raises(ValueError, match="Cannot claim an epic"):
            temp_beads.claim(bid, "claraity:session-abc")

    def test_claim_task_succeeds(self, temp_beads):
        bid = temp_beads.add_bead(title="Regular task", issue_type="task")
        assert temp_beads.claim(bid, "claraity:session-abc") is True

    def test_claim_bug_succeeds(self, temp_beads):
        bid = temp_beads.add_bead(title="Bug fix", issue_type="bug")
        assert temp_beads.claim(bid, "claraity:session-abc") is True


class TestStaleClaims:
    """Test stale claim detection in ready queue."""

    def test_fresh_claim_not_in_ready(self, temp_beads):
        bid = temp_beads.add_bead(title="Freshly claimed")
        temp_beads.claim(bid, "claraity:session-abc")
        ready = temp_beads.get_ready()
        assert bid not in {r["id"] for r in ready}

    def test_stale_claim_appears_in_ready(self, temp_beads):
        bid = temp_beads.add_bead(title="Stale task")
        temp_beads.claim(bid, "claraity:session-dead")
        # Simulate staleness by backdating last_activity
        stale_time = (
            datetime.now(timezone.utc) - timedelta(minutes=60)
        ).isoformat()
        with temp_beads._cursor() as cur:
            cur.execute(
                "UPDATE beads SET last_activity=? WHERE id=?",
                (stale_time, bid),
            )
        ready = temp_beads.get_ready()
        assert bid in {r["id"] for r in ready}

    def test_stale_epic_not_in_ready(self, temp_beads):
        """Epics never appear in ready even if stale."""
        bid = temp_beads.add_bead(title="Old epic", issue_type="epic")
        # Manually set in_progress + stale (bypass claim guard for test)
        stale_time = (
            datetime.now(timezone.utc) - timedelta(minutes=60)
        ).isoformat()
        with temp_beads._cursor() as cur:
            cur.execute(
                "UPDATE beads SET status='in_progress', assignee='someone', last_activity=? WHERE id=?",
                (stale_time, bid),
            )
        ready = temp_beads.get_ready()
        assert bid not in {r["id"] for r in ready}

    def test_unclaimed_open_still_in_ready(self, temp_beads):
        """Regular open tasks still appear in ready (regression check)."""
        bid = temp_beads.add_bead(title="Normal open task")
        ready = temp_beads.get_ready()
        assert bid in {r["id"] for r in ready}


class TestRenderExpanded:
    """Test markdown renderer with new statuses and fields."""

    def test_renders_deferred_section(self, temp_beads):
        bid = temp_beads.add_bead(title="Parked task")
        temp_beads.defer(bid, until="2026-06-01")
        md = render_tasks_md(temp_beads)
        assert "## Deferred" in md
        assert "Parked task" in md
        assert "2026-06-01" in md

    def test_renders_issue_type_badge(self, temp_beads):
        temp_beads.add_bead(title="Login crash", issue_type="bug", priority=1)
        md = render_tasks_md(temp_beads)
        assert "(bug)" in md

    def test_renders_blocked_and_deferred_stats(self, temp_beads):
        a = temp_beads.add_bead(title="A")
        b = temp_beads.add_bead(title="B")
        temp_beads.update_status(a, "blocked")
        temp_beads.update_status(b, "deferred")
        md = render_tasks_md(temp_beads)
        assert "1 blocked" in md
        assert "1 deferred" in md

    def test_in_progress_shows_description(self, temp_beads):
        bid = temp_beads.add_bead(
            title="Working task",
            description="Extract auth middleware into separate module",
        )
        temp_beads.update_status(bid, "in_progress")
        md = render_tasks_md(temp_beads)
        assert "## In Progress" in md
        assert "Extract auth middleware" in md

    def test_in_progress_shows_latest_notes(self, temp_beads):
        bid = temp_beads.add_bead(title="Noted task")
        temp_beads.update_status(bid, "in_progress")
        temp_beads.add_note(bid, "Started extraction")
        temp_beads.add_note(bid, "Middleware moved, 3 call sites left")
        temp_beads.add_note(bid, "Updated agent.py call site")
        md = render_tasks_md(temp_beads)
        # Should show latest 2 notes, not the first one
        assert "3 call sites left" in md
        assert "Updated agent.py" in md
        assert "Started extraction" not in md


class TestRenderBeadDetail:
    """Test full bead detail rendering."""

    def test_renders_all_fields(self, temp_beads):
        bid = temp_beads.add_bead(
            title="Full detail task",
            description="This is the description",
            design="Use compare-and-swap",
            acceptance_criteria="No race conditions",
            issue_type="bug",
            external_ref="jira-CC-42",
            estimated_minutes=60,
            priority=1,
            tags=["urgent", "auth"],
        )
        temp_beads.add_note(bid, "Progress note 1")
        md = render_bead_detail(temp_beads, bid)
        assert "Full detail task" in md
        assert "This is the description" in md
        assert "Use compare-and-swap" in md
        assert "No race conditions" in md
        assert "bug" in md
        assert "jira-CC-42" in md
        assert "60 min" in md
        assert "P1" in md
        assert "urgent" in md
        assert "Progress note 1" in md

    def test_renders_dependencies(self, temp_beads):
        a = temp_beads.add_bead(title="Blocker task")
        b = temp_beads.add_bead(title="Detailed task")
        temp_beads.add_dependency(a, b, "blocks")
        temp_beads.add_dependency(a, b, "discovered-from")
        md = render_bead_detail(temp_beads, b)
        assert "Blocked By" in md
        assert "Blocker task" in md
        assert "Related" in md
        assert "discovered-from" in md

    def test_not_found(self, temp_beads):
        md = render_bead_detail(temp_beads, "bd-nope")
        assert "not found" in md
