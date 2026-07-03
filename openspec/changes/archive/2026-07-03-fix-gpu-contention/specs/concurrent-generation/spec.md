## ADDED Requirements

### Requirement: MLXLLM serializes concurrent generate() calls

The `MLXLLM` singleton SHALL serialize concurrent calls to `generate()` and `generate_stream()` using an `asyncio.Lock` so that only one MLX GPU inference operation runs at a time, preventing GPU-level contention when multiple RAG backends or concurrent requests hit the model simultaneously.

#### Scenario: Single caller acquires and releases lock

- **WHEN** a coroutine calls `MLXLLM.generate()` with no other concurrent callers
- **THEN** the lock SHALL be acquired immediately
- **THEN** the `asyncio.to_thread(mlx_lm.generate, ...)` call SHALL execute
- **THEN** the lock SHALL be released after the result is returned or an exception is raised

#### Scenario: Concurrent callers queue on the lock

- **WHEN** caller A is inside the lock (executing `asyncio.to_thread(mlx_lm.generate, ...)`)
- **AND** caller B invokes `MLXLLM.generate()` concurrently
- **THEN** caller B SHALL await the lock without spawning a thread
- **THEN** caller B SHALL acquire the lock and execute only after caller A releases it

#### Scenario: Lock is released on exception

- **WHEN** `asyncio.to_thread(generate, ...)` raises an exception inside the lock context
- **THEN** the `async with self._generate_lock` SHALL release the lock
- **THEN** the exception SHALL propagate to the caller as normal

### Requirement: Lock scope excludes preamble

The `asyncio.Lock` SHALL be acquired only for the `asyncio.to_thread()` call that runs MLX inference — NOT for the preamble steps (chat template formatting, prompt hashing, debug logging). This allows preamble work to overlap between concurrent callers.

#### Scenario: Preamble runs outside lock

- **WHEN** caller A holds the generation lock
- **AND** caller B invokes `generate()`
- **THEN** caller B SHALL perform chat template formatting and prompt hashing while caller A is still generating
- **THEN** caller B SHALL block only at the `async with self._generate_lock:` line

### Requirement: Streaming generation is also serialized

The `generate_stream()` method SHALL use the same `asyncio.Lock` so concurrent streaming calls do not contend on the GPU model.

#### Scenario: Concurrent streaming queues on the lock

- **WHEN** caller A is streaming tokens via `generate_stream()`
- **AND** caller B invokes `generate_stream()` or `generate()`
- **THEN** caller B SHALL await the lock
- **THEN** caller B SHALL start streaming only after caller A's stream generator completes (all tokens yielded)

### Requirement: Lock does not affect model loading

The generation lock SHALL be separate from the model loading lock (`self._load_lock`, a `threading.Lock` used in `_ensure_model_loaded`). These protect independent resources.

#### Scenario: Model loading and generation are independent

- **WHEN** the model is being loaded by `_ensure_model_loaded()`
- **AND** a caller invokes `generate()`
- **THEN** `generate()` SHALL await `_ensure_model_loaded()` (which uses `asyncio.to_thread(self._ensure_model_loaded)`)
- **THEN** once model is loaded, `generate()` SHALL acquire the generation lock and proceed with inference

### Requirement: Lock is inactive in demo mode

The lock SHALL be a no-op when `_model_loaded` is `False` (MLX not available). In demo mode, both `generate()` and `generate_stream()` return early before any `async with self._generate_lock:` is reached, so no serialization occurs. This avoids introducing unnecessary overhead in environments where MLX is not installed.

#### Scenario: Demo mode skips lock entirely

- **WHEN** `MLXLLM._model_loaded` is `False`
- **AND** a caller invokes `generate()` or `generate_stream()`
- **THEN** the method SHALL return the canned demo response without acquiring `self._generate_lock`
- **THEN** concurrent demo-mode callers SHALL NOT block each other

#### Scenario: Lock exists only on MLXLLM, not on LLM port implementations

- **GIVEN** `TestLLM` or `RealisticTestLLM` implement the abstract `LLM` port (not `MLXLLM`)
- **THEN** those test doubles SHALL NOT need or contain the `asyncio.Lock`
- **THEN** verification of the lock SHALL use the existing real-model profiling tests (`tests/integration/real_models/`), comparing `[PROFILE]` step timings before and after the change — proving the lock adds no measurable overhead to single-query paths

### Requirement: Streaming lock scope covers only MLX inference call

In `generate_stream()`, the `asyncio.Lock` SHALL wrap only the `asyncio.to_thread(lambda: list(generate_tokens()))` call — NOT the post-inference token-yielding loop (`for token in all_tokens: ... yield token`). This allows the next caller's generation to start while the previous caller continues yielding tokens to the client, and avoids holding the lock across token-by-token `yield` suspension points.

#### Scenario: Post-inference token yielding runs outside lock

- **WHEN** caller A's `asyncio.to_thread(list(generate_tokens()))` completes inside the lock
- **THEN** the lock SHALL be released immediately after the thread result is assigned to `all_tokens`
- **THEN** caller A SHALL yield individual tokens from `all_tokens` outside the lock
- **THEN** caller B SHALL be able to acquire the lock and start its own generation while caller A is still yielding tokens
