from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    document_ids: list[str] = Field(default_factory=list)

    # Tunable RAG parameters
    temperature: float = Field(default=0.5, ge=0.0, le=1.0, description="LLM temperature (0=factual, 1=creative)")  # noqa: E501
    max_tokens: int = Field(default=600, ge=50, le=4096, description="Max tokens to generate")
    top_k: int = Field(default=5, ge=1, le=20, description="Number of chunks to retrieve")
    prompt_sources: int = Field(default=3, ge=1, le=10, description="Number of chunks to use in prompt")  # noqa: E501

    # Citation control
    include_citations: bool = Field(
        default=True,
        description="Include source citations in the response"
    )

    # NEW - Response verbosity
    response_length: str = Field(
        default="normal",
        description="Response verbosity: concise (1-2 sentences), normal (3-5), detailed (full)",
        pattern="^(concise|normal|detailed)$"
    )

    # Response cleaning control
    clean_response: bool = Field(
        default=True,
        description="Apply response cleaning pipeline"
    )

    # Link traversal parameters
    link_decay_factor: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Score decay factor for link-traversal results (0=disable, 0.85=default)"
    )
    link_expansion_factor: int = Field(
        default=2,
        ge=1,
        le=10,
        description="Max expansion multiplier for link-traversal results"
    )


class SourceChunk(BaseModel):
    chunk_id: str
    content: str
    score: float
    metadata: dict | None = None


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceChunk]
    cached: bool = False
    latency_ms: int


class QueryHistoryItem(BaseModel):
    id: str
    query_text: str
    response_text: str
    source_chunk_ids: list[str] | None
    created_at: datetime
    expires_at: datetime

    model_config = ConfigDict(from_attributes=True)


class QueryHistoryResponse(BaseModel):
    queries: list[QueryHistoryItem]
    total: int


class SSEEvent(BaseModel):
    token: str | None = None
    sources: list[SourceChunk] | None = None
    cached: bool | None = None
    latency_ms: int | None = None
    done: bool = False
    error: str | None = None


# ── Async task-based query schemas ──────────────────────────────────────────


class QueryStartRequest(BaseModel):
    """Request schema for starting an async RAG query."""

    question: str = Field(min_length=1, max_length=2000)
    document_ids: list[str] = Field(default_factory=list)

    # Tunable RAG parameters
    temperature: float = Field(default=0.5, ge=0.0, le=1.0)
    max_tokens: int = Field(default=600, ge=50, le=4096)
    top_k: int = Field(default=5, ge=1, le=20)
    prompt_sources: int = Field(default=3, ge=1, le=10)

    include_citations: bool = Field(default=True)
    response_length: str = Field(
        default="normal",
        pattern="^(concise|normal|detailed)$",
    )
    clean_response: bool = Field(default=True)

    link_decay_factor: float = Field(default=0.85, ge=0.0, le=1.0)
    link_expansion_factor: int = Field(default=2, ge=1, le=10)

    enable_rag: bool = Field(default=True)
    enable_docs: bool = Field(default=True)
    backends: list[str] = Field(
        default_factory=lambda: ["cosine", "langchain", "llamaindex"],
    )

    ALLOWED_BACKENDS: ClassVar[set[str]] = {"cosine", "langchain", "llamaindex"}

    @field_validator("backends")
    @classmethod
    def validate_backends(cls, v: list[str]) -> list[str]:
        for b in v:
            if b not in cls.ALLOWED_BACKENDS:
                raise ValueError(
                    f"Invalid backend: {b}. Allowed: {', '.join(sorted(cls.ALLOWED_BACKENDS))}"
                )
        return v


class QueryStartResponse(BaseModel):
    """Response returned immediately after starting an async query."""

    task_id: str
    status: str


class BackendResultSchema(BaseModel):
    """Schema version of BackendResult for API serialization."""

    backend: str
    answer: str
    sources: list[SourceChunk] = Field(default_factory=list)
    error: str | None = None
    cached: bool = False
    confidence: float = 0.0
    relevant_functions: list[str] = Field(default_factory=list)
    relevant_types: list[str] = Field(default_factory=list)
    reasoning_hint: str = ""


class TaskStatusResponse(BaseModel):
    """Polling response for an async query task."""

    task_id: str
    status: str
    results: list[BackendResultSchema] = Field(default_factory=list)
    progress: dict[str, str] = Field(default_factory=dict)
    error: str | None = None
    created_at: float
    completed_at: float | None = None
