# API Docs RAG — Prompt and Retrieval Improvements

## Purpose

Delta spec for the `api-docs-rag` capability. Adds requirements for enum-accurate generation prompt and E-prefix enum cross-reference traversal in the LinkTraverser.

## ADDED Requirements

### Requirement: Generation prompt SHALL enforce exact enum values from context

The `_generate_answer()` prompt in `ApiDocPipelineManager` SHALL include an explicit instruction requiring the LLM to use exact enum member values from the provided context and never invent or approximate them.

#### Scenario: Prompt instructs exact enum values
- **WHEN** the generation prompt is constructed for an api-docs query
- **THEN** the prompt SHALL contain the instruction: `"Use EXACT enum values from context. Do not invent or approximate enum member names."`
- **AND** the instruction SHALL appear in the system prompt section, not as a user message

#### Scenario: LLM receives correct enum context
- **WHEN** the retrieved chunks include an `ENationalDesignCode` enum with values `["ndcEuroCode", "ndcBritishStandard", "ndcDIN"]`
- **AND** the query asks about adding a cross section from catalog
- **THEN** the prompt context SHALL include these exact enum values
- **AND** the instruction SHALL prevent the LLM from fabricating values like `"Steel"` or `"EuroCode"`

### Requirement: Generation prompt SHALL include citation markers

The generation prompt SHALL instruct the LLM to cite each source chunk using `[Source N]` markers, where `N` is the 1-based index of the relevant chunk in the provided context.

#### Scenario: Prompt instructs citation format
- **WHEN** the generation prompt is constructed
- **THEN** the prompt SHALL contain: `"Cite each source as [Source N] where N is the index of the relevant chunk."`
- **AND** the prompt SHALL include the chunk index alongside each context snippet (e.g., `[Source 1]`, `[Source 2]`)

#### Scenario: Response includes citations
- **WHEN** the LLM generates an answer using context chunks
- **THEN** the answer SHOULD reference sources using `[Source N]` markers inline
- **AND** the response metadata SHALL indicate whether citations were generated

### Requirement: Generation prompt SHALL include grounding and anti-repetition guardrails

The generation prompt SHALL include instructions to: (1) only use information from the provided context, declining to answer if insufficient; (2) avoid repeating the same information; (3) structure answers with clear sections when discussing multiple concepts.

#### Scenario: Prompt includes grounding instruction
- **WHEN** the generation prompt is constructed
- **THEN** the prompt SHALL contain: `"Only use information from the provided context. If the context does not contain the answer, say so."`

#### Scenario: Prompt includes anti-repetition guard
- **WHEN** the generation prompt is constructed
- **THEN** the prompt SHALL contain: `"Do not repeat the same information multiple times."`

#### Scenario: Prompt includes structure guidance
- **WHEN** the generation prompt is constructed
- **THEN** the prompt SHALL contain: `"Structure your answer with clear sections if multiple concepts are discussed."`

### Requirement: LinkTraverser SHALL follow E-prefix enum type cross-references

The api-docs `LinkTraverser` SHALL expand retrieval results by following `E`-prefix enum type references found in chunk content (e.g., `ENationalDesignCode`, `EMaterialType`), in addition to the existing `I`-prefix interface references. Matched enum type names SHALL be resolved to their corresponding enum chunk nodes for inclusion in the expanded result set.

#### Scenario: Enum type name in method signature triggers traversal
- **WHEN** a method chunk for `AddFromCatalog` contains the text `ENationalDesignCode` in its signature
- **AND** the retrieval step includes this chunk in the top-k results
- **THEN** `LinkTraverser` SHALL identify `ENationalDesignCode` as an `E`-prefix name match
- **AND** SHALL resolve it to the `ENationalDesignCode` enum chunk node ID
- **AND** SHALL include the `ENationalDesignCode` enum chunk (and its enum value children via ParentExpander) in the expanded results

#### Scenario: I-prefix interface references still followed
- **WHEN** a chunk contains an `I`-prefix name like `IAxisVMApplication`
- **THEN** the existing interface cross-reference behavior SHALL be unchanged
- **AND** both `I`-prefix and `E`-prefix matches SHALL be followed in the same traversal pass

#### Scenario: Enum name resolution uses dedicated mapping
- **WHEN** a matched enum name like `EMaterialType` is found
- **THEN** the system SHALL resolve it via an enum node ID map (analogous to the existing `_interface_name_to_id` mapping)
- **AND** SHALL NOT attempt to resolve it as an interface name

#### Scenario: Max traversal depth applies to enum references
- **WHEN** an enum chunk itself contains additional cross-references
- **THEN** the existing `max_depth` limit (default 2) SHALL apply to enum-originated traversal, preventing unbounded expansion

#### Scenario: Enum names without matching nodes are skipped silently
- **WHEN** chunk content contains text matching `\bE[A-Z][a-zA-Z0-9_]*\b` that does NOT correspond to any known enum node ID
- **THEN** the unmatched name SHALL be silently ignored (consistent with interface reference behavior)
