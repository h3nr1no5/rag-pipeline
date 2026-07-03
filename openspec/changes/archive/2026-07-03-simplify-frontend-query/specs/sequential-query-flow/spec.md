# Sequential Query Flow

## Purpose

Define how the frontend Chat page executes RAG queries sequentially across selected backends, calling each one's existing sync endpoint with per-backend spinner feedback and inline result rendering.

## Requirements

### Requirement: Frontend SHALL call backends sequentially with spinners

When a user submits a question with one or more RAG backends selected, the Chat page SHALL iterate over the selected backends in a fixed order (cosine, LangChain, LlamaIndex) and call each backend's existing sync endpoint. Each backend call SHALL be wrapped in a `st.spinner()` that shows which backend is currently being queried.

#### Scenario: Three backends selected, all succeed
- **WHEN** the user submits a question with cosine, LangChain, and LlamaIndex all selected
- **THEN** the page SHALL show `st.spinner("Querying cosine...")` and call `POST /api/v1/query`
- **THEN** when cosine returns, its answer SHALL render immediately with avatar and label
- **THEN** the page SHALL show `st.spinner("Querying langchain...")` and call `POST /api/v1/query/langchain`
- **THEN** when LangChain returns, its answer SHALL render below the cosine answer
- **THEN** the same pattern SHALL repeat for LlamaIndex via `POST /api/v1/query/llamaindex`

#### Scenario: Single backend selected
- **WHEN** the user submits a question with only one backend selected
- **THEN** only that backend's sync endpoint SHALL be called
- **THEN** the spinner SHALL show that single backend's name

#### Scenario: API docs backend selected
- **WHEN** the user has selected api-docs documents and the API Docs checkbox is checked
- **THEN** the API docs query SHALL be called via `POST /api/v1/query/api-docs` as part of the sequential loop
- **THEN** its result SHALL render with API docs avatar, label, confidence badge, and expandable sections

### Requirement: Backend errors SHALL NOT block other backends

If a backend call returns an HTTP error or transport error, the error SHALL be displayed inline for that backend and the loop SHALL continue to the next backend.

#### Scenario: Middle backend fails
- **WHEN** cosine succeeds, LangChain returns HTTP 500, and LlamaIndex is also selected
- **THEN** the cosine answer SHALL render normally
- **THEN** an `st.error()` SHALL show for LangChain with the error details
- **THEN** the LlamaIndex call SHALL execute and render its answer

#### Scenario: All backends fail
- **WHEN** all selected backend endpoints return errors
- **THEN** each error SHALL be displayed inline for its corresponding backend
- **THEN** no new assistant messages SHALL be added to the session state

### Requirement: Responses SHALL be cached independently

Each backend's sync endpoint handles its own caching (per-backend cache keys with `_langchain`, `_llamaindex` suffixes). The frontend SHALL NOT add additional caching logic.

#### Scenario: Cached response from backend
- **WHEN** the backend returns `{"cached": true}` for a backend call
- **THEN** the frontend SHALL render the cached answer identically to a fresh one
- **THEN** the cached indicator from the backend SHALL be displayed if present

### Requirement: Session state SHALL persist completed answers

After all backends complete, the rendered answers SHALL be appended to `st.session_state.messages` with their rag_type, content, sources, and include_citations flag, so they survive page reruns.

#### Scenario: All answers stored after loop
- **WHEN** the sequential loop finishes (all backends succeeded or errored)
- **THEN** all backend answers with content SHALL be appended to `st.session_state.messages`
- **THEN** the messages SHALL be in the original selection order
