"""Chunk text formatting — converts each ChunkNode's domain content into
formatted text suitable for embedding and retrieval.

Task 4.4: ChunkTextFormatter
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
    """

    def format_graph(
        self,
        graph: ChunkGraph,
        interfaces: list[APIInterface] | None = None,
        enums: list[APIEnum] | None = None,
        error_codes: list[APIErrorCode] | None = None,
    ) -> ChunkGraph:
        """Format every node in the graph **in-place** and return the graph.

        Args:
            graph: The graph to format (mutated in-place).
            interfaces: Original interface domain objects for detailed formatting.
            enums: Original enum domain objects for detailed formatting.
            error_codes: Original error-code domain objects for detailed formatting.

        Returns:
            The same ``ChunkGraph`` instance with ``content`` filled.
        """
        # Build lookup maps for quick domain-object access.
        iface_map = {iface.name: iface for iface in (interfaces or [])}
        enum_map = {enum.name: enum for enum in (enums or [])}
        error_map = {ec.name: ec for ec in (error_codes or [])}

        for node in graph.nodes.values():
            self._format_node(node, iface_map, enum_map, error_map)

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
    ) -> None:
        kind = node.kind
        m = node.metadata

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

    # ------------------------------------------------------------------
    # Domain-object-based formatters
    # ------------------------------------------------------------------

    @staticmethod
    def _format_interface(iface: APIInterface) -> str:
        method_names = ", ".join(m.name for m in iface.methods)
        prop_names = ", ".join(p.name for p in iface.properties)
        parts = [f"Interface {iface.name}: {iface.description or ''}"]
        if method_names:
            parts.append(f"\nMethods: {method_names}")
        if prop_names:
            parts.append(f"\nProperties: {prop_names}")
        return "".join(parts)

    @staticmethod
    def _format_method(method: APIFunction) -> str:
        params_str = ", ".join(
            f"{p.name}: {p.type_annotation or 'any'}" for p in method.parameters
        )
        ret = method.return_type or "void"
        desc = method.description or ""
        return f"{method.name}({params_str}) -> {ret}: {desc}"

    @staticmethod
    def _format_parameter(param: APIParameter) -> str:
        desc = param.description or ""
        return f"{param.name}: {param.type_annotation or 'any'} - {desc}"

    @staticmethod
    def _format_property(prop: APIProperty) -> str:
        access = prop.access or "public"
        desc = prop.description or ""
        return f"{prop.name}: {prop.type_annotation or 'any'} [{access}] - {desc}"

    @staticmethod
    def _format_enum(enum_def: APIEnum) -> str:
        value_names = ", ".join(v.name for v in enum_def.values)
        return f"Enum {enum_def.name}: {value_names}"

    @staticmethod
    def _format_enum_value(value: APIEnumValue) -> str:
        desc = value.description or ""
        val_str = repr(value.value) if value.value is not None else ""
        return f"{value.name} = {val_str}: {desc}"

    @staticmethod
    def _format_error_code(ec: APIErrorCode) -> str:
        code = ec.code if ec.code is not None else ""
        desc = ec.description or ""
        return f"{ec.name} ({code}): {desc}"

    # ------------------------------------------------------------------
    # Metadata-based fallback formatters
    # ------------------------------------------------------------------

    @staticmethod
    def _meta_interface(m: dict) -> str:
        name = m.get("interface_name", "")
        desc = m.get("description", "")
        return f"Interface {name}: {desc}" if name else f"Interface: {desc}"

    @staticmethod
    def _meta_method(m: dict) -> str:
        name = m.get("function_name", "") or m.get("name", "")
        desc = m.get("description", "")
        ret = m.get("return_type", "void")
        param_count = m.get("param_count", 0)
        params_placeholder = ", ..." if param_count > 0 else ""
        return f"{name}({params_placeholder}) -> {ret}: {desc}" if name else desc or ""

    @staticmethod
    def _meta_parameter(m: dict) -> str:
        name = m.get("name", "")
        type_ann = m.get("type_annotation", "any")
        desc = m.get("description", "")
        return f"{name}: {type_ann} - {desc}" if name else desc or ""

    @staticmethod
    def _meta_property(m: dict) -> str:
        name = m.get("name", "")
        type_ann = m.get("type_annotation", "any")
        access = m.get("access", "public")
        desc = m.get("description", "")
        return f"{name}: {type_ann} [{access}] - {desc}" if name else desc or ""

    @staticmethod
    def _meta_enum(m: dict) -> str:
        name = m.get("type_name", "")
        values_str = m.get("enum_values", "")
        return f"Enum {name}: {values_str}".rstrip(": ")

    @staticmethod
    def _meta_enum_value(m: dict) -> str:
        name = m.get("name", "")
        val_str = m.get("value", "")
        desc = m.get("description", "")
        return f"{name} = {val_str}: {desc}".rstrip(": ")

    @staticmethod
    def _meta_error_code(m: dict) -> str:
        name = m.get("name", "")
        code = m.get("code", "")
        desc = m.get("description", "")
        return f"{name} ({code}): {desc}".rstrip(": ")

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
