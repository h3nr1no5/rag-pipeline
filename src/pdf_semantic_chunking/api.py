import asyncio
import logging

from .errors import SemanticChunkingError

logger = logging.getLogger(__name__)


async def chunk_pdf(file_path: str, **kwargs) -> dict:
    from .cli import chunk_pdf_async

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: asyncio.run(chunk_pdf_async(file_path, **kwargs)),
    )


__all__ = ["chunk_pdf", "SemanticChunkingError"]
