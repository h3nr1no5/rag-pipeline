# API Docs RAG

## Purpose

Delta spec for the api-docs-rag capability — adding fallback prompt enhancements to include parameter-level detail in generated answers.

## ADDED Requirements

### Requirement: Fallback prompt SHALL request parameter names, types, and descriptions

The `_generate_answer()` fallback prompt SHALL instruct the LLM to include parameter names, types, and descriptions from the context for every function it mentions in its answer.

#### Scenario: Fallback answer includes parameter details
- **WHEN** the fallback path (`_generate_answer()`) generates a response
- **AND** the context contains function signatures with parameter descriptions
- **THEN** the prompt SHALL include an instruction to reproduce parameter names, types, and descriptions
- **AND** the generated answer SHALL contain parameter-level detail when the context supports it

#### Scenario: Fallback answer omits parameters when context lacks them
- **WHEN** the fallback path generates a response
- **AND** the context does not contain parameter descriptions
- **THEN** the answer SHALL NOT fabricate parameter details
- **AND** SHALL describe the function at the level of detail available in context

#### Scenario: Fallback answer follows existing citation rules
- **WHEN** the fallback path generates a response with parameter details
- **THEN** all parameter names and types SHALL use EXACT values from the context
- **AND** any hallucinated or invented parameter information is still subject to `ResponseVerifier` filtering downstream
