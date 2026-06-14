import pytest
from src.domain.services.progress import compute_stage_progress


class TestComputeStageProgress:
    """Unit tests for compute_stage_progress()."""

    @pytest.mark.parametrize(
        "processing_step, saved_chunks, chunk_count, expected",
        [
            # ── Normal stage transitions ──────────────────────────────
            pytest.param(
                None,
                0,
                0,
                {"parsing": 0, "chunking": 0, "saving": 0},
                id="pending_no_step",
            ),
            pytest.param(
                "parsing",
                0,
                0,
                {"parsing": 0, "chunking": 0, "saving": 0},
                id="parsing_step",
            ),
            pytest.param(
                "chunking",
                0,
                0,
                {"parsing": 100, "chunking": 0, "saving": 0},
                id="chunking_step",
            ),
            pytest.param(
                "saving",
                0,
                10,
                {"parsing": 100, "chunking": 100, "saving": 0},
                id="saving_step_no_chunks_saved",
            ),
            pytest.param(
                "saving",
                5,
                10,
                {"parsing": 100, "chunking": 100, "saving": 50},
                id="saving_step_partial",
            ),
            pytest.param(
                "saving",
                10,
                10,
                {"parsing": 100, "chunking": 100, "saving": 100},
                id="saving_step_complete",
            ),
            pytest.param(
                "completed",
                10,
                10,
                {"parsing": 100, "chunking": 100, "saving": 100},
                id="completed_step",
            ),
            # ── Non-standard / unknown steps ─────────────────────────
            pytest.param(
                "failed",
                0,
                0,
                {"parsing": 0, "chunking": 0, "saving": 0},
                id="failed_step",
            ),
            pytest.param(
                "unknown",
                0,
                0,
                {"parsing": 0, "chunking": 0, "saving": 0},
                id="unknown_step",
            ),
            pytest.param(
                "",
                0,
                0,
                {"parsing": 0, "chunking": 0, "saving": 0},
                id="empty_string_step",
            ),
            # ── Edge cases ───────────────────────────────────────────
            pytest.param(
                "saving",
                0,
                0,
                {"parsing": 100, "chunking": 100, "saving": 0},
                id="saving_zero_chunk_count_no_division_by_zero",
            ),
            pytest.param(
                "saving",
                20,
                10,
                {"parsing": 100, "chunking": 100, "saving": 100},
                id="saving_capped_at_100",
            ),
            pytest.param(
                "completed",
                0,
                0,
                {"parsing": 100, "chunking": 100, "saving": 100},
                id="completed_zero_chunks",
            ),
        ],
    )
    def test_compute_stage_progress(
        self,
        processing_step: str | None,
        saved_chunks: int,
        chunk_count: int,
        expected: dict[str, int],
    ) -> None:
        result = compute_stage_progress(processing_step, saved_chunks, chunk_count)
        assert result == expected

        # Verify all values are plain ints (not floats, not strings)
        for key, value in result.items():
            assert isinstance(value, int), f"{key} should be int, got {type(value)}"
