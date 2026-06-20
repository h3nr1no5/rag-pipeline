## Why

The "API Documentation" chunking strategy is misnamed — the semantic chunking engine handles any structured content (COM docs, PDFs, code), not just API docs. Meanwhile, the link-aware embedding augmentation (`build_augmented_text_with_links`) injects "Links To:" and "Referenced From:" summaries into the embedding text, which pollutes the semantic representation and degrades chat response quality. Users have no way to opt out of this behavior.

## What Changes

1. **Rename "API chunking strategy" → "Semantic Chunking"** — New strategy `id: "semantic"`, `name: "Semantic Chunking"`. Migrate existing documents using `"api-docs"` to the new ID.
2. **Remove `is_api_aware` field** — Vestigial; stored and passed around but never changes behavior.
3. **Add `use_hyperlinks: bool = False` to `ChunkingStrategy`** — Controls whether hyperlinks are considered during indexing and query time.
4. **Gate entire link pipeline on `use_hyperlinks`** — When `false`: skip `extract_links()`, `resolve_links()`, link-aware embedding augmentation, and force query-time link traversal off.
5. **Update DB seed data** — Default strategies become: "Default" (recursive) and "Semantic Chunking" (semantic, `use_hyperlinks=false`).

## Capabilities

### New Capabilities

None — this modifies existing capabilities.

### Modified Capabilities

- **`semantic-chunking-engine`**: Requirements change — add `use_hyperlinks` configuration setting, update naming from "API Documentation" to "Semantic Chunking", define hyperlink handling behavior.
- **`chunking-strategies`** (API): Schema changes — replace `is_api_aware` with `use_hyperlinks` in create/response schemas.

## Impact

| File | Change |
|------|--------|
| `src/domain/entities.py` | Rename `api_docs_strategy()` → `semantic_strategy()`. Replace `is_api_aware` with `use_hyperlinks: bool = False` |
| `src/infrastructure/database/models.py` | Replace `is_api_aware` column with `use_hyperlinks` column (default `False`) |
| `src/api/schemas/document.py` | Replace `is_api_aware` with `use_hyperlinks` in `ChunkingStrategyCreate` and `ChunkingStrategyResponse` |
| `src/api/routes/documents.py` | Pass `use_hyperlinks` through on strategy creation |
| `src/api/main.py` | Seed `"semantic"` strategy, migrate docs from `"api-docs"`, delete old row |
| `src/domain/services/processor.py` | Gate link pipeline on `use_hyperlinks` — skip extraction, resolution, link-augmented embedding when `false` |
| `src/api/routes/query/routes.py` | Pass strategy's `use_hyperlinks` to force query-time traversal off |
| `src/api/routes/query/_retrieval.py` | Accept `use_hyperlinks` param to force `link_decay_factor=0` |
| `src/api/schemas/query.py` | No change needed (query-level params remain for granular control when enabled) |
| `tests/conftest.py` | Update strategy fixture |
| `tests/` | Update all tests referencing `"api-docs"` or `is_api_aware` |

**Breaking**: Documents using the old `"api-docs"` strategy ID will automatically migrate to `"semantic"`. The `is_api_aware` field is removed from the API schema.
