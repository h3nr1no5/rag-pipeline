# API Docs Unknown Table Handling

## Purpose

Preserve table content from API documentation DOCX files when the table type cannot be classified as any known COM type (Functions, Properties, Enumerated Types, Error Codes, Records), preventing silent data loss and making potentially valuable documentation available for retrieval.

## Requirements

### Requirement: Unclassified tables SHALL produce generic table domain objects

The DOCX table detection pipeline SHALL, when a table cannot be classified into any known COM type (Functions, Properties, Enumerated Types, Error Codes, Records), create a generic table representation instead of silently skipping it. The generic table SHALL include the raw cell content, the heading context stack, and its position in the document.

#### Scenario: Unknown table with no type match creates generic entry
- **WHEN** a table's classification result is `unknown` (no bold label match, no consecutive-table type inheritance, no keyword+multi-signal fallback match)
- **THEN** the converter SHALL NOT silently skip the table
- **AND** SHALL create a generic table entry with:
  - `heading_stack`: the heading context at the table's position
  - `rows`: list of lists of cell text content
  - `header_row`: the first row if it appears to be a header (all cells bold or distinct from data rows)
  - `position`: the table's sequential position in the document

#### Scenario: Heading context preserved for unknown tables
- **WHEN** an unknown table appears under `IAxisVMCalculation` / `Functions` heading
- **THEN** the generic table entry SHALL have a `heading_stack` of `["IAxisVMCalculation", "Functions"]`

#### Scenario: Known tables unaffected
- **WHEN** a table is classified as `Functions` (known type)
- **THEN** the existing behavior SHALL be unchanged — the table SHALL be processed into `APIFunction` domain objects as before

### Requirement: Generic table chunks SHALL be created from unknown tables

The chunk graph builder SHALL create a `generic_table` chunk node for each unknown table stored on an interface. The chunk SHALL contain a markdown-like text representation of the table (header row, separator, data rows). The node SHALL be a level-1 child of the nearest parent interface. Metadata SHALL include `kind: "generic_table"`, `interface_name`, and the heading context.

#### Scenario: Generic table chunk created under parent interface
- **WHEN** an unknown table is associated with `IAxisVMApplication` via heading context
- **THEN** the chunk graph SHALL contain a `generic_table` node
- **AND** the node SHALL have `level: 1` and `parent_id` pointing to the interface node
- **AND** `metadata["kind"]` SHALL be `"generic_table"`
- **AND** `metadata["interface_name"]` SHALL be `"IAxisVMApplication"`

#### Scenario: Table rendered as markdown-like text in chunk content
- **WHEN** a generic table has 3 columns and 5 data rows (plus a header row)
- **THEN** the chunk content SHALL be formatted as:
  ```
  | Header1 | Header2 | Header3 |
  |---------|---------|---------|
  | Cell1   | Cell2   | Cell3   |
  | ...     | ...     | ...     |
  ```
- **AND** the `ChunkTextFormatter` SHALL support the `generic_table` kind with this format

#### Scenario: Unknown table text is searchable
- **WHEN** the BM25 index is built from generic table chunks
- **THEN** the keyword text SHALL include the rendered table content
- **AND** the `interface_name` metadata SHALL be included in keyword text construction

### Requirement: Unknown table logging SHALL be informative

When a table is classified as unknown, the converter SHALL log the heading context, number of rows and columns, and first-row cell previews at `INFO` level (not `DEBUG`), so that operators can audit which tables are not being classified and identify missing classification patterns.

#### Scenario: Unknown table logged at INFO level
- **WHEN** a table is classified as `unknown`
- **THEN** the converter SHALL log: `"Unknown table at heading stack [IAxisVMApplication, Functions]: 5 rows x 3 cols, first cells: ['Name', 'Type', ...]"`
- **AND** the log level SHALL be `INFO`
