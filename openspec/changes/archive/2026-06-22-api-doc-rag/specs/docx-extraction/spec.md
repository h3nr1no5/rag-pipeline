## ADDED Requirements

### Requirement: Parse DOCX tables into structured function definitions
The system SHALL parse DOCX files using `python-docx` and extract tables containing COM API function/method definitions. For each table, the system MUST identify the column layout and extract structured `APIFunction` objects.

The system MUST support at minimum these table column layouts:
- Method/Function tables: Method name column, Parameters column, Return type column, Description column
- Each parameter cell contains `name: type` pairs, one per line within the cell
- Multi-row functions (one logical function spanning N table rows) MUST be detected and merged into a single `APIFunction` with N parameters

#### Scenario: Extract simple function table
- **WHEN** a DOCX is ingested containing a 2-column table with Method and Parameters columns
- **THEN** the system extracts each row as a separate `APIFunction` with the method name and parameter list

#### Scenario: Extract multi-row function
- **WHEN** a DOCX table has a function name in the first row and additional parameters in subsequent rows with an empty first cell
- **THEN** the system merges all rows into a single `APIFunction` with all parameters collected from the merged rows

#### Scenario: Validate against unknown column layout
- **WHEN** a DOCX table column header does not match any known layout
- **THEN** the system SHALL fall back to PDF text extraction for that table

### Requirement: Parse DOCX paragraphs and headings
The system SHALL extract non-table content (paragraphs, headings, bullet lists) from DOCX files with their style hierarchy preserved. Heading levels MUST be preserved for section hierarchy detection.

#### Scenario: Extract section hierarchy
- **WHEN** a DOCX has heading levels (Heading 1, Heading 2) interspersed with paragraphs
- **THEN** the system produces a section hierarchy with parent-child relationships based on heading level

### Requirement: Build structured COM domain objects
The system SHALL convert parsed DOCX content into typed domain objects:
- `APIInterface`: interface name, GUID, base interface, methods list, properties list
- `APIFunction`: function name, return type, parameters list, description, parent interface
- `APIParameter`: parameter name, type annotation, description, optional flag, default value
- `APIProperty`: property name, type, access modifier (get/set), description
- `APIEnum`: enum name, values list
- `APIEnumValue`: value name, numeric value, description
- `APIErrorCode`: error code name, numeric value, description

All domain objects SHALL be defined as `pydantic` BaseModel classes.

#### Scenario: Convert extraction to domain objects
- **WHEN** table extraction produces raw row data for a function
- **THEN** the system creates an `APIFunction` with parsed `APIParameter` objects

#### Scenario: Handle malformed parameter types
- **WHEN** a parameter cell contains `name: type` in an unrecognized format
- **THEN** the system stores the raw text as the parameter description and sets type to `"unknown"` rather than failing
