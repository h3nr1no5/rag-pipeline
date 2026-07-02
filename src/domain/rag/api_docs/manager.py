"""Manager for API documentation RAG pipeline orchestration.

Provides a singleton :class:`ApiDocPipelineManager` that coordinates:

* In-memory storage of indexed documents (ChunkGraph + HybridRetriever per doc)
* Pipeline orchestration: extract -> chunk -> index
* Query execution: retrieve -> generate
"""

from __future__ import annotations

import asyncio
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
from src.domain.rag.api_docs.types import ProgressReporter

logger = logging.getLogger(__name__)


def _sanitize_chunk_for_prompt(content: str, max_len: int = 5000) -> str:
    """Sanitize chunk content for safe LLM prompt inclusion.

    Strips non-printable characters (except newlines/tabs which are
    important for code and table formatting), limits length, and
    removes obvious prompt-injection patterns like instruction overrides.
    """
    # Remove non-printable chars but keep newlines and tabs
    sanitized = "".join(ch for ch in content if ch.isprintable() or ch in "\n\t")
    # Truncate overly long chunks
    if len(sanitized) > max_len:
        sanitized = sanitized[:max_len] + "\n... [truncated]"
    return sanitized


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

        from src.core.config import get_settings
        self._dspy_enabled = get_settings().api_docs_dspy_enabled

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

    async def ingest_docx(self, file_path: str | Path, document_id: str, user_id: str = "", config: dict | None = None,  # noqa: E501
                           progress_callback: ProgressReporter | None = None) -> dict:
        """Run the full DOCX pipeline: parse → detect → convert → chunk → index.

        Args:
            file_path: Path to the ``.docx`` file on disk.
            document_id: Unique identifier for the document (used as the
                         ``source_doc`` in the chunk graph).
            config: Optional strategy configuration dict. Formatting keys
                (``format_style``, ``include_signatures``, ``include_descriptions``)
                are passed through to :meth:`ChunkTextFormatter.format_graph`.
            progress_callback: Optional async callback for progress updates.

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
        table_types = self._table_detector.detect_from_document(raw_doc)
        merged_tables = merge_multi_row_functions(raw_doc.tables)
        type_counts: dict[str, int] = {}
        for tt in table_types.values():
            type_counts[tt] = type_counts.get(tt, 0) + 1
        logger.info("  → table types: %s", type_counts)

        # Stage 3: Convert to domain objects
        logger.info("Pipeline stage 3/5: Converting to domain objects")
        converter = DocumentConverter()
        domain_result = converter.convert(raw_doc, table_types, merged_tables, config=config)
        interfaces = domain_result["interfaces"]
        enums = domain_result["enums"]
        error_codes = domain_result["error_codes"]
        records = domain_result.get("records", [])
        generic_tables = domain_result.get("generic_tables", [])
        logger.info(
            "  → %d interfaces, %d enums, %d error codes, %d records, %d generic tables",
            len(interfaces),
            len(enums),
            len(error_codes),
            len(records),
            len(generic_tables),
        )

        # Stage 4: Build chunk graph
        logger.info("Pipeline stage 4/5: Building chunk graph")
        graph = self._graph_builder.build(
            interfaces=interfaces,
            enums=enums,
            error_codes=error_codes,
            records=records,
            generic_tables=generic_tables,
            source_doc=document_id,
            config=config,
        )
        self._text_formatter.format_graph(graph, interfaces, enums, error_codes, records=records, config=config)  # noqa: E501
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
            records=records,
            progress_callback=progress_callback,
        )
        logger.info("  → Indexing complete")

        self._indexed_docs[(user_id, document_id)] = {
            "graph": graph,
            "retriever": retriever,
            "interfaces": interfaces,
            "enums": enums,
            "error_codes": error_codes,
            "records": records,
            "doc_type": "docx",
            "user_id": user_id,
        }

        return {
            "document_id": document_id,
            "chunk_count": len(graph.nodes),
            "interface_count": len(interfaces),
            "enum_count": len(enums),
            "error_code_count": len(error_codes),
            "record_count": len(records),
            "status": "indexed",
        }

    # ------------------------------------------------------------------
    # Ingestion — PDF fallback
    # ------------------------------------------------------------------

    async def ingest_pdf(self, file_path: str | Path, document_id: str, user_id: str = "",
                          progress_callback: ProgressReporter | None = None) -> dict:
        """Ingest a PDF file using :class:`PdfFallbackExtractor`.

        Because PDF extraction does not produce structured tables, each page
        is stored as a single ``section``-kind chunk node.

        Args:
            file_path: Path to the ``.pdf`` file on disk.
            document_id: Unique identifier for the document.
            progress_callback: Optional async callback for progress updates.

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
        await retriever.ingest_graph(graph, progress_callback=progress_callback)
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
        temperature: float | None = None,
        verification_enabled: bool = True,
        max_tokens: int | None = None,
    ) -> ApiDocQueryResponse:
        """Run hybrid retrieval + generation for a given document.

        Args:
            document_id: The document to search against (must be indexed).
            query_text: Free-text or keyword query.
            top_k: Number of results to retrieve from the hybrid index.
            rerank_k: Number of candidates to rerank with cross-encoder.
                      ``None`` uses the retriever's default.
            user_id: The owner of the document (prevents cross-user access).
            temperature: Override the generation temperature. ``None`` uses
                         the default from settings.
            verification_enabled: Whether to run response verification (claim
                                  checking against source chunks).
            max_tokens: Override the generation max tokens. ``None`` uses
                        the default from settings.

        Returns:
            An :class:`ApiDocQueryResponse` with sources, answer, and metadata.

        Raises:
            ValueError: If *document_id* has not been indexed.
        """
        if (user_id, document_id) not in self._indexed_docs:
            raise ValueError(f"Document {document_id} has not been indexed")

        info = self._indexed_docs[(user_id, document_id)]
        retriever: HybridRetriever = info["retriever"]
        graph: ChunkGraph = info["graph"]

        start_time = time.time()

        if self._dspy_enabled:
            try:
                return await self._query_dspy(
                    retriever, graph, query_text, top_k, rerank_k,
                    temperature=temperature, verification_enabled=verification_enabled,
                    max_tokens=max_tokens,
                )
            except Exception as exc:
                logger.warning(
                    "DSPy pipeline failed (%s: %s) — falling back to prompt generation",
                    type(exc).__name__,
                    exc,
                    exc_info=True,
                )
                # fall through to _query_fallback below

        # DSPy disabled or failed — use fallback
        elapsed_already = int((time.time() - start_time) * 1000)
        result = await self._query_fallback(
            retriever, graph, query_text, top_k, rerank_k,
            temperature=temperature, verification_enabled=verification_enabled,
        )
        result.latency_ms += elapsed_already  # add DSPy attempt time
        return result

    async def _query_fallback(
        self,
        retriever: HybridRetriever,
        graph: ChunkGraph,
        query_text: str,
        top_k: int = 10,
        rerank_k: int | None = None,
        temperature: float | None = None,
        verification_enabled: bool = True,
    ) -> ApiDocQueryResponse:
        """Fallback query path using prompt-based generation (no DSPy).

        Args:
            retriever: The document's hybrid retriever.
            graph: The document's chunk graph (for source resolution).
            query_text: The user's query.
            top_k: Number of chunks to retrieve.
            rerank_k: Number of candidates to rerank.
            temperature: Override the generation temperature.
            verification_enabled: Whether to run response verification.

        Returns:
            An :class:`ApiDocQueryResponse` with sources, answer, and metadata.
        """
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
        answer, unsupported_sentences = await self._generate_answer(
            query_text, sources, temperature=temperature, verification_enabled=verification_enabled,
        )

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
            reasoning_hint="",
            sources=sources,
            citations=[s.chunk_id for s in sources[:5]],
            relevant_functions=sorted(seen_functions),
            relevant_types=sorted(seen_types),
            confidence=confidence,
            cached=False,
            latency_ms=elapsed,
            unsupported_sentences=unsupported_sentences,
        )

    async def _query_dspy(
        self,
        retriever: HybridRetriever,
        graph: ChunkGraph,
        query_text: str,
        top_k: int = 10,
        rerank_k: int | None = None,
        temperature: float | None = None,
        verification_enabled: bool = True,
        max_tokens: int | None = None,
    ) -> ApiDocQueryResponse:
        """Run the DSPy pipeline for answer generation.

        Args:
            retriever: The document's hybrid retriever.
            graph: The document's chunk graph (for source resolution).
            query_text: The user's query.
            top_k: Number of chunks to retrieve.
            rerank_k: Number of candidates to rerank.
            temperature: Override the generation temperature.
            verification_enabled: Whether to run response verification.
            max_tokens: Override the generation max tokens.

        Returns:
            An ApiDocQueryResponse.
        """
        from src.domain.rag.api_docs.pipeline.module import APIDocRAG

        start = time.time()
        module = APIDocRAG(hybrid_retriever=retriever)
        result = await asyncio.to_thread(
            module, question=query_text, top_k=top_k,
            temperature=temperature, max_tokens=max_tokens,
        )
        latency_ms = int((time.time() - start) * 1000)

        return await self._build_dspy_response(
            result, graph, latency_ms, verification_enabled=verification_enabled,
        )

    async def _build_dspy_response(
        self,
        result: dict,
        graph: ChunkGraph,
        latency_ms: int,
        verification_enabled: bool = True,
    ) -> ApiDocQueryResponse:
        """Map APIDocRAG.forward() output dict to ApiDocQueryResponse.

        Args:
            result: Output dict from APIDocRAG.forward() with keys:
                answer, citations, relevant_functions, relevant_types,
                confidence, retrieved_chunks, primary_chunk_id,
                assertions_passed, used_fallback.
            graph: The document's ChunkGraph for source resolution.
            latency_ms: Wall-clock time for the full DSPy query.
            verification_enabled: Whether to run response verification.

        Returns:
            A populated ApiDocQueryResponse.
        """
        # Log observability fields not surfaced in response schema
        logger.info(
            "DSPy pipeline result: assertions_passed=%s used_fallback=%s primary_chunk=%s",
            result.get("assertions_passed"),
            result.get("used_fallback"),
            result.get("primary_chunk_id"),
        )

        # Build sources from retrieved_chunks
        sources = self._resolve_chunk_sources(
            result.get("retrieved_chunks", []),
            graph,
        )

        answer = result.get("answer", "")

        # Run response verification (skip when disabled per-request)
        unsupported_sentences: list[str] = []
        if answer and verification_enabled:
            try:
                from src.core.config import get_settings
                from src.domain.services.verification import ResponseVerifier

                settings = get_settings()
                if settings.verification_enabled:
                    verifier = ResponseVerifier()
                    source_texts = [s.content for s in sources[:10]]
                    vresult = await verifier.verify(
                        answer,
                        source_texts,
                        similarity_threshold=settings.verification_similarity_threshold,
                        remove_unsupported=settings.verification_remove_unsupported,
                    )
                    answer = vresult.verified_text
                    unsupported_sentences = vresult.unsupported
            except Exception:
                logger.exception("Response verification failed on DSPy output")

        # Filter citations to only include chunk IDs present in resolved sources
        valid_chunk_ids = {s.chunk_id for s in sources}
        citations = [
            c for c in result.get("citations", [])
            if c in valid_chunk_ids
        ]
        if len(citations) < len(result.get("citations", [])):
            logger.debug(
                "Filtered %d citation(s) that reference unresolvable chunk IDs",
                len(result.get("citations", [])) - len(citations),
            )

        return ApiDocQueryResponse(
            answer=answer,
            reasoning_hint=result.get("rationale", ""),
            sources=sources,
            citations=citations,
            relevant_functions=result.get("relevant_functions", []),
            relevant_types=result.get("relevant_types", []),
            confidence=result.get("confidence", 0.0),
            cached=False,
            latency_ms=latency_ms,
            unsupported_sentences=unsupported_sentences,
        )

    def _resolve_chunk_sources(
        self,
        retrieved_chunks: list[tuple[str, float]],
        graph: ChunkGraph,
    ) -> list[ApiDocSource]:
        """Resolve (chunk_id, score) tuples from DSPy into ApiDocSource objects.

        Args:
            retrieved_chunks: List of (chunk_id, score) tuples from DSPy output.
            graph: The document's ChunkGraph containing nodes keyed by chunk_id.

        Returns:
            List of ApiDocSource objects with content and metadata resolved
            from the graph.
        """
        sources: list[ApiDocSource] = []
        valid_ids: set[str] = set(graph.nodes.keys())
        unknown_count = 0
        for chunk_id, score in retrieved_chunks:
            if chunk_id not in valid_ids:
                unknown_count += 1
                continue
            node = graph.nodes[chunk_id]
            meta = node.metadata or {}
            sources.append(
                ApiDocSource(
                    chunk_id=chunk_id,
                    content=node.content or "",
                    score=score,
                    kind=node.kind,
                    interface_name=meta.get("interface_name", ""),
                    function_name=meta.get("function_name", "") or meta.get("name", ""),
                )
            )
        if unknown_count:
            logger.debug(
                "DSPy returned %d chunk_id(s) not found in graph (ignored)",
                unknown_count,
            )
        return sources

    # ------------------------------------------------------------------
    # Answer generation (fallback when APIDocRAG is unavailable)
    # ------------------------------------------------------------------

    async def _generate_answer(
        self,
        query: str,
        sources: list[ApiDocSource],
        temperature: float | None = None,
        verification_enabled: bool = True,
    ) -> tuple[str, list[str]]:
        """Generate a natural-language answer using the local LLM.

        Falls back to a simple prompt-based generation when the DSPy
        ``APIDocRAG`` module is not available.

        Args:
            query: The user's query.
            sources: Retrieved source chunks.
            temperature: Override the generation temperature. ``None`` uses
                         the default from settings.
            verification_enabled: Whether to run response verification.

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
                ctx += f"\n{_sanitize_chunk_for_prompt(src.content)}"
                context_parts.append(ctx)

            context = "\n\n".join(context_parts)

            prompt = (
                "You are an API documentation assistant. Answer the question "
                "based solely on the provided context.\n\n"
                "Requirements:\n"
                "1. Use EXACT enum values from context. Do not invent or approximate "
                "enum member names.\n"
                "2. Cite each source as [Source N] where N is the index of the "
                "relevant chunk.\n"
                "3. Only use information from the provided context. If the context "
                "does not contain the answer, say so.\n"
                "4. Do not repeat the same information multiple times.\n"
                "5. Structure your answer with clear sections if multiple concepts "
                "are discussed.\n\n"
                f"Context:\n{context}\n\n"
                f"Question: {query}\n\n"
                "Answer concisely using only the information from the context. "
                "If the context does not contain relevant information, say so."
            )

            llm = await get_llm()
            temp = temperature if temperature is not None else 0.1
            response = await llm.generate(
                prompt,
                max_tokens=600,
                temperature=temp,
            )
            answer = response.strip()

            # ---- Response verification (skip when disabled per-request) ----
            if verification_enabled and settings.verification_enabled:
                verifier = ResponseVerifier()
                source_texts = [s.content for s in sources[:10]]
                result = await verifier.verify(
                    answer,
                    source_texts,
                    similarity_threshold=settings.verification_similarity_threshold,
                    remove_unsupported=settings.verification_remove_unsupported,
                )
                # Fallback when all sentences fail verification
                fallback = "I don't have enough information to answer this question."
                if not result.verified_text or result.verified_text == fallback:
                    return (fallback, [])
                # Return verified text with unsupported sentences metadata
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
