# API Docs Strategy

## Purpose

Define the chunking strategy for "API Documentation" documents and handle routing through the dedicated API doc extraction pipeline instead of the standard parse-chunk-embed loop.

## Requirements

### Requirement: System SHALL seed "API Documentation" strategy on startup

The application lifespan SHALL create an `api-docs` chunking strategy with `engine_type="api-docs"` if one does not already exist. This replaces the old removed `is_api_doc` flag and uses the strategy itself as the routing signal.

#### Scenario: Seed api-docs strategy on first startup
- **WHEN** the application starts and no `ChunkingStrategy` with `id="api-docs"` exists
- **THEN** the system SHALL create a new strategy with:
  - `id="api-docs"`
  - `name="API Documentation"`
  - `description="Structure-aware chunking for API documentation (DOCX/PDF)"`
  - `chunk_size=0`, `chunk_overlap=0`, `separators=[]` (N/A for this engine type)
  - `engine_type="api-docs"`
  - `use_hyperlinks=False`
  - `is_system=True`
  - `embedding_model` SHALL use the current settings value

#### Scenario: Existing api-docs strategy not duplicated
- **WHEN** the application starts and a `ChunkingStrategy` with `id="api-docs"` already exists
- **THEN** the system SHALL NOT create a duplicate
- **AND** the existing strategy SHALL be used as-is

### Requirement: Standard upload endpoint SHALL accept api-docs strategy

The `POST /documents` endpoint SHALL accept `strategy_id="api-docs"` and validate that the uploaded file is DOCX or PDF (not plain text, not PDF for semantic-only constraints).

#### Scenario: Upload DOCX with api-docs strategy succeeds
- **WHEN** a user uploads a `.docx` file with `strategy_id="api-docs"`
- **THEN** the upload SHALL succeed
- **THEN** a `Document` record SHALL be created with `chunking_strategy_id="api-docs"`
- **THEN** a `ProcessingConfig` SHALL be created with `engine_type="api-docs"`, `chunk_size=0`, `chunk_overlap=0`, `separators=[]`
- **AND** `trigger_document_processing()` SHALL be called

#### Scenario: Upload PDF with api-docs strategy succeeds
- **WHEN** a user uploads a `.pdf` file with `strategy_id="api-docs"`
- **THEN** the upload SHALL succeed
- **AND** the PDF SHALL be processed via the PDF fallback extractor (flat sections, no table detection)

#### Scenario: Upload unsupported file type with api-docs rejected
- **WHEN** a user uploads a `.txt` or other unsupported file type with `strategy_id="api-docs"`
- **THEN** the upload SHALL fail with an HTTP 400 error
- **AND** the error message SHALL indicate "API Documentation strategy only supports DOCX and PDF files"

### Requirement: Processor SHALL route api-docs engine type to dedicated pipeline

The `process_document_async()` function SHALL detect `engine_type="api-docs"` and branch to the dedicated API doc extraction/chunking pipeline instead of the standard parse-chunk-embed loop.

#### Scenario: Processor branches on engine_type
- **WHEN** the processor loads a `ProcessingConfig` with `engine_type="api-docs"`
- **THEN** it SHALL skip standard parsing (`parser_registry.parse`), standard chunking (`create_chunking_service`), and standard embedding loops
- **THEN** it SHALL call `_process_api_doc(document_id, file_path, doc_type)` instead
- **AND** standard progress tracking (`update_document_progress`, `mark_document_failed`) SHALL still apply

#### Scenario: api-docs document marked completed after processing
- **WHEN** `_process_api_doc()` completes successfully
- **THEN** `document.status` SHALL be set to `"completed"`
- **THEN** `document.processing_message` SHALL be `"Indexed for API doc querying"`
- **AND** `document.chunk_count` SHALL reflect the ChunkGraph node count

### Requirement: Type patterns for entity name extraction

The api-docs pipeline SHALL use configurable regex patterns to extract entity names from DOCX headings. Patterns SHALL be per entity type: `interface`, `enum`, `record`, `error_code`.

**Detection order:**
1. The heading name is extracted via `_extract_interface_name()` (existing logic — strips leading number, brackets, etc.)
2. The extracted name is matched against `type_patterns` in order: `interface` → `enum` → `record` → `error_code`
3. The first matching type determines the entity type
4. If no pattern matches, a prefix-based fallback SHALL be applied:
   - `I` followed by uppercase → interface
   - `E` followed by uppercase → enum
   - `R` followed by uppercase → record
5. If no pattern or prefix matches, the heading SHALL be treated as a section (no entity created)

Default `type_patterns`:
```yaml
type_patterns:
  interface: ["^I[A-Z]\\w+"]
  enum: ["^E[A-Z]\\w+"]
  record: ["^R[A-Z]\\w+"]
```

#### Scenario: Heading matches interface pattern
- **WHEN** a DOCX heading contains "IMyInterface" and `type_patterns` has `interface: ["^I[A-Z]\\w+"]`
- **THEN** the entity type SHALL be `interface` with name "IMyInterface"

#### Scenario: Heading matches enum pattern
- **WHEN** a DOCX heading contains "EColor" and `type_patterns` has `enum: ["^E[A-Z]\\w+"]`
- **THEN** the entity type SHALL be `enum` with name "EColor"

#### Scenario: Heading matches no pattern — prefix fallback
- **WHEN** a DOCX heading contains "IMyInterface" but no `type_patterns` are defined (empty or null)
- **THEN** the prefix-based fallback SHALL detect `interface` from the `I` prefix

#### Scenario: Heading matches no pattern and no prefix — treated as section
- **WHEN** a DOCX heading contains "Overview" and no pattern matches and no prefix matches
- **THEN** no APIInterface SHALL be created for this heading — it SHALL be a section grouping

#### Scenario: Multiple patterns per type
- **WHEN** `type_patterns` has `interface: ["^I[A-Z]\\w+", "Service$"]` and a heading contains "UserService"
- **THEN** the entity type SHALL be `interface` (matches second pattern)

---

### Requirement: Heading policy for interface nesting

The api-docs pipeline SHALL use `heading_policy` to control how DOCX heading levels (Heading 1, Heading 2, etc.) map to interface nesting depth. The policy SHALL have three lists:
- `interface_levels`: heading levels that create interfaces (nesting depth determined by position in list)
- `section_levels`: heading levels that create section groupings (no APIInterface)
- `ignore_levels`: heading levels to skip entirely

**Nesting depth rules:**
- The nesting depth of an interface equals the index of its heading level within `interface_levels`
- Depth 0 = root interface
- Depth 1+ = child interface (sets `base_interface` to nearest shallower-depth interface ID)

Default `heading_policy`:
```yaml
heading_policy:
  interface_levels: [0, 1, 2, 3, 4]
  section_levels: [3]
  ignore_levels: []
```

#### Scenario: Heading level creates root interface
- **WHEN** a Heading 1 with text "IMyInterface" is processed and `interface_levels` contains 0
- **THEN** an `APIInterface` SHALL be created with name "IMyInterface"
- **AND** `base_interface` SHALL be `None` (depth = 0 in interface_levels)

#### Scenario: Heading level creates nested child interface
- **WHEN** a Heading 2 with text "IChildInterface" follows a Heading 1 with "IParentInterface" and `interface_levels` contains both 0 and 1
- **THEN** the child's `base_interface` SHALL be set to the `IParentInterface` interface's ID

#### Scenario: Heading level in section_levels does not create interface
- **WHEN** a Heading 3 with text "Methods" is processed and `interface_levels`=[0,1,2,3,4] and `section_levels`=[3]
- **THEN** no APIInterface SHALL be created — section grouping only

#### Scenario: Heading level in ignore_levels is skipped
- **WHEN** a Heading 1 with text "Appendix" is processed and `ignore_levels`=[0]
- **THEN** the heading SHALL be skipped entirely — no entity, no section, no tracking in heading_stack

#### Scenario: Interface levels with gaps
- **WHEN** `interface_levels`=[0, 2] and a Heading 2 with "IChild" follows a Heading 1 with "IParent"
- **THEN** "IChild" SHALL have depth 1 (index of 2 in interface_levels = 1)
- **AND** its `base_interface` SHALL be set to "IParent" (nearest shallower depth)

---

### Requirement: Positional column layout per table type

The api-docs converter SHALL use hardcoded positional column indices (not configurable column names) for each table type. Positions are determined by the actual table layout in the real DOCX files and are not configurable.

| Type | Col 0 | Col 1 | Col 2 |
|------|-------|-------|-------|
| method | return_type | name(`params`) or param_name or func_desc | param_desc |
| property | type | name+desc (combined) | — |
| record | field_type | field_name | field_desc |
| enum | — / "enum" | `name = value` or `{` `}` | desc |
| error_code | — / "enum" | `name = value` | desc |

#### Scenario: Method extraction uses positional columns
- **WHEN** a table is detected as type `"method"`
- **THEN** column 0 is parsed as the return type
- **AND** column 1 is parsed as the method name with inline parameters `name(params)`
- **AND** rows with empty col 0 after a function signature are treated as parameter descriptions or function-level description text

#### Scenario: Property extraction uses col 0 for type, col 1 for combined name+desc
- **WHEN** a table is detected as type `"property"`
- **THEN** column 0 is parsed as the property type
- **AND** column 1 is split heuristically into name and description (bullet ` • ` → bracket ` [` → word-boundary fallback)

#### Scenario: Column positions are not configurable
- **WHEN** `_apply_config()` is called
- **THEN** no `method_table` or column-position config SHALL be accepted — positions are hardcoded per type

---

### Requirement: Formatting parameters

The api-docs text formatter (`ChunkTextFormatter`) SHALL accept formatting parameters from the strategy's `config`:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_depth` | int | 3 | Maximum nesting depth for chunk tree traversal (0 = all) |
| `include_entities` | list[str] \| null | null | Whitelist of entity types to include (null = all) |
| `format_style` | str | "detailed" | `"detailed"` (full descriptions + signatures) or `"compact"` (names only) |
| `include_signatures` | bool | true | Include method/field signatures in output |
| `include_descriptions` | bool | true | Include text descriptions in output |

#### Scenario: Formatter respects max_depth
- **WHEN** `max_depth=1` and the chunk tree has nested interfaces
- **THEN** only root interfaces and their direct children are included in formatted text

#### Scenario: Formatter respects include_entities whitelist
- **WHEN** `include_entities=["interface", "enum"]` and the chunk graph also contains records
- **THEN** only interfaces and enums SHALL appear in the formatted output

#### Scenario: Formatter respects format_style
- **WHEN** `format_style="compact"`
- **THEN** the output SHALL include entity names and method signatures only — no descriptions

---

### Requirement: ChunkGraphBuilder creates nested chunk nodes

The `ChunkGraphBuilder` SHALL use `APIInterface.base_interface` to build nested chunk nodes. When `base_interface` is set, the interface's chunk node SHALL be a child of the parent interface's chunk node.

#### Scenario: Nested interfaces create parent-child chunks
- **WHEN** `IChild` has `base_interface` set to `IParent`
- **THEN** `IChild`'s chunks SHALL be nested under `IParent`'s chunks in the chunk graph
- **AND** the chunk tree depth is determined by `max_depth` from config

#### Scenario: Flat entities remain at root level
- **WHEN** an enum `EColor` has `base_interface=None`
- **THEN** its chunks SHALL be at root level in the chunk graph (depth 0)

---

### Requirement: Entity-to-interface ownership for enums, records, and error codes

Every `APIEnum`, `APIRecord`, and `APIErrorCode` SHALL carry the name of the interface they belong to. This ensures that the RAG answer context includes the owning interface name for all entity types.

**Detection at conversion time:**
When an enum table, error-code table, or record table is processed, the converter SHALL:
1. Extract the interface name from the table's heading context (existing `_extract_interface_name()` logic)
2. Set `parent_interface` on the entity to the extracted name (or leave `None` if no interface detected)

**Propagation into chunk graph:**
The `ChunkGraphBuilder` SHALL include `interface_name` in the metadata of enum, error-code, and record chunk nodes (matching the pattern already used for method and property nodes).

#### Scenario: Enum carries parent interface name
- **WHEN** an enum table appears after a heading with text "IFooBar Interface" that matches `_INTERFACE_RE`
- **THEN** the resulting `APIEnum` SHALL have `parent_interface` set to `"IFooBar"`
- **AND** the enum's chunk node in the graph SHALL have `interface_name` set to `"IFooBar"` in its metadata

#### Scenario: Error code carries parent interface name
- **WHEN** an error-code table appears after a heading with text "ISomeInterface"
- **THEN** each `APIErrorCode` SHALL have `parent_interface` set to `"ISomeInterface"`
- **AND** each error-code's chunk node SHALL have `interface_name` set to `"ISomeInterface"`

#### Scenario: Record carries parent interface name
- **WHEN** a record table appears after a heading with text "IFooBar Interface"
- **THEN** the resulting `APIRecord` SHALL have `parent_interface` set to `"IFooBar"`
- **AND** its chunk node SHALL have `interface_name` set to `"IFooBar"` in its metadata
- **AND** each `APIRecordField` SHALL be nested as a child record_field node under the record node

#### Scenario: Record table conversion with field extraction
- **WHEN** a record table has data rows with member name in column 0, type in column 1, and description in column 2
- **THEN** each row SHALL produce one `APIRecordField` with `name`, `type_annotation`, and `description` populated from those columns
- **AND** the record name SHALL come from the heading context

#### Scenario: Record table with only name and type (no description)
- **WHEN** a record table has only 2 data columns (name, type) with no description column
- **THEN** each `APIRecordField` SHALL have an empty `description`

#### Scenario: Enum at document root (no parent interface)
- **WHEN** an enum table appears before any interface heading
- **THEN** the resulting `APIEnum` SHALL have `parent_interface` set to `None`
- **AND** its chunk node SHALL have `interface_name` set to `""`

#### Scenario: RAG context includes interface for all entity types
- **WHEN** a query retrieves an enum/record/error-code chunk with `interface_name="IFooBar"`
- **THEN** the answer generation prompt SHALL include `"Interface: IFooBar"` in that source's context block
- **AND** the LLM SHALL be able to state which interface the entity belongs to