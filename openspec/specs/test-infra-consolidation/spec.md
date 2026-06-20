## Purpose

Consolidate test infrastructure to eliminate duplication, remove subprocess-based server spawning in integration tests, and clean up dead code in fixtures.

## Requirements

### Requirement: Single `pytest_sessionfinish` hook in root conftest
The system SHALL define exactly one `pytest_sessionfinish` hook in the root `tests/conftest.py` that cleans up all test artifacts. All duplicate hooks in individual test files SHALL be removed.

#### Scenario: Session finish cleanup removes all artifact patterns
- **WHEN** the test session finishes
- **THEN** all `.sqlite` files matching known patterns SHALL be removed from `./data/`
- **AND** all files in the upload directory SHALL be removed

#### Scenario: No orphan hooks remain in test files
- **WHEN** the test suite is scanned for `pytest_sessionfinish` definitions
- **THEN** only the root `tests/conftest.py` SHALL contain such a hook

### Requirement: Single `setup_test_db` fixture in root conftest
The system SHALL define exactly one `setup_test_db` fixture in the root `tests/conftest.py`. All duplicate definitions in individual test files SHALL be removed. The fixture SHALL:
- Create a unique SQLite database per test
- Swap `db_session.engine`, `db_session.async_session_maker`, and `processor.async_session_maker`
- Create all tables and seed default data
- Restore all swapped values during teardown

#### Scenario: Setup fixture runs for every test
- **WHEN** any test in the suite runs
- **THEN** the `setup_test_db` fixture SHALL execute before the test body
- **AND** the fixture SHALL restore all globals after the test

#### Scenario: No duplicate setup fixtures exist
- **WHEN** the test suite is scanned for `setup_test_db` fixture definitions
- **THEN** only the root `tests/conftest.py` SHALL define it

### Requirement: No subprocess server in integration tests
Integration tests SHALL use in-process `ASGITransport` with `httpx.AsyncClient` instead of spawning real uvicorn subprocesses. The `test_user_persistence.py` file SHALL be rewritten to follow this pattern.

#### Scenario: User persistence test uses ASGI transport
- **WHEN** `test_user_persistence.py` runs
- **THEN** it SHALL use `httpx.AsyncClient` with `ASGITransport(app=app)` for all HTTP calls
- **AND** it SHALL NOT spawn any `subprocess.Popen` for a server

#### Scenario: User registration survives simulated restart
- **WHEN** a user registers via the API
- **AND** the test simulates a restart by creating a fresh client
- **THEN** the registered user's credentials SHALL still be valid for login

### Requirement: No dead code in auth_client fixtures
The `auth_client` fixture in all test files SHALL NOT contain dead `pass` statements as the first line of the fixture body.

#### Scenario: Dead pass statements removed
- **WHEN** scanning `auth_client` fixtures in test files for `pass` as the first statement after the fixture signature
- **THEN** no such `pass` statements SHALL exist

### Requirement: Shared `wait_for_document` helper replaces all copy-pasted implementations
The system SHALL provide exactly one shared implementation of the `wait_for_document()` function in `tests/integration/conftest.py`. All 7 copy-pasted `upload_and_wait_for_document()` implementations across integration test files SHALL be replaced with imports from the shared helper.

The affected test files are:
- `tests/integration/test_rag_comparison.py`
- `tests/integration/test_pdf_integration.py`
- `tests/integration/test_chat_integration.py`
- `tests/integration/test_clear_embeddings.py`
- `tests/integration/test_cache_bug.py`
- `tests/integration/test_chat_e2e.py`
- `tests/integration/test_documents_integration.py`

#### Scenario: No duplicate upload_and_wait implementations remain
- **WHEN** scanning all test files in `tests/integration/` for `async def upload_and_wait`
- **THEN** no such function definitions SHALL exist

#### Scenario: All seven test files import the shared helper
- **WHEN** each of the seven affected test files is inspected
- **THEN** each SHALL import `wait_for_document` from `tests.integration.conftest`

### Requirement: Shared `auth_client` fixture replaces local definitions
The system SHALL provide exactly one shared `auth_client` fixture in `tests/integration/conftest.py`. All local `auth_client` fixture definitions in individual integration test files SHALL be removed in favor of the shared fixture.

#### Scenario: No local auth_client fixtures remain
- **WHEN** scanning all test files in `tests/integration/` for `auth_client` fixture definitions
- **THEN** no such async fixture definitions SHALL exist outside `tests/integration/conftest.py`
