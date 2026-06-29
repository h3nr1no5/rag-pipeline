## ADDED Requirements

### Requirement: Set error key for transport failures in query functions
All 4 query functions (`query_sync`, `query_langchain_sync`, `query_llamaindex_sync`, `api_docs_query`) SHALL include an `"error"` key in the response dictionary when a transport exception (timeout, connection error) occurs.

#### Scenario: Transport exception in query_sync
- **WHEN** `requests.post()` raises a `requests.exceptions.Timeout` or other transport exception
- **THEN** the returned dictionary SHALL contain `"error": "transport_error"` in addition to the answer text

#### Scenario: Transport exception in query_langchain_sync
- **WHEN** `requests.post()` raises a transport exception in the LangChain query function
- **THEN** the returned dictionary SHALL contain `"error": "transport_error"`
- **AND** the answer text SHALL indicate the LangChain query timed out

### Requirement: Set error key for HTTP error responses
All 4 query functions SHALL include an `"error"` key when the server returns a non-200 HTTP status.

#### Scenario: HTTP 500 in query_langchain_sync
- **WHEN** the backend returns HTTP 500 for a LangChain query
- **THEN** the returned dictionary SHALL contain `"error": "http_error"`
- **AND** the answer text SHALL indicate the server encountered an error

### Requirement: Chat page renders transport errors via st.error()
The Chat page SHALL display transport error responses using `st.error()` instead of rendering them as normal assistant chat messages.

#### Scenario: Transport error displayed correctly
- **WHEN** the result dictionary contains `"error": "transport_error"`
- **THEN** the Chat page SHALL call `st.error()` with the answer text
- **AND** SHALL NOT add the message to the chat history as a normal assistant message

#### Scenario: HTTP error displayed correctly
- **WHEN** the result dictionary contains `"error": "http_error"`
- **THEN** the Chat page SHALL call `st.error()` with the answer text
- **AND** SHALL NOT add the message to the chat history as a normal assistant message

### Requirement: Clear timeout language in error messages
The error messages for transport errors SHALL use clear, actionable language that explains what happened and suggests retrying.

#### Scenario: Timeout error message for LangChain
- **WHEN** a LangChain query times out (transport error)
- **THEN** the answer text SHALL be: `"LangChain query timed out after 180s. Please try again or rephrase your question."`

#### Scenario: Generic transport error message
- **WHEN** a non-timeout transport error occurs (e.g., connection refused)
- **THEN** the answer text SHALL be: `"Unable to connect to the server. Please check that the backend is running and try again."`
