from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class ChunkingStrategy:
    id: str
    name: str
    chunk_size: int
    chunk_overlap: int
    separators: list[str]
    embedding_model: str
    engine_type: str = "recursive"
    is_api_aware: bool = False
    is_system: bool = False
    description: Optional[str] = None

    @classmethod
    def default_strategy(cls, embedding_model: str) -> "ChunkingStrategy":
        return cls(
            id="default",
            name="Default",
            chunk_size=500,
            chunk_overlap=50,
            separators=["\n\n", "\n", ". "],
            embedding_model=embedding_model,
            is_system=True,
            description="Standard recursive chunking for general documents",
        )

    @classmethod
    def api_docs_strategy(cls, embedding_model: str) -> "ChunkingStrategy":
        return cls(
            id="api-docs",
            name="API Documentation",
            chunk_size=300,
            chunk_overlap=30,
            separators=["\n## ", "\n### ", "\n", "## ", "### "],
            embedding_model=embedding_model,
            is_api_aware=True,
            is_system=True,
            description="Specialized chunking for API documentation and OpenAPI specs",
        )


@dataclass
class DocumentMetadata:
    source: str
    page: Optional[int] = None
    section: Optional[str] = None
    title: Optional[str] = None


@dataclass
class Chunk:
    id: str
    document_id: str
    content: str
    chunk_index: int
    metadata: Optional[dict] = None


@dataclass
class RetrievedChunk:
    chunk: Chunk
    score: float


@dataclass
class APIEndpointInfo:
    path: str
    method: str
    operation_id: Optional[str]
    summary: Optional[str]
    description: Optional[str]
    parameters: Optional[dict]
    request_body: Optional[dict]
    responses: Optional[dict]
    tags: Optional[list[str]]
