"""Tests for ClarAIty Knowledge DB (claraity_db.py)."""

import json
import tempfile
import shutil
from pathlib import Path

import pytest

from src.claraity.claraity_db import (
    ClaraityStore,
    render_compact_briefing,
    render_module_detail,
    render_file_detail,
    render_search,
    render_impact,
    scan_files,
)


@pytest.fixture
def temp_store():
    """Create a ClaraityStore with a temporary DB."""
    temp_dir = tempfile.mkdtemp()
    db_path = Path(temp_dir) / "test_knowledge.db"
    store = ClaraityStore(str(db_path))
    yield store
    store.close()
    shutil.rmtree(temp_dir)


@pytest.fixture
def populated_store(temp_store):
    """Store with sample architecture data."""
    s = temp_store

    # System nodes
    s.add_node(id="sys-api", type="system", layer=1, name="External API",
               description="Third-party REST API")

    # Module nodes
    s.add_node(id="mod-core", type="module", layer=2, name="src/core/",
               description="Core application logic", risk_level="high",
               properties={"flow_rank": 1, "flow_col": 0})
    s.add_node(id="mod-db", type="module", layer=2, name="src/db/",
               description="Database access layer", risk_level="medium",
               properties={"flow_rank": 2, "flow_col": 0})

    # Component nodes
    s.add_node(id="comp-engine", type="component", layer=3, name="Engine",
               description="Main processing engine", file_path="src/core/engine.py",
               line_count=500, risk_level="high",
               properties={"key_methods": ["process", "run"]})
    s.add_node(id="comp-parser", type="component", layer=3, name="Parser",
               description="Input parser for various formats", file_path="src/core/parser.py",
               line_count=200, risk_level="low")
    s.add_node(id="comp-repo", type="component", layer=3, name="Repository",
               description="Data access repository", file_path="src/db/repo.py",
               line_count=300, risk_level="medium")

    # Containment edges
    s.add_edge("mod-core", "comp-engine", "contains")
    s.add_edge("mod-core", "comp-parser", "contains")
    s.add_edge("mod-db", "comp-repo", "contains")

    # Dependency edges
    s.add_edge("comp-engine", "comp-parser", "uses", label="Parses input")
    s.add_edge("comp-engine", "comp-repo", "calls", label="Stores results")
    s.add_edge("mod-core", "mod-db", "uses", label="Data persistence")

    # Decision
    s.add_node(id="dec-async", type="decision", layer=0, name="Async Processing",
               description="All processing must be async to avoid blocking",
               properties={"affects": ["comp-engine"], "rationale": "Non-blocking I/O"})
    s.add_edge("dec-async", "comp-engine", "constrains")

    # Invariant
    s.add_node(id="inv-validation", type="invariant", layer=0, name="Input Validation",
               description="All inputs must be validated before processing",
               properties={"severity": "critical", "affects": ["comp-parser"]})
    s.add_edge("inv-validation", "comp-parser", "constrains")

    # Flow
    s.add_node(id="flow-main", type="flow", layer=0, name="Main Processing Flow",
               description="Input -> Parse -> Process -> Store",
               properties={"trigger": "API request", "steps": ["Parse input", "Process data", "Store result"]})

    return s


# =============================================================================
# Schema & CRUD Tests
# =============================================================================

class TestClaraityStore:
    """Test ClaraityStore basic operations."""

    def test_create_store(self, temp_store):
        assert temp_store.conn is not None or temp_store.db_path.exists()

    def test_add_node(self, temp_store):
        nid = temp_store.add_node(
            id="test-1", type="component", layer=3, name="TestNode",
            description="A test node",
        )
        assert nid == "test-1"

        nodes = temp_store.get_all_nodes()
        assert len(nodes) == 1
        assert nodes[0]["name"] == "TestNode"

    def test_add_node_with_properties(self, temp_store):
        temp_store.add_node(
            id="test-2", type="component", layer=3, name="PropsNode",
            properties={"key_methods": ["foo", "bar"], "pattern": "singleton"},
        )
        nodes = temp_store.get_all_nodes()
        props = json.loads(nodes[0]["properties"])
        assert props["key_methods"] == ["foo", "bar"]
        assert props["pattern"] == "singleton"

    def test_add_node_replace(self, temp_store):
        """INSERT OR REPLACE should update existing nodes."""
        temp_store.add_node(id="test-1", type="component", layer=3, name="Original")
        temp_store.add_node(id="test-1", type="component", layer=3, name="Updated")
        nodes = temp_store.get_all_nodes()
        assert len(nodes) == 1
        assert nodes[0]["name"] == "Updated"

    def test_add_edge(self, temp_store):
        temp_store.add_node(id="a", type="component", layer=3, name="A")
        temp_store.add_node(id="b", type="component", layer=3, name="B")
        eid = temp_store.add_edge("a", "b", "uses", label="A uses B")
        assert eid.startswith("e-")

        edges = temp_store.get_all_edges()
        assert len(edges) == 1
        assert edges[0]["from_id"] == "a"
        assert edges[0]["to_id"] == "b"
        assert edges[0]["type"] == "uses"
        assert edges[0]["label"] == "A uses B"

    def test_add_edge_foreign_key(self, temp_store):
        """Edge should fail if nodes don't exist."""
        with pytest.raises(Exception):
            temp_store.add_edge("nonexistent-a", "nonexistent-b", "uses")

    def test_set_and_get_metadata(self, temp_store):
        temp_store.set_metadata("repo_name", "test-repo")
        temp_store.set_metadata("language", "python")
        meta = temp_store.get_metadata()
        assert meta["repo_name"] == "test-repo"
        assert meta["language"] == "python"

    def test_get_stats(self, populated_store):
        stats = populated_store.get_stats()
        assert stats["total_nodes"] > 0
        assert stats["total_edges"] > 0
        assert "component" in stats["node_types"]
        assert "uses" in stats["edge_types"]

    def test_make_id_deterministic(self):
        id1 = ClaraityStore._make_id("e", "a:b:uses")
        id2 = ClaraityStore._make_id("e", "a:b:uses")
        assert id1 == id2

    def test_make_id_different_inputs(self):
        id1 = ClaraityStore._make_id("e", "a:b:uses")
        id2 = ClaraityStore._make_id("e", "a:c:uses")
        assert id1 != id2

    def test_close_and_reopen(self, temp_store):
        temp_store.add_node(id="persist", type="component", layer=3, name="Persisted")
        db_path = str(temp_store.db_path)
        temp_store.close()

        # Reopen
        store2 = ClaraityStore(db_path)
        nodes = store2.get_all_nodes()
        assert len(nodes) == 1
        assert nodes[0]["name"] == "Persisted"
        store2.close()


# =============================================================================
# Export Tests
# =============================================================================

class TestExport:
    def test_export_graph_json(self, populated_store, tmp_path):
        out_path = str(tmp_path / "graph.json")
        graph = populated_store.export_graph_json(out_path)
        assert "nodes" in graph
        assert "edges" in graph
        assert "metadata" in graph
        assert "stats" in graph
        assert len(graph["nodes"]) > 0

        # Verify file written
        with open(out_path) as f:
            loaded = json.load(f)
        assert len(loaded["nodes"]) == len(graph["nodes"])

    def test_export_properties_parsed(self, populated_store, tmp_path):
        """Properties should be dicts, not JSON strings, in export."""
        graph = populated_store.export_graph_json(str(tmp_path / "g.json"))
        for n in graph["nodes"]:
            assert isinstance(n["properties"], dict), f"Node {n['id']} has string properties"


# =============================================================================
# Renderer Tests
# =============================================================================

class TestCompactBriefing:
    def test_renders_markdown(self, populated_store):
        md = render_compact_briefing(populated_store)
        assert "# Codebase:" in md
        assert "## Modules" in md
        assert "## Decisions" in md
        assert "## Invariants" in md

    def test_includes_modules(self, populated_store):
        md = render_compact_briefing(populated_store)
        assert "core" in md
        assert "db" in md

    def test_includes_decisions(self, populated_store):
        md = render_compact_briefing(populated_store)
        assert "Async Processing" in md

    def test_includes_invariants(self, populated_store):
        md = render_compact_briefing(populated_store)
        assert "Input Validation" in md
        assert "CRITICAL" in md


class TestModuleDetail:
    def test_renders_module(self, populated_store):
        md = render_module_detail(populated_store, "mod-core")
        assert "# Module: core" in md
        assert "Engine" in md
        assert "Parser" in md
        assert "src/core/engine.py" in md

    def test_shows_dependencies(self, populated_store):
        md = render_module_detail(populated_store, "mod-core")
        assert "Depends on" in md or "Used by" in md

    def test_nonexistent_module(self, populated_store):
        md = render_module_detail(populated_store, "mod-nonexistent")
        assert "not found" in md

    def test_shows_files(self, populated_store):
        """Module detail should show file nodes if present."""
        # Add a file node
        populated_store.add_node(id="file-test", type="file", layer=4, name="engine.py",
                                 file_path="src/core/engine.py", line_count=500,
                                 properties={"role": "source"})
        populated_store.add_edge("mod-core", "file-test", "contains")

        md = render_module_detail(populated_store, "mod-core")
        assert "Files" in md


class TestFileDetail:
    @pytest.fixture(autouse=True)
    def _add_file_nodes(self, populated_store):
        """Add layer 4 file nodes matching component file_paths."""
        populated_store.add_node(id="file-engine", type="file", layer=4, name="engine.py",
                                  file_path="src/core/engine.py", line_count=500,
                                  properties={"role": "source", "module": "mod-core"})
        populated_store.add_edge("mod-core", "file-engine", "contains")

    def test_renders_file_with_component(self, populated_store):
        md = render_file_detail(populated_store, "src/core/engine.py")
        assert "# File: src/core/engine.py" in md
        assert "Engine" in md
        assert "Depends On" in md

    def test_shows_applicable_decisions(self, populated_store):
        md = render_file_detail(populated_store, "src/core/engine.py")
        assert "Async Processing" in md

    def test_nonexistent_file(self, populated_store):
        md = render_file_detail(populated_store, "src/nonexistent.py")
        assert "not found" in md


class TestSearch:
    def test_search_by_name(self, populated_store):
        md = render_search(populated_store, "Engine")
        assert "Engine" in md
        assert "matches" in md

    def test_search_by_description(self, populated_store):
        md = render_search(populated_store, "processing")
        assert "Engine" in md or "Async" in md

    def test_search_no_results(self, populated_store):
        md = render_search(populated_store, "xyznonexistent")
        assert "No results" in md

    def test_search_includes_neighbors(self, populated_store):
        md = render_search(populated_store, "Engine")
        assert "Depends on" in md or "Used by" in md


class TestImpact:
    def test_impact_with_dependents(self, populated_store):
        md = render_impact(populated_store, "comp-parser")
        assert "Impact Analysis" in md
        assert "Engine" in md  # Engine depends on Parser

    def test_impact_no_dependents(self, populated_store):
        md = render_impact(populated_store, "comp-engine")
        # Engine is at the top — nothing depends on it (in this test data)
        assert "Impact Analysis" in md

    def test_impact_nonexistent(self, populated_store):
        md = render_impact(populated_store, "comp-nonexistent")
        assert "not found" in md

    def test_impact_depth_classification(self, populated_store):
        """BFS depth should correctly classify direct vs indirect dependents."""
        # In test data: Engine uses Parser and calls Repo
        # So Parser's dependents: Engine (direct, depth 1)
        # Repo's dependents: Engine (direct, depth 1)
        md = render_impact(populated_store, "comp-repo")
        assert "Direct dependents" in md
        assert "Engine" in md

    def test_impact_multiple_direct_dependents(self, temp_store):
        """Multiple components at same BFS level should all be 'direct'."""
        s = temp_store
        s.add_node(id="target", type="component", layer=3, name="Target")
        s.add_node(id="dep-a", type="component", layer=3, name="DepA")
        s.add_node(id="dep-b", type="component", layer=3, name="DepB")
        s.add_node(id="dep-c", type="component", layer=3, name="DepC")
        s.add_edge("dep-a", "target", "uses")
        s.add_edge("dep-b", "target", "uses")
        s.add_edge("dep-c", "target", "calls")

        md = render_impact(s, "target")
        assert "Direct dependents (3)" in md
        assert "DepA" in md
        assert "DepB" in md
        assert "DepC" in md
        # No indirect section since all are direct
        assert "Indirect" not in md


# =============================================================================
# File Scanner Tests
# =============================================================================

class TestScanFiles:
    def test_scan_creates_file_nodes(self, temp_store, tmp_path):
        """Scan a temp directory with Python files."""
        # Create temp source files
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "__init__.py").write_text('"""Test package."""\n')
        (src_dir / "main.py").write_text('"""Main entry point."""\n\ndef main():\n    pass\n')
        (src_dir / "utils.py").write_text('# Utility functions\n\ndef helper():\n    pass\n')

        scan_files(temp_store, root=str(src_dir))

        nodes = temp_store.get_all_nodes()
        file_nodes = [n for n in nodes if n["type"] == "file"]
        assert len(file_nodes) == 3

    def test_scan_extracts_descriptions(self, temp_store, tmp_path):
        """Scanner should extract docstrings."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "documented.py").write_text('"""This is a well-documented module."""\n')

        scan_files(temp_store, root=str(src_dir))

        nodes = temp_store.get_all_nodes()
        file_nodes = [n for n in nodes if n["type"] == "file"]
        assert len(file_nodes) == 1
        assert "well-documented" in file_nodes[0]["description"]

    def test_scan_skips_pycache(self, temp_store, tmp_path):
        src_dir = tmp_path / "src"
        cache_dir = src_dir / "__pycache__"
        cache_dir.mkdir(parents=True)
        (src_dir / "real.py").write_text("# Real file\n")
        (cache_dir / "cached.py").write_text("# Cached\n")

        scan_files(temp_store, root=str(src_dir))

        nodes = temp_store.get_all_nodes()
        file_nodes = [n for n in nodes if n["type"] == "file"]
        assert len(file_nodes) == 1
        assert file_nodes[0]["name"] == "real.py"

    def test_scan_language_agnostic(self, temp_store, tmp_path):
        """Scanner should handle non-Python files."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "app.ts").write_text("// TypeScript application\nexport function main() {}\n")
        (src_dir / "lib.go").write_text("// Go library\npackage main\n")
        (src_dir / "readme.md").write_text("# Not source\n")

        scan_files(temp_store, root=str(src_dir), extensions=[".ts", ".go"])

        nodes = temp_store.get_all_nodes()
        file_nodes = [n for n in nodes if n["type"] == "file"]
        assert len(file_nodes) == 2
        names = {n["name"] for n in file_nodes}
        assert "app.ts" in names
        assert "lib.go" in names
        assert "readme.md" not in names

    def test_scan_detects_roles(self, temp_store, tmp_path):
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "__init__.py").write_text("")
        (src_dir / "test_foo.py").write_text("# Tests\n")
        (src_dir / "__main__.py").write_text("# Entry\n")
        (src_dir / "utils.py").write_text("# Utils\n")

        scan_files(temp_store, root=str(src_dir))

        nodes = temp_store.get_all_nodes()
        file_nodes = {n["name"]: json.loads(n["properties"]) for n in nodes if n["type"] == "file"}
        assert file_nodes["__init__.py"]["role"] == "package init"
        assert file_nodes["test_foo.py"]["role"] == "test"
        assert file_nodes["__main__.py"]["role"] == "entry point"
        assert file_nodes["utils.py"]["role"] == "source"

    def test_scan_nonexistent_root(self, temp_store):
        """Should handle missing root gracefully."""
        scan_files(temp_store, root="/nonexistent/path")
        nodes = temp_store.get_all_nodes()
        assert len(nodes) == 0
