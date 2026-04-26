from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    document_ids: list[str] = Field(default_factory=list)


class SourceChunk(BaseModel):
    chunk_id: str
    content: str
    score: float
    metadata: Optional[dict] = None


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceChunk]
    cached: bool = False
    latency_ms: int


class QueryHistoryItem(BaseModel):
    id: str
    query_text: str
    response_text: str
    source_chunk_ids: Optional[list[str]]
    created_at: datetime
    expires_at: datetime

    model_config = ConfigDict(from_attributes=True)


class QueryHistoryResponse(BaseModel):
    queries: list[QueryHistoryItem]
    total: int


class SSEEvent(BaseModel):
    token: Optional[str] = None
    sources: Optional[list[SourceChunk]] = None
    cached: Optional[bool] = None
    latency_ms: Optional[int] = None
    done: bool = False
    error: Optional[str] = None
