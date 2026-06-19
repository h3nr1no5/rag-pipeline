## MODIFIED Requirements

### Requirement: Citation instruction conditional on `include_citations`

**Change**: The `include_citations=False` scenario is updated so that `[Source N]` labels are always prepended to context chunks, regardless of citation preference. Only the citation instruction in the system prompt remains conditional.

The `build_prompt()` function SHALL conditionally include the `[Source N]` citation instruction in the system prompt based on the `include_citations` parameter. Context chunks SHALL always be prefixed with `[Source N]` labels to ensure proper prompt template splitting.

#### Scenario: Citation instruction included when True

- **WHEN** `build_prompt()` is called with `include_citations=True`
- **THEN** the system message SHALL include the instruction: *"For EVERY factual statement you make, you MUST include a source citation in brackets like [Source 1]"*
- **AND** context chunks SHALL be prefixed with `[Source N]` labels

#### Scenario: Source labels always present, citation instruction omitted when False

- **WHEN** `build_prompt()` is called with `include_citations=False`
- **THEN** the system message SHALL NOT include any citation instruction
- **AND** context chunks SHALL still be prefixed with `[Source N]` labels (unchanged from the True case)
- **AND** the LLM SHALL NOT be asked to cite sources
- **AND** `clean_response()` SHALL still strip `[Source N]` markers from the output when `include_citations=False`
