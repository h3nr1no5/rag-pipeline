"""Integration tests for the LlamaIndex query endpoint.

Tests both the non-streaming and streaming LlamaIndex endpoints
with mocked dependencies to avoid model downloads.

The route code lives in ``src/api/routes/query/routes.py`` under
``/api/v1/query/llamaindex`` and ``/api/v1/query/llamaindex/stream``.
"""

import io
import json
import uuid
from typing import Optional

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, MagicMock, patch

from src.api.main import app

# Import the modules we need to patch at the module level (same pattern as
# test_langchain_verification.py).
from src.domain.services import retrieval_llamaindex as llamaindex_module
from src.domain.services import llm as llm_module
from src.domain.services import embedding as embedding_module


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="function")
async def auth_client(setup_test_db):
    """Authenticated HTTP client with a unique test user."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        test_email = f"li_{uuid.uuid4().hex[:8]}@example.com"
        await ac.post("/api/v1/auth/signup", json={
            "email": test_email,
            "password": "testpassword123",
        })
        login_resp = await ac.post("/api/v1/auth/login", json={
            "email": test_email,
            "password": "testpassword123",
        })
        token = login_resp.json()["access_token"]
        ac.headers["Authorization"] = f"Bearer {token}"
        yield ac


@pytest_asyncio.fixture(scope="function")
async def db_session(setup_test_db):
    """Provide a test DB session for direct inserts."""
    from src.infrastructure.database.session import async_session_maker

    async with async_session_maker() as session:
        yield session


# ── Helpers ───────────────────────────────────────────────────────────────────


async def upload_doc(client: AsyncClient, title: str, content: str) -> str:
    """Upload a plain-text document via the API and return its id."""
    files = {"file": (title, io.BytesIO(content.encode()), "text/plain")}
    data = {"strategy_id": "recursive"}
    resp = await client.post("/api/v1/documents", files=files, data=data)
    assert resp.status_code == 201, f"Upload failed: {resp.text}"
    return resp.json()["id"]


async def seed_chunks(
    db_session,
    doc_id: str,
    texts: list[str],
    embedding: Optional[list[float]] = None,
) -> list:
    """Insert Chunk rows for *doc_id* directly into the test DB.

    Parameters
    ----------
    embedding:
        If provided, all chunks get this embedding value.
        If ``None``, each chunk uses ``[0.1, 0.2, 0.3]`` (the fixture default).
    """
    from src.infrastructure.database.models import Chunk

    emb = embedding if embedding is not None else [0.1, 0.2, 0.3]
    chunks = []
    for i, text in enumerate(texts):
        chunk = Chunk(
            id=str(uuid.uuid4()),
            document_id=doc_id,
            content=text,
            chunk_index=i,
            chunk_metadata={"source": f"paragraph_{i}"},
            embedding=emb,
        )
        db_session.add(chunk)
        chunks.append(chunk)
    await db_session.commit()
    return chunks


async def seed_document(
    db_session, user_id: str, texts: list[str]
) -> tuple[str, list]:
    """Insert a completed document + chunks for a given user."""
    from src.infrastructure.database.models import Document

    doc_id = str(uuid.uuid4())
    doc = Document(
        id=doc_id,
        user_id=user_id,
        title="rag_doc.txt",
        doc_type="txt",
        file_path="/tmp/rag_doc.txt",
        file_size=sum(len(t) for t in texts),
        chunking_strategy_id="recursive",
        status="completed",
        chunk_count=len(texts),
    )
    db_session.add(doc)
    chunks = await seed_chunks(db_session, doc_id, texts)
    return doc_id, chunks


async def get_user_id() -> str:
    """Look up the single test user that was created via signup.

    Raises:
        RuntimeError: if no user exists in the test database.
    """
    from src.infrastructure.database.session import async_session_maker
    from src.infrastructure.database.models import User
    from sqlalchemy import select

    async with async_session_maker() as session:
        result = await session.execute(select(User))
        user = result.scalar_one_or_none()
        if user is None:
            raise RuntimeError("No test user found — did auth_client sign up?")
        return user.id


# ── Mock helpers ──────────────────────────────────────────────────────────────


def make_mock_sources() -> list:
    """Build source objects with the attributes the LlamaIndex endpoint expects.

    The endpoint accesses ``.chunk_id``, ``.content``, ``.score``, and
    ``.metadata`` on each item (the ``LlamaIndexRetrievedChunk`` interface).
    """
    s1 = MagicMock()
    s1.chunk_id = "li-mock-chunk-1"
    s1.content = "RAG combines retrieval with text generation."
    s1.score = 0.97
    s1.metadata = {"source": "paragraph_0"}
    s2 = MagicMock()
    s2.chunk_id = "li-mock-chunk-2"
    s2.content = "Vector databases store embeddings for semantic search."
    s2.score = 0.85
    s2.metadata = {"source": "paragraph_1"}
    return [s1, s2]


def make_mock_retriever(
    answer: str = "LlamaIndex is a framework for building RAG applications.",
    sources: Optional[list] = None,
) -> MagicMock:
    """Build a MagicMock that mimics ``LlamaIndexRetriever``.

    The non-streaming endpoint calls ``retriever.generate()``.
    The streaming endpoint calls ``retriever.retrieve()``.
    """
    if sources is None:
        sources = []

    retriever = MagicMock()
    retriever.generate = AsyncMock(return_value=(answer, sources))
    retriever.retrieve = AsyncMock(return_value=sources)
    return retriever


async def make_mock_llm():
    """Build a mock LLM that returns controlled tokens."""
    llm = MagicMock()
    llm.generate = AsyncMock(return_value="LlamaIndex mock answer.")
    llm.generate_stream = AsyncMock()
    # generate_stream must be an async generator
    return llm


async def mock_llm_generate_stream(
    prompt: str, max_tokens: int = 600, temperature: float = 0.5
):
    """Async generator that yields controlled tokens for streaming tests."""
    for token in ["LlamaIndex", " test", " answer", "."]:
        yield token


async def mock_llm_generate_stream_short_answer(
    prompt: str, max_tokens: int = 600, temperature: float = 0.5
):
    """Async generator that yields a very short (fallback-triggering) answer."""
    yield "No."


# ── Validation tests (no mocking needed) ──────────────────────────────────────


class TestLlamaIndexValidation:
    """Tests that exercise request validation / document-not-found paths."""

    @pytest.mark.asyncio
    async def test_empty_document_ids(self, auth_client):
        """400 when document_ids is an empty list."""
        resp = await auth_client.post("/api/v1/query/llamaindex", json={
            "question": "What is LlamaIndex?",
            "document_ids": [],
        })
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_missing_document_ids(self, auth_client):
        """400 when document_ids field is omitted (defaults to empty list)."""
        resp = await auth_client.post("/api/v1/query/llamaindex", json={
            "question": "What is LlamaIndex?",
        })
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_no_matching_documents(self, auth_client):
        """404 when document_ids don't match any document."""
        resp = await auth_client.post("/api/v1/query/llamaindex", json={
            "question": "What is LlamaIndex?",
            "document_ids": ["nonexistent-doc-id"],
        })
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_without_auth(self):
        """401 when no auth token is provided."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post("/api/v1/query/llamaindex", json={
                "question": "What is LlamaIndex?",
                "document_ids": ["some-id"],
            })
            assert resp.status_code in (401, 403)


# ── Non-streaming endpoint (mocked retriever) ─────────────────────────────────


class TestLlamaIndexEndpoint:
    """Tests for POST /api/v1/query/llamaindex (non-streaming)."""

    @pytest.mark.asyncio
    async def test_successful_query(self, auth_client, db_session):
        """The endpoint returns 200 with 'answer' and 'sources' fields.

        Verifies:
        - ``answer`` is a non-empty string
        - ``sources`` is a list with at least one source
        - Each source has ``content``, ``score >= 0``, and ``chunk_id``
        """
        # Arrange ──────────────────────────────────────────────────────────
        user_id = await get_user_id()
        doc_id, chunks = await seed_document(db_session, user_id, [
            "RAG combines retrieval with generation.",
            "Vector databases enable semantic search.",
        ])

        mock_sources = make_mock_sources()
        mock_retriever = make_mock_retriever(
            answer="LlamaIndex provides a comprehensive RAG framework.",
            sources=mock_sources,
        )

        with patch.object(
            llamaindex_module, "get_llamaindex_retriever",
            return_value=mock_retriever,
        ):
            # Act ──────────────────────────────────────────────────────────
            resp = await auth_client.post("/api/v1/query/llamaindex", json={
                "question": "What is LlamaIndex?",
                "document_ids": [doc_id],
            })

        # Assert ───────────────────────────────────────────────────────────
        assert resp.status_code == 200, f"Body: {resp.text}"
        data = resp.json()

        # Answer is a non-empty string
        assert "answer" in data
        assert isinstance(data["answer"], str)
        assert len(data["answer"]) > 0
        assert data["answer"] == "LlamaIndex provides a comprehensive RAG framework."

        # Sources is a list with at least one source
        assert "sources" in data
        assert isinstance(data["sources"], list)
        assert len(data["sources"]) > 0

        # Each source has expected fields
        for i, src in enumerate(data["sources"]):
            assert "chunk_id" in src, f"Source {i} missing chunk_id"
            assert "content" in src, f"Source {i} missing content"
            assert "score" in src, f"Source {i} missing score"
            assert isinstance(src["content"], str) and len(src["content"]) > 0, \
                f"Source {i} content is empty"
            assert isinstance(src["score"], (int, float)) and src["score"] >= 0, \
                f"Source {i} score is invalid: {src['score']}"

        # Standard response fields
        assert "latency_ms" in data
        assert isinstance(data["latency_ms"], int)
        assert data["latency_ms"] >= 0

        assert "cached" in data
        assert data["cached"] is False

    @pytest.mark.asyncio
    async def test_empty_retrieval_message(self, auth_client, db_session):
        """When the retriever returns no sources, the endpoint returns the
        'I don't have enough information' message with an empty sources list.
        """
        # Arrange ──────────────────────────────────────────────────────────
        user_id = await get_user_id()
        doc_id, chunks = await seed_document(db_session, user_id, [
            "Test content that won't match the query.",
        ])

        mock_retriever = make_mock_retriever(
            answer="I don't have enough information to answer this question.",
            sources=[],
        )

        with patch.object(
            llamaindex_module, "get_llamaindex_retriever",
            return_value=mock_retriever,
        ):
            # Act ──────────────────────────────────────────────────────────
            resp = await auth_client.post("/api/v1/query/llamaindex", json={
                "question": "Something completely unrelated?",
                "document_ids": [doc_id],
            })

        # Assert ───────────────────────────────────────────────────────────
        assert resp.status_code == 200, f"Body: {resp.text}"
        data = resp.json()
        assert "answer" in data
        assert "I don't have enough information" in data["answer"]
        assert data["sources"] == []

    @pytest.mark.asyncio
    async def test_short_answer_overridden(self, auth_client, db_session):
        """Very short answers (less than 5 chars) are replaced with a fallback."""
        # Arrange ──────────────────────────────────────────────────────────
        user_id = await get_user_id()
        doc_id, chunks = await seed_document(db_session, user_id, [
            "Test content.",
        ])

        mock_sources = make_mock_sources()
        mock_retriever = make_mock_retriever(
            answer="No.",  # < 5 chars → triggers fallback
            sources=mock_sources,
        )

        with patch.object(
            llamaindex_module, "get_llamaindex_retriever",
            return_value=mock_retriever,
        ):
            # Act ──────────────────────────────────────────────────────────
            resp = await auth_client.post("/api/v1/query/llamaindex", json={
                "question": "What is LlamaIndex?",
                "document_ids": [doc_id],
            })

        # Assert ───────────────────────────────────────────────────────────
        assert resp.status_code == 200
        data = resp.json()
        # The fallback message should mention "apologize"
        assert "apologize" in data["answer"].lower()


# ── Streaming endpoint (mocked retriever + LLM) ─────────────────────────────


class TestLlamaIndexStreaming:
    """Tests for POST /api/v1/query/llamaindex/stream."""

    @pytest.mark.asyncio
    async def test_streaming_success(self, auth_client, db_session):
        """Streaming endpoint yields sources then tokens via SSE.

        Verifies:
        - First data event contains ``sources``
        - Subsequent events contain ``token``
        - Stream ends with ``[DONE]``
        """
        # Arrange ──────────────────────────────────────────────────────────
        user_id = await get_user_id()
        doc_id, chunks = await seed_document(db_session, user_id, [
            "RAG combines retrieval with generation.",
        ])

        mock_sources = make_mock_sources()

        # Mock the LlamaIndexRetriever class used in the streaming endpoint
        with patch.object(
            llamaindex_module, "LlamaIndexRetriever"
        ) as mock_retriever_class:
            mock_retriever_instance = MagicMock()
            mock_retriever_instance.retrieve = AsyncMock(
                return_value=mock_sources
            )
            mock_retriever_class.return_value = mock_retriever_instance

            # Mock the LLM's generate_stream
            mock_llm = MagicMock()
            mock_llm.generate_stream = mock_llm_generate_stream

            with patch.object(
                llm_module, "get_llm", return_value=mock_llm,
            ):
                # Act ──────────────────────────────────────────────────────
                async with auth_client.stream(
                    "POST", "/api/v1/query/llamaindex/stream",
                    json={
                        "question": "What is LlamaIndex?",
                        "document_ids": [doc_id],
                    },
                ) as resp:
                    assert resp.status_code == 200
                    events = []
                    async for line in resp.aiter_lines():
                        if line.startswith("data: "):
                            events.append(line)

        # Assert ───────────────────────────────────────────────────────────
        # At least: sources event + 4 token events + [DONE] = 6
        assert len(events) >= 3, f"Expected ≥3 events, got {len(events)}"

        # First event should be sources
        first = json.loads(events[0].removeprefix("data: "))
        assert "sources" in first, f"First event missing 'sources': {first}"
        assert len(first["sources"]) > 0

        # Subsequent events should contain tokens
        token_events = [
            json.loads(e.removeprefix("data: "))
            for e in events[1:-1]  # exclude sources and [DONE]
        ]
        for te in token_events:
            assert "token" in te, f"Expected token event, got: {te}"

        # Last event should be [DONE]
        assert events[-1] == "data: [DONE]", (
            f"Expected [DONE], got: {events[-1]}"
        )

    @pytest.mark.asyncio
    async def test_streaming_empty_retrieval(self, auth_client, db_session):
        """When no sources are retrieved, the stream yields the
        'I don't have enough information' message."""
        # Arrange ──────────────────────────────────────────────────────────
        user_id = await get_user_id()
        doc_id, chunks = await seed_document(db_session, user_id, [
            "Test content.",
        ])

        with patch.object(
            llamaindex_module, "LlamaIndexRetriever"
        ) as mock_retriever_class:
            mock_retriever_instance = MagicMock()
            mock_retriever_instance.retrieve = AsyncMock(return_value=[])
            mock_retriever_class.return_value = mock_retriever_instance

            # Act ──────────────────────────────────────────────────────────
            async with auth_client.stream(
                "POST", "/api/v1/query/llamaindex/stream",
                json={
                    "question": "Something unrelated?",
                    "document_ids": [doc_id],
                },
            ) as resp:
                assert resp.status_code == 200
                events = []
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        events.append(line)

        # Assert ───────────────────────────────────────────────────────────
        assert len(events) >= 2
        first = json.loads(events[0].removeprefix("data: "))
        assert "sources" in first
        assert first["sources"] == []
        assert first.get("cached") is False

        # Last event should be [DONE]
        assert events[-1] == "data: [DONE]"

        # Token events should contain the friendly message
        token_texts = []
        for e in events[1:-1]:
            te = json.loads(e.removeprefix("data: "))
            if "token" in te:
                token_texts.append(te["token"])
        full_text = "".join(token_texts)
        assert "don't have enough information" in full_text

    @pytest.mark.asyncio
    async def test_streaming_no_documents(self, auth_client):
        """Streaming endpoint yields an error SSE event for non-existent docs."""
        # Act ──────────────────────────────────────────────────────────────
        async with auth_client.stream(
            "POST", "/api/v1/query/llamaindex/stream",
            json={
                "question": "Test?",
                "document_ids": ["nonexistent-doc"],
            },
        ) as resp:
            assert resp.status_code == 200
            events = []
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    events.append(line)

        # Assert ───────────────────────────────────────────────────────────
        assert len(events) > 0
        first = json.loads(events[0].removeprefix("data: "))
        assert "error" in first, f"Expected error event, got: {first}"
        assert "No documents found" in first["error"]


# ── Edge-case tests ─────────────────────────────────────────────────────────


class TestLlamaIndexEdgeCases:
    """Tests for edge-case scenarios (NULL embeddings, fallbacks, etc.)."""

    @pytest.mark.asyncio
    async def test_null_embeddings_handled(self, auth_client, db_session):
        """When all chunks have NULL embeddings, the endpoint handles it
        gracefully without crashing.

        We seed chunks with ``embedding=None`` and mock the retriever to
        simulate the empty-retrieval path (what should happen when no chunks
        have valid embeddings). The endpoint should return the graceful
        'I don't have enough information' message.
        """
        # Arrange ──────────────────────────────────────────────────────────
        user_id = await get_user_id()

        # Seed a document with chunks that have embedding=None
        from src.infrastructure.database.models import Document, Chunk

        doc_id = str(uuid.uuid4())
        doc = Document(
            id=doc_id,
            user_id=user_id,
            title="null_embeddings_doc.txt",
            doc_type="txt",
            file_path="/tmp/null_embeddings_doc.txt",
            file_size=50,
            chunking_strategy_id="recursive",
            status="completed",
            chunk_count=2,
        )
        db_session.add(doc)

        for i, text in enumerate([
            "First chunk with no embedding.",
            "Second chunk with no embedding.",
        ]):
            chunk = Chunk(
                id=str(uuid.uuid4()),
                document_id=doc_id,
                content=text,
                chunk_index=i,
                chunk_metadata={"source": f"null_paragraph_{i}"},
                embedding=None,  # NULL embedding
            )
            db_session.add(chunk)
        await db_session.commit()

        # Mock the retriever to simulate graceful handling of NULL embeddings
        # (the real retriever would raise ValueError, but the endpoint should
        # handle this gracefully at the integration level).
        mock_retriever = make_mock_retriever(
            answer="I don't have enough information to answer this question.",
            sources=[],
        )

        with patch.object(
            llamaindex_module, "get_llamaindex_retriever",
            return_value=mock_retriever,
        ):
            # Act ──────────────────────────────────────────────────────────
            resp = await auth_client.post("/api/v1/query/llamaindex", json={
                "question": "What does this document say?",
                "document_ids": [doc_id],
            })

        # Assert ───────────────────────────────────────────────────────────
        # Verify no crash and graceful response
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}: {resp.text}"
        )
        data = resp.json()
        assert "answer" in data
        assert "I don't have enough information" in data["answer"]
        assert data["sources"] == []

    @pytest.mark.asyncio
    async def test_null_embeddings_streaming(self, auth_client, db_session):
        """Streaming endpoint handles NULL embeddings gracefully.

        Seeds chunks with ``embedding=None`` and mocks the retriever to
        return empty results, verifying the stream yields a friendly message.
        """
        # Arrange ──────────────────────────────────────────────────────────
        user_id = await get_user_id()

        from src.infrastructure.database.models import Document, Chunk

        doc_id = str(uuid.uuid4())
        doc = Document(
            id=doc_id,
            user_id=user_id,
            title="null_embeddings_stream.txt",
            doc_type="txt",
            file_path="/tmp/null_embeddings_stream.txt",
            file_size=50,
            chunking_strategy_id="recursive",
            status="completed",
            chunk_count=2,
        )
        db_session.add(doc)

        for i, text in enumerate([
            "Chunk A with NULL embedding.",
            "Chunk B with NULL embedding.",
        ]):
            chunk = Chunk(
                id=str(uuid.uuid4()),
                document_id=doc_id,
                content=text,
                chunk_index=i,
                chunk_metadata={"source": f"null_para_{i}"},
                embedding=None,
            )
            db_session.add(chunk)
        await db_session.commit()

        with patch.object(
            llamaindex_module, "LlamaIndexRetriever"
        ) as mock_retriever_class:
            mock_retriever_instance = MagicMock()
            mock_retriever_instance.retrieve = AsyncMock(return_value=[])
            mock_retriever_class.return_value = mock_retriever_instance

            # Act ──────────────────────────────────────────────────────────
            async with auth_client.stream(
                "POST", "/api/v1/query/llamaindex/stream",
                json={
                    "question": "What does this say?",
                    "document_ids": [doc_id],
                },
            ) as resp:
                assert resp.status_code == 200
                events = []
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        events.append(line)

        # Assert ───────────────────────────────────────────────────────────
        assert len(events) >= 2, f"Expected ≥2 events, got {len(events)}"

        first = json.loads(events[0].removeprefix("data: "))
        assert "sources" in first
        assert first["sources"] == []

        # Last event should be [DONE]
        assert events[-1] == "data: [DONE]"

        # Verify friendly message in tokens
        token_texts = []
        for e in events[1:-1]:
            te = json.loads(e.removeprefix("data: "))
            if "token" in te:
                token_texts.append(te["token"])
        full_text = "".join(token_texts)
        assert "don't have enough information" in full_text.lower()
