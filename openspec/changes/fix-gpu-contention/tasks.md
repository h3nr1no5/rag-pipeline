## 1. Add asyncio.Lock to MLXLLM

- [ ] 1.1 Add `self._generate_lock: asyncio.Lock = asyncio.Lock()` in `MLXLLM.__init__()` (after `self._load_lock`)
- [ ] 1.2 In `MLXLLM.generate()`, wrap the `asyncio.to_thread(generate, ...)` call in `async with self._generate_lock:` — preamble (chat template, prompt hashing) stays outside the lock
- [ ] 1.3 In `MLXLLM.generate_stream()`, wrap ONLY the `asyncio.to_thread(lambda: list(generate_tokens()))` call in `async with self._generate_lock:` — preamble AND the post-inference token-yielding loop (`for token in all_tokens: ... yield token`) stay outside the lock
- [ ] 1.4 Verify `asyncio` import already exists at top of `src/domain/services/llm.py` (currently imported for `asyncio.to_thread` usage — confirm no new import needed)

## 2. Frontend Loading Indicators

- [ ] 2.1 In `client/pages/3_💬_Chat.py`, before the `ThreadPoolExecutor` block (line ~519), render per-backend loading indicators:
  - For each backend in `selected_rags`, create a `st.chat_message("assistant", avatar=AVATARS[rag_type])` containing `st.empty()` placeholder with `st.info("⏳ **Label** — thinking...")`
  - Store placeholders in a `rag_placeholders` dict keyed by `rag_type`
- [ ] 2.2 Inside the `as_completed()` loop, replace each completed backend's placeholder with its result:
  - `placeholder.empty()` then `placeholder.container()` → `render_message("assistant", result["answer"], result.get("sources", []), avatar_img=AVATARS[rag_type], label=label, include_citations=params["include_citations"])`
  - Handle errors: `placeholder.empty()` → `st.error(result["answer"])`
  - Other backends' indicators remain visible
- [ ] 2.3 Keep `st.session_state.messages` append and `st.rerun()` unchanged at end of block
- [ ] 2.4 Run `ruff check client/pages/3_💬_Chat.py` to verify clean

## 3. Profile Baseline Comparison

- [ ] 3.1 Run `scripts/run_profile.sh` and save baseline to `before_gpu_lock.log` — verify it matches existing `before_profile.log` (no external drift)
- [ ] 3.2 Run `scripts/run_profile.sh` after lock change, save to `after_gpu_lock.log`
- [ ] 3.3 Diff the two logs — all 11 `[PROFILE]` lines present in both; individual step timings should be approximately equal (lock adds ~1µs overhead, which is noise vs multi-second MLX inference)

## 4. Verification

- [ ] 4.1 Run full unit test suite: `uv run pytest tests/unit/ -q`
- [ ] 4.2 Run real-model integration tests: `uv run pytest tests/integration/real_models/ -v --log-cli-level=INFO -s | grep -E "PROFILE|PASSED|FAILED|ERROR"`
- [ ] 4.3 Run lint: `uv run ruff check .`
- [ ] 4.4 Run type check: `uv run mypy src/`
