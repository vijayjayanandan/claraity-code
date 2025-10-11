"""Data models for RAG system."""

from typing import List, Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


class CodeChunk(BaseModel):
    """A chunk of code for embedding and retrieval."""

    id: str
    file_path: str
    content: str
    start_line: int
    end_line: int
    language: str
    chunk_type: str  # file, class, function, block
    name: Optional[str] = None  # function/class name if applicable
    signature: Optional[str] = None  # function signature
    docstring: Optional[str] = None
    parent_context: Optional[str] = None  # parent class/module
    imports: List[str] = Field(default_factory=list)
    dependencies: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    embedding: Optional[List[float]] = None
    created_at: datetime = Field(default_factory=datetime.now)

    def get_searchable_content(self) -> str:
        """Get content optimized for search."""
        parts = []

        # Add context
        if self.parent_context:
            parts.append(f"Context: {self.parent_context}")

        # Add signature or name
        if self.signature:
            parts.append(f"Signature: {self.signature}")
        elif self.name:
            parts.append(f"Name: {self.name}")

        # Add docstring
        if self.docstring:
            parts.append(f"Description: {self.docstring}")

        # Add content
        parts.append(f"Code:\n{self.content}")

        # Add imports
        if self.imports:
            parts.append(f"Imports: {', '.join(self.imports)}")

        return "\n\n".join(parts)


class SearchResult(BaseModel):
    """A search result from RAG retrieval."""

    chunk: CodeChunk
    score: float  # Combined relevance score
    semantic_score: Optional[float] = None  # Vector similarity score
    keyword_score: Optional[float] = None  # BM25 score
    rank: int = 0
    explanation: Optional[str] = None


class CodebaseIndex(BaseModel):
    """Metadata about indexed codebase."""

    root_path: str
    total_files: int = 0
    total_chunks: int = 0
    languages: Dict[str, int] = Field(default_factory=dict)  # language -> file count
    indexed_at: datetime = Field(default_factory=datetime.now)
    last_updated: Optional[datetime] = None
    file_patterns: List[str] = Field(default_factory=list)
    exclude_patterns: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DependencyGraph(BaseModel):
    """Dependency graph for code navigation."""

    nodes: Dict[str, Dict[str, Any]] = Field(default_factory=dict)  # file -> metadata
    edges: List[tuple[str, str, str]] = Field(
        default_factory=list
    )  # (from, to, relation_type)

    def add_node(self, file_path: str, metadata: Optional[Dict] = None) -> None:
        """Add a node to the graph."""
        self.nodes[file_path] = metadata or {}

    def add_edge(self, from_file: str, to_file: str, relation: str = "imports") -> None:
        """Add an edge to the graph."""
        self.edges.append((from_file, to_file, relation))

    def get_dependencies(self, file_path: str) -> List[str]:
        """Get all dependencies of a file."""
        return [to_file for from_file, to_file, _ in self.edges if from_file == file_path]

    def get_dependents(self, file_path: str) -> List[str]:
        """Get all files that depend on this file."""
        return [
            from_file for from_file, to_file, _ in self.edges if to_file == file_path
        ]
