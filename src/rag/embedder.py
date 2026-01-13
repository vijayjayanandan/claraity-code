"""Embedder for generating vector embeddings of code chunks using OpenAI-compatible APIs."""

from typing import List, Optional, Dict, Any
import numpy as np
from pathlib import Path
import pickle
import os
from openai import OpenAI

from .models import CodeChunk


class Embedder:
    """
    Generates and caches embeddings for code chunks using OpenAI-compatible APIs.
    Supports any embedding service with OpenAI-compatible endpoints.
    """

    def __init__(
        self,
        model_name: str,
        cache_dir: Optional[str] = None,
        batch_size: Optional[int] = None,
        api_key: Optional[str] = None,
        api_key_env: str = "EMBEDDING_API_KEY",
        base_url: Optional[str] = None,
        embedding_dimension: Optional[int] = None,
    ):
        """
        Initialize embedder with OpenAI-compatible API.

        Args:
            model_name: Embedding model name (required, no default)
            cache_dir: Directory for caching embeddings
            batch_size: Batch size for embedding generation (from .env EMBEDDING_BATCH_SIZE)
            api_key: API key (optional, will use env var if not provided)
            api_key_env: Environment variable name for API key (default: EMBEDDING_API_KEY)
            base_url: API base URL (from .env EMBEDDING_BASE_URL)
            embedding_dimension: Dimension of embeddings (from .env EMBEDDING_DIMENSION)
        """
        self.model_name = model_name
        # Read batch_size from .env
        self.batch_size = batch_size or int(os.getenv("EMBEDDING_BATCH_SIZE", "10"))
        self.cache_dir = Path(cache_dir) if cache_dir else None

        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Get API key from parameter or environment variable
        resolved_api_key = api_key or os.getenv(api_key_env)
        if not resolved_api_key:
            # Fallback to OPENAI_API_KEY if EMBEDDING_API_KEY is not set
            resolved_api_key = os.getenv("OPENAI_API_KEY")
        if not resolved_api_key:
            raise ValueError(
                f"Embedding API key not provided. Set {api_key_env} or OPENAI_API_KEY environment variable "
                f"or pass api_key parameter."
            )

        # Get base URL from parameter or environment variable
        resolved_base_url = base_url or os.getenv("EMBEDDING_BASE_URL")
        if not resolved_base_url:
            raise ValueError(
                "Embedding base URL not provided. Set EMBEDDING_BASE_URL environment variable "
                "or pass base_url parameter."
            )

        # Initialize OpenAI client with provided configuration
        self.client = OpenAI(
            api_key=resolved_api_key,
            base_url=resolved_base_url,
        )

        # Embedding dimension from parameter or environment
        self.embedding_dimension = embedding_dimension or int(os.getenv("EMBEDDING_DIMENSION", "1536"))
        if not self.embedding_dimension:
            raise ValueError(
                "Embedding dimension not provided. Set EMBEDDING_DIMENSION environment variable "
                "or pass embedding_dimension parameter."
            )

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
