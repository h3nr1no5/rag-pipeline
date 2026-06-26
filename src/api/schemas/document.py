from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ChunkingStrategyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    chunk_size: int = Field(ge=50, le=2000)
    chunk_overlap: int = Field(ge=0, le=500)
    separators: list[str] = Field(default_factory=lambda: ["\n\n", "\n", ". "])
    use_hyperlinks: bool = Field(default=False)
    config: dict | None = None


class ChunkingStrategyUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = None
    chunk_size: int | None = Field(None, ge=50, le=2000)
    chunk_overlap: int | None = Field(None, ge=0, le=500)
    separators: list[str] | None = None
    use_hyperlinks: bool | None = None
    config: dict | None = None


class ChunkingStrategyResponse(BaseModel):
    id: str
    name: str
    description: str | None
    chunk_size: int
    chunk_overlap: int
    separators: list[str]
    use_hyperlinks: bool = Field(...)
    is_system: bool
    engine_type: str
    config: dict | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProcessingConfigResponse(BaseModel):
    id: str
    document_id: str
    strategy_id: str
    chunk_size: int
    chunk_overlap: int
    separators: list[str]
    use_hyperlinks: bool
    engine_type: str
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
    chunk_count: int
    file_size: int | None
    created_at: datetime
    chunking_strategy: ChunkingStrategyResponse
    embedded: bool
    parsing_progress: int = 0
    chunking_progress: int = 0
    saving_progress: int = 0
    saved_chunks: int = 0
    processing_config: ProcessingConfigResponse | None = None
    processing_configs: list[ProcessingConfigResponse] = []

    model_config = ConfigDict(from_attributes=True)


class DocumentListResponse(BaseModel):
    documents: list[DocumentResponse]
    total: int


class ChunkResponse(BaseModel):
    id: str
    content: str
    chunk_index: int
    metadata: dict | None
    embedding: list[float] | None = None

    model_config = ConfigDict(from_attributes=True)


class DocumentChunksResponse(BaseModel):
    document_id: str
    chunks: list[ChunkResponse]
    total: int


class ParamInfo(BaseModel):
    """Describes a single configurable parameter for a chunking strategy type."""

    type: str  # "integer", "string", "array", "boolean", "object"
    default: Any | None = None
    description: str = ""
    items: str | None = None  # for array type
    enum: list[str] | None = None  # for string enums
    nullable: bool = False


class StrategyTypeInfo(BaseModel):
    """Describes one chunking engine type and its configurable parameters."""

    params: dict[str, ParamInfo] | None = None  # for recursive/semantic
    config_schema: dict[str, ParamInfo] | None = None  # for api-docs


class StrategyTypesResponse(BaseModel):
    """Response for GET /strategies/types."""

    types: dict[str, StrategyTypeInfo]


# ── Static schema definitions for each chunking engine type ──────────────
# These are hardcoded (not from DB) so UI clients can dynamically render
# config forms without needing to know the schema ahead of time.

STRATEGY_TYPE_SCHEMAS: dict[str, StrategyTypeInfo] = {
    "recursive": StrategyTypeInfo(
        params={
            "chunk_size": ParamInfo(
                type="integer",
                default=1000,
                description="Maximum chunk size in characters",
            ),
            "chunk_overlap": ParamInfo(
                type="integer",
                default=200,
                description="Overlap between chunks",
            ),
            "separators": ParamInfo(
                type="array",
                items="string",
                default=["\n\n", "\n", ". "],
                description="Separator strings in priority order",
            ),
            "min_chunk_length": ParamInfo(
                type="integer",
                default=20,
                description="Minimum chunk length to keep",
            ),
        }
    ),
    "semantic": StrategyTypeInfo(
        params={
            "chunk_size": ParamInfo(
                type="integer",
                default=300,
                description="Maximum chunk size in characters",
            ),
            "chunk_overlap": ParamInfo(
                type="integer",
                default=30,
                description="Overlap between chunks",
            ),
            "separators": ParamInfo(
                type="array",
                items="string",
                default=["\n## ", "\n### ", "\n", "## ", "### "],
                description="Separator strings in priority order",
            ),
            "use_hyperlinks": ParamInfo(
                type="boolean",
                default=False,
                description="Enable hyperlink extraction",
            ),
            "min_chunk_length": ParamInfo(
                type="integer",
                default=20,
                description="Minimum chunk length to keep",
            ),
        }
    ),
    "api-docs": StrategyTypeInfo(
        config_schema={
            "type_patterns": ParamInfo(
                type="object",
                description="Regex patterns per entity type for extracting interface/enum/record names from headings",
            ),
            "heading_policy": ParamInfo(
                type="object",
                description="Heading level to interface nesting rules (interface_levels, section_levels, ignore_levels)",
            ),
            "max_depth": ParamInfo(
                type="integer",
                default=3,
                description="Maximum nesting depth for chunk tree traversal",
            ),
            "include_entities": ParamInfo(
                type="array",
                items="string",
                nullable=True,
                default=None,
                description="Whitelist of entity types to include (null = all)",
            ),
            "format_style": ParamInfo(
                type="string",
                enum=["detailed", "compact"],
                default="detailed",
                description="Output format style",
            ),
            "include_signatures": ParamInfo(
                type="boolean",
                default=True,
                description="Include method/field signatures in output",
            ),
            "include_descriptions": ParamInfo(
                type="boolean",
                default=True,
                description="Include text descriptions in output",
            ),
            "min_chunk_length": ParamInfo(
                type="integer",
                default=20,
                description="Minimum chunk length to keep",
            ),
        }
    ),
}
