from dataclasses import dataclass
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
    use_hyperlinks: bool = False
    is_system: bool = False
    description: Optional[str] = None

    @classmethod
    def recursive_strategy(cls, embedding_model: str) -> "ChunkingStrategy":
        return cls(
            id="recursive",
            name="Recursive",
            chunk_size=500,
            chunk_overlap=50,
            separators=["\n\n", "\n", ". "],
            embedding_model=embedding_model,
            is_system=True,
            description="Recursive chunking for general documents",
        )

    @classmethod
    def semantic_strategy(cls, embedding_model: str) -> "ChunkingStrategy":
        return cls(
            id="semantic",
            name="Semantic",
            chunk_size=300,
            chunk_overlap=30,
            separators=["\n## ", "\n### ", "\n", "## ", "### "],
            embedding_model=embedding_model,
            use_hyperlinks=False,
            is_system=True,
            description="Semantic chunking for structured content with optional hyperlink support",
        )


@dataclass
class ProcessingConfig:
    id: str
    document_id: str
    strategy_id: str
    chunk_size: int
    chunk_overlap: int
    separators: list[str]
    use_hyperlinks: bool
    engine_type: str
    created_at: Optional[str] = None


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
