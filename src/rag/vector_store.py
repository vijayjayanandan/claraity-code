"""Vector store wrapper for managing code embeddings."""

from typing import List, Optional, Dict, Any
from pathlib import Path
# chromadb is an optional dependency (pip install claraity-code[rag])
try:
    import chromadb
    from chromadb.config import Settings
    CHROMADB_AVAILABLE = True
except ImportError:
    chromadb = None
    Settings = None
    CHROMADB_AVAILABLE = False

from .models import CodeChunk, CodebaseIndex


class VectorStore:
    """
    Vector store for code chunk embeddings using ChromaDB.
    Provides persistence and efficient similarity search.
    """

    def __init__(
        self,
        persist_directory: str = "./data/embeddings",
        collection_name: str = "code_chunks",
    ):
        """
        Initialize vector store.

        Args:
            persist_directory: Directory to persist database
            collection_name: Name of the collection
        """
        self.persist_directory = Path(persist_directory)
        self.persist_directory.mkdir(parents=True, exist_ok=True)

        # Initialize ChromaDB client
        self.client = chromadb.Client(
            Settings(
                persist_directory=str(self.persist_directory),
                anonymized_telemetry=False,
            )
        )

        # Get or create collection
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def add_chunks(self, chunks: List[CodeChunk]) -> None:
        """
        Add code chunks to vector store.

        Args:
            chunks: List of code chunks with embeddings
        """
        if not chunks:
            return

        ids = []
        embeddings = []
        documents = []
        metadatas = []

        for chunk in chunks:
            if not chunk.embedding:
                continue

            ids.append(chunk.id)
            embeddings.append(chunk.embedding)
            documents.append(chunk.get_searchable_content())

            metadata = {
                "file_path": chunk.file_path,
                "language": chunk.language,
                "chunk_type": chunk.chunk_type,
                "start_line": chunk.start_line,
                "end_line": chunk.end_line,
                "name": chunk.name or "",
                "parent_context": chunk.parent_context or "",
            }
            metadatas.append(metadata)

        if ids:
            self.collection.add(
                ids=ids,
                embeddings=embeddings,
                documents=documents,
                metadatas=metadatas,
            )

    def search(
        self,
        query_embedding: List[float],
        n_results: int = 10,
        where: Optional[Dict[str, Any]] = None,
    ) -> List[CodeChunk]:
        """
        Search for similar code chunks.

        Args:
            query_embedding: Query embedding vector
            n_results: Number of results to return
            where: Optional metadata filters

        Returns:
            List of matching code chunks
        """
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where=where,
        )

        chunks = []
        if results["documents"] and results["documents"][0]:
            for i in range(len(results["ids"][0])):
                chunk_id = results["ids"][0][i]
                content = results["documents"][0][i]
                metadata = results["metadatas"][0][i] if results["metadatas"] else {}
                embedding = results["embeddings"][0][i] if results["embeddings"] else None

                chunk = CodeChunk(
                    id=chunk_id,
                    file_path=metadata.get("file_path", ""),
                    content=content,
                    start_line=metadata.get("start_line", 0),
                    end_line=metadata.get("end_line", 0),
                    language=metadata.get("language", ""),
                    chunk_type=metadata.get("chunk_type", ""),
                    name=metadata.get("name") or None,
                    parent_context=metadata.get("parent_context") or None,
                    embedding=embedding,
                )
                chunks.append(chunk)

        return chunks

    def get_by_file(self, file_path: str) -> List[CodeChunk]:
        """Get all chunks for a specific file."""
        return self.search(
            query_embedding=[0.0] * 384,  # Dummy embedding
            n_results=1000,
            where={"file_path": file_path},
        )

    def delete_by_file(self, file_path: str) -> None:
        """Delete all chunks for a specific file."""
        self.collection.delete(where={"file_path": file_path})

    def update_chunk(self, chunk: CodeChunk) -> None:
        """Update a code chunk."""
        if not chunk.embedding:
            return

        self.collection.update(
            ids=[chunk.id],
            embeddings=[chunk.embedding],
            documents=[chunk.get_searchable_content()],
            metadatas=[
                {
                    "file_path": chunk.file_path,
                    "language": chunk.language,
                    "chunk_type": chunk.chunk_type,
                    "start_line": chunk.start_line,
                    "end_line": chunk.end_line,
                    "name": chunk.name or "",
                    "parent_context": chunk.parent_context or "",
                }
            ],
        )

    def count(self) -> int:
        """Get total number of chunks."""
        return self.collection.count()

    def clear(self) -> None:
        """Clear all chunks from store."""
        self.client.delete_collection(name=self.collection.name)
        self.collection = self.client.get_or_create_collection(
            name=self.collection.name,
            metadata={"hnsw:space": "cosine"},
        )
