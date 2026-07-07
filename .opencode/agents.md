# Project Agents

This project uses a **multi-agent orchestration system**
The central **@coordinator** (Big Pickle) decomposes tasks and delegates to specialized sub-agents.

## Core Agents

| Agent                     | Role                              | Free Model                     | Temp | Key Strength                     |
|---------------------------|-----------------------------------|--------------------------------|------|----------------------------------|
| @coordinator              | Orchestrator                      | big-pickle                     | 0.1  | Planning & delegation            |

## Usage
- Start with `@coordinator` for best results.
- All models are free (as of April 2026). Run `/models` to confirm current availability.


---
## Mandatory Security Policy

**Security review is non-negotiable.**

- Every feature, refactor, or code change **must** receive a security review from @subagents/security before final delivery.
- The @coordinator is responsible for enforcing this gate in every workflow.
- Violations of this policy are not allowed.

---
## Project Facts (for all agents)

**Architecture**: FastAPI backend + Streamlit frontend. 4 RAG backends: cosine similarity, LangChain (BM25+FAISS hybrid), LlamaIndex, API-doc. Query routes in `src/api/routes/query/routes.py`.

**Entrypoint**: `src/main.py` imports `app` from `src.api.main` and runs uvicorn.

**DB**: SQLite via SQLAlchemy + aiosqlite. FAISS vector store in `data/vectorstore/`.

**Auth**: JWT/bcrypt, 30-min expiry, route-level `get_current_user` dependency. All routes under `/api/v1` prefix. `GET /api/v1/documents/strategies/types` is the only unauthenticated endpoint.

**LLM & Embedder**: Singletons, lazy-loaded on first use (`domain/services/llm.py`, `domain/services/embedding.py`).

**Document processing**: Async background via `asyncio.create_task` in `domain/services/processor.py`.

**API-docs pipeline**: YAML-based chunking strategies (`config/strategies.yaml`), seeded by `src/infrastructure/strategies/seeder.py`, 4 entity types: interfaces, enums, error_codes, records.

**Key quirks**:
- `rank-bm25` has conflicting constraints (`>=0.7` and `==0.2.2`) in pyproject.toml — uv resolves to `0.2.2`
- `.env` loaded redundantly in both `src/core/config.py` and `src/api/main.py`
- No `.pre-commit-config.yaml`, no CI workflows, no Docker configs
- `config` JSON column on ChunkingStrategy stores YAML-based params

**Testing**: `asyncio_mode = auto`, all test files use `@pytest.mark.asyncio`. Tests organized by directory (`tests/unit/`, `tests/integration/`). `@pytest.mark.integration` NOT registered.

**Root conftest (`tests/conftest.py`)** — 3 autouse fixtures run on every integration test:
1. `setup_test_db` — creates a unique SQLite file per test (`test_integration_db_*.sqlite`), patches `async_session_maker` across all modules (database, processor, executor), creates tables + seeds system chunking strategies (recursive, semantic, api-docs). Teardown: cancels background tasks, disposes engine, retries file deletion with backoff.
2. `clean_uploads_dir` — removes all files from `./data/uploads/` before each test.
3. `cancel_background_tasks` — cancels any lingering `process_doc_*` and `async_query_*` tasks before teardown.
4. `collect_garbage` — runs `gc.collect()` after each test to prevent tensor leaks.

**Unit conftest (`tests/unit/conftest.py`)** — overrides all 3 autouse fixtures with no-ops (unit tests don't need a database).

**Integration conftest (`tests/integration/conftest.py`)**:
- `auth_client` fixture — provides an `AsyncClient` with `ASGITransport(app=app)`, auto-signs up + logs in a unique user, attaches Bearer token.
- `seed_singletons` (session-scoped) — replaces real LLM/embedder with test doubles (`tests/doubles/llm.py`, `tests/doubles/embedder.py`) so tests run without loading real models.
- `wait_for_document()` helper — polls `GET /api/v1/documents/{id}/status` until completed/failed, with chunk count consistency verification.

**Test doubles** live in `tests/doubles/`: `TestEmbedder` (returns fake embeddings), `TestLLM` (returns canned responses).

**Fixture doc files** in `tests/docs/` (PDF, DOCX for upload tests).

---
## Async/Await Rules (critical)

This project is **heavily async** — FastAPI, aiosqlite, pytest-asyncio, background task processing. New code must follow these rules:

**DO:**
- Use `async def` for any function that awaits, and `await` for all async calls
- Use `asyncio.create_task()` with `task.get_name()` for background work — name tasks with a unique prefix (e.g. `process_doc_*`, `async_query_*`) so they can be tracked/cancelled
- Use `asyncio.sleep()` (not `time.sleep()`) inside async functions
- Use `AsyncClient` + `ASGITransport` for HTTP testing (never a live server)
- Cancel background tasks in test teardown with `await asyncio.wait(tasks, timeout=...)`

**DON'T:**
- **Never call `asyncio.run()` inside an async context** — it creates a new event loop and crashes with "Event loop is already running". This is why DSPy is disabled in tests (`API_DOCS_DSPY_ENABLED=false`).
- **Never mix `sync` and `async` DB sessions** — SQLAlchemy async session cannot be used with sync engine and vice versa
- **Never fire-and-forget a task** without naming it and providing a cancellation path
- **Never use blocking I/O** (sync HTTP calls, `time.sleep()`, sync file reads) inside async routes — they block the entire event loop
- **Never share an async engine across event loops** — create engine per-loop or use singleton with proper lifecycle

**Important env vars**: `SECRET_KEY` (required), `HF_HUB_OFFLINE=1` to skip model downloads, `ACCESS_TOKEN_EXPIRE_MINUTES=30`.
