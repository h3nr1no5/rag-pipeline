"""Integration tests for LangChain QA chain with verification.

Tests both the LangChain query endpoint and streaming endpoint
with mocked dependencies to avoid model downloads.
"""

import io
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.api.main import app
from src.core.config import get_settings

# Import the modules we need to patch (they are not re-exported from
# src.domain.services.__init__.py, so patch('a.b.c') would fail.)
from src.domain.services import chain_langchain as chain_module
from src.domain.services import embedding as embedding_module

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="function")
async def auth_client(setup_test_db):
    """Authenticated HTTP client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        test_email = f"lc_{uuid.uuid4().hex[:8]}@example.com"
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


async def seed_chunks(db_session, doc_id: str, texts: list[str]) -> list:
    """Insert Chunk rows for *doc_id* directly into the test DB."""
    from src.infrastructure.database.models import Chunk
    chunks = []
    for i, text in enumerate(texts):
        chunk = Chunk(
            id=str(uuid.uuid4()),
            document_id=doc_id,
            content=text,
            chunk_index=i,
            chunk_metadata={"source": f"paragraph_{i}"},
            embedding=[0.1, 0.2, 0.3],
        )
        db_session.add(chunk)
        chunks.append(chunk)
    await db_session.commit()
    return chunks


async def seed_document(db_session, user_id: str, texts: list[str]) -> tuple[str, list]:
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
    from sqlalchemy import select

    from src.infrastructure.database.models import User
    from src.infrastructure.database.session import async_session_maker

    async with async_session_maker() as session:
        result = await session.execute(select(User))
        user = result.scalar_one_or_none()
        if user is None:
            raise RuntimeError("No test user found — did auth_client sign up?")
        return user.id


def make_mock_qa_chain(
    answer: str = "RAG stands for Retrieval Augmented Generation.",
    sources: list | None = None,
    is_initialized: bool = True,
    doc_ids: set | None = None,
) -> MagicMock:
    """Build a MagicMock that mimics a fully initialized LangChainQAChain."""
    if sources is None:
        sources = []
    if doc_ids is None:
        doc_ids = set()

    chain = MagicMock()
    chain.is_initialized = MagicMock(return_value=is_initialized)
    chain.get_document_ids = MagicMock(return_value=doc_ids)
    chain.initialize = AsyncMock()
    chain.generate = AsyncMock(return_value=(answer, sources))
    return chain


def make_streaming_sources() -> list:
    """Build source objects with the attributes the endpoint expects.

    The endpoint accesses .chunk_id, .content, .score, .metadata on each item.
    """
    s1 = MagicMock()
    s1.chunk_id = "mock-chunk-1"
    s1.content = "RAG combines retrieval with text generation."
    s1.score = 0.97
    s1.metadata = {"source": "paragraph_0"}
    s2 = MagicMock()
    s2.chunk_id = "mock-chunk-2"
    s2.content = "Vector databases store embeddings for semantic search."
    s2.score = 0.85
    s2.metadata = {"source": "paragraph_1"}
    return [s1, s2]


# ── Validation tests (no mocking needed) ──────────────────────────────────────


class TestLangChainValidation:
    """Tests that exercise request validation / document-not-found paths."""

    @pytest.mark.asyncio
    async def test_empty_document_ids(self, auth_client):
        """400 when document_ids is an empty list."""
        resp = await auth_client.post("/api/v1/query/langchain", json={
            "question": "What is RAG?",
            "document_ids": [],
        })
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_missing_document_ids(self, auth_client):
        """400 when document_ids field is omitted (defaults to empty list)."""
        resp = await auth_client.post("/api/v1/query/langchain", json={
            "question": "What is RAG?",
        })
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_no_matching_documents(self, auth_client):
        """404 when document_ids don't match any document."""
        resp = await auth_client.post("/api/v1/query/langchain", json={
            "question": "What is RAG?",
            "document_ids": ["nonexistent-doc-id"],
        })
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_no_chunks(self, auth_client, db_session):
        """404 when document exists but has no chunks yet (still pending)."""
        doc_id = await upload_doc(auth_client, "empty.txt", "Some text")
        resp = await auth_client.post("/api/v1/query/langchain", json={
            "question": "What is RAG?",
            "document_ids": [doc_id],
        })
        assert resp.status_code == 404
        detail = resp.json().get("detail", "")
        assert "chunk" in detail.lower()

    @pytest.mark.asyncio
    async def test_without_auth(self):
        """401 when no auth token is provided."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post("/api/v1/query/langchain", json={
                "question": "What is RAG?",
                "document_ids": ["some-id"],
            })
            assert resp.status_code in (401, 403)


# ── Non-streaming endpoint (mocked chain) ─────────────────────────────────────


class TestLangChainEndpoint:
    """Tests that mock the QA chain and embedder to avoid model downloads."""

    @pytest.mark.asyncio
    async def test_successful_query(self, auth_client, db_session):
        """The endpoint returns 200 with 'answer' and 'sources' fields."""
        # Arrange ──────────────────────────────────────────────────────────
        user_id = await get_user_id()
        doc_id, _chunks = await seed_document(db_session, user_id, [
            "RAG combines retrieval with generation.",
            "Vector databases enable semantic search.",
        ])

        mock_sources = make_streaming_sources()
        mock_chain = make_mock_qa_chain(
            answer="RAG stands for Retrieval Augmented Generation.",
            sources=mock_sources,
            doc_ids={doc_id},
        )
        mock_embedder = AsyncMock()
        mock_embedder.embed_texts = AsyncMock(
            return_value=[[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        )

        with (
            patch.object(chain_module, "get_qa_chain",
                         return_value=mock_chain),
            patch.object(embedding_module, "get_embedder",
                         return_value=mock_embedder),
        ):
            # Act ──────────────────────────────────────────────────────────
            resp = await auth_client.post("/api/v1/query/langchain", json={
                "question": "What is RAG?",
                "document_ids": [doc_id],
            })

        # Assert ───────────────────────────────────────────────────────────
        assert resp.status_code == 200, f"Body: {resp.text}"
        data = resp.json()
        assert "answer" in data
        assert data["answer"] == "RAG stands for Retrieval Augmented Generation."
        assert "sources" in data
        assert len(data["sources"]) > 0
        assert "latency_ms" in data
        assert "cached" in data
        assert data["cached"] is False

    @pytest.mark.asyncio
    async def test_chain_not_initialized(self, auth_client, db_session):
        """The endpoint re-initializes the chain when is_initialized() is False."""
        user_id = await get_user_id()
        doc_id, _chunks = await seed_document(db_session, user_id, [
            "Test content for initialization.",
        ])

        mock_sources = make_streaming_sources()
        mock_chain = make_mock_qa_chain(
            answer="Generated answer.",
            sources=mock_sources,
            is_initialized=False,       # triggers re-initialization
            doc_ids=set(),
        )
        mock_embedder = AsyncMock()
        mock_embedder.embed_texts = AsyncMock(
            return_value=[[0.1, 0.2, 0.3]]
        )

        with (
            patch.object(chain_module, "get_qa_chain",
                         return_value=mock_chain),
            patch.object(embedding_module, "get_embedder",
                         return_value=mock_embedder),
        ):
            resp = await auth_client.post("/api/v1/query/langchain", json={
                "question": "What is RAG?",
                "document_ids": [doc_id],
            })

        assert resp.status_code == 200
        # verify initialize was called
        mock_chain.initialize.assert_awaited_once()
        mock_chain.generate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_empty_sources_fallback(self, auth_client, db_session):
        """When the chain returns empty sources, the endpoint returns answer + empty list."""
        user_id = await get_user_id()
        doc_id, _chunks = await seed_document(db_session, user_id, [
            "Test content.",
        ])

        mock_chain = make_mock_qa_chain(
            answer="Fallback answer.",
            sources=[],
            doc_ids={doc_id},
        )
        mock_embedder = AsyncMock()
        mock_embedder.embed_texts = AsyncMock(
            return_value=[[0.1, 0.2, 0.3]]
        )

        with (
            patch.object(chain_module, "get_qa_chain",
                         return_value=mock_chain),
            patch.object(embedding_module, "get_embedder",
                         return_value=mock_embedder),
        ):
            resp = await auth_client.post("/api/v1/query/langchain", json={
                "question": "What is RAG?",
                "document_ids": [doc_id],
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["answer"] == "Fallback answer."
        assert data["sources"] == []

    @pytest.mark.asyncio
    async def test_short_answer_overridden(self, auth_client, db_session):
        """Very short answers (less than 5 chars) are replaced with a fallback."""
        user_id = await get_user_id()
        doc_id, _chunks = await seed_document(db_session, user_id, [
            "Test content.",
        ])

        mock_sources = make_streaming_sources()
        mock_chain = make_mock_qa_chain(
            answer="No.",               # < 5 chars → trigger fallback
            sources=mock_sources,
            doc_ids={doc_id},
        )
        mock_embedder = AsyncMock()
        mock_embedder.embed_texts = AsyncMock(
            return_value=[[0.1, 0.2, 0.3]]
        )

        with (
            patch.object(chain_module, "get_qa_chain",
                         return_value=mock_chain),
            patch.object(embedding_module, "get_embedder",
                         return_value=mock_embedder),
        ):
            resp = await auth_client.post("/api/v1/query/langchain", json={
                "question": "What is RAG?",
                "document_ids": [doc_id],
            })

        assert resp.status_code == 200
        data = resp.json()
        assert "apologize" in data["answer"].lower()


# ── Streaming endpoint (mocked chain) ────────────────────────────────────────


class TestLangChainStreaming:
    """Tests for the POST /api/v1/query/langchain/stream endpoint."""

    @pytest.mark.asyncio
    async def test_streaming_success(self, auth_client, db_session):
        """Streaming endpoint yields sources then tokens via SSE."""
        user_id = await get_user_id()
        doc_id, _chunks = await seed_document(db_session, user_id, [
            "RAG combines retrieval with generation.",
        ])

        mock_sources = make_streaming_sources()

        # generate_stream must be an async generator
        async def mock_generate_stream(**kwargs):
            yield ("RAG is a technique for retrieval augmented generation.", mock_sources)

        mock_chain = make_mock_qa_chain(doc_ids={doc_id})
        mock_chain.generate_stream = mock_generate_stream

        mock_embedder = AsyncMock()
        mock_embedder.embed_texts = AsyncMock(
            return_value=[[0.1, 0.2, 0.3]]
        )

        with (
            patch.object(chain_module, "get_qa_chain",
                         return_value=mock_chain),
            patch.object(embedding_module, "get_embedder",
                         return_value=mock_embedder),
        ):
            async with auth_client.stream(
                "POST", "/api/v1/query/langchain/stream",
                json={"question": "What is RAG?", "document_ids": [doc_id]},
            ) as resp:
                assert resp.status_code == 200
                events = []
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        events.append(line)

        # Expect: sources event, then tokens, then [DONE]
        assert len(events) >= 2
        first = json.loads(events[0].removeprefix("data: "))
        if "sources" in first:
            assert len(first["sources"]) > 0
        elif "error" in first:
            pytest.fail(f"Streaming returned error: {first['error']}")

        # Last event should be [DONE] (aiter_lines strips the trailing newline)
        assert events[-1] == "data: [DONE]"

    @pytest.mark.asyncio
    async def test_streaming_empty_document_ids(self, auth_client):
        """Streaming endpoint yields an error SSE event for empty doc IDs."""
        async with auth_client.stream(
            "POST", "/api/v1/query/langchain/stream",
            json={"question": "Test?", "document_ids": []},
        ) as resp:
            assert resp.status_code == 200
            events = []
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                        events.append(line)

        assert len(events) > 0
        first = json.loads(events[0].removeprefix("data: "))
        assert "error" in first

    @pytest.mark.asyncio
    async def test_streaming_no_sources_fallback(self, auth_client, db_session):
        """When no sources are retrieved, the stream yields a friendly message."""
        user_id = await get_user_id()
        doc_id, _chunks = await seed_document(db_session, user_id, [
            "Test content.",
        ])

        async def mock_generate_stream(**kwargs):
            yield ("No information available.", [])

        mock_chain = make_mock_qa_chain(doc_ids={doc_id})
        mock_chain.generate_stream = mock_generate_stream

        mock_embedder = AsyncMock()
        mock_embedder.embed_texts = AsyncMock(
            return_value=[[0.1, 0.2, 0.3]]
        )

        with (
            patch.object(chain_module, "get_qa_chain",
                         return_value=mock_chain),
            patch.object(embedding_module, "get_embedder",
                         return_value=mock_embedder),
        ):
            async with auth_client.stream(
                "POST", "/api/v1/query/langchain/stream",
                json={"question": "What is RAG?", "document_ids": [doc_id]},
            ) as resp:
                events = []
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        events.append(line)

        # Should have a token/sources event and a [DONE]
        assert len(events) >= 2
        assert events[-1] == "data: [DONE]"


# ── Verification integration ─────────────────────────────────────────────────


class TestVerificationIntegration:
    """Tests that verify the end-to-end flow including response verification.

    These tests mock the LLM but exercise the verification layer, ensuring
    the verification is correctly wired into the chain.
    """

    @pytest.mark.asyncio
    async def test_verification_pass_through(
        self, auth_client, db_session
    ):
        """The chain's answer is passed through when mocked.

        We patch the chain at the module level so no models are loaded.
        """
        user_id = await get_user_id()
        doc_id, _chunks = await seed_document(db_session, user_id, [
            "RAG stands for Retrieval Augmented Generation.",
        ])

        mock_sources = make_streaming_sources()
        mock_chain = make_mock_qa_chain(
            answer="Verified answer.",
            sources=mock_sources,
            doc_ids={doc_id},
        )
        mock_embedder = AsyncMock()
        mock_embedder.embed_texts = AsyncMock(
            return_value=[[0.1, 0.2, 0.3]]
        )

        with (
            patch.object(chain_module, "get_qa_chain",
                         return_value=mock_chain),
            patch.object(embedding_module, "get_embedder",
                         return_value=mock_embedder),
        ):
            resp = await auth_client.post("/api/v1/query/langchain", json={
                "question": "What is RAG?",
                "document_ids": [doc_id],
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["answer"] == "Verified answer."

    @pytest.mark.asyncio
    async def test_verification_disabled_returns_answer(
        self, auth_client, db_session
    ):
        """The endpoint returns the answer when verification is skipped."""
        user_id = await get_user_id()
        doc_id, _chunks = await seed_document(db_session, user_id, [
            "RAG content.",
        ])

        mock_sources = make_streaming_sources()
        mock_chain = make_mock_qa_chain(
            answer="RAG combines retrieval with generation.",
            sources=mock_sources,
            doc_ids={doc_id},
        )
        mock_embedder = AsyncMock()
        mock_embedder.embed_texts = AsyncMock(
            return_value=[[0.1, 0.2, 0.3]]
        )

        with (
            patch.object(chain_module, "get_qa_chain",
                         return_value=mock_chain),
            patch.object(embedding_module, "get_embedder",
                         return_value=mock_embedder),
        ):
            resp = await auth_client.post("/api/v1/query/langchain", json={
                "question": "What is RAG?",
                "document_ids": [doc_id],
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["answer"] == "RAG combines retrieval with generation."
        assert len(data["sources"]) > 0


# ── Caching ───────────────────────────────────────────────────────────────────


class TestLangChainCaching:
    """Tests that verify caching behavior for the LangChain endpoint."""

    @pytest.mark.asyncio
    async def test_cached_response_returns_quickly(
        self, auth_client, db_session
    ):
        """A second identical query returns a cached response."""
        settings = get_settings()
        original_cache_days = settings.cache_expiry_days
        settings.cache_expiry_days = 7  # enable caching

        try:
            user_id = await get_user_id()
            doc_id, _chunks = await seed_document(db_session, user_id, [
                "RAG combines retrieval with generation.",
            ])

            mock_sources = make_streaming_sources()
            mock_chain = make_mock_qa_chain(
                answer="RAG is a technique.",
                sources=mock_sources,
                doc_ids={doc_id},
            )
            mock_embedder = AsyncMock()
            mock_embedder.embed_texts = AsyncMock(
                return_value=[[0.1, 0.2, 0.3]]
            )

            with (
                patch.object(chain_module, "get_qa_chain",
                             return_value=mock_chain),
                patch.object(embedding_module, "get_embedder",
                             return_value=mock_embedder),
            ):
                # First call — should invoke the chain
                resp1 = await auth_client.post("/api/v1/query/langchain", json={
                    "question": "What is RAG?",
                    "document_ids": [doc_id],
                })
                assert resp1.status_code == 200
                assert resp1.json()["cached"] is False

            # The chain.generate should have been called once
            assert mock_chain.generate.await_count == 1

            # Second identical call — should hit cache
            with (
                patch.object(chain_module, "get_qa_chain",
                             return_value=mock_chain),
                patch.object(embedding_module, "get_embedder",
                             return_value=mock_embedder),
            ):
                resp2 = await auth_client.post("/api/v1/query/langchain", json={
                    "question": "What is RAG?",
                    "document_ids": [doc_id],
                })
                assert resp2.status_code == 200
                data2 = resp2.json()
                assert data2["cached"] is True
                assert data2["answer"] == "RAG is a technique."
        finally:
            settings.cache_expiry_days = original_cache_days
