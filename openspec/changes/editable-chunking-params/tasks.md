## 1. Data Model Changes

- [ ] 1.1 Add `ProcessingConfig` dataclass to `src/domain/entities.py` with fields: `id`, `document_id`, `strategy_id`, `chunk_size`, `chunk_overlap`, `separators`, `use_hyperlinks`, `engine_type`, `created_at`
- [ ] 1.2 Add `ProcessingConfig` SQLAlchemy model to `src/infrastructure/database/models.py` matching the entity fields, with FK to `documents.id`
- [ ] 1.3 Add `current_processing_config_id` nullable FK column to `Document` model in `models.py`
- [ ] 1.4 Rename `default_strategy()` → `recursive_strategy()` in `entities.py`, update id to `"recursive"`, name to `"Recursive"`, description accordingly
- [ ] 1.5 Update `semantic_strategy()` in `entities.py`: rename name from `"Semantic Chunking"` to `"Semantic"`

## 2. Strategy Rename & Migration

- [ ] 2.1 Update seed data in `src/api/main.py`: create strategy with `id="recursive"`, `name="Recursive"` instead of `"default"`/`"Default"`
- [ ] 2.2 Update semantic seed strategy: change name from `"Semantic Chunking"` to `"Semantic"`
- [ ] 2.3 Add startup migration: `UPDATE document SET chunking_strategy_id = 'recursive' WHERE chunking_strategy_id = 'default'`
- [ ] 2.4 Remove old `"default"` strategy row after migration
- [ ] 2.5 Update `_get_or_create_default_strategy` in `documents.py` to use `"recursive"` as fallback ID

## 3. API Schema Changes

- [ ] 3.1 Add `ChunkingStrategyUpdate` Pydantic schema in `src/api/schemas/document.py` with optional fields: `name`, `description`, `chunk_size`, `chunk_overlap`, `separators`, `use_hyperlinks`
- [ ] 3.2 Add `ProcessingConfigResponse` Pydantic schema in `src/api/schemas/document.py` with all ProcessingConfig fields
- [ ] 3.3 Add override fields to `POST /documents` upload schema: optional `chunk_size`, `chunk_overlap`, `separators`, `use_hyperlinks`
- [ ] 3.4 Add `ProcessingConfig` to document response schema (nested `processing_config` object, `processing_configs` array)

## 4. API Endpoint Changes

- [ ] 4.1 Add `PATCH /strategies/{strategy_id}` endpoint in `src/api/routes/documents.py` that accepts `ChunkingStrategyUpdate` and updates the strategy row in DB
- [ ] 4.2 Modify `POST /documents` in `routes.py`: after document creation, merge strategy defaults with user overrides and create a `ProcessingConfig` record
- [ ] 4.3 Assign `document.current_processing_config_id` to the new `ProcessingConfig` record after creation
- [ ] 4.4 Include `processing_config` nested object in `GET /documents/{id}` response
- [ ] 4.5 Add `GET /documents/{id}/processing-configs` endpoint returning all configs for a document ordered by created_at descending

## 5. Processor: Read from ProcessingConfig

- [ ] 5.1 In `src/domain/services/processor.py`, load `ProcessingConfig` from `document.current_processing_config_id` at the start of processing
- [ ] 5.2 Use `ProcessingConfig.chunk_size`, `chunk_overlap`, `separators` instead of reading from `ChunkingStrategy` directly
- [ ] 5.3 Thread `chunk_size` and `chunk_overlap` into the semantic chunking engine call: `semantic_chunk_pdf(file_path, chunk_size=..., chunk_overlap=...)`
- [ ] 5.4 Continue using `ProcessingConfig.use_hyperlinks` for link pipeline gating

## 6. Semantic Engine: Wire Strategy Params, Remove Per-Type Limits

- [ ] 6.1 Update `src/pdf_semantic_chunking/api.py` `chunk_pdf()` to accept `chunk_size` and `chunk_overlap` parameters (optional, with backward-compatible defaults: chunk_size=800, chunk_overlap=80)
- [ ] 6.2 Thread these params through to `ChunkAssembler` as `max_tokens` and overlap value
- [ ] 6.3 Remove `ELEMENT_TYPE_TOKEN_LIMITS` dict from `src/pdf_semantic_chunking/chunking/assembler.py`
- [ ] 6.4 Derive `min_chunk_size` as `max(50, chunk_size // 4)` inside assembler
- [ ] 6.5 Compute overlap as `chunk_overlap` directly (not as a ratio of chunk_size)
- [ ] 6.6 Update `src/pdf_semantic_chunking/cli.py` to accept `--chunk-size` and `--chunk-overlap` flags (keep old `--min-chunk-size`/`--max-chunk-size`/`--overlap` as aliases)
- [ ] 6.7 Add `effective_chunk_size` and `effective_chunk_overlap` to processing stats output

## 7. Reprocessing: Create New ProcessingConfig

- [ ] 7.1 Modify `POST /documents/{id}/reprocess` in `routes.py` to accept optional override params (same as upload)
- [ ] 7.2 On reprocess, create a new `ProcessingConfig` record with merged current strategy defaults + new overrides
- [ ] 7.3 Update `document.current_processing_config_id` to the new config before triggering async reprocessing
- [ ] 7.4 Retain the old `ProcessingConfig` record (do not delete)

## 8. Frontend: Editable Params & Sticky Defaults

- [ ] 8.1 Create `data/chunking_params.json` load/save pattern in `client/pages/4_📁_Documents.py` (same pattern as `3_💬_Chat.py` chat params)
- [ ] 8.2 Replace read-only strategy captions with editable inputs: `chunk_size` slider, `chunk_overlap` slider, `separators` text input, `use_hyperlinks` checkbox
- [ ] 8.3 Pre-fill form fields from saved `chunking_params.json` on page load, falling back to strategy defaults
- [ ] 8.4 Add "Save as Defaults" button that writes current values to `chunking_params.json`
- [ ] 8.5 When strategy selection changes, update form fields to that strategy's defaults (but preserve any user edits as overrides)
- [ ] 8.6 On upload, send override values alongside `strategy_id` to `POST /documents`

## 9. Update Tests

- [ ] 9.1 Update `tests/conftest.py` strategy fixtures: rename `default`→`recursive`, update fixture factory to produce `ProcessingConfig` objects
- [ ] 9.2 Update tests referencing `"default"` strategy ID to use `"recursive"`
- [ ] 9.3 Add unit tests for `ProcessingConfig` entity creation and field defaults
- [ ] 9.4 Add integration tests for `PATCH /strategies/{id}` endpoint
- [ ] 9.5 Add integration tests for upload with override params and ProcessingConfig creation
- [ ] 9.6 Add integration tests for reprocessing endpoint with new params creating new ProcessingConfig
- [ ] 9.7 Add integration tests for `GET /documents/{id}/processing-configs`
- [ ] 9.8 Add unit tests for semantic engine with custom chunk_size/chunk_overlap
- [ ] 9.9 Add unit tests confirming per-element-type limits are replaced by chunk_size
- [ ] 9.10 Run `uv run pytest -v` and fix any failures

## 10. Sync & Verify

- [ ] 10.1 Run full test suite: `uv run pytest -v`
- [ ] 10.2 Sync delta specs to main specs via `/opsx-sync-specs`
