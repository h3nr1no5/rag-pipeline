## Context

The project has 3 testing layers:
- **Unit tests** (`tests/unit/`): Pure logic, no I/O
- **Integration tests** (`tests/integration/`): FastAPI backend via `ASGITransport(app=app)`, in-process, use `seed_singletons` test doubles for LLM/embedder
- **No frontend tests**: Zero coverage for the Streamlit UI layer

The `fix-rag-ui-freeze` change implemented an async task queue with polling (`POST /api/v1/query/start` + `GET /api/v1/query/status/{id}`). The frontend renders answers via `poll_query_task()` appended to `Chat.py`. However, a rendering bug persists: answers returned by the backend never appear on screen.

Two changes are needed:
1. **Fix the rendering bug** in `poll_query_task()` or the message rendering loop
2. **Add Playwright-based frontend e2e tests** to prevent regression — these require running backend + frontend as real HTTP servers

## Goals / Non-Goals

**Goals:**
- Fix the "answer never appears" rendering bug in the Streamlit chat UI
- Create a reusable Playwright test framework (`tests/frontend/conftest.py`) that starts the FastAPI backend and Streamlit frontend as subprocesses
- Write one end-to-end test: login → upload document → submit query → assert answer appears in the DOM
- Use **real LLM and embedder models** in the e2e test — no test doubles — because their asyncio patterns may be related to the rendering bug

**Non-Goals:**
- Testing the API Docs (DSPy) query path in the e2e test — focus on the 3 standard RAG backends (cosine, langchain, llamaindex)
- Cross-browser testing — Chromium only
- Performance/load testing
- Visual regression testing (screenshots)

## Decisions

### Decision 1: Subprocess server fixtures (no custom entrypoint)

**Chosen: Start uvicorn directly as a subprocess**

The existing integration tests run FastAPI in-process via `ASGITransport`. For Playwright, we need real HTTP servers. The approach:

1. No custom entrypoint script is needed. The backend fixture starts uvicorn directly:
   ```
   python -m uvicorn src.api.main:app --host 127.0.0.1 --port <random>
   ```
   with `DATABASE_URL` set to a unique SQLite path in the environment.
2. Health check polls `GET /api/v1/documents/strategies/types` (no auth required, does NOT trigger model lazy-loading).
3. A separate subprocess for Streamlit: `streamlit run client/app.py --server.port=<port> --server.headless=true`
4. Both are terminated in fixture teardown via SIGTERM → wait → SIGKILL fallback.

**Alternatives considered:**
- *In-process Streamlit testing*: `streamlit.testing.v1` exists but doesn't support the full interactive flow (auth, file upload, async rendering)
- *Docker Compose*: Adds complexity, not suitable for a project without Docker configs
- *Custom test entrypoint script*: Unnecessary complexity — uvicorn CLI with env vars is sufficient

### Decision 2: Real models — no test doubles

**Chosen: Use real LLM and embedder models to exercise async patterns**

The rendering bug has persisted despite passing integration tests that use `TestLLM`/`TestEmbedder`. Using real models ensures the e2e test exercises the actual async patterns that may trigger the bug:

- **Real async inference**: `TestLLM` returns synchronously in milliseconds. Real model inference is async and takes seconds — different event loop scheduling.
- **Lazy-load timing**: The first query triggers model loading (`get_llm()` / `get_embedder()` singletons). If `poll_query_task()` starts receiving results before models are fully initialized, the control flow differs from the pre-loaded test-double path.
- **MLX asyncio integration**: The `mlx-community/Qwen2.5-1.5B-Instruct-4bit` model uses MLX's async compute patterns. Test doubles are plain synchronous Python.

**Implications:**
- Test requires real models: `mlx-community/Qwen2.5-1.5B-Instruct-4bit` (~500MB) + `sentence-transformers/all-mpnet-base-v2` (~1GB)
- First run downloads models unless `HF_HUB_OFFLINE=1` is set (models already cached from dev use)
- Test execution time: ~30-120s (real inference, model loading on first query)
- Hardware requirement: Apple Silicon (MLX-optimized model)
- Test is marked with `@pytest.mark.slow` and placed in `tests/frontend/`
- `HF_TOKEN` env var may be needed if gated models are configured

**Alternatives considered:**
- *Test doubles*: Masks async patterns that may cause the bug (REJECTED)
- *Hybrid (real LLM, fake embedder)*: Embedder asyncio could also be involved; all-or-nothing is more reliable

### Decision 3: Isolated SQLite database per test session

**Chosen: Unique random SQLite file per test session**

Following the existing pattern (`setup_test_db`), the backend subprocess receives `DATABASE_URL` pointing to a unique SQLite file. The conftest fixture generates this path, starts the backend subprocess on a random port (setting `DATABASE_URL` in the env), and cleans up the DB + kills the process on teardown.

### Decision 4: Rendering bug fix

**Chosen: Fix the answer-content guard + ensure answers survive full-page rerun**

Based on code analysis, the rendering path has specific issues:

1. **Inline rendering in `poll_query_task()` (lines 625-637)**: Renders answers during polling using `st.chat_message()` + `st.markdown()`. These renders ARE visible during the current script run, but on the NEXT `st.rerun()` (line 715), the inline-rendered content is gone unless it was persisted to `st.session_state.messages`.

2. **The session state append guard (line 640)**: `cache_key = f"rendered_{task_id}_{r['backend']}"` prevents duplicate appends. After the first successful poll that returns an answer, the answer IS appended. On subsequent reruns, the top message loop (line 465) renders it from state. This should work.

3. **Likely root cause — the `status == "completed"` cleanup race**: When the status transitions from "processing" directly to "completed" in a single poll, the inline rendering in the `elif r.get("answer"):` branch (line 618) happens BEFORE the `status == "completed"` cleanup block (line 681). The cleanup then clears `task_started`, and calls `st.rerun()`. On the NEXT rerun, `task_started` is False → `poll_query_task()` returns immediately. The top message loop should render from `st.session_state.messages`. **If the answer was never appended** (because the results arrived in the same poll that returned "completed" and the append happened on a different code path), the answer would be lost.

4. **Fix**: Restructure the completion flow so results are always in `st.session_state.messages` before cleanup, and guarantee answers survive the final rerun by either:
   - Moving the `st.session_state.messages.append()` BEFORE the inline render, using a two-phase commit
   - Ensuring the status="completed" handler does NOT call `st.rerun()` if results haven't been appended yet
   - Adding a re-render safety net in the top message loop that doesn't rely on `cache_key`

The specific fix will be determined during implementation by adding logging to trace the exact sequence of events when the bug manifests.

### Decision 5: Test assertion approach

**Chosen: DOM text content assertion via `page.locator`**

The test will:
1. Log in via the Streamlit UI (fill email/password → click Login)
2. Navigate to the Documents page
3. Select the `api-docs` chunking strategy from the strategy dropdown
4. Upload `tests/docs/test docx.docx` (the docx is structured as API documentation)
5. Wait for processing to complete (poll for status indicator text like "completed" or no longer showing "processing")
6. Navigate to the Chat page
7. Select the processed document in the sidebar
8. Type the question `"how to change logo?"` into the chat input and press Enter
9. Wait for the answer to appear in the DOM — look for assistant chat messages with non-empty text content
10. Since real models are used, assert that at least one assistant chat message exists with non-empty content (no canned string to match against)
11. Generous timeout: 180s (includes model lazy-loading on first query + real inference time)

The `api-docs` strategy processes the DOCX using the API-docs pipeline (table extraction, entity mapping for interfaces/enums/error_codes/records), which matches the document's structure. This is the same strategy used by the existing integration test for this document.

## Risks / Trade-offs

| Risk | Impact | Mitigation |
|------|--------|------------|
| Subprocess startup is slow (~5-10s for backend + streamlit) | Slow test startup | Session-scoped fixtures (start once per test run); mark with `@pytest.mark.slow` |
| Flaky subprocess lifecycle (zombie processes) | CI hangs or port conflicts | Use `subprocess.Popen` with `atexit` + fixture teardown cleanup; kill process group; use random ports (`port=0`) |
| Streamlit headless mode differs from real browser | Tests pass but bug persists in real browser | Use Playwright's headless Chromium which is identical to headed; accept minor rendering differences |
| Real model inference is slow (30-120s per query) | Test is slow | Generous 180s timeouts; session-scoped fixtures prevent per-test overhead; `@pytest.mark.slow` |
| Model loading on first query blocks the event loop | First request timeout | Ensure frontend retries/waits; model only loads once (singleton) |
| MLX models require Apple Silicon | Test cannot run on non-Mac CI | Accept as current limitation; consider CPU fallback or CI runner choice in future |
| First run requires model download (~1.5GB) | Setup time | Already cached locally from development use; `HF_HUB_OFFLINE=1` skips re-download |
