"""
Code Analyzer - Extract architecture from existing codebase

Scans Python files to extract:
- Components (classes, modules)
- Code artifacts (files, classes, functions, methods)
- Relationships (imports, calls, inheritance, USAGE)
- Documentation (docstrings, comments)

This analyzer uses ACCURATE usage detection (not just imports).
Follows Anthropic mindset: accuracy > speed.
"""

import ast
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set
from dataclasses import dataclass, field

from .usage_analyzer import UsageAnalyzer, extract_imported_names


@dataclass
class AnalyzedComponent:
    """Represents an analyzed component"""
    id: str
    name: str
    type: str  # class|module|orchestrator
    layer: str  # core|memory|rag|workflow|tools
    purpose: str
    business_value: str
    design_rationale: str
    responsibilities: List[str] = field(default_factory=list)
    file_path: str = ""
    line_start: int = 0
    line_end: int = 0


@dataclass
class AnalyzedArtifact:
    """Represents a code artifact"""
    component_id: str
    type: str  # file|class|function|method
    name: str
    file_path: str
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    description: str = ""


@dataclass
class AnalyzedRelationship:
    """Represents a relationship between components"""
    source_id: str
    target_id: str
    relationship_type: str  # imports|uses|depends-on|extends
    description: str = ""


class CodeAnalyzer:
    """
    Analyzes existing codebase to extract architectural information

    This analyzer scans Python source files to extract components (classes),
    artifacts (files, methods), and relationships (imports, inheritance).
    """

    # Map directory names to layers
    LAYER_MAP = {
        'core': 'core',
        'memory': 'memory',
        'rag': 'rag',
        'workflow': 'workflow',
        'tools': 'tools',
        'llm': 'llm',
        'prompts': 'prompts',
        'hooks': 'hooks',
        'subagents': 'subagents',
        'utils': 'utils',
        'cli': 'cli'
    }

    # Orchestrator classes (main coordinators)
    ORCHESTRATORS = [
        'CodingAgent',
        'MemoryManager',
        'HookManager',
        'SubAgentManager',
        'ExecutionEngine',
        'TaskAnalyzer',
        'TaskPlanner'
    ]

    def __init__(self, source_dir: str = "src"):
        """
        Initialize CodeAnalyzer

        Args:
            source_dir: Root directory to analyze (default: "src")
        """
        self.source_dir = Path(source_dir).resolve()
        self.base_dir = Path.cwd().resolve()
        self.components: Dict[str, AnalyzedComponent] = {}
        self.artifacts: List[AnalyzedArtifact] = []
        self.relationships: List[AnalyzedRelationship] = []

        # Usage analyzer - will be initialized after first pass
        self.usage_analyzer: Optional[UsageAnalyzer] = None

    def analyze(self) -> Tuple[Dict[str, AnalyzedComponent], List[AnalyzedArtifact], List[AnalyzedRelationship]]:
        """
        Analyze the codebase (two-pass analysis for accurate relationships)

        Pass 1: Extract all components (classes, modules)
        Pass 2: Analyze usage relationships between components

        Returns:
            Tuple of (components, artifacts, relationships)
        """
        python_files = self._find_python_files()

        # Pass 1: Extract components and inheritance
        for python_file in python_files:
            self._analyze_file(python_file, extract_usage=False)

        # Initialize usage analyzer with known components
        component_names = {comp.name for comp in self.components.values()}
        self.usage_analyzer = UsageAnalyzer(component_names)

        # Pass 2: Analyze usage relationships
        for python_file in python_files:
            self._analyze_file_usage(python_file)

        return self.components, self.artifacts, self.relationships

    def analyze_file(self, file_path: str) -> List[AnalyzedComponent]:
        """
        Analyze a single file and return components found.

        This is the public API for incremental analysis (used by SyncOrchestrator).

        Args:
            file_path: Path to Python file (absolute or relative)

        Returns:
            List of components found in the file
        """
        # Convert to Path
        path = Path(file_path)
        if not path.is_absolute():
            path = self.base_dir / path

        if not path.exists():
            return []

        # Clear previous state for this file
        relative_path = str(path.resolve().relative_to(self.base_dir)) if path.is_relative_to(self.base_dir) else str(path)

        # Remove components from this file
        file_components = [comp_id for comp_id, comp in self.components.items() if comp.file_path == relative_path]
        for comp_id in file_components:
            del self.components[comp_id]

        # Remove artifacts from this file
        self.artifacts = [art for art in self.artifacts if art.file_path != relative_path]

        # Remove relationships from this file
        self.relationships = [rel for rel in self.relationships if not any(
            self.components.get(rel.source_id, AnalyzedComponent("", "", "", "", "", "", "", file_path=relative_path)).file_path == relative_path
            for _ in [1]  # Dummy iteration
        )]

        # Analyze the file
        self._analyze_file(path)

        # Return components found in this file
        return [comp for comp in self.components.values() if comp.file_path == relative_path]

    def _find_python_files(self) -> List[Path]:
        """
        Find all Python files in source directory

        Returns:
            List of Python file paths
        """
        python_files = []
        for root, dirs, files in os.walk(self.source_dir):
            # Skip __pycache__, .pytest_cache, etc.
            dirs[:] = [d for d in dirs if not d.startswith('__') and not d.startswith('.')]

            for file in files:
                if file.endswith('.py') and not file.startswith('__'):
                    python_files.append(Path(root) / file)

        return python_files

    def _analyze_file(self, file_path: Path, extract_usage: bool = True) -> None:
        """
        Analyze a single Python file

        Args:
            file_path: Path to Python file
            extract_usage: Whether to extract usage relationships (default: True)
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                source_code = f.read()

            # Parse AST
            tree = ast.parse(source_code, filename=str(file_path))

            # Determine layer from path
            layer = self._determine_layer(file_path)

            # Extract module-level docstring
            module_docstring = ast.get_docstring(tree) or ""

            # Create file artifact
            try:
                relative_path = file_path.resolve().relative_to(self.base_dir)
            except ValueError:
                # If file is not relative to base_dir, use absolute path
                relative_path = file_path

            file_artifact = AnalyzedArtifact(
                component_id="",  # Will be set later
                type="file",
                name=file_path.name,
                file_path=str(relative_path),
                description=module_docstring[:200] if module_docstring else ""
            )

            # Extract imports - removed, we now use accurate usage analysis instead
            # Old approach: self._extract_imports() created relationships with empty source_id
            # New approach: Usage analyzer in pass 2 detects actual usage

            # Extract classes
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    component = self._analyze_class(node, file_path, layer, source_code)
                    if component:
                        self.components[component.id] = component

                        # Add class artifact
                        class_artifact = AnalyzedArtifact(
                            component_id=component.id,
                            type="class",
                            name=node.name,
                            file_path=str(relative_path),
                            line_start=node.lineno,
                            line_end=node.end_lineno,
                            description=ast.get_docstring(node) or ""
                        )
                        self.artifacts.append(class_artifact)

                        # Add file artifact with component_id
                        file_artifact.component_id = component.id
                        self.artifacts.append(file_artifact)

                        # Extract methods
                        self._extract_methods(node, component.id, str(relative_path))

                        # Extract inheritance relationships
                        self._extract_inheritance(node, component.id)

        except Exception as e:
            # Skip files that can't be parsed
            print(f"Warning: Could not analyze {file_path}: {e}")

    def _determine_layer(self, file_path: Path) -> str:
        """
        Determine the architectural layer from file path

        Args:
            file_path: Path to file

        Returns:
            Layer name
        """
        parts = file_path.parts
        for part in parts:
            if part in self.LAYER_MAP:
                return self.LAYER_MAP[part]

        return "other"

    def _analyze_class(self, node: ast.ClassDef, file_path: Path, layer: str, source_code: str) -> Optional[AnalyzedComponent]:
        """
        Analyze a class definition

        Args:
            node: AST ClassDef node
            file_path: Path to file containing class
            layer: Architectural layer
            source_code: Full source code

        Returns:
            AnalyzedComponent or None
        """
        class_name = node.name

        # Skip test classes, private classes, internal classes
        if class_name.startswith('_') or class_name.startswith('Test'):
            return None

        # Generate component ID
        component_id = class_name.upper().replace('_', '')

        # Determine component type
        if class_name in self.ORCHESTRATORS:
            component_type = "orchestrator"
        elif class_name.endswith('Tool') or class_name.endswith('Manager'):
            component_type = "core-class"
        elif class_name.endswith('Error') or class_name.endswith('Exception'):
            component_type = "exception"
        else:
            component_type = "core-class"

        # Extract docstring
        docstring = ast.get_docstring(node) or ""

        # Extract purpose (first line of docstring)
        purpose = docstring.split('\n')[0] if docstring else f"{class_name} class"

        # Extract responsibilities from methods
        responsibilities = []
        for item in node.body:
            if isinstance(item, ast.FunctionDef) and not item.name.startswith('_'):
                # Public methods are responsibilities
                method_doc = ast.get_docstring(item)
                if method_doc:
                    responsibilities.append(f"{item.name}: {method_doc.split('.')[0]}")
                else:
                    responsibilities.append(item.name)

        # Business value (generic for now, can be enhanced)
        business_value = f"Provides {layer} layer functionality"

        # Design rationale (generic for now)
        design_rationale = f"Encapsulates {class_name.lower()} logic"

        try:
            relative_path = file_path.resolve().relative_to(self.base_dir)
        except ValueError:
            relative_path = file_path

        return AnalyzedComponent(
            id=component_id,
            name=class_name,
            type=component_type,
            layer=layer,
            purpose=purpose[:200] if purpose else "",
            business_value=business_value,
            design_rationale=design_rationale,
            responsibilities=responsibilities[:10],  # Limit to 10
            file_path=str(relative_path),
            line_start=node.lineno,
            line_end=node.end_lineno or 0
        )

    def _extract_methods(self, class_node: ast.ClassDef, component_id: str, file_path: str) -> None:
        """
        Extract methods from a class

        Args:
            class_node: AST ClassDef node
            component_id: Component ID
            file_path: File path
        """
        for node in class_node.body:
            if isinstance(node, ast.FunctionDef):
                # Skip private methods and magic methods (except __init__)
                if node.name.startswith('__') and node.name != '__init__':
                    continue
                if node.name.startswith('_') and node.name != '__init__':
                    continue

                docstring = ast.get_docstring(node) or ""
                description = docstring.split('\n')[0] if docstring else ""

                artifact = AnalyzedArtifact(
                    component_id=component_id,
                    type="method",
                    name=node.name,
                    file_path=file_path,
                    line_start=node.lineno,
                    line_end=node.end_lineno,
                    description=description[:200] if description else ""
                )
                self.artifacts.append(artifact)

    def _analyze_file_usage(self, file_path: Path) -> None:
        """
        Analyze usage relationships in a file (Pass 2).

        This method analyzes HOW components use each other, not just imports.
        It detects instantiation, method calls, and attribute access.

        Args:
            file_path: Path to Python file
        """
        if not self.usage_analyzer:
            return  # Skip if usage analyzer not initialized

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                source_code = f.read()

            # Parse AST
            tree = ast.parse(source_code, filename=str(file_path))

            # Extract imported names in this file
            imported_names = extract_imported_names(tree)

            # Get relative path for component lookup
            try:
                relative_path = file_path.resolve().relative_to(self.base_dir)
            except ValueError:
                relative_path = file_path

            # Analyze each class in the file
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    class_name = node.name

                    # Skip test classes, private classes
                    if class_name.startswith('_') or class_name.startswith('Test'):
                        continue

                    # Find the component for this class
                    component_id = class_name.upper().replace('_', '')
                    if component_id not in self.components:
                        continue  # Component not found, skip

                    # Analyze usage in this class
                    usage_relationships = self.usage_analyzer.analyze_class(
                        node, component_id, imported_names
                    )

                    # Add relationships
                    for target_id, rel_type, description in usage_relationships:
                        # Only add if target component exists
                        if target_id in self.components:
                            relationship = AnalyzedRelationship(
                                source_id=component_id,
                                target_id=target_id,
                                relationship_type=rel_type,
                                description=description
                            )
                            self.relationships.append(relationship)

        except Exception as e:
            # Skip files that can't be parsed
            print(f"Warning: Could not analyze usage in {file_path}: {e}")

    def _extract_imports(self, tree: ast.Module, file_path: str) -> List[AnalyzedRelationship]:
        """
        Extract import statements

        Args:
            tree: AST Module node
            file_path: File path

        Returns:
            List of relationships
        """
        relationships = []

        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.ImportFrom):
                    if node.module and node.module.startswith('src.'):
                        # Internal import
                        module_parts = node.module.split('.')
                        if len(module_parts) >= 3:
                            # Extract imported names
                            for alias in node.names:
                                imported_name = alias.name
                                # Try to map to component
                                target_id = imported_name.upper().replace('_', '')

                                # Infer relationship type
                                rel_type = "imports"

                                relationship = AnalyzedRelationship(
                                    source_id="",  # Will be set later when we know the component
                                    target_id=target_id,
                                    relationship_type=rel_type,
                                    description=f"Imports {imported_name} from {node.module}"
                                )
                                relationships.append(relationship)

        return relationships

    def _extract_inheritance(self, class_node: ast.ClassDef, component_id: str) -> None:
        """
        Extract class inheritance relationships

        Args:
            class_node: AST ClassDef node
            component_id: Component ID
        """
        for base in class_node.bases:
            if isinstance(base, ast.Name):
                base_name = base.id
                target_id = base_name.upper().replace('_', '')

                relationship = AnalyzedRelationship(
                    source_id=component_id,
                    target_id=target_id,
                    relationship_type="extends",
                    description=f"Extends {base_name}"
                )
                self.relationships.append(relationship)

    def get_summary(self) -> Dict[str, any]:
        """
        Get analysis summary

        Returns:
            Summary dict
        """
        return {
            'total_components': len(self.components),
            'total_artifacts': len(self.artifacts),
            'total_relationships': len(self.relationships),
            'components_by_layer': self._count_by_layer(),
            'components_by_type': self._count_by_type()
        }

    def _count_by_layer(self) -> Dict[str, int]:
        """Count components by layer"""
        counts = {}
        for component in self.components.values():
            counts[component.layer] = counts.get(component.layer, 0) + 1
        return counts

    def _count_by_type(self) -> Dict[str, int]:
        """Count components by type"""
        counts = {}
        for component in self.components.values():
            counts[component.type] = counts.get(component.type, 0) + 1
        return counts
