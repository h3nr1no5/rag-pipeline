## Context

The API documentation RAG pipeline (`src/domain/rag/api_docs/`) uses a `HybridRetriever` with BM25 keyword search and FAISS embedding search. Two bugs degrade retrieval quality to zero for common query patterns:

**Bug A — BM25 camelCase tokenization** (`bm25_index.py`): The tokenizer `text.lower().split()` only splits on whitespace. A method named `StartSelection` becomes the single token `"startselection"`. A user query like "how to start selection" becomes `["how", "to", "start", "selection"]`. BM25 does exact token matching, so neither "start" nor "selection" matches "startselection" — the BM25 index contributes zero useful results.

**Bug B — `load_all_from_db` never called at startup** (`main.py`): `ApiDocPipelineManager.load_all_from_db()` was implemented (manager.py:130) as part of a previous change (api-docs-frontend-integration) but was never wired into the application's `lifespan` startup. After a server restart, the in-memory `_indexed_docs` dict is empty. The first query triggers `_run_on_the_fly_ingestion()` which re-processes the original file — fragile if temp files were cleaned up, and redundant since the `ApiDocIndex` table already has the persisted data.

## Goals / Non-Goals

**Goals:**
- Fix BM25 tokenization so camelCase method names like `StartSelection` match user queries that split them into separate words ("start", "selection")
- Ensure API doc indexes survive server restarts by calling `load_all_from_db()` during startup
- Maintain backward compatibility with existing indexed data
- Add tests that verify the fix with realistic query scenarios

**Non-Goals:**
- No changes to the embedding index (FAISS) or the RRF fusion logic
- No changes to the DSPy LLM answer generation
- No changes to the main RAG pipeline (`Chunk` table backends)
- No new dependencies

## Decisions

### Decision 1: Regex-based camelCase tokenization for BM25

**Option A (selected)**: Apply a two-phase regex before splitting on whitespace:
1. `re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', text)` — splits acronym+word boundaries (`PDFParser` → `PDF Parser`)
2. `re.sub(r'([a-z])([A-Z])', r'\1 \2', text)` — splits lowercase→uppercase boundaries (`StartSelection` → `Start Selection`)
3. Then `.lower().split()` as before

This converts `StartSelection` → tokens `["start", "selection"]` in the index. The same transformation is applied to the query at search time, so the match is symmetrical.

**Option B (rejected)**: Use a dedicated tokenizer like `spacy` or `nltk` — overkill for a single regex, adds a heavy dependency for one line of preprocessing.

**Option C (rejected)**: Add n-gram indexing (character trigrams) — would increase index size 10x and slow down searches. Unnecessary when a simple regex handles the actual pattern.

### Decision 2: Add `load_all_from_db()` call to `lifespan` startup

**Approach**: In `src/api/main.py`, after the existing startup logic (strategy seeding, schema migration), import `get_manager` and call:
```python
if settings.api_docs_enabled:
    from src.domain.rag.api_docs.manager import get_manager
    manager = get_manager()
    async with async_session_maker() as session:
        await manager.load_all_from_db(session)
```

This goes after the existing `api_docs_enabled` block that configures DSPy (around line 326, before `yield`). This ensures:
- The singleton manager is reused (not a new instance)
- Data is loaded before the first request arrives
- If `api_docs_enabled` is False, the call is skipped (no unnecessary DB query)

**Alternative considered**: Lazy-load on first query — no, that's what's already happening (`_run_on_the_fly_ingestion`). The point is to avoid it.

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| Tokenization change produces different BM25 corpus hashes, changing results for existing queries | This is fine — results *should* improve. Index is rebuilt on next `add_graph()` call |
| `load_all_from_db()` could slow startup if many docs are indexed | It's a simple DB query + in-memory graph rebuild. With dozens of documents, this should be <1s. Logged at INFO level for observability |
| `async_session` lifecycle — using `async_session_maker()` context manager in startup ensures session is closed | Already handled by the `async with` pattern |
| Existing persisted BM25 index data in `ApiDocIndex` table doesn't store token-level data — only graph_data + embeddings | Correct — the BM25 index is rebuilt from `graph_data` on `load_from_db()`. Tokenization change applies automatically |
