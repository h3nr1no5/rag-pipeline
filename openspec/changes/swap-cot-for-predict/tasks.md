## 1. Module Code Changes

- [ ] 1.1 Replace `ChainOfThought` with `Predict` as the sole response generator in `APIDocRAG.__init__()` — remove `self.response_generator` (CoT), rename `self.fallback_generator` to `self.response_generator`
- [ ] 1.2 Simplify `_generate_with_assertions()` — remove try/except around the generator call (Predict has fewer fields, no `reasoning`), remove `_generate_fallback()` invocations
- [ ] 1.3 Remove `_generate_fallback()` method entirely
- [ ] 1.4 Update the result dict in `_generate_with_assertions()` to always return `"rationale": ""` (no `reasoning` field from Predict)
- [ ] 1.5 Run linting and type checking: `uv run ruff check .` and `uv run mypy src/`

## 2. Test Updates

- [ ] 2.1 Update `module` fixture — remove `dspy.ChainOfThought` patch, rename `fallback_generator` → `response_generator`, remove redundant mock assignment for `response_generator`
- [ ] 2.2 Update `test_assertions_pass_returns_co_output` — rename to `test_assertions_pass_returns_predict_output`, remove `used_fallback` assertion (no longer applicable)
- [ ] 2.3 Remove `test_rationale_included_in_return_dict` — replace with `test_rationale_is_always_empty` asserting `result["rationale"] == ""`
- [ ] 2.4 Remove `test_assertions_fail_still_includes_rationale` — no longer relevant (rationale is always empty)
- [ ] 2.5 Remove `test_fallback_path_returns_empty_rationale` — no fallback path exists
- [ ] 2.6 Remove `test_runtime_exception_still_falls_back` — no fallback path exists
- [ ] 2.7 Update `test_assertions_fail_does_not_call_fallback` — rename to reflect that `_generate_fallback` no longer exists; verify assertions failure path still works (returns Predict output, logs warning)
- [ ] 2.8 Keep `test_assertions_fail_logs_warning_and_returns_co_output` — rename to replace `co_output` with `predict_output`
- [ ] 2.9 Keep `test_assertions_fail_reports_both_citation_and_reference_issues` — no changes needed
- [ ] 2.10 Run tests: `uv run pytest tests/unit/domain/rag/api_docs/test_api_docs_dspy_integration.py -v`

## 3. Documentation

- [ ] 3.1 Update main spec `openspec/specs/api-docs-rag/spec.md` — replace the "Pipeline SHALL propagate rationale" requirement with the delta spec content reflecting always-empty rationale
