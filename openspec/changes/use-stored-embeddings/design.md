## Context

The RAG pipeline processes documents through a pipeline: parse → chunk → augment text → embed → store. The augmentation step produces an "augmented text" (which may include COM API metadata and/or hyperlink context) that is **only used for embedding**. The original `Chunk.content` in the database remains unchanged.

**The bug**: At query time, both the main cosine path (`_retrieval.py`) and the LangChain path (`routes.py`) take `Chunk.content` and re-embed it from scratch. This means:

1. The stored `Chunk.embedding` (computed from augmented text containing COM API metadata, section hierarchy, and optional link context) is ignored.
2. Query-time retrieval compares against raw content embeddings instead of the richer augmented-text embeddings.
3. The hyperlink-aware feature's "Links To:" / "Referenced From:" augmentation is effectively wasted — retrieval never sees it.
4. Unnecessary compute: re-embedding N chunks on every query instead of a single query embedding.

Three additional issues were discovered during investigation:

- **Key type mismatch**: `augmentation.py` builds `link_target_contents` with `str` keys (from `str(chunk_index)`) but looks them up with `int` keys (`tid` from `target_chunk_ids`). Internal link target content is never resolved.
- **No relevance threshold**: The main cosine path returns top-k regardless of relevance, unlike LangChain path which has `min_relevance_score` filtering.
- **Recursive path inconsistency**: When `use_hyperlinks=False`, the recursive path skips `build_augmented_text()` entirely, missing COM API metadata injection that the semantic path always applies.

## Goals / Non-Goals

**Goals:**
- Use stored `Chunk.embedding` vectors at query time in all 3 RAG backends (cosine, LangChain, LlamaIndex)
- Fix the `str`/`int` key mismatch in link target content resolution
- Add `min_relevance_score` filtering to main cosine retrieval path
- Make recursive chunking path always use `build_augmented_text()` for COM API metadata
- Default `use_hyperlinks` to `false`
- All changes are backward-compatible for already-processed documents

**Non-Goals:**
- Adding cross-encoder re-ranking to the main cosine path (that's a separate optimization)
- Removing the hyperlink feature entirely (user indicated "will remove later")
- Changing the LlamaIndex backend (already correctly uses stored embeddings)
- Performance optimization beyond eliminating re-embedding

## Decisions

### D1: Use cosine similarity against stored embedding vectors

The main cosine path currently computes `query_embedding @ chunk_embedding` after determining chunk embeddings by re-embedding `c.content`. The fix: load pre-stored `Chunk.embedding` vectors and compute dot-product similarity directly.

```python
# Before (bug):
chunk_texts = [c.content for c in all_chunks]
chunk_embeddings = await embedder.embed_texts(chunk_texts)
query_embedding = await embedder.embed_query(query)
scores = cosine_similarity([query_embedding], chunk_embeddings)[0]

# After (fix):
query_embedding = await embedder.embed_query(query)
chunk_embeddings = [c.embedding for c in all_chunks if c.embedding is not None]
scores = cosine_similarity([query_embedding], chunk_embeddings)[0]
```

**Alternatives considered:**
- **SQL-level vector search**: Would require SQLite vector extension. Too invasive, not worth it.
- **FAISS index for all chunks**: Overkill for in-process RAG with moderate document sizes.
- **NumPy array with stacking**: Used for the batch cosine similarity — applied consistently.

**Rationale:** Minimal change, maximum correctness. Eliminates the discrepancy between which embeddings are stored and which are used.

### D2: SQL filter for chunks without embeddings

Add `Chunk.embedding.isnot(None)` filter to the query that loads chunks for retrieval. This ensures we never try to compute similarity against `None` vectors.

```python
# Before:
all_chunks = await db.execute(
    select(Chunk).where(Chunk.document_id == document_id)
)

# After:
all_chunks = await db.execute(
    select(Chunk).where(
        Chunk.document_id == document_id,
        Chunk.embedding.isnot(None)
    )
)
```

### D3: Fix link_target_contents key type

Change the lookup from `contents.get(tid)` to `contents.get(str(tid))` in `augmentation.py`. This is a one-line fix.

**Why not change the dict construction instead?** The dict is built in `processor.py` using `str(other_chunk.get("chunk_index", ""))`. Changing that would affect other potential uses. The lookup is the defect — fix it at the point of failure.

### D4: min_relevance_score for main cosine path

The config already has `settings.MIN_RELEVANCE_SCORE` (default 0.15). Apply it after score computation but before top-k selection:

```python
# After computing scores and before top-k:
min_score = settings.MIN_RELEVANCE_SCORE
filtered = [(chunk, score) for chunk, score in zip(all_chunks, scores) if score >= min_score]
# Then take top-k from filtered results
```

This matches the LangChain path behavior (`retrieval_langchain.py` line 403).

### D5: Recursive path always uses build_augmented_text()

In `processor.py`, the recursive path's "no hyperlinks" branch currently sends raw `chunk_info["content"]` to the embedder. Change it to call `build_augmented_text(chunk_info)` (same as the semantic path's base behavior).

```python
# Before (recursive, no hyperlinks):
texts_to_embed.append(chunk_info["content"])

# After (recursive, no hyperlinks):
texts_to_embed.append(build_augmented_text(chunk_info))
```

### D6: LangChain path uses stored embeddings

The LangChain path in `retrieval_langchain.py` receives pre-loaded chunks with embeddings from `routes.py`. The LangChain document constructor currently uses chunk content. Change it to pass the embedding vector so the FAISS index is built from stored vectors rather than re-computed.

The LangChain path assembles a local FAISS index from the returned chunks for hybrid retrieval. Instead of building embeddings from content, inject the pre-stored `chunk_embedding` directly into the FAISS index construction.

## Risks / Trade-offs

- **[Risk] Stale embeddings**: If the embedding model changes, stored embeddings become stale. **Mitigation**: Document re-processing is required when the model changes (no online migration).
- **[Risk] Chunks with null embedding**: If a document was processed before embeddings were computed (edge case), chunks will be silently skipped. **Mitigation**: The `.isnot(None)` filter means they're excluded; the system already should not produce chunks without embeddings, but this is a safety net.
- **[Trade-off] Memory**: Loading all embedding vectors into memory for similarity computation. Already the case with re-embedding (which also loads all content + computes embeddings). No regression.
- **[Trade-off] LangChain path still uses content for BM25**: The LangChain path does hybrid BM25+FAISS. BM25 still needs content text, which is correct. The fix only affects the FAISS (embedding) portion.
