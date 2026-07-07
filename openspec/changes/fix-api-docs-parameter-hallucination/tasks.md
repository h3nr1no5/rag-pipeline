## 1. Assertion Retry — Make assertions actionable

- [ ] 1.1 Modify `_generate_with_assertions()` in `module.py` to retry with `_generate_fallback()` when assertions fail (not just on exception)
- [ ] 1.2 Add structured fallback answer in `_generate_with_assertions()` for when both CoT and Predict fail assertions
- [ ] 1.3 Update the final response dict to accurately reflect the retry stage used

## 2. Fallback Prompt — Add parameter detail instruction

- [ ] 2.1 Update `_generate_answer()` prompt in `manager.py` to request parameter names, types, and descriptions
- [ ] 2.2 Verify fallback answers include parameter details when context supports it

## 3. BM25 — Index per-parameter names and descriptions

- [ ] 3.1 Extend `_build_keyword_text()` in `bm25_index.py` method branch to flatten `parameters` metadata into keyword text
- [ ] 3.2 Verify BM25 search matches parameter description queries

## 4. Parameter Validation — Answer-level claim verification

- [ ] 4.1 Implement `validate_parameter_claims()` function that extracts parameter mentions from answer text and checks against source chunk metadata
- [ ] 4.2 Integrate parameter validation into the fallback path in `manager.py` (after `_generate_answer()`)
- [ ] 4.3 Integrate parameter validation into the DSPy path in `module.py` (after `_generate_with_assertions()`)
- [ ] 4.4 Add unsupported parameter claims to response metadata
