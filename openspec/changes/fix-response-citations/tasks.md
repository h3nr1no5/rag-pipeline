## 1. Prompt Builder — `build_prompt()` changes

- [ ] 1.1 Strip `[Page N]` markers from chunk content when assembling context text in `build_prompt()`, before prefixing with `[Source N]` labels
- [ ] 1.2 Conditionally include the citation instruction in the system prompt based on `include_citations` parameter
- [ ] 1.3 Conditionally add `[Source N]` labels to context chunks based on `include_citations` parameter
- [ ] 1.4 Verify: `include_citations=False` produces context without citation instruction or `[Source N]` labels, but with `[Page N]` stripped in both modes

## 2. Clean Response — `clean_response()` verification

- [ ] 2.1 Verify `clean_response()` already strips `[Page N]` unconditionally (line 159) — no changes needed
- [ ] 2.2 Verify `clean_response()` already strips `[Source N]` conditionally on `include_citations` (lines 172-173) — no changes needed

## 3. Cosine Streaming — fix double-stream bug

- [ ] 3.1 Refactor `POST /api/v1/query/stream` to buffer all LLM tokens first, then apply `clean_response()`, then stream only the cleaned text
- [ ] 3.2 Remove the first pass that streams raw tokens to the client during generation
- [ ] 3.3 Ensure sources are emitted before cleaned tokens (current order preserved)
- [ ] 3.4 Verify the cached response uses the cleaned text (already the case via `answer` variable)

## 4. LlamaIndex Streaming — fix missing re-stream bug

- [ ] 4.1 Refactor `POST /api/v1/query/llamaindex/stream` to buffer all LLM tokens first, then apply `clean_response()`, then stream only the cleaned text
- [ ] 4.2 Remove the current code that streams raw tokens during generation then caches the cleaned version without re-streaming
- [ ] 4.3 Ensure sources are emitted before cleaned tokens (current order preserved)
- [ ] 4.4 Verify the cached response uses the cleaned text

## 5. Client-side Display — `strip_markdown_formatting()` changes

- [ ] 5.1 Add `[Page N]` stripping to `strip_markdown_formatting()` as unconditional safety net
- [ ] 5.2 Add `include_citations` parameter support to `strip_markdown_formatting()` for conditional `[Source N]` stripping
- [ ] 5.3 Thread the `include_citations` value from the SSE events to the rendering call in `Chat.py`
- [ ] 5.4 Store `include_citations` in the message state alongside answer and sources

## 6. Testing

- [ ] 6.1 Add unit tests for `build_prompt()`: `[Page N]` stripping from context, conditional citation instruction, conditional `[Source N]` labels
- [ ] 6.2 Add unit tests for `clean_response()`: `[Page N]` always stripped, `[Source N]` stripped correctly per `include_citations`
- [ ] 6.3 Add integration tests for cosine streaming: verify response does not contain `[Page N]` or leaked `[Source N]` when `include_citations=False`
- [ ] 6.4 Add integration tests for LlamaIndex streaming: verify response does not contain `[Page N]` or leaked `[Source N]` when `include_citations=False`
- [ ] 6.5 Run full test suite to verify no regressions in existing behavior when `include_citations=True`
