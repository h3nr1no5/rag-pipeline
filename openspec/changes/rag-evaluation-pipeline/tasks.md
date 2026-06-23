## 1. Module Scaffolding

- [x] 1.1 Create `src/evaluation/__init__.py` — module marker
- [x] 1.2 Create `src/evaluation/__main__.py` — entry point that delegates to `run.main()`
- [x] 1.3 Create `src/evaluation/dataset.py` — `EvalDataset` dataclass + json loader with validation (version check, file existence, expected_sources match)
- [x] 1.4 Create `src/evaluation/metrics.py` — pure functions: `precision_at_k`, `recall_at_k`, `mrr`, `keyword_recall`, `faithfulness` (wraps `ResponseVerifier")
- [x] 1.5 Create `src/evaluation/report.py` — JSON writer + Markdown table writer to `data/eval_reports/report_<timestamp>.{json,md}`
- [x] 1.6 Create `src/evaluation/run.py` — orchestrator: arg parse → dataset load → document upload → query loop → metric compute → report write

## 2. Dataset

- [x] 2.1 Create `tests/evaluation/eval_dataset.json` with 5-6 questions against `sample_python.txt`, including expected_sources (verbatim from document), expected_keywords, and min_answer_length

## 3. Output Directory & Config

- [x] 3.1 Create `data/eval_reports/` directory with a `.gitkeep`
- [x] 3.2 Add `data/eval_reports/` to `.gitignore`

## 4. Smoke Tests

- [x] 4.1 Create `tests/evaluation/__init__.py` — module marker
- [x] 4.2 Create `tests/evaluation/test_eval_rag.py` — 3 tests: module imports, dataset loads, metrics compute with synthetic data

## 5. Verification

- [x] 5.1 Run `uv run pytest tests/evaluation/test_eval_rag.py -v` — all smoke tests pass
- [ ] 5.2 Run `python -m src.evaluation.run --backends cosine --dataset tests/evaluation/eval_dataset.json` — end-to-end with one backend produces a valid report
- [ ] 5.3 Verify the JSON report contains per-question results and per-backend summary
- [x] 5.4 Run `uv run pytest tests/unit/ tests/integration/ -v` — existing tests not broken
- [x] 5.5 Run `uv run ruff check src/evaluation/ tests/evaluation/` — no lint errors
