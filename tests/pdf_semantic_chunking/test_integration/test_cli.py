"""Integration tests for the PDF semantic chunking CLI.

Tests exercise the command-line entry point (``__main__.py``) via
subprocess, covering JSONL / JSON output formats, custom chunking
parameters, and error handling for corrupt or missing files.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
FIXTURES_DIR = PROJECT_ROOT / "tests" / "pdf_semantic_chunking" / "fixtures"


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    """Run ``python -m src.pdf_semantic_chunking`` with *args*.

    Uses ``sys.executable`` (the same interpreter running the test suite)
    to avoid ``uv run`` overhead while exercising the exact same code path.
    """
    cmd = [sys.executable, "-m", "src.pdf_semantic_chunking", *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(PROJECT_ROOT),
    )


# ======================================================================
#  Tests — JSONL output  (*default* format)
# ======================================================================


class TestCliJsonlOutput:
    """CLI produces valid JSONL output on ``structured.pdf``."""

    FIXTURE = str(FIXTURES_DIR / "structured.pdf")

    def test_exit_code_zero(self):
        """Exit code is 0 on success."""
        result = _run_cli(self.FIXTURE, "--format", "jsonl")
        assert result.returncode == 0, (
            f"CLI exited with code {result.returncode}.\n"
            f"stderr:\n{result.stderr}"
        )

    def test_stdout_has_jsonl_lines(self):
        """stdout contains one JSON object per line."""
        result = _run_cli(self.FIXTURE, "--format", "jsonl")

        lines = result.stdout.strip().split("\n")
        assert len(lines) > 0, "Expected at least one JSONL line in stdout"

        for i, line in enumerate(lines):
            obj = json.loads(line)
            assert isinstance(obj, dict), (
                f"Line {i} is not a JSON object: {line!r}"
            )

    def test_each_line_has_expected_keys(self):
        """Every JSONL line has ``content``, ``metadata``, ``chunk_index``."""
        result = _run_cli(self.FIXTURE, "--format", "jsonl")

        for i, line in enumerate(result.stdout.strip().split("\n")):
            obj = json.loads(line)
            assert "content" in obj, f"Line {i} is missing 'content'"
            assert "metadata" in obj, f"Line {i} is missing 'metadata'"
            assert "chunk_index" in obj, f"Line {i} is missing 'chunk_index'"
            assert isinstance(obj["chunk_index"], int), (
                f"Line {i} chunk_index is not int: {obj['chunk_index']!r}"
            )

    def test_stderr_contains_summary(self):
        """stderr carries a human-readable processing summary."""
        result = _run_cli(self.FIXTURE, "--format", "jsonl")

        assert "Processed" in result.stderr, (
            f"Expected 'Processed' in stderr summary.\n"
            f"stderr:\n{result.stderr}"
        )
        assert "chunks" in result.stderr, (
            f"Expected 'chunks' in stderr summary.\n"
            f"stderr:\n{result.stderr}"
        )

    def test_chunk_content_is_nonempty(self):
        """Every chunk's content field is a non-empty string."""
        result = _run_cli(self.FIXTURE, "--format", "jsonl")

        for i, line in enumerate(result.stdout.strip().split("\n")):
            obj = json.loads(line)
            content = obj["content"]
            assert isinstance(content, str) and len(content) > 0, (
                f"Line {i} has empty or non-string content"
            )


# ======================================================================
#  Tests — JSON output
# ======================================================================


class TestCliJsonOutput:
    """CLI produces valid JSON output on ``unstructured.pdf``."""

    FIXTURE = str(FIXTURES_DIR / "unstructured.pdf")

    def test_exit_code_zero(self):
        """Exit code is 0 on success."""
        result = _run_cli(self.FIXTURE, "--format", "json")
        assert result.returncode == 0, (
            f"CLI exited with code {result.returncode}.\n"
            f"stderr:\n{result.stderr}"
        )

    def test_stdout_is_valid_json(self):
        """stdout is parseable as a JSON object."""
        result = _run_cli(self.FIXTURE, "--format", "json")
        data = json.loads(result.stdout)
        assert isinstance(data, dict)

    def test_has_chunks_and_stats_keys(self):
        """The top-level JSON object has ``chunks`` and ``stats`` keys."""
        result = _run_cli(self.FIXTURE, "--format", "json")
        data = json.loads(result.stdout)
        assert "chunks" in data, "Missing top-level 'chunks' key"
        assert "stats" in data, "Missing top-level 'stats' key"

    def test_stats_has_expected_fields(self):
        """The ``stats`` object contains ``chunk_count``, ``total_tokens``,
        and ``elapsed_seconds``."""
        result = _run_cli(self.FIXTURE, "--format", "json")
        data = json.loads(result.stdout)
        stats = data["stats"]

        assert "chunk_count" in stats, "Missing 'chunk_count' in stats"
        assert "total_tokens" in stats, "Missing 'total_tokens' in stats"
        assert "elapsed_seconds" in stats, "Missing 'elapsed_seconds' in stats"

    def test_stats_fields_have_correct_types(self):
        """Stats fields have the expected numeric types."""
        result = _run_cli(self.FIXTURE, "--format", "json")
        data = json.loads(result.stdout)
        stats = data["stats"]

        assert isinstance(stats["chunk_count"], int), (
            f"chunk_count should be int, got {type(stats['chunk_count'])}"
        )
        assert isinstance(stats["total_tokens"], int), (
            f"total_tokens should be int, got {type(stats['total_tokens'])}"
        )
        assert isinstance(stats["elapsed_seconds"], (int, float)), (
            f"elapsed_seconds should be numeric, "
            f"got {type(stats['elapsed_seconds'])}"
        )
        assert stats["chunk_count"] >= 1, (
            f"Expected at least 1 chunk, got {stats['chunk_count']}"
        )

    def test_chunk_objects_have_required_keys(self):
        """Every chunk in the JSON output has the required keys."""
        result = _run_cli(self.FIXTURE, "--format", "json")
        data = json.loads(result.stdout)

        for i, chunk in enumerate(data["chunks"]):
            assert "content" in chunk, f"Chunk {i} missing 'content'"
            assert "metadata" in chunk, f"Chunk {i} missing 'metadata'"
            assert "chunk_index" in chunk, f"Chunk {i} missing 'chunk_index'"

    def test_stats_includes_element_types(self):
        """The stats object includes an ``element_types`` breakdown."""
        result = _run_cli(self.FIXTURE, "--format", "json")
        data = json.loads(result.stdout)
        assert "element_types" in data["stats"], (
            "Missing 'element_types' in stats"
        )
        assert isinstance(data["stats"]["element_types"], dict)


# ======================================================================
#  Tests — custom chunking parameters
# ======================================================================


class TestCliCustomParams:
    """CLI accepts custom ``--min-chunk-size``, ``--max-chunk-size``,
    and ``--overlap``."""

    FIXTURE = str(FIXTURES_DIR / "com_sample.pdf")

    def test_exit_code_zero(self):
        """Custom parameters do not prevent successful completion."""
        result = _run_cli(
            self.FIXTURE,
            "--min-chunk-size", "100",
            "--max-chunk-size", "500",
            "--overlap", "15",
        )
        assert result.returncode == 0, (
            f"CLI exited with code {result.returncode}.\n"
            f"stderr:\n{result.stderr}"
        )

    def test_output_is_valid_jsonl(self):
        """Output with custom params is still valid JSONL."""
        result = _run_cli(
            self.FIXTURE,
            "--min-chunk-size", "100",
            "--max-chunk-size", "500",
            "--overlap", "15",
        )
        lines = result.stdout.strip().split("\n")
        assert len(lines) > 0, "Expected at least one JSONL line"
        for i, line in enumerate(lines):
            obj = json.loads(line)
            assert isinstance(obj, dict), f"Line {i} is not valid JSON"

    def test_each_line_has_required_keys(self):
        """JSONL lines still have the contract keys with custom params."""
        result = _run_cli(
            self.FIXTURE,
            "--min-chunk-size", "100",
            "--max-chunk-size", "500",
            "--overlap", "15",
        )
        for i, line in enumerate(result.stdout.strip().split("\n")):
            obj = json.loads(line)
            assert "content" in obj, f"Line {i} missing 'content'"
            assert "metadata" in obj, f"Line {i} missing 'metadata'"
            assert "chunk_index" in obj, f"Line {i} missing 'chunk_index'"

    def test_stderr_shows_summary(self):
        """Processing summary still printed to stderr."""
        result = _run_cli(
            self.FIXTURE,
            "--min-chunk-size", "100",
            "--max-chunk-size", "500",
            "--overlap", "15",
        )
        assert "Processed" in result.stderr, (
            f"Expected 'Processed' in stderr.\n"
            f"stderr:\n{result.stderr}"
        )


# ======================================================================
#  Tests — error handling: corrupt PDF
# ======================================================================


class TestCliErrorCorruptPdf:
    """CLI reports errors gracefully for corrupt / invalid PDF files."""

    def test_exit_code_nonzero(self, tmp_path: Path):
        """A corrupt PDF causes a non-zero exit code."""
        corrupt_file = tmp_path / "corrupt.pdf"
        corrupt_file.write_text("This is not a valid PDF file content.")

        result = _run_cli(str(corrupt_file))
        assert result.returncode != 0, (
            f"Expected non-zero exit code for corrupt PDF, "
            f"got {result.returncode}"
        )

    def test_stderr_contains_json_error(self, tmp_path: Path):
        """Error information is emitted as JSON on stderr.

        NOTE: stderr may contain log lines (WARNING / ERROR) before the
        final JSON error report. We extract the last ``{...}`` block.
        """
        corrupt_file = tmp_path / "corrupt.pdf"
        corrupt_file.write_text("Not a valid PDF.")

        result = _run_cli(str(corrupt_file))

        # Find the last line that looks like a JSON object
        stderr_lines = result.stderr.strip().split("\n")
        json_line = None
        for line in reversed(stderr_lines):
            if line.strip().startswith("{"):
                json_line = line.strip()
                break

        assert json_line is not None, (
            f"No JSON error report found in stderr.\n"
            f"stderr:\n{result.stderr}"
        )

        error_report = json.loads(json_line)
        assert "error" in error_report, (
            f"Missing 'error' key in error report.\n"
            f"Got keys: {list(error_report)}"
        )
        # The error report should also carry a stage identifier
        assert "stage" in error_report, (
            "Missing 'stage' key in error report."
        )

    def test_stdout_empty_on_error(self, tmp_path: Path):
        """On error, stdout contains no chunk data."""
        corrupt_file = tmp_path / "corrupt.pdf"
        corrupt_file.write_text("invalid content")

        result = _run_cli(str(corrupt_file))
        assert result.stdout.strip() == "", (
            f"Expected empty stdout on error, got:\n{result.stdout}"
        )


# ======================================================================
#  Tests — error handling: non-existent file
# ======================================================================


class TestCliErrorNonexistentFile:
    """CLI reports errors gracefully when the input file does not exist."""

    NONEXISTENT = "/nonexistent/path/to/file.pdf"

    def test_exit_code_nonzero(self):
        """A non-existent file causes a non-zero exit code."""
        result = _run_cli(self.NONEXISTENT)
        assert result.returncode != 0, (
            f"Expected non-zero exit code for missing file, "
            f"got {result.returncode}"
        )

    def test_stderr_contains_error_report(self):
        """Error information is reported on stderr.

        NOTE: stderr may contain log lines before the final JSON report.
        """
        result = _run_cli(self.NONEXISTENT)

        # Find the last JSON-object line in stderr
        stderr_lines = result.stderr.strip().split("\n")
        json_line = None
        for line in reversed(stderr_lines):
            if line.strip().startswith("{"):
                json_line = line.strip()
                break

        assert json_line is not None, (
            f"No JSON error report found in stderr.\n"
            f"stderr:\n{result.stderr}"
        )

        error_report = json.loads(json_line)
        assert "error" in error_report, (
            f"Missing 'error' key: {error_report}"
        )
        # The snapshot should reference the input path
        snapshot = error_report.get("context_snapshot", {})
        assert "file_path" in snapshot, (
            f"Missing file_path in context_snapshot: {snapshot}"
        )

    def test_stdout_empty_on_error(self):
        """On error, stdout contains no chunk data."""
        result = _run_cli(self.NONEXISTENT)
        assert result.stdout.strip() == "", (
            f"Expected empty stdout on error, got:\n{result.stdout}"
        )
