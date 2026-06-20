## Why

RAG responses are currently flattened to plain text — all Markdown formatting (bold, headings, italic, structured lists) is stripped by both the backend `clean_response()` and the frontend `strip_markdown_formatting()`. The LLM prompt itself actively tells the model to avoid formatting ("plain text without Markdown formatting"). The result is dense, hard-to-scan walls of text, especially for "detailed" responses where structure matters most. Users want easy-to-read, visually structured responses without inline `[Source N]` citations cluttering the answer body.

## What Changes

- **Prompt instruction updated**: `build_prompt()` now tells the LLM to use Markdown formatting (headings, bold, lists) instead of banning it
- **Markdown stripping removed from `clean_response()`**: The regexes that strip `# headings`, `**bold**`, `*italic*`, `__underlines__`, and `~~strikethrough~~` are removed — but `[Page N]` stripping and conditional `[Source N]` stripping are preserved
- **Markdown stripping removed from frontend `strip_markdown_formatting()`**: Same change on the client side — only artifact/citation markers are stripped
- **No change to `[Source N]` behavior**: Citations are still stripped from the response body when `include_citations=False`, and preserved when `True`

## Capabilities

### New Capabilities

None — this modifies the existing `response-formatting` capability.

### Modified Capabilities

- `response-formatting`: The spec currently only covers `[Page N]` and `[Source N]` handling. Two new requirements are added:
  1. **Markdown formatting preserved in responses** — `clean_response()` shall NOT strip Markdown formatting (bold, italic, headings, lists)
  2. **LLM instructed to use formatting** — `build_prompt()` shall encourage structured Markdown output instead of banning it

## Impact

- `src/domain/services/prompt_builder.py`
  - `build_prompt()` — change the formatting instruction in the system prompt
  - `clean_response()` — remove Markdown-stripping regex block (lines 167-174)
- `client/components/chat_message.py`
  - `strip_markdown_formatting()` — remove Markdown-stripping regex block (lines 14-26)
- All 3 RAG backends (cosine, LangChain, LlamaIndex) — they all pass through `clean_response()`
- Tests: unit tests for `clean_response()` and `strip_markdown_formatting()` will need updating
