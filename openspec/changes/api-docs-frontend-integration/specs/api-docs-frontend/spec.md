## ADDED Requirements

### Requirement: Upload page SHALL offer "API Documentation" chunking strategy

The upload document page SHALL list "API Documentation" as a selectable chunking strategy. When selected, chunking parameters that are irrelevant to the API Doc pipeline SHALL be hidden or disabled.

#### Scenario: API Documentation strategy selectable
- **WHEN** a user opens the document upload page
- **THEN** the strategy dropdown SHALL include "API Documentation" as an option
- **AND** selecting it SHALL set `strategy_id="api-docs"` on the upload request

#### Scenario: Irrelevant parameters hidden for API Docs strategy
- **WHEN** the user selects "API Documentation" strategy
- **THEN** the `chunk_size` slider SHALL be hidden
- **THEN** the `chunk_overlap` slider SHALL be hidden
- **THEN** the `separators` input SHALL be hidden
- **THEN** the `use_hyperlinks` checkbox SHALL be hidden
- **AND** a note SHALL be displayed: "API documentation uses structure-aware extraction. Standard chunking parameters do not apply."

### Requirement: Chat page SHALL show 4th "API Docs" backend selector

The chat page SHALL detect when selected documents include any with `engine_type="api-docs"` and show a 4th "API Docs" backend checkbox alongside Cosine Similarity, LangChain, and LlamaIndex.

#### Scenario: API Docs checkbox appears when API docs selected
- **WHEN** a user selects at least one document whose strategy has `engine_type="api-docs"`
- **THEN** a 4th checkbox labeled "🔶 API Docs" SHALL appear in the backend selector
- **AND** it SHALL be unchecked by default

#### Scenario: API Docs checkbox hidden when no API docs selected
- **WHEN** a user selects only documents with `engine_type="recursive"` or `"semantic"`
- **THEN** the "🔶 API Docs" checkbox SHALL NOT appear
- **AND** the query SHALL NOT be routeable to the API Doc pipeline

### Requirement: Chat page SHALL route API doc queries to the correct endpoint

When the "API Docs" checkbox is checked, the chat page SHALL route the query to `POST /query/api-docs` with the first selected API doc's `document_id` instead of the standard `POST /query` endpoint.

#### Scenario: Query routes to /query/api-docs
- **WHEN** the user has "🔶 API Docs" checked and submits a query
- **THEN** the frontend SHALL call `POST /api/v1/query/api-docs` with `{"query": "...", "document_id": "<first api-doc document id>", "top_k": 10}`
- **AND** other selected backends SHALL be ignored for the API doc routing (API docs use their own pipeline)

#### Scenario: Multiple API docs selected
- **WHEN** the user selects multiple documents with `engine_type="api-docs"`
- **THEN** the frontend SHALL use the first API doc's `document_id` for the query
- **AND** a note SHALL indicate which document is being queried

### Requirement: Response display SHALL show API doc-specific fields

When the response comes from the API Doc pipeline, the chat UI SHALL display the extended response fields (confidence, relevant_functions, relevant_types) in a dedicated section below the answer.

#### Scenario: Show confidence badge
- **WHEN** the API doc response includes a `confidence` value
- **THEN** the UI SHALL display a confidence badge (e.g., "High", "Medium", "Low" based on thresholds 0.7/0.4)
- **AND** SHALL color-code it: green ≥ 0.7, yellow ≥ 0.4, red < 0.4

#### Scenario: Show relevant functions and types
- **WHEN** the API doc response includes non-empty `relevant_functions` or `relevant_types` arrays
- **THEN** the UI SHALL display them as expandable sections below the answer
- **AND** each function/type SHALL be shown as a clickable tag or chip

### Requirement: Frontend SHALL have an api_docs_query utility function

The `client/utils/query.py` module SHALL have an `api_docs_query()` function that constructs and sends requests to the API Doc query endpoint.

#### Scenario: api_docs_query function interface
- **WHEN** `api_docs_query(api_base_url, token, query_text, document_id, top_k=10)` is called
- **THEN** it SHALL send a POST request to `{api_base_url}/api/v1/query/api-docs`
- **THEN** it SHALL send the request body as `{"query": query_text, "document_id": document_id, "top_k": top_k}`
- **THEN** it SHALL include the auth token header
- **AND** it SHALL return the parsed JSON response
