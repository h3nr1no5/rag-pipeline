## ADDED Requirements

### Requirement: RAG Evaluation Pipeline

The system SHALL provide an offline evaluation pipeline that measures RAG quality across all 3 backends (cosine, LangChain hybrid, LlamaIndex) using a labeled dataset with content-matched ground truth.

#### Scenario: Evaluate all backends
- **WHEN** the user runs `python -m src.evaluation.run` with default arguments
- **THEN** the pipeline SHALL load `tests/evaluation/eval_dataset.json`, upload referenced documents, run each question against each backend, compute all metrics, and write reports to `data/eval_reports/`

#### Scenario: Evaluate specific backends
- **WHEN** the user runs with `--backends cosine,langchain`
- **THEN** the pipeline SHALL only test the specified backends

#### Scenario: Graceful failure on missing cross-encoder
- **WHEN** the cross-encoder model is not available
- **THEN** the faithfulness metric SHALL be reported as `null` (not crash) and a warning SHALL be logged

---

### Requirement: Evaluator Dataset Format

The system SHALL define a JSON dataset format with versioning, document references, and per-question labels including expected source text snippets, expected keywords, and minimum answer length.

#### Scenario: Dataset loads successfully
- **WHEN** the dataset JSON is valid and all referenced document files exist
- **THEN** the loader SHALL return a validated `EvalDataset` object with `questions`, `documents`, and `version` attributes

#### Scenario: Dataset validation warns on missing snippets
- **WHEN** a question's `expected_sources` text snippet does not appear in any chunk of the referenced document
- **THEN** the loader SHALL emit a warning but continue loading

#### Scenario: Dataset validation fails on missing document file
- **WHEN** a referenced document file path does not exist on disk
- **THEN** the loader SHALL raise a `FileNotFoundError`

---

### Requirement: Retrieval Metrics via Content-Matching

The system SHALL compute precision@k, recall@k, and MRR using dynamically determined ground-truth chunk IDs via content substring matching against `expected_sources`.

#### Scenario: Content matching identifies relevant chunks
- **WHEN** the pipeline queries the DB for all chunks of a document and searches each chunk's `.content` for an `expected_source` substring
- **THEN** any chunk whose content contains the `expected_source` SHALL be added to the ground-truth relevant set for that question

#### Scenario: Precision@k computed correctly
- **WHEN** a question has 2 relevant chunks out of 5 retrieved and k=4
- **THEN** precision@4 SHALL be `|relevant ∩ retrieved[:4]| / 4`

#### Scenario: Recall@k computed correctly
- **WHEN** a question has 3 relevant total chunks and 2 appear in the top 4 retrieved
- **THEN** recall@4 SHALL be `2 / 3`

#### Scenario: MRR computed correctly
- **WHEN** the first relevant chunk appears at rank 2
- **THEN** MRR SHALL be `1/2`
- **WHEN** no relevant chunk is retrieved
- **THEN** MRR SHALL be `0.0`

---

### Requirement: Answer Quality Metrics

The system SHALL compute faithfulness (via existing `ResponseVerifier`) and keyword recall for each generated answer.

#### Scenario: Faithfulness uses ResponseVerifier
- **WHEN** computing faithfulness for a (question, answer, sources) triple
- **THEN** the pipeline SHALL instantiate `ResponseVerifier`, call `verify(answer, sources)`, and record the `.confidence` value
- **WHEN** `ResponseVerifier` raises an exception (e.g., model not loaded)
- **THEN** the faithfulness score SHALL be recorded as `null` and the error SHALL be logged

#### Scenario: Keyword recall computed
- **WHEN** a question has expected_keywords `["programming language", "interpreted", "readability"]` and the answer contains "programming language" and "interpreted" but not "readability"
- **THEN** keyword_recall SHALL be `2/3`

---

### Requirement: Performance Metrics

The system SHALL record latency per (question, backend) combination and report summary statistics.

#### Scenario: Latency recorded per query
- **WHEN** the pipeline calls a query endpoint
- **THEN** it SHALL record the `latency_ms` value from the response and associate it with the question + backend

#### Scenario: Summary statistics computed
- **WHEN** all questions have been evaluated for a given backend
- **THEN** the report SHALL include `avg_latency_ms`, `min_latency_ms`, and `max_latency_ms` for that backend

---

### Requirement: Report Generation

The system SHALL generate timestamped reports in JSON and Markdown format, saved to `data/eval_reports/`.

#### Scenario: JSON report written
- **WHEN** the pipeline completes evaluation
- **THEN** a JSON report SHALL be written to `data/eval_reports/report_<ISO_TIMESTAMP>.json` containing per-question results and per-backend summary statistics

#### Scenario: Markdown report written
- **WHEN** the pipeline completes evaluation
- **THEN** a Markdown report SHALL be written to `data/eval_reports/report_<ISO_TIMESTAMP>.md` with tables for per-backend metrics

#### Scenario: Reports are timestamped
- **WHEN** two evaluations run at different times
- **THEN** their report filenames SHALL differ by timestamp

---

### Requirement: Smoke Tests

The system SHALL include pytest smoke tests that verify the evaluation module imports, dataset loads, and metrics compute without error.

#### Scenario: Smoke test imports
- **WHEN** `pytest tests/evaluation/test_eval_rag.py` is run
- **THEN** the evaluation module SHALL import without errors

#### Scenario: Smoke test dataset loads
- **WHEN** the smoke test loads `eval_dataset.json`
- **THEN** it SHALL verify the version field is present and at least one question is defined

#### Scenario: Smoke test metrics compute
- **WHEN** the smoke test calls each metric function with synthetic data
- **THEN** it SHALL verify the output type and range for each metric
