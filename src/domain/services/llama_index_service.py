"""LlamaIndex service: index management backed by Chroma.

Provides build, update, and delete operations for the LlamaIndex
``VectorStoreIndex`` that powers the rewritten LlamaIndex retriever.
"""

import logging
import os
from typing import Optional

from llama_index.core import VectorStoreIndex, Document as LIDocument, StorageContext
from llama_index.core.node_parser import SentenceSplitter
from llama_index.vector_stores.chroma import ChromaVectorStore
import chromadb

from ...core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class LlamaIndexService:
    """Manages the Chroma-backed LlamaIndex lifecycle.

    A single persisted ``ChromaCollection`` is used per application.
    Metadata filtering (e.g. ``document_id``) is handled at query time.
    """

    def __init__(self) -> None:
        self._index: Optional[VectorStoreIndex] = None
        self._vector_store: Optional[ChromaVectorStore] = None
        self._chroma_client: Optional[chromadb.PersistentClient] = None

    async def _ensure_index(self) -> VectorStoreIndex:
        """Lazy-initialize the Chroma collection and LlamaIndex."""
        if self._index is not None:
            return self._index

        persist_dir = settings.chroma_persist_dir
        os.makedirs(persist_dir, exist_ok=True)

        import asyncio
        self._chroma_client = await asyncio.to_thread(
            lambda: chromadb.PersistentClient(path=persist_dir)
        )
        chroma_collection = await asyncio.to_thread(
            self._chroma_client.get_or_create_collection, name="rag_pipeline"
        )

        self._vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
        storage_context = StorageContext.from_defaults(vector_store=self._vector_store)

        self._index = VectorStoreIndex.from_vector_store(
            self._vector_store, storage_context=storage_context
        )
        logger.info(f"Chroma/LlamaIndex initialised (persist_dir={persist_dir})")
        return self._index

    async def build_index(self, nodes: list[dict]) -> None:
        """Build or update the index from a list of document nodes.

        Each node dict must have:
          - ``id_`` (str): unique node identifier
          - ``text`` (str): chunk text
          - ``metadata`` (dict): at minimum ``document_id``, ``chunk_index``
        """
        index = await self._ensure_index()

        documents = [
            LIDocument(
                id_=node["id_"],
                text=node["text"],
                metadata=node.get("metadata", {}),
            )
            for node in nodes
        ]
        for doc in documents:
            index.insert(doc)
        logger.info(f"Indexed {len(documents)} nodes into Chroma")

    async def delete_document(self, document_id: str) -> None:
        """Remove all nodes belonging to a document from the Chroma index."""
        if self._chroma_client is None:
            logger.warning("Chroma client not initialised — skipping deletion")
            return
        collection = self._chroma_client.get_collection("rag_pipeline")
        collection.delete(where={"document_id": document_id})
        logger.info(f"Deleted document {document_id} from Chroma index")

    async def get_index(self) -> VectorStoreIndex:
        """Return the initialised index (lazy-loads on first call)."""
        return await self._ensure_index()


_service_instance: Optional[LlamaIndexService] = None


async def get_llama_index_service() -> LlamaIndexService:
    """Get or create the global LlamaIndex service instance."""
    global _service_instance
    if _service_instance is None:
        _service_instance = LlamaIndexService()
    return _service_instance


def reset_llama_index_service() -> None:
    """Reset the service instance (for testing)."""
    global _service_instance
    _service_instance = None
