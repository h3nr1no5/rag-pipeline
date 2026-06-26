## ADDED Requirements

### Requirement: Converter SHALL use per-type positional extractors

The document converter SHALL dispatch to a type-specific extraction method based on the table type detected by the table detector. Each extractor interprets columns by position (not header keywords) according to the known layout for that type. The extractors SHALL treat `table.headers` as the first data row (since real COM tables have no header row).

#### Scenario: Method table extracts return type from col 0, signature from col 1
- **WHEN** the converter processes a `"method"` type table
- **THEN** rows where col 0 is non-empty SHALL begin a new function definition
- **AND** col 0 SHALL be set as the `return_type`
- **AND** col 1 SHALL contain the function name (`name(…)` syntax with optional inline parameters)

#### Scenario: Method table extracts parameter descriptions from subsequent rows
- **WHEN** a method table has rows following a function signature with empty col 0
- **WHEN** col 1 text matches a known parameter name from the current function
- **THEN** that row SHALL be added as a parameter description entry
- **AND** col 1 SHALL be the parameter name, col 2 SHALL be the description

#### Scenario: Method table extracts function-level description
- **WHEN** a method table has rows following a function signature with empty col 0
- **WHEN** col 1 text does NOT match any known parameter name
- **AND** the text is not empty and does not match the separator pattern
- **THEN** that row SHALL be added as the function-level description

#### Scenario: Method table handles functions with no parameters
- **WHEN** a function signature has no `(` character in col 1
- **THEN** the function SHALL be created with an empty parameter list
- **AND** the next non-empty row with empty col 0 SHALL be the function-level description

#### Scenario: Method table uses blank row as function separator
- **WHEN** a method table row has all empty cells
- **THEN** the row SHALL be treated as a function separator (no new function, no description text)

### Requirement: Property extractor SHALL split combined name+description from col 1

The property table extractor SHALL parse col 0 as the property type and col 1 as combined name+description text. The name and description SHALL be separated heuristically.

#### Scenario: Property name separated by bullet character
- **WHEN** col 1 contains a ` • ` (bullet with surrounding spaces)
- **THEN** text before the bullet SHALL be the property name
- **AND** text after the bullet SHALL be the property description

#### Scenario: Property name separated by bracket parameter
- **WHEN** col 1 contains ` [` indicating a property with index parameter
- **THEN** text before ` [` SHALL be the property name
- **AND** text after `] ` SHALL be the property description (parameter stored in metadata)

#### Scenario: Property name is first word when no clear separator
- **WHEN** neither bullet nor bracket separator is found
- **THEN** the first PascalCase/camelCase identifier word SHALL be the property name
- **AND** the remaining text SHALL be the property description
- **AND** both combined text and separated values SHALL be preserved in the output

### Requirement: Enum extractor SHALL parse name=value pairs from positional columns

The enum and error_code extractors SHALL parse col 1 for `name = value` (or `name = value,`) patterns and col 2 for descriptions. The first row may contain an enum group name in col 1. Rows with `{` or `}` in col 1 SHALL be structural markers, not members.

#### Scenario: Enum table parses member name and value
- **WHEN** col 1 contains text matching `identifier = literal` (with optional trailing comma)
- **THEN** the identifier SHALL be the enum member name
- **AND** the literal SHALL be the member value
- **AND** col 2 SHALL be the member description

#### Scenario: Enum table skips brace rows
- **WHEN** col 1 contains `{` or `}` (enum opening/closing braces)
- **THEN** the row SHALL NOT be parsed as a member
- **AND** col 2 SHALL be treated as the enum group description

#### Scenario: Enum table sets group name from first row
- **WHEN** col 1 of the first row contains `EnumName = {` or `EnumName {`
- **THEN** the text before `=` or `{` SHALL be extracted as the enum group name

### Requirement: Record extractor SHALL parse fields from positional columns

The record extractor SHALL parse col 0 as field type, col 1 as field name, and col 2 as field description. The first row may contain the record name. Rows with `(` or `)` in col 1 are structural markers.

#### Scenario: Record table parses field type, name, and description
- **WHEN** col 0 is non-empty
- **THEN** col 0 SHALL be the field type, col 1 the field name, col 2 the field description
- **AND** rows with empty col 0 and parentheses in col 1 SHALL be treated as record delimiters

### Requirement: Converter SHALL capture interface descriptions

When the DOCX parser encounters a Heading 2 or Heading 3 paragraph whose text matches an interface name pattern (starts with `I`, PascalCase), the next non-table paragraph SHALL be captured as the interface description. This description SHALL be stored on the `APIInterface.description` field.

#### Scenario: Interface description captured from paragraph after heading
- **WHEN** a Heading 2 paragraph reads `"IAxisVMApplication"`
- **AND** the next paragraph (non-table) reads `"The main interface of the COM server"`
- **THEN** the interface object for `IAxisVMApplication` SHALL have `description="The main interface of the COM server"`

### Requirement: Dead `method_table` config SHALL be removed

The `method_table` configuration block SHALL be removed from `config/strategies.yaml` and from `DocumentConverter`. Column positions are hardcoded per type in the positional extractors. The keyword fallback path uses hardcoded positions (col 0 = return type, col 1 = name).

#### Scenario: Strategy config no longer requires method_table
- **WHEN** a strategy config is loaded without `method_table`
- **THEN** `DocumentConverter._apply_config()` SHALL NOT fail
- **AND** the converter SHALL still work correctly using hardcoded positions
