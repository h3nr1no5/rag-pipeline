## 1. Audit and pre-flight check

- [ ] 1.1 Run `grep -rn "async def auth_client" tests/integration/ | grep -v conftest.py` to confirm 17 duplicate fixtures exist (baseline)
- [ ] 1.2 Run `uv run pytest -m "not slow" -v --tb=short -q` to confirm green baseline before changes
- [ ] 1.3 Run `uv run ruff check tests/` to confirm clean lint baseline

## 2. Delete duplicate auth_client fixtures (test files in tests/integration/)

- [ ] 2.1 Delete `auth_client` from `tests/integration/test_api_docs_e2e.py` (line 45)
- [ ] 2.2 Delete `auth_client` from `tests/integration/test_chat_e2e.py` (line 14)
- [ ] 2.3 Delete `auth_client` from `tests/integration/test_chat_integration.py` (line 16)
- [ ] 2.4 Delete `auth_client` from `tests/integration/test_cosine_verification.py` (line 23)
- [ ] 2.5 Delete `auth_client` from `tests/integration/test_documents_progress.py` (line 17)
- [ ] 2.6 Delete `auth_client` from `tests/integration/test_embedding_presence.py` (line 13)
- [ ] 2.7 Delete `auth_client` from `tests/integration/test_langchain_verification.py` (line 28)
- [ ] 2.8 Delete `auth_client` from `tests/integration/test_langchain_verification_integration.py` (line 24)
- [ ] 2.9 Delete `auth_client` from `tests/integration/test_link_aware_rag.py` (line 31)
- [ ] 2.10 Delete `auth_client` from `tests/integration/test_llamaindex.py` (line 30)
- [ ] 2.11 Delete `auth_client` from `tests/integration/test_pdf_integration.py` (line 13)
- [ ] 2.12 Delete `auth_client` from `tests/integration/test_processing_config.py` (line 25)
- [ ] 2.13 Delete `auth_client` from `tests/integration/test_rag_pipelines_e2e.py` (line 93)
- [ ] 2.14 Delete `auth_client` from `tests/integration/test_strategies.py` (line 11)

## 3. Delete duplicate auth_client fixtures (real_models/ subdirectory)

- [ ] 3.1 Delete `auth_client` from `tests/integration/real_models/conftest.py` (line 32)
- [ ] 3.2 Delete `auth_client` from `tests/integration/real_models/test_langchain_integration.py` (line 27)
- [ ] 3.3 Delete `auth_client` from `tests/integration/real_models/test_llamaindex_integration.py` (line 27)

## 4. Verification

- [ ] 4.1 Confirm zero remaining duplicates: `grep -rn "async def auth_client" tests/integration/ | grep -v conftest.py` — expect empty output (only canonical in conftest.py)
- [ ] 4.2 Confirm canonical fixture is intact: `grep -n "async def auth_client" tests/integration/conftest.py` — expect line 102
- [ ] 4.3 Run all integration tests: `uv run pytest tests/integration/ -v --tb=short -q` — expect 0 failures
- [ ] 4.4 Run full suite (fast): `uv run pytest -m "not slow" -v --tb=short -q` — expect green
- [ ] 4.5 Run lint check: `uv run ruff check tests/` — expect clean
- [ ] 4.6 Run type check: `uv run mypy src/` — expect no regressions (test changes shouldn't affect mypy)

## 5. Cleanup

- [ ] 5.1 If any test file had a `client` fixture that depended on the local `auth_client`, verify it now correctly uses the canonical one (audit any test failures from 4.3–4.4)
- [ ] 5.2 Update AGENTS.md if any architectural decisions need to be documented
