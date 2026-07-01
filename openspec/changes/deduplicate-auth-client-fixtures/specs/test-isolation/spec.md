## MODIFIED Requirements

### Requirement: Auth client fixture is canonical and non-duplicated
The system SHALL define exactly one `auth_client` fixture for all integration tests, located in `tests/integration/conftest.py`. No integration test file or subdirectory conftest SHALL define its own `auth_client` fixture. The canonical fixture SHALL use an idempotent signup-then-always-login pattern that guarantees token capture regardless of signup result.

#### Scenario: Single auth_client fixture definition
- **WHEN** a user greps for `async def auth_client` across all `tests/integration/` Python files
- **THEN** exactly one match SHALL be found, located in `tests/integration/conftest.py`
- **AND** zero matches SHALL be found in any other file under `tests/integration/`

#### Scenario: Auth client always produces authenticated requests
- **WHEN** a test requests the `auth_client` fixture
- **THEN** the returned `AsyncClient` SHALL have a valid `Authorization: Bearer <token>` header
- **AND** the token SHALL be obtained from a login response, not assumed from signup

#### Scenario: Canonical fixture is idempotent on rerun
- **WHEN** the canonical `auth_client` fixture runs
- **AND** the test user already exists in the database (from a prior signup)
- **THEN** the fixture SHALL NOT raise an error
- **AND** the fixture SHALL obtain a valid token via login
- **AND** the returned client SHALL have an `Authorization` header with the token

## REMOVED Requirements

### Requirement: No duplicate auth_client fixtures in integration tests
**Reason**: All 17 remaining duplicate `auth_client` fixtures removed as part of the `deduplicate-auth-client-fixtures` change. The canonical fixture in `tests/integration/conftest.py` is now the single source of truth across the entire integration test tree.
**Migration**: Any test that previously relied on a locally-defined `auth_client` fixture should use the canonical fixture from `tests/integration/conftest.py` via normal pytest conftest resolution. No import changes needed — deletion of the local definition automatically activates the parent conftest fixture.
