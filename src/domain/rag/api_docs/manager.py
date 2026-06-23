"""Manager for API documentation RAG pipeline orchestration.

Provides a singleton :class:`ApiDocPipelineManager` that coordinates:

* In-memory storage of indexed documents (ChunkGraph + HybridRetriever per doc)
* Pipeline orchestration: extract -> chunk -> index
* Query execution: retrieve -> generate
"""

from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path

from src.domain.rag.api_docs.chunking.builder import ChunkGraph, ChunkGraphBuilder
from src.domain.rag.api_docs.chunking.graph import ChunkNode
from src.domain.rag.api_docs.chunking.text_formatter import ChunkTextFormatter
from src.domain.rag.api_docs.extraction.converter import DocumentConverter
from src.domain.rag.api_docs.extraction.docx_parser import DocxParser
from src.domain.rag.api_docs.extraction.pdf_fallback import PdfFallbackExtractor
from src.domain.rag.api_docs.extraction.table_detector import (
    TableDetector,
    merge_multi_row_functions,
)
from src.domain.rag.api_docs.pipeline.schemas import ApiDocQueryResponse, ApiDocSource
from src.domain.rag.api_docs.retrieval.bm25_index import ApiBm25Index
from src.domain.rag.api_docs.retrieval.embedding_index import ApiEmbeddingIndex
from src.domain.rag.api_docs.retrieval.hybrid_retriever import HybridRetriever

logger = logging.getLogger(__name__)


class ApiDocPipelineManager:
    """Manages in-memory storage, pipeline orchestration, and query execution.

    Thread-safe for async usage; uses a module-level singleton.  Each indexed
    document is stored in memory as a dict with keys:

    * ``graph``       — :class:`ChunkGraph`
    * ``retriever``   — :class:`HybridRetriever`
    * ``interfaces``  — list of :class:`APIInterface`
    * ``enums``       — list of :class:`APIEnum`
    * ``error_codes`` — list of :class:`APIErrorCode`
    * ``doc_type``    — ``"docx"`` or ``"pdf"``
    """

    def __init__(self) -> None:
        # Keyed by (user_id, document_id) to prevent cross-user data leaks
        self._indexed_docs: dict[tuple[str, str], dict] = {}
        self._table_detector = TableDetector()
        self._graph_builder = ChunkGraphBuilder()
        self._text_formatter = ChunkTextFormatter()

    # ------------------------------------------------------------------
    # Startup recovery — load from database
    # ------------------------------------------------------------------

    def load_from_db(
        self,
        document_id: str,
        user_id: str,
        domain_data: dict,
        graph_data: dict,
        embeddings: dict | None,
        embedding_dim: int | None,
    ) -> None:
        """Restore an indexed document from serialised database data.

        Args:
            document_id: The document identifier.
            user_id: The document owner identifier.
            domain_data: Dict with keys ``interfaces``, ``enums``, ``error_codes``.
            graph_data: Serialised chunk graph (from ``serialize_chunk_graph``).
            embeddings: Optional mapping of ``chunk_id`` → embedding vector.
            embedding_dim: Dimensionality of the embedding vectors.
        """
        from src.domain.rag.api_docs.chunking.serializer import (
            deserialize_chunk_graph,
        )

        # Deserialize domain data
        interfaces = domain_data.get("interfaces", [])
        enums = domain_data.get("enums", [])
        error_codes = domain_data.get("error_codes", [])

        # Deserialize chunk graph
        graph = deserialize_chunk_graph(graph_data)

        # Build BM25 index
        bm25_index = ApiBm25Index()
        bm25_index.add_graph(graph)

        # Build embedding index (if embeddings available)
        embedding_index = ApiEmbeddingIndex()
        if embeddings is not None and embedding_dim is not None:
            try:
                embedding_index.load_embeddings(embeddings, embedding_dim)
            except Exception as exc:
                logger.warning(
                    "Failed to load embeddings for %s: %s. "
                    "Falling back to BM25-only.",
                    document_id,
                    exc,
                )
        else:
            reason = (
                "missing" if embeddings is None else "dimension mismatch"
            )
            logger.warning(
                "Skipping FAISS rebuild for %s: embeddings=%s",
                document_id,
                reason,
            )

        # Create hybrid retriever
        retriever = HybridRetriever(bm25_index, embedding_index, graph)

        self._indexed_docs[(user_id, document_id)] = {
            "graph": graph,
            "retriever": retriever,
            "interfaces": interfaces,
            "enums": enums,
            "error_codes": error_codes,
            "doc_type": "docx",
            "user_id": user_id,
        }

    async def load_all_from_db(self, async_session) -> None:
        """Query all ``ApiDocIndex`` rows and rebuild in-memory indexes.

        Joins with the ``Document`` table to retrieve the correct ``user_id``
        for each index row, preventing cross-user data leaks.

        Args:
            async_session: An async SQLAlchemy session factory or session.
        """
        from sqlalchemy import select

        from src.infrastructure.database.models import ApiDocIndex, Document

        result = await async_session.execute(
            select(ApiDocIndex, Document.user_id)
            .join(Document, ApiDocIndex.document_id == Document.id)
        )
        rows = result.all()

        count = 0
        for api_doc_index, user_id in rows:
            self.load_from_db(
                document_id=api_doc_index.document_id,
                user_id=user_id,
                domain_data=api_doc_index.domain_data,
                graph_data=api_doc_index.graph_data,
                embeddings=api_doc_index.embeddings,
                embedding_dim=api_doc_index.embedding_dim,
            )
            count += 1

        logger.info(
            "Loaded %d API doc(s) from database into in-memory indexes", count
        )

    # ------------------------------------------------------------------
    # Ingestion — DOCX
    # ------------------------------------------------------------------

    async def ingest_docx(self, file_path: str | Path, document_id: str, user_id: str = "") -> dict:
        """Run the full DOCX pipeline: parse → detect → convert → chunk → index.

        Args:
            file_path: Path to the ``.docx`` file on disk.
            document_id: Unique identifier for the document (used as the
                         ``source_doc`` in the chunk graph).

        Returns:
            A status dict with keys ``document_id``, ``chunk_count``,
            ``interface_count``, ``enum_count``, ``error_code_count``, ``status``.
        """
        # Stage 1: Parse
        logger.info("Pipeline stage 1/5: Parsing DOCX %s", file_path)
        parser = DocxParser(str(file_path))
        raw_doc = parser.parse()
        logger.info(
            "  → %d paragraphs, %d tables",
            len(raw_doc.paragraphs),
            len(raw_doc.tables),
        )

        # Stage 2: Detect table types & merge
        logger.info("Pipeline stage 2/5: Detecting table types & merging")
        table_types: dict[int, str] = {}
        for i, table in enumerate(raw_doc.tables):
            table_types[i] = self._table_detector.detect(table)
        merged_tables = merge_multi_row_functions(raw_doc.tables)
        type_counts: dict[str, int] = {}
        for tt in table_types.values():
            type_counts[tt] = type_counts.get(tt, 0) + 1
        logger.info("  → table types: %s", type_counts)

        # Stage 3: Convert to domain objects
        logger.info("Pipeline stage 3/5: Converting to domain objects")
        converter = DocumentConverter()
        domain_result = converter.convert(raw_doc, table_types, merged_tables)
        interfaces = domain_result["interfaces"]
        enums = domain_result["enums"]
        error_codes = domain_result["error_codes"]
        logger.info(
            "  → %d interfaces, %d enums, %d error codes",
            len(interfaces),
            len(enums),
            len(error_codes),
        )

        # Stage 4: Build chunk graph
        logger.info("Pipeline stage 4/5: Building chunk graph")
        graph = self._graph_builder.build(
            interfaces=interfaces,
            enums=enums,
            error_codes=error_codes,
            source_doc=document_id,
        )
        self._text_formatter.format_graph(graph, interfaces, enums, error_codes)
        logger.info("  → %d nodes in graph", len(graph.nodes))

        # Stage 5: Index
        logger.info("Pipeline stage 5/5: Indexing in BM25 + Embedding indexes")
        bm25_index = ApiBm25Index()
        embedding_index = ApiEmbeddingIndex()
        retriever = HybridRetriever(bm25_index, embedding_index, graph)
        await retriever.ingest_graph(
            graph,
            self._text_formatter,
            interfaces=interfaces,
            enums=enums,
            error_codes=error_codes,
        )
        logger.info("  → Indexing complete")

        self._indexed_docs[(user_id, document_id)] = {
            "graph": graph,
            "retriever": retriever,
            "interfaces": interfaces,
            "enums": enums,
            "error_codes": error_codes,
            "doc_type": "docx",
            "user_id": user_id,
        }

        return {
            "document_id": document_id,
            "chunk_count": len(graph.nodes),
            "interface_count": len(interfaces),
            "enum_count": len(enums),
            "error_code_count": len(error_codes),
            "status": "indexed",
        }

    # ------------------------------------------------------------------
    # Ingestion — PDF fallback
    # ------------------------------------------------------------------

    async def ingest_pdf(self, file_path: str | Path, document_id: str, user_id: str = "") -> dict:
        """Ingest a PDF file using :class:`PdfFallbackExtractor`.

        Because PDF extraction does not produce structured tables, each page
        is stored as a single ``section``-kind chunk node.

        Args:
            file_path: Path to the ``.pdf`` file on disk.
            document_id: Unique identifier for the document.

        Returns:
            A status dict with keys ``document_id``, ``chunk_count``, ``status``.
        """
        # Stage 1: Extract
        logger.info("Pipeline stage 1/3: Extracting PDF %s", file_path)
        extractor = PdfFallbackExtractor(str(file_path))
        raw_doc = extractor.extract()
        logger.info("  → %d paragraphs extracted", len(raw_doc.paragraphs))

        # Stage 2: Build chunk graph from paragraphs
        logger.info("Pipeline stage 2/3: Building chunk graph from paragraphs")
        graph = ChunkGraph()
        for para in raw_doc.paragraphs:
            node_id = str(uuid.uuid4())
            node = ChunkNode(
                chunk_id=node_id,
                kind="section",
                level=0,
                source_doc=document_id,
                content=para.text,
                metadata={
                    "source_doc": document_id,
                    "kind": "section",
                    "level": 0,
                },
            )
            graph.nodes[node_id] = node
            graph.root_node_ids.append(node_id)

        logger.info("  → %d nodes in graph", len(graph.nodes))

        # Stage 3: Index
        logger.info("Pipeline stage 3/3: Indexing in BM25 + Embedding indexes")
        bm25_index = ApiBm25Index()
        embedding_index = ApiEmbeddingIndex()
        retriever = HybridRetriever(bm25_index, embedding_index, graph)
        await retriever.ingest_graph(graph)
        logger.info("  → Indexing complete")

        self._indexed_docs[(user_id, document_id)] = {
            "graph": graph,
            "retriever": retriever,
            "interfaces": [],
            "enums": [],
            "error_codes": [],
            "doc_type": "pdf",
            "user_id": user_id,
        }

        return {
            "document_id": document_id,
            "chunk_count": len(graph.nodes),
            "status": "indexed",
        }

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    async def query(
        self,
        document_id: str,
        query_text: str,
        top_k: int = 10,
        rerank_k: int | None = None,
        user_id: str = "",
    ) -> ApiDocQueryResponse:
        """Run hybrid retrieval + generation for a given document.

        Args:
            document_id: The document to search against (must be indexed).
            query_text: Free-text or keyword query.
            top_k: Number of results to retrieve from the hybrid index.
            rerank_k: Number of candidates to rerank with cross-encoder.
                      ``None`` uses the retriever's default.
            user_id: The owner of the document (prevents cross-user access).

        Returns:
            An :class:`ApiDocQueryResponse` with sources, answer, and metadata.

        Raises:
            ValueError: If *document_id* has not been indexed.
        """
        if (user_id, document_id) not in self._indexed_docs:
            raise ValueError(f"Document {document_id} has not been indexed")

        info = self._indexed_docs[(user_id, document_id)]
        retriever: HybridRetriever = info["retriever"]

        start_time = time.time()

        # 1. Retrieve
        results = await retriever.retrieve(query_text, top_k=top_k, rerank_k=rerank_k)

        # 2. Build sources
        sources: list[ApiDocSource] = []
        seen_functions: set[str] = set()
        seen_types: set[str] = set()

        for node, score in results:
            meta = node.metadata
            kind = node.kind
            interface_name = meta.get("interface_name", "")
            function_name = (
                meta.get("function_name", "") or meta.get("name", "")
            )
            content = node.content or ""

            if function_name:
                seen_functions.add(function_name)
            type_name = meta.get("type_name", "")
            if type_name:
                seen_types.add(type_name)

            sources.append(
                ApiDocSource(
                    chunk_id=node.chunk_id,
                    content=content,
                    score=score,
                    kind=kind,
                    interface_name=interface_name,
                    function_name=function_name,
                )
            )

        # 3. Generate answer (with optional response verification)
        answer, unsupported_sentences = await self._generate_answer(query_text, sources)

        # 4. Compute confidence based on top-N retrieval scores
        confidence = 0.0
        if sources:
            top_scores = [s.score for s in sources[:3]]
            confidence = sum(top_scores) / len(top_scores)
            # Normalize to a 0-1 range (clamp)
            confidence = min(1.0, max(0.0, confidence))

        elapsed = int((time.time() - start_time) * 1000)

        return ApiDocQueryResponse(
            answer=answer,
            sources=sources,
            citations=[s.chunk_id for s in sources[:5]],
            relevant_functions=sorted(seen_functions),
            relevant_types=sorted(seen_types),
            confidence=confidence,
            cached=False,
            latency_ms=elapsed,
            unsupported_sentences=unsupported_sentences,
        )

    # ------------------------------------------------------------------
    # Answer generation (fallback when APIDocRAG is unavailable)
    # ------------------------------------------------------------------

    async def _generate_answer(
        self,
        query: str,
        sources: list[ApiDocSource],
    ) -> tuple[str, list[str]]:
        """Generate a natural-language answer using the local LLM.

        Falls back to a simple prompt-based generation when the DSPy
        ``APIDocRAG`` module is not available.

        Returns:
            Tuple of ``(answer_text, unsupported_sentences)``.
            ``unsupported_sentences`` is populated by response verification
            when some claims cannot be verified against source chunks.
        """
        try:
            from src.core.config import get_settings
            from src.domain.services.llm import get_llm
            from src.domain.services.verification import ResponseVerifier

            settings = get_settings()

            # Build context from top sources
            context_parts: list[str] = []
            for i, src in enumerate(sources[:10]):
                ctx = f"[Source {i + 1}]"
                if src.interface_name:
                    ctx += f" Interface: {src.interface_name}"
                if src.function_name:
                    ctx += f" Function: {src.function_name}"
                ctx += f"\n{src.content}"
                context_parts.append(ctx)

            context = "\n\n".join(context_parts)

            prompt = (
                "You are an API documentation assistant. Answer the question "
                "based solely on the provided context.\n\n"
                f"Context:\n{context}\n\n"
                f"Question: {query}\n\n"
                "Answer concisely using only the information from the context. "
                "If the context does not contain relevant information, say so."
            )

            llm = await get_llm()
            response = await llm.generate(
                prompt,
                max_tokens=600,
                temperature=0.1,
            )
            answer = response.strip()

            # ---- Response verification (4.2-4.5) ----
            if settings.verification_enabled:
                verifier = ResponseVerifier()
                source_texts = [s.content for s in sources[:10]]
                result = await verifier.verify(
                    answer,
                    source_texts,
                    similarity_threshold=settings.verification_similarity_threshold,
                    remove_unsupported=settings.verification_remove_unsupported,
                )
                # 4.3: Fallback when all sentences fail verification
                fallback = "I don't have enough information to answer this question."
                if not result.verified_text or result.verified_text == fallback:
                    return (fallback, [])
                # 4.4: Return verified text with unsupported sentences metadata
                return (result.verified_text, result.unsupported)

            return (answer, [])

        except ImportError as exc:
            logger.warning("LLM module not available: %s", exc)
            return (
                "The language model is not available. "
                "Please check that the model is properly configured.",
                [],
            )
        # Let all other exceptions propagate naturally (5.2) so the route
        # handler's ``except Exception`` can return a proper HTTP 500.

    # ------------------------------------------------------------------
    # Status / lifecycle helpers
    # ------------------------------------------------------------------

    def is_indexed(self, document_id: str, user_id: str = "") -> bool:
        """Return ``True`` if *document_id* has been indexed in memory."""
        return (user_id, document_id) in self._indexed_docs

    def get_indexed_docs(self, user_id: str = "") -> list[str]:
        """Return document IDs indexed by *user_id*."""
        return [
            doc_id for (uid, doc_id) in self._indexed_docs
            if uid == user_id
        ]

    def remove_document(self, document_id: str, user_id: str = "") -> None:
        """Remove a document from the in-memory index."""
        self._indexed_docs.pop((user_id, document_id), None)

    def get_document_info(self, document_id: str, user_id: str = "") -> dict | None:
        """Return the stored info dict for *document_id*, or ``None``."""
        return self._indexed_docs.get((user_id, document_id))


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_manager_instance: ApiDocPipelineManager | None = None


def get_manager() -> ApiDocPipelineManager:
    """Return the singleton :class:`ApiDocPipelineManager` (create on first call)."""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = ApiDocPipelineManager()
        logger.info("ApiDocPipelineManager singleton created")
    return _manager_instance
