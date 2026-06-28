# Async BM25 Loading

## Purpose

Ensure BM25 keyword index building runs in a thread pool so CPU-bound tokenization does not block the asyncio event loop during request handling.

## Requirements

### Requirement: BM25 SHALL be built in a thread pool

BM25 index construction (tokenization and term frequency computation) SHALL run via `asyncio.to_thread()` to avoid blocking the event loop.

#### Scenario: LangChain BM25 builds asynchronously
- **WHEN** `BM25Retriever.from_documents()` is called during LangChain retriever initialization
- **THEN** the call SHALL be wrapped in `await asyncio.to_thread()`
- **THEN** the event loop SHALL remain responsive for other requests during BM25 building

#### Scenario: LlamaIndex BM25 builds asynchronously
- **WHEN** `BM25Okapi(tokenized_docs)` is called during LlamaIndex hybrid retriever initialization
- **THEN** the call SHALL be wrapped in `await asyncio.to_thread()`
- **THEN** the event loop SHALL remain responsive for other requests during BM25 building

### Requirement: BM25 SHALL be initialized at most once

The BM25 index SHALL be built once and cached, with subsequent requests using the already-built index.

#### Scenario: First request builds BM25
- **WHEN** the first LangChain or LlamaIndex query arrives
- **AND** BM25 has not been built yet
- **THEN** BM25 SHALL be built asynchronously via `to_thread()`
- **THEN** the built index SHALL be stored for reuse

#### Scenario: Subsequent requests use cached index
- **WHEN** a second query arrives
- **AND** BM25 has already been built
- **THEN** the cached BM25 index SHALL be used
- **THEN** no new `to_thread()` call SHALL be made

### Requirement: Initialization functions SHALL be async

Functions that ensure BM25 is initialized (e.g., `_ensure_retriever`, `_ensure_components`) SHALL be async to support the `await to_thread()` call.

#### Scenario: Async initialization API
- **WHEN** `_ensure_retriever()` is called
- **THEN** it SHALL be an `async def` function
- **THEN** callers SHALL `await` it
