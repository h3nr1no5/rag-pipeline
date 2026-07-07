# Frontend E2E Tests

## ADDED Requirements

### Requirement: test-backend-lifecycle

The frontend e2e test framework SHALL start the FastAPI backend on a random available port before tests and SHALL terminate it after tests complete. The backend subprocess SHALL:
- Use a random, isolated SQLite database file
- Use real LLM and embedder models — no test doubles (async patterns may be related to the rendering bug)
- Use `GET /api/v1/documents/strategies/types` for health check (no auth required, does NOT trigger model lazy-loading)
- Handle SIGTERM gracefully for clean teardown

#### Scenario: Backend starts and responds to health check
- **WHEN** the test fixture starts the backend subprocess
- **THEN** the health endpoint `/api/v1/documents/strategies/types` returns HTTP 200 within 30 seconds

#### Scenario: Backend loads real models on first query
- **WHEN** the first query is submitted to the backend
- **THEN** the LLM and embedder models lazy-load (singletons, ~10-30s)
- **AND** the query completes with a real model-generated answer

### Requirement: test-frontend-lifecycle

The frontend e2e test framework SHALL start the Streamlit frontend on a random available port before tests and SHALL terminate it after tests complete. The Streamlit subprocess SHALL:
- Run in headless mode (`--server.headless=true`)
- Connect to the backend started by the test-backend-lifecycle fixture
- Handle SIGTERM gracefully for clean teardown

#### Scenario: Frontend starts and serves the login page
- **WHEN** the test fixture starts the Streamlit frontend subprocess
- **THEN** the Streamlit UI is accessible via HTTP and serves the login page

### Requirement: test-playwright-browser

The test framework SHALL provide a Playwright browser fixture that opens a Chromium browser in headless mode. The fixture SHALL:
- Create a new browser context for each test (isolated cookies, localStorage)
- Provide a `page` object for DOM interaction
- Close the context and browser after each test

#### Scenario: Browser navigates to frontend URL
- **WHEN** the Playwright page navigates to the Streamlit frontend URL
- **THEN** the page loads and renders the Streamlit app

### Requirement: frontend-e2e-login-upload-query

The end-to-end test SHALL verify the full user flow: login → document upload → submit query → answer displayed in DOM.

#### Scenario: Login flow succeeds
- **WHEN** the user navigates to the Streamlit app
- **AND** fills in email and password fields
- **AND** clicks the Login button
- **THEN** the user is redirected to the chat page
- **AND** the page title contains "Chat with Documents"

#### Scenario: Document upload with api-docs strategy and processing completes
- **WHEN** the authenticated user navigates to the upload page
- **AND** selects the "API Documentation" chunking strategy from the strategy dropdown
- **AND** uploads `tests/docs/test docx.docx`
- **AND** waits for processing to complete
- **THEN** the document appears in the document list on the chat page sidebar
- **AND** the document shows "api-docs" as its chunking strategy

#### Scenario: Query answer appears in the DOM
- **WHEN** the user selects a processed document
- **AND** types `"how to change logo?"` in the chat input
- **AND** presses Enter to submit
- **AND** waits for the query to complete (up to 180s — includes model lazy-loading + real inference)
- **THEN** a chat message from the assistant appears in the DOM
- **AND** the message contains non-empty text content
- **AND** the text is from a real model (not a canned test double response)

### Requirement: test-isolation

Each e2e test SHALL use its own database and browser context to prevent test pollution. The server fixtures (backend + frontend) MAY be session-scoped for performance.

#### Scenario: Test databases are isolated
- **WHEN** two e2e tests run sequentially
- **THEN** each test uses a unique SQLite database file
- **AND** documents uploaded in one test do not appear in the other test's database

#### Scenario: Browser contexts are isolated
- **WHEN** two e2e tests run sequentially
- **THEN** each test starts with a clean browser context (no cookies, no localStorage)
