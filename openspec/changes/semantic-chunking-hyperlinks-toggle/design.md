## Context

The system has two chunking paths: recursive (default) and semantic (via `pdf_semantic_chunking/`). The "API Documentation" strategy uses `engine_type="semantic"` but is misnamed — it handles all structured content. Link handling currently runs unconditionally: `extract_links()` + `resolve_links()` + `build_augmented_text_with_links()` always execute when a document has hyperlinks. This link-aware embedding augmentation injects "Links To:" and "Referenced From:" summaries into the embedding text, polluting the semantic representation and degrading chat response quality.

The existing `is_api_aware` field on `ChunkingStrategy` is vestigial — stored and passed around but never checked to change behavior.

## Goals / Non-Goals

**Goals:**
- Rename "API Documentation" strategy to "Semantic Chunking" with new `id: "semantic"`
- Remove `is_api_aware` field from entity, DB model, and API schemas
- Add `use_hyperlinks: bool = False` setting to `ChunkingStrategy`
- Gate all hyperlink processing on `use_hyperlinks`: extraction, resolution, embedding augmentation, and query-time traversal
- Auto-migrate existing documents using `"api-docs"` to `"semantic"` on startup
- Preserve non-link embedding augmentation (COM prefix, section hierarchy, element type)

**Non-Goals:**
- Not changing the recursive chunking path behavior (it already uses separators-only, no semantic pipeline)
- Not removing query-time `link_decay_factor`/`link_expansion_factor` params (they remain for granular control when `use_hyperlinks=true`)
- Not modifying the link extraction or link traversal specs themselves
- No changes to the stored `Chunk.chunk_metadata` schema

## Decisions

### Decision 1: `use_hyperlinks` as a strategy-level toggle, not document-level

Chosen over per-document or per-query toggles at the DB level. Strategy-level means:
- A user sets it once when creating a strategy
- All documents using that strategy inherit the behavior consistently
- Query-time `link_decay_factor` remains available as an override when the strategy has `use_hyperlinks=true`

**Alternative considered**: Per-document flag on `Document` table. Rejected because it adds another per-document decision point and complicates the upload UI. Strategy-level is simpler and groups related documents together.

### Decision 2: New ID with migration, not in-place rename

Create `id="semantic"` and migrate existing documents from `"api-docs"` rather than renaming in place.

**Why**: The `"api-docs"` ID is embedded in existing DB rows. Changing it in-place could cause confusion for environments with custom strategies or backups. A migration is safer and cleaner.

### Decision 3: Skip entire link pipeline when `use_hyperlinks=false`, not just augmentation

When disabled, skip `extract_links()`, `resolve_links()`, link-augmented embedding, and force query-time traversal off. This is zero-cost for the common case.

**Alternative considered**: Still extract and resolve links (store metadata) but skip augmentation and traversal. Rejected — storing dead metadata wastes DB space and adds parse-time cost with no benefit.

### Decision 4: Force `link_decay_factor=0` at the route level when `use_hyperlinks=false`

Rather than threading the strategy's `use_hyperlinks` flag deep into `_retrieval.py`, the query route will clamp `link_decay_factor` to `0.0` before calling `retrieve_chunks()` when the document's strategy has `use_hyperlinks=false`. This keeps the retrieval layer agnostic of strategy-level concerns.

## Risks / Trade-offs

- **[Migration]** Existing environments with custom strategies named `"api-docs"` could conflict. Mitigation: the seed logic checks for existence by ID before creating. The migration targets only rows with `chunking_strategy_id="api-docs"`.
- **[Backward compat]** API clients sending `is_api_aware` in `ChunkingStrategyCreate` will get a validation error. Mitigation: this is a minor API change; document in release notes.
- **[Existing chunks]** Chunks already in the DB with link-augmented embeddings are not re-embedded. Mitigation: link-augmentation embedding is computed at index time and stored; existing chunks retain their embeddings. Only newly processed documents are affected.
