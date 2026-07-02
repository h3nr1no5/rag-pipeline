"""Integration tests for async background query execution API endpoints.

Tests the ``POST /api/v1/query/start`` and ``GET /api/v1/query/status/{task_id}``
endpoints including task creation, status polling, limit enforcement, and error
handling.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from src.api.main import app

# The start endpoint only validates document_ids is non-empty and creates a
# task record.  Background execution happens out-of-band, so most tests use
# dummy document IDs and poll for status without waiting for completion.


class TestStartQuery:
    """Tests for POST /api/v1/query/start."""

    @pytest.mark.asyncio
    async def test_start_query_returns_task_id_and_pending(self, auth_client):
        """Starting a query should return task_id and pending status."""
        response = await auth_client.post(
            "/api/v1/query/start",
            json={
                "question": "What is this document about?",
                "document_ids": ["dummy-doc-id"],
            },
        )

        assert response.status_code == 200, f"Start failed: {response.text}"
        data = response.json()

        assert "task_id" in data
        assert isinstance(data["task_id"], str)
        assert len(data["task_id"]) > 0
        assert data["status"] == "pending"

    @pytest.mark.asyncio
    async def test_start_query_rejects_empty_document_ids(self, auth_client):
        """Starting a query with no document_ids should return 400."""
        response = await auth_client.post(
            "/api/v1/query/start",
            json={
                "question": "Test question?",
                "document_ids": [],
            },
        )

        assert response.status_code == 400
        data = response.json()
        assert "detail" in data
        detail_lower = data["detail"].lower()
        assert "document_id" in detail_lower or "required" in detail_lower

    @pytest.mark.asyncio
    async def test_start_query_rejects_invalid_backends(self, auth_client):
        """Starting a query with an invalid backend name should return 422."""
        response = await auth_client.post(
            "/api/v1/query/start",
            json={
                "question": "Test?",
                "document_ids": ["dummy-doc"],
                "backends": ["invalid_backend"],
            },
        )

        assert response.status_code == 422
        data = response.json()
        assert "detail" in data

        # Verify the error mentions the invalid backend
        detail_str = str(data["detail"]).lower()
        assert "invalid_backend" in detail_str or "backend" in detail_str

    @pytest.mark.asyncio
    async def test_start_query_rejects_multiple_invalid_backends(self, auth_client):
        """Starting with several invalid backends should return 422."""
        response = await auth_client.post(
            "/api/v1/query/start",
            json={
                "question": "Test?",
                "document_ids": ["dummy-doc"],
                "backends": ["cosine", "bad_1", "bad_2"],
            },
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_start_query_without_auth(self):
        """Starting a query without authentication should return 401/403."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/query/start",
                json={
                    "question": "Test?",
                    "document_ids": ["some-doc-id"],
                },
            )
        assert response.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_start_query_accepts_valid_backends(self, auth_client):
        """All valid backend combinations should be accepted."""
        for backends in [
            ["cosine"],
            ["langchain"],
            ["llamaindex"],
            ["cosine", "langchain"],
            ["cosine", "langchain", "llamaindex"],
        ]:
            response = await auth_client.post(
                "/api/v1/query/start",
                json={
                    "question": "Test?",
                    "document_ids": ["dummy-doc"],
                    "backends": backends,
                },
            )
            assert response.status_code == 200, (
                f"Backends {backends} failed: {response.text}"
            )

    @pytest.mark.asyncio
    async def test_start_query_accepts_empty_backends_list(self, auth_client):
        """An empty backends list should be accepted (no RAG backends will run)."""
        response = await auth_client.post(
            "/api/v1/query/start",
            json={
                "question": "Test?",
                "document_ids": ["dummy-doc"],
                "backends": [],
            },
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_start_query_question_min_length(self, auth_client):
        """A question with 1 character should be valid."""
        response = await auth_client.post(
            "/api/v1/query/start",
            json={
                "question": "?",
                "document_ids": ["dummy-doc"],
            },
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_start_query_question_max_length(self, auth_client):
        """A question at exactly 2000 characters should be valid."""
        response = await auth_client.post(
            "/api/v1/query/start",
            json={
                "question": "x" * 2000,
                "document_ids": ["dummy-doc"],
            },
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_start_query_question_too_long(self, auth_client):
        """A question longer than 2000 characters should be rejected."""
        response = await auth_client.post(
            "/api/v1/query/start",
            json={
                "question": "x" * 2001,
                "document_ids": ["dummy-doc"],
            },
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_start_query_rejects_empty_question(self, auth_client):
        """An empty question should be rejected."""
        response = await auth_client.post(
            "/api/v1/query/start",
            json={
                "question": "",
                "document_ids": ["dummy-doc"],
            },
        )
        assert response.status_code == 422


class TestQueryStatus:
    """Tests for GET /api/v1/query/status/{task_id}."""

    @pytest.mark.asyncio
    async def test_poll_status_returns_current_state(self, auth_client):
        """Polling a task should return its current status with valid response shape."""
        start_resp = await auth_client.post(
            "/api/v1/query/start",
            json={
                "question": "What is this about?",
                "document_ids": ["dummy-doc"],
            },
        )
        assert start_resp.status_code == 200
        task_id = start_resp.json()["task_id"]

        # Poll — task should exist regardless of whether background exec started
        poll_resp = await auth_client.get(f"/api/v1/query/status/{task_id}")
        assert poll_resp.status_code == 200, f"Poll failed: {poll_resp.text}"
        data = poll_resp.json()

        # Validate response shape matches TaskStatusResponse
        assert data["task_id"] == task_id
        assert data["status"] in ("pending", "running", "completed", "failed")
        assert isinstance(data["created_at"], (int, float))
        assert isinstance(data["progress"], dict)
        assert isinstance(data["results"], list)

        # Optional fields
        if data["error"] is not None:
            assert isinstance(data["error"], str)
        if data["completed_at"] is not None:
            assert isinstance(data["completed_at"], (int, float))

    @pytest.mark.asyncio
    async def test_poll_returns_404_for_unknown_task(self, auth_client):
        """Polling a non-existent task should return 404."""
        response = await auth_client.get(
            "/api/v1/query/status/nonexistent-task-id"
        )
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data

    @pytest.mark.asyncio
    async def test_poll_returns_403_for_wrong_user(self, auth_client):
        """A user should not be able to poll another user's task."""
        # Start a query as user A
        start_resp = await auth_client.post(
            "/api/v1/query/start",
            json={
                "question": "Test?",
                "document_ids": ["dummy-doc"],
            },
        )
        assert start_resp.status_code == 200
        task_id = start_resp.json()["task_id"]

        # Create a second user and try to poll the task
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            email = f"other_{uuid.uuid4().hex[:8]}@example.com"
            await ac.post(
                "/api/v1/auth/signup",
                json={"email": email, "password": "testpassword123"},
            )
            login_resp = await ac.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "testpassword123"},
            )
            token = login_resp.json()["access_token"]
            ac.headers["Authorization"] = f"Bearer {token}"

            poll_resp = await ac.get(f"/api/v1/query/status/{task_id}")
            assert poll_resp.status_code == 403
            data = poll_resp.json()
            assert "detail" in data

    @pytest.mark.asyncio
    async def test_poll_returns_same_result_on_repeated_polls(self, auth_client):
        """Repeated polls of the same task should return consistent data."""
        start_resp = await auth_client.post(
            "/api/v1/query/start",
            json={
                "question": "Test?",
                "document_ids": ["dummy-doc"],
            },
        )
        task_id = start_resp.json()["task_id"]

        # Poll twice
        resp1 = await auth_client.get(f"/api/v1/query/status/{task_id}")
        resp2 = await auth_client.get(f"/api/v1/query/status/{task_id}")

        assert resp1.status_code == 200
        assert resp2.status_code == 200
        d1, d2 = resp1.json(), resp2.json()
        assert d1["task_id"] == d2["task_id"]
        # Status could progress between polls, but task_id stays same


class TestTaskLimits:
    """Tests for task creation limits enforcement."""

    @pytest.mark.asyncio
    async def test_per_user_task_limit(self, auth_client):
        """Creating many tasks for the same user should eventually hit the limit.

        The per-user limit is 50.  This test creates 52 tasks and expects
        the last few to be rejected.

        ``TaskLimitError`` is caught in the endpoint and returned as HTTP 429.
        """
        responses = []
        for i in range(52):
            resp = await auth_client.post(
                "/api/v1/query/start",
                json={
                    "question": f"Test question {i}?",
                    "document_ids": [f"dummy-doc-{i % 5}"],
                },
            )
            responses.append(resp)

        # Count successes and errors
        success_count = sum(1 for r in responses if r.status_code == 200)
        error_count = sum(1 for r in responses if r.status_code >= 400)
        total_count = len(responses)

        # Exactly 52 requests were made
        assert total_count == 52

        # At most 50 should succeed (per-user limit)
        assert success_count <= 50, (
            f"Expected ≤50 successful task creations, got {success_count}. "
            f"Per-user limit may not be enforced."
        )

        # The remaining should be errors (currently 500 due to missing handler)
        assert error_count >= 2, (
            f"Expected at least 2 errors, got {error_count}. "
            f"Success count: {success_count}, Error count: {error_count}"
        )

        # All errors should be 429 (TaskLimitError caught and converted)
        for r in responses:
            if r.status_code >= 400:
                assert r.status_code == 429, (
                    f"Expected 429 but got {r.status_code}: {r.text[:200]}"
                )
                assert "limit" in r.json().get("detail", "").lower()

    @pytest.mark.asyncio
    async def test_task_creation_after_success(self, auth_client):
        """A user should still be able to create tasks even after some succeed."""
        # Create a few tasks
        for i in range(3):
            resp = await auth_client.post(
                "/api/v1/query/start",
                json={
                    "question": f"Batch 1 question {i}?",
                    "document_ids": ["dummy-doc"],
                },
            )
            assert resp.status_code == 200

        # Create more tasks — should still work
        for i in range(3):
            resp = await auth_client.post(
                "/api/v1/query/start",
                json={
                    "question": f"Batch 2 question {i}?",
                    "document_ids": ["dummy-doc"],
                },
            )
            assert resp.status_code == 200


class TestTaskStatusShape:
    """Tests for status endpoint response schema validation."""

    @pytest.mark.asyncio
    async def test_status_has_all_required_fields(self, auth_client):
        """The status response should have all required fields."""
        start_resp = await auth_client.post(
            "/api/v1/query/start",
            json={
                "question": "Test shape?",
                "document_ids": ["dummy-doc"],
            },
        )
        task_id = start_resp.json()["task_id"]

        poll_resp = await auth_client.get(f"/api/v1/query/status/{task_id}")
        assert poll_resp.status_code == 200
        data = poll_resp.json()

        # Required fields
        assert "task_id" in data
        assert "status" in data
        assert "results" in data
        assert "progress" in data
        assert "created_at" in data

        # Types
        assert isinstance(data["results"], list)
        assert isinstance(data["progress"], dict)
        assert isinstance(data["created_at"], (int, float))

    @pytest.mark.asyncio
    async def test_backend_result_shape_in_completed_task(self, auth_client):
        """If a task has completed results, each result should match BackendResultSchema."""
        start_resp = await auth_client.post(
            "/api/v1/query/start",
            json={
                "question": "What is this about?",
                "document_ids": ["dummy-doc-for-shape"],
                "backends": ["cosine"],
            },
        )
        task_id = start_resp.json()["task_id"]

        # Poll a few times to see if the task progresses
        for attempt in range(10):
            poll_resp = await auth_client.get(f"/api/v1/query/status/{task_id}")
            data = poll_resp.json()

            # If there are results, validate their shape
            results = data.get("results", [])
            if results:
                for result in results:
                    assert "backend" in result
                    assert "answer" in result
                    assert "sources" in result
                    assert isinstance(result["sources"], list)
                    assert "error" in result
                    assert "cached" in result

                    assert isinstance(result["backend"], str)
                    assert isinstance(result["answer"], str)
                    assert isinstance(result["cached"], bool)
                    if result["error"] is not None:
                        assert isinstance(result["error"], str)

                    # Source chunks
                    for source in result["sources"]:
                        assert "chunk_id" in source
                        assert "content" in source
                        assert "score" in source
                break

            if data["status"] in ("completed", "failed"):
                # Terminal state but no results — that's possible if backends failed
                break

            await asyncio.sleep(0.3)


class TestAsyncQueryE2E:
    """End-to-end tests for the async query pipeline with real seeded data.

    Unlike the other tests in this file that use dummy document IDs,
    these tests seed actual Document + Chunk rows with proper 768-dim
    embeddings directly into the test DB and verify that the full
    pipeline (retrieval --> prompt building --> LLM --> result storage
    --> status endpoint) produces and returns a non-empty answer.

    This directly catches regressions of the 'answer not shown' bug
    where the backend generates an answer but it doesn't surface
    through the ``GET /api/v1/query/status/{task_id}`` endpoint.
    """

    @pytest.fixture(autouse=True, scope="function")
    def _realistic_llm(self):
        """Override the session-scoped TestLLM with RealisticTestLLM.

        RealisticTestLLM parses ``[Source N]:`` sections from the
        assembled prompt and returns a response containing actual
        document content, verifying the full retrieval-to-LLM path.
        """
        import src.domain.services.llm as llm_mod
        from tests.doubles.llm import RealisticTestLLM

        llm_mod._llm_instance = RealisticTestLLM()

    @pytest_asyncio.fixture(autouse=True, scope="function")
    async def db_session(self, setup_test_db):
        """Provide a test DB session for direct data seeding."""
        from src.infrastructure.database.session import async_session_maker

        async with async_session_maker() as session:
            yield session

    @pytest.mark.asyncio
    async def test_async_cosine_returns_non_empty_answer(
        self, auth_client, db_session
    ):
        """Async cosine backend must return a non-empty answer with real data.

        Test flow:
          1. Seed a Document + 5 Chunks with proper 768-dim embeddings.
          2. Start an async query via ``POST /api/v1/query/start``.
          3. Poll ``GET /api/v1/query/status/{task_id}`` until completion.
          4. Assert the cosine backend result has a non-empty answer.
          5. Assert sources contain valid ``chunk_id`` / ``content`` / ``score``.
          6. Assert the answer references actual document content.
        """
        from src.infrastructure.database.models import Chunk, Document, User
        from tests.doubles.embedder import TestEmbedder

        # -- 1. Get the test user ID -------------------------------------------
        result = await db_session.execute(select(User))
        user = result.scalar_one()

        # -- 2. Seed document + chunks with real embeddings --------------------
        embedder = TestEmbedder()

        texts = [
            "To add material to the project, use the `add_material` function with the material name and quantity.",  # noqa: E501
            "The system supports various material types: concrete, steel, wood, and composites.",
            "Adding material requires authentication and the appropriate user permissions.",
            "Material quantities are tracked in cubic meters for concrete and kilograms for steel.",
            "For composite materials, the ratio of components must be specified during addition.",
        ]

        doc_id = str(uuid.uuid4())
        doc = Document(
            id=doc_id,
            user_id=user.id,
            title="test_material.txt",
            doc_type="txt",
            file_path="/tmp/test_material.txt",
            file_size=sum(len(t) for t in texts),
            chunking_strategy_id="recursive",
            status="completed",
            chunk_count=len(texts),
        )
        db_session.add(doc)

        embeddings = await embedder.embed_texts(texts)
        for i, (text, emb) in enumerate(zip(texts, embeddings)):
            chunk = Chunk(
                id=str(uuid.uuid4()),
                document_id=doc_id,
                content=text,
                chunk_index=i,
                chunk_metadata={"source": f"paragraph_{i}"},
                embedding=emb,
            )
            db_session.add(chunk)

        await db_session.commit()

        # -- 3. Start async query with cosine backend --------------------------
        start_resp = await auth_client.post(
            "/api/v1/query/start",
            json={
                "question": "how to add material?",
                "document_ids": [doc_id],
                "backends": ["cosine"],
            },
        )
        assert start_resp.status_code == 200, (
            f"Start query failed: {start_resp.text}"
        )
        task_id = start_resp.json()["task_id"]

        # -- 4. Poll until completion (up to 15s) ------------------------------
        data = None
        for _ in range(30):
            poll_resp = await auth_client.get(
                f"/api/v1/query/status/{task_id}"
            )
            assert poll_resp.status_code == 200, (
                f"Poll failed: {poll_resp.text}"
            )
            data = poll_resp.json()

            if data["status"] in ("completed", "failed"):
                break
            await asyncio.sleep(0.5)
        else:
            pytest.fail(
                f"Task did not reach terminal state within 15s. "
                f"Last status: {data.get('status') if data else 'N/A'}"
            )

        assert data is not None, "Poll loop exited without setting data"

        # -- 5. Verify task completed, not failed ------------------------------
        assert data["status"] == "completed", (
            f"Task failed: status={data['status']}, error={data.get('error')}"
        )

        # -- 6. Find the cosine backend result --------------------------------
        results = data.get("results", [])
        assert len(results) > 0, (
            f"No backend results returned. Full response: {data}"
        )

        cosine_result = next(
            (r for r in results if r["backend"] == "cosine"), None
        )
        assert cosine_result is not None, (
            f"No cosine result in task results. Available backends: "
            f"{[r['backend'] for r in results]}"
        )

        # -- 7. CRITICAL: Verify answer is present and non-empty --------------
        assert cosine_result.get("answer"), (
            f"BUG: Cosine answer is empty/None! "
            f"This is the 'answer not shown' bug. Full result:\n{cosine_result}"
        )
        assert cosine_result.get("error") is None, (
            f"Cosine backend returned error: {cosine_result['error']}"
        )

        # -- 8. Verify answer references document content ---------------------
        # RealisticTestLLM returns "Based on the provided material: ..."
        assert "material" in cosine_result["answer"].lower(), (
            f"Answer does not reference document content. "
            f"Answer: {cosine_result['answer'][:100]}"
        )

        # -- 9. Verify sources -------------------------------------------------
        sources = cosine_result.get("sources", [])
        assert len(sources) > 0, (
            f"Should have at least 1 source chunk. Got {len(sources)}"
        )
        for source in sources:
            assert "chunk_id" in source, f"Source missing chunk_id: {source}"
            assert "content" in source, f"Source missing content: {source}"
            assert "score" in source, f"Source missing score: {source}"
