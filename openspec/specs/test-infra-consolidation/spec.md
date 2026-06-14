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
