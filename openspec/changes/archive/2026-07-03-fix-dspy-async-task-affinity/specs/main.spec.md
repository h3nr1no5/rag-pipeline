# DSPy Async Task Affinity Fix

This is a bug fix with no new capabilities and no modified requirements. The change is purely an implementation refactor — behavior is preserved identically from the caller's perspective.

## ADDED Requirements

### Requirement: Lifespan must not call dspy.configure()

The FastAPI lifespan function SHALL NOT call `dspy.configure()` under any circumstances. All DSPy configuration MUST happen inside `warmup_models()`.

#### Scenario: Lifespan startup does not call dspy.configure

- **WHEN** the FastAPI application starts (lifespan runs)
- **THEN** `dspy.configure()` MUST NOT have been called by the lifespan
- **AND** `warmup_models()` SHALL be the only caller of `dspy.configure()` during startup

#### Scenario: Regression test catches lifespan dspy.configure call

- **WHEN** a `dspy.configure()` call is added to the lifespan
- **THEN** the regression test `test_no_dspy_configure_during_lifespan` MUST fail

## MODIFIED Requirements

_(No modified requirements — all public APIs, endpoints, and user-facing behavior remain unchanged.)_

## REMOVED Requirements

_(No removed requirements.)_
