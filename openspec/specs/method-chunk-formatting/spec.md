# Method Chunk Formatting

## Purpose

Define the formatting rules for API documentation method chunks, including inline parameter descriptions that make method chunks self-contained for LLM prompting.

## Requirements

### Requirement: Method chunk SHALL include parameter descriptions inline

When `include_descriptions` is enabled in the chunk text formatter, method chunk content SHALL include the name, type, and description of each parameter below the method signature. This makes method chunks self-contained for LLM prompting, eliminating the dependency on separate parameter-level chunks being retrieved.

Format:
```
FunctionName(param1: type1, param2: type2) -> ReturnType: Description
  param1 (type1): Description of param1
  param2 (type2): Description of param2
```

#### Scenario: Parameter descriptions appended below signature
- **WHEN** a method has parameters with non-empty descriptions
- **AND** `include_descriptions` is `True`
- **THEN** the method chunk content SHALL contain one line per parameter below the signature line
- **AND** each line SHALL begin with two spaces, followed by `paramName (paramType): paramDescription`

#### Scenario: Parameter descriptions not included when disabled
- **WHEN** `include_descriptions` is `False`
- **THEN** the method chunk content SHALL be the signature only (no parameter detail lines appended)

#### Scenario: No parameter description lines when all descriptions empty
- **WHEN** a method has parameters but all descriptions are empty
- **THEN** the method chunk content SHALL NOT include parameter detail lines (only signature, matching current behavior)

#### Scenario: Metadata fallback includes parameter descriptions
- **WHEN** the method chunk is formatted via the metadata-based fallback (`_meta_method`)
- **AND** the metadata contains parameter name/type/description arrays
- **AND** `include_descriptions` is `True`
- **THEN** the fallback content SHALL include the same inline parameter detail lines

### Requirement: DSPy generation SHALL include parameter details

The `APIResponseGenerator` answer signature SHALL instruct the LLM to include parameter names, types, descriptions, and usage patterns in its generated answers. This ensures the prompt asks for the right level of detail.

#### Scenario: Answer includes parameter details when prompted
- **WHEN** a user asks how to use a specific function
- **AND** the function has parameters with descriptions in the context
- **THEN** the generated answer SHALL name the function parameters and describe how to use them

#### Scenario: Answer without parameters stays concise
- **WHEN** a user asks about a property, enum, or interface with no function parameters
- **THEN** the generated answer SHALL NOT fabricate parameter information
