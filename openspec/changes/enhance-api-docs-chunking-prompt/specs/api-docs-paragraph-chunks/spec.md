# API Docs Paragraph Chunks

## Purpose

Capture prose paragraphs from API documentation DOCX files as retrievable chunks linked to their parent interface, ensuring interface descriptions and explanatory text are available for retrieval alongside structured table data.

## ADDED Requirements

### Requirement: Paragraphs SHALL be extracted and associated with their parent interface

The DOCX extraction pipeline SHALL identify all prose paragraphs that appear under an interface-level heading (Heading 2 or 3 containing an `I`-prefix interface name) and associate each with the nearest preceding interface heading. The first paragraph immediately following the heading SHALL be treated as the interface description (current behavior, unchanged). All subsequent paragraphs within the same heading section SHALL be stored for chunking.

#### Scenario: Paragraphs after first description paragraph are captured
- **WHEN** a Heading 2/3 containing an interface name `IAxisVMApplication` is followed by three paragraphs (P1, P2, P3)
- **AND** P1 is captured as the interface `description` (existing behavior)
- **THEN** P2 and P3 SHALL be stored as paragraph texts associated with `IAxisVMApplication`

#### Scenario: Paragraphs between table groups are captured
- **WHEN** a heading section contains: paragraph → Functions table → paragraph → Properties table → paragraph
- **THEN** all three paragraphs SHALL be stored as paragraph texts associated with the interface

#### Scenario: Paragraphs after the last table in a section are captured
- **WHEN** a heading section ends with a paragraph following the last table
- **THEN** that paragraph SHALL be stored as paragraph text associated with the interface

#### Scenario: Paragraphs under non-interface headings are skipped
- **WHEN** a Heading 2/3 does not contain an `I`-prefix interface name
- **THEN** paragraphs under that heading SHALL NOT be stored as paragraph chunks (they are not associated with any interface)

### Requirement: Paragraph chunks SHALL be created as children of their parent interface node

The chunk graph builder SHALL create a `paragraph` chunk node for each paragraph text stored on an interface. Each paragraph node SHALL be a level-1 child of the parent interface node (same level as methods and properties). The metadata SHALL include `interface_name`, `kind: "paragraph"`, and `content` containing the paragraph text.

#### Scenario: Paragraph node created with correct metadata
- **WHEN** an interface `IAxisVMApplication` has 3 paragraph texts
- **THEN** the chunk graph SHALL contain 3 `paragraph` nodes
- **AND** each node SHALL have `level: 1` and `parent_id` pointing to the interface node
- **AND** each node SHALL have metadata with `kind: "paragraph"`, `interface_name: "IAxisVMApplication"`
- **AND** the interface node's `child_ids` SHALL include these paragraph node IDs

#### Scenario: Paragraph chunk text is searchable by BM25
- **WHEN** the BM25 index is built from paragraph chunks
- **THEN** the keyword text SHALL include the full paragraph content
- **AND** the `interface_name` metadata SHALL be used in keyword text construction

### Requirement: Interface description paragraph SHALL NOT be duplicated as a paragraph chunk

The first paragraph after an interface heading that is used as the interface `description` SHALL be excluded from paragraph chunk creation to avoid content duplication. The interface description is already stored in the interface node's metadata.

#### Scenario: First paragraph excluded from chunking
- **WHEN** an interface heading has exactly one paragraph following it (P1)
- **AND** P1 is captured as the interface `description`
- **THEN** zero paragraph chunks SHALL be created for that interface

#### Scenario: Multiple paragraphs: second onward become chunks
- **WHEN** an interface heading has three paragraphs (P1, P2, P3)
- **AND** P1 is captured as the interface `description`
- **THEN** paragraph chunks SHALL be created for P2 and P3 only
- **AND** P1 SHALL NOT appear as a paragraph chunk

### Requirement: Enum value and record field chunk metadata SHALL include interface_name

The chunk graph builder SHALL inject `interface_name` into the metadata of `enum_value` and `record_field` chunk nodes, sourced from their domain objects' `parent_interface` field. This ensures every chunk that belongs to an interface carries the owning interface name, enabling ParentExpander and BM25 keyword text to surface the correct interface context.

#### Scenario: Enum value node carries interface_name
- **WHEN** an enum `ENationalDesignCode` has `parent_interface: "IAxisVMApplication"`
- **AND** the chunk graph is built
- **THEN** each `enum_value` child node of `ENationalDesignCode` SHALL have `metadata["interface_name"]` set to `"IAxisVMApplication"`

#### Scenario: Record field node carries interface_name
- **WHEN** a record `RCalculationParameters` has `parent_interface: "IAxisVMApplication"`
- **AND** the chunk graph is built
- **THEN** each `record_field` child node of `RCalculationParameters` SHALL have `metadata["interface_name"]` set to `"IAxisVMApplication"`

#### Scenario: Existing enum_value metadata fields preserved
- **WHEN** `interface_name` is added to an `enum_value` node
- **THEN** all existing metadata fields (`type_name`, `name`, `value`, `description`) SHALL remain unchanged

#### Scenario: Existing record_field metadata fields preserved
- **WHEN** `interface_name` is added to a `record_field` node
- **THEN** all existing metadata fields (`record_name`, `name`, `type_annotation`, `description`) SHALL remain unchanged
