"""Code indexer for parsing and chunking source code."""

import os
import uuid
from pathlib import Path
from typing import List, Optional, Dict, Any, Set
from tree_sitter_languages import get_language, get_parser
import tree_sitter as ts

from .models import CodeChunk, CodebaseIndex, DependencyGraph


class CodeIndexer:
    """
    Indexes source code files into searchable chunks.
    Uses Tree-sitter for AST-based parsing and intelligent chunking.
    """

    # Supported languages and their Tree-sitter parsers
    SUPPORTED_LANGUAGES = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".tsx": "tsx",
        ".java": "java",
        ".go": "go",
        ".rs": "rust",
        ".cpp": "cpp",
        ".c": "c",
        ".cs": "csharp",
        ".rb": "ruby",
        ".php": "php",
    }

    # Default file patterns to exclude
    DEFAULT_EXCLUDE_PATTERNS = {
        "node_modules",
        ".git",
        "__pycache__",
        ".venv",
        "venv",
        "env",
        "dist",
        "build",
        ".egg-info",
        "target",
        ".pytest_cache",
        ".mypy_cache",
    }

    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
        exclude_patterns: Optional[Set[str]] = None,
    ):
        """
        Initialize code indexer.

        Args:
            chunk_size: Target size for code chunks (in characters)
            chunk_overlap: Overlap between chunks (in characters)
            exclude_patterns: Patterns to exclude from indexing
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.exclude_patterns = exclude_patterns or self.DEFAULT_EXCLUDE_PATTERNS

        # Cache for Tree-sitter parsers
        self._parsers: Dict[str, Any] = {}

    def _get_parser(self, language: str) -> Optional[Any]:
        """Get Tree-sitter parser for language."""
        if language not in self._parsers:
            try:
                self._parsers[language] = get_parser(language)
            except Exception as e:
                print(f"Failed to load parser for {language}: {e}")
                return None

        return self._parsers[language]

    def _should_exclude(self, path: Path) -> bool:
        """Check if path should be excluded from indexing."""
        path_str = str(path)

        for pattern in self.exclude_patterns:
            if pattern in path_str:
                return True

        return False

    def index_codebase(
        self,
        root_path: str,
        file_patterns: Optional[List[str]] = None,
    ) -> tuple[List[CodeChunk], CodebaseIndex, DependencyGraph]:
        """
        Index an entire codebase.

        Args:
            root_path: Root directory to index
            file_patterns: Optional list of glob patterns to include

        Returns:
            Tuple of (chunks, index metadata, dependency graph)
        """
        root = Path(root_path).resolve()
        chunks: List[CodeChunk] = []
        dependency_graph = DependencyGraph()
        language_counts: Dict[str, int] = {}

        # Get all files to index
        files_to_index = self._get_files_to_index(root, file_patterns)

        for file_path in files_to_index:
            try:
                file_chunks = self.index_file(str(file_path))
                chunks.extend(file_chunks)

                # Update language counts
                ext = file_path.suffix
                lang = self.SUPPORTED_LANGUAGES.get(ext, "unknown")
                language_counts[lang] = language_counts.get(lang, 0) + 1

                # Build dependency graph
                self._update_dependency_graph(file_path, file_chunks, dependency_graph)

            except Exception as e:
                print(f"Failed to index {file_path}: {e}")

        # Create index metadata
        index = CodebaseIndex(
            root_path=str(root),
            total_files=len(files_to_index),
            total_chunks=len(chunks),
            languages=language_counts,
            file_patterns=file_patterns or [],
            exclude_patterns=list(self.exclude_patterns),
        )

        return chunks, index, dependency_graph

    def _get_files_to_index(
        self, root: Path, patterns: Optional[List[str]] = None
    ) -> List[Path]:
        """Get list of files to index."""
        files = []

        if patterns:
            # Use provided patterns
            for pattern in patterns:
                files.extend(root.glob(pattern))
        else:
            # Index all supported files
            for ext in self.SUPPORTED_LANGUAGES.keys():
                files.extend(root.glob(f"**/*{ext}"))

        # Filter out excluded paths
        return [f for f in files if f.is_file() and not self._should_exclude(f)]

    def index_file(self, file_path: str) -> List[CodeChunk]:
        """
        Index a single file into chunks.

        Args:
            file_path: Path to file

        Returns:
            List of code chunks
        """
        path = Path(file_path)
        ext = path.suffix
        language = self.SUPPORTED_LANGUAGES.get(ext)

        if not language:
            # Unsupported language, create single chunk
            return self._create_text_chunks(file_path)

        # Parse with Tree-sitter
        parser = self._get_parser(language)
        if not parser:
            return self._create_text_chunks(file_path)

        with open(file_path, "rb") as f:
            source_code = f.read()

        tree = parser.parse(source_code)
        source_text = source_code.decode("utf-8")

        # Extract structured chunks
        chunks = self._extract_structured_chunks(
            file_path=file_path,
            language=language,
            tree=tree,
            source_text=source_text,
        )

        return chunks

    def _extract_structured_chunks(
        self,
        file_path: str,
        language: str,
        tree: Any,
        source_text: str,
    ) -> List[CodeChunk]:
        """Extract structured chunks based on AST."""
        chunks = []

        # Language-specific node types to extract
        chunk_types = self._get_chunk_node_types(language)

        # Extract imports
        imports = self._extract_imports(tree, language, source_text)

        # Traverse AST and extract chunks
        def traverse(node: Any, parent_context: Optional[str] = None) -> None:
            if node.type in chunk_types:
                chunk = self._create_chunk_from_node(
                    file_path=file_path,
                    language=language,
                    node=node,
                    source_text=source_text,
                    parent_context=parent_context,
                    imports=imports,
                )
                if chunk:
                    chunks.append(chunk)

                # Update parent context for children
                new_context = chunk.name if chunk and chunk.name else parent_context

                for child in node.children:
                    traverse(child, new_context)
            else:
                for child in node.children:
                    traverse(child, parent_context)

        traverse(tree.root_node)

        # If no structured chunks, fall back to text chunking
        if not chunks:
            chunks = self._create_text_chunks(file_path)

        return chunks

    def _get_chunk_node_types(self, language: str) -> Set[str]:
        """Get AST node types to extract as chunks for a language."""
        common_types = {"function_definition", "class_definition", "method_definition"}

        language_specific = {
            "python": {"function_definition", "class_definition"},
            "javascript": {"function_declaration", "class_declaration", "method_definition"},
            "typescript": {"function_declaration", "class_declaration", "method_definition"},
            "java": {"method_declaration", "class_declaration"},
            "go": {"function_declaration", "method_declaration"},
            "rust": {"function_item", "impl_item"},
        }

        return language_specific.get(language, common_types)

    def _create_chunk_from_node(
        self,
        file_path: str,
        language: str,
        node: Any,
        source_text: str,
        parent_context: Optional[str],
        imports: List[str],
    ) -> Optional[CodeChunk]:
        """Create a code chunk from an AST node."""
        start_line = node.start_point[0]
        end_line = node.end_point[0]
        content = source_text[node.start_byte : node.end_byte]

        # Extract name
        name = self._extract_node_name(node, source_text)

        # Extract signature
        signature = self._extract_signature(node, source_text, language)

        # Extract docstring
        docstring = self._extract_docstring(node, source_text, language)

        return CodeChunk(
            id=str(uuid.uuid4()),
            file_path=file_path,
            content=content,
            start_line=start_line,
            end_line=end_line,
            language=language,
            chunk_type=node.type,
            name=name,
            signature=signature,
            docstring=docstring,
            parent_context=parent_context,
            imports=imports,
        )

    def _extract_node_name(self, node: Any, source_text: str) -> Optional[str]:
        """Extract name from AST node."""
        for child in node.children:
            if child.type == "identifier":
                return source_text[child.start_byte : child.end_byte]
        return None

    def _extract_signature(
        self, node: Any, source_text: str, language: str
    ) -> Optional[str]:
        """Extract function/method signature."""
        # For functions, get everything up to the body
        for child in node.children:
            if child.type in {"block", "body"}:
                return source_text[node.start_byte : child.start_byte].strip()
        return None

    def _extract_docstring(
        self, node: Any, source_text: str, language: str
    ) -> Optional[str]:
        """Extract docstring/documentation."""
        if language == "python":
            # Look for string literal as first statement
            for child in node.children:
                if child.type == "block":
                    for stmt in child.children:
                        if stmt.type == "expression_statement":
                            for expr_child in stmt.children:
                                if expr_child.type == "string":
                                    return source_text[
                                        expr_child.start_byte : expr_child.end_byte
                                    ].strip('"""\'\'\'')
        return None

    def _extract_imports(self, tree: Any, language: str, source_text: str) -> List[str]:
        """Extract import statements."""
        imports = []

        import_types = {
            "python": {"import_statement", "import_from_statement"},
            "javascript": {"import_statement"},
            "typescript": {"import_statement"},
            "java": {"import_declaration"},
            "go": {"import_declaration"},
        }

        target_types = import_types.get(language, set())

        def traverse(node: Any) -> None:
            if node.type in target_types:
                import_text = source_text[node.start_byte : node.end_byte]
                imports.append(import_text)

            for child in node.children:
                traverse(child)

        if tree.root_node:
            traverse(tree.root_node)

        return imports

    def _create_text_chunks(self, file_path: str) -> List[CodeChunk]:
        """Create simple text-based chunks for unsupported file types."""
        chunks = []

        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        # Simple line-based chunking
        lines = content.split("\n")
        current_chunk = []
        current_size = 0
        start_line = 0

        for i, line in enumerate(lines):
            current_chunk.append(line)
            current_size += len(line)

            if current_size >= self.chunk_size:
                chunk_content = "\n".join(current_chunk)
                chunks.append(
                    CodeChunk(
                        id=str(uuid.uuid4()),
                        file_path=file_path,
                        content=chunk_content,
                        start_line=start_line,
                        end_line=i,
                        language="text",
                        chunk_type="block",
                    )
                )

                # Keep overlap
                overlap_lines = int(self.chunk_overlap / (current_size / len(current_chunk)))
                current_chunk = current_chunk[-overlap_lines:] if overlap_lines > 0 else []
                current_size = sum(len(line) for line in current_chunk)
                start_line = i - len(current_chunk) + 1

        # Add final chunk
        if current_chunk:
            chunks.append(
                CodeChunk(
                    id=str(uuid.uuid4()),
                    file_path=file_path,
                    content="\n".join(current_chunk),
                    start_line=start_line,
                    end_line=len(lines) - 1,
                    language="text",
                    chunk_type="block",
                )
            )

        return chunks

    def _update_dependency_graph(
        self,
        file_path: Path,
        chunks: List[CodeChunk],
        graph: DependencyGraph,
    ) -> None:
        """Update dependency graph based on imports."""
        graph.add_node(str(file_path))

        # Extract dependencies from imports
        for chunk in chunks:
            for import_stmt in chunk.imports:
                # Simple heuristic: extract module names
                # This can be improved with better parsing
                imported_modules = self._parse_import_modules(import_stmt, file_path)
                for module in imported_modules:
                    graph.add_edge(str(file_path), module, "imports")

    def _parse_import_modules(self, import_stmt: str, file_path: Path) -> List[str]:
        """Parse module names from import statement."""
        # This is a simplified implementation
        # Can be enhanced with proper parsing
        modules = []

        if "import" in import_stmt:
            # Extract module names (very basic)
            parts = import_stmt.replace("from", "").replace("import", "").strip().split()
            if parts:
                module = parts[0].strip(";,")
                # Try to resolve to file path
                potential_path = file_path.parent / f"{module.replace('.', '/')}.py"
                if potential_path.exists():
                    modules.append(str(potential_path))

        return modules
