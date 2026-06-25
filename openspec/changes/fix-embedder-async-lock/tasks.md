## 1. Fix SentenceTransformerEmbedder singleton guard

- [ ] 1.1 Add `import threading` to `src/domain/services/embedding.py` (replace the `asyncio` import with `threading` — only `asyncio.Lock` was needed; `asyncio.to_thread` is still needed for `embed_text`/`embed_texts`)
- [ ] 1.2 Replace `_embedder_lock = asyncio.Lock()` with `_embedder_lock = threading.Lock()` at module level
- [ ] 1.3 Create synchronous `_load_embedder_sync()` function with double-checked locking using `threading.Lock()`, mirroring the `MLXLLM._ensure_model_loaded()` pattern
- [ ] 1.4 Refactor `async def get_embedder()` to check `_embedder_instance` first, then delegate to `asyncio.to_thread(_load_embedder_sync)` if not loaded
- [ ] 1.5 Verify `get_embedder_stats()` and `reset_embedder()` remain unchanged

## 2. Fix CrossEncoderReRanker singleton guard

- [ ] 2.1 Add `import threading` to `src/domain/services/retrieval_langchain.py` (if not already present)
- [ ] 2.2 Replace `_lock = asyncio.Lock()` with `_lock = threading.Lock()` on the `CrossEncoderReRanker` class
- [ ] 2.3 Refactor `_ensure_model()` to delegate model construction to a synchronous inner function under `threading.Lock()`
- [ ] 2.4 Verify `rerank()` and other public methods are unaffected

## 3. Narrow exception handler in DSPy pipeline module

- [ ] 3.1 In `src/domain/rag/api_docs/pipeline/module.py`, change `except Exception:` at line 195 to `except (ValueError, asyncio.TimeoutError):`
- [ ] 3.2 Add `asyncio` import to module.py if not already present (it is — already at line 12)
- [ ] 3.3 Verify that the DSPy circuit-breaker in `manager.py:_query_dspy()` correctly catches any unexpected exceptions from `module.forward()` and falls back to prompt generation

## 4. Verify and test

- [ ] 4.1 Run existing unit tests: `uv run pytest tests/unit/ -v`
- [ ] 4.2 Run existing integration tests: `uv run pytest tests/integration/ -v -x`
- [ ] 4.3 Run full test suite with lint + typecheck: `uv run ruff check src/ && uv run mypy src/ && uv run pytest -v`
- [ ] 4.4 Start the server and verify first query against API docs returns a valid answer (not the "not found" fallback)
