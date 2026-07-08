## ADDED Requirements

### Requirement: System SHALL detect table type from preceding paragraph

The DOCX table detector SHALL determine the type of each table by examining the nearest preceding bold paragraph. This replaces header keyword matching as the primary detection path.

#### Scenario: Functions paragraph detected as method type
- **WHEN** a table is preceded (immediately before) by a bold paragraph with text `"Functions"`
- **THEN** the table SHALL be classified as type `"method"`

#### Scenario: Properties paragraph detected as property type
- **WHEN** a table is preceded by a bold paragraph `"Properties"`
- **THEN** the table SHALL be classified as type `"property"`

#### Scenario: Enumerated types paragraph detected as enum type
- **WHEN** a table is preceded by a bold paragraph `"Enumerated types"`
- **THEN** the table SHALL be classified as type `"enum"`

#### Scenario: Error codes paragraph detected as error_code type
- **WHEN** a table is preceded by a bold paragraph `"Error codes"`
- **THEN** the table SHALL be classified as type `"error_code"`

#### Scenario: Records / structures paragraph detected as record type
- **WHEN** a table is preceded by a bold paragraph `"Records / structures"` (with leading slash)
- **THEN** the table SHALL be classified as type `"record"`

### Requirement: Consecutive tables SHALL inherit the preceding table's type

When two or more tables appear consecutively in the DOCX body with no paragraph between them, the second and subsequent tables SHALL inherit the type of the first table in the sequence. This handles DOCX rendering artifacts where a logical table is split into multiple XML tables.

#### Scenario: Second function table inherits method type
- **WHEN** a "Functions" table is immediately followed by another table with no intervening paragraph
- **THEN** the second table SHALL be classified as type `"method"` (inherited from the first)

### Requirement: Detection SHALL fall back to keyword matching when no paragraph matches

When no preceding bold paragraph matches a known label and no inheritance applies, the detector SHALL use the existing multi-signal keyword matching strategy (scanning column headers for `[in]`, `[out]`, parameter-like patterns) as a secondary path.

#### Scenario: Unknown paragraph falls through to keyword matching
- **WHEN** a table is preceded by a bold paragraph whose text does NOT match any known label (e.g., `"Units"`, `"Data types"`)
- **WHEN** the preceding DOCX sibling is NOT a table (no inheritance)
- **THEN** the detector SHALL use the existing keyword-based header matching logic

### Requirement: Label matching SHALL use exact text after whitespace normalization

The known labels SHALL be matched against the paragraph text after stripping leading/trailing whitespace and normalizing internal whitespace. The match SHALL be exact (not substring/contains) to prevent false positives from label-like text in other contexts.

#### Scenario: Partial match does not trigger detection
- **WHEN** a bold paragraph reads `"Functions and events"` (not exact label)
- **THEN** it SHALL NOT match the `"functions"` label
