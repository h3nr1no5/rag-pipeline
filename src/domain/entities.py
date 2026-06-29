from dataclasses import dataclass


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
    description: str | None = None
    config: dict | None = None


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
    created_at: str | None = None


@dataclass
class DocumentMetadata:
    source: str
    page: int | None = None
    section: str | None = None
    title: str | None = None


@dataclass
class Chunk:
    id: str
    document_id: str
    content: str
    chunk_index: int
    metadata: dict | None = None


@dataclass
class RetrievedChunk:
    chunk: Chunk
    score: float


@dataclass
class APIEndpointInfo:
    path: str
    method: str
    operation_id: str | None
    summary: str | None
    description: str | None
    parameters: dict | None
    request_body: dict | None
    responses: dict | None
    tags: list[str] | None
