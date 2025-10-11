"""Semantic Memory - Long-term knowledge base with vector storage."""

import uuid
from typing import List, Optional, Dict, Any, Tuple
from pathlib import Path
import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

from .models import MemoryEntry, MemoryType, CodeContext


class SemanticMemory:
    """
    Semantic memory provides long-term knowledge storage using vector embeddings.
    Supports similarity-based retrieval for code, concepts, and solutions.
    """

    def __init__(
        self,
        persist_directory: str = "./data/embeddings",
        collection_name: str = "semantic_memory",
        embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2",
        similarity_threshold: float = 0.7,
    ):
        """
        Initialize semantic memory.

        Args:
            persist_directory: Directory to persist vector database
            collection_name: Name of the collection
            embedding_model: SentenceTransformer model name
            similarity_threshold: Minimum similarity score for retrieval
        """
        self.persist_directory = Path(persist_directory)
        self.persist_directory.mkdir(parents=True, exist_ok=True)

        self.similarity_threshold = similarity_threshold
        self.embedding_model_name = embedding_model

        # Initialize embedding model
        self.embedding_model = SentenceTransformer(embedding_model)

        # Initialize ChromaDB
        self.client = chromadb.Client(
            Settings(
                persist_directory=str(self.persist_directory),
                anonymized_telemetry=False,
            )
        )

        # Get or create collection
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},  # Use cosine similarity
        )

    def add_memory(
        self,
        content: str,
        memory_type: MemoryType = MemoryType.SEMANTIC,
        metadata: Optional[Dict[str, Any]] = None,
        importance_score: float = 0.5,
    ) -> str:
        """
        Add a memory entry to semantic storage.

        Args:
            content: Content to store
            memory_type: Type of memory
            metadata: Optional metadata
            importance_score: Importance score (0.0-1.0)

        Returns:
            ID of stored memory
        """
        memory_id = str(uuid.uuid4())

        # Generate embedding
        embedding = self.embedding_model.encode(content).tolist()

        # Prepare metadata
        meta = metadata or {}
        meta.update(
            {
                "memory_type": memory_type.value,
                "importance_score": importance_score,
                "created_at": str(uuid.uuid1().time),
            }
        )

        # Store in ChromaDB
        self.collection.add(
            ids=[memory_id],
            embeddings=[embedding],
            documents=[content],
            metadatas=[meta],
        )

        return memory_id

    def add_code_context(self, code_context: CodeContext, importance_score: float = 0.6) -> str:
        """
        Add code context to semantic memory.

        Args:
            code_context: CodeContext to store
            importance_score: Importance score

        Returns:
            ID of stored context
        """
        # Create searchable content
        content_parts = [f"File: {code_context.file_path}"]

        if code_context.summary:
            content_parts.append(f"Summary: {code_context.summary}")

        if code_context.functions:
            content_parts.append(f"Functions: {', '.join(code_context.functions)}")

        if code_context.classes:
            content_parts.append(f"Classes: {', '.join(code_context.classes)}")

        if code_context.imports:
            content_parts.append(f"Imports: {', '.join(code_context.imports)}")

        content = "\n".join(content_parts)

        metadata = {
            "type": "code_context",
            "file_path": code_context.file_path,
            "language": code_context.language or "unknown",
            "functions": code_context.functions,
            "classes": code_context.classes,
            **code_context.metadata,
        }

        return self.add_memory(
            content=content,
            memory_type=MemoryType.SEMANTIC,
            metadata=metadata,
            importance_score=importance_score,
        )

    def search(
        self,
        query: str,
        n_results: int = 5,
        filter_metadata: Optional[Dict[str, Any]] = None,
    ) -> List[Tuple[str, float, Dict[str, Any]]]:
        """
        Search semantic memory for relevant entries.

        Args:
            query: Search query
            n_results: Number of results to return
            filter_metadata: Optional metadata filters

        Returns:
            List of (content, similarity_score, metadata) tuples
        """
        # Generate query embedding
        query_embedding = self.embedding_model.encode(query).tolist()

        # Search ChromaDB
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where=filter_metadata,
        )

        # Process results
        matches = []
        if results["documents"] and results["documents"][0]:
            for i, doc in enumerate(results["documents"][0]):
                distance = results["distances"][0][i] if results["distances"] else 1.0
                similarity = 1.0 - distance  # Convert distance to similarity

                if similarity >= self.similarity_threshold:
                    metadata = results["metadatas"][0][i] if results["metadatas"] else {}
                    matches.append((doc, similarity, metadata))

        return matches

    def search_code(
        self, query: str, language: Optional[str] = None, n_results: int = 5
    ) -> List[Tuple[str, float, Dict[str, Any]]]:
        """
        Search for code-related memories.

        Args:
            query: Search query
            language: Optional language filter
            n_results: Number of results

        Returns:
            List of matching code contexts
        """
        filter_meta = {"type": "code_context"}
        if language:
            filter_meta["language"] = language

        return self.search(query=query, n_results=n_results, filter_metadata=filter_meta)

    def get_similar_solutions(
        self, problem_description: str, n_results: int = 3
    ) -> List[Tuple[str, float, Dict[str, Any]]]:
        """
        Find similar solutions to a problem.

        Args:
            problem_description: Description of the problem
            n_results: Number of similar solutions

        Returns:
            List of similar solutions
        """
        return self.search(
            query=problem_description,
            n_results=n_results,
            filter_metadata={"type": "solution"},
        )

    def add_solution(
        self, problem: str, solution: str, metadata: Optional[Dict] = None
    ) -> str:
        """
        Store a problem-solution pair.

        Args:
            problem: Problem description
            solution: Solution description
            metadata: Optional metadata

        Returns:
            ID of stored solution
        """
        content = f"Problem: {problem}\nSolution: {solution}"

        meta = metadata or {}
        meta["type"] = "solution"
        meta["problem"] = problem
        meta["solution"] = solution

        return self.add_memory(
            content=content,
            memory_type=MemoryType.SEMANTIC,
            metadata=meta,
            importance_score=0.8,  # Solutions are important
        )

    def update_importance(self, memory_id: str, new_importance: float) -> None:
        """
        Update importance score of a memory.

        Args:
            memory_id: ID of memory to update
            new_importance: New importance score
        """
        # Get existing memory
        result = self.collection.get(ids=[memory_id])

        if result["metadatas"]:
            metadata = result["metadatas"][0]
            metadata["importance_score"] = new_importance

            # Update in ChromaDB
            self.collection.update(ids=[memory_id], metadatas=[metadata])

    def delete_memory(self, memory_id: str) -> None:
        """Delete a memory entry."""
        self.collection.delete(ids=[memory_id])

    def get_all_code_files(self) -> List[str]:
        """Get list of all indexed code files."""
        results = self.collection.get(where={"type": "code_context"})

        files = set()
        if results["metadatas"]:
            for meta in results["metadatas"]:
                if "file_path" in meta:
                    files.add(meta["file_path"])

        return sorted(list(files))

    def get_statistics(self) -> Dict[str, Any]:
        """Get semantic memory statistics."""
        all_data = self.collection.get()

        # Count by type
        type_counts: Dict[str, int] = {}
        if all_data["metadatas"]:
            for meta in all_data["metadatas"]:
                mem_type = meta.get("type", "unknown")
                type_counts[mem_type] = type_counts.get(mem_type, 0) + 1

        return {
            "total_memories": len(all_data["ids"]) if all_data["ids"] else 0,
            "embedding_model": self.embedding_model_name,
            "embedding_dimension": self.embedding_model.get_sentence_embedding_dimension(),
            "similarity_threshold": self.similarity_threshold,
            "type_counts": type_counts,
            "collection_name": self.collection.name,
        }

    def clear(self) -> None:
        """Clear all semantic memory."""
        # Delete collection and recreate
        self.client.delete_collection(name=self.collection.name)
        self.collection = self.client.get_or_create_collection(
            name=self.collection.name,
            metadata={"hnsw:space": "cosine"},
        )

    def export_memories(self, filepath: Path) -> None:
        """
        Export all memories to JSON file.

        Args:
            filepath: Path to export file
        """
        import json

        all_data = self.collection.get()

        export_data = {
            "memories": [
                {
                    "id": all_data["ids"][i],
                    "content": all_data["documents"][i],
                    "metadata": all_data["metadatas"][i],
                }
                for i in range(len(all_data["ids"]))
            ]
            if all_data["ids"]
            else []
        }

        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w") as f:
            json.dump(export_data, f, indent=2)
