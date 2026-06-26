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

_DEFAULT_TYPE_PATTERNS: dict[str, str] = {
    "enum": r"^(enums|enum)$",
    "error_code": r"^(errors|error-codes|error_codes)$",
    "record": r"^(records|record|models|model)$",
}

_DEFAULT_HEADING_POLICY: dict[str, int] = {
    "interface_depth": 2,
    "method_depth": 3,
    "enum_depth": 2,
    "error_code_depth": 2,
    "record_depth": 2,
}



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

        # ---- Configurable strategy parameters (Task 5.1) ----
        self.heading_policy: dict = dict(_DEFAULT_HEADING_POLICY)
        self.type_patterns: dict[str, str] = dict(_DEFAULT_TYPE_PATTERNS)
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
        self._interface_map = {}
        self._entity_depths = {}

        # Apply optional strategy config (Task 5.4)
        if config:
            self._apply_config(config)

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
                effective_type, depth, ctx.heading_text,
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
                        enum.name, enum.parent_interface,
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
                        len(codes), codes[0].parent_interface,
                    )

            elif effective_type == "record":
                record = self._convert_record_table(table)
                if record is not None:
                    # Set parent interface from heading context (Task 5.6)
                    record.parent_interface = self._find_parent_interface(ctx)
                    self.records.append(record)
                    logger.debug(
                        "  → record '%s' (parent_interface=%s)",
                        record.name, record.parent_interface,
                    )

            else:
                logger.debug("Table %d: unhandled type '%s'", table_idx, effective_type)

        logger.info(
            "Converted: %d interfaces, %d enums, %d error codes, %d records",
            len(self.interfaces), len(self.enums),
            len(self.error_codes), len(self.records),
        )

        return {
            "interfaces": self.interfaces,
            "enums": self.enums,
            "error_codes": self.error_codes,
            "records": self.records,
        }

    # ------------------------------------------------------------------
    # Config application (Task 5.4)
    # ------------------------------------------------------------------

    def _apply_config(self, config: dict) -> None:
        """Apply a strategy configuration dict to override defaults."""
        if "heading_policy" in config:
            self.heading_policy.update(config["heading_policy"])
            logger.debug("Updated heading_policy: %s", self.heading_policy)
        if "type_patterns" in config:
            self.type_patterns.update(config["type_patterns"])
            logger.debug("Updated type_patterns: %s", self.type_patterns)
        raw_max_depth = config.get("max_depth", self.max_depth)
        self.max_depth = max(1, min(10, raw_max_depth))
        self.format_style = config.get("format_style", self.format_style)
        self.include_signatures = config.get("include_signatures", self.include_signatures)
        self.include_descriptions = config.get("include_descriptions", self.include_descriptions)
        raw_min_chunk_length = config.get("min_chunk_length", self.min_chunk_length)
        self.min_chunk_length = max(0, min(10000, raw_min_chunk_length))
        logger.debug("Config applied (max_depth=%d, format_style=%s)", self.max_depth, self.format_style)

    # ------------------------------------------------------------------
    # Type-pattern matching (Task 5.7)
    # ------------------------------------------------------------------

    def _match_type_pattern(self, heading_text: str) -> str | None:
        """Check heading text against ``self.type_patterns`` regexes.

        Returns the matched type key (``"enum"``, ``"error_code"``,
        ``"record"``) or ``None`` if no pattern matches.
        """
        for entity_type, pattern in self.type_patterns.items():
            if re.search(pattern, heading_text, re.IGNORECASE):
                return entity_type
        return None

    # ------------------------------------------------------------------
    # Method-table conversion
    # ------------------------------------------------------------------

    def _convert_method_table(self, table: RawTable) -> list[APIFunction]:
        """Convert a method-type table to a list of :class:`APIFunction`.

        Expected column roles (detected via header keywords):

        * **name** — function / method name
        * **params** — parameter definitions (one per line)
        * **return** — return type
        * **description** — function description
        """
        headers = table.headers
        name_col = _find_column(headers, _NAME_KW)
        params_col = _find_column(headers, _PARAM_KW)
        return_col = _find_column(headers, _RETURN_KW)
        desc_col = _find_column(headers, _DESC_KW)

        functions: list[APIFunction] = []
        for row in table.rows:
            if not row:
                continue

            func_name = _safe_get(row, name_col)
            if not func_name:
                # Skip rows that don't have a function name
                continue

            params = _parse_parameters(_safe_get(row, params_col))
            return_type = _safe_get(row, return_col)
            description = _safe_get(row, desc_col)

            functions.append(APIFunction(
                name=func_name,
                return_type=return_type,
                parameters=params,
                description=description,
            ))

        return functions

    # ------------------------------------------------------------------
    # Property-table conversion
    # ------------------------------------------------------------------

    def _convert_property_table(self, table: RawTable) -> list[APIProperty]:
        """Convert a property-type table to :class:`APIProperty` objects.

        Expected column roles:

        * **name** — property name
        * **type** — property type
        * **access** — access modifier (read/write)
        * **description** — property description
        """
        headers = table.headers
        name_col = _find_column(headers, _NAME_KW)
        type_col = _find_column(headers, _TYPE_KW)
        access_col = _find_column(headers, _ACCESS_KW)
        desc_col = _find_column(headers, _DESC_KW)

        properties: list[APIProperty] = []
        for row in table.rows:
            if not row:
                continue

            prop_name = _safe_get(row, name_col)
            if not prop_name:
                continue

            properties.append(APIProperty(
                name=prop_name,
                type_annotation=_safe_get(row, type_col),
                access=_safe_get(row, access_col),
                description=_safe_get(row, desc_col),
            ))

        return properties

    # ------------------------------------------------------------------
    # Enum-table conversion
    # ------------------------------------------------------------------

    def _convert_enum_table(self, table: RawTable) -> APIEnum | None:
        """Convert an enum-type table to an :class:`APIEnum`.

        Expected column roles:

        * **name** — enum value name (optional)
        * **value** — numeric/string value
        * **description** — value description
        """
        headers = table.headers
        name_col = _find_column(headers, _NAME_KW)
        value_col = _find_column(headers, _VALUE_KW)
        desc_col = _find_column(headers, _DESC_KW)

        values: list[APIEnumValue] = []
        for row in table.rows:
            if not row:
                continue

            raw_name = _safe_get(row, name_col)
            raw_value = _safe_get(row, value_col)
            raw_desc = _safe_get(row, desc_col)

            values.append(APIEnumValue(
                name=raw_name or raw_value or "unnamed",
                value=_parse_enum_value(raw_value),
                description=raw_desc,
            ))

        if not values:
            return None

        return APIEnum(
            name=_infer_enum_name(table, values),
            values=values,
            description="",
        )

    # ------------------------------------------------------------------
    # Record-table conversion (Task 5.3)
    # ------------------------------------------------------------------

    def _convert_record_table(self, table: RawTable) -> APIRecord | None:
        """Convert a record-type table to an :class:`APIRecord`.

        Expected column roles:

        * **name** — field name
        * **type** / **type_annotation** — field type
        * **description** — field description

        The record name is taken from the table caption if available,
        otherwise inferred later from heading context.
        """
        headers = table.headers
        name_col = _find_column(headers, _NAME_KW)
        type_col = _find_column(headers, _TYPE_KW)
        desc_col = _find_column(headers, _DESC_KW)

        fields: list[APIRecordField] = []
        for row in table.rows:
            if not row:
                continue

            field_name = _safe_get(row, name_col)
            if not field_name:
                continue

            fields.append(APIRecordField(
                name=field_name,
                type_annotation=_safe_get(row, type_col),
                description=_safe_get(row, desc_col),
            ))

        if not fields:
            logger.debug("Record table has no fields — skipping")
            return None

        record = APIRecord(
            name=table.caption or "UnknownRecord",
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

        Expected column roles:

        * **code** — error code value (e.g. ``0x80070057``, ``E_INVALIDARG``)
        * **description** — error description
        """
        headers = table.headers
        code_col = _find_column(headers, _CODE_KW)
        desc_col = _find_column(headers, _DESC_KW)

        codes: list[APIErrorCode] = []
        for row in table.rows:
            if not row:
                continue

            raw_code = _safe_get(row, code_col)
            raw_desc = _safe_get(row, desc_col)
            if not raw_code:
                continue

            codes.append(APIErrorCode(
                name=raw_code,
                code=_parse_error_code(raw_code),
                description=raw_desc,
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

        iface = APIInterface(
            name=iface_name,
            description=context.heading_text,
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
