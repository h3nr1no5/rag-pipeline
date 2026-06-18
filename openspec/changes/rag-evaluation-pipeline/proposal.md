## Why

The RAG pipeline has 3 backends (cosine, LangChain hybrid, LlamaIndex) and 39 tests, but no systematic way to measure retrieval quality, answer faithfulness, or regression across changes. Without quantitative metrics, it's impossible to tell whether a change improves or degrades the system. This proposal adds an in-house evaluation pipeline so every change can be measured against a labeled dataset.

## What Changes

- New `src/evaluation/` module with:
  - Dataset loader (`eval_dataset.json` with labeled Q&A pairs)
  - Retrieval metrics: precision@k, recall@k, MRR (via content-matching ground truth)
  - Answer quality metrics: faithfulness (via existing `ResponseVerifier`), keyword recall
  - Performance metrics: latency per backend, cross-backend comparison
  - Report generator (JSON + Markdown) saved to `data/eval_reports/`
- New `data/eval_reports/` directory for timestamped evaluation reports (gitignored)
- New `tests/evaluation/test_eval_rag.py` with 2-3 smoke tests (imports, dataset loads, metrics compute)
- New `tests/evaluation/eval_dataset.json` with 5-10 labeled questions against existing test documents
- CI-compatible runner: `python -m src.evaluation.run --backends cosine,langchain,llamaindex`

No existing code is modified. No dependencies are added.

## Capabilities

### New Capabilities
- `rag-evaluation`: Offline evaluation pipeline for RAG quality metrics — retrieval accuracy (precision@k, recall@k, MRR via content-matching), answer faithfulness (via cross-encoder), latency measurement, and cross-backend comparison. Includes dataset format, metric computation, report generation, and smoke tests.

### Modified Capabilities
- *None* — no existing spec's requirements change.

## Impact

- **New code**: `src/evaluation/` (module), `tests/evaluation/` (dataset + smoke tests)
- **New data directory**: `data/eval_reports/` (report output, gitignored)
- **Entry points**:
  - `python -m src.evaluation.run` for manual/ad-hoc runs
  - `pytest tests/evaluation/` for smoke tests
  - Future CI integration via `--run-eval` marker
- **No regression risk**: evaluation module imports from but never modifies existing source; all existing tests continue unchanged
