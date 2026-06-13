"""Unit tests for the validation module.

Tests for:
- ``RequiredFieldValidator`` — COM field presence and return-keyword checks
- ``TokenDistributionAnalyzer`` — min/max/mean/percentile stats
- ``ValidationReportBuilder`` — report composition and delegation
"""

from typing import Optional


from src.pdf_semantic_chunking.validation.validator import (
    RequiredFieldValidator,
    TokenDistributionAnalyzer,
    ValidationReportBuilder,
)


# ======================================================================
# Helpers
# ======================================================================


def _chunk(
    content: str = "",
    element_type: Optional[str] = None,
    interface: Optional[str] = None,
    element_name: Optional[str] = None,
    token_count: Optional[int] = None,
) -> dict:
    """Build a minimal chunk dict for testing."""
    meta: dict = {}
    if element_type is not None:
        meta["element_type"] = element_type
    if interface is not None:
        meta["interface"] = interface
    if element_name is not None:
        meta["element_name"] = element_name
    if token_count is not None:
        meta["token_count"] = token_count
    return {"content": content, "metadata": meta}


# ======================================================================
# RequiredFieldValidator
# ======================================================================


class TestRequiredFieldValidator:
    """Tests for :class:`RequiredFieldValidator`."""

    def test_function_with_required_fields_passes(self):
        """Function with interface + element_name + 'return' keyword passes."""
        result = RequiredFieldValidator().validate([
            _chunk("HRESULT Method(); // return", element_type="function",
                   interface="IFoo", element_name="Method"),
        ])
        assert result["passed"] == 1
        assert result["warnings"] == 0

    def test_function_missing_interface(self):
        """Function without ``interface`` reports ``missing_field: interface``."""
        result = RequiredFieldValidator().validate([
            _chunk("return;", element_type="function", element_name="Method"),
        ])
        assert result["passed"] == 0
        assert result["warnings"] == 1
        assert "missing_field: interface on chunk_0" in result["warnings_detail"]

    def test_function_missing_element_name(self):
        """Function without ``element_name`` reports ``missing_field: element_name``."""
        result = RequiredFieldValidator().validate([
            _chunk("return;", element_type="function", interface="IFoo"),
        ])
        assert result["passed"] == 0
        assert result["warnings"] == 1
        assert "missing_field: element_name on chunk_0" in result["warnings_detail"]

    def test_function_missing_return_keyword(self):
        """Function with no 'return' in content reports ``missing_return``."""
        result = RequiredFieldValidator().validate([
            _chunk("HRESULT Method();", element_type="function",
                   interface="IFoo", element_name="Method"),
        ])
        assert result["passed"] == 0
        assert result["warnings"] == 1
        assert "missing_return: chunk_0 function lacks 'return' keyword" in result["warnings_detail"]

    def test_return_check_is_case_insensitive(self):
        """Function with 'Return' (uppercase R) still passes the return check."""
        result = RequiredFieldValidator().validate([
            _chunk("Return value", element_type="function",
                   interface="IFoo", element_name="Method"),
        ])
        assert result["passed"] == 1
        assert result["warnings"] == 0

    def test_property_with_required_fields_passes(self):
        """Property with interface + element_name passes (no return check)."""
        result = RequiredFieldValidator().validate([
            _chunk("Gets the value", element_type="property",
                   interface="ISomething", element_name="Value"),
        ])
        assert result["passed"] == 1
        assert result["warnings"] == 0

    def test_non_com_chunk_always_passes(self):
        """Non-COM chunks (e.g. mixed) always pass validation."""
        result = RequiredFieldValidator().validate([
            _chunk("Some free text.", element_type="mixed"),
        ])
        assert result["passed"] == 1
        assert result["warnings"] == 0

    def test_empty_chunks_list(self):
        """Empty chunk list returns valid report with all-zero counts."""
        result = RequiredFieldValidator().validate([])
        assert result["total_chunks"] == 0
        assert result["passed"] == 0
        assert result["warnings"] == 0

    def test_mixed_valid_and_invalid_chunks(self):
        """Correct pass/warning counts for a mix of valid and invalid chunks."""
        chunks = [
            _chunk("return ok", element_type="function",
                   interface="I", element_name="M"),           # valid (has return)
            _chunk("no return keyword present", element_type="function",
                   interface="I", element_name="M"),           # valid (has "return")
            _chunk("void Method(); no ret!", element_type="function",
                   interface="I", element_name="M"),           # missing return
            _chunk("text", element_type="mixed"),               # valid
        ]
        result = RequiredFieldValidator().validate(chunks)
        assert result["total_chunks"] == 4
        assert result["passed"] == 3      # chunks 0, 1, 3
        assert result["warnings"] == 1    # chunk 2 only
        assert "missing_return" in result["warnings_detail"][0]

    def test_chunk_with_multiple_issues_reports_all_warnings(self):
        """A single chunk with both missing fields and missing return gets 3 warnings."""
        result = RequiredFieldValidator().validate([
            _chunk("HRESULT Method();", element_type="function"),
        ])
        # Missing: interface, element_name, return → 3 warnings
        assert result["warnings"] == 3
        assert result["passed"] == 0


# ======================================================================
# TokenDistributionAnalyzer
# ======================================================================


class TestTokenDistributionAnalyzer:
    """Tests for :class:`TokenDistributionAnalyzer`."""

    def test_single_chunk(self):
        """Single chunk: all stats equal the single value."""
        result = TokenDistributionAnalyzer().analyze([
            _chunk(token_count=100),
        ])
        assert result["min"] == 100
        assert result["max"] == 100
        assert result["mean"] == 100.0
        assert result["p50"] == 100
        assert result["p90"] == 100
        assert result["p95"] == 100
        assert result["total"] == 100

    def test_multiple_chunks_different_sizes(self):
        """Multiple chunks produce correct min, max, mean, and total."""
        chunks = [_chunk(token_count=t) for t in [10, 20, 30, 40, 50]]
        result = TokenDistributionAnalyzer().analyze(chunks)
        assert result["min"] == 10
        assert result["max"] == 50
        assert result["mean"] == 30.0
        assert result["total"] == 150

    def test_percentile_calculations(self):
        """p50, p90, p95 computed correctly via integer-index percentile formula.

        Sorted values:  [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]   (n = 10)
          p50 = sorted[10 * 50 // 100] = sorted[5] = 6
          p90 = sorted[10 * 90 // 100] = sorted[9] = 10
          p95 = sorted[10 * 95 // 100] = sorted[9] = 10
        """
        chunks = [_chunk(token_count=i) for i in range(1, 11)]
        result = TokenDistributionAnalyzer().analyze(chunks)
        assert result["p50"] == 6
        assert result["p90"] == 10
        assert result["p95"] == 10

    def test_empty_list(self):
        """Empty chunk list returns all-zero stats."""
        result = TokenDistributionAnalyzer().analyze([])
        assert result == {"min": 0, "max": 0, "mean": 0, "p50": 0, "p90": 0, "p95": 0, "total": 0}

    def test_chunks_without_token_count_default_to_zero(self):
        """Chunks missing ``token_count`` in metadata default to 0."""
        chunks = [
            _chunk(),                      # no metadata → 0
            _chunk(element_type="function"),  # metadata present but no token_count → 0
            _chunk(token_count=50),
        ]
        result = TokenDistributionAnalyzer().analyze(chunks)
        assert result["min"] == 0
        assert result["max"] == 50
        assert result["mean"] == 50 / 3
        assert result["total"] == 50


# ======================================================================
# ValidationReportBuilder
# ======================================================================


class TestValidationReportBuilder:
    """Tests for :class:`ValidationReportBuilder`."""

    def test_delegates_to_validator_and_analyzer(self):
        """Build output includes keys from both validator result and analysis."""
        chunks = [
            _chunk("return ok", element_type="function",
                   interface="I", element_name="M"),
        ]
        result = ValidationReportBuilder().build(chunks)
        assert "total_chunks" in result
        assert "passed" in result
        assert "warnings" in result
        assert "token_distribution" in result
        assert "element_type_counts" in result

    def test_element_type_counts(self):
        """Count of each ``element_type`` present in the chunk list."""
        chunks = [
            _chunk("a", element_type="function"),
            _chunk("b", element_type="function"),
            _chunk("c", element_type="property"),
            _chunk("d", element_type="mixed"),
            _chunk("e"),                     # missing element_type → defaults to "mixed"
        ]
        result = ValidationReportBuilder().build(chunks)
        assert result["element_type_counts"]["function"] == 2
        assert result["element_type_counts"]["property"] == 1
        assert result["element_type_counts"]["mixed"] == 2  # explicit + default

    def test_token_distribution_included(self):
        """Token distribution sub-dict is present and correctly populated."""
        chunks = [
            _chunk("a", element_type="function", token_count=100),
        ]
        result = ValidationReportBuilder().build(chunks)
        td = result["token_distribution"]
        assert td["min"] == 100
        assert td["total"] == 100

    def test_empty_chunks(self):
        """Empty chunks produce a complete report with all-zero counts."""
        result = ValidationReportBuilder().build([])
        assert result["total_chunks"] == 0
        assert result["passed"] == 0
        assert result["warnings"] == 0
        assert result["element_type_counts"] == {}
        assert result["token_distribution"]["total"] == 0

    def test_validator_failures_reflected_in_report(self):
        """Invalid chunks produce non-zero warning counts in the final report."""
        chunks = [
            _chunk("returns a value", element_type="function",
                   interface="I", element_name="M"),         # valid
            _chunk("void foo()", element_type="function"),   # missing interface + element_name + return
        ]
        result = ValidationReportBuilder().build(chunks)
        assert result["total_chunks"] == 2
        assert result["passed"] == 1
        assert result["warnings"] == 3  # interface + element_name + return
