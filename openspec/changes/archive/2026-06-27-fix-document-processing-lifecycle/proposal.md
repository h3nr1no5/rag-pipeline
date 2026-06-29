## Why

Documents uploaded to the RAG pipeline frequently get stuck in `status="pending"` forever because the server has no mechanism to recover pending work after a restart. Additionally, users receive no progress feedback during the ~16-second embedding model cold load, making the application appear hung. Profiling confirms three distinct root causes that together make the document processing lifecycle unreliable and opaque.

## What Changes

- Add a **pending-document recovery loop** on server startup so documents survive restarts
- Add **progress callback hooks** to the embedding index stage so the frontend receives status updates during model loading and batch encoding
- **Extend model warmup** to pre-load the embedding model (in addition to the existing LLM warmup), eliminating the cold-start penalty on first document after startup
- **Remove redundant `format_graph()` call** in `ApiEmbeddingIndex.add_graph()` when content is already populated
- Add a **performance regression test** that profiles the full pipeline against the real `axis com snippet.docx` fixture with timing budgets

## Capabilities

### New Capabilities
- `document-processing-lifecycle`: Reliable document processing that survives restarts, provides progress feedback during slow stages, and avoids redundant work

### Modified Capabilities
- *(No spec-level requirement changes — the fixes are additive and backward-compatible with existing specs)*

## Impact

- **Backend**: `src/api/main.py` (lifespan startup recovery + warmup extension), `src/domain/rag/api_docs/retrieval/embedding_index.py` (progress callback + redundant format removal), `src/domain/services/processor.py` (wire callback through pipeline)
- **Database**: No schema changes — existing `document.status` and `processing_step` columns are sufficient
- **Tests**: New unit tests for recovery, progress hooks, and format-skip logic; new integration performance test (`tests/integration/test_processing_perf.py`)
- **No breaking changes**: All additions are backward-compatible; the existing API contract is preserved
