from dataclasses import dataclass, field

from ..extraction.model import DocumentHierarchy


@dataclass
class ChunkData:
    content: str
    metadata: dict
    chunk_index: int


@dataclass
class PipelineContext:
    file_path: str
    parser_type: str = "pdfminer"
    element_tree: DocumentHierarchy | None = None
    enriched_tree: DocumentHierarchy | None = None
    boundaries: list[int] = field(default_factory=list)
    chunks: list[ChunkData] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    errors: list[dict] = field(default_factory=list)
