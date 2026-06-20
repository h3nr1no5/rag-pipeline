## 1. Update Prompt to Encourage Markdown Formatting

- [x] 1.1 Modify `build_prompt()` in `src/domain/services/prompt_builder.py` — replace the "plain text without Markdown formatting" instruction with one that encourages structured Markdown output (headings, bold, lists)
- [x] 1.2 Verify the prompt change across all three RAG backends (cosine, LangChain, LlamaIndex) by checking they all use the shared `build_prompt()` function

## 2. Remove Markdown Stripping from `clean_response()`

- [x] 2.1 In `src/domain/services/prompt_builder.py`, remove the Markdown-stripping regex block from `clean_response()` (lines ~167-174: `# Strip Markdown formatting`)
- [x] 2.2 Verify that `[Page N]` stripping and conditional `[Source N]` stripping are preserved after the change
- [x] 2.3 Verify repetition detection, token artifact stripping, and line deduplication still work

## 3. Remove Markdown Stripping from Frontend

- [x] 3.1 In `client/components/chat_message.py`, remove the Markdown-stripping regex block from `strip_markdown_formatting()` (lines ~14-26)
- [x] 3.2 Verify that `[Page N]` stripping (safety net) and conditional `[Source N]` stripping are preserved after the change

## 4. Update Tests

- [x] 4.1 Update `clean_response()` unit tests — add scenarios verifying Markdown formatting is preserved while `[Page N]` and `[Source N]` handling remains correct
- [x] 4.2 Update `strip_markdown_formatting()` unit tests — same scenarios for the frontend function
- [x] 4.3 Run full test suite (`uv run pytest -v`) and fix any failures
