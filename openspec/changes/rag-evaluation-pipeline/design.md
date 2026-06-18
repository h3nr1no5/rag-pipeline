## Context

The RAG pipeline has 3 backends (cosine similarity at `/api/v1/query`, LangChain hybrid BM25+FAISS at `/api/v1/query/langchain`, LlamaIndex at `/api/v1/query/llamaindex`), response verification via a cross-encoder `ResponseVerifier`, and 39 tests. All integration tests use `ASGITransport(app=app)` for in-process HTTP — no server needed. Each test gets a fresh SQLite DB via the `setup_test_db` autouse fixture. Test documents live in `tests/docs/` (`sample_python.txt`, `AI short.pdf`, etc.).

Key constraint: chunk IDs are UUIDs generated at document upload time, so ground-truth data cannot reference fixed chunk IDs. The design uses **content-matching** to dynamically determine which chunks are relevant for each question.

The proposed module `src/evaluation/` is dev-only tooling, not production code. The runner is a CLI script (`python -m src.evaluation.run`) that orchestrates: dataset loading → document upload → querying each backend → metric computation → report generation.

## Goals / Non-Goals

**Goals:**
- Provide **retrieval metrics** (precision@k, recall@k, MRR) using content-matched ground truth
- Provide **answer quality metrics** (faithfulness via existing `ResponseVerifier`, keyword recall)
- Provide **performance metrics** (latency per backend, comparative)
- Support all 3 RAG backends from a single runner invocation
- Produce timestamped, diffable reports (JSON + Markdown) in `data/eval_reports/`
- Include smoke tests verifying imports, dataset loading, and metric computation
- Run entirely offline using existing test documents — no external services

**Non-Goals:**
- Not a CI gate (deferred — requires infrastructure decisions)
- Not a labeled benchmark for publication (in-house quality signal only)
- No modification to existing source code, tests, or dependencies
- No streaming endpoint evaluation (latency measurement focuses on non-streaming endpoints)
- No human evaluation / A/B testing framework

## Decisions

### 1. Content-Matching for Ground-Truth Chunk IDs

**Problem**: Chunk IDs are UUIDs generated at upload time — unpredictable and non-portable. We need a way to label "which chunks are relevant for question Q" that survives re-processing.

**Decision**: Each eval dataset entry declares `expected_sources` — text snippets that should appear in at least one retrieved chunk for the answer to be considered grounded. At evaluation time, after uploading + processing the document:
1. Query the DB for all chunks belonging to the document
2. For each expected_source snippet, find chunks whose `.content` contains the snippet (substring match)
3. Those chunk IDs become the ground-truth set for precision@k / recall@k / MRR

**Alternatives considered:**
- *Fixed chunk IDs* → rejected: would break on every re-upload
- *Embedding similarity threshold* → rejected: circular (evaluates retrieval via the same embeddings)
- *No chunk-level metrics* → rejected: retrieval quality is core to RAG, need signal

Substring matching is deliberately simple and deterministic. Expected_sources should be verbatim excerpts from the test document.

### 2. Module Structure: `src/evaluation/` as CLI + Library

```
src/evaluation/
├── __init__.py              # Module marker
├── __main__.py              # CLI entry point: python -m src.evaluation.run
├── run.py                   # Orchestrator: load dataset → run backends → compute → report
├── dataset.py               # Dataset loader + validator (loads eval_dataset.json)
├── metrics.py               # Pure functions: precision_at_k, recall_at_k, MRR, keyword_recall, faithfulness
└── report.py                # Report generation (JSON + Markdown writer)
```

**Why `src/` not `tests/`:** The runner imports from `src.domain.services` and `src.api`, which is cleaner from a sibling module. It's explicitly documented as dev-only. The `__main__.py` pattern gives a clean CLI without `if __name__`.

### 3. eval_dataset.json Format

```json
{
  "version": "1.0",
  "created": "2026-06-18",
  "description": "In-house RAG evaluation dataset",
  "documents": [
    {
      "filename": "sample_python.txt",
      "path": "tests/docs/sample_python.txt"
    }
  ],
  "questions": [
    {
      "id": "q001",
      "question": "What is Python and what are its key features?",
      "document": "sample_python.txt",
      "expected_sources": [
        "Python is a high-level, interpreted programming language",
        "Python is known for its readability and simplicity"
      ],
      "expected_keywords": ["programming language", "interpreted", "readability"],
      "min_answer_length": 30
    }
  ]
}
```

Each question references one document by filename. `expected_sources` are verbatim text that must appear in at least one chunk to qualify that chunk as relevant. `expected_keywords` are used for coarse answer-quality checking. `min_answer_length` filters out degenerate empty responses.

### 4. Metric Definitions

```
Retrieval Metrics (computed per question, then macro-averaged):

  precision@k = |{relevant_chunks} ∩ {retrieved_chunks[:k]}| / k
  recall@k    = |{relevant_chunks} ∩ {retrieved_chunks[:k]}| / |{relevant_chunks}|
  MRR         = 1 / rank_of_first_relevant_chunk (0 if none found)

  k defaults to top_k used in query (usually 4-5). Computed for each backend.

Answer Quality Metrics:

  faithfulness   = ResponseVerifier.verify().confidence  (0..1)
  keyword_recall = |{kw in answer} ∩ {expected_keywords}| / |{expected_keywords}|
  has_min_length = len(answer) >= min_answer_length  (boolean)

Performance Metrics:

  latency_ms     = total endpoint response time (per backend, per question)
```

### 5. Report Format

**JSON report** (primary — machine-readable, diffable):
```json
{
  "report": {
    "timestamp": "2026-06-18T10:30:00",
    "dataset_version": "1.0",
    "backends": ["cosine", "langchain", "llamaindex"],
    "config": {"top_k": 4, "temperature": 0.1},
    "results": {
      "q001": {
        "cosine": {
          "precision_at_4": 0.75,
          "recall_at_4": 1.0,
          "mrr": 1.0,
          "faithfulness": 0.92,
          "keyword_recall": 0.67,
          "latency_ms": 4520
        },
        "langchain": { ... },
        "llamaindex": { ... }
      }
    },
    "summary": {
      "cosine": {
        "avg_precision_at_4": 0.72,
        "avg_recall_at_4": 0.85,
        "avg_mrr": 0.90,
        "avg_faithfulness": 0.88,
        "avg_keyword_recall": 0.70,
        "avg_latency_ms": 4500
      },
      "langchain": { ... }
    }
  }
}
```

**Markdown report** (secondary — human-readable summary with tables).

Both written to `data/eval_reports/report_<YYYY-MM-DDTHH-MM-SS>.json` and `.md`.

### 6. Runner Interface

```
python -m src.evaluation.run \
  --backends cosine,langchain,llamaindex \
  --dataset tests/evaluation/eval_dataset.json \
  --top-k 4 \
  --temperature 0.1 \
  --output data/eval_reports/

Default behavior: run all backends, dataset at default location, write report.
```

The orchestrator (`run.py`):
1. Loads and validates the dataset
2. For each unique document: uploads via API, polls for completion, stores doc_id
3. For each question + each backend:
   - Calls the query endpoint
   - Extracts sources + answer + latency
   - Computes retrieval metrics via content-matching against known chunks
   - Computes faithfulness via `ResponseVerifier`
   - Computes keyword recall
4. Aggregates results, generates reports

### 7. Test Document Handling

The test document `sample_python.txt` already exists at `tests/docs/sample_python.txt` and is used by existing integration tests. The eval pipeline will upload and process it fresh on each run (the DB is ephemeral in tests, but persistent in eval runs — we use the real API).

A `data/uploads/` cleanup concern: eval runs upload the same document repeatedly. The runner should use a consistent upload (same file bytes = same chunks) and clean up after itself, or tolerate re-processing.

### 8. Faithfulness via Existing ResponseVerifier

No new cross-encoder loading. The eval uses the existing `ResponseVerifier` (which lazily loads the cross-encoder on first use). If the cross-encoder model is unavailable, faithfulness reports `null` and logs a warning — the eval continues rather than crashing.

## Risks / Trade-offs

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Content-matching is brittle: document text changes → ground truth breaks | False metric degradation | Validate on load: warn if an expected_source matches zero chunks |
| Eval run is slow (LLM + cross-encoder on Apple Silicon) | Slow dev feedback | Smoke test uses 1 doc × 2 Qs; full run is manual/CI-triggered |
| `data/eval_reports/` accumulates over time | Disk bloat | Report files are small (KB each); add an optional `--max-reports N` or doc note |
| eval_dataset.json and test documents drift apart | Misleading metrics | Document a process: update dataset whenever test docs change significantly |
| Faithfulness requires ~500MB cross-encoder model | First-run setup cost | Already required by existing `ResponseVerifier` — no new model cost |
| Uploading same document on every eval run is wasteful | Slower runs | Acceptable for manual runs; future optimization: skip-upload if content hash matches |
