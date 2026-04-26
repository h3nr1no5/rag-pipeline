from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime


class ChunkingStrategyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: Optional[str] = None
    chunk_size: int = Field(ge=50, le=2000)
    chunk_overlap: int = Field(ge=0, le=500)
    separators: list[str] = Field(default_factory=lambda: ["\n\n", "\n", ". "])
    is_api_aware: bool = False


class ChunkingStrategyResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    chunk_size: int
    chunk_overlap: int
    separators: list[str]
    is_api_aware: bool
    is_system: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentUploadResponse(BaseModel):
    id: str
    title: str
    doc_type: str
    status: str
    message: str


class DocumentResponse(BaseModel):
    id: str
    title: str
    doc_type: str
    status: str
    is_api_doc: bool
    chunk_count: int
    file_size: Optional[int]
    created_at: datetime
    chunking_strategy: ChunkingStrategyResponse
    embedded: bool

    model_config = ConfigDict(from_attributes=True)


class DocumentListResponse(BaseModel):
    documents: list[DocumentResponse]
    total: int


class ChunkResponse(BaseModel):
    id: str
    content: str
    chunk_index: int
    metadata: Optional[dict]
    embedding: Optional[list[float]] = None

    model_config = ConfigDict(from_attributes=True)


class DocumentChunksResponse(BaseModel):
    document_id: str
    chunks: list[ChunkResponse]
    total: int
