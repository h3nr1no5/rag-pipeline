## 1. Core Pipeline — Remove UUID from Chunk Context

- [ ] 1.1 Remove `[chunk_id]` prefix from `_format_chunks()` in `src/domain/rag/api_docs/pipeline/module.py` — return only raw content with blank-line separation
- [ ] 1.2 Update `APIResponseGenerator.answer` field description in `src/domain/rag/api_docs/pipeline/signatures.py` — remove instruction about bracketed citation numbers
- [ ] 1.3 Update `ContextAssembler.chunks` and `ContextAssembler.assembled_context` field descriptions in `signatures.py` — remove `[chunk_id]` prefix references
- [ ] 1.4 Simplify `validate_citations()` in `src/domain/rag/api_docs/pipeline/assertions.py` — remove `missing_inline_citations` check, remove `extract_cited_names` dependency, make inline validation always pass

## 2. Defense-in-Depth — UUID Stripping

- [ ] 2.1 Add UUID-pattern regex stripping to `clean_response()` in `src/domain/services/prompt_builder.py` — strip `[uuid]` patterns when `include_citations=False` or unconditionally

## 3. Update Tests

- [ ] 3.1 Update `test_validate_citations_missing_inline` in `tests/unit/test_api_docs_pipeline.py` — adapt or remove test that expected inline brackets to be required
- [ ] 3.2 Update `test_validate_citations_empty_answer` — now passes vacuously (no inline requirement), change expected `valid` from `False` to `True`
- [ ] 3.3 Update `test_validate_citations_all_valid` — adjust answer text (no `[Name]` brackets needed), expectation unchanged
- [ ] 3.4 Update DSPy integration test `test_assertions_fail_logs_warning_and_returns_co_output` — with `answer="Use the CreateNode method."` and `citations="CreateNode"`, the citation validation now passes; assertions_passed changes from `False` to `True` (only reference check remains)
- [ ] 3.5 Update DSPy integration test `test_assertions_fail_does_not_call_fallback` — same change as 3.4, `assertions_passed` changes from `False` to `True`
- [ ] 3.6 Update DSPy integration test `test_assertions_fail_reports_both_citation_and_reference_issues` — with `citations=""` and `answer="I don't know the answer"`, the citation validation now passes; reference check still fails (missing "CreateNode"); warning message no longer mentions citations issue — update assertion to only check for "refs" in warning message
- [ ] 3.7 Update `test_assertions_fail_still_includes_rationale` — same adjustment, `assertions_passed` expected `True`
- [ ] 3.8 Update `test_validate_citations_unknown` — adjust answer text (no `[FakeFunc]` brackets needed), expectation `valid=False` unchanged (unknown citations still detected from `citations` list)

## 4. Verification

- [ ] 4.1 Run unit tests to confirm all pass: `uv run pytest tests/unit/ -v`
- [ ] 4.2 Run specific DSPy pipeline tests: `uv run pytest tests/unit/test_api_docs_pipeline.py tests/unit/domain/rag/api_docs/test_api_docs_dspy_integration.py -v`
