## Why

The integration test suite has **9+ flaky failures** that pass when run individually but fail in batch due to test-isolation gaps. These failures erode trust in CI results, waste developer time on re-runs, and create "it works on my machine" friction.

Three root causes account for all flakiness:

1. **readonly database (4 tests)**: When tests are run sequentially, the previous test's async SQLAlchemy engine may still hold a write lock on the `.db` file when the next test's `setup_test_db` tears down and recreates it. `engine.dispose()` is not awaited before file removal.

2. **401 Not Authenticated (2 tests)**: Seven+ test files each define their own `auth_client` fixture. At least one variant has a bug where the login response token is discarded when signup returns 400 (UUID collision on retry). The client yields without an `Authorization` header.

3. **MPNet segfault (1 test)**: The SentenceTransformer model leaves stale GPU/CPU tensor references across test boundaries. When many embedding operations run in sequence, memory pressure triggers a segfault in `transformers` C extension code.

### Existing Context

Prior changes (`test-fixes`, `resolve-test-failures`) addressed WarmupState seeding, lifespan gaps, and model-loading async issues. Those fixes eliminated ~113 hard failures but left these flaky races unresolved. The `test-hygiene` change (archived) started consolidating fixtures and cleanup but did not complete the auth_client deduplication or engine lifecycle fix.

### Evidence

| Test | Failure Pattern | Frequency |
|------|----------------|-----------|
| `test_documents::test_upload_pdf_document` | `readonly database` | ~2/10 batch runs |
| `test_documents::test_upload_multiple_documents` | `401 Not Authenticated` | ~3/10 batch runs |
| `test_documents_integration::test_upload_python_guide` | `readonly database` | ~1/10 batch runs |
| `test_documents_integration::test_document_processing_status_updates` | `readonly database` | ~1/10 batch runs |
| `test_query_flow::test_list_selected_documents` | `401 Not Authenticated` | ~2/10 batch runs |
| `test_langchain_verification::TestLangChainStreaming` (2 tests) | State pollution | ~2/10 batch runs |
| `test_rag_pipelines_e2e::test_cosine_pipeline` | `readonly database` | ~3/10 batch runs |
| `test_clear_embeddings::test_clear_embeddings_then_reprocess` | `readonly database` | ~4/10 batch runs |
| `test_documents::test_upload_yaml_api_document` | MPNet segfault | ~1/10 batch runs |

## What Changes

- **`setup_test_db` engine lifecycle fix**: Add `await engine.dispose()` to the teardown phase in `tests/conftest.py`, ensuring the old engine's write lock is fully released before the DB file is removed. Add `gc.collect()` after disposal as a safety net.

- **Single canonical `auth_client` fixture in `tests/integration/conftest.py`**: Move the authoritative auth_client into integration conftest with an idempotent signup-then-always-login pattern (login token is always captured). Delete all 6+ duplicate definitions across individual test files.

- **GC collection after embedding-heavy tests**: Add a post-test `gc.collect()` hook in conftest, targeted at tests that load the embedding model, to free tensor references and prevent segfault accumulation.

- **Document existing `@pytest.mark.flaky`**: Add the `flaky` marker to the 9 tests above with a reason string, so the test taxonomy is honest about known instability while fixes are verified.

## Capabilities

### New Capabilities
- `test-db-engine-lifecycle`: Deterministic async engine disposal with awaited `engine.dispose()` before DB file removal in `setup_test_db` teardown
- `test-auth-client-canonical`: Single idempotent `auth_client` fixture in integration conftest — signup-first, always-login, always-capture-token. Zero ambiguity.
- `test-embedding-gc-hook`: Post-test garbage collection for embedding-heavy tests to prevent MPNet segfault from tensor accumulation

### Modified Capabilities
- `test-isolation` (from `test-hygiene` change): Strengthened to cover engine lifecycle, auth token lifecycle, and memory pressure

### Removed Capabilities
- 6+ duplicate `auth_client` fixture definitions removed from individual test files

## Impact

- **`tests/conftest.py`**: Add `await engine.dispose()` + `gc.collect()` in `setup_test_db` teardown
- **`tests/integration/conftest.py`**: Add canonical `auth_client` fixture, delete all duplicates from individual test files
- **`tests/integration/test_auth_flow.py`**: Delete duplicate `auth_client` (contained the bug)
- **`tests/integration/test_documents.py`**: Delete duplicate `auth_client`
- **`tests/integration/test_documents_integration.py`**: Delete duplicate `auth_client`
- **`tests/integration/test_query_flow.py`**: Delete duplicate `auth_client`
- **`tests/integration/test_cache_bug.py`**: Delete duplicate `auth_client`
- **`tests/integration/test_clear_embeddings.py`**: Delete duplicate `auth_client`
- **`tests/integration/test_score_normalization.py`**: Delete duplicate `auth_client`
- **Flaky tests**: Each gets `@pytest.mark.flaky(reason="...")` marker while fix is verified
- **No production code changes**: All changes are in test infrastructure only
