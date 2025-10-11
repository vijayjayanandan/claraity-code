"""Embedder for generating vector embeddings of code chunks."""

from typing import List, Optional, Dict, Any
from sentence_transformers import SentenceTransformer
import numpy as np
from pathlib import Path
import pickle

from .models import CodeChunk


class Embedder:
    """
    Generates and caches embeddings for code chunks.
    Optimized for small, efficient embedding models.
    """

    def __init__(
        self,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        cache_dir: Optional[str] = None,
        batch_size: int = 32,
    ):
        """
        Initialize embedder.

        Args:
            model_name: SentenceTransformer model name
            cache_dir: Directory for caching embeddings
            batch_size: Batch size for embedding generation
        """
        self.model_name = model_name
        self.model = SentenceTransformer(model_name)
        self.batch_size = batch_size
        self.cache_dir = Path(cache_dir) if cache_dir else None

        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

        # In-memory cache
        self._cache: Dict[str, List[float]] = {}

    def embed_chunks(
        self, chunks: List[CodeChunk], use_cache: bool = True
    ) -> List[CodeChunk]:
        """
        Generate embeddings for code chunks.

        Args:
            chunks: List of code chunks
            use_cache: Whether to use caching

        Returns:
            Chunks with embeddings populated
        """
        chunks_to_embed = []
        chunk_indices = []

        # Check cache
        for i, chunk in enumerate(chunks):
            if use_cache and chunk.id in self._cache:
                chunk.embedding = self._cache[chunk.id]
            else:
                chunks_to_embed.append(chunk)
                chunk_indices.append(i)

        # Generate embeddings for uncached chunks
        if chunks_to_embed:
            # Prepare texts
            texts = [chunk.get_searchable_content() for chunk in chunks_to_embed]

            # Generate embeddings in batches
            embeddings = self.model.encode(
                texts,
                batch_size=self.batch_size,
                show_progress_bar=len(texts) > 100,
                convert_to_numpy=True,
            )

            # Update chunks and cache
            for chunk, embedding, idx in zip(
                chunks_to_embed, embeddings, chunk_indices
            ):
                embedding_list = embedding.tolist()
                chunk.embedding = embedding_list
                chunks[idx] = chunk

                if use_cache:
                    self._cache[chunk.id] = embedding_list

        return chunks

    def embed_query(self, query: str) -> List[float]:
        """
        Generate embedding for a query.

        Args:
            query: Query text

        Returns:
            Embedding vector
        """
        embedding = self.model.encode(query, convert_to_numpy=True)
        return embedding.tolist()

    def compute_similarity(
        self, embedding1: List[float], embedding2: List[float]
    ) -> float:
        """
        Compute cosine similarity between two embeddings.

        Args:
            embedding1: First embedding
            embedding2: Second embedding

        Returns:
            Similarity score (0-1)
        """
        vec1 = np.array(embedding1)
        vec2 = np.array(embedding2)

        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return float(dot_product / (norm1 * norm2))

    def save_cache(self, filepath: Optional[Path] = None) -> None:
        """Save embedding cache to disk."""
        if not filepath and self.cache_dir:
            filepath = self.cache_dir / "embedding_cache.pkl"

        if filepath:
            with open(filepath, "wb") as f:
                pickle.dump(self._cache, f)

    def load_cache(self, filepath: Optional[Path] = None) -> None:
        """Load embedding cache from disk."""
        if not filepath and self.cache_dir:
            filepath = self.cache_dir / "embedding_cache.pkl"

        if filepath and filepath.exists():
            with open(filepath, "rb") as f:
                self._cache = pickle.load(f)

    def get_embedding_dimension(self) -> int:
        """Get dimensionality of embeddings."""
        return self.model.get_sentence_embedding_dimension()

    def clear_cache(self) -> None:
        """Clear embedding cache."""
        self._cache.clear()
