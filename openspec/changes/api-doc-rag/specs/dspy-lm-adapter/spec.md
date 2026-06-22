## ADDED Requirements

### Requirement: Wrap MLXLLM as dspy.BaseLM
The system SHALL implement a `MLXDspyLM` class that inherits from `dspy.BaseLM` and wraps the existing `MLXLLM` singleton. The adapter MUST:
- Accept the same model configuration as the existing MLXLLM (model name, temperature, max_tokens, repetition_penalty)
- Implement the `forward()` method expected by DSPy for synchronous inference
- Return responses in the format DSPy expects (OpenAI-compatible response object shape)
- Use the existing singleton cache (do not reload the model)
- Be usable as `dspy.configure(lm=mlx_dspy_lm)`

#### Scenario: DSPy uses MLXLM for generation
- **WHEN** `dspy.ChainOfThought` calls `lm.generate()`
- **THEN** `MLXDspyLM.forward()` delegates to `MLXLLM.generate()` with the prompt extracted from DSPy's message format
- **AND** the response is returned in DSPy's expected format

#### Scenario: Singleton is preserved
- **WHEN** `MLXDspyLM` is instantiated multiple times
- **THEN** the underlying MLX model is loaded only once (reuses the existing singleton pattern)

### Requirement: Configure DSPy with local MLX LM
The system SHALL configure DSPy to use the MLX LM as its default model at application startup. No external API keys or network calls SHALL be required for DSPy's LM operations.

The configuration SHALL happen once during application initialization, in the same location where the current `MLXLLM` singleton is initialized.

#### Scenario: DSPy default LM is MLX
- **WHEN** `dspy.ChainOfThought` is instantiated without an explicit `lm` parameter
- **THEN** DSPy uses the configured `MLXDspyLM` as the default
- **AND** text generation runs entirely on the local MLX backend

### Requirement: Support DSPy's deepcopy
The adapter SHALL implement `__deepcopy__` to return `self`, since DSPy's compilation process deep-copies modules and the underlying MLX model is not deepcopy-friendly.

#### Scenario: DSPy compilation does not crash
- **WHEN** `dspy.MIPROv2.compile()` is called (in future, when Q/A pairs exist)
- **THEN** the LM adapter's `__deepcopy__` returns `self` without attempting to deep-copy the MLX model
