## Why

Chunking strategy parameters (`chunk_size`, `chunk_overlap`, `separators`, `use_hyperlinks`) are frozen at strategy creation time — there is no PATCH/PUT endpoint, no frontend editing, and no way to tune them per-document. The semantic chunking engine independently hardcodes its own size defaults (`min_tokens=200`, `max_tokens=800`, `overlap_ratio=0.10`) and completely ignores the strategy's `chunk_size` and `chunk_overlap`, making those fields decorative for the semantic path. Users have no way to override parameters before processing a document, and their last-used preferences are forgotten on page refresh.

## What Changes

1. **Rename `"default"` strategy → `"recursive"`** — New ID `"recursive"`, name `"Recursive"`. Migrate existing documents from `"default"` to `"recursive"`. Rename `"Semantic Chunking"` → `"Semantic"` for consistency.
2. **New `ProcessingConfig` entity and DB table** — Stores a full copy of the effective processing parameters used for a document at processing time. Created at upload alongside the document. Processor reads from `ProcessingConfig` directly.
3. **Add PATCH `/strategies/{id}` endpoint** — Makes strategy parameters editable after creation. A user can update name, chunk_size, chunk_overlap, separators, use_hyperlinks.
4. **Wire semantic chunking engine to strategy params** — Thread `chunk_size` → `max_tokens` and `chunk_overlap` → overlap ratio through to `ChunkAssembler`. Remove hardcoded defaults. Per-element-type token limits are replaced by strategy `chunk_size`.
5. **Accept override params in `POST /documents`** — Upload endpoint accepts optional `chunk_size`, `chunk_overlap`, `separators`, `use_hyperlinks` that override strategy defaults for this document. The merged effective params are stored in a `ProcessingConfig` record.
6. **Sticky defaults via JSON file** — Frontend saves last-used parameter values to `data/chunking_params.json` (same pattern as `data/chat_params.json`). Loaded on page start to pre-fill the upload form.
7. **Reprocessing uses current params** — `POST /documents/{id}/reprocess` accepts new params or uses current strategy defaults, not the original `ProcessingConfig` snapshot.
8. **Frontend editable params** — Strategy selector in the upload sidebar shows editable sliders/inputs for params instead of read-only captions.

**BREAKING**: Documents using strategy ID `"default"` automatically migrate to `"recursive"`. The `POST /documents` endpoint now accepts optional param overrides.

## Capabilities

### New Capabilities
- `processing-config`: New `ProcessingConfig` entity, DB model, and API endpoints for recording and retrieving the effective processing parameters used per document. Processor reads `ProcessingConfig` instead of strategy directly.

### Modified Capabilities
- `semantic-chunking-engine`: Requirements change — wire strategy params (`chunk_size`, `chunk_overlap`) into the engine; replace hardcoded per-element-type token limits with strategy `chunk_size`; accept params from `ProcessingConfig` via processor.

## Impact

| File | Change |
|------|--------|
| `src/domain/entities.py` | Rename `default_strategy()` → `recursive_strategy()`. Add `ProcessingConfig` dataclass. |
| `src/infrastructure/database/models.py` | Rename strategy seed ID `"default"`→`"recursive"`. Add `ProcessingConfig` SQLAlchemy model. |
| `src/api/schemas/document.py` | Add override fields to upload schema. Add `ProcessingConfigCreate`/`ProcessingConfigResponse` schemas. Add `ChunkingStrategyUpdate` schema. |
| `src/api/routes/documents.py` | Add `PATCH /strategies/{id}`. Modify `POST /documents` to accept overrides & create `ProcessingConfig`. Modify `POST /documents/{id}/reprocess` to accept new params. |
| `src/api/main.py` | Update seed: `"default"`→`"recursive"`, `"Semantic Chunking"`→`"Semantic"`. Migrate docs from `"default"` to `"recursive"`. |
| `src/domain/services/processor.py` | Read effective params from `ProcessingConfig`. Thread `chunk_size`/`chunk_overlap` into semantic call. |
| `src/pdf_semantic_chunking/` | Accept `chunk_size`/`chunk_overlap` params from processor. Replace hardcoded `ChunkAssembler` defaults. |
| `client/pages/4_📁_Documents.py` | Editable params in upload sidebar. "Save as Defaults" button. Load sticky defaults on page start. |
| `data/chunking_params.json` | New file (same pattern as `chat_params.json`). |
| `tests/` | Update strategy fixtures. Add tests for `ProcessingConfig`, PATCH strategy, override params, reprocessing. |
