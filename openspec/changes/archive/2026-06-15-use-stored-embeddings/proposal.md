## Why

The RAG pipeline has a critical performance and correctness bug: **query-time re-embedding**. At query time, both the main cosine retrieval path and the LangChain path re-compute embeddings from raw chunk content instead of using the pre-stored `Chunk.embedding` vectors. This means:

1. The augmented text computed during document processing (including COM API metadata and optional hyperlink context) is **never used** at query time — the stored embedding that was built from augmented text is ignored.
2. Unnecessary compute cost: embeddings are re-computed on every query instead of once during ingestion.
3. The hyperlink-aware feature's value is nullified because the embeddings that capture link context are discarded at retrieval time.

Additionally, three related bugs were discovered:
- String/int key mismatch in `link_target_contents` dictionary prevents internal link target content from resolving in augmented text.
- Main cosine retrieval path has no `min_relevance_score` filter, returning low-relevance chunks.
- Recursive chunking path doesn't inject COM API metadata into embeddings (unlike the semantic path).

Fix now because ongoing experiments with response quality are being confounded by this discrepancy between what was processed and what is retrieved.

## What Changes

- **Main cosine retrieval path**: Replace `embedder.embed_texts([c.content...])` with direct cosine similarity against stored `Chunk.embedding` vectors. Add SQL filter to skip chunks without embeddings.
- **LangChain retrieval path**: Same fix — use stored embeddings instead of re-embedding chunk content at query time.
- **Augmentation bug fix**: Fix `str`/`int` key mismatch in `link_target_contents` dictionary (`augmentation.py`).
- **Relevance threshold**: Add `min_relevance_score` configurable filter in main cosine retrieval path (matching LangChain's existing behavior).
- **Recursive path consistency**: Always call `build_augmented_text()` in the recursive chunking path, matching the semantic path behavior.
- **`use_hyperlinks` default**: Change default to `false` (was already done in `entities.py`, but this formally establishes it).

## Capabilities

### New Capabilities
- `retrieval`: Query-time retrieval using pre-stored embeddings instead of on-the-fly re-embedding

### Modified Capabilities
- *(No existing specs are changing — this is a new capability.)*

## Impact

- **`src/api/routes/query/_retrieval.py`**: `retrieve_chunks()` — use `Chunk.embedding` directly, add `.isnot(None)` filter
- **`src/api/routes/query/routes.py`**: LangChain path — pass stored embeddings instead of content for re-embedding
- **`src/pdf_semantic_chunking/augmentation.py`**: Fix `str(tid)` lookup in `build_augmented_text_with_links()`
- **`src/domain/services/processor.py`**: Recursive chunking path — call `build_augmented_text()` when `use_hyperlinks=False`
- **`src/core/config.py`**: `min_relevance_score` already exists in config
- **Tests**: Update `_retrieval.py` tests, LangChain retrieval tests, augmentation tests, processor tests
