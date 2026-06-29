## Why

The `fix-rag-query-freezing` change added 4 slow E2E tests for the RAG pipelines, but these tests pass with meaningless canned answers because `seed_singletons` (a session-scoped, autouse fixture in `tests/integration/conftest.py`) silently replaces the real LLM and Embedder with test doubles (`TestLLM` and `TestEmbedder`). The tests assert `len(result["answer"]) > 0` which trivially passes with the fixed TestLLM string — they never verify the answer actually contains content from the uploaded document. Additionally, the Streamlit frontend silently returns "Please login to ask questions" when the JWT token is missing from session state, rather than raising an error, masking auth failures.

## What Changes

1. **Exempt slow E2E tests from `seed_singletons`** — Restructure the fixture hierarchy so that the 4 `@pytest.mark.slow` E2E tests load real LLM/embedder models (or their own dedicated test doubles) instead of being contaminated by the session-scoped `seed_singletons` fixture.

2. **Strengthen E2E test assertions** — Replace the trivially-passing `len(result["answer"]) > 0` check with assertions that verify the answer is actually about the document content (e.g., contains key terms from the document, is not a canned/fallback response).

3. **Fix frontend silent auth failure** — In `client/utils/query.py`, raise/return an explicit error instead of silently returning `{"answer": "Please login to ask questions.", ...}` which looks like a valid successful response.

## Capabilities

### New Capabilities
- `e2e-rag-test-integrity`: Ensures slow E2E RAG integration tests run with real model instances (not test doubles) and verify the answer actually contains meaningful content about the uploaded document.

### Modified Capabilities
- *(None — the existing `async-rag-initialization` spec from `fix-rag-query-freezing` has no requirement-level changes; this is test infrastructure and frontend hardening.)*

## Impact

- `tests/integration/conftest.py` — `seed_singletons` fixture scope/behavior needs to change so it doesn't apply to slow E2E tests
- `tests/integration/test_rag_pipelines_e2e.py` — Strengthen assertions to verify meaningful answers (not just non-empty)
- `tests/doubles/llm.py` — May need a configurable TestLLM variant that simulates real model behavior more realistically
- `client/utils/query.py` — Change all 4 functions to raise or return a clear error state instead of silently returning a "Please login" answer
- `client/pages/3_💬_Chat.py` — Handle the new error state from query functions
- No new dependencies, no API contract changes, no database schema changes
