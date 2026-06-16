## 1. Model Switch & Score Cleanup

- [x] 1.1 Update RERANKER_MODEL in `.env` to `Alibaba-NLP/gte-reranker-modernbert-base`
- [x] 1.2 Update RERANKER_MODEL default in `.env.example`
- [x] 1.3 Remove `trust_remote_code=True` from `retrieval_langchain.py` CrossEncoder instantiation (no longer needed)
- [x] 1.4 Remove min-max score normalization from `retrieval_langchain.py` (scores already [0,1])

## 2. Backend: Warmup State & Health Endpoint

- [x] 2.1 Create `WarmupState` singleton with per-model status (`loading`/`ready`/`error`), model name, progress (0-100), and optional error message
- [x] 2.2 Create `warmup_models()` async function iterating over cross-encoder + LLM, loading each via `asyncio.to_thread()` and updating `WarmupState`
- [x] 2.3 Launch `warmup_models()` via `asyncio.create_task` in FastAPI lifespan handler (`src/api/main.py`)
- [x] 2.4 Add `GET /health/models` endpoint returning `WarmupState` serialization
- [x] 2.5 Wrap `CrossEncoderReranker._ensure_model()` in `asyncio.to_thread()` for non-blocking lazy fallback load

## 3. Frontend: Model Status Polling & Display

- [x] 3.1 Add polling logic in `client/app.py` — poll `/health/models` every 200ms while any model is `loading`
- [x] 3.2 Add per-model progress bars above chat input using `st.progress()` and `st.empty()` placeholders
- [x] 3.3 Hide status section and make chat fully interactive once all models are `ready`
- [x] 3.4 Show error indicator if any model reaches `error` status

## 4. Graceful Error Handling

- [x] 4.1 Add cross-encoder failure check in LangChain query route — return HTTP 503 with error message if `WarmupState.cross_encoder.status == "error"`

## 5. Testing & Verification

- [x] 5.1 Run `uv sync` to verify no new dependency conflicts
- [x] 5.2 Run unit tests (`uv run pytest tests/unit/ -q`) — all pass
- [x] 5.3 Run integration tests (`TESTING=1 uv run pytest tests/integration/test_rag_comparison.py tests/integration/test_server_smoke.py -q`) — all pass
- [x] 5.4 Manual smoke test: start server, observe warmup progress on frontend, send a LangChain query, verify [0,1] scores in response
