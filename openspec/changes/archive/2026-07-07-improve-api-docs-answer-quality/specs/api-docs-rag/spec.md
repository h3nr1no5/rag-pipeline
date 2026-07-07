## ADDED Requirements

### Requirement: Generated answer SHALL include parameter-level details

The `APIResponseGenerator` answer output SHALL include parameter names, types, descriptions, and usage guidance when the context contains function parameters with descriptions. The answer field description in the signature SHALL explicitly instruct the model to include parameter-level detail.

#### Scenario: Answer includes parameter details
- **WHEN** the context contains function signatures with parameter descriptions
- **AND** the question asks how to use the function
- **THEN** the answer SHALL name the parameters and describe their purpose
- **AND** SHALL reference the parameter types from the context
