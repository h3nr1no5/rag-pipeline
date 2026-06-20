## Context

RAG query responses pass through a three-layer formatting pipeline before reaching the user:

```
LLM output → clean_response() → JSON API → strip_markdown_formatting() → st.markdown()
```

Currently, **all three layers** actively strip Markdown formatting:

1. **Prompt** tells the LLM: "plain text without Markdown formatting (no headings, no bold, no italics)"
2. **`clean_response()`** applies regexes that strip `# headings`, `**bold**`, `*italic*`, `__underline__`, `~~strikethrough~~`
3. **`strip_markdown_formatting()`** in the frontend does the same stripping as defense-in-depth

The result is that responses lose all visual structure — no way to emphasize key terms, no section hierarchy, no visual scanning. The existing `response-formatting` spec covers `[Page N]` and `[Source N]` handling but doesn't address Markdown formatting at all.

## Goals / Non-Goals

**Goals:**
- Restore Markdown formatting (bold, italic, headings, lists) in RAG responses
- Keep `[Page N]` stripping in both backend and frontend (parser artifacts)
- Keep conditional `[Source N]` stripping based on `include_citations`
- Ensure streaming endpoints still buffer-then-clean (no raw tokens)
- Update the LLM prompt to encourage structured output
- Update tests to reflect new behavior

**Non-Goals:**
- Not changing how `[Source N]` labels are handled in the prompt context (they stay for prompt-template splitting)
- Not changing the `[Page N]` stripping from context chunks (happens before LLM sees them)
- Not introducing new API parameters or frontend controls
- Not changing the verification system or cache layer

## Decisions

### Decision 1: Remove Markdown regexes from `clean_response()`, keep artifact stripping

**Rationale:** The Markdown regexes were added as a blunt fix for inconsistent LLM output. Instead of fixing the root cause (the prompt), they stripped all formatting indiscriminately. By fixing the prompt to produce clean Markdown, we no longer need regex-level stripping.

**What stays:**
- `[Page N]` stripping → parser artifacts, not user-facing
- `[Source N]` stripping (conditional) → user control via `include_citations`
- Repetition detection → still guards against degenerate output
- Token artifact stripping → `<|endoftext|>`, `[INST]`, etc.
- Line deduplication → still valuable

**What goes:**
- `re.sub(r'^#+\s+', ...)` → heading removal
- `re.sub(r'\*\*(.+?)\*\*', ...)` → bold removal
- `re.sub(r'__.+?__', ...)` → underline bold removal
- `re.sub(r'\*(.+?)\*', ...)` → italic removal
- `re.sub(r'_(.+?)_', ...)` → italic removal
- `re.sub(r'~~.+?~~', ...)` → strikethrough removal
- `re.sub(r'^[\s]*[-*_]{3,}[\s]*$', ...)` → horizontal rule removal

### Decision 2: Mirror the same change in frontend `strip_markdown_formatting()`

**Rationale:** The frontend function was added as defense-in-depth, duplicating the backend stripping. With the backend no longer stripping formatting, the frontend should follow suit. The only client-side stripping that remains is `[Page N]` (safety net) and `[Source N]` (based on citation state).

### Decision 3: Update the prompt to encourage, not ban, formatting

**Current instruction:**
```
Present information in plain text without Markdown formatting
(no headings, no bold, no italics). Use simple paragraphs and
bullet points if needed.
```

**New instruction:**
```
Structure your response clearly using Markdown formatting — you
may use headings, bold for emphasis, and bullet points for lists.
Keep paragraphs concise and avoid repetition.
```

**Rationale:** The LLM's training data is rich in Markdown-formatted text (documentation, READMEs, wikis). Tapping into this natural capability produces better-structured output than fighting it.

### Decision 4: No changes to streaming architecture

Each streaming endpoint already buffers the full response, calls `clean_response()`, then streams the cleaned text. This doesn't change — the buffer-and-clean pattern stays. The only difference is `clean_response()` now preserves Markdown instead of stripping it.

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| LLM produces malformed/inconsistent Markdown | The prompt gives clear guidance. Users can toggle `include_citations` to control citation visibility. If quality issues emerge, we can tune the prompt further rather than blanket-stripping. |
| Some users prefer plain-text responses | The `response_length` parameter remains — "concise" mode still produces brief answers. Full plain-text mode could be added later as a new parameter if needed. |
| Existing tests expect stripped formatting | Tests for `clean_response()` and `strip_markdown_formatting()` need updating. Test scenarios should verify that Markdown is preserved while `[Page N]` and `[Source N]` are correctly handled. |
| Bold/headings could make responses look noisy | The prompt emphasizes "clear structure" and "concise paragraphs." Detailed responses benefit most from formatting; concise/normal modes are naturally shorter and less likely to over-format. |
