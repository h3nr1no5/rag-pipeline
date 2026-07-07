# Response Verification

## Purpose

Delta spec for the response-verification capability — adding parameter-level claim validation against source chunk metadata.

## ADDED Requirements

### Requirement: Parameter claims SHALL be validated against source chunk metadata

The verification system SHALL check that parameter names and descriptions mentioned in the generated answer exist in the retrieved source chunks' metadata. Parameter claims that reference non-existent parameters or contain fabricated descriptions SHALL be flagged and optionally reported in the response metadata.

#### Scenario: Parameter name validated against source
- **WHEN** the generated answer contains text matching a known parameter pattern (e.g., `"CrossSectionName (ECrossSectionShape)"`)
- **THEN** the system SHALL check that the parameter name exists in at least one source chunk's `parameters` metadata list
- **AND** SHALL record any unknown parameter names in the `unsupported` list

#### Scenario: Parameter description validated against source
- **WHEN** the generated answer contains a parameter description (e.g., `"Shape of the cross-section"`)
- **AND** the parameter name is known
- **THEN** the system SHALL compare the description text against the source chunk's description for that parameter
- **AND** SHALL flag any significant deviation as an unsupported claim

#### Scenario: No parameter claims in answer
- **WHEN** the generated answer does not contain any parameter names or descriptions
- **THEN** parameter validation SHALL be skipped
- **AND** shall not modify or reject the answer

#### Scenario: Parameter validation is advisory
- **WHEN** parameter validation detects unsupported claims
- **THEN** the answer SHALL NOT be automatically modified or rejected
- **AND** the unsupported claims SHALL be recorded in response metadata for transparency
