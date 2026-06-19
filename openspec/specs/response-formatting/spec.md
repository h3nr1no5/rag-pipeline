# Response Formatting

## Purpose

Consistent post-generation response formatting across all RAG query backends (cosine, LangChain, LlamaIndex) — stripping `[Page N]` artifacts unconditionally, conditionally preserving `[Source N]` citations based on user preference, and ensuring streaming endpoints buffer-then-clean so no raw LLM output reaches the client.

## Requirements

### Requirement: Strip `[Page N]` from LLM context before prompting

The `build_prompt()` function SHALL remove `[Page N]` markers from chunk content before presenting it as context to the LLM. This prevents the LLM from reproducing page-number artifacts in its output.

#### Scenario: `[Page N]` stripped from context text

- **WHEN** `build_prompt()` is called with chunks whose content contains `[Page N]` markers at line start
- **THEN** the context text provided to the LLM SHALL NOT contain `[Page N]` markers
- **AND** the rest of the chunk content SHALL be preserved

#### Scenario: `[Page N]` stripped regardless of `include_citations` flag

- **WHEN** `build_prompt()` is called with `include_citations=True` or `include_citations=False`
- **THEN** `[Page N]` markers SHALL be stripped from context in both cases

#### Scenario: Non-PDF chunks unaffected

- **WHEN** chunk content does not begin with a `[Page N]` marker
- **THEN** `build_prompt()` SHALL NOT modify the chunk content

### Requirement: Citation instruction conditional on `include_citations`

The `build_prompt()` function SHALL conditionally include the `[Source N]` citation instruction in the system prompt based on the `include_citations` parameter. Context chunks SHALL always be prefixed with `[Source N]` labels to ensure proper prompt template splitting.

#### Scenario: Citation instruction included when True

- **WHEN** `build_prompt()` is called with `include_citations=True`
- **THEN** the system message SHALL include the instruction: *"For EVERY factual statement you make, you MUST include a source citation in brackets like [Source 1]"*
- **AND** context chunks SHALL be prefixed with `[Source N]` labels

#### Scenario: Source labels always present, citation instruction omitted when False

- **WHEN** `build_prompt()` is called with `include_citations=False`
- **THEN** the system message SHALL NOT include any citation instruction
- **AND** context chunks SHALL still be prefixed with `[Source N]` labels (unchanged from the True case)
- **AND** the LLM SHALL NOT be asked to cite sources

### Requirement: `clean_response` always strips `[Page N]`

The `clean_response()` function SHALL always remove `[Page N]` references from the LLM response text, regardless of the `include_citations` parameter.

#### Scenario: `[Page N]` stripped from response

- **WHEN** the LLM output contains `[Page 3]` or `[Page 10]:` text
- **THEN** `clean_response()` SHALL remove those markers
- **AND** replace them with a single space to preserve word boundaries

#### Scenario: Multiple page references stripped

- **WHEN** the LLM output contains multiple `[Page N]` references throughout the text
- **THEN** all such references SHALL be removed

### Requirement: `clean_response` conditionally strips `[Source N]`

The `clean_response()` function SHALL conditionally remove `[Source N]` citations from the LLM response based on the `include_citations` parameter.

#### Scenario: `[Source N]` preserved when True

- **WHEN** `clean_response()` is called with `include_citations=True`
- **THEN** `[Source N]` markers SHALL be preserved in the output

#### Scenario: `[Source N]` stripped when False

- **WHEN** `clean_response()` is called with `include_citations=False`
- **THEN** `[Source N]` markers SHALL be removed from the output

### Requirement: All streaming endpoints buffer then stream cleaned text

Each streaming query endpoint SHALL buffer the full LLM response, apply `clean_response()`, then stream the cleaned text to the client. No raw LLM output SHALL reach the client without passing through `clean_response()`.

#### Scenario: Cosine streaming endpoint buffers and cleans

- **WHEN** a client connects to `POST /api/v1/query/stream`
- **THEN** the server SHALL accumulate all LLM output tokens before streaming them to the client
- **AND** the accumulated text SHALL be passed through `clean_response()`
- **AND** only the cleaned text SHALL be streamed as SSE `token` events
- **AND** the client SHALL NOT receive both raw and cleaned versions

#### Scenario: LangChain streaming endpoint already correct

- **WHEN** a client connects to `POST /api/v1/query/langchain/stream`
- **THEN** behavior is already correct (buffers, verifies, cleans, then streams)
- **AND** no changes are needed

#### Scenario: LlamaIndex streaming endpoint buffers and cleans

- **WHEN** a client connects to `POST /api/v1/query/llamaindex/stream`
- **THEN** the server SHALL accumulate all LLM output tokens before streaming them to the client
- **AND** the accumulated text SHALL be passed through `clean_response()`
- **AND** only the cleaned text SHALL be streamed as SSE `token` events
- **AND** the cached response SHALL be the cleaned text

#### Scenario: Non-streaming endpoints continue working

- **WHEN** a client uses `POST /api/v1/query`, `/langchain`, or `/llamaindex` (non-streaming)
- **THEN** behavior is unchanged — `clean_response()` is already called before returning the response

### Requirement: Streaming SSE includes sources before tokens

All streaming endpoints SHALL send the `sources` event before sending `token` events, so the client can display source metadata alongside the response.

#### Scenario: Sources sent before tokens in cosine stream

- **WHEN** a streaming response is generated via `POST /api/v1/query/stream`
- **THEN** the first SSE event SHALL contain the `sources` data
- **AND** subsequent events SHALL contain only `token` data until `[DONE]`

#### Scenario: Sources sent before tokens in LlamaIndex stream

- **WHEN** a streaming response is generated via `POST /api/v1/query/llamaindex/stream`
- **THEN** the first SSE event SHALL contain the `sources` data
- **AND** subsequent events SHALL contain only `token` data until `[DONE]`

### Requirement: Client display respects citation state

The client-side `strip_markdown_formatting()` function SHALL conditionally strip `[Source N]` markers based on whether citations should be shown.

#### Scenario: `[Source N]` stripped when citations hidden

- **WHEN** the response was generated with `include_citations=False`
- **THEN** the client display SHALL strip `[Source N]` markers from the rendered text
- **AND** the sources metadata SHALL still be available in the expander

#### Scenario: `[Source N]` shown when citations visible

- **WHEN** the response was generated with `include_citations=True`
- **THEN** the client display SHALL preserve `[Source N]` markers in the rendered text

### Requirement: `[Page N]` stripped by client as safety net

The client-side `strip_markdown_formatting()` function SHALL always strip `[Page N]` markers from displayed text as a defense-in-depth measure.

#### Scenario: `[Page N]` stripped client-side

- **WHEN** any response text contains `[Page N]` markers
- **THEN** the client display SHALL strip them unconditionally

---

## ADDED Requirements

### Requirement: Markdown formatting preserved in LLM responses

The `clean_response()` function SHALL preserve Markdown formatting (bold, italic, headings, lists, horizontal rules, strikethrough) in the LLM output. It SHALL continue to strip `[Page N]` markers and conditionally strip `[Source N]` markers based on `include_citations`.

#### Scenario: Bold text preserved

- **WHEN** the LLM output contains `**bold text**` or `__bold text__`
- **THEN** `clean_response()` SHALL NOT modify the bold markers
- **AND** the rendered response SHALL display bold text

#### Scenario: Italic text preserved

- **WHEN** the LLM output contains `*italic text*` or `_italic text_`
- **THEN** `clean_response()` SHALL NOT modify the italic markers
- **AND** the rendered response SHALL display italic text

#### Scenario: Headings preserved

- **WHEN** the LLM output contains `# `, `## `, `### ` headings
- **THEN** `clean_response()` SHALL NOT remove the heading markers
- **AND** the rendered response SHALL display headings

#### Scenario: Lists preserved

- **WHEN** the LLM output contains bullet lists (`- item`) or numbered lists (`1. item`)
- **THEN** `clean_response()` SHALL NOT modify list markers
- **AND** the rendered response SHALL display formatted lists

#### Scenario: Horizontal rules preserved

- **WHEN** the LLM output contains `---` or `***` on its own line
- **THEN** `clean_response()` SHALL NOT remove the horizontal rule
- **AND** the rendered response SHALL display a horizontal rule

#### Scenario: Strikethrough preserved

- **WHEN** the LLM output contains `~~strikethrough text~~`
- **THEN** `clean_response()` SHALL NOT modify the strikethrough markers
- **AND** the rendered response SHALL display strikethrough text

#### Scenario: `[Page N]` still stripped

- **WHEN** the LLM output contains `[Page 3]` markers
- **THEN** `clean_response()` SHALL still remove them (unchanged behavior)
- **AND** `[Source N]` markers SHALL still be conditionally stripped based on `include_citations`

### Requirement: Frontend preserves Markdown formatting in display

The client-side `strip_markdown_formatting()` function SHALL preserve Markdown formatting (bold, italic, headings, lists) in displayed text. It SHALL continue to strip `[Page N]` markers as a safety net and conditionally strip `[Source N]` markers based on `include_citations`.

#### Scenario: Frontend preserves bold/italic/headings

- **WHEN** response text contains Markdown formatting (`**bold**`, `*italic*`, `# heading`)
- **THEN** `strip_markdown_formatting()` SHALL NOT modify Markdown markers
- **AND** `st.markdown()` SHALL render them as formatted text

#### Scenario: Frontend continues to strip `[Page N]`

- **WHEN** response text contains `[Page N]` markers
- **THEN** `strip_markdown_formatting()` SHALL still remove them (defense in depth)
- **AND** `[Source N]` markers SHALL still be conditionally stripped

### Requirement: LLM prompted to use Markdown formatting

The `build_prompt()` function SHALL instruct the LLM to use Markdown formatting in its response, replacing the current instruction that prohibits it.

#### Scenario: Prompt encourages formatting

- **WHEN** `build_prompt()` constructs the system message
- **THEN** the instruction SHALL tell the LLM to use headings, bold, and lists as appropriate
- **AND** the instruction SHALL NOT tell the LLM to avoid Markdown formatting

#### Scenario: Citation instruction unchanged

- **WHEN** `build_prompt()` is called with `include_citations=True`
- **THEN** the citation instruction SHALL still be included (unchanged)
- **AND** context chunks SHALL still be prefixed with `[Source N]` labels
