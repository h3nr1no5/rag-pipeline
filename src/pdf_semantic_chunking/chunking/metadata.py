import os
import re
import uuid
from datetime import UTC, datetime

from ..pipeline.context import ChunkData


class MetadataEnricher:
    def enrich(self, chunks: list[ChunkData], source_document: str) -> list[ChunkData]:
        enriched: list[ChunkData] = []
        sanitized_name = os.path.basename(source_document)
        for chunk in chunks:
            meta = dict(chunk.metadata)

            meta["chunk_id"] = str(uuid.uuid4())
            meta["source_document"] = sanitized_name
            meta["created_at"] = datetime.now(UTC).isoformat()

            if meta.get("element_name"):
                meta["keywords"] = self._extract_keywords(str(meta["element_name"]), chunk.content)

            enriched.append(ChunkData(
                content=chunk.content,
                metadata=meta,
                chunk_index=chunk.chunk_index,
            ))
        return enriched

    def _extract_keywords(self, element_name: str, content: str) -> list[str]:
        keywords: list[str] = []

        camel_parts = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)", element_name)
        keywords.extend(p.lower() for p in camel_parts if len(p) > 1)

        content_lower = content.lower()
        common_terms = ["error", "code", "return", "value", "get", "set", "interface", "method"]
        for term in common_terms:
            if term in content_lower and term not in keywords:
                keywords.append(term)

        return list(dict.fromkeys(keywords))
