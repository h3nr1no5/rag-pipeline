## 1. Update llamaindex-rewrite spec

- [ ] 1.1 Replace the "LlamaIndex owns its response pipeline" requirement in `openspec/specs/llamaindex-rewrite/spec.md` to remove the `ResponseSynthesizer` mandate and reflect the use of `build_prompt()` / `get_llm()`
- [ ] 1.2 Remove the Chroma-related requirements (index build, vector store persistence, index update) that no longer apply

## 2. Refactor LlamaIndexRetriever.generate() to use shared prompt pipeline

- [ ] 2.1 Add `prompt_sources`, `include_citations`, and `response_length` parameters to `generate()` method signature
- [ ] 2.2 Replace `_retrieve_and_rerank()` call with `self.retrieve()` call to get `min_relevance_score` filtered chunks
- [ ] 2.3 Add empty-retrieval guard — return `("I don't have enough information to answer this question.", [])` when no chunks pass filtering
- [ ] 2.4 Add `deduplicate_chunks()` call on retrieved chunks
- [ ] 2.5 Replace inline prompt with `build_prompt()` call using the deduplicated chunks
- [ ] 2.6 Replace `MLXLlamaIndexLLM.acomplete()` with `get_llm().generate()` for response generation
- [ ] 2.7 Return raw LLM output (let route handle `clean_response()`)

## 3. Refactor LlamaIndexRetriever.generate_stream() similarly

- [ ] 3.1 Add `prompt_sources`, `include_citations`, `response_length` parameters to `generate_stream()` method signature
- [ ] 3.2 Replace `_retrieve_and_rerank()` call with `self.retrieve()` call
- [ ] 3.3 Add empty-retrieval guard
- [ ] 3.4 Add `deduplicate_chunks()` and `build_prompt()` calls
- [ ] 3.5 Replace `MLXLlamaIndexLLM.astream_complete()` with `get_llm().generate_stream()`

## 4. Remove dead code

- [ ] 4.1 Remove `_build_context()` method from `LlamaIndexRetriever`
- [ ] 4.2 Remove inline prompt strings from both `generate()` and `generate_stream()`

## 5. Update non-streaming route

- [ ] 5.1 Add `prompt_sources`, `include_citations`, `response_length` parameter passing from request to `retriever.generate()` call in `routes.py`
- [ ] 5.2 Verify `clean_response()` call in route still works correctly with raw LLM output

## 6. Update streaming route (if needed)

- [ ] 6.1 Verify streaming route already handles `prompt_sources`, `include_citations`, `response_length` correctly — it already uses `build_prompt()`, so likely no change needed

## 7. Test the fix

- [ ] 7.1 Run existing test suite (`uv run pytest -v`) to confirm no regressions
- [ ] 7.2 Verify non-streaming LlamaIndex endpoint returns correct answer for "what is llm?" query
