## ADDED Requirements

### Requirement: Async multi-backend query execution

The system SHALL execute queries across multiple selected RAG backends asynchronously and concurrently using `asyncio.gather()`.

- Each backend SHALL execute as an independent async task
- The system SHALL allow retrieval phases (document search, embedding, BM25 ranking) to run concurrently across backends
- The system SHALL serialize only the GPU-bound LLM `generate()` calls via the existing `_generate_lock`
- The overall query task SHALL have a maximum wall-clock timeout of 300 seconds from creation
- Each individual backend SHALL report its status (running, completed, failed, timed_out) independently

#### Scenario: All backends complete successfully
- **WHEN** a query is submitted with 3 backends selected
- **THEN** all 3 backends execute concurrently
- **THEN** each backend's result is available independently as it completes
- **THEN** the overall task status transitions to "completed" when all backends finish

#### Scenario: One backend times out
- **WHEN** a backend exceeds its individual timeout
- **THEN** that backend returns a "timed_out" error
- **THEN** the other backends continue executing uninterrupted
- **THEN** the overall task status transitions to "completed" once all non-timed-out backends finish

#### Scenario: Retrieval phases overlap across backends
- **WHEN** 3 backends execute via `asyncio.gather()`
- **THEN** the retrieval phases (document search, BM25 ranking, embedding) of different backends execute concurrently
- **THEN** only the LLM `generate()` calls are serialized by `_generate_lock`
- **THEN** this concurrency is verifiable via trace-level logging of lock acquire/release timestamps

### Requirement: LangChain backend timeout

The LangChain backend SHALL have a maximum execution timeout of 240 seconds. If execution exceeds this limit, the backend SHALL return a timeout error without crashing the overall task.

The timeout value SHALL be configurable via a `LANGCHAIN_TIMEOUT` constant (in `_executor.py` or `src/core/config.py`), defaulting to 240 seconds.

#### Scenario: LangChain completes within timeout
- **WHEN** LangChain backend execution finishes within 240 seconds
- **THEN** the result is included in the task results

#### Scenario: LangChain exceeds timeout
- **WHEN** LangChain backend execution exceeds 240 seconds
- **THEN** `asyncio.TimeoutError` is caught
- **THEN** a timeout error entry is returned in the results with `backend="langchain"`, `answer=null`, `error="LangChain backend timed out"`
- **THEN** the overall task continues (other backends are unaffected)

#### Scenario: Configurable timeout used in tests
- **WHEN** tests set `LANGCHAIN_TIMEOUT` to a lower value (e.g., 1 second)
- **THEN** a slow LangChain backend times out within the test-configured duration
- **THEN** the timeout error is returned without waiting the full default 240s

### Requirement: Backend result isolation

Each backend SHALL return an independent result dictionary containing at minimum: `backend` (name), `answer` (text or null), `error` (string or null), and `status`. A failure or timeout in one backend SHALL NOT affect the results of other backends.

#### Scenario: Partial results
- **WHEN** 2 of 3 backends complete successfully and 1 fails
- **THEN** the task status response includes results from all 3 backends
- **THEN** the 2 successful backends have populated `answer` fields
- **THEN** the failed backend has a populated `error` field and null `answer`

#### Scenario: Independent timeout
- **WHEN** LangChain backend times out
- **THEN** cosine similarity and LlamaIndex results are returned normally
- **THEN** the frontend can display partial results immediately

### Requirement: LLM lock scope confirmation

The system SHALL confirm that the `_generate_lock` in `MLXLLM.generate()` is only held during the GPU-bound inference call, not during document retrieval or post-processing. Trace-level logging SHALL be added at lock acquire/release points to verify concurrent retrieval execution in production.

#### Scenario: Lock correctly scoped
- **WHEN** any backend executes
- **THEN** document retrieval runs without acquiring `_generate_lock`
- **THEN** `_generate_lock` is acquired only for the `MLXLLM.generate()` inference call
- **THEN** trace logs record lock acquisition timing for verification
