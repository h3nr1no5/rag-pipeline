# Retrieval

## Purpose

Delta spec for the retrieval capability — adding per-parameter name and description indexing to the BM25 keyword text for method chunks.

## ADDED Requirements

### Requirement: BM25 keyword text SHALL include per-parameter names and descriptions

The `ApiBm25Index._build_keyword_text()` method for `"method"` kind chunks SHALL flatten the `parameters` metadata list into keyword text, appending each parameter's `name` and `description` to the keyword string.

#### Scenario: Method with parameters indexed
- **WHEN** a method chunk has metadata containing `parameters: [{"name": "CrossSectionName", "description": "Name of the cross-section"}, {"name": "CrossSectionShape", "description": "Shape of the cross-section"}]`
- **AND** `_build_keyword_text()` is called for that chunk
- **THEN** the output keyword text SHALL contain `"CrossSectionName"`, `"Name of the cross-section"`, `"CrossSectionShape"`, and `"Shape of the cross-section"`
- **AND** these terms SHALL be tokenized with camelCase splitting

#### Scenario: Method with no parameters
- **WHEN** a method chunk has no `parameters` metadata or an empty list
- **THEN** `_build_keyword_text()` SHALL NOT add any extra terms
- **AND** the existing fields (`interface_name`, `function_name`, `name`, `return_type`, `description`) SHALL remain unchanged

#### Scenario: Parameter description is empty
- **WHEN** a method chunk has a parameter with `name: "CrossSectionName"` and `description: ""`
- **THEN** the parameter name SHALL still be included in keyword text
- **AND** the empty description SHALL be excluded (no empty-string terms)

#### Scenario: BM25 search matches parameter description
- **WHEN** the BM25 index contains method chunks with parameter descriptions indexed
- **AND** a user queries `"shape of the cross-section"`
- **THEN** the BM25 search SHALL return the `AddFromCatalog` method chunk among the top results
