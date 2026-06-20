# Response Formatting — Delta Spec

## Purpose

This delta spec modifies the existing `response-formatting` capability to make `clean_response()` conditionally applied based on the new `clean_response` request parameter, rather than being always applied.

## MODIFIED Requirements

### Requirement: `clean_response` always strips `[Page N]`

The `clean_response()` function SHALL always remove `[Page N]` references from the LLM response text, regardless of the `include_citations` parameter. This only applies when `clean_response=True` (the default). When `clean_response=False`, the function is not called and raw LLM output is returned.

#### Scenario: `[Page N]` stripped from response when enabled

- **WHEN** `clean_response=True` and the LLM output contains `[Page 3]` or `[Page 10]:` text
- **THEN** `clean_response()` SHALL remove those markers
- **AND** replace them with a single space to preserve word boundaries

#### Scenario: Multiple page references stripped when enabled

- **WHEN** `clean_response=True` and the LLM output contains multiple `[Page N]` references throughout the text
- **THEN** all such references SHALL be removed

#### Scenario: `[Page N]` not stripped when toggle is off

- **WHEN** `clean_response=False`
- **THEN** `clean_response()` SHALL NOT be called
- **AND** `[Page N]` markers SHALL remain in the response (client-side `strip_markdown_formatting()` still strips them as defense-in-depth)

### Requirement: `clean_response` conditionally strips `[Source N]`

The `clean_response()` function SHALL conditionally remove `[Source N]` citations from the LLM response based on the `include_citations` parameter. This only applies when `clean_response=True`. When `clean_response=False`, `[Source N]` markers remain in the raw output regardless of `include_citations`.

#### Scenario: `[Source N]` preserved when enabled with citations

- **WHEN** `clean_response=True` and `include_citations=True`
- **THEN** `[Source N]` markers SHALL be preserved in the output

#### Scenario: `[Source N]` stripped when enabled without citations

- **WHEN** `clean_response=True` and `include_citations=False`
- **THEN** `[Source N]` markers SHALL be removed from the output

#### Scenario: `[Source N]` behavior when toggle is off

- **WHEN** `clean_response=False`
- **THEN** `[Source N]` markers SHALL NOT be stripped server-side regardless of `include_citations`
- **AND** `include_citations` still controls the prompt instruction (LLM is asked to cite or not)
- **AND** client-side `strip_markdown_formatting()` still conditionally strips `[Source N]` based on `include_citations`

### Requirement: All streaming endpoints buffer then optionally stream cleaned text

Each streaming query endpoint SHALL buffer the full LLM response. When `clean_response=True`, the buffered text SHALL be passed through `clean_response()` before streaming. When `clean_response=False`, the raw buffered text SHALL be streamed directly.

#### Scenario: Cosine streaming endpoint buffers and cleans when enabled

- **WHEN** a client connects to `POST /api/v1/query/stream` with `clean_response=True`
- **THEN** the server SHALL accumulate all LLM output tokens before streaming them to the client
- **AND** the accumulated text SHALL be passed through `clean_response()`
- **AND** only the cleaned text SHALL be streamed as SSE `token` events

#### Scenario: Cosine streaming endpoint streams raw when disabled

- **WHEN** a client connects to `POST /api/v1/query/stream` with `clean_response=False`
- **THEN** the server SHALL accumulate all LLM output tokens
- **AND** the accumulated text SHALL NOT be passed through `clean_response()`
- **AND** the raw text SHALL be streamed as SSE `token` events

#### Scenario: LangChain streaming endpoint respects toggle

- **WHEN** a client connects to `POST /api/v1/query/langchain/stream` with `clean_response=True`
- **THEN** behavior is already correct (buffers, verifies, cleans, then streams)

#### Scenario: LlamaIndex streaming endpoint buffers and conditionally cleans

- **WHEN** a client connects to `POST /api/v1/query/llamaindex/stream` with `clean_response=True`
- **THEN** the server SHALL accumulate all LLM output tokens before streaming them to the client
- **AND** the accumulated text SHALL be passed through `clean_response()`
- **AND** only the cleaned text SHALL be streamed as SSE `token` events

#### Scenario: Non-streaming endpoints respect toggle

- **WHEN** a client uses `POST /api/v1/query`, `/langchain`, or `/llamaindex` (non-streaming) with `clean_response=False`
- **THEN** `clean_response()` SHALL NOT be called before returning the response

## ADDED Requirements

### Requirement: All query routes gate `clean_response` on request parameter

Each query route handler SHALL check the `clean_response` boolean from the request before calling `clean_response()`. The function SHALL only be called when the parameter is `True`.

#### Scenario: Sync endpoints check parameter

- **WHEN** any sync endpoint handler (cosine, LangChain, LlamaIndex) processes a response
- **THEN** the handler SHALL evaluate `request.clean_response`
- **AND** SHALL call `clean_response()` only when the value is `True`
- **AND** SHALL use the raw LLM output directly when `False`

### Requirement: Include citations independently controlled

The `include_citations` parameter SHALL continue to independently control citation behavior in the prompt and client-side display, regardless of the `clean_response` toggle.

#### Scenario: Citations in prompt controlled by `include_citations`

- **WHEN** `include_citations=True` and `clean_response=False`
- **THEN** the LLM SHALL still be instructed to cite sources
- **AND** `[Source N]` markers SHALL appear in the raw output

#### Scenario: Client-side citation stripping still applies

- **WHEN** `include_citations=False` and `clean_response=False`
- **THEN** the client-side `strip_markdown_formatting()` SHALL still remove `[Source N]` markers from the displayed text
