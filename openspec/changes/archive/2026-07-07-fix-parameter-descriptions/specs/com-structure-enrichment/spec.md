## MODIFIED Requirements

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

#### Scenario: Handle parameter descriptions in DOCX table continuation rows
- **WHEN** a method function is extracted from a DOCX table with continuation rows containing parameter descriptions
- **THEN** the system SHALL parse the merged cell content and associate each continuation row's text with the corresponding parameter by name
- **AND** the extracted `APIParameter.description` SHALL NOT be empty when a description is present in the continuation row
- **AND** the function description SHALL include text from continuation rows that do not match known parameter names

#### Scenario: Exclude `_vb` alias parentheticals from parameter extraction
- **WHEN** a function name ends with `_vb`
- **AND** its signature contains a parenthetical describing the alias (e.g., `(Visual Basic compatible function of X)`)
- **THEN** the system SHALL NOT create parameters from the parenthetical content
- **AND** the function description SHALL indicate the alias target

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
