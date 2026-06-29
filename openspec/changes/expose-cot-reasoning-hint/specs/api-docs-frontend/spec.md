## ADDED Requirements

### Requirement: Chat UI SHALL display reasoning_hint in expandable section

When the API docs response includes a non-empty `reasoning_hint` field, the chat UI SHALL display a "💭 Reasoning" expandable section below the confidence badge and above the Relevant Functions section. The section SHALL contain the raw rationale text rendered as markdown.

#### Scenario: Reasoning hint displayed when present
- **WHEN** the API docs response includes a non-empty `reasoning_hint`
- **THEN** a `st.expander("💭 Reasoning")` section SHALL appear below the confidence badge
- **AND** the expander content SHALL display the raw `reasoning_hint` text

#### Scenario: Reasoning hint hidden when empty
- **WHEN** the API docs response has `reasoning_hint` set to `""`
- **THEN** no Reasoning expander SHALL be rendered
- **AND** the confidence badge, Relevant Functions, Relevant Types, and Sources SHALL display as normal

#### Scenario: Reasoning expander follows existing component pattern
- **WHEN** the Reasoning expander is rendered
- **THEN** it SHALL use the same `st.expander` pattern as the existing Sources, Relevant Functions, and Relevant Types sections
- **AND** it SHALL be collapsed by default
