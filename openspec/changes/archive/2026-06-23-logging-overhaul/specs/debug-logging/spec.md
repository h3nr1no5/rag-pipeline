## ADDED Requirements

### Requirement: Get current log level overrides
The system SHALL expose a `GET /api/v1/debug/logging` endpoint that returns a JSON object mapping module names to their currently overridden log level.

The endpoint SHALL require authentication via the existing `get_current_user` dependency.

The response SHALL be a JSON object where keys are Python logger names (e.g., `src.domain.services.retrieval`) and values are the log level integer or name (e.g., `10` or `"DEBUG"`).

#### Scenario: Developer retrieves current overrides
- **WHEN** an authenticated user sends `GET /api/v1/debug/logging`
- **THEN** the system returns `200 OK` with a JSON body containing the current module-to-level overrides

#### Scenario: Unauthenticated request is rejected
- **WHEN** an unauthenticated request sends `GET /api/v1/debug/logging`
- **THEN** the system returns `401 Unauthorized`

### Requirement: Set log level override for a module
The system SHALL expose a `PUT /api/v1/debug/logging` endpoint that accepts a JSON body mapping module names to log levels.

Each entry SHALL set that module's effective log level to the specified value. The override SHALL persist in memory until the process restarts or the override is explicitly removed.

Removing an override (setting level to `null`) SHALL restore the module's level to the default from the logging config / `.env`.

The endpoint SHALL require authentication via the existing `get_current_user` dependency.

#### Scenario: Developer overrides a module to DEBUG
- **WHEN** an authenticated user sends `PUT /api/v1/debug/logging` with body `{"src.domain.services.retrieval": "DEBUG"}`
- **THEN** the `src.domain.services.retrieval` logger SHALL output DEBUG-level messages
- **AND** the response SHALL be `200 OK`

#### Scenario: Developer removes an override
- **WHEN** an authenticated user sends `PUT /api/v1/debug/logging` with body `{"src.domain.services.retrieval": null}`
- **THEN** the `src.domain.services.retrieval` logger SHALL return to its default level
- **AND** the response SHALL be `200 OK`

#### Scenario: Invalid module name returns 422
- **WHEN** an authenticated user sends `PUT /api/v1/debug/logging` with body `{"invalid module!!!": "DEBUG"}`
- **THEN** the system SHALL return `422 Unprocessable Entity`

### Requirement: DevModeFilter suppresses noisy log patterns
The system SHALL register a `logging.Filter` named `DevModeFilter` on the root logger that reduces log noise from known high-volume sources.

The filter SHALL suppress uvicorn access logs when the log level is MODERATE or below (effectively removing `uvicorn.access` INFO messages unless the user has toggled that logger to DEBUG).

The filter SHALL NOT affect ERROR or CRITICAL messages from any logger.

#### Scenario: Uvicorn access log is suppressed
- **WHEN** a request is processed and `uvicorn.access` logs at INFO level
- **AND** no override sets `uvicorn.access` to DEBUG
- **THEN** the log line SHALL NOT be emitted

#### Scenario: Error messages still pass through
- **WHEN** any logger emits an ERROR or CRITICAL message
- **THEN** the message SHALL pass through the filter unchanged

### Requirement: Structured event helper for consolidated logging
The system SHALL provide a `log_structured()` helper function that accepts a module name, event type, and keyword arguments, emitting a single log line with all context bundled in a parseable format.

The helper SHALL use the module's logger at INFO level by default, with an optional `level` parameter.

The format SHALL be: `<event_type> [key=value ...]` — supporting both human readability and simple machine parsing.

#### Scenario: log_structured emits consolidated log line
- **WHEN** code calls `log_structured("retrieval", "query", top_k=5, results=3, latency_ms=42)`
- **THEN** a single INFO log line SHALL be emitted containing `query top_k=5 results=3 latency_ms=42`
- **AND** the logger used SHALL be `src.domain.services.retrieval`

### Requirement: Overrides reset on restart
The system SHALL NOT persist log level overrides across process restarts. All overrides exist only in memory.

#### Scenario: Overrides cleared after restart
- **WHEN** a developer sets a module override via PUT
- **AND** the process restarts
- **THEN** all overrides SHALL be cleared
- **AND** all loggers SHALL return to their default levels from config
