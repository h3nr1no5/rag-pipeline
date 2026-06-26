"""Chunk text formatting — converts each ChunkNode's domain content into
formatted text suitable for embedding and retrieval.

Task 4.4: ChunkTextFormatter
Task 7.1: Configurable formatting (format_style, include_signatures, include_descriptions)
"""

from __future__ import annotations

from src.domain.rag.api_docs.chunking.builder import ChunkGraph
from src.domain.rag.api_docs.chunking.graph import ChunkNode
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


class ChunkTextFormatter:
    """Formats ChunkNode content into human-readable text for embedding.

    Two modes of operation:

    **With domain objects** (recommended)
        Pass ``interfaces``, ``enums`` and/or ``error_codes`` to
        :meth:`format_graph` for the most detailed formatting (including
        full method signatures and type information).

    **Metadata-only** (fallback)
        If domain objects are not provided, the formatter relies on each
        node's ``metadata`` dict.  This works as long as the builder has
        populated the relevant keys (``name``, ``type_annotation``,
        ``description``, etc.).

    Formatting can be customised by passing ``config`` to :meth:`format_graph`:

    * ``format_style`` — ``"detailed"`` (default) or ``"compact"`` (shorter headings)
    * ``include_signatures`` — whether method signatures are included (default ``True``)
    * ``include_descriptions`` — whether descriptions are included (default ``True``)
    """

    def __init__(self) -> None:
        self.format_style: str = "detailed"
        self.include_signatures: bool = True
        self.include_descriptions: bool = True

    def format_graph(
        self,
        graph: ChunkGraph,
        interfaces: list[APIInterface] | None = None,
        enums: list[APIEnum] | None = None,
        error_codes: list[APIErrorCode] | None = None,
        records: list[APIRecord] | None = None,
        config: dict | None = None,
    ) -> ChunkGraph:
        """Format every node in the graph **in-place** and return the graph.

        Args:
            graph: The graph to format (mutated in-place).
            interfaces: Original interface domain objects for detailed formatting.
            enums: Original enum domain objects for detailed formatting.
            error_codes: Original error-code domain objects for detailed formatting.
            records: Original record domain objects for detailed formatting.
            config: Optional formatting configuration dict. Supported keys:
                ``format_style`` ("detailed"|"compact"),
                ``include_signatures`` (bool),
                ``include_descriptions`` (bool).
                ``None`` values use defaults.

        Returns:
            The same ``ChunkGraph`` instance with ``content`` filled.
        """
        # Apply formatting config (or reset to defaults)
        if config is not None:
            self.format_style = config.get("format_style", "detailed") or "detailed"
            self.include_signatures = config.get("include_signatures", True)
            self.include_descriptions = config.get("include_descriptions", True)
        else:
            self.format_style = "detailed"
            self.include_signatures = True
            self.include_descriptions = True

        # Build lookup maps for quick domain-object access.
        iface_map = {iface.name: iface for iface in (interfaces or [])}
        enum_map = {enum.name: enum for enum in (enums or [])}
        error_map = {ec.name: ec for ec in (error_codes or [])}
        record_map = {rec.name: rec for rec in (records or [])}

        for node in graph.nodes.values():
            self._format_node(node, iface_map, enum_map, error_map, record_map)

        return graph

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _format_node(
        self,
        node: ChunkNode,
        iface_map: dict[str, APIInterface],
        enum_map: dict[str, APIEnum],
        error_map: dict[str, APIErrorCode],
        record_map: dict[str, APIRecord] | None = None,
    ) -> None:
        kind = node.kind
        m = node.metadata
        record_map = record_map or {}

        if kind == "interface":
            name = m.get("interface_name", "")
            iface = iface_map.get(name)
            node.content = self._format_interface(iface) if iface else self._meta_interface(m)

        elif kind == "method":
            iface_name = m.get("interface_name", "")
            func_name = m.get("function_name", "")
            iface = iface_map.get(iface_name)
            method = self._find_method(iface, func_name)
            node.content = self._format_method(method) if method else self._meta_method(m)

        elif kind == "parameter":
            iface_name = m.get("interface_name", "")
            func_name = m.get("function_name", "")
            param_name = m.get("name", "")
            iface = iface_map.get(iface_name)
            param = self._find_parameter(iface, func_name, param_name)
            node.content = self._format_parameter(param) if param else self._meta_parameter(m)

        elif kind == "property":
            iface_name = m.get("interface_name", "")
            prop_name = m.get("name", "")
            iface = iface_map.get(iface_name)
            prop = self._find_property(iface, prop_name)
            node.content = self._format_property(prop) if prop else self._meta_property(m)

        elif kind == "enum":
            enum_name = m.get("type_name", "")
            enum_def = enum_map.get(enum_name)
            node.content = self._format_enum(enum_def) if enum_def else self._meta_enum(m)

        elif kind == "enum_value":
            enum_name = m.get("type_name", "")
            value_name = m.get("name", "")
            enum_def = enum_map.get(enum_name)
            value = self._find_enum_value(enum_def, value_name)
            node.content = self._format_enum_value(value) if value else self._meta_enum_value(m)

        elif kind == "error_code":
            name = m.get("name", "")
            ec = error_map.get(name)
            node.content = self._format_error_code(ec) if ec else self._meta_error_code(m)

        elif kind == "record":
            record_name = m.get("record_name", "") or m.get("type_name", "")
            rec = record_map.get(record_name)
            node.content = self._format_record(rec) if rec else self._meta_record(m)

        elif kind == "record_field":
            record_name = m.get("record_name", "")
            field_name = m.get("name", "")
            rec = record_map.get(record_name)
            field = self._find_record_field(rec, field_name)
            node.content = self._format_record_field(field) if field else self._meta_record_field(m)

    # ------------------------------------------------------------------
    # Domain-object-based formatters
    # ------------------------------------------------------------------

    def _format_interface(self, iface: APIInterface) -> str:
        method_names = ", ".join(m.name for m in iface.methods)
        prop_names = ", ".join(p.name for p in iface.properties)
        is_compact = self.format_style == "compact"

        if is_compact:
            desc = f" - {iface.description}" if self.include_descriptions and iface.description else ""
            parts = [f"I: {iface.name}{desc}"]
        else:
            desc = f": {iface.description}" if self.include_descriptions and iface.description else ":"
            parts = [f"Interface {iface.name}{desc}"]
        if method_names:
            label = "M" if is_compact else "Methods"
            parts.append(f"\n{label}: {method_names}")
        if prop_names:
            label = "P" if is_compact else "Properties"
            parts.append(f"\n{label}: {prop_names}")
        return "".join(parts)

    def _format_method(self, method: APIFunction) -> str:
        parts: list[str] = []
        if self.include_signatures:
            params_str = ", ".join(
                f"{p.name}: {p.type_annotation or 'any'}" for p in method.parameters
            )
            ret = method.return_type or "void"
            parts.append(f"{method.name}({params_str}) -> {ret}")
        else:
            parts.append(method.name)
        if self.include_descriptions and method.description:
            parts.append(f": {method.description}")
        return "".join(parts)

    def _format_parameter(self, param: APIParameter) -> str:
        base = f"{param.name}: {param.type_annotation or 'any'}"
        if self.include_descriptions and param.description:
            return f"{base} - {param.description}"
        return base

    def _format_property(self, prop: APIProperty) -> str:
        access = prop.access or "public"
        base = f"{prop.name}: {prop.type_annotation or 'any'} [{access}]"
        if self.include_descriptions and prop.description:
            return f"{base} - {prop.description}"
        return base

    def _format_enum(self, enum_def: APIEnum) -> str:
        value_names = ", ".join(v.name for v in enum_def.values)
        if self.format_style == "compact":
            return f"E: {enum_def.name} - {value_names}"
        return f"Enum {enum_def.name}: {value_names}"

    def _format_enum_value(self, value: APIEnumValue) -> str:
        val_str = repr(value.value) if value.value is not None else ""
        base = f"{value.name} = {val_str}"
        if self.include_descriptions and value.description:
            return f"{base}: {value.description}"
        return base

    def _format_error_code(self, ec: APIErrorCode) -> str:
        code = ec.code if ec.code is not None else ""
        base = f"{ec.name} ({code})"
        if self.include_descriptions and ec.description:
            return f"{base}: {ec.description}"
        return base

    def _format_record(self, record: APIRecord) -> str:
        """Format a record node using the domain object."""
        field_names = ", ".join(f.name for f in record.fields)
        is_compact = self.format_style == "compact"

        if is_compact:
            desc = f" - {record.description}" if self.include_descriptions and record.description else ""
            parts = [f"R: {record.name}{desc}"]
        else:
            desc = f": {record.description}" if self.include_descriptions and record.description else ":"
            parts = [f"Record {record.name}{desc}"]
        if field_names:
            label = "F" if is_compact else "Fields"
            parts.append(f"\n{label}: {field_names}")
        return "".join(parts)

    def _format_record_field(self, field: APIRecordField) -> str:
        """Format a record field node using the domain object."""
        base = f"{field.name}: {field.type_annotation or 'any'}"
        if self.include_descriptions and field.description:
            return f"{base} - {field.description}"
        return base

    # ------------------------------------------------------------------
    # Metadata-based fallback formatters
    # ------------------------------------------------------------------

    def _meta_interface(self, m: dict) -> str:
        name = m.get("interface_name", "")
        desc = m.get("description", "")
        is_compact = self.format_style == "compact"

        if is_compact:
            desc_part = f" - {desc}" if self.include_descriptions and desc else ""
            return f"I: {name}{desc_part}" if name else f"I:{desc_part}"
        else:
            desc_part = f": {desc}" if self.include_descriptions and desc else ":"
            return f"Interface {name}{desc_part}" if name else f"Interface{desc_part}"

    def _meta_method(self, m: dict) -> str:
        name = m.get("function_name", "") or m.get("name", "")
        desc = m.get("description", "")
        if not name:
            return desc if self.include_descriptions and desc else ""

        parts: list[str] = []
        if self.include_signatures:
            ret = m.get("return_type", "void")
            param_count = m.get("param_count", 0)
            params_placeholder = ", ..." if param_count > 0 else ""
            parts.append(f"{name}({params_placeholder}) -> {ret}")
        else:
            parts.append(name)
        if self.include_descriptions and desc:
            parts.append(f": {desc}")
        return "".join(parts)

    def _meta_parameter(self, m: dict) -> str:
        name = m.get("name", "")
        if not name:
            desc = m.get("description", "")
            return desc if self.include_descriptions and desc else ""
        type_ann = m.get("type_annotation", "any")
        base = f"{name}: {type_ann}"
        if self.include_descriptions:
            desc = m.get("description", "")
            if desc:
                return f"{base} - {desc}"
        return base

    def _meta_property(self, m: dict) -> str:
        name = m.get("name", "")
        if not name:
            desc = m.get("description", "")
            return desc if self.include_descriptions and desc else ""
        type_ann = m.get("type_annotation", "any")
        access = m.get("access", "public")
        base = f"{name}: {type_ann} [{access}]"
        if self.include_descriptions:
            desc = m.get("description", "")
            if desc:
                return f"{base} - {desc}"
        return base

    def _meta_enum(self, m: dict) -> str:
        name = m.get("type_name", "")
        values_str = m.get("enum_values", "")
        if self.format_style == "compact":
            result = f"E: {name} - {values_str}".rstrip(" -")
        else:
            result = f"Enum {name}: {values_str}".rstrip(": ")
        return result

    def _meta_enum_value(self, m: dict) -> str:
        name = m.get("name", "")
        val_str = m.get("value", "")
        base = f"{name} = {val_str}".rstrip(" =")
        if self.include_descriptions:
            desc = m.get("description", "")
            if desc:
                return f"{base}: {desc}"
        return base

    def _meta_error_code(self, m: dict) -> str:
        name = m.get("name", "")
        code = m.get("code", "")
        base = f"{name} ({code})".rstrip(" ()")
        if self.include_descriptions:
            desc = m.get("description", "")
            if desc:
                return f"{base}: {desc}"
        return base

    def _meta_record(self, m: dict) -> str:
        """Format a record node using only metadata."""
        name = m.get("record_name", "") or m.get("type_name", "")
        desc = m.get("description", "")
        is_compact = self.format_style == "compact"

        if is_compact:
            desc_part = f" - {desc}" if self.include_descriptions and desc else ""
            return f"R: {name}{desc_part}" if name else f"R:{desc_part}"
        else:
            desc_part = f": {desc}" if self.include_descriptions and desc else ":"
            return f"Record {name}{desc_part}" if name else f"Record{desc_part}"

    def _meta_record_field(self, m: dict) -> str:
        """Format a record field node using only metadata."""
        name = m.get("name", "")
        if not name:
            desc = m.get("description", "")
            return desc if self.include_descriptions and desc else ""
        type_ann = m.get("type_annotation", "any")
        base = f"{name}: {type_ann}"
        if self.include_descriptions:
            desc = m.get("description", "")
            if desc:
                return f"{base} - {desc}"
        return base

    # ------------------------------------------------------------------
    # Lookup helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _find_method(iface: APIInterface | None, name: str) -> APIFunction | None:
        if not iface or not name:
            return None
        return next((m for m in iface.methods if m.name == name), None)

    @staticmethod
    def _find_parameter(
        iface: APIInterface | None, func_name: str, param_name: str
    ) -> APIParameter | None:
        if not iface or not func_name:
            return None
        method = next((m for m in iface.methods if m.name == func_name), None)
        if not method or not param_name:
            return None
        return next((p for p in method.parameters if p.name == param_name), None)

    @staticmethod
    def _find_property(iface: APIInterface | None, name: str) -> APIProperty | None:
        if not iface or not name:
            return None
        return next((p for p in iface.properties if p.name == name), None)

    @staticmethod
    def _find_enum_value(
        enum_def: APIEnum | None, name: str
    ) -> APIEnumValue | None:
        if not enum_def or not name:
            return None
        return next((v for v in enum_def.values if v.name == name), None)

    @staticmethod
    def _find_record_field(
        record: APIRecord | None, name: str
    ) -> APIRecordField | None:
        """Look up a record field by name."""
        if not record or not name:
            return None
        return next((f for f in record.fields if f.name == name), None)
