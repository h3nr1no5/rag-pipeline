## ADDED Requirements

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
