## Why

The previous change (`fix-flaky-test-isolation`) identified and eliminated **6 duplicate `auth_client` fixtures** from integration test files, but its security review flagged **17 remaining files** with copy-pasted `auth_client` definitions that shadow the canonical fixture in `tests/integration/conftest.py`. Each duplicate represents a maintenance burden, a potential future bug (the buggy if/elif pattern from `test_auth_flow.py` is present in many of them), and architectural drift. With the canonical fixture now proven to be idempotent and reliable, there is zero reason to keep any duplicates.

## What Changes

- **Delete 17 duplicate `auth_client` fixture definitions** from integration test files and `real_models/` subdirectory
- **No changes to `tests/integration/conftest.py`** — the canonical fixture (lines 102–121) remains the single source of truth
- **No changes to any test logic** — all tests already import the canonical `auth_client` via pytest conftest resolution; deleting the local definition simply lifts the shadow
- **Verify no regressions**: full integration test suite pass; confirm all 17 files use the inherited canonical fixture

## Capabilities

### New Capabilities
*(none — no new capabilities, pure removal of duplicate code)*

### Modified Capabilities
- `test-auth-client-canonical` (from `fix-flaky-test-isolation` change): Extended coverage from 6 deleted duplicates to 23 total (6 done + 17 now). The canonical fixture is now the ONLY `auth_client` definition in the entire integration test tree.

### Removed Capabilities
- 17 duplicate `async def auth_client(setup_test_db)` fixture definitions from individual test files

## Impact

- **17 test files** across `tests/integration/` and `tests/integration/real_models/` — each gets its `auth_client` fixture definition deleted
- **No production code** changes
- **No spec changes** — pure test infrastructure cleanup
- **Dependency**: the canonical `auth_client` fixture in `tests/integration/conftest.py` must be correct (already verified in prior change)

### Files to modify

1. `tests/integration/test_api_docs_e2e.py` — line 45
2. `tests/integration/test_chat_e2e.py` — line 14
3. `tests/integration/test_chat_integration.py` — line 16
4. `tests/integration/test_cosine_verification.py` — line 23
5. `tests/integration/test_documents_progress.py` — line 17
6. `tests/integration/test_embedding_presence.py` — line 13
7. `tests/integration/test_langchain_verification.py` — line 28
8. `tests/integration/test_langchain_verification_integration.py` — line 24
9. `tests/integration/test_link_aware_rag.py` — line 31
10. `tests/integration/test_llamaindex.py` — line 30
11. `tests/integration/test_pdf_integration.py` — line 13
12. `tests/integration/test_processing_config.py` — line 25
13. `tests/integration/test_rag_pipelines_e2e.py` — line 93
14. `tests/integration/test_strategies.py` — line 11
15. `tests/integration/real_models/conftest.py` — line 32
16. `tests/integration/real_models/test_langchain_integration.py` — line 27
17. `tests/integration/real_models/test_llamaindex_integration.py` — line 27
