# Response Formatting — Delta Spec

> Delta spec for the `response-formatting` capability.
> Existing requirements for `[Page N]` stripping, `[Source N]` handling,
> streaming buffering, SSE ordering, and client-side citation display
> remain unchanged.

## ADDED Requirements

### Requirement: Markdown formatting preserved in LLM responses

The `clean_response()` function SHALL preserve Markdown formatting (bold, italic, headings, lists, horizontal rules) in the LLM output. It SHALL continue to strip `[Page N]` markers and conditionally strip `[Source N]` markers based on `include_citations`.

#### Scenario: Bold text preserved

- **WHEN** the LLM output contains `**bold text**` or `__bold text__`
- **THEN** `clean_response()` SHALL NOT modify the bold markers
- **AND** the rendered response SHALL display bold text

#### Scenario: Italic text preserved

- **WHEN** the LLM output contains `*italic text*` or `_italic text_`
- **THEN** `clean_response()` SHALL NOT modify the italic markers
- **AND** the rendered response SHALL display italic text

#### Scenario: Headings preserved

- **WHEN** the LLM output contains `# `, `## `, `### ` headings
- **THEN** `clean_response()` SHALL NOT remove the heading markers
- **AND** the rendered response SHALL display headings

#### Scenario: Lists preserved

- **WHEN** the LLM output contains bullet lists (`- item`) or numbered lists (`1. item`)
- **THEN** `clean_response()` SHALL NOT modify list markers
- **AND** the rendered response SHALL display formatted lists

#### Scenario: Horizontal rules preserved

- **WHEN** the LLM output contains `---` or `***` on its own line
- **THEN** `clean_response()` SHALL NOT remove the horizontal rule
- **AND** the rendered response SHALL display a horizontal rule

#### Scenario: Strikethrough preserved

- **WHEN** the LLM output contains `~~strikethrough text~~`
- **THEN** `clean_response()` SHALL NOT modify the strikethrough markers
- **AND** the rendered response SHALL display strikethrough text

#### Scenario: `[Page N]` still stripped

- **WHEN** the LLM output contains `[Page 3]` markers
- **THEN** `clean_response()` SHALL still remove them (unchanged behavior)
- **AND** `[Source N]` markers SHALL still be conditionally stripped based on `include_citations`

### Requirement: Frontend preserves Markdown formatting in display

The client-side `strip_markdown_formatting()` function SHALL preserve Markdown formatting (bold, italic, headings, lists) in displayed text. It SHALL continue to strip `[Page N]` markers as a safety net and conditionally strip `[Source N]` markers based on `include_citations`.

#### Scenario: Frontend preserves bold/italic/headings

- **WHEN** response text contains Markdown formatting (`**bold**`, `*italic*`, `# heading`)
- **THEN** `strip_markdown_formatting()` SHALL NOT modify Markdown markers
- **AND** `st.markdown()` SHALL render them as formatted text

#### Scenario: Frontend continues to strip `[Page N]`

- **WHEN** response text contains `[Page N]` markers
- **THEN** `strip_markdown_formatting()` SHALL still remove them (defense in depth)
- **AND** `[Source N]` markers SHALL still be conditionally stripped

### Requirement: LLM prompted to use Markdown formatting

The `build_prompt()` function SHALL instruct the LLM to use Markdown formatting in its response, replacing the current instruction that prohibits it.

#### Scenario: Prompt encourages formatting

- **WHEN** `build_prompt()` constructs the system message
- **THEN** the instruction SHALL tell the LLM to use headings, bold, and lists as appropriate
- **AND** the instruction SHALL NOT tell the LLM to avoid Markdown formatting

#### Scenario: Citation instruction unchanged

- **WHEN** `build_prompt()` is called with `include_citations=True`
- **THEN** the citation instruction SHALL still be included (unchanged)
- **AND** context chunks SHALL still be prefixed with `[Source N]` labels
