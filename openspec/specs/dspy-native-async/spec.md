# DSPy Native Async

## Purpose

Define the native async DSPy pipeline execution layer that eliminates `asyncio.run()` bridging from the API docs RAG pipeline, enabling event-loop-safe execution in all async contexts (FastAPI server, pytest-asyncio tests).

## Requirements

### Requirement: MLXDspyLM SHALL provide async forward method

`MLXDspyLM` SHALL implement `async def aforward(self, prompt=None, messages=None, **kwargs)` that calls `await self._llm.generate(...)` directly without `asyncio.run()`.

#### Scenario: Async forward generates via await
- **WHEN** `aforward()` is called with a valid prompt
- **THEN** it SHALL `await self._llm.generate(final_prompt, ...)` on the current event loop
- **AND** return an OpenAI-chat-compatible `SimpleNamespace` object

#### Scenario: Sync forward preserved for compatibility
- **WHEN** `forward()` is called (sync context)
- **THEN** it SHALL use `asyncio.run()` as before (unchanged behavior)
- **AND** NOT raise a RuntimeError when no event loop is running

#### Scenario: Temperature override in async forward
- **WHEN** `aforward()` is called with `temperature=0.7` in kwargs
- **THEN** the value SHALL be passed to `self._llm.generate(temperature=0.7, ...)`

#### Scenario: Max tokens override in async forward
- **WHEN** `aforward()` is called with `max_tokens=1024` in kwargs
- **THEN** the value SHALL be passed to `self._llm.generate(max_tokens=1024, ...)`

### Requirement: APIDocRAG SHALL provide async forward method

`APIDocRAG` SHALL implement `async def aforward(self, question, top_k=10, temperature=None, max_tokens=None)` that mirrors `forward()` logic using `await` for all async operations.

#### Scenario: Async pipeline steps match sync
- **WHEN** `aforward()` runs
- **THEN** it SHALL execute: input validation, hybrid retrieval via `await`, context formatting, response generation via `await response_generator.acall()`, assertion validation, and optional fallback via `await fallback_generator.acall()`

#### Scenario: Empty retrieval in async path
- **WHEN** `aforward()` retrieves no chunks
- **THEN** it SHALL return the same empty-response dict as `forward()`

#### Scenario: Async fallback on generation failure
- **WHEN** `response_generator.acall()` raises an exception
- **THEN** `aforward()` SHALL catch the exception and call `fallback_generator.acall()`
- **AND** return a response with `used_fallback=True`
