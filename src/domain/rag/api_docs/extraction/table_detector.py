"""Table type detection and multi-row function merging for API DOCX tables."""

import re

from src.domain.rag.api_docs.extraction.docx_parser import (
    RawDocument,
    RawParagraph,
    RawTable,
)

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
# COM-signal helpers (used when standard header keywords don't match)
# ---------------------------------------------------------------------------

# C++ / COM return types commonly found in column 0 of method tables.
_RETURN_TYPES_RE = re.compile(
    r"^(void|long|unsigned long|double|float|int|bool|BSTR|"
    r"SAFEARRAY|HRESULT|VARIANT|BOOL|DWORD|UINT|LONG|"
    r"[A-Z][A-Za-z]*\*)$"
)

# Regex to detect value assignments like ``name = value``
_VALUE_ASSIGN_RE = re.compile(r"\w+\s*=\s*")

# Regex to detect negative integer values in assignments (supports en-dash U+2013)
_NEGATIVE_VALUE_RE = re.compile(r"=\s*[\-\u2013]\d")

# Regex to detect COM parameter annotations: ([in] or ([out]
_IN_OUT_PARAM_RE = re.compile(r"\(\[(in|out)\]", re.IGNORECASE)


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
# Multi-signal analysis helpers (COM-style tables)
# ---------------------------------------------------------------------------


def _any_cell_contains(cells: list[str], substring: str) -> bool:
    """Return ``True`` if *substring* appears in any cell (case-insensitive)."""
    lower = substring.lower()
    return any(lower in c.lower() for c in cells)


def _all_cells(headers: list[str], rows: list[list[str]]) -> list[str]:
    """Return a flat list of every cell (headers + all data rows)."""
    result = list(headers)
    for row in rows:
        result.extend(row)
    return result


def _is_record_pattern(headers: list[str], rows: list[list[str]]) -> bool:
    """Detect a COM record/struct definition table.

    Signals:
    - First header cell is empty.
    - Second header cell contains ``= (`` (e.g. ``RName = (``).
    """
    if len(headers) < 2:
        return False
    if headers[0].strip():
        return False
    return "= (" in headers[1] or headers[1].strip().endswith("=(")


def _is_com_method_pattern(headers: list[str], rows: list[list[str]]) -> bool:
    """Detect a COM method/function table.

    Signals (any one is sufficient):
    - ``([in]`` or ``([out]`` appears in any cell (COM parameter annotation).
    - First header cell looks like a C++ return type (e.g. ``long``, ``void``).
    """
    all_cells = _all_cells(headers, rows)
    for cell in all_cells:
        if _IN_OUT_PARAM_RE.search(cell):
            return True
    if headers and _RETURN_TYPES_RE.match(headers[0].strip()):
        return True
    return False


def _is_com_property_pattern(headers: list[str], rows: list[list[str]]) -> bool:
    """Detect a COM property table.

    Signals (headers only for most, all cells for ``get or set``):
    - A header cell contains the word ``property``.
    - A header cell contains ``Access to``.
    - A header cell contains the ``•`` bullet separator.
    - Any cell contains ``Get or set`` (specific enough to be reliable).
    """
    # These signals are checked only in headers to avoid false positives
    # from natural-language text in data rows.
    for h in headers:
        hl = h.lower()
        if "property" in hl:
            return True
        if "access to" in hl:
            return True
        if "\u2022" in h:
            return True
    # "Get or set" is very specific — safe to check all cells
    all_cells = _all_cells(headers, rows)
    if _any_cell_contains(all_cells, "get or set"):
        return True
    return False


def _is_enum_headers(headers: list[str]) -> bool:
    """Return ``True`` if the first header cell is ``enum``."""
    return bool(headers) and headers[0].strip().lower() == "enum"


def _has_value_assignments(rows: list[list[str]]) -> bool:
    """Return ``True`` if any data-row cell contains ``name = value``."""
    for row in rows:
        for cell in row:
            if _VALUE_ASSIGN_RE.search(cell):
                return True
    return False


def _has_negative_values(rows: list[list[str]]) -> bool:
    """Return ``True`` if any data-row cell contains a negative number."""
    for row in rows:
        for cell in row:
            if _NEGATIVE_VALUE_RE.search(cell):
                return True
    return False


# ---------------------------------------------------------------------------
# Table label mapping for paragraph-based detection
# ---------------------------------------------------------------------------

TABLE_LABELS: dict[str, str] = {
    "functions": "method",
    "properties": "property",
    "enumerated types": "enum",
    "error codes": "error_code",
    "records / structures": "record",
}

# ---------------------------------------------------------------------------
# TableDetector
# ---------------------------------------------------------------------------


class TableDetector:
    """Detects the type of a table by examining its headers, data rows,
    and cell content patterns.

    Two-tier classification:

    1. **Keyword matching** (existing) — matches standard semantic headers
       (e.g. ``Method | Parameters | Return Type | Description``).

    2. **Multi-signal analysis** (fallback) — uses structural and content
       signals to classify COM-style documentation tables that lack
       conventional column labels.
    """

    def detect_from_document(
        self, raw_document: RawDocument
    ) -> dict[int, str]:
        """Detect the type of every table in a *raw_document*.

        Uses three-tier detection in priority order:
        1. **Paragraph match** — nearest preceding bold paragraph
           (via :meth:`_detect_by_paragraph`).
        2. **Inheritance** — if the preceding DOCX body element was also
           a table, inherit its type.
        3. **Keyword / multi-signal fallback** — existing
           :meth:`detect` logic.

        Returns a ``dict`` mapping ``table_index → type`` for every table
        in the document.
        """
        # Build a unified, position-sorted view of all body elements
        elements: list[tuple[int, str, int]] = []
        for i, p in enumerate(raw_document.paragraphs):
            elements.append((p.position, "paragraph", i))
        for i, t in enumerate(raw_document.tables):
            elements.append((t.position, "table", i))
        elements.sort(key=lambda x: x[0])

        result: dict[int, str] = {}
        last_table_type: str | None = None
        last_was_table = False

        for _pos, kind, index in elements:
            if kind != "table":
                last_was_table = False
                last_table_type = None
                continue

            table = raw_document.tables[index]
            table_type: str | None = None

            # Tier 1: paragraph-based detection
            table_type = self._detect_by_paragraph(
                table.position, raw_document.paragraphs
            )

            # Tier 2: consecutive-table inheritance
            if table_type is None and last_was_table:
                table_type = last_table_type

            # Tier 3: keyword / multi-signal fallback
            if table_type is None:
                table_type = self.detect(table)

            final_type = table_type or "unknown"
            result[index] = final_type
            last_table_type = final_type
            last_was_table = True

        return result

    @staticmethod
    def detect(table: RawTable) -> str:
        """Return the detected table type.

        Returns one of ``"method"``, ``"property"``, ``"enum"``,
        ``"error_code"``, ``"record"``, ``"unknown"``.
        """
        headers = table.headers
        rows = table.rows
        if not headers:
            return "unknown"

        # ― Tier 1: Standard header keyword matching (existing logic) ---
        result = TableDetector._keyword_match(headers)
        if result != "unknown":
            return result

        # ― Tier 2: Multi-signal analysis for COM-style tables ---
        return TableDetector._multi_signal_classify(headers, rows)

    # ------------------------------------------------------------------
    # Tier 1a — paragraph-based detection (primary path)
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_by_paragraph(
        current_table_position: int,
        paragraphs: list[RawParagraph],
    ) -> str | None:
        """Walk backwards from *current_table_position* through
        *paragraphs* to find the nearest preceding bold paragraph.

        If the nearest bold paragraph's text matches one of the known
        :data:`TABLE_LABELS` after whitespace normalisation, return the
        mapped type string.  Otherwise return ``None``.

        The match is **exact** (not substring/contains) after
        lowercasing and normalising whitespace, preventing false
        positives from label-like text in other contexts.
        """
        # Collect paragraphs that appear before the table position
        preceding = [
            p for p in paragraphs if p.position < current_table_position
        ]

        # Walk backwards through positions to find the NEAREST bold paragraph
        for p in reversed(preceding):
            if not p.bold:
                continue
            # Whitespace normalisation: strip outer + collapse internal
            normalized = " ".join(p.text.split()).lower()
            return TABLE_LABELS.get(normalized)

        return None

    # ------------------------------------------------------------------
    # Tier 1b — keyword matching (fallback)
    # ------------------------------------------------------------------

    @staticmethod
    def _keyword_match(headers: list[str]) -> str:
        """Try keyword-based classification; return ``"unknown"`` if no match."""
        # Method table: must have method/function + parameter + return + desc
        if _match_all(headers, [
            _METHOD_KEYWORDS,
            _PARAMETER_KEYWORDS,
            _RETURN_KEYWORDS,
            _DESCRIPTION_KEYWORDS,
        ]):
            return "method"

        # Property table: must have name + type + access + description
        if _match_all(headers, [
            _NAME_KEYWORDS,
            _TYPE_KEYWORDS,
            _ACCESS_KEYWORDS,
            _DESCRIPTION_KEYWORDS,
        ]):
            return "property"

        # Enum table: must have value + description (name is optional)
        if _match_all(headers, [
            _VALUE_KEYWORDS,
            _DESCRIPTION_KEYWORDS,
        ]):
            return "enum"

        # Error code table: must have code + description
        if _match_all(headers, [
            _CODE_KEYWORDS,
            _DESCRIPTION_KEYWORDS,
        ]):
            return "error_code"

        return "unknown"

    # ------------------------------------------------------------------
    # Tier 2 — multi-signal analysis
    # ------------------------------------------------------------------

    @staticmethod
    def _multi_signal_classify(headers: list[str],
                               rows: list[list[str]]) -> str:
        """Classify a table using content and structural signals.

        Order matters — checks progress from most-specific to broadest.
        """
        # 1. Record/struct definition
        if _is_record_pattern(headers, rows):
            return "record"

        # 2. COM property table (checked before method because return-type
        #    signals in col 0 can be false positives for property tables)
        if _is_com_property_pattern(headers, rows):
            return "property"

        # 3. COM method/function table
        if _is_com_method_pattern(headers, rows):
            return "method"

        # 4. Enum / error-code table
        if _is_enum_headers(headers) and _has_value_assignments(rows):
            if _has_negative_values(rows):
                return "error_code"
            return "enum"

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
