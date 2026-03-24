"""Tests for ClarAIty Beads task tracker (claraity_beads.py)."""

import json
import tempfile
import shutil
from pathlib import Path

import pytest

from src.claraity.claraity_beads import BeadStore, render_tasks_md


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
