"""Converts raw extracted structures into typed domain objects.

Flow
----
1.  A :class:`DocxParser` yields a :class:`RawDocument`.
2.  A :class:`TableDetector` classifies each table.
3.  :func:`merge_multi_row_functions` collapses continuation rows.
4.  :class:`DocumentConverter` consumes all three and produces domain
    objects (:class:`APIInterface`, :class:`APIFunction`, etc.).
"""

import logging
import re
from dataclasses import dataclass
from typing import Any

from src.domain.rag.api_docs.extraction.docx_parser import (
    RawDocument,
    RawParagraph,
    RawTable,
)
from src.domain.rag.api_docs.model.models import (
    APIEnum,
    APIEnumValue,
    APIErrorCode,
    APIFunction,
    APIInterface,
    APIParameter,
    APIProperty,
    APIRecord,
    APIRecordField,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Column-role detection helpers
# ---------------------------------------------------------------------------

# Keyword groups used to map table columns to semantic roles
_NAME_KW = {"name", "method", "function", "property", "member", "identifier"}
_PARAM_KW = {"parameter", "param", "argument", "arg", "parameters"}
_RETURN_KW = {"return", "returns", "retval", "ret value", "type"}
_DESC_KW = {"description", "desc", "remarks", "summary", "comment"}
_TYPE_KW = {"type", "type_annotation", "data type", "datatype"}
_ACCESS_KW = {"access", "access modifier", "accessor"}
_VALUE_KW = {"value", "constant", "enum value", "values"}
_CODE_KW = {"code", "error code", "error_code", "error", "errorcode"}


def _find_column(headers: list[str], keywords: set[str]) -> int | None:
    """Return the index of the first header matching any *keywords*."""
    normalised = [h.lower().strip() for h in headers]
    for kw in keywords:
        kw_lower = kw.lower()
        for i, h in enumerate(normalised):
            if kw_lower in h:
                return i
    return None


# ---------------------------------------------------------------------------
# Parameter-string parsing
# ---------------------------------------------------------------------------


def _parse_parameter_line(line: str) -> APIParameter:
    """Parse a single parameter definition line.

    Accepted formats (trimmed)::

        name
        name : type
        name : type   # description  (not currently parsed separately)
        name : type   optional
        name : type = default

    The colon-whitespace boundary is used to split name from type.  If no
    colon is present the entire string is treated as the parameter name and
    the type defaults to ``"unknown"``.
    """
    line = line.strip()
    if not line:
        return APIParameter(name="unnamed", type_annotation="unknown",
                            description="(empty)")

    # Split on the first colon surrounded by whitespace
    parts = re.split(r"\s*:\s*", line, maxsplit=1)

    name = parts[0].strip()
    rest = parts[1].strip() if len(parts) > 1 else ""

    # Heuristic: if there was no colon we can't determine a type
    if not rest:
        return APIParameter(name=name, type_annotation="unknown",
                            description="")

    # Try to extract optional / default from the type portion
    optional = False
    default_value: str | None = None

    # Match trailing "= default" or "=default"
    eq_match = re.search(r"\s*=\s*(.+)$", rest)
    if eq_match:
        default_value = eq_match.group(1).strip()
        rest = rest[:eq_match.start()].strip()

    # Match trailing "[optional]", "(optional)", or "optional" keyword
    opt_match = re.search(
        r"(?:\[optional\]|\(optional\)|\boptional\b)\s*$", rest, re.IGNORECASE,
    )
    if opt_match:
        optional = True
        rest = rest[:opt_match.start()].strip()

    type_annotation = rest if rest else "unknown"

    return APIParameter(
        name=name,
        type_annotation=type_annotation,
        description="",
        optional=optional,
        default_value=default_value,
    )


def _parse_parameters(cell_text: str) -> list[APIParameter]:
    """Parse a multi-line parameter cell into a list of :class:`APIParameter`."""
    if not cell_text.strip():
        return []
    return [_parse_parameter_line(line) for line in cell_text.split("\n")
            if line.strip()]


def _parse_inline_params(params_str: str) -> list[APIParameter]:
    """Parse inline comma-separated parameters from a method signature.

    Accepts formats like::

        [in] long value
        [out] BSTR* result
        long value, BSTR* result

    Col 1 of a method row may contain ``FuncName([in] long value, [out] BSTR* result)``
    — this function handles the inner portion after extracting the function name.
    """
    if not params_str.strip():
        return []

    params: list[APIParameter] = []
    for part in params_str.split(","):
        part = part.strip()
        if not part:
            continue

        # Extract [modifier] if present
        modifier = ""
        if part.startswith("[") and "]" in part:
            close_idx = part.index("]")
            modifier = part[1:close_idx]
            part = part[close_idx + 1 :].strip()

        # Split on whitespace; last token is typically the name
        tokens = part.split()
        if not tokens:
            continue

        if len(tokens) == 1:
            name = tokens[0]
            type_annotation = "unknown"
        else:
            name = tokens[-1]
            type_annotation = " ".join(tokens[:-1])

        params.append(APIParameter(
            name=name,
            type_annotation=type_annotation,
            description="",
            optional=("optional" in modifier.lower()
                      or "out" in modifier.lower()),
            default_value=None,
        ))

    return params


# ---------------------------------------------------------------------------
# Interface-name extraction from heading text
# ---------------------------------------------------------------------------

# Regex that matches common COM interface naming patterns inside headings
_INTERFACE_RE = re.compile(
    r"(?:Interface\s*:?\s*)?"
    r"(I[A-Z][A-Za-z0-9]*)"
    r"(?:\s+Interface)?",
    re.IGNORECASE,
)


def _extract_interface_name(heading_text: str) -> str | None:
    """Try to extract a COM interface name from a heading string.

    Returns the interface name (e.g. ``"IFileDialog"``) or ``None``.
    """
    m = _INTERFACE_RE.search(heading_text)
    if m:
        return m.group(1)
    # Fallback: if no I-prefix match, return the full heading text as-is
    clean = heading_text.strip().rstrip(".:")
    return clean if clean else None


# ---------------------------------------------------------------------------
# Heading-context builder
# ---------------------------------------------------------------------------


@dataclass
class TableContext:
    """Heading context for a single table during conversion."""

    heading_text: str = ""
    heading_levels: dict[int, str] | None = None  # level → text


def _build_table_contexts(
    raw_document: RawDocument,
    num_tables: int,
) -> tuple[dict[int, TableContext], dict[int, int]]:
    """Build a heading-context map for the first *num_tables* tables.

    Returns ``(contexts, depths)`` where:
      * contexts: ``{table_index: TableContext}``
      * depths: ``{table_index: heading_depth}`` (number of active headings)
    """
    # Collect all elements (paragraphs + tables) with their body positions
    elements: list[tuple[int, str, Any]] = []
    for p in raw_document.paragraphs:
        elements.append((p.position, "paragraph", p))
    for t_idx, t in enumerate(raw_document.tables[:num_tables]):
        elements.append((t.position, "table", t_idx))

    elements.sort(key=lambda x: x[0])

    heading_stack: dict[int, str] = {}
    contexts: dict[int, TableContext] = {}
    depths: dict[int, int] = {}

    for _pos, kind, data in elements:
        if kind == "paragraph":
            para: RawParagraph = data
            if para.heading_level >= 0:
                # Remove lower-level headings (higher level number)
                # so the stack only contains the active heading chain
                levels_to_remove = [
                    lvl for lvl in heading_stack
                    if lvl >= para.heading_level
                ]
                for lvl in levels_to_remove:
                    heading_stack.pop(lvl, None)
                heading_stack[para.heading_level] = para.text
        elif kind == "table":
            table_index: int = data
            # The most specific heading is the one with the highest level
            # number (deepest in the hierarchy) still in the stack
            best_heading = ""
            if heading_stack:
                deepest_level = max(heading_stack.keys())
                best_heading = heading_stack.get(deepest_level, "")
            contexts[table_index] = TableContext(
                heading_text=best_heading,
                heading_levels=dict(heading_stack),
            )
            depths[table_index] = len(heading_stack)

    return contexts, depths


# ---------------------------------------------------------------------------
# Column index caching helper
# ---------------------------------------------------------------------------


def _safe_get(
    row: list[str],
    col: int | None,
    default: str = "",
) -> str:
    """Return ``row[col]`` if *col* is not ``None``, otherwise *default*."""
    if col is None:
        return default
    if 0 <= col < len(row):
        return row[col]
    return default


# ---------------------------------------------------------------------------
# DocumentConverter
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Default configuration values (matching spec design details)
# ---------------------------------------------------------------------------

_DEFAULT_TYPE_PATTERNS: dict[str, re.Pattern] = {
    "enum": re.compile(r"^(enums|enum)$", re.IGNORECASE),
    "error_code": re.compile(r"^(errors|error-codes|error_codes)$", re.IGNORECASE),
    "record": re.compile(r"^(records|record|models|model)$", re.IGNORECASE),
}

_DEFAULT_HEADING_POLICY: dict[str, int] = {
    "interface_depth": 2,
    "method_depth": 3,
    "enum_depth": 2,
    "error_code_depth": 2,
    "record_depth": 2,
}


# ---------------------------------------------------------------------------
# ReDoS-pattern detection (nested quantifiers)
# ---------------------------------------------------------------------------

# Match a parenthesised group followed by + or * quantifier
_REDOS_GROUP_RE = re.compile(r"\(([^()]*)\)([*+])")


@dataclass
class GenericTableEntry:
    """Generic table created when a table does not match any known COM type."""

    heading_stack: dict[int, str]
    rows: list[list[str]]
    header_row: list[str]
    position: int
    heading_text: str = ""
    parent_interface: str | None = None


def _has_redos_vulnerability(pattern: str) -> bool:
    """Check if a regex pattern may be vulnerable to ReDoS.

    Looks for groups with ``+`` or ``*`` quantifiers that contain
    inner quantifiers or alternation (common catastrophic-backtracking
    sources).  This is a best-effort heuristic, not a full static
    analysis.
    """
    # Strip character classes to reduce false positives
    simplified = re.sub(r"\[[^\]]*\]", "X", pattern)
    for m in _REDOS_GROUP_RE.finditer(simplified):
        inner = m.group(1)
        # Group contains a quantifier -> nested quantifier risk
        if re.search(r"[*+{?]", inner):
            return True
        # Alternation inside a quantified group -> catastrophic backtracking
        if "|" in inner and m.group(2) in "*+":
            return True
    return False


def _validate_regex_pattern(pattern: str) -> re.Pattern:
    """Validate and compile a regex pattern, guarding against ReDoS.

    Returns
    -------
    Compiled :class:`re.Pattern` with ``re.IGNORECASE`` baked in.

    Raises
    ------
    ValueError
        If the pattern is syntactically invalid or deemed a ReDoS risk.
    """
    if _has_redos_vulnerability(pattern):
        raise ValueError(f"Potentially vulnerable regex pattern rejected: {pattern!r}")
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        raise ValueError(f"Invalid regex pattern: {pattern!r}: {e}") from e


# ---------------------------------------------------------------------------
# Log-redaction helper
# ---------------------------------------------------------------------------

_SENSITIVE_VALUE_RE = re.compile(
    r"(?i)((?:api[_-]?key|secret|token|password|auth|credential)\s*[:=]\s*)(\S+)",
)


def _redact_for_log(text: str, max_len: int = 200) -> str:
    """Truncate and redact sensitive values from *text* for safe logging.

    - Strips non-printable characters (except tab) to prevent log injection.
    - Replaces newlines and carriage returns with visible markers.
    - Truncates to ``max_len`` characters.
    - Replaces common secret values (API keys, tokens, passwords, etc.)
      with ``key=***REDACTED***`` or ``key: ***REDACTED***``.
    """
    # Remove non-printable chars (except tab) to prevent log injection
    text = "".join(ch for ch in text if ch.isprintable() or ch == "\t")
    # Replace newlines/carriage returns with visible markers
    text = text.replace("\n", "\\n").replace("\r", "\\r")
    truncated = text[:max_len]
    return _SENSITIVE_VALUE_RE.sub(r"\1***REDACTED***", truncated)



class DocumentConverter:
    """Converts raw extracted structures into typed domain objects.

    Usage::

        converter = DocumentConverter()
        result = converter.convert(raw_doc, table_types, merged_tables)
        interfaces = result["interfaces"]
        enums = result["enums"]
        error_codes = result["error_codes"]
    """

    def __init__(self) -> None:
        self.interfaces: list[APIInterface] = []
        self.enums: list[APIEnum] = []
        self.error_codes: list[APIErrorCode] = []
        self.records: list[APIRecord] = []
        # Tracks interfaces we've already created (by name)
        self._interface_map: dict[str, APIInterface] = {}
        # Pre-computed interface descriptions from heading-adjacent paragraphs
        self._interface_descriptions: dict[str, str] = {}

        # ---- Configurable strategy parameters (Task 5.1) ----
        self.heading_policy: dict = dict(_DEFAULT_HEADING_POLICY)
        self.type_patterns: dict[str, re.Pattern] = dict(_DEFAULT_TYPE_PATTERNS)
        self.max_depth: int = 5
        self.format_style: str = "detailed"
        self.include_signatures: bool = True
        self.include_descriptions: bool = True
        self.min_chunk_length: int = 50

        # Entity depths populated during convert() (Task 5.2)
        self._entity_depths: dict[int, int] = {}

    def convert(
        self,
        raw_document: RawDocument,
        table_types: dict[int, str],
        merged_tables: list[RawTable],
        config: dict | None = None,
    ) -> dict[str, Any]:
        """Convert raw structures to domain objects.

        Parameters
        ----------
        raw_document:
            The raw document produced by :class:`DocxParser`.
        table_types:
            Mapping ``{table_index: type_string}`` as returned by
            :class:`TableDetector`.
        merged_tables:
            Tables after multi-row function merging.
        config:
            Optional strategy configuration dict.  If provided, overrides
            ``self.heading_policy``, ``self.type_patterns``, and other
            configurable attributes (Task 5.4).

        Returns
        -------
        dict with keys ``"interfaces"`` (list of APIInterface),
        ``"enums"`` (list of APIEnum), ``"error_codes"`` (list of
        APIErrorCode), and ``"records"`` (list of APIRecord).
        """
        self.interfaces = []
        self.enums = []
        self.error_codes = []
        self.records = []
        self.generic_tables: list[GenericTableEntry] = []
        self._interface_map = {}
        self._entity_depths = {}

        # Apply optional strategy config (Task 5.4)
        if config:
            try:
                self._apply_config(config)
            except (ValueError, re.error) as e:
                logger.warning("Invalid strategy config: %s, using defaults", e)

        # Build interface descriptions from heading-adjacent paragraphs (Task 3.1-3.3)
        self._interface_descriptions = self._build_interface_descriptions(raw_document)

        contexts, self._entity_depths = _build_table_contexts(
            raw_document, len(merged_tables),
        )

        for table_idx, table in enumerate(merged_tables):
            table_type = table_types.get(table_idx, "unknown")
            ctx = contexts.get(table_idx, TableContext())
            heading_text = ctx.heading_text.lower().strip()
            depth = self._entity_depths.get(table_idx, 0)

            # ---- Classify table using type_patterns (Task 5.7) ----
            matched_type = self._match_type_pattern(heading_text)
            effective_type = matched_type if matched_type else table_type

            logger.debug(
                "Table %d: detector_type=%s heading_pattern_type=%s "
                "effective_type=%s depth=%d heading='%s'",
                table_idx, table_type, matched_type or "—",
                effective_type, depth, _redact_for_log(ctx.heading_text),
            )

            if effective_type == "method":
                functions = self._convert_method_table(table)
                self._assign_to_interface(functions, ctx)

            elif effective_type == "property":
                properties = self._convert_property_table(table)
                self._assign_properties_to_interface(properties, ctx)

            elif effective_type == "enum":
                enum = self._convert_enum_table(table)
                if enum is not None:
                    # Set parent interface from heading context (Task 5.6)
                    enum.parent_interface = self._find_parent_interface(ctx)
                    self.enums.append(enum)
                    logger.debug(
                        "  → enum '%s' (parent_interface=%s)",
                        _redact_for_log(enum.name),
                        _redact_for_log(str(enum.parent_interface)),
                    )

            elif effective_type == "error_code":
                codes = self._convert_error_code_table(table)
                for ec in codes:
                    # Set parent interface from heading context (Task 5.6)
                    ec.parent_interface = self._find_parent_interface(ctx)
                self.error_codes.extend(codes)
                if codes:
                    logger.debug(
                        "  → %d error code(s) (parent_interface=%s)",
                        len(codes), _redact_for_log(str(codes[0].parent_interface)),
                    )

            elif effective_type == "record":
                record = self._convert_record_table(table)
                if record is not None:
                    # Set parent interface from heading context (Task 5.6)
                    record.parent_interface = self._find_parent_interface(ctx)
                    self.records.append(record)
                    logger.debug(
                        "  → record '%s' (parent_interface=%s)",
                        _redact_for_log(record.name),
                        _redact_for_log(str(record.parent_interface)),
                    )

            else:
                # Generic table — preserve unknown tables instead of dropping (Task 3.1)
                parent_interface = self._find_parent_interface(ctx)
                generic_entry = GenericTableEntry(
                    heading_stack=dict(ctx.heading_levels) if ctx.heading_levels else {},
                    rows=[[cell or "" for cell in row] for row in table.rows],
                    header_row=[cell or "" for cell in table.headers] if table.headers else [],
                    position=table_idx,
                    heading_text=ctx.heading_text,
                    parent_interface=parent_interface,
                )
                self.generic_tables.append(generic_entry)

                # Task 3.4: Upgrade logging to INFO with rich context
                first_row_preview = (
                    [cell[:50] for cell in table.rows[0][:3]]
                    if table.rows else []
                )
                logger.info(
                    "Unknown table at heading stack %s: %d rows x %d cols, "
                    "first cells: %s",
                    list(ctx.heading_levels.values()) if ctx.heading_levels else [],
                    len(table.rows), len(table.headers) if table.headers else 0,
                    first_row_preview,
                )

        # Capture non-first paragraphs under interface headings (Task 2.1)
        self._assign_paragraphs_to_interfaces(raw_document)

        logger.info(
            "Converted: %d interfaces, %d enums, %d error codes, %d records, "
            "%d generic tables",
            len(self.interfaces), len(self.enums),
            len(self.error_codes), len(self.records),
            len(self.generic_tables),
        )

        return {
            "interfaces": self.interfaces,
            "enums": self.enums,
            "error_codes": self.error_codes,
            "records": self.records,
            "generic_tables": self.generic_tables,
        }

    # ------------------------------------------------------------------
    # Config application (Task 5.4)
    # ------------------------------------------------------------------

    def _apply_config(self, config: dict) -> None:
        """Apply a strategy configuration dict to override defaults.

        Performs type validation on ``heading_policy`` and ``type_patterns``,
        compiles ``type_patterns`` values into compiled :class:`re.Pattern`
        objects (with ReDoS checking), and redacts sensitive values from
        debug log output.

        Raises
        ------
        ValueError
            If ``heading_policy`` is not a dict,
            ``type_patterns`` is not a dict or has non-string keys/values,
            or a ``type_patterns`` value is an invalid or ReDoS-vulnerable
            regex pattern.
        re.error
            If a compiled pattern raises :class:`re.error` (should not
            happen after the ``re.compile`` inside
            :func:`_validate_regex_pattern`, but caught for safety).
        """
        if "heading_policy" in config:
            hp = config["heading_policy"]
            if not isinstance(hp, dict):
                raise ValueError("heading_policy must be a dict")
            self.heading_policy.update(hp)
            logger.debug("Updated heading_policy: %s", _redact_for_log(str(self.heading_policy)))
        if "type_patterns" in config:
            tp = config["type_patterns"]
            if not isinstance(tp, dict):
                raise ValueError("type_patterns must be a dict")
            # Validate all patterns before mutating state
            new_patterns: dict[str, re.Pattern] = {}
            for key, value in tp.items():
                if not isinstance(key, str):
                    raise ValueError("type_patterns keys must be strings")
                if not isinstance(value, str):
                    raise ValueError(f"type_patterns value for {key!r} must be a string")
                new_patterns[key] = _validate_regex_pattern(value)
            self.type_patterns.update(new_patterns)
            logger.debug("Updated type_patterns: %s", _redact_for_log(str(self.type_patterns)))
        raw_max_depth = config.get("max_depth", self.max_depth)
        self.max_depth = max(1, min(10, raw_max_depth))
        self.format_style = config.get("format_style", self.format_style)
        self.include_signatures = config.get("include_signatures", self.include_signatures)
        self.include_descriptions = config.get("include_descriptions", self.include_descriptions)
        raw_min_chunk_length = config.get("min_chunk_length", self.min_chunk_length)
        self.min_chunk_length = max(0, min(10000, raw_min_chunk_length))
        logger.debug("Config applied (max_depth=%d, format_style=%s)", self.max_depth, self.format_style)  # noqa: E501

    # ------------------------------------------------------------------
    # Type-pattern matching (Task 5.7)
    # ------------------------------------------------------------------

    def _match_type_pattern(self, heading_text: str) -> str | None:
        """Check heading text against ``self.type_patterns`` regexes.

        *self.type_patterns* values are already compiled
        :class:`re.Pattern` objects (with ``re.IGNORECASE`` baked in),
        so we call ``pattern.search()`` directly.

        Returns the matched type key (``"enum"``, ``"error_code"``,
        ``"record"``) or ``None`` if no pattern matches.
        """
        for entity_type, pattern in self.type_patterns.items():
            if pattern.search(heading_text):
                return entity_type
        return None

    # ------------------------------------------------------------------
    # Interface-description capture (Task 3.1-3.3)
    # ------------------------------------------------------------------

    @staticmethod
    def _build_interface_descriptions(
        raw_document: RawDocument,
    ) -> dict[str, str]:
        """Build a map of interface name → description from heading paragraphs.

        For each Heading 2 or Heading 3 paragraph whose text matches the
        interface name pattern (starts with ``I``, PascalCase), the next
        non-table paragraph becomes its description.

        Returns ``{interface_name: description}``.  Interfaces without a
        following paragraph are omitted from the map (the caller falls back
        to heading text as the description).
        """
        # Collect all elements (paragraphs + tables) with their body positions
        elements: list[tuple[int, str, Any]] = []
        for p in raw_document.paragraphs:
            elements.append((p.position, "paragraph", p))
        for t in raw_document.tables:
            elements.append((t.position, "table", None))

        elements.sort(key=lambda x: x[0])

        descriptions: dict[str, str] = {}
        for i, (_pos, kind, data) in enumerate(elements):
            if kind != "paragraph":
                continue
            para: RawParagraph = data
            if para.heading_level not in (2, 3):
                continue
            iface_name = _extract_interface_name(para.text)
            # Only capture for real I-prefix interface names
            if not iface_name or not iface_name.startswith("I"):
                continue
            if len(iface_name) <= 1 or not iface_name[1].isupper():
                continue

            # Find next non-table paragraph
            for j in range(i + 1, len(elements)):
                next_kind, next_data = elements[j][1], elements[j][2]
                if next_kind == "paragraph":
                    next_para: RawParagraph = next_data
                    if next_para.text.strip():
                        descriptions[iface_name] = next_para.text.strip()
                        break

        return descriptions

    # ------------------------------------------------------------------
    # Paragraph assignment under interface headings (Task 2.1)
    # ------------------------------------------------------------------

    def _assign_paragraphs_to_interfaces(
        self,
        raw_document: RawDocument,
    ) -> None:
        """Assign non-first prose paragraphs under interface headings to their
        parent interface.

        Skips the first paragraph after each interface heading (already used as
        interface description by :meth:`_build_interface_descriptions`).
        Subsequent paragraphs are appended to the interface's ``paragraphs``
        list.
        """
        current_iface_name: str | None = None
        first_para_seen = False

        for para in raw_document.paragraphs:
            if para.heading_level >= 0:
                # This is a heading
                if para.heading_level in (2, 3):
                    iface_name = _extract_interface_name(para.text)
                    if iface_name and iface_name in self._interface_map:
                        current_iface_name = iface_name
                        first_para_seen = False
                        continue
                # Non-interface heading resets context
                current_iface_name = None
                continue

            # Non-heading paragraph
            if current_iface_name is None:
                continue
            if not para.text.strip():
                continue

            if not first_para_seen:
                first_para_seen = True
                continue  # Skip first paragraph (interface description)

            # All subsequent paragraphs belong to this interface
            iface = self._interface_map[current_iface_name]
            iface.paragraphs.append(para.text.strip())

    # ------------------------------------------------------------------
    # Method-table conversion
    # ------------------------------------------------------------------

    def _convert_method_table(self, table: RawTable) -> list[APIFunction]:
        """Convert a method-type table to a list of :class:`APIFunction`.

        Positional column layout (``table.headers`` is row 0):

        * **Col 0** — return type (non-empty starts a new function)
        * **Col 1** — ``name(params)`` or param name or function description
        * **Col 2** — parameter description

        Fully empty rows act as function separators.
        """
        all_rows: list[list[str]] = [table.headers, *table.rows]

        functions: list[APIFunction] = []
        current_func: APIFunction | None = None

        for row in all_rows:
            if not any(cell.strip() for cell in row):
                # Fully empty row → function separator
                if current_func is not None:
                    functions.append(current_func)
                    current_func = None
                continue

            col0 = _safe_get(row, 0)
            col1 = _safe_get(row, 1)
            col2 = _safe_get(row, 2)

            if col0.strip():
                # Non-empty col 0 → start new function
                if current_func is not None:
                    functions.append(current_func)

                return_type = col0.strip()

                if "(" in col1:
                    # Parse name(params)
                    name = col1.split("(")[0].strip()
                    inner = col1[col1.index("(") + 1:]
                    if ")" in inner:
                        inner = inner[:inner.index(")")]
                    parsed_params = _parse_inline_params(inner)
                else:
                    name = col1.strip()
                    parsed_params = []

                current_func = APIFunction(
                    name=name or "unnamed",
                    return_type=return_type,
                    parameters=parsed_params,
                    description="",
                )
            else:
                # Empty col 0 → continuation (param desc or func desc)
                if current_func is None:
                    continue

                if col1.strip() and col2.strip():
                    # Could be param description or function description text
                    known_param_names = {p.name for p in current_func.parameters}
                    if col1.strip() in known_param_names:
                        # Param description row
                        for p in current_func.parameters:
                            if p.name == col1.strip():
                                if not p.description:
                                    p.description = col2.strip()
                                break
                    else:
                        # Function description text
                        text = col1.strip()
                        if col2.strip():
                            text += " " + col2.strip()
                        if current_func.description:
                            current_func.description += " " + text
                        else:
                            current_func.description = text
                elif col1.strip():
                    # Only col 1 has text → function description text
                    if current_func.description:
                        current_func.description += " " + col1.strip()
                    else:
                        current_func.description = col1.strip()

        if current_func is not None:
            functions.append(current_func)

        return functions

    # ------------------------------------------------------------------
    # Property-table conversion
    # ------------------------------------------------------------------

    def _convert_property_table(self, table: RawTable) -> list[APIProperty]:
        """Convert a property-type table to :class:`APIProperty` objects.

        Positional column layout (``table.headers`` is row 0):

        * **Col 0** — property type annotation
        * **Col 1** — combined name+description text (split heuristically)
        * **Col 2** — unused
        """
        all_rows: list[list[str]] = [table.headers, *table.rows]

        properties: list[APIProperty] = []
        for row in all_rows:
            if not any(cell.strip() for cell in row):
                continue

            col0 = _safe_get(row, 0).strip()
            col1 = _safe_get(row, 1).strip()

            if not col1:
                continue

            name, desc = self._split_property_name_desc(col1)

            properties.append(APIProperty(
                name=name,
                type_annotation=col0,
                description=desc,
            ))

        return properties

    @staticmethod
    def _split_property_name_desc(text: str) -> tuple[str, str]:
        """Split combined property name+description text heuristically.

        Attempts, in order:

        1. Split on `` • `` (bullet with spaces)
        2. Split on `` [`` (bracket-index parameter)
        3. Fallback: find the first PascalCase/camelCase identifier
        4. Last resort: entire text is name, description is empty
        """
        text = text.strip()
        if not text:
            return ("", "")

        # 1. Bullet separator
        if " \u2022 " in text:
            parts = text.split(" \u2022 ", 1)
            return (parts[0].strip(), parts[1].strip())

        # 2. Bracket-index parameter
        if " [" in text:
            idx = text.index(" [")
            name = text[:idx].strip()
            rest = text[idx:]
            close_idx = rest.index("]") if "]" in rest else -1
            desc = rest[close_idx + 1:].strip() if close_idx >= 0 else ""
            return (name, desc)

        # 3. Find first PascalCase / camelCase identifier
        m = re.search(
            r"\b([A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)*|[a-z]+[A-Z][a-zA-Z0-9]*)\b",
            text,
        )
        if m:
            name = m.group(1)
            before = text[:m.start()].strip()
            after = text[m.end():].strip()
            desc = " ".join(p for p in [before, after] if p)
            return (name, desc)

        # 4. Last resort — entire text is the name
        return (text, "")

    # ------------------------------------------------------------------
    # Enum-table conversion
    # ------------------------------------------------------------------

    def _convert_enum_table(self, table: RawTable) -> APIEnum | None:
        """Convert an enum-type table to an :class:`APIEnum`.

        Positional column layout (``table.headers`` is row 0):

        * **Col 0** — ignored (may contain ``"enum"``)
        * **Col 1** — ``name = value`` (member) / ``EnumName {`` (group)
          / ``{`` / ``}`` (structural)
        * **Col 2** — member description or enum group description

        ``{`` and ``}`` rows are structural markers, not members.
        The first row may contain the enum group name before ``=`` or ``{``.
        """
        all_rows: list[list[str]] = [table.headers, *table.rows]

        values: list[APIEnumValue] = []
        enum_name = ""
        enum_description = ""

        for row in all_rows:
            if not any(cell.strip() for cell in row):
                continue

            _col0 = _safe_get(row, 0).strip()
            col1 = _safe_get(row, 1).strip()
            col2 = _safe_get(row, 2).strip()

            # Structural markers: { or }
            if col1 in ("{", "}"):
                if col2 and not enum_description:
                    enum_description = col2
                continue

            # Enum group name: "EnumName {" or "EnumName = {"
            if " {" in col1 or "= {" in col1:
                name_part = col1.split("{")[0].strip()
                name_part = name_part.rstrip("=").strip()
                if name_part and not enum_name:
                    enum_name = name_part
                if col2 and not enum_description:
                    enum_description = col2
                continue

            # Parse "name = value" (with optional trailing comma)
            eq_match = re.match(r"(\w+)\s*=\s*(.+?)(?:,\s*)?$", col1)
            if eq_match:
                member_name = eq_match.group(1)
                value_str = eq_match.group(2).strip()
                member_value = _parse_enum_value(value_str)
                values.append(APIEnumValue(
                    name=member_name,
                    value=member_value,
                    description=col2,
                ))
            elif col1:
                # Fallback: plain name, no value
                values.append(APIEnumValue(
                    name=col1,
                    value=None,
                    description=col2,
                ))

        if not values:
            return None

        return APIEnum(
            name=enum_name or _infer_enum_name(table, values),
            values=values,
            description=enum_description,
        )

    # ------------------------------------------------------------------
    # Record-table conversion (Task 5.3)
    # ------------------------------------------------------------------

    def _convert_record_table(self, table: RawTable) -> APIRecord | None:
        """Convert a record-type table to an :class:`APIRecord`.

        Positional column layout (``table.headers`` is row 0):

        * **Col 0** — field type (non-empty = field definition)
        * **Col 1** — field name
        * **Col 2** — field description

        Rows with ``(`` or ``)`` in col 1 are structural/delimiter rows.
        The first row may contain a record name pattern (e.g. ``RecordName = (``).
        Table caption is preferred for the record name.
        """
        all_rows: list[list[str]] = [table.headers, *table.rows]

        fields: list[APIRecordField] = []
        record_name = table.caption or ""

        for row_idx, row in enumerate(all_rows):
            if not any(cell.strip() for cell in row):
                continue

            col0 = _safe_get(row, 0).strip()
            col1 = _safe_get(row, 1).strip()
            col2 = _safe_get(row, 2).strip()

            # Skip structural/delimiter rows with parentheses
            if "(" in col1 or ")" in col1:
                if row_idx == 0 and not record_name:
                    # First row may contain record name: "RecordName = ("
                    name_part = (
                        col1.split("=")[0].strip()
                        if "=" in col1
                        else col1.rstrip("(").strip()
                    )
                    if name_part:
                        record_name = name_part
                continue

            if not col0:
                continue

            fields.append(APIRecordField(
                name=col1 or "unnamed",
                type_annotation=col0,
                description=col2,
            ))

        if not fields:
            logger.debug("Record table has no fields — skipping")
            return None

        record = APIRecord(
            name=record_name or "UnknownRecord",
            fields=fields,
            description="",
        )
        logger.debug("Parsed record '%s' with %d field(s)", record.name, len(fields))
        return record

    # ------------------------------------------------------------------
    # Error-code table conversion
    # ------------------------------------------------------------------

    def _convert_error_code_table(
        self,
        table: RawTable,
    ) -> list[APIErrorCode]:
        """Convert an error-code table to :class:`APIErrorCode` objects.

        Positional column layout (``table.headers`` is row 0):

        * **Col 0** — ignored (may contain ``"enum"``)
        * **Col 1** — ``name = value`` or plain error-code name
        * **Col 2** — description
        """
        all_rows: list[list[str]] = [table.headers, *table.rows]

        codes: list[APIErrorCode] = []
        for row in all_rows:
            if not any(cell.strip() for cell in row):
                continue

            col1 = _safe_get(row, 1).strip()
            col2 = _safe_get(row, 2).strip()

            if not col1:
                continue

            # Skip structural markers
            if col1 in ("{", "}"):
                continue

            # Parse "name = value" pattern
            eq_match = re.match(r"(\w+)\s*=\s*(.+?)(?:,\s*)?$", col1)
            if eq_match:
                name = eq_match.group(1)
                value_str = eq_match.group(2).strip()
                code_value = _parse_error_code(value_str)
                codes.append(APIErrorCode(
                    name=name,
                    code=code_value,
                    description=col2,
                ))
            else:
                # Plain name (no value)
                codes.append(APIErrorCode(
                    name=col1,
                    code=_parse_error_code(col1),
                    description=col2,
                ))

        return codes

    # ------------------------------------------------------------------
    # Interface membership helpers
    # ------------------------------------------------------------------

    def _assign_to_interface(
        self,
        functions: list[APIFunction],
        context: TableContext,
    ) -> None:
        """Assign *functions* to an interface determined by *context*."""
        iface = self._get_or_create_interface(context)
        for func in functions:
            func.parent_interface = iface.name
            # Remove duplicates by name
            existing_names = {m.name for m in iface.methods}
            if func.name not in existing_names:
                iface.methods.append(func)

    def _assign_properties_to_interface(
        self,
        properties: list[APIProperty],
        context: TableContext,
    ) -> None:
        """Assign *properties* to an interface determined by *context*."""
        iface = self._get_or_create_interface(context)
        for prop in properties:
            prop.parent_interface = iface.name
            existing_names = {p.name for p in iface.properties}
            if prop.name not in existing_names:
                iface.properties.append(prop)

    def _get_or_create_interface(self, context: TableContext) -> APIInterface:
        """Return an existing interface matching *context*, or create one."""
        iface_name = _extract_interface_name(context.heading_text) or "Unknown"

        if iface_name in self._interface_map:
            return self._interface_map[iface_name]

        # Prefer pre-computed interface description from heading-adjacent
        # paragraph; fall back to heading text (Task 3.1-3.3).
        description = self._interface_descriptions.get(
            iface_name,
            context.heading_text,
        )

        iface = APIInterface(
            name=iface_name,
            description=description,
        )
        self._interface_map[iface_name] = iface
        self.interfaces.append(iface)
        return iface

    # ------------------------------------------------------------------
    # Parent-interface resolution (Task 5.6)
    # ------------------------------------------------------------------

    @staticmethod
    def _find_parent_interface(ctx: TableContext) -> str | None:
        """Scan the heading context for a known interface name.

        Iterates through all active heading levels and returns the first
        interface name that matches a known (already-created) interface.
        """
        if not ctx.heading_levels:
            return None
        for level_text in ctx.heading_levels.values():
            iface_name = _extract_interface_name(level_text)
            if iface_name:
                return iface_name
        # Fallback: also check the most specific heading
        if ctx.heading_text:
            return _extract_interface_name(ctx.heading_text)
        return None


# ---------------------------------------------------------------------------
# Value parsing helpers
# ---------------------------------------------------------------------------


def _parse_enum_value(raw: str) -> int | str | None:
    """Try to interpret *raw* as a numeric enum value.

    Handles hex (``0x…``), plain integer, and falls back to returning the
    raw string as-is.
    """
    raw = raw.strip()
    if not raw:
        return None
    # Hex
    if raw.startswith("0x") or raw.startswith("0X"):
        try:
            return int(raw, 16)
        except ValueError:
            return raw
    # Decimal integer
    try:
        return int(raw)
    except ValueError:
        return raw


def _parse_error_code(raw: str) -> int | str | None:
    """Try to interpret *raw* as an error code value.

    Mirrors :func:`_parse_enum_value` logic since error codes often use
    the same notation (``0x80070057``, ``E_INVALIDARG``, etc.).
    """
    raw = raw.strip()
    if not raw:
        return None
    if raw.startswith("0x") or raw.startswith("0X"):
        try:
            return int(raw, 16)
        except ValueError:
            return raw
    try:
        return int(raw)
    except ValueError:
        return raw


def _infer_enum_name(
    table: RawTable,
    values: list[APIEnumValue],
) -> str:
    """Try to infer an enum name from the table caption or heading."""
    if table.caption:
        return table.caption
    # Fall back to the heading context (handled by the converter caller)
    return "UnknownEnum"
