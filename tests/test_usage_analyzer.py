"""
Tests for Usage Analyzer

Tests the accurate detection of component usage relationships.
Follows Anthropic mindset: comprehensive testing for core features.
"""

import ast
import pytest
from src.clarity.analyzer.usage_analyzer import (
    UsageAnalyzer,
    UsageVisitor,
    UsageContext,
    extract_imported_names
)


class TestExtractImportedNames:
    """Test extraction of imported names from AST."""

    def test_extract_from_import(self):
        """Test extracting names from 'from x import y' statements."""
        code = """
from src.core.agent import CodingAgent
from src.memory.manager import MemoryManager, WorkingMemory
"""
        tree = ast.parse(code)
        names = extract_imported_names(tree)

        assert "CodingAgent" in names
        assert "MemoryManager" in names
        assert "WorkingMemory" in names
        assert len(names) == 3

    def test_extract_import_statement(self):
        """Test extracting from 'import x' statements."""
        code = """
import src.core.agent
import os
"""
        tree = ast.parse(code)
        names = extract_imported_names(tree)

        assert "agent" in names  # Last part of src.core.agent
        assert "os" not in names  # Non-src imports ignored

    def test_empty_module(self):
        """Test empty module returns empty set."""
        code = ""
        tree = ast.parse(code)
        names = extract_imported_names(tree)

        assert len(names) == 0


class TestUsageContext:
    """Test usage context tracking."""

    def test_resolve_instance_var(self):
        """Test resolving instance variables."""
        context = UsageContext()
        context.instance_vars["memory"] = "MemoryManager"

        assert context.resolve_name("memory") == "MemoryManager"
        assert context.resolve_name("unknown") is None

    def test_resolve_local_var(self):
        """Test resolving local variables."""
        context = UsageContext()
        context.local_vars["mem"] = "MemoryManager"

        assert context.resolve_name("mem") == "MemoryManager"

    def test_resolve_direct_class(self):
        """Test resolving direct class names."""
        context = UsageContext()
        context.available_names.add("MemoryManager")

        assert context.resolve_name("MemoryManager") == "MemoryManager"

    def test_resolution_priority(self):
        """Test instance vars take priority over local vars."""
        context = UsageContext()
        context.instance_vars["x"] = "TypeA"
        context.local_vars["x"] = "TypeB"
        context.available_names.add("TypeC")

        assert context.resolve_name("x") == "TypeA"  # Instance var wins


class TestUsageVisitor:
    """Test usage detection visitor."""

    def test_detect_instantiation_assignment(self):
        """Test detecting instantiation in assignment."""
        code = """
class Agent:
    def __init__(self):
        self.memory = MemoryManager()
"""
        tree = ast.parse(code)
        class_node = tree.body[0]  # Agent class
        init_method = class_node.body[0]  # __init__ method

        context = UsageContext(available_names={"MemoryManager"})
        context.current_method = "__init__"

        visitor = UsageVisitor(context)
        visitor.visit(init_method)

        # Should detect instantiation
        usages = [u for u in visitor.usages if u.usage_type == "instantiation"]
        assert len(usages) == 1
        assert usages[0].used_name == "MemoryManager"

        # Should track instance variable
        assert "memory" in context.instance_vars
        assert context.instance_vars["memory"] == "MemoryManager"

    def test_detect_method_call(self):
        """Test detecting method calls."""
        code = """
class Agent:
    def execute(self):
        self.memory.store()
"""
        tree = ast.parse(code)
        class_node = tree.body[0]
        execute_method = class_node.body[0]

        context = UsageContext(available_names={"MemoryManager"})
        context.instance_vars["memory"] = "MemoryManager"
        context.current_method = "execute"

        visitor = UsageVisitor(context)
        visitor.visit(execute_method)

        # Should detect method call
        usages = [u for u in visitor.usages if u.usage_type == "method_call"]
        assert len(usages) == 1
        assert usages[0].used_name == "MemoryManager"

    def test_detect_direct_instantiation(self):
        """Test detecting direct instantiation without assignment."""
        code = """
class Agent:
    def process(self):
        MemoryManager().store()
"""
        tree = ast.parse(code)
        class_node = tree.body[0]
        method = class_node.body[0]

        context = UsageContext(available_names={"MemoryManager"})
        context.current_method = "process"

        visitor = UsageVisitor(context)
        visitor.visit(method)

        # Should detect instantiation
        usages = [u for u in visitor.usages if u.usage_type == "instantiation"]
        assert len(usages) == 1
        assert usages[0].used_name == "MemoryManager"

    def test_ignore_unknown_classes(self):
        """Test that unknown classes are ignored."""
        code = """
class Agent:
    def __init__(self):
        self.data = dict()
        self.list = list()
"""
        tree = ast.parse(code)
        class_node = tree.body[0]
        init_method = class_node.body[0]

        context = UsageContext(available_names={"MemoryManager"})  # Not dict/list
        context.current_method = "__init__"

        visitor = UsageVisitor(context)
        visitor.visit(init_method)

        # Should not detect dict/list (not in available_names)
        assert len(visitor.usages) == 0

    def test_local_variable_tracking(self):
        """Test tracking local variables."""
        code = """
class Agent:
    def process(self):
        mem = MemoryManager()
        mem.store()
"""
        tree = ast.parse(code)
        class_node = tree.body[0]
        method = class_node.body[0]

        context = UsageContext(available_names={"MemoryManager"})
        context.current_method = "process"

        visitor = UsageVisitor(context)
        visitor.visit(method)

        # Should track local variable
        assert "mem" in context.local_vars
        assert context.local_vars["mem"] == "MemoryManager"

        # Should detect both instantiation and method call
        assert len(visitor.usages) >= 2
        instantiations = [u for u in visitor.usages if u.usage_type == "instantiation"]
        method_calls = [u for u in visitor.usages if u.usage_type == "method_call"]
        assert len(instantiations) >= 1
        assert len(method_calls) >= 1


class TestUsageAnalyzer:
    """Test usage analyzer."""

    def test_analyze_simple_class(self):
        """Test analyzing a simple class with usage."""
        code = """
class CodingAgent:
    def __init__(self):
        self.memory = MemoryManager()

    def execute(self):
        self.memory.store()
"""
        tree = ast.parse(code)
        class_node = tree.body[0]

        analyzer = UsageAnalyzer(available_components={"MemoryManager"})
        imported_names = {"MemoryManager"}

        relationships = analyzer.analyze_class(
            class_node, "CODINGAGENT", imported_names
        )

        # Should detect usage of MemoryManager
        assert len(relationships) >= 1

        # Check relationship details
        rel = relationships[0]
        target_id, rel_type, description = rel

        assert target_id == "MEMORYMANAGER"
        assert rel_type == "uses"
        assert "instantiates" in description.lower() or "uses" in description.lower()

    def test_analyze_multiple_dependencies(self):
        """Test analyzing class with multiple dependencies."""
        code = """
class WorkflowEngine:
    def __init__(self):
        self.memory = MemoryManager()
        self.planner = TaskPlanner()

    def execute(self):
        self.memory.store()
        self.planner.plan()
"""
        tree = ast.parse(code)
        class_node = tree.body[0]

        analyzer = UsageAnalyzer(
            available_components={"MemoryManager", "TaskPlanner"}
        )
        imported_names = {"MemoryManager", "TaskPlanner"}

        relationships = analyzer.analyze_class(
            class_node, "WORKFLOWENGINE", imported_names
        )

        # Should detect both dependencies
        assert len(relationships) == 2

        targets = {rel[0] for rel in relationships}
        assert "MEMORYMANAGER" in targets
        assert "TASKPLANNER" in targets

    def test_ignore_unavailable_components(self):
        """Test that unavailable components are ignored."""
        code = """
class Agent:
    def __init__(self):
        self.memory = MemoryManager()
        self.logger = Logger()  # Not in available_components
"""
        tree = ast.parse(code)
        class_node = tree.body[0]

        analyzer = UsageAnalyzer(available_components={"MemoryManager"})
        imported_names = {"MemoryManager", "Logger"}

        relationships = analyzer.analyze_class(
            class_node, "AGENT", imported_names
        )

        # Should only detect MemoryManager, not Logger
        assert len(relationships) == 1
        assert relationships[0][0] == "MEMORYMANAGER"

    def test_deduplication(self):
        """Test that multiple usages are aggregated."""
        code = """
class Agent:
    def method1(self):
        self.memory = MemoryManager()

    def method2(self):
        self.memory.store()

    def method3(self):
        self.memory.retrieve()
"""
        tree = ast.parse(code)
        class_node = tree.body[0]

        analyzer = UsageAnalyzer(available_components={"MemoryManager"})
        imported_names = {"MemoryManager"}

        relationships = analyzer.analyze_class(
            class_node, "AGENT", imported_names
        )

        # Should create ONE relationship despite multiple usages
        assert len(relationships) == 1

        # Description should mention multiple usage types
        description = relationships[0][2]
        assert "instantiates" in description.lower() or "calls methods" in description.lower()

    def test_no_usage_no_relationship(self):
        """Test that imports without usage don't create relationships."""
        code = """
class Agent:
    def execute(self):
        pass  # No usage of MemoryManager
"""
        tree = ast.parse(code)
        class_node = tree.body[0]

        analyzer = UsageAnalyzer(available_components={"MemoryManager"})
        imported_names = {"MemoryManager"}  # Imported but not used

        relationships = analyzer.analyze_class(
            class_node, "AGENT", imported_names
        )

        # Should NOT create relationship (no usage)
        assert len(relationships) == 0


class TestEndToEnd:
    """End-to-end integration tests."""

    def test_full_analysis_workflow(self):
        """Test complete analysis workflow."""
        code = """
from src.memory.manager import MemoryManager
from src.workflow.planner import TaskPlanner

class CodingAgent:
    def __init__(self):
        self.memory = MemoryManager()
        self.planner = TaskPlanner()

    def execute_task(self, task):
        plan = self.planner.create_plan(task)
        self.memory.store(plan)
        return plan
"""
        tree = ast.parse(code)

        # Extract imports
        imported_names = extract_imported_names(tree)
        assert "MemoryManager" in imported_names
        assert "TaskPlanner" in imported_names

        # Analyze class
        class_node = tree.body[2]  # CodingAgent class (after imports)
        analyzer = UsageAnalyzer(
            available_components={"MemoryManager", "TaskPlanner"}
        )

        relationships = analyzer.analyze_class(
            class_node, "CODINGAGENT", imported_names
        )

        # Should detect both dependencies
        assert len(relationships) == 2

        targets = {rel[0] for rel in relationships}
        assert "MEMORYMANAGER" in targets
        assert "TASKPLANNER" in targets

        # All relationships should be "uses"
        for rel in relationships:
            assert rel[1] == "uses"

    def test_real_world_complexity(self):
        """Test with realistic complex code."""
        code = """
from src.memory.manager import MemoryManager
from src.tools.file_ops import ReadFileTool
from src.llm.backend import LLMBackend

class ComplexAgent:
    def __init__(self, config):
        self.memory = MemoryManager()
        self.llm = LLMBackend(config)
        self.file_tool = ReadFileTool()

    def process(self, input_file):
        # Read file
        content = self.file_tool.read(input_file)

        # Get context from memory
        context = self.memory.retrieve()

        # Generate response
        response = self.llm.generate(content, context)

        # Store result
        self.memory.store(response)

        return response

    def cleanup(self):
        self.memory.clear()
"""
        tree = ast.parse(code)

        # Extract imports
        imported_names = extract_imported_names(tree)

        # Analyze class
        class_node = tree.body[3]  # ComplexAgent class
        analyzer = UsageAnalyzer(
            available_components={"MemoryManager", "ReadFileTool", "LLMBackend"}
        )

        relationships = analyzer.analyze_class(
            class_node, "COMPLEXAGENT", imported_names
        )

        # Should detect all 3 dependencies
        assert len(relationships) == 3

        targets = {rel[0] for rel in relationships}
        assert "MEMORYMANAGER" in targets
        assert "READFILETOOL" in targets
        assert "LLMBACKEND" in targets


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
