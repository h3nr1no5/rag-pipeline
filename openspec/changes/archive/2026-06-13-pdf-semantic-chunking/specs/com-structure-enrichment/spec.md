## ADDED Requirements

### Requirement: Enrich generic document tree with COM-specific structure

The system SHALL transform the generic `DocumentElement` tree produced by the structure parser into a COM-aware hierarchy with typed elements: interfaces, methods, properties, enums, records, and error codes — producing a tree of `Interface → Section → Element`.

#### Scenario: Detect COM interface boundaries from attribute clusters
- **WHEN** the document element tree contains a sequence of C# COM interop attributes (`[ComImport]`, `[Guid("...")]`, `[InterfaceType(...)]`) immediately followed by an `interface I\w+` declaration
- **THEN** the system SHALL group the attribute cluster and the interface declaration into a single `com_interface` element
- **AND** the `com_interface` element SHALL have `children` containing all members of that interface
- **AND** SHALL set `confidence: 1.0` when all three attributes (`ComImport`, `Guid`, `InterfaceType`) are present

#### Scenario: Classify interface members by element type
- **WHEN** a code block or text element within a `com_interface` boundary matches a method signature pattern (return type + name + parameter list, e.g., `long BringToFront()`)
- **THEN** the system SHALL classify it as element_type `com_method`
- **WHEN** an element matches a property pattern (contains `get_`/`set_` prefix, or `[propget]`/`[propput]` attribute, or uses C# property syntax with `{ get; set; }`)
- **THEN** the system SHALL classify it as element_type `com_property`
- **WHEN** an element is a C# property with both getter and setter defined as separate methods
- **THEN** the system SHALL merge them into a single `com_property` element with `has_getter: true` and `has_setter: true`

#### Scenario: Extract parameter details from function signatures and descriptions
- **WHEN** a `com_method` element has parameters in its signature
- **THEN** the system SHALL parse each parameter's name, type, and direction indicator (`[in]`, `[out]`, `[in, out]`, `[in,out]`)
- **AND** SHALL look for parameter descriptions in the paragraph immediately following the signature
- **AND** SHALL associate each description with its parameter by name
- **AND** SHALL store the result as `parameters: [{name, direction, type, description}]`

#### Scenario: Handle parameter descriptions in bullet lists or tables
- **WHEN** parameter descriptions are formatted as a bullet list or table below the function signature
- **THEN** the system SHALL parse the list/table structure and associate each row with the corresponding parameter
- **AND** SHALL set `parameters_source: "table"` or `parameters_source: "list"` in element metadata

#### Scenario: Reconstruct multi-line signatures
- **WHEN** a function signature spans multiple lines in the PDF (e.g., return type on one line, name+params on the next)
- **THEN** the system SHALL detect the continuation by checking for indented lines following a partial signature
- **AND** SHALL join them into a single normalized signature string
- **AND** SHALL set `signature_reconstructed: true` in element metadata

#### Scenario: Detect and classify enum blocks
- **WHEN** a text block matches `enum E\w+` followed by a brace-delimited list of member definitions
- **THEN** the system SHALL classify the entire block as element_type `com_enum`
- **AND** SHALL NOT split the enum block — it is atomic
- **AND** SHALL extract member names and optional values as `enum_members: [{name, value}]`

#### Scenario: Detect and classify record/struct definitions
- **WHEN** a text block matches a C# record pattern (`record R\w+`, `readonly record struct`, `struct S\w+`) with a parenthesized member list
- **THEN** the system SHALL classify it as element_type `com_record`
- **AND** SHALL extract member names and types

#### Scenario: Group error codes by interface
- **WHEN** error code constants are defined near an interface declaration (e.g., `EApplicationError` enum with members like `errInterfaceNotFound`)
- **THEN** the system SHALL associate them with the nearest preceding interface
- **AND** SHALL generate a `com_error_code` element containing the error code group
- **AND** SHALL include the error codes in each chunk's `error_codes` metadata field within that interface

#### Scenario: Build the Interface → Section → Element hierarchy
- **WHEN** all elements of an interface have been classified
- **THEN** the system SHALL organize them into a three-level tree:
  ```
  IAxisVMApplication (com_interface)
  ├── Functions (section)
  │   ├── BringToFront (com_method)
  │   ├── ChangeUnitSystem (com_method)
  │   └── ...
  ├── Properties (section)
  │   ├── ActiveDocument (com_property)
  │   └── ...
  ├── Enumerated types (section)
  │   └── EMessageDialogButton (com_enum)
  ├── Error codes (section)
  │   └── EApplicationError (com_error_code)
  └── Records / structures (section)
      └── RCalculationParameters (com_record)
  ```
- **AND** the hierarchy SHALL be stored in each chunk's `section_hierarchy` metadata as `["IAxisVMApplication", "Functions", "BringToFront"]`

#### Scenario: Preserve cross-references as text
- **WHEN** a description contains a cross-reference like "see GetValidCombinationTypes"
- **THEN** the system SHALL keep the reference text as-is in the description
- **AND** SHALL NOT resolve or follow the reference
- **AND** SHALL add `cross_references: ["GetValidCombinationTypes"]` to element metadata

#### Scenario: Handle non-COM elements with graceful degradation
- **WHEN** the enrichment stage cannot classify an element as any COM-specific type
- **THEN** the system SHALL leave the element unclassified (original generic element type)
- **AND** SHALL set `com_confidence: 0.0` and `com_fallback_reason: "no_com_pattern_match"`
- **AND** these elements SHALL be chunked by the semantic-chunking-engine's generic fallback rules

#### Scenario: Output the enriched element tree
- **WHEN** enrichment completes
- **THEN** the output SHALL be a tree of `ComDocumentElement` nodes, each extending `DocumentElement` with:
  - `com_type`: one of `com_interface`, `com_method`, `com_property`, `com_enum`, `com_record`, `com_error_code`, or `null`
  - `element_name`: the name of the element (e.g., `"BringToFront"`, `"IAxisVMApplication"`)
  - `signature`: the normalized full signature string (for methods/properties)
  - `return_type`: the return type string (for methods/properties)
  - `parameters`: list of parameter dicts (for methods)
  - `error_codes`: list of associated error code names
  - `enum_members`: list of member dicts (for enums)
  - `record_members`: list of member dicts (for records)
  - `keywords`: auto-extracted keywords from element name and description
  - `com_confidence`: float 0.0–1.0
