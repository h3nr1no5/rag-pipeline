## Purpose

TBD — Performance optimizations for the test suite, including fixture overrides, shared helpers, middleware suppression, LLM test guards, ASGITransport migration, sleep removal, lazy imports, and atexit cleanup.

## Requirements

### Requirement: Unit and pdf_semantic_chunking tests override root autouse fixtures
Tests in `tests/unit/` and `tests/pdf_semantic_chunking/` that do not require database access, upload directory interaction, or background task management SHALL override the root conftest's autouse fixtures as no-ops. The overrides SHALL be defined in `tests/unit/conftest.py` and `tests/pdf_semantic_chunking/conftest.py` respectively.

Three fixtures SHALL be overridden:
- `setup_test_db`: No-op — no database engine creation, migration, seeding, or teardown
- `clean_uploads_dir`: No-op — no filesystem scan of upload directory
- `cancel_background_tasks`: No-op — no asyncio task enumeration or cancellation

#### Scenario: Unit test runs without database setup
- **WHEN** any test in `tests/unit/` runs
- **THEN** the `setup_test_db` fixture SHALL NOT create a SQLite engine
- **AND** the `setup_test_db` fixture SHALL NOT run migrations
- **AND** the `setup_test_db` fixture SHALL NOT seed strategy data
- **AND** the `setup_test_db` fixture SHALL NOT tear down any database

#### Scenario: Unit test runs without upload directory scan
- **WHEN** any test in `tests/unit/` runs
- **THEN** the `clean_uploads_dir` fixture SHALL NOT scan `./data/uploads/`

#### Scenario: Unit test runs without background task cancellation
- **WHEN** any test in `tests/unit/` runs
- **THEN** the `cancel_background_tasks` fixture SHALL NOT enumerate or cancel asyncio tasks

#### Scenario: pdf_semantic_chunking test runs without database setup
- **WHEN** any test in `tests/pdf_semantic_chunking/` runs
- **THEN** all three autouse fixtures SHALL behave identically to the unit test overrides

### Requirement: Shared `wait_for_document` helper in integration conftest
The system SHALL provide a shared `wait_for_document()` function in `tests/integration/conftest.py` that all integration tests import and use. This helper SHALL replace all 7 copy-pasted `upload_and_wait_for_document()` implementations.

The helper SHALL:
- Accept `client`, `document_id`, optional `poll_interval` (default 0.1s), and optional `timeout` (default 30s)
- Use `time.monotonic()` for elapsed time tracking
- Poll at the configured interval using `asyncio.sleep(poll_interval)`
- NOT add any extra "settling" sleep after completion
- Raise `pytest.fail` on timeout or processing failure

#### Scenario: Shared helper polls document until completed
- **WHEN** `wait_for_document(client, doc_id)` is called
- **AND** the document processing completes within the timeout
- **THEN** the function SHALL return the status dict from the API
- **AND** the function SHALL NOT sleep after the status returns "completed"

#### Scenario: Shared helper fails on timeout
- **WHEN** `wait_for_document(client, doc_id)` is called
- **AND** the document does not complete within the timeout
- **THEN** the function SHALL raise `pytest.fail` with a timeout message

#### Scenario: Shared helper fails on processing error
- **WHEN** `wait_for_document(client, doc_id)` is called
- **AND** the document status returns "failed"
- **THEN** the function SHALL raise `pytest.fail` with the error message from the API

### Requirement: Centralized `auth_client` fixture in integration conftest
The system SHALL provide a shared `auth_client` fixture in `tests/integration/conftest.py` that creates a unique user, authenticates via signup+login, and returns an authorized HTTPX client. All integration test files SHALL import this fixture instead of defining their own.

#### Scenario: Auth client fixture creates unique user
- **WHEN** `auth_client` fixture is used in a test
- **THEN** it SHALL sign up a new user with a unique email address
- **AND** it SHALL log in and set the `Authorization` header on the client
- **AND** it SHALL yield the authenticated client to the test

### Requirement: MonitoringMiddleware disabled during tests
The `MonitoringMiddleware` SHALL NOT be registered on the FastAPI app when the `TESTING` environment variable is set to `1`. This prevents per-request logging overhead during test execution.

#### Scenario: Middleware omitted when TESTING=1
- **WHEN** the environment variable `TESTING=1` is set
- **AND** the FastAPI app starts
- **THEN** `MonitoringMiddleware` SHALL NOT be added to the middleware stack
- **AND** all API routes SHALL still function correctly without monitoring

#### Scenario: Middleware present in normal operation
- **WHEN** the `TESTING` environment variable is not set or is `0`
- **AND** the FastAPI app starts
- **THEN** `MonitoringMiddleware` SHALL be registered as before

### Requirement: `test_llm_loading.py` guarded behind env var
The LLM loading test SHALL only run when the `RUN_LLM_TESTS` environment variable is explicitly set to `1`. This prevents the 500MB model download and 120s model loading timeout from executing on every test run.

#### Scenario: Test skipped without env var
- **WHEN** `pytest` runs without `RUN_LLM_TESTS` set
- **THEN** `test_llm_loading.py` SHALL be skipped with a clear message

#### Scenario: Test runs with env var
- **WHEN** `RUN_LLM_TESTS=1` is set
- **THEN** `test_llm_loading.py` SHALL execute its full test body including model loading

### Requirement: Server smoke test uses ASGITransport
The `test_server_smoke.py` integration test SHALL use `httpx.AsyncClient` with `ASGITransport(app=app)` instead of spawning a real uvicorn subprocess. The test SHALL cover the health endpoint, OpenAPI docs page, and OpenAPI schema validation.

#### Scenario: Health endpoint returns 200
- **WHEN** the test sends a GET to `/api/v1/health`
- **THEN** the response SHALL have status 200
- **AND** the response SHALL contain valid health status data

#### Scenario: OpenAPI docs render
- **WHEN** the test sends a GET to `/docs`
- **THEN** the response SHALL have status 200
- **AND** the response SHALL contain HTML documentation

#### Scenario: OpenAPI schema is valid
- **WHEN** the test sends a GET to `/openapi.json`
- **THEN** the response SHALL have status 200
- **AND** the response SHALL contain valid OpenAPI schema JSON

### Requirement: Standalone asyncio.sleep calls removed
Integration tests SHALL NOT contain standalone `asyncio.sleep(n)` calls where `n >= 1` that are not part of a polling loop. These calls compensate for slow document processing that the processor batching optimizations (processor-batch-operations spec) make unnecessary.

Specifically, the following calls SHALL be removed:
- `test_link_aware_rag.py`: 3x `asyncio.sleep(2)` calls at lines 300, 433, 506
- `test_chat_integration.py`: 1x `asyncio.sleep(2)` call
- `test_pdf_integration.py`: 1x `asyncio.sleep(2)` call
- `test_documents_integration.py`: 1x `asyncio.sleep(2)` call

#### Scenario: No sleep(2) calls exist in integration tests
- **WHEN** scanning integration test files for `await asyncio.sleep(2)`
- **THEN** no such calls SHALL exist outside polling loop helpers

### Requirement: Heavy imports loaded lazily in test files
Test files that import heavy native libraries (`fitz`/PyMuPDF or `docx`/python-docx) SHALL use function-level imports or pytest's `pytest.importorskip()` to avoid module-level load cost when the test file is collected.

#### Scenario: fitz not imported at module level
- **WHEN** `test_pdf_link_extraction.py` is imported by pytest
- **THEN** `import fitz` SHALL NOT execute at module level
- **AND** `fitz` SHALL be imported only inside the test function that needs it

#### Scenario: docx not imported at module level unnecessarily
- **WHEN** `test_docx_link_extraction.py` patches `docx.Document`
- **THEN** the `docx` module SHALL only be loaded when the patching fixture activates

### Requirement: Duplicate atexit cleanup removed
The `_cleanup_test_artifacts` function SHALL be registered exactly once. The `atexit.register(_cleanup_test_artifacts)` call in `tests/conftest.py` SHALL be removed. Only the `pytest_sessionfinish` hook SHALL handle cleanup.

#### Scenario: Only one cleanup registration exists
- **WHEN** scanning `tests/conftest.py` for cleanup registration
- **THEN** only `pytest_sessionfinish` SHALL call `_cleanup_test_artifacts`
- **AND** `atexit.register` SHALL NOT call `_cleanup_test_artifacts`
