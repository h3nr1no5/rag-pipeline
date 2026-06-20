## ADDED Requirements

### Requirement: LlamaIndex non-streaming path shall use the shared prompt builder

The non-streaming LlamaIndex endpoint (`POST /api/v1/query/llamaindex`) SHALL use the shared `build_prompt()` from `prompt_builder.py` instead of its own inline prompt format. This ensures the chat template split in `_apply_chat_template()` works correctly, producing proper system/user message separation.

#### Scenario: Non-streaming path uses build_prompt()

- **WHEN** `LlamaIndexRetriever.generate()` is called
- **THEN** it SHALL construct the prompt via `build_prompt()` from `prompt_builder.py`
- **AND** NOT use the inline prompt template or `_build_context()` method

#### Scenario: Response matches other backends for identical query

- **WHEN** the same query is sent to all three backends with the same `document_ids`
- **THEN** the LlamaIndex non-streaming response SHALL contain the same factual information as the cosine and LangChain responses
- **AND** NOT return "I don't have enough information to answer this question" when sources are present

### Requirement: LlamaIndex generate() shall use shared LLM singleton

The `generate()` method SHALL use the shared `get_llm()` singleton (from `llm.py`) for response generation, matching the streaming path.

#### Scenario: Generation uses shared LLM instance

- **WHEN** `LlamaIndexRetriever.generate()` generates a response
- **THEN** it SHALL use `get_llm()` to obtain the `MLXLLM` instance
- **AND** NOT delegate through `MLXLlamaIndexLLM.acomplete()` (which adds an unnecessary adapter layer)

### Requirement: generate() shall apply min_relevance_score filtering

The `generate()` method SHALL filter retrieved nodes by `min_relevance_score` before constructing the prompt, matching the behavior of `retrieve()` and the streaming path.

#### Scenario: Low-relevance nodes are excluded from context

- **WHEN** `generate()` retrieves nodes with scores below `settings.min_relevance_score`
- **THEN** those nodes SHALL be excluded from the context passed to `build_prompt()`
- **AND** if all nodes are filtered out, `generate()` SHALL return "I don't have enough information to answer this question."

### Requirement: generate() shall deduplicate retrieved chunks

The `generate()` method SHALL deduplicate retrieved chunks using the shared `deduplicate_chunks()` before passing them to `build_prompt()`, matching the streaming path.

#### Scenario: Duplicate chunks are removed before prompting

- **WHEN** retrieval returns chunks with overlapping content
- **THEN** `generate()` SHALL deduplicate them via `deduplicate_chunks()`
- **AND** only unique chunks SHALL appear in the prompt context
