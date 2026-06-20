## ADDED Requirements

### Requirement: Fix prompt contradiction

The system SHALL resolve the conflict between citation and no-verbatim instructions in `build_prompt()`. When `include_citations=True`, the prompt MUST instruct the model to cite sources using `[Source N]` format and MUST NOT include the "Never include '[Source N]' labels" directive. When `include_citations=False`, the prompt MUST NOT include either citation instruction.

#### Scenario: Citation instruction active without contradiction

- **WHEN** `include_citations=True` in a query request
- **THEN** the prompt MUST include "For EVERY factual statement... include a source citation in brackets like [Source 1]" and MUST NOT include "Never include '[Source N]' labels in your answer"

### Requirement: Remove "in your own words" anti-pattern

The system SHALL remove the instruction "Answer concisely in your own words" from the prompt. The prompt SHALL instruct the model to quote or closely paraphrase sources instead of rephrasing freely.

#### Scenario: Prompt encourages verbatim grounding

- **WHEN** the prompt is built for any query
- **THEN** the system SHALL NOT include the phrase "in your own words" in the system instructions
- **THEN** the prompt SHALL include "Quote or closely paraphrase the sources" instead

### Requirement: Mandatory inline citations

When `include_citations=True`, the system SHALL require the model to include a `[Source N]` citation for every factual statement. The instruction SHALL be unconditional: "For EVERY factual statement you make, you MUST include a source citation in brackets like [Source 1] immediately after the statement." The prompt SHALL also include: "If a statement is not supported by any source, you MUST NOT make it. Do not guess or use outside knowledge."

#### Scenario: Citation enforcement in prompt

- **WHEN** the prompt is built with `include_citations=True`
- **THEN** the prompt SHALL contain the mandatory citation instruction with explicit "MUST" language
- **THEN** the prompt SHALL contain "Do not guess or use outside knowledge"

#### Scenario: No citation instruction when disabled

- **WHEN** the prompt is built with `include_citations=False`
- **THEN** the prompt SHALL NOT include any citation-related instructions

### Requirement: Negative reinforcement for hallucination

The prompt SHALL include explicit negative instructions: "Do not add information that is not present in the sources. It is better to say 'I don't know' than to make up information."

#### Scenario: Prompt includes guardrails

- **WHEN** the prompt is built for any query
- **THEN** the system SHALL include "It is better to say 'I don't know' than to make up information" in the system instructions

### Requirement: Post-processing citation validation

When `include_citations=True`, the `clean_response()` function SHALL parse and validate all `[Source N]` citations in the generated response. Citations that reference invalid source indices (e.g., [Source 0], [Source 99]) SHALL be replaced with the best-matching source based on embedding similarity. Sentences without citations SHOULD have citations retroactively attached when a clear source match exists.

#### Scenario: Citation validation and retroactive matching

- **WHEN** the response contains a citation `[Source 0]` or `[Source 99]`
- **THEN** the system SHALL replace it with the best-matching valid source citation based on embedding similarity
- **WHEN** a sentence has no citation and `include_citations=True`
- **THEN** the system SHOULD attempt to match it to the most similar source chunk and insert a citation
