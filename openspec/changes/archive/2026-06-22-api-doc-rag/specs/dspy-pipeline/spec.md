## ADDED Requirements

### Requirement: Define DSPy signatures for API documentation
The system SHALL define the following DSPy signatures:

1. **QueryAnalyzer**: Extracts search intent and target types from the user question
   - Input: `question: str`
   - Output: `search_queries: list[str]`, `target_types: list[str]`, `intent: str` (one of: "how_to", "reference", "troubleshooting")

2. **ContextAssembler**: Selects and orders chunks from retrieved results for optimal context
   - Input: `question: str`, `chunks: list[str]`
   - Output: `assembled_context: str`, `primary_chunk_id: str`

3. **APIResponseGenerator**: Generates the final answer with structured citations
   - Input: `context: str`, `question: str`
   - Output: `answer: str`, `citations: list[str]`, `relevant_functions: list[str]`, `relevant_types: list[str]`, `confidence: float`

All signatures SHALL use `dspy.InputField` and `dspy.OutputField` with descriptive docstrings.

#### Scenario: QueryAnalyzer extracts search intent
- **WHEN** a user asks "How do I create a node?"
- **THEN** QueryAnalyzer produces intent="how_to", search_queries containing "create node" and "CreateNode", target_types containing "INode"

#### Scenario: APIResponseGenerator produces structured answer
- **WHEN** the pipeline processes a question with retrieved context
- **THEN** the answer includes inline citations in the format `[FunctionName]` and a `citations` list of function/type names

### Requirement: Implement DSPy pipeline module
The system SHALL implement a `APIDocRAG` DSPy module that:
1. Calls `QueryAnalyzer` to extract search intent
2. Passes `search_queries` to the hybrid retriever
3. Calls `ContextAssembler` to construct the prompt context
4. Calls `APIResponseGenerator` to produce the final answer
5. Applies DSPy assertions for quality validation

The module SHALL inherit from `dspy.Module` and implement a `forward()` method.

#### Scenario: Pipeline produces answer for how-to query
- **WHEN** the pipeline receives "How do I add a material to an element?"
- **THEN** the pipeline returns an answer with step-by-step instructions referencing specific functions and types

### Requirement: DSPy assertions for quality
The system SHALL use `dspy.Suggest` to enforce at minimum these quality constraints:
- The answer MUST cite at least one function or type from the retrieved context
- If the question mentions a specific function name, the answer MUST reference that function
- Citations MUST reference functions/types that exist in the chunk graph

#### Scenario: Assertion catches missing citation
- **WHEN** the generated answer does not cite any function or type
- **THEN** the assertion fires and the pipeline retries or falls back to a simpler generation strategy

### Requirement: Evaluation metrics
The system SHALL implement at minimum these evaluation metrics (compatible with `dspy.Evaluate`):
- `retrieval_recall`: fraction of gold-standard functions/types present in top-5 retrieved chunks
- `citation_accuracy`: fraction of citations that reference actual functions/types
- `answer_completeness`: manual score (1-5) for whether the answer addresses the question
- `hallucination_rate`: fraction of statements in answer not supported by retrieved context

#### Scenario: Evaluate on test set
- **WHEN** `dspy.Evaluate` is called with a dev set of Q/A pairs
- **THEN** all metrics are computed and aggregated into a single score per metric
