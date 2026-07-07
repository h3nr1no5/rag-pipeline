"""Integration tests for sequential RAG execution behavior.

Verifies that backends execute in request order and that a failure
in one backend does not prevent subsequent backends from running.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select


class TestSequentialOrder:
    """Verify backends execute in the order specified in the request."""

    @pytest.fixture(autouse=True, scope="function")
    def _realistic_llm(self):
        """Override session-scoped TestLLM with RealisticTestLLM.

        RealisticTestLLM parses ``[Source N]:`` sections from the
        assembled prompt and returns a response containing actual
        document content.
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
    async def test_results_appear_in_request_order(
        self, auth_client, db_session
    ):
        """Backend results should appear in the order specified in the request.

        Test flow:
          1. Seed a Document + Chunks with 768-dim embeddings.
          2. Start a query with backends=["cosine", "langchain"].
          3. Poll until completed.
          4. Verify results are in order: cosine first, then langchain.
          5. Verify all succeeded.
        """
        from src.infrastructure.database.models import Chunk, Document, User
        from tests.doubles.embedder import TestEmbedder

        # -- 1. Get test user --
        result = await db_session.execute(select(User))
        user = result.scalar_one()

        # -- 2. Seed document + chunks with embeddings --
        embedder = TestEmbedder()
        texts = [
            "To add material to the project, use the `add_material` function "
            "with the material name and quantity.",
            "The system supports various material types: concrete, steel, "
            "wood, and composites.",
            "Adding material requires authentication and the appropriate "
            "user permissions.",
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

        # -- 3. Start query with two backends --
        backends = ["cosine", "langchain"]
        start_resp = await auth_client.post(
            "/api/v1/query/start",
            json={
                "question": "how to add material?",
                "document_ids": [doc_id],
                "backends": backends,
                "include_citations": False,
                "enable_docs": False,
            },
        )
        assert start_resp.status_code == 200, (
            f"Start failed: {start_resp.text}"
        )
        task_id = start_resp.json()["task_id"]

        # -- 4. Poll until completed (up to 20s) --
        data = None
        for _ in range(40):
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
                f"Task did not reach terminal state within 20s. "
                f"Last data: {data}"
            )

        assert data is not None, "Poll loop exited without setting data"

        # -- 5. Task should be completed --
        assert data["status"] == "completed", (
            f"Task failed: status={data['status']}, error={data.get('error')}"
        )

        results = data.get("results", [])
        assert len(results) == len(backends), (
            f"Expected {len(backends)} results, got {len(results)}"
        )

        # -- 6. Verify results are in request order --
        backend_names = [r["backend"] for r in results]
        assert backend_names == backends, (
            f"Expected backends in order {backends}, got {backend_names}"
        )

        # -- 7. Verify both succeeded --
        for r in results:
            assert r.get("error") is None, (
                f"Backend {r['backend']} failed: {r.get('error')}"
            )
            assert r.get("answer"), (
                f"Backend {r['backend']} returned empty answer"
            )

    @pytest.mark.asyncio
    async def test_three_backends_in_request_order(
        self, auth_client, db_session
    ):
        """All three backends should appear in the specified order."""
        from src.infrastructure.database.models import Chunk, Document, User
        from tests.doubles.embedder import TestEmbedder

        # -- 1. Get test user --
        result = await db_session.execute(select(User))
        user = result.scalar_one()

        # -- 2. Seed document + chunks --
        embedder = TestEmbedder()
        texts = [
            "To add material to the project, use the `add_material` function.",
            "Material quantities are tracked in cubic meters for concrete.",
            "For composite materials, the ratio of components must be specified.",
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

        # -- 3. Start query with all three RAG backends --
        backends = ["cosine", "langchain", "llamaindex"]
        start_resp = await auth_client.post(
            "/api/v1/query/start",
            json={
                "question": "how to add material?",
                "document_ids": [doc_id],
                "backends": backends,
                "include_citations": False,
                "enable_docs": False,
            },
        )
        assert start_resp.status_code == 200, (
            f"Start failed: {start_resp.text}"
        )
        task_id = start_resp.json()["task_id"]

        # -- 4. Poll until completed (up to 30s for three backends) --
        data = None
        for _ in range(60):
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
                f"Task did not reach terminal state. Last data: {data}"
            )

        assert data is not None, "Poll loop exited without setting data"

        # -- 5. Task should be completed --
        assert data["status"] == "completed", (
            f"Task failed: status={data['status']}, error={data.get('error')}"
        )

        results = data.get("results", [])
        assert len(results) == len(backends), (
            f"Expected {len(backends)} results, got {len(results)}"
        )

        # -- 6. Verify results are in request order --
        backend_names = [r["backend"] for r in results]
        assert backend_names == backends, (
            f"Expected backends in order {backends}, got {backend_names}"
        )

        # -- 7. Verify all succeeded --
        for r in results:
            assert r.get("error") is None, (
                f"Backend {r['backend']} failed: {r.get('error')}"
            )
            assert r.get("answer"), (
                f"Backend {r['backend']} returned empty answer"
            )


class TestFailureContinuation:
    """Verify that a backend failure does not stop subsequent backends."""

    @pytest.fixture(autouse=True, scope="function")
    def _realistic_llm(self):
        """Override session-scoped TestLLM with RealisticTestLLM."""
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
    async def test_failure_in_first_backend_does_not_block_second(
        self, auth_client, db_session
    ):
        """If the first backend fails, the second should still run and succeed.

        Test flow:
          1. Monkeypatch _BACKEND_MAP so "cosine" raises an exception.
          2. Seed Document + Chunks with embeddings.
          3. Start a query with backends=["cosine", "langchain"].
          4. Poll until completed.
          5. Verify cosine result has error.
          6. Verify langchain result succeeded.
          7. Verify results are still in request order.
        """
        import src.api.routes.query._executor as executor_mod
        from src.infrastructure.database.models import Chunk, Document, User
        from tests.doubles.embedder import TestEmbedder

        # -- 1. Monkeypatch cosine to fail --
        async def _failing_cosine(db, request, user_id):
            raise ValueError("Simulated cosine failure")

        original_cosine = executor_mod._BACKEND_MAP["cosine"]
        executor_mod._BACKEND_MAP["cosine"] = _failing_cosine

        try:
            # -- 2. Get test user --
            result = await db_session.execute(select(User))
            user = result.scalar_one()

            # -- 3. Seed document + chunks --
            embedder = TestEmbedder()
            texts = [
                "To add material to the project, use the `add_material` function.",
                "The system supports various material types: concrete, steel.",
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

            # -- 4. Start query --
            backends = ["cosine", "langchain"]
            start_resp = await auth_client.post(
                "/api/v1/query/start",
                json={
                    "question": "how to add material?",
                    "document_ids": [doc_id],
                    "backends": backends,
                    "include_citations": False,
                    "enable_docs": False,
                },
            )
            assert start_resp.status_code == 200, (
                f"Start failed: {start_resp.text}"
            )
            task_id = start_resp.json()["task_id"]

            # -- 5. Poll until completed (up to 20s) --
            data = None
            for _ in range(40):
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
                    f"Task did not reach terminal state. Last: {data}"
                )

            assert data is not None, "Poll loop exited without setting data"

            # -- 6. Task should be completed (partial success) --
            assert data["status"] == "completed", (
                f"Task failed entirely: {data.get('error')}"
            )

            results = data.get("results", [])
            assert len(results) == 2, (
                f"Expected 2 results, got {len(results)}"
            )

            # -- 7. Verify cosine failed --
            cosine_result = next(
                r for r in results if r["backend"] == "cosine"
            )
            assert cosine_result.get("error") is not None, (
                "Expected cosine to have an error but it succeeded"
            )

            # -- 8. Verify langchain succeeded --
            langchain_result = next(
                r for r in results if r["backend"] == "langchain"
            )
            assert langchain_result.get("error") is None, (
                f"Langchain should have succeeded: "
                f"{langchain_result.get('error')}"
            )
            assert langchain_result.get("answer"), (
                "Langchain should have a non-empty answer"
            )

            # -- 9. Verify order preserved even with failure --
            backend_names = [r["backend"] for r in results]
            assert backend_names == backends, (
                f"Expected order {backends}, got {backend_names}"
            )

        finally:
            # Restore original backend
            executor_mod._BACKEND_MAP["cosine"] = original_cosine

    @pytest.mark.asyncio
    async def test_failure_in_middle_does_not_block_last(
        self, auth_client, db_session
    ):
        """If the middle backend fails, third should still run and succeed."""
        import src.api.routes.query._executor as executor_mod
        from src.infrastructure.database.models import Chunk, Document, User
        from tests.doubles.embedder import TestEmbedder

        # -- 1. Monkeypatch langchain to fail --
        async def _failing_langchain(db, request, user_id):
            raise RuntimeError("Simulated langchain failure")

        original_langchain = executor_mod._BACKEND_MAP["langchain"]
        executor_mod._BACKEND_MAP["langchain"] = _failing_langchain

        try:
            # -- 2. Get test user + seed document --
            result = await db_session.execute(select(User))
            user = result.scalar_one()

            embedder = TestEmbedder()
            texts = [
                "To add material to the project, use the `add_material` function.",
                "The system supports various material types: concrete, steel.",
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
                    chunk_metadata={},
                    embedding=emb,
                )
                db_session.add(chunk)
            await db_session.commit()

            # -- 3. Start query with three backends --
            backends = ["cosine", "langchain", "llamaindex"]
            start_resp = await auth_client.post(
                "/api/v1/query/start",
                json={
                    "question": "how to add material?",
                    "document_ids": [doc_id],
                    "backends": backends,
                    "include_citations": False,
                    "enable_docs": False,
                },
            )
            assert start_resp.status_code == 200, (
                f"Start failed: {start_resp.text}"
            )
            task_id = start_resp.json()["task_id"]

            # -- 4. Poll until completed (up to 30s) --
            data = None
            for _ in range(60):
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
                    f"Task did not reach terminal state. Last: {data}"
                )

            assert data is not None, "Poll loop exited without setting data"

            # -- 5. Task should be completed (partial success) --
            assert data["status"] == "completed", (
                f"Task failed entirely: {data.get('error')}"
            )

            results = data.get("results", [])
            assert len(results) == 3, (
                f"Expected 3 results, got {len(results)}"
            )

            # -- 6. Verify cosine succeeded --
            cosine_result = next(
                r for r in results if r["backend"] == "cosine"
            )
            assert cosine_result.get("error") is None, (
                f"Cosine should have succeeded: "
                f"{cosine_result.get('error')}"
            )

            # -- 7. Verify langchain failed --
            langchain_result = next(
                r for r in results if r["backend"] == "langchain"
            )
            assert langchain_result.get("error") is not None, (
                "Expected langchain to have an error"
            )

            # -- 8. Verify llamaindex succeeded --
            llamaindex_result = next(
                r for r in results if r["backend"] == "llamaindex"
            )
            assert llamaindex_result.get("error") is None, (
                f"LlamaIndex should have succeeded: "
                f"{llamaindex_result.get('error')}"
            )
            assert llamaindex_result.get("answer"), (
                "LlamaIndex should have a non-empty answer"
            )

            # -- 9. Verify order preserved --
            backend_names = [r["backend"] for r in results]
            assert backend_names == backends, (
                f"Expected order {backends}, got {backend_names}"
            )

        finally:
            executor_mod._BACKEND_MAP["langchain"] = original_langchain

    @pytest.mark.asyncio
    async def test_all_backends_fail_reports_failed(
        self, auth_client, db_session
    ):
        """If all backends fail, the task should be marked failed."""
        import src.api.routes.query._executor as executor_mod
        from src.infrastructure.database.models import Chunk, Document, User
        from tests.doubles.embedder import TestEmbedder

        # -- 1. Monkeypatch both backends to fail --
        async def _failing_backend(db, request, user_id):
            raise ValueError("Simulated failure")

        original_cosine = executor_mod._BACKEND_MAP["cosine"]
        original_langchain = executor_mod._BACKEND_MAP["langchain"]
        executor_mod._BACKEND_MAP["cosine"] = _failing_backend
        executor_mod._BACKEND_MAP["langchain"] = _failing_backend

        try:
            # -- 2. Seed document + chunks --
            result = await db_session.execute(select(User))
            user = result.scalar_one()

            embedder = TestEmbedder()
            texts = ["Some text for testing."]
            doc_id = str(uuid.uuid4())
            doc = Document(
                id=doc_id,
                user_id=user.id,
                title="test.txt",
                doc_type="txt",
                file_path="/tmp/test.txt",
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
                    chunk_metadata={},
                    embedding=emb,
                )
                db_session.add(chunk)
            await db_session.commit()

            # -- 3. Start query --
            start_resp = await auth_client.post(
                "/api/v1/query/start",
                json={
                    "question": "test question?",
                    "document_ids": [doc_id],
                    "backends": ["cosine", "langchain"],
                    "include_citations": False,
                    "enable_docs": False,
                },
            )
            assert start_resp.status_code == 200
            task_id = start_resp.json()["task_id"]

            # -- 4. Poll until terminal --
            data = None
            for _ in range(40):
                poll_resp = await auth_client.get(
                    f"/api/v1/query/status/{task_id}"
                )
                data = poll_resp.json()
                if data["status"] in ("completed", "failed"):
                    break
                await asyncio.sleep(0.5)
            else:
                pytest.fail(
                    f"Task did not reach terminal state. Last: {data}"
                )

            # -- 5. Task should be failed --
            assert data["status"] == "failed", (
                f"Expected failed status when all backends fail, "
                f"got: {data['status']}"
            )
            assert data.get("error") is not None, (
                "Expected error message when all backends fail"
            )
            assert "All backends failed" in data["error"], (
                f"Error message should mention all backends failed: "
                f"{data['error']}"
            )

            # -- 6. Results should still be in order --
            results = data.get("results", [])
            backend_names = [r["backend"] for r in results]
            assert backend_names == ["cosine", "langchain"], (
                f"Expected order preserved even on failure, "
                f"got: {backend_names}"
            )

        finally:
            executor_mod._BACKEND_MAP["cosine"] = original_cosine
            executor_mod._BACKEND_MAP["langchain"] = original_langchain
