## ADDED Requirements

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
- `interface_levels`: heading levels that create interfaces (with nesting depth determined by position in list)
- `section_levels`: heading levels that create section groupings (no APIInterface)
- `ignore_levels`: heading levels to skip entirely

**Nesting depth rules:**
- The nesting depth of an interface equals the index of its heading level within `interface_levels`
- Depth 0 = root interface (no `base_interface`)
- Depth 1+ = child interface (`base_interface` set to nearest shallower-depth interface ID)
- Only interfaces nest; enums, records, and error_codes are always flat (no `base_interface`)

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

#### Scenario: Enums and records do not nest

- **WHEN** a Heading 2 with "EColor" follows a Heading 1 with "IParent" and the entity type is detected as `enum`
- **THEN** the enum's `base_interface` SHALL be `None` (enums are always flat)

#### Scenario: Interface levels with gaps

- **WHEN** `interface_levels`=[0, 2] and a Heading 2 with "IChild" follows a Heading 1 with "IParent"
- **THEN** "IChild" SHALL have depth 1 (index of 2 in interface_levels = 1)
- **AND** its `base_interface` SHALL be set to "IParent" (nearest shallower depth)

---

### Requirement: Method table column layout

The api-docs pipeline SHALL use `method_table` configuration to interpret table column positions when extracting methods. The `method_table` config SHALL specify:
- `return_type_col`: zero-based column index for return type (default 0)
- `name_col`: zero-based column index for method name with inline parameters (default 1)

Default `method_table`:
```yaml
method_table:
  return_type_col: 0
  name_col: 1
```

#### Scenario: Method extraction uses configured column indices

- **WHEN** a table is detected with `method_table.return_type_col=0` and `method_table.name_col=1`
- **THEN** column 0 is parsed as the return type
- **AND** column 1 is parsed as the method name with inline parameters (e.g., `SelectObject(id: long, name: string)`)

---

### Requirement: Formatting parameters

The api-docs text formatter (`ChunkTextFormatter`) SHALL accept formatting parameters from the strategy's `config`:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_depth` | int | 3 | Maximum nesting depth for chunk tree traversal (0 = all) |
| `include_entities` | list[str] \| null | null | Whitelist of entity types to include (null = all: `["interface", "enum", "record", "error_code"]`) |
| `format_style` | str | "detailed" | `"detailed"` (full descriptions + signatures) or `"compact"` (names only) |
| `include_signatures` | bool | true | Include method/field signatures in output |
| `include_descriptions` | bool | true | Include text descriptions in output |

#### Scenario: Formatter respects max_depth

- **WHEN** `max_depth=1` and the chunk tree has nested interfaces
- **THEN** only root interfaces (depth 0) and their direct children are included in formatted text

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
