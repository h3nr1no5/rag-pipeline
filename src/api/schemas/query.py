from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    document_ids: list[str] = Field(default_factory=list)

    # Tunable RAG parameters
    temperature: float = Field(default=0.5, ge=0.0, le=1.0, description="LLM temperature (0=factual, 1=creative)")  # noqa: E501
    max_tokens: int = Field(default=600, ge=50, le=2000, description="Max tokens to generate")
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
