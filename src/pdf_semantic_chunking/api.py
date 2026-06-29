import logging

from .errors import SemanticChunkingError

logger = logging.getLogger(__name__)


async def chunk_pdf(file_path: str, chunk_size: int = 800, chunk_overlap: int = 80, **kwargs) -> dict:  # noqa: E501
    from .cli import chunk_pdf_async

    return await chunk_pdf_async(file_path, chunk_size=chunk_size, chunk_overlap=chunk_overlap, **kwargs)  # noqa: E501


__all__ = ["SemanticChunkingError", "chunk_pdf"]
