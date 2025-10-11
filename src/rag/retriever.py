"""Hybrid retriever combining semantic and keyword search."""

from typing import List, Optional, Dict, Any, Tuple
import re
from collections import Counter
import math

from .models import CodeChunk, SearchResult
from .embedder import Embedder


class HybridRetriever:
    """
    Hybrid retrieval combining semantic search (embeddings) and keyword search (BM25).
    Optimized for code retrieval with reranking.
    """

    def __init__(
        self,
        embedder: Embedder,
        alpha: float = 0.7,  # Weight for semantic vs keyword (0=keyword, 1=semantic)
        k1: float = 1.5,  # BM25 parameter
        b: float = 0.75,  # BM25 parameter
    ):
        """
        Initialize hybrid retriever.

        Args:
            embedder: Embedder instance
            alpha: Balance between semantic (high) and keyword (low) search
            k1: BM25 k1 parameter
            b: BM25 b parameter
        """
        self.embedder = embedder
        self.alpha = alpha
        self.k1 = k1
        self.b = b

        # BM25 state
        self._doc_freqs: Dict[str, int] = {}
        self._idf_cache: Dict[str, float] = {}
        self._avg_doc_length = 0.0
        self._total_docs = 0

    def index_chunks(self, chunks: List[CodeChunk]) -> None:
        """
        Index chunks for BM25 keyword search.

        Args:
            chunks: List of code chunks to index
        """
        # Calculate document frequencies
        self._doc_freqs.clear()
        self._idf_cache.clear()

        doc_lengths = []

        for chunk in chunks:
            tokens = self._tokenize(chunk.get_searchable_content())
            doc_lengths.append(len(tokens))

            # Count unique terms
            unique_tokens = set(tokens)
            for token in unique_tokens:
                self._doc_freqs[token] = self._doc_freqs.get(token, 0) + 1

        # Calculate average document length
        self._total_docs = len(chunks)
        self._avg_doc_length = sum(doc_lengths) / len(doc_lengths) if doc_lengths else 0

        # Precompute IDF values
        for term, df in self._doc_freqs.items():
            self._idf_cache[term] = self._compute_idf(df)

    def search(
        self,
        query: str,
        chunks: List[CodeChunk],
        top_k: int = 5,
        rerank: bool = True,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        """
        Hybrid search combining semantic and keyword retrieval.

        Args:
            query: Search query
            chunks: Code chunks to search
            top_k: Number of results to return
            rerank: Whether to rerank results
            filters: Optional filters (language, file_path, etc.)

        Returns:
            List of search results
        """
        # Apply filters
        filtered_chunks = self._apply_filters(chunks, filters)

        if not filtered_chunks:
            return []

        # Get semantic scores
        query_embedding = self.embedder.embed_query(query)
        semantic_scores = self._compute_semantic_scores(query_embedding, filtered_chunks)

        # Get keyword scores
        keyword_scores = self._compute_bm25_scores(query, filtered_chunks)

        # Combine scores
        combined_scores = []
        for i, chunk in enumerate(filtered_chunks):
            semantic_score = semantic_scores[i]
            keyword_score = keyword_scores[i]

            # Weighted combination
            combined_score = (
                self.alpha * semantic_score + (1 - self.alpha) * keyword_score
            )

            combined_scores.append(
                (chunk, combined_score, semantic_score, keyword_score)
            )

        # Sort by combined score
        combined_scores.sort(key=lambda x: x[1], reverse=True)

        # Take top-k
        top_results = combined_scores[:top_k * 2 if rerank else top_k]

        # Create search results
        results = []
        for rank, (chunk, score, sem_score, kw_score) in enumerate(top_results):
            results.append(
                SearchResult(
                    chunk=chunk,
                    score=score,
                    semantic_score=sem_score,
                    keyword_score=kw_score,
                    rank=rank,
                )
            )

        # Optional reranking
        if rerank and len(results) > top_k:
            results = self._rerank(query, results, top_k)

        return results[:top_k]

    def _compute_semantic_scores(
        self, query_embedding: List[float], chunks: List[CodeChunk]
    ) -> List[float]:
        """Compute semantic similarity scores."""
        scores = []

        for chunk in chunks:
            if not chunk.embedding:
                # Generate embedding if missing
                chunk.embedding = self.embedder.embed_query(
                    chunk.get_searchable_content()
                )

            similarity = self.embedder.compute_similarity(query_embedding, chunk.embedding)
            scores.append(similarity)

        return scores

    def _compute_bm25_scores(self, query: str, chunks: List[CodeChunk]) -> List[float]:
        """Compute BM25 scores for keyword search."""
        query_tokens = self._tokenize(query)
        scores = []

        for chunk in chunks:
            doc_tokens = self._tokenize(chunk.get_searchable_content())
            doc_length = len(doc_tokens)
            term_freqs = Counter(doc_tokens)

            score = 0.0
            for term in query_tokens:
                if term in term_freqs:
                    tf = term_freqs[term]
                    idf = self._idf_cache.get(term, 0.0)

                    # BM25 formula
                    numerator = tf * (self.k1 + 1)
                    denominator = tf + self.k1 * (
                        1 - self.b + self.b * (doc_length / self._avg_doc_length)
                    )

                    score += idf * (numerator / denominator)

            # Normalize by query length
            scores.append(score / max(len(query_tokens), 1))

        # Normalize scores to 0-1 range
        if scores:
            max_score = max(scores)
            if max_score > 0:
                scores = [s / max_score for s in scores]

        return scores

    def _compute_idf(self, doc_freq: int) -> float:
        """Compute IDF (Inverse Document Frequency)."""
        return math.log((self._total_docs - doc_freq + 0.5) / (doc_freq + 0.5) + 1.0)

    def _tokenize(self, text: str) -> List[str]:
        """Tokenize text for keyword search."""
        # Simple tokenization: lowercase, split on non-alphanumeric
        text = text.lower()
        tokens = re.findall(r'\w+', text)
        return tokens

    def _apply_filters(
        self, chunks: List[CodeChunk], filters: Optional[Dict[str, Any]]
    ) -> List[CodeChunk]:
        """Apply filters to chunks."""
        if not filters:
            return chunks

        filtered = chunks

        if "language" in filters:
            filtered = [c for c in filtered if c.language == filters["language"]]

        if "file_path" in filters:
            filtered = [c for c in filtered if filters["file_path"] in c.file_path]

        if "chunk_type" in filters:
            filtered = [c for c in filtered if c.chunk_type == filters["chunk_type"]]

        return filtered

    def _rerank(
        self, query: str, results: List[SearchResult], top_k: int
    ) -> List[SearchResult]:
        """
        Rerank results using additional signals.

        Args:
            query: Original query
            results: Initial results
            top_k: Number of top results to return

        Returns:
            Reranked results
        """
        query_lower = query.lower()

        # Apply reranking heuristics
        for result in results:
            boost = 0.0

            # Boost if query term in name
            if result.chunk.name and query_lower in result.chunk.name.lower():
                boost += 0.1

            # Boost if query term in docstring
            if result.chunk.docstring and query_lower in result.chunk.docstring.lower():
                boost += 0.05

            # Boost functions over other types
            if result.chunk.chunk_type in {"function_definition", "method_definition"}:
                boost += 0.02

            # Apply boost
            result.score = min(1.0, result.score + boost)

        # Re-sort with boosted scores
        results.sort(key=lambda x: x.score, reverse=True)

        # Update ranks
        for rank, result in enumerate(results):
            result.rank = rank

        return results
