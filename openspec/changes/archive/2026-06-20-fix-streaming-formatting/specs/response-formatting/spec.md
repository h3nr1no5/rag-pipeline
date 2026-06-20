## MODIFIED Requirements

### Requirement: All streaming endpoints buffer then stream cleaned text

Each streaming query endpoint SHALL buffer the full LLM response, apply `clean_response()`, then stream the cleaned text to the client. No raw LLM output SHALL reach the client without passing through `clean_response()`. The streaming endpoints remain available for API consumers but the primary Chat frontend SHALL use sync (buffered) endpoints instead.

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

#### Scenario: Primary Chat frontend uses sync endpoints

- **WHEN** the user submits a question in the Chat page
- **THEN** the frontend SHALL call the sync (non-streaming) endpoint for the selected RAG backend
- **AND** the frontend SHALL display a spinner indicator while the response is being generated
- **AND** the full response SHALL be rendered using `st.markdown()` once received
- **AND** Markdown formatting (headings, bold, lists, paragraphs) SHALL be preserved in the displayed response

## ADDED Requirements

### Requirement: Sync client helpers pass `include_citations`

The frontend sync query helpers (`query_sync()`, `query_langchain_sync()`, `query_llamaindex_sync()`) SHALL accept and forward the `include_citations` parameter to the API, matching the capability already provided by the streaming helpers.

#### Scenario: `include_citations` forwarded in sync cosine query

- **WHEN** `query_sync()` is called with `include_citations=False`
- **THEN** the parameter SHALL be included in the POST request body to `/api/v1/query`
- **AND** the backend SHALL strip `[Source N]` markers from the response

#### Scenario: `include_citations` forwarded in sync LangChain query

- **WHEN** `query_langchain_sync()` is called with `include_citations=True`
- **THEN** the parameter SHALL be included in the POST request body to `/api/v1/query/langchain`
- **AND** the response SHALL preserve `[Source N]` markers

#### Scenario: `include_citations` forwarded in sync LlamaIndex query

- **WHEN** `query_llamaindex_sync()` is called with `include_citations=True`
- **THEN** the parameter SHALL be included in the POST request body to `/api/v1/query/llamaindex`
- **AND** the response SHALL preserve `[Source N]` markers

## REMOVED Requirements

### Requirement: Unused streaming client functions removed

**Reason**: These functions are no longer used by the Chat page after migrating to sync endpoints. They add maintenance burden and testing surface without purpose.

**Migration**: The single Chat page caller is updated to use sync equivalents. Any external consumers of these functions should migrate to the sync helpers or call the streaming API directly via `requests`.

Functions removed:
- `_strip_display_text()` — stripped `**bold**` and `# ` heading markers (also duplicated `strip_markdown_formatting()` concerns)
- `stream_query()` — unused simple streaming client
- `stream_query_with_placeholder()` — replaced by `query_sync()`
- `stream_query_langchain()` / `stream_query_langchain_with_placeholder()` — replaced by `query_langchain_sync()`
- `stream_query_llamaindex()` / `stream_query_llamaindex_with_placeholder()` — replaced by `query_llamaindex_sync()`
