import logging
from typing import Optional

from ..extraction.model import DocumentElement, DocumentHierarchy
from ..enrichment.model import ComDocumentElement
from ..pipeline.context import ChunkData

logger = logging.getLogger(__name__)

ELEMENT_TYPE_TOKEN_LIMITS: dict[str, tuple[int, int]] = {
    "function": (400, 800),
    "property": (150, 400),
    "enum": (300, 600),
    "record": (200, 500),
    "error_code": (200, 400),
    "mixed": (200, 600),
    "fallback_text": (200, 800),
}

DEFAULT_MIN_TOKENS = 200
DEFAULT_MAX_TOKENS = 800
DEFAULT_OVERLAP_RATIO = 0.10


def _count_tokens(text: str) -> int:
    return len(text.split())


class ChunkAssembler:
    def __init__(
        self,
        min_tokens: int = DEFAULT_MIN_TOKENS,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        overlap_ratio: float = DEFAULT_OVERLAP_RATIO,
    ):
        self.min_tokens = min_tokens
        self.max_tokens = max_tokens
        self.overlap_ratio = overlap_ratio

    def assemble(
        self,
        hierarchy: DocumentHierarchy,
        boundaries: list[int],
    ) -> list[ChunkData]:
        flat = hierarchy.flatten_depth_first()
        if not flat:
            return []

        flat = self._strip_root(flat)
        if not flat:
            return []

        boundary_set = set(boundaries)
        segments: list[list[DocumentElement]] = []
        current_segment: list[DocumentElement] = []

        for i, el in enumerate(flat):
            if i in boundary_set and current_segment:
                segments.append(current_segment)
                current_segment = [el]
            else:
                current_segment.append(el)
        if current_segment:
            segments.append(current_segment)

        chunks: list[ChunkData] = []
        for seg_idx, segment in enumerate(segments):
            chunk = self._segment_to_chunk(segment, seg_idx)
            if chunk:
                chunks.append(chunk)

        chunks = self._merge_undersized(chunks)

        for chunk in chunks:
            chunk.metadata["token_count"] = _count_tokens(chunk.content)

        chunks = self._apply_overlap(chunks)

        for i, chunk in enumerate(chunks):
            chunk.chunk_index = i

        return chunks

    def _strip_root(self, flat: list[DocumentElement]) -> list[DocumentElement]:
        if len(flat) == 1 and flat[0].type == "PAGE" and flat[0].content == "":
            return flat[0].children
        return flat

    def _segment_to_chunk(self, segment: list[DocumentElement], seg_idx: int) -> Optional[ChunkData]:
        if not segment:
            return None
        content_parts: list[str] = []
        metadata: dict = self._build_metadata(segment)
        for el in segment:
            if el.content.strip():
                content_parts.append(el.content)
        full_content = "\n\n".join(content_parts)
        if not full_content.strip():
            return None

        element_type = metadata.get("element_type", "mixed")
        min_t, max_t = ELEMENT_TYPE_TOKEN_LIMITS.get(element_type, (self.min_tokens, self.max_tokens))
        min_t = max(min_t, self.min_tokens)
        max_t = max(max_t, self.max_tokens)

        token_count = _count_tokens(full_content)

        if token_count > max_t * 2:
            logger.warning(f"Chunk {seg_idx} exceeds 2x max_tokens ({token_count} > {max_t * 2}), splitting structurally")
            split_chunks = self._split_oversized(full_content, metadata, max_t)
            return split_chunks[0] if split_chunks else ChunkData(content=full_content, metadata=metadata, chunk_index=seg_idx)

        return ChunkData(content=full_content, metadata=metadata, chunk_index=seg_idx)

    def _build_metadata(self, segment: list[DocumentElement]) -> dict:
        metadata: dict = {
            "element_type": "mixed",
            "section_hierarchy": [],
            "confidence": 1.0,
        }
        com_types_found: set[str] = set()
        element_names: list[str] = []
        has_code = False
        section_hierarchy: list[str] = []

        for el in segment:
            if isinstance(el, ComDocumentElement) and el.com_type:
                type_map = {
                    "COM_METHOD": "function",
                    "COM_PROPERTY": "property",
                    "COM_ENUM": "enum",
                    "COM_RECORD": "record",
                    "COM_ERROR_CODE": "error_code",
                }
                mapped = type_map.get(el.com_type)
                if mapped:
                    com_types_found.add(mapped)
                if el.element_name:
                    element_names.append(el.element_name)
                if el.return_type:
                    metadata["return_type"] = el.return_type
                if el.signature:
                    metadata["signature"] = el.signature
                if el.parameters:
                    metadata["parameters"] = el.parameters
                if el.error_codes:
                    metadata["error_codes"] = el.error_codes
                if el.keywords:
                    metadata["keywords"] = el.keywords

            if el.type in ("CODE_BLOCK", "INFERRED_CODE_BLOCK"):
                has_code = True

            hierarchy = el.metadata.get("section_hierarchy", [])
            if hierarchy:
                section_hierarchy = hierarchy

        if len(com_types_found) == 1:
            metadata["element_type"] = next(iter(com_types_found))
        elif com_types_found:
            metadata["element_type"] = "mixed"

        if element_names:
            metadata["element_name"] = element_names[0]

        metadata["has_code_block"] = has_code
        metadata["section_hierarchy"] = section_hierarchy

        return metadata

    def _merge_undersized(self, chunks: list[ChunkData]) -> list[ChunkData]:
        if len(chunks) <= 1:
            return chunks

        merged: list[ChunkData] = []
        i = 0
        while i < len(chunks):
            current = chunks[i]
            token_count = _count_tokens(current.content)
            if token_count < self.min_tokens and i + 1 < len(chunks):
                next_chunk = chunks[i + 1]
                merged_content = current.content + "\n\n" + next_chunk.content
                merged_metadata = {**current.metadata}
                merged_metadata["merged_from"] = [
                    current.metadata.get("element_type"),
                    next_chunk.metadata.get("element_type"),
                ]
                merged.append(ChunkData(
                    content=merged_content,
                    metadata=merged_metadata,
                    chunk_index=len(merged),
                ))
                i += 2
            else:
                merged.append(current)
                i += 1
        return merged

    def _split_oversized(self, content: str, metadata: dict, max_tokens: int) -> list[ChunkData]:
        paragraphs = content.split("\n\n")
        chunks: list[ChunkData] = []
        current_parts: list[str] = []
        current_tokens = 0
        for para in paragraphs:
            para_tokens = _count_tokens(para)
            if current_tokens + para_tokens > max_tokens and current_parts:
                chunk_content = "\n\n".join(current_parts)
                chunks.append(ChunkData(content=chunk_content, metadata={**metadata}, chunk_index=0))
                current_parts = [para]
                current_tokens = para_tokens
            else:
                current_parts.append(para)
                current_tokens += para_tokens
        if current_parts:
            chunks.append(ChunkData(content="\n\n".join(current_parts), metadata={**metadata}, chunk_index=0))
        return chunks

    def _apply_overlap(self, chunks: list[ChunkData]) -> list[ChunkData]:
        if len(chunks) <= 1:
            return chunks

        result: list[ChunkData] = []
        for i, chunk in enumerate(chunks):
            content = chunk.content
            if i > 0:
                prev = chunks[i - 1]
                overlap_tokens = max(int(_count_tokens(prev.content) * self.overlap_ratio), 10)
                prev_words = prev.content.split()
                if len(prev_words) > overlap_tokens:
                    overlap_text = " ".join(prev_words[-overlap_tokens:])
                    content = overlap_text + "\n\n" + content
            result.append(ChunkData(
                content=content,
                metadata=chunk.metadata,
                chunk_index=i,
            ))
        return result
