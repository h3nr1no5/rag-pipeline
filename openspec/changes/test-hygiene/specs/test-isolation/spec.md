## ADDED Requirements

### Requirement: Background tasks are cancelled during test teardown
The system SHALL cancel and await any background `asyncio` tasks created by the document processor during fixture teardown. The `processor.async_session_maker` SHALL be restored to its original value after each test.

#### Scenario: Background task does not outlive test
- **WHEN** a test triggers document processing via `trigger_document_processing`
- **AND** the test fixture tears down
- **THEN** the background task for that document SHALL be cancelled within 5 seconds
- **AND** `processor.async_session_maker` SHALL be restored to its original value

#### Scenario: Test without processing runs cleanly
- **WHEN** a test does not trigger any document processing
- **AND** the test fixture tears down
- **THEN** no cancellation errors SHALL be raised

### Requirement: Upload directory is cleaned before each test
The system SHALL remove all files from the upload directory before each test function runs, ensuring no cross-test file contamination.

#### Scenario: Uploaded files from prior test are removed
- **WHEN** a test completes and leaves files in `./data/uploads/`
- **AND** the next test begins
- **THEN** the upload directory SHALL be empty before the next test executes

#### Scenario: Explicitly uploaded files are visible during test
- **WHEN** a test uploads a file via the API
- **THEN** the file SHALL exist in the upload directory during that test
- **AND** the file SHALL be removed before the next test

### Requirement: Databases are isolated per test
Each test SHALL use a unique SQLite database file that is cleaned up after the test completes.

#### Scenario: Setup creates unique database
- **WHEN** a test starts
- **THEN** the `TEST_DATABASE_URL` environment variable SHALL point to a unique `.sqlite` file
- **AND** the database SHALL be initialized with all required tables and seed data

#### Scenario: Database is cleaned up after test
- **WHEN** a test completes
- **THEN** the unique `.sqlite` file for that test SHALL be deleted
- **AND** no stale `.sqlite` files SHALL remain in `./data/` after the test session
