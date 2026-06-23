"""Table type detection and multi-row function merging for API DOCX tables."""

from src.domain.rag.api_docs.extraction.docx_parser import RawTable

# ---------------------------------------------------------------------------
# Keyword sets used for table-type classification
# ---------------------------------------------------------------------------

_METHOD_KEYWORDS = {"method", "function", "procedure"}
_PARAMETER_KEYWORDS = {"parameter", "param", "argument", "arg", "parameters"}
_RETURN_KEYWORDS = {"return", "returns", "retval", "ret value"}
_DESCRIPTION_KEYWORDS = {"description", "desc", "remarks", "summary", "comment"}
_NAME_KEYWORDS = {"name", "property", "member", "identifier"}
_TYPE_KEYWORDS = {"type", "type_annotation", "data type", "datatype"}
_ACCESS_KEYWORDS = {"access", "access modifier", "accessor"}
_VALUE_KEYWORDS = {"value", "constant", "enum value", "values"}
_CODE_KEYWORDS = {"code", "error code", "error_code", "error", "errorcode",
                  "hr", "hresult"}


# ---------------------------------------------------------------------------
# Header normalisation helpers
# ---------------------------------------------------------------------------


def _normalise(headers: list[str]) -> list[str]:
    """Return lower-cased, stripped versions of each header."""
    return [h.lower().strip() for h in headers]


def _match_any(headers: list[str], keywords: set[str]) -> bool:
    """Return ``True`` if *any* header contains one of the *keywords*."""
    normalised = _normalise(headers)
    for h in normalised:
        for kw in keywords:
            if kw in h:
                return True
    return False


def _match_all(headers: list[str], keyword_sets: list[set[str]]) -> bool:
    """Return ``True`` if *every* keyword set matches at least one header."""
    return all(_match_any(headers, ks) for ks in keyword_sets)


# ---------------------------------------------------------------------------
# TableDetector
# ---------------------------------------------------------------------------


class TableDetector:
    """Detects the type of a table by examining its column headers.

    Classification is case-insensitive and uses fuzzy substring matching
    so that small variations in column naming (e.g. "Return Value" vs
    "Returns") are handled gracefully.
    """

    @staticmethod
    def detect(table: RawTable) -> str:
        """Return the detected table type.

        Returns one of ``"method"``, ``"property"``, ``"enum"``,
        ``"error_code"``, ``"unknown"``.
        """
        headers = table.headers
        if not headers:
            return "unknown"

        # ― Method table: must have method/function + parameter + return + desc
        if _match_all(headers, [
            _METHOD_KEYWORDS,
            _PARAMETER_KEYWORDS,
            _RETURN_KEYWORDS,
            _DESCRIPTION_KEYWORDS,
        ]):
            return "method"

        # ― Property table: must have name + type + access + description
        if _match_all(headers, [
            _NAME_KEYWORDS,
            _TYPE_KEYWORDS,
            _ACCESS_KEYWORDS,
            _DESCRIPTION_KEYWORDS,
        ]):
            return "property"

        # ― Enum table: must have value + description (name is optional)
        if _match_all(headers, [
            _VALUE_KEYWORDS,
            _DESCRIPTION_KEYWORDS,
        ]):
            return "enum"

        # ― Error code table: must have code + description
        if _match_all(headers, [
            _CODE_KEYWORDS,
            _DESCRIPTION_KEYWORDS,
        ]):
            return "error_code"

        return "unknown"


# ---------------------------------------------------------------------------
# Multi-row function merging
# ---------------------------------------------------------------------------


def merge_multi_row_functions(tables: list[RawTable]) -> list[RawTable]:
    """Merge functions that span multiple rows in a single table.

    Some API documentation formats a single function across *N* rows:

    * **Row 1** — function name, return type, description (first cell filled)
    * **Row 2** — empty first cell, parameter name + type (continuation)
    * **Row N** — further parameter rows, each with an empty first cell

    This function collapses those continuation rows into the parent row so
    that every output row represents exactly one logical function.  Parameters
    from continuation rows are appended to the function's parameter column,
    separated by ``\\n``.

    The output list has the same length as the input list (every input table
    produces exactly one output table).
    """
    return [_merge_table_rows(t) for t in tables]


def _merge_table_rows(table: RawTable) -> RawTable:
    """Merge continuation rows inside a single table."""
    if not table.rows or len(table.rows) < 2:
        return RawTable(headers=table.headers, rows=list(table.rows),
                        caption=table.caption)

    # Fast check: does this table even have continuation rows?
    has_continuation = any(not row[0].strip() for row in table.rows[1:])
    if not has_continuation:
        return RawTable(headers=table.headers, rows=list(table.rows),
                        caption=table.caption)

    merged: list[list[str]] = []
    current: list[str] | None = None

    for row in table.rows:
        if row[0].strip():
            # Start of a new logical row
            if current is not None:
                merged.append(current)
            current = list(row)
        else:
            # Continuation of the previous logical row
            if current is not None:
                for i, cell in enumerate(row):
                    if cell.strip() and i < len(current):
                        if current[i]:
                            current[i] += "\n" + cell.strip()
                        else:
                            current[i] = cell.strip()

    if current is not None:
        merged.append(current)

    return RawTable(headers=table.headers, rows=merged, caption=table.caption)
