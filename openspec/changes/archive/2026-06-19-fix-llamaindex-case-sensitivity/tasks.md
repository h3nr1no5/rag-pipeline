## 1. Fix BM25 Case Sensitivity in LlamaIndex Hybrid Retriever

- [x] 1.1 Normalize BM25 corpus tokenization to lowercase in `HybridRetriever._build_bm25()` — change `doc.split()` to `doc.lower().split()`
- [x] 1.2 Normalize BM25 query tokenization to lowercase in `HybridRetriever._aretrieve()` — change `query.split()` to `query.lower().split()` in the BM25 scoring section

## 2. Fix Source Boundary Markers in Prompt Builder

- [x] 2.1 Remove the conditional `[Source N]` label logic in `build_prompt()` — always prepend `[Source N]:` labels to context chunks regardless of `include_citations` flag
- [x] 2.2 Keep the citation instruction in the system prompt conditional — only the `citation_block` variable should depend on `include_citations`, not the `[Source N]` labels

## 3. Update Unit Tests

- [x] 3.1 Update `test_no_citations_omits_source_label` in `test_prompt_builder.py` — change assertion from `"[Source" not in prompt` to `"[Source 1]:" in prompt` for `include_citations=False`
- [x] 3.2 Update `test_object_format_no_citations_no_labels` — same pattern: expect `[Source N]` labels when `include_citations=False`
- [x] 3.3 Update `test_no_citations_everything_off` in combined tests — change assertion from `"[Source" not in prompt` to expect `[Source 1]:` and `[Page" not in prompt` but `"CRITICAL" not in prompt`
- [x] 3.4 Run `uv run pytest tests/unit/test_prompt_builder.py -v` to confirm all tests pass after updates

## 4. Update Main Spec

- [x] 4.1 Update `openspec/specs/response-formatting/spec.md` — change the `include_citations=False` scenario under "Citation instruction conditional on `include_citations`" so that context chunks SHALL always have `[Source N]` labels, only the citation instruction is conditional

## 5. Verification

- [x] 5.1 Run `uv run pytest tests/unit/ -v` to confirm all unit tests pass
- [x] 5.2 Run `uv run pytest tests/integration/test_llamaindex.py -v` to confirm LlamaIndex integration tests pass
- [x] 5.3 Run `uv run pytest tests/integration/test_response_formatting.py -v` to confirm response formatting integration tests pass
- [x] 5.4 Run `uv run ruff check .` and `uv run mypy src/` to confirm no linting or type errors
