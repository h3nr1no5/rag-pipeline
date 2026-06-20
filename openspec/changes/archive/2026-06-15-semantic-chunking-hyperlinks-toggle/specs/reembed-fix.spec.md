# Re-Embedding Fix: Use Stored Embeddings at Query Time

## Overview

**Problem**: `retrieve_chunks()` in the main cosine path and the LangChain path both re-embed `Chunk.content` from scratch at query time (`embedder.embed_texts(chunk_texts)`), completely ignoring the pre-stored `Chunk.embedding` that was computed from augmented text during document processing. This means:

1. All link-aware augmentation during processing is wasted — retrieval always compares against raw content embeddings
2. The system pays the cost of re-embedding **N** chunks on every query (N = total chunks across all queried documents)
3. Results differ from what the stored embeddings would produce, causing inconsistent retrieval quality

**Goal**: All query-time retrieval paths MUST use stored `Chunk.embedding` exclusively. Never re-embed at query time.

---

## Fix #1: Main Cosine Path — `_retrieval.py`

**File**: `src/api/routes/query/_retrieval.py`

**Current behavior** (lines 198-204):
```python
chunk_texts = [c.content for c in all_chunks]
chunk_embeddings = await embedder.embed_texts(chunk_texts)
```

**Required change**: Query chunks with non-null embeddings and use the stored `chunk.embedding` field directly:
```python
# Instead of re-embedding, use stored embeddings from the database
chunks_with_embeddings = [(c, c.embedding) for c in all_chunks if c.embedding is not None]
if not chunks_with_embeddings:
    logger.warning("No chunks with stored embeddings found")
    return []
chunk_embeddings = [emb for _, emb in chunks_with_embeddings]
all_chunks = [c for c, _ in chunks_with_embeddings]
```

**SQL query change** (line 185-187): Add `Chunk.embedding.isnot(None)` filter:
```python
chunk_results = await db.execute(
    select(Chunk).where(
        Chunk.document_id.in_(document_ids),
        Chunk.embedding.isnot(None),
    )
)
```

**Logic change**: Remove `embedder` usage from `retrieve_chunks()` entirely — it's only needed for the query embedding, which is a single text. The embedder for the query is still needed but the `embedder.embed_texts()` call for ALL chunks is removed.

---

## Fix #2: LangChain Path — `routes.py`

**File**: `src/api/routes/query/routes.py`

**Current behavior** (lines 436-439 in non-streaming, 616-618 in streaming):
```python
chunk_texts = [c.content for c in all_chunks]
chunk_embeddings = await embedder.embed_texts(chunk_texts)
```

**Required change**: Use stored embeddings instead:
```python
# Use stored embeddings from DB
chunks_with_emb = [c for c in all_chunks if c.embedding is not None]
if not chunks_with_emb:
    raise HTTPException(status_code=404, detail="No chunks with embeddings found")
chunk_texts = [c.content for c in chunks_with_emb]
chunk_embeddings = [c.embedding for c in chunks_with_emb]
all_chunks = chunks_with_emb  # Use filtered list
```

**SQL query change** (lines 425-428, 606-609): Add `Chunk.embedding.isnot(None)` filter.

**SQLAlchemy filter approach**: Since LangChain retrieves ALL chunks unconditionally, the most consistent fix is to filter in Python after retrieving, and add the SQL filter for efficiency.

---

## Fix #3: str/int Key Mismatch — `augmentation.py` + `processor.py`

**File**: `src/pdf_semantic_chunking/augmentation.py`

**Current bug** (lines 94-95):
```python
for tid in target_ids:          # tid is int from target_chunk_ids
    target_text = contents.get(tid)  # contents keys are str → ALWAYS None
```

The `link_target_contents` dict is built with **string keys** in `processor.py` (line 241: `str(other_chunk.get("chunk_index", ""))`) but looked up with **integer keys** in `augmentation.py` (line 81: `target_ids = link.get("target_chunk_ids") or []` which returns integers).

**Required change in `augmentation.py`**: Convert `tid` to string for lookup:
```python
for tid in target_ids:
    target_text = contents.get(str(tid))  # str() for lookup
```

**Same fix needed for backlinks** (line 131): The `source_id` from backlinks is also an integer (stored as `source_chunk_id`). When it's an int, convert:
```python
source_text = contents.get(str(source_id) if isinstance(source_id, int) else source_id)
```

---

## Fix #4: `min_relevance_score` Threshold — Main Cosine Path

**File**: `src/api/routes/query/_retrieval.py`

**Current behavior**: Cosine similarity chunk scores are used as-is without any minimum relevance threshold. Low-quality matches are included in results sent to the LLM.

**Required change**: After computing `top_chunks`, apply a relevance threshold:
```python
from ....core.config import get_settings
settings = get_settings()

# Apply relevance threshold
top_chunks = [(c, s) for c, s in top_chunks if s >= settings.min_relevance_score]
if not top_chunks:
    logger.warning("No chunks above relevance threshold")
    return []
```

This aligns the main cosine path with the LangChain path (which already applies `min_relevance_score` at `retrieval_langchain.py` line 403).

---

## Fix #5: Recursive Path Asymmetry — `processor.py`

**File**: `src/domain/services/processor.py`

**Current behavior** (lines 359-367): When `use_hyperlinks=False` in the recursive path, the raw `content` is used as `text_to_embed` — `build_augmented_text()` is NOT called. The semantic path always calls at least `build_augmented_text()` (which injects COM API metadata and section hierarchy).

**Required change**: Always use `build_augmented_text()` in the recursive path when hyperlinks are disabled (matching semantic path behavior):
```python
from ...pdf_semantic_chunking.augmentation import build_augmented_text, build_augmented_text_with_links

# [...]

text_to_embed = content
if use_hyperlinks and (metadata.get("links") or metadata.get("backlinks")):
    # [...] build link_target_contents
    text_to_embed = build_augmented_text_with_links(content, metadata, link_target_contents)
else:
    text_to_embed = build_augmented_text(content, metadata)  # Always augment
```

---

## Side-Effect: `_retrieval.py` No Longer Needs `get_embedder`

With Fix #1, the embedder is only needed for a single query embedding in `retrieve_chunks()`. The current code imports and calls `get_embedder()` at lines 152, 157. The function still needs the embedder for `embedder.embed_text(question)` but the `embedder.embed_texts(chunk_texts)` call is removed.

The embedder singleton load remains but is now only doing query embedding — a much lighter operation.

---

## Implementation Plan

| # | File | Change | Priority |
|---|------|--------|----------|
| 1a | `src/api/routes/query/_retrieval.py` | Add `Chunk.embedding.isnot(None)` to SQL query, filter by non-null embeddings | High |
| 1b | `src/api/routes/query/_retrieval.py` | Replace `embedder.embed_texts()` with stored `c.embedding` usage | High |
| 2a | `src/api/routes/query/routes.py` | LangChain non-streaming: filter chunks with embeddings, use stored `c.embedding` | High |
| 2b | `src/api/routes/query/routes.py` | LangChain streaming: same fix as 2a | High |
| 3 | `src/pdf_semantic_chunking/augmentation.py` | Fix str/int key mismatch in `build_augmented_text_with_links()` | High |
| 4 | `src/api/routes/query/_retrieval.py` | Add `min_relevance_score` threshold filter | Medium |
| 5 | `src/domain/services/processor.py` | Always use `build_augmented_text()` in recursive path | Medium |

---

## Testing Strategy

1. **Unit test** for `augmentation.py`: Verify str/int key fix works — create `link_target_contents` with string keys, pass int `target_chunk_ids`, confirm content is resolved
2. **Integration test** for `_retrieval.py`: Create chunks with known embeddings, verify `retrieve_chunks()` uses stored embeddings (not re-embed)
3. **Integration test** for LangChain path: Same as above for the LangChain route
4. **Performance test**: Verify query latency drops proportionally to chunk count (N embeddings saved per query)

---

## Rollback Safety

- **Chunks without embeddings** (e.g., from processing errors or older documents): The `isnot(None)` filter means these chunks are silently excluded from retrieval. If ALL chunks lack embeddings, a `404 No relevant content` response is returned (existing behavior in routes.py).
- **Mixed documents**: Some with embeddings, some without: Only document_ids with embeddings return results.
