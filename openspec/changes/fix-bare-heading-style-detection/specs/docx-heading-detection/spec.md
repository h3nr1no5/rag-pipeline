## ADDED Requirements

### Requirement: Heading level detection SHALL map bare "Heading" style to level 0

The `get_heading_level()` function SHALL map DOCX paragraph style names to heading levels as follows:

| Style name | Level | Behavior |
|------------|-------|----------|
| Any non-heading style | `-1` | Ignored by heading stack |
| `"Heading"` (bare, no number) | `0` | Top-level heading (above `Heading 1`) |
| `"Heading 1"` – `"Heading 6"` | `1` – `6` | Standard numbered headings |
| `"Title"` | `1` | Treated as level-1 heading |
| `"Subtitle"` | `2` | Treated as level-2 heading |

#### Scenario: Bare "Heading" style detected as level 0

- **WHEN** a DOCX paragraph has style name `"Heading"`
- **THEN** `get_heading_level()` SHALL return `0`

#### Scenario: Numbered heading styles return their level

- **WHEN** a DOCX paragraph has style name `"Heading 3"`
- **THEN** `get_heading_level()` SHALL return `3`

#### Scenario: Non-heading styles return -1

- **WHEN** a DOCX paragraph has style name `"Normal"` or empty string
- **THEN** `get_heading_level()` SHALL return `-1`

#### Scenario: Bare "Heading" creates heading context for tables

- **WHEN** a paragraph with bare `"Heading"` style (level `0`) is processed
- **THEN** the heading stack SHALL include it
- **AND** subsequent tables SHALL be assigned to its heading text as their interface context

#### Scenario: Heading 1 is nested under bare Heading in the stack

- **WHEN** a bare `"Heading"` paragraph (level `0`) appears
- **AND** a `"Heading 1"` paragraph (level `1`) appears later
- **THEN** the `"Heading 1"` SHALL be nested under the bare `"Heading"` in the heading stack
- **AND** tables between the two headings SHALL use the bare `"Heading"` text as context
- **AND** tables after the `"Heading 1"` SHALL use the `"Heading 1"` text as context
