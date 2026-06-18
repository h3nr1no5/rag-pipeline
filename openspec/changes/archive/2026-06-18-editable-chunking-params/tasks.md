## 1. Data Model Changes

- [x] 1.1 Add `ProcessingConfig` dataclass to `src/domain/entities.py` with fields: `id`, `document_id`, `strategy_id`, `chunk_size`, `chunk_overlap`, `separators`, `use_hyperlinks`, `engine_type`, `created_at`
- [x] 1.2 Add `ProcessingConfig` SQLAlchemy model to `src/infrastructure/database/models.py` matching the entity fields, with FK to `documents.id`
- [x] 1.3 Add `current_processing_config_id` nullable FK column to `Document` model in `models.py`
- [x] 1.4 Rename `default_strategy()` → `recursive_strategy()` in `entities.py`, update id to `"recursive"`, name to `"Recursive"`, description accordingly
- [x] 1.5 Update `semantic_strategy()` in `entities.py`: rename name from `"Semantic Chunking"` to `"Semantic"`

## 2. Strategy Rename & Migration

- [x] 2.1 Update seed data in `src/api/main.py`: create strategy with `id="recursive"`, `name="Recursive"` instead of `"default"`/`"Default"`
- [x] 2.2 Update semantic seed strategy: change name from `"Semantic Chunking"` to `"Semantic"`
- [x] 2.3 Add startup migration: `UPDATE document SET chunking_strategy_id = 'recursive' WHERE chunking_strategy_id = 'default'`
- [x] 2.4 Remove old `"default"` strategy row after migration
- [x] 2.5 Update `_get_or_create_default_strategy` in `documents.py` to use `"recursive"` as fallback ID

## 3. API Schema Changes

- [x] 3.1 Add `ChunkingStrategyUpdate` Pydantic schema in `src/api/schemas/document.py` with optional fields: `name`, `description`, `chunk_size`, `chunk_overlap`, `separators`, `use_hyperlinks`
- [x] 3.2 Add `ProcessingConfigResponse` Pydantic schema in `src/api/schemas/document.py` with all ProcessingConfig fields
- [x] 3.3 Add override fields to `POST /documents` upload schema: optional `chunk_size`, `chunk_overlap`, `separators`, `use_hyperlinks`
- [x] 3.4 Add `ProcessingConfig` to document response schema (nested `processing_config` object, `processing_configs` array)

## 4. API Endpoint Changes

- [x] 4.1 Add `PATCH /strategies/{strategy_id}` endpoint in `src/api/routes/documents.py` that accepts `ChunkingStrategyUpdate` and updates the strategy row in DB
- [x] 4.2 Modify `POST /documents` in `routes.py`: after document creation, merge strategy defaults with user overrides and create a `ProcessingConfig` record
- [x] 4.3 Assign `document.current_processing_config_id` to the new `ProcessingConfig` record after creation
- [x] 4.4 Include `processing_config` nested object in `GET /documents/{id}` response
- [x] 4.5 Add `GET /documents/{id}/processing-configs` endpoint returning all configs for a document ordered by created_at descending

## 5. Processor: Read from ProcessingConfig

- [x] 5.1 In `src/domain/services/processor.py`, load `ProcessingConfig` from `document.current_processing_config_id` at the start of processing
- [x] 5.2 Use `ProcessingConfig.chunk_size`, `chunk_overlap`, `separators` instead of reading from `ChunkingStrategy` directly
- [x] 5.3 Thread `chunk_size` and `chunk_overlap` into the semantic chunking engine call: `semantic_chunk_pdf(file_path, chunk_size=..., chunk_overlap=...)`
- [x] 5.4 Continue using `ProcessingConfig.use_hyperlinks` for link pipeline gating

## 6. Semantic Engine: Wire Strategy Params, Remove Per-Type Limits

- [x] 6.1 Update `src/pdf_semantic_chunking/api.py` `chunk_pdf()` to accept `chunk_size` and `chunk_overlap` parameters (optional, with backward-compatible defaults: chunk_size=800, chunk_overlap=80)
- [x] 6.2 Thread these params through to `ChunkAssembler` as `max_tokens` and overlap value
- [x] 6.3 Remove `ELEMENT_TYPE_TOKEN_LIMITS` dict from `src/pdf_semantic_chunking/chunking/assembler.py`
- [x] 6.4 Derive `min_chunk_size` as `max(50, chunk_size // 4)` inside assembler
- [x] 6.5 Compute overlap as `chunk_overlap` directly (not as a ratio of chunk_size)
- [x] 6.6 Update `src/pdf_semantic_chunking/cli.py` to accept `--chunk-size` and `--chunk-overlap` flags (keep old `--min-chunk-size`/`--max-chunk-size`/`--overlap` as aliases)
- [x] 6.7 Add `effective_chunk_size` and `effective_chunk_overlap` to processing stats output

## 7. Reprocessing: Create New ProcessingConfig

- [x] 7.1 Modify `POST /documents/{id}/reprocess` in `routes.py` to accept optional override params (same as upload)
- [x] 7.2 On reprocess, create a new `ProcessingConfig` record with merged current strategy defaults + new overrides
- [x] 7.3 Update `document.current_processing_config_id` to the new config before triggering async reprocessing
- [x] 7.4 Retain the old `ProcessingConfig` record (do not delete)

## 8. Frontend: Editable Params & Sticky Defaults

- [x] 8.1 Create `data/chunking_params.json` load/save pattern in `client/pages/4_📁_Documents.py` (same pattern as `3_💬_Chat.py` chat params)
- [x] 8.2 Replace read-only strategy captions with editable inputs: `chunk_size` slider, `chunk_overlap` slider, `separators` text input, `use_hyperlinks` checkbox
- [x] 8.3 Pre-fill form fields from saved `chunking_params.json` on page load, falling back to strategy defaults
- [x] 8.4 Add "Save as Defaults" button that writes current values to `chunking_params.json`
- [x] 8.5 When strategy selection changes, update form fields to that strategy's defaults (but preserve any user edits as overrides)
- [x] 8.6 On upload, send override values alongside `strategy_id` to `POST /documents`

## 9. Update Tests

- [x] 9.1 Update `tests/conftest.py` strategy fixtures: rename `default`→`recursive`, update fixture factory to produce `ProcessingConfig` objects
- [x] 9.2 Update tests referencing `"default"` strategy ID to use `"recursive"`
- [x] 9.3 Add unit tests for `ProcessingConfig` entity creation and field defaults
- [x] 9.4 Add integration tests for `PATCH /strategies/{id}` endpoint
- [x] 9.5 Add integration tests for upload with override params and ProcessingConfig creation
- [x] 9.6 Add integration tests for reprocessing endpoint with new params creating new ProcessingConfig
- [x] 9.7 Add integration tests for `GET /documents/{id}/processing-configs`
- [x] 9.8 Add unit tests for semantic engine with custom chunk_size/chunk_overlap
- [x] 9.9 Add unit tests confirming per-element-type limits are replaced by chunk_size
- [x] 9.10 Run `uv run pytest -v` and fix any failures

## 10. Sync & Verify

- [x] 10.1 Run full test suite: `uv run pytest -v`
- [x] 10.2 Sync delta specs to main specs via `/opsx-sync-specs`
