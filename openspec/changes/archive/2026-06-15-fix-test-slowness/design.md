## Context

The test suite runs 775 tests (~10 min). A waste audit identified ~700s of avoidable overhead. The three biggest contributors:

1. **Root conftest autouse fixtures** run for ALL 775 tests — including 667 tests in `tests/unit/` and `tests/pdf_semantic_chunking/` that never use a database, upload directory, or background tasks. Each fixture creates a SQLite engine, runs migrations, seeds data, and tears down (~240s total waste).

2. **Sleep-based polling** — 7 copy-pasted `upload_and_wait_for_document()` helpers poll at 1s granularity with 2s "settling" sleeps. 34 upload-and-wait calls across 7 test files waste ~190s.

3. **Per-chunk DB commits + per-chunk embedding** in `processor.py` — `await session.commit()` inside the chunk loop (12+ commits per document instead of 2-3), plus `embed_text()` per chunk instead of `embed_texts()` batch. Adds ~100s to document processing time, which directly inflates polling wait times.

Additional smaller waste: real LLM loading (120s), real uvicorn subprocess (10s), MonitoringMiddleware logging (~10s), standalone sleeps (~12s), duplicate cleanup and module-level heavy imports (~3s).

**Constraint**: All changes must preserve test correctness. The existing test coverage (771 passing, 4 xfail) must not regress. No functional API behavior changes.

## Goals / Non-Goals

**Goals:**
- Reduce test suite runtime from ~10 min to ~3 min (70% reduction)
- Eliminate copy-pasted test helper code (7 upload_and_wait → 1 shared helper)
- Centralize auth_client fixture (16 local definitions → 1 shared fixture)
- Reduce DB transactions in processor.py from O(chunks) to O(1) per document
- Reduce model inference calls from O(chunks) to O(1) per document
- Remove code that only exists to compensate for slow polling (standalone sleeps)
- No regressions in test correctness or code coverage

**Non-Goals:**
- Mocking the embedding model or LLM in integration tests (would reduce coverage confidence)
- Changing the database isolation strategy (per-test SQLite DBs stay)
- Refactoring the entire test suite architecture
- Adding new test coverage or test types
- CI/CD pipeline changes or Docker configuration

## Decisions

### D1: Override autouse fixtures at conftest level (not markers or conditional logic)
**Decision**: Create `tests/unit/conftest.py` and edit `tests/pdf_semantic_chunking/conftest.py` with no-op overrides of `setup_test_db`, `clean_uploads_dir`, and `cancel_background_tasks`. Pytest naturally picks the most specific conftest.
**Alternatives considered**:
- **Conditional skip inside fixture**: Check `os.path.basename(pytest.config.invocation_params.dir)` to skip. Fragile, couples the fixture to directory structure, and requires changing the root fixture (riskier).
- **`@pytest.mark.no_db` marker**: Would require marking every test manually. Brittle, easy to forget.
- **Why this wins**: Leverages pytest's built-in conftest scoping. Zero test file changes needed. The fixture override is explicit and visible in the directory.

### D2: 0.1s poll interval with no settling sleep
**Decision**: Use 0.1s `poll_interval` in the shared `wait_for_document()` helper with no extra sleep after completion.
**Alternatives considered**:
- **Event-based notification**: Could use an `asyncio.Event` or channel to signal completion. Would require injecting signaling into processor.py — architectural coupling for test infra.
- **Why this wins**: 0.1s polling is ~1-2 extra HTTP calls per document (cheap). No production code changes needed. Simple, reliable, and decoupled.

### D3: Remove per-chunk commits in processor.py (keep progress commits)
**Decision**: Remove `await session.commit()` from lines 383 and 402 (per-chunk save commits). Keep the progress-update commits at lines 261, 273, 414 and the final status commit.
**Risk mitigation**: The session tracks all modifications. A single post-loop commit flushes everything atomically. If processing crashes mid-loop, partial chunks are lost — this is the same behavior as today (no savepoint logic exists).
**Alternatives considered**:
- **Batch every N chunks**: Commit every 10 chunks. More complex, marginal benefit over single commit.
- **Why this wins**: Simplest change. Maximum savings. Acceptable risk for a single-process async document processor.

### D4: Batch embedding with `embed_texts()` not `embed_text()`
**Decision**: Collect all chunk texts, call `embedder.embed_texts()` once, assign embeddings back.
**Rationale**: `EmbedderService` already has `embed_texts()` (line 48 of `embedding.py`). Sentence-transformers `encode()` batches internally — processing 20 texts takes roughly the same time as 1 text.
**Alternative**: Parallel `asyncio.gather()` on individual `embed_text()` calls. Adds complexity, doesn't leverage batch encoding optimization in sentence-transformers.

### D5: Guard `test_llm_loading.py` behind `RUN_LLM_TESTS` env var
**Decision**: Add `@pytest.mark.skipif(not os.environ.get("RUN_LLM_TESTS"), ...)` to the test file.
**Rationale**: This test exists to verify the LLM model downloads and loads correctly. It's a deployment verification, not a regression test. The 500MB model and 120s timeout are appropriate for that purpose, but shouldn't run on every test invocation.
**Alternative**: Mark `@pytest.mark.slow` and configure `pytest.ini` to skip slow tests. Less explicit about the specific environmental requirement.

### D6: Disable MonitoringMiddleware via env var, not mock
**Decision**: Gate middleware registration on `os.getenv("TESTING")` in `src/api/main.py`.
**Alternative**: Mock or override the middleware in test conftest. More complex, requires `app.middleware_stack` manipulation. Environment check is simpler and matches the existing pattern of `asyncio_mode = "auto"` in `pytest.ini`.

### D7: Convert server smoke test to ASGITransport
**Decision**: Rewrite `test_server_smoke.py` to use `httpx.AsyncClient(transport=ASGITransport(app=app))`.
**Rationale**: Every other integration test uses this pattern. It's faster (no subprocess), more reliable (no port discovery), and tests the same endpoints. The only thing lost is the ability to detect uvicorn-specific startup failures — but those are uvicorn's responsibility, not ours.

## Risks / Trade-offs

- **[R1: Processor crash mid-loop → partial chunk loss]** → Same as current behavior. No regression. If this becomes a problem, add savepoint logic in a future change.
- **[R2: Batch embedding with embed_texts could mask per-chunk embedding errors]** → The current code catches exceptions per-chunk (lines 249, 381). With batching, one failed text in the batch could fail the whole batch. Mitigation: Wrap the batch call in try/except with fallback to per-chunk embedding.
- **[R3: Overriding autouse fixtures could hide cross-test contamination]** → The overrides are in directories where tests demonstrably don't use DB, uploads, or background tasks. Integration tests (which do need isolation) use the root conftest's fixtures unchanged.
- **[R4: Shared wait_for_document changes poll behavior across all tests]** → Reduced poll interval (0.1s vs 1s) means slightly more HTTP requests on average (~10-30 vs ~3-5). Each is a lightweight async call to an in-memory app. Acceptable trade-off for faster completion detection.
- **[R5: LLM test only runs when explicitly requested]** → Risk of broken LLM integration going undetected until deployment. Mitigation: Run the LLM test in CI as a separate job step (e.g., `RUN_LLM_TESTS=1 pytest tests/integration/test_llm_loading.py`).
