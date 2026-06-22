# Clean Response Toggle

## Purpose

Allow users to optionally skip the `clean_response()` post-processing pipeline for LLM responses, enabling them to receive raw LLM output when the cleaning is too aggressive (e.g., deduplication removes nuance). The toggle is available in the frontend sidebar, passed to the backend as a request parameter, and persisted across sessions alongside other query parameters.

## Requirements

### Requirement: `clean_response` parameter on QueryRequest

The `QueryRequest` schema SHALL include a `clean_response` boolean field that controls whether `clean_response()` is applied to the LLM output.

#### Scenario: Default is True

- **WHEN** a client sends a query request without specifying `clean_response`
- **THEN** the server SHALL default to `clean_response=True`
- **AND** `clean_response()` SHALL be applied to the response

#### Scenario: Explicitly disabled

- **WHEN** a client sends a query request with `clean_response=False`
- **THEN** the server SHALL NOT call `clean_response()`
- **AND** the raw LLM output SHALL be returned as the answer

### Requirement: `clean_response` gated in all query routes

All 3 RAG backend routes (cosine, LangChain, LlamaIndex) and their streaming variants SHALL conditionally apply `clean_response()` based on the `clean_response` request parameter.

#### Scenario: Cosine sync route respects toggle

- **WHEN** a POST request is made to `/api/v1/query` with `clean_response=False`
- **THEN** the server SHALL skip the `clean_response()` call
- **AND** return the raw LLM output as the `answer` field

#### Scenario: LangChain sync route respects toggle

- **WHEN** a POST request is made to `/api/v1/query/langchain` with `clean_response=False`
- **THEN** the server SHALL skip the `clean_response()` call
- **AND** return the raw LLM output as the `answer` field

#### Scenario: LlamaIndex sync route respects toggle

- **WHEN** a POST request is made to `/api/v1/query/llamaindex` with `clean_response=False`
- **THEN** the server SHALL skip the `clean_response()` call
- **AND** return the raw LLM output as the `answer` field

#### Scenario: Streaming endpoints respect toggle

- **WHEN** any streaming endpoint receives a request with `clean_response=False`
- **THEN** the server SHALL stream the raw LLM output tokens without passing through `clean_response()`

### Requirement: Client helpers forward `clean_response`

The frontend sync query helper functions SHALL accept and forward the `clean_response` parameter to the API.

#### Scenario: `clean_response` forwarded in sync cosine query

- **WHEN** `query_sync()` is called with `clean_response=False`
- **THEN** the parameter SHALL be included in the POST request body to `/api/v1/query`
- **AND** the backend SHALL skip `clean_response()`

#### Scenario: `clean_response` forwarded in sync LangChain query

- **WHEN** `query_langchain_sync()` is called with `clean_response=False`
- **THEN** the parameter SHALL be included in the POST request body to `/api/v1/query/langchain`

#### Scenario: `clean_response` forwarded in sync LlamaIndex query

- **WHEN** `query_llamaindex_sync()` is called with `clean_response=False`
- **THEN** the parameter SHALL be included in the POST request body to `/api/v1/query/llamaindex`

### Requirement: Frontend checkbox in sidebar

The Chat page sidebar SHALL include a "Clean Response" checkbox that controls the `clean_response` parameter.

#### Scenario: Checkbox present in sidebar

- **WHEN** the user opens the Chat page
- **THEN** the sidebar SHALL display a "Clean Response" checkbox in the Parameters section
- **AND** the checkbox SHALL default to unchecked (False)
- **AND** the checkbox SHALL be positioned alongside the existing "Show Citations" checkbox

#### Scenario: Toggle affects query behavior

- **WHEN** the user unchecks "Clean Response" and submits a query
- **THEN** the backend SHALL receive `clean_response=False`
- **AND** the response SHALL display raw LLM output

### Requirement: Parameter persistence

The `clean_response` setting SHALL be saved and loaded via the existing `chat_params.json` persistence mechanism, alongside temperature, max_tokens, top_k, prompt_sources, and include_citations.

#### Scenario: Setting saved on button click

- **WHEN** the user clicks "Save Parameters"
- **THEN** the current state of the "Clean Response" checkbox SHALL be saved to `chat_params.json`
- **AND** the saved value SHALL be restored on the next page load

#### Scenario: Setting restored on page load

- **WHEN** the Chat page loads and `chat_params.json` contains `"clean_response": false`
- **THEN** the "Clean Response" checkbox SHALL be unchecked
- **AND** subsequent queries SHALL be sent with `clean_response=False`

#### Scenario: First load without saved params silently gets default

- **WHEN** the Chat page loads and `chat_params.json` does not contain a `"clean_response"` key (e.g., fresh install or upgrade)
- **THEN** `saved_params.get("clean_response", False)` SHALL return `False`
- **AND** the checkbox SHALL be unchecked
- **AND** no migration prompt or notification SHALL be shown