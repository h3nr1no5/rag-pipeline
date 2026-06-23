## 1. Fix BM25 camelCase tokenization

- [ ] 1.1 Add `_tokenize(text: str) -> list[str]` helper to `ApiBm25Index` that applies camelCase regex splitting before `lower().split()` — handles both `([A-Z]+)([A-Z][a-z])` (acronym+word) and `([a-z])([A-Z])` (lower→upper) boundaries
- [ ] 1.2 Replace inline `keyword_text.lower().split()` in `add_graph()` (line 65) with the new `_tokenize()` helper
- [ ] 1.3 Replace inline `text.lower().split()` in `add_graph()` tokenized_corpus construction (line 68) with `_tokenize()`
- [ ] 1.4 Replace inline `query.lower().split()` in `search()` (line 91) with `_tokenize()` — ensures symmetrical tokenization between index and query
- [ ] 1.5 Add `import re` to `bm25_index.py` if not already present

## 2. Wire `load_all_from_db()` into application startup

- [ ] 2.1 In `src/api/main.py` `lifespan` startup, add a block after the existing `api_docs_enabled` DSPy configuration (before `yield`) that calls `get_manager()` and `await manager.load_all_from_db(session)`
- [ ] 2.2 Guard the call with `if settings.api_docs_enabled:` — no-op when API docs are disabled
- [ ] 2.3 Verify the import of `get_manager` from `src.domain.rag.api_docs.manager` does not create circular imports

## 3. Add tests

- [ ] 3.1 Add unit test to `tests/unit/` (or an existing api_docs test file): verify `_tokenize()` splits `"StartSelection"` → `["start", "selection"]`, `"PDFParser"` → `["pdf", "parser"]`, `"initialize"` → `["initialize"]`, `"parseXML"` → `["parse", "xml"]`
- [ ] 3.2 Add integration test: create a BM25 index with a `StartSelection` method chunk, query `"how to start selection"`, assert chunk is in top results
- [ ] 3.3 Add integration test: start app with `api_docs_enabled=True`, verify `load_all_from_db` is called and indexes are available without re-ingestion
