## 1. Data Model Changes

- [ ] 1.1 Add `use_hyperlinks: bool = False` to `ChunkingStrategy` dataclass in `src/domain/entities.py`, replace `is_api_aware`
- [ ] 1.2 Rename `api_docs_strategy()` → `semantic_strategy()` in `entities.py`, update name/description/id to "semantic"
- [ ] 1.3 Add `use_hyperlinks` column (Boolean, default=False) to `ChunkingStrategy` model in `src/infrastructure/database/models.py`, remove `is_api_aware`
- [ ] 1.4 Replace `is_api_aware` with `use_hyperlinks` in `ChunkingStrategyCreate` schema in `src/api/schemas/document.py`
- [ ] 1.5 Replace `is_api_aware` with `use_hyperlinks` in `ChunkingStrategyResponse` schema in `src/api/schemas/document.py`

## 2. DB Seed & Migration

- [ ] 2.1 Update `src/api/main.py` startup: create `id="semantic"`, `name="Semantic Chunking"`, `use_hyperlinks=False` strategy
- [ ] 2.2 Add migration logic in `src/api/main.py`: `UPDATE document SET chunking_strategy_id = 'semantic' WHERE chunking_strategy_id = 'api-docs'`
- [ ] 2.3 Remove old `"api-docs"` strategy row after migration
- [ ] 2.4 Remove `is_api_aware=True` from the DB seed (it's replaced by `use_hyperlinks`)

## 3. Update Document Routes

- [ ] 3.1 Update `_get_or_create_default_strategy` and `create_strategy` in `src/api/routes/documents.py` to pass `use_hyperlinks` instead of `is_api_aware`

## 4. Processor: Gate Link Pipeline on `use_hyperlinks`

- [ ] 4.1 In `src/domain/services/processor.py`, extract `use_hyperlinks` from the strategy (alongside existing `is_api_aware` extraction)
- [ ] 4.2 Gate `extract_links()` + `resolve_links()` call on `use_hyperlinks` — skip entirely when false
- [ ] 4.3 In the recursive path, gate `build_augmented_text_with_links()` on `use_hyperlinks` — use `build_augmented_text()` when false
- [ ] 4.4 In the semantic path, gate `build_augmented_text_with_links()` on `use_hyperlinks` — use `build_augmented_text()` when false
- [ ] 4.5 Remove `is_api_aware` from the `ChunkingStrategyEntity` construction in processor.py

## 5. Query Pipeline: Force Traversal Off When Disabled

- [ ] 5.1 In `src/api/routes/query/routes.py`, load the document's strategy `use_hyperlinks` flag
- [ ] 5.2 When `use_hyperlinks=False`, clamp `link_decay_factor` to `0.0` before passing to `retrieve_chunks()` and cache key construction

## 6. Update Tests

- [ ] 6.1 Update `tests/conftest.py`: rename `api_strategy` fixture, replace `is_api_aware=True` with `use_hyperlinks=False`
- [ ] 6.2 Update `tests/unit/test_chunking.py` if it references the old strategy fields
- [ ] 6.3 Update `tests/integration/test_strategies.py`: replace `is_api_aware` with `use_hyperlinks` in test payloads
- [ ] 6.4 Update `tests/integration/test_rag_comparison.py`, `test_pdf_integration.py`, `test_chat_integration.py`, `test_cache_bug.py`, `test_llm_loading.py`: replace `ChunkingStrategy(id="api-docs"` references with `"semantic"` and update fields
- [ ] 6.5 Update `tests/integration/test_link_aware_rag.py` if strategy seed is used

## 7. Sync & Verify

- [ ] 7.1 Run all tests: `uv run pytest -v` and fix any failures
- [ ] 7.2 Sync delta specs to main specs via `/opsx-sync-specs`
