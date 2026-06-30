## 1. Add asyncio.Lock to MLXLLM

- [ ] 1.1 Add `self._generate_lock: asyncio.Lock = asyncio.Lock()` in `MLXLLM.__init__()` (after `self._load_lock`)
- [ ] 1.2 In `MLXLLM.generate()`, wrap the `asyncio.to_thread(generate, ...)` call in `async with self._generate_lock:` — preamble (chat template, prompt hashing) stays outside the lock
- [ ] 1.3 In `MLXLLM.generate_stream()`, wrap ONLY the `asyncio.to_thread(lambda: list(generate_tokens()))` call in `async with self._generate_lock:` — preamble AND the post-inference token-yielding loop (`for token in all_tokens: ... yield token`) stay outside the lock
- [ ] 1.4 Verify `asyncio` import already exists at top of `src/domain/services/llm.py` (currently imported for `asyncio.to_thread` usage — confirm no new import needed)

## 2. Unit Tests

- [ ] 2.1 Create `tests/unit/test_llm_concurrency.py` — construct an `MLXLLM` instance with `_model_loaded = True`, mock `_ensure_model_loaded` to no-op, and mock `asyncio.to_thread` as a slow controllable call. Assert concurrent `generate()` calls execute sequentially (lock behavior) using asyncio barriers/events
- [ ] 2.2 Add test asserting lock is released on exception in `generate()` — mock `asyncio.to_thread` to raise after acquiring lock via `async with`, verify second concurrent caller proceeds and acquires lock
- [ ] 2.3 Add test asserting preamble steps (chat template, formatting, prompt hashing) run before lock acquisition — verify ordering via spy on `_apply_chat_template` while lock is held by another coroutine
- [ ] 2.4 Add test asserting demo mode (`_model_loaded = False`) bypasses lock entirely — two concurrent calls return immediately without blocking each other

## 3. Profile Baseline Comparison

- [ ] 3.1 Run `scripts/run_profile.sh` and save current baseline to `before_gpu_lock.log` (should match existing `before_profile.log` — verify no regression from unrelated changes)
- [ ] 3.2 Run `scripts/run_profile.sh` after lock change, save to `after_gpu_lock.log`
- [ ] 3.3 Diff the two logs — verify all 11 PROFILE lines present in both; note any timing differences

## 4. Verification

- [ ] 4.1 Run full unit test suite: `uv run pytest tests/unit/ -q`
- [ ] 4.2 Run real-model integration tests: `uv run pytest tests/integration/real_models/ -v --log-cli-level=INFO -s | grep -E "PROFILE|PASSED|FAILED|ERROR"`
- [ ] 4.3 Run lint: `uv run ruff check .`
- [ ] 4.4 Run type check: `uv run mypy src/`
