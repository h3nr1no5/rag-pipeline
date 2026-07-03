# API Docs RAG

## ADDED Requirements

### Requirement: Response SHALL populate `relevant_functions` from chunk metadata

The `ApiDocQueryResponse.relevant_functions` field SHALL be populated with function names extracted from the retrieved chunks' metadata. Each unique chunk that has a `function_name` or `name` metadata entry SHALL contribute its value to this list.

#### Scenario: `function_name` metadata populates relevant_functions
- **WHEN** the retrieved chunks include a chunk with `function_name` metadata set to `"StartSelection"`
- **THEN** the `relevant_functions` list SHALL include `"StartSelection"`

#### Scenario: `name` metadata populates relevant_functions
- **WHEN** the retrieved chunks include a chunk without `function_name` but with `name` metadata set to `"Initialize"`
- **THEN** the `relevant_functions` list SHALL include `"Initialize"`

#### Scenario: Interface-name-only chunks do NOT populate relevant_functions
- **WHEN** the retrieved chunks have only `interface_name` metadata (no `function_name` or `name`)
- **THEN** those chunks SHALL NOT contribute to `relevant_functions`

#### Scenario: Deduplication by function name
- **WHEN** multiple retrieved chunks share the same `function_name` value
- **THEN** that function name SHALL appear exactly once in `relevant_functions`

### Requirement: Response SHALL populate `relevant_types` from type and interface metadata

The `ApiDocQueryResponse.relevant_types` field SHALL be populated with type names and interface names extracted from the retrieved chunks' metadata. Both `type_name` and `interface_name` metadata entries SHALL contribute to this list.

#### Scenario: `type_name` metadata populates relevant_types
- **WHEN** the retrieved chunks include a chunk with `type_name` metadata set to `"MsoTriState"`
- **THEN** the `relevant_types` list SHALL include `"MsoTriState"`

#### Scenario: `interface_name` metadata populates relevant_types
- **WHEN** the retrieved chunks include a chunk with `interface_name` metadata set to `"IApplication"`
- **THEN** the `relevant_types` list SHALL include `"IApplication"`

#### Scenario: Deduplication by name
- **WHEN** multiple retrieved chunks share the same `type_name` or `interface_name` value
- **THEN** that name SHALL appear exactly once in `relevant_types`

#### Scenario: Both type_name and interface_name on same chunk
- **WHEN** a chunk has both `type_name: "MsoTriState"` and `interface_name: "IApplication"`
- **THEN** both `"MsoTriState"` and `"IApplication"` SHALL appear in `relevant_types`

### Requirement: DSPy path SHALL fall back to metadata extraction when LLM output is empty

When the DSPy predictor (`_query_dspy`) returns a result where `relevant_functions` or `relevant_types` is empty, the pipeline SHALL fall back to extracting these values from the resolved source chunk metadata, using the same logic as the non-DSPy fallback path.

#### Scenario: Empty `relevant_functions` triggers fallback extraction
- **WHEN** the DSPy predictor returns a result with `relevant_functions: []`
- **AND** the resolved sources include a chunk with `function_name: "StartSelection"`
- **THEN** the final `relevant_functions` SHALL include `"StartSelection"`

#### Scenario: Empty `relevant_types` triggers fallback extraction
- **WHEN** the DSPy predictor returns a result with `relevant_types: []`
- **AND** the resolved sources include a chunk with `interface_name: "IApplication"`
- **THEN** the final `relevant_types` SHALL include `"IApplication"`

#### Scenario: Non-empty DSPy output preserved without fallback
- **WHEN** the DSPy predictor returns `relevant_functions: ["StartSelection"]`
- **THEN** the final `relevant_functions` SHALL match the DSPy output
- **AND** fallback extraction SHALL NOT be applied

#### Scenario: Partial fallback (only empty field is extracted)
- **WHEN** the DSPy predictor returns `relevant_functions: ["StartSelection"]` but `relevant_types: []`
- **THEN** `relevant_functions` SHALL be `["StartSelection"]` from DSPy (unchanged)
- **AND** `relevant_types` SHALL be populated from source metadata via fallback

### Requirement: Ordering of `relevant_functions` and `relevant_types` SHALL be deterministic

Both lists SHALL be returned in sorted (alphabetical, ascending) order to ensure deterministic output regardless of chunk retrieval order or processing order.

#### Scenario: Sorted output
- **WHEN** the collected function names are `{"ZooMethod", "AlphaInit", "MidSort"}`
- **THEN** `relevant_functions` SHALL be `["AlphaInit", "MidSort", "ZooMethod"]`

#### Scenario: Empty list returns `[]`
- **WHEN** no retrieved chunk has any `function_name`, `name`, `type_name`, or `interface_name` metadata
- **THEN** both `relevant_functions` and `relevant_types` SHALL be empty lists `[]`
