"""Pydantic models for the API documentation RAG pipeline request/response."""

from pydantic import BaseModel, Field


class ApiDocQueryRequest(BaseModel):
    """Request model for querying an API documentation document."""

    query: str
    document_id: str  # The document to search against (supports both DOCX and PDF docs)
    top_k: int = Field(default=10, ge=1, le=50)
    rerank_k: int = Field(
        default=20, ge=0, le=50,
        description=(
            "Number of RRF-fused candidates to rerank with the cross-encoder. "
            "Set to 0 to skip reranking. Default 20. Max 50 to limit compute."
        ),
    )


class ApiDocSource(BaseModel):
    """A single source chunk returned in an API doc query response."""

    chunk_id: str
    content: str
    score: float
    kind: str = ""
    interface_name: str = ""
    function_name: str = ""


class ApiDocQueryResponse(BaseModel):
    """Response model for API documentation queries."""

    answer: str
    sources: list[ApiDocSource]
    citations: list[str] = []
    relevant_functions: list[str] = []
    relevant_types: list[str] = []
    confidence: float = 0.0
    cached: bool = False
    latency_ms: int = 0
    unsupported_sentences: list[str] = []
    """Sentences removed by response verification (empty when all verified)."""
