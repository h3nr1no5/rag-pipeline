## MODIFIED Requirements

### Requirement: Background tasks are cancelled during test teardown

**Previous**: The system SHALL cancel and await background asyncio tasks for ALL test scopes without exception.

**Updated**: The system SHALL cancel and await background asyncio tasks created by the document processor during fixture teardown. The root `tests/conftest.py` SHALL define this fixture with `autouse=True` as the default behavior. However, subdirectory conftest files (`tests/unit/conftest.py`, `tests/pdf_semantic_chunking/conftest.py`) MAY override this fixture as a no-op when their tests do not trigger document processing. The `processor.async_session_maker` SHALL be restored to its original value after each test (in conftests that use the full fixture).

#### Scenario: Background task does not outlive test (root conftest)
- **WHEN** a test in the root test directory or `tests/integration/` triggers document processing via `trigger_document_processing`
- **AND** the test fixture tears down
- **THEN** the background task for that document SHALL be cancelled within 5 seconds
- **AND** `processor.async_session_maker` SHALL be restored to its original value

#### Scenario: Background task fixture overridden in unit tests
- **WHEN** a test in `tests/unit/` completes
- **THEN** the `cancel_background_tasks` fixture SHALL NOT enumerate or cancel any asyncio tasks
- **AND** no cancellation errors SHALL be raised

#### Scenario: Background task fixture overridden in pdf_semantic_chunking tests
- **WHEN** a test in `tests/pdf_semantic_chunking/` completes
- **THEN** the `cancel_background_tasks` fixture SHALL NOT enumerate or cancel any asyncio tasks
- **AND** no cancellation errors SHALL be raised

### Requirement: Upload directory is cleaned before each test

**Previous**: The system SHALL remove all files from the upload directory before each test function runs across ALL test scopes.

**Updated**: The system SHALL remove all files from the upload directory before each test function runs. The root `tests/conftest.py` SHALL define this fixture with `autouse=True` as the default behavior. Subdirectory conftest files MAY override this fixture as a no-op when their tests do not interact with the file upload API.

#### Scenario: Upload directory cleaned by default
- **WHEN** a test runs under the root conftest or `tests/integration/`
- **THEN** the upload directory SHALL be empty before the test executes

#### Scenario: Upload directory fixture overridden in unit tests
- **WHEN** a test in `tests/unit/` runs
- **THEN** the `clean_uploads_dir` fixture SHALL NOT scan `./data/uploads/`

### Requirement: Databases are isolated per test

**Previous**: Each test SHALL use a unique SQLite database file. This SHALL apply to ALL tests in the suite.

**Updated**: Each test SHALL use a unique SQLite database file. The root `tests/conftest.py` SHALL define the `setup_test_db` fixture with `autouse=True` as the default behavior. Subdirectory conftest files MAY override this fixture as a no-op when their tests do not access the database.

#### Scenario: Setup creates unique database (default)
- **WHEN** a test starts under the root conftest or `tests/integration/`
- **THEN** the `TEST_DATABASE_URL` environment variable SHALL point to a unique `.sqlite` file
- **AND** the database SHALL be initialized with all required tables and seed data

#### Scenario: Database fixture overridden in unit tests
- **WHEN** a test in `tests/unit/` starts
- **THEN** the `setup_test_db` fixture SHALL NOT create any database engine or file

#### Scenario: Database fixture overridden in pdf_semantic_chunking tests
- **WHEN** a test in `tests/pdf_semantic_chunking/` starts
- **THEN** the `setup_test_db` fixture SHALL NOT create any database engine or file
