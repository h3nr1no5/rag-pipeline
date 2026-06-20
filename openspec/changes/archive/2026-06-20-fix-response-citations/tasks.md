## 1. Fix Response Citations — `build_prompt()` changes

- [x] 1.1 Fix response citations in search results
- [x] 1.2 Update citation formatting in API response
- [x] 1.3 Add citation validation for edge cases
- [x] 1.4 Test citation rendering in frontend
- [x] 1.5 Update documentation for citation changes

## 2. Clean Response — `clean_response()` verification

- [x] 2.1 Verify `clean_response()` already strips `[Page N]` unconditionally (line 159) — no changes needed
- [x] 2.2 Verify `clean_response()` already strips `[Source N]` conditionally on `include_citations` (lines 172-173) — no changes needed

## 3. Cosine Streaming — fix double-stream bug

- [x] 3.1 Refactor `POST /api/v1/query/stream` to buffer all LLM tokens first, then apply `clean_response()`, then stream only the cleaned text
- [x] 3.2 Remove the first pass that streams raw tokens to the client during generation
- [x] 3.3 Ensure sources are emitted before cleaned tokens (current order preserved)
- [x] 3.4 Verify the cached response uses the cleaned text (already the case via `answer` variable)

## 4. LlamaIndex Streaming — fix missing re-stream bug

- [x] 4.1 Refactor `POST /api/v1/query/llamaindex/stream` to buffer all LLM tokens first, then apply `clean_response()`, then stream only the cleaned text
- [x] 4.2 Remove the current code that streams raw tokens during generation then caches the cleaned version without re-streaming
- [x] 4.3 Ensure sources are emitted before cleaned tokens (current order preserved)
- [x] 4.4 Verify the cached response uses the cleaned text

## 5. Client-side Display — `strip_markdown_formatting()` changes

- [x] 5.1 Add `[Page N]` stripping to `strip_markdown_formatting()` as unconditional safety net
- [x] 5.2 Add `include_citations` parameter support to `strip_markdown_formatting()` for conditional `[Source N]` stripping
- [x] 5.3 Thread the `include_citations` value from the SSE events to the rendering call in `Chat.py`
- [x] 5.4 Store `include_citations` in the message state alongside answer and sources

## 6. Testing

- [x] 6.1 Add unit tests for `build_prompt()`: `[Page N]` stripping from context, conditional citation instruction, conditional `[Source N]` labels
- [x] 6.2 Add unit tests for `clean_response()`: `[Page N]` always stripped, `[Source N]` stripped correctly per `include_citations`
- [x] 6.3 Add integration tests for cosine streaming: verify response does not contain `[Page N]` or leaked `[Source N]` when `include_citations=False`
- [x] 6.4 Add integration tests for LlamaIndex streaming: verify response does not contain `[Page N]` or leaked `[Source N]` when `include_citations=False`
- [x] 6.5 Run full test suite to verify no regressions in existing behavior when `include_citations=True`
