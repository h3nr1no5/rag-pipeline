"""API documentation chunking module.

Converts structured COM domain objects into a directed acyclic graph of
text chunks suitable for embedding, retrieval and LLM-based generation.
"""

from src.domain.rag.api_docs.chunking.builder import ChunkGraph, ChunkGraphBuilder
from src.domain.rag.api_docs.chunking.graph import ChunkNode
from src.domain.rag.api_docs.chunking.serializer import (
    deserialize_chunk_graph,
    serialize_chunk_graph,
)
from src.domain.rag.api_docs.chunking.text_formatter import ChunkTextFormatter

__all__ = [
    "ChunkGraph",
    "ChunkGraphBuilder",
    "ChunkNode",
    "ChunkTextFormatter",
    "deserialize_chunk_graph",
    "serialize_chunk_graph",
]
