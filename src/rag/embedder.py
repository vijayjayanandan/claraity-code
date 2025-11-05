"""Embedder for generating vector embeddings of code chunks using Alibaba Cloud API."""

from typing import List, Optional, Dict, Any
import numpy as np
from pathlib import Path
import pickle
import os
from openai import OpenAI

from .models import CodeChunk


class Embedder:
    """
    Generates and caches embeddings for code chunks using Alibaba Cloud API.
    Uses text-embedding-v2 model via OpenAI-compatible interface.
    """

    def __init__(
        self,
        model_name: str = "text-embedding-v4",  # Alibaba model
        cache_dir: Optional[str] = None,
        batch_size: int = 32,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,  # Will use LLM_HOST env var or default
    ):
        """
        Initialize embedder with Alibaba Cloud API.

        Args:
            model_name: Alibaba embedding model name (default: text-embedding-v4)
            cache_dir: Directory for caching embeddings
            batch_size: Batch size for embedding generation
            api_key: Alibaba API key (defaults to DASHSCOPE_API_KEY env var)
            base_url: API base URL
        """
        self.model_name = model_name
        self.batch_size = batch_size
        self.cache_dir = Path(cache_dir) if cache_dir else None

        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Initialize OpenAI client for Alibaba API
        self.client = OpenAI(
            api_key=api_key or os.getenv("DASHSCOPE_API_KEY"),
            base_url=base_url
            or os.getenv("LLM_HOST")
            or "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        )

        # Embedding dimension for text-embedding-v4 is 1024
        self.embedding_dimension = 1024

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

            # Generate embeddings using Alibaba API
            # Process in batches to respect API limits
            all_embeddings = []
            for i in range(0, len(texts), self.batch_size):
                batch_texts = texts[i : i + self.batch_size]

                response = self.client.embeddings.create(
                    model=self.model_name, input=batch_texts
                )

                batch_embeddings = [item.embedding for item in response.data]
                all_embeddings.extend(batch_embeddings)

            # Update chunks and cache
            for chunk, embedding, idx in zip(
                chunks_to_embed, all_embeddings, chunk_indices
            ):
                chunk.embedding = embedding
                chunks[idx] = chunk

                if use_cache:
                    self._cache[chunk.id] = embedding

        return chunks

    def embed_query(self, query: str) -> List[float]:
        """
        Generate embedding for a query using Alibaba API.

        Args:
            query: Query text

        Returns:
            Embedding vector
        """
        response = self.client.embeddings.create(model=self.model_name, input=[query])
        return response.data[0].embedding

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
        """Get dimensionality of embeddings (1024 for text-embedding-v4)."""
        return self.embedding_dimension

    def clear_cache(self) -> None:
        """Clear embedding cache."""
        self._cache.clear()
