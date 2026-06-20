## 1. Fix Embeddings Interface Conformance

- [x] 1.1 Add `Embeddings` base class import to `retrieval_langchain.py`
- [x] 1.2 Make `_ProjectEmbeddingFunction` inherit from `langchain_core.embeddings.Embeddings`
- [x] 1.3 Add `embed_documents()` method stub that raises `NotImplementedError` (already existed)

## 2. Verification

- [x] 2.1 Integration tests pass: 228/228 unit tests, 14/15 LangChain verification tests (1 pre-existing SQLite issue). `test_successful_query`, `test_streaming_success`, `test_cached_response_returns_quickly` all pass.
- [ ] 2.2 Manual frontend test: skipped — fix validated by automated tests. Pre-existing DB/permission issues prevent full end-to-end test.
