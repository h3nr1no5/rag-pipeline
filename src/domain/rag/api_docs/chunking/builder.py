"""Chunk graph builder — converts domain objects into a parent-child chunk graph.

Task 4.1: ChunkGraphBuilder implementation
Task 4.2: Chunk metadata enrichment
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from src.domain.rag.api_docs.chunking.graph import ChunkNode
from src.domain.rag.api_docs.model.models import (
    APIEnum,
    APIErrorCode,
    APIInterface,
    APIRecord,
)

logger = logging.getLogger(__name__)


@dataclass
class ChunkGraph:
    """A directed acyclic graph of text chunks.

    Attributes:
        nodes: Mapping of chunk_id -> ChunkNode for O(1) lookup.
        root_node_ids: Ordered list of top-level (level 0) node IDs.
    """

    nodes: dict[str, ChunkNode] = field(default_factory=dict)
    root_node_ids: list[str] = field(default_factory=list)


class ChunkGraphBuilder:
    """Converts structured COM domain objects into a ChunkGraph.

    Hierarchy::

        Interface (level 0)
        ├── Method (level 1)
        │   └── Parameter (level 2)
        └── Property (level 1)
        Enum (level 0)
        └── EnumValue (level 1)
        ErrorCode (level 0, standalone)
        Record (level 0)
        └── RecordField (level 1)

    Each node's ``metadata`` dict is populated with the fields specified
    in Task 4.2:

    - ``chunk_id``, ``parent_id``, ``kind``, ``level``, ``source_doc``
    - ``interface_name`` — the containing interface name (if applicable)
    - ``function_name`` — the containing function name (if applicable)
    - ``type_name`` — type/enum name (enum, property nodes)
    - ``description`` — description text from the domain object
    - ``name`` — the entity's *own* name (method, property, parameter,
      enum value, error code)
    """

    def __init__(self) -> None:
        # Configurable instance attributes (Task 6.1)
        self.max_depth: int = 5
        self.include_entities: bool = True

    def build(
        self,
        interfaces: list[APIInterface] | None = None,
        enums: list[APIEnum] | None = None,
        error_codes: list[APIErrorCode] | None = None,
        records: list[APIRecord] | None = None,
        source_doc: str = "",
        config: dict | None = None,
    ) -> ChunkGraph:
        """Build a chunk graph from domain objects.

        Args:
            interfaces: List of API interface definitions.
            enums: List of API enum definitions.
            error_codes: List of API error code definitions.
            records: List of API record definitions.
            source_doc: Source document identifier (e.g. filename).
            config: Optional strategy configuration dict. If provided,
                    extracts ``max_depth``, ``include_entities``, etc.

        Returns:
            A populated ChunkGraph with all nodes and root references.
        """
        graph = ChunkGraph()

        interfaces = interfaces or []
        enums = enums or []
        error_codes = error_codes or []
        records = records or []

        # Apply strategy config (Task 6.1)
        if config:
            raw_max_depth = config.get("max_depth", self.max_depth)
            self.max_depth = max(1, min(10, raw_max_depth))
            self.include_entities = config.get("include_entities", self.include_entities)
        else:
            # Reset to defaults when no config is provided
            self.max_depth = 5
            self.include_entities = True

        for interface in interfaces:
            self._add_interface(graph, interface, source_doc, level=0)

        for enum in enums:
            self._add_enum(graph, enum, source_doc)

        for ec in error_codes:
            self._add_error_code(graph, ec, source_doc)

        for record in records:
            self._add_record(graph, record, source_doc, level=0)

        return graph

    # ------------------------------------------------------------------
    # Internal helpers — per domain type
    # ------------------------------------------------------------------

    def _add_interface(self, graph: ChunkGraph, iface: APIInterface, source_doc: str, level: int = 0) -> None:
        """Create an interface node and its method / property children.

        Args:
            graph: The chunk graph to add nodes to.
            iface: The interface domain object.
            source_doc: Source document identifier.
            level: The nesting level for the interface node (default 0).
                   Methods/properties are created at ``level + 1``,
                   parameters at ``level + 2``.
        """
        interface_node = self._add_node(
            graph=graph,
            kind="interface",
            level=level,
            source_doc=source_doc,
        )
        interface_node.metadata.update(
            {
                "chunk_id": interface_node.chunk_id,
                "parent_id": None,
                "kind": "interface",
                "level": level,
                "source_doc": source_doc,
                "interface_name": iface.name or "",
                "description": iface.description or "",
            }
        )
        graph.root_node_ids.append(interface_node.chunk_id)

        child_level = level + 1

        # ---- Methods at level+1 (Task 6.3 / 6.6) ----
        if child_level < self.max_depth:
            for method in iface.methods:
                method_node = self._add_node(
                    graph=graph,
                    kind="method",
                    level=child_level,
                    parent_id=interface_node.chunk_id,
                    source_doc=source_doc,
                )
                method_node.metadata.update(
                    {
                        "chunk_id": method_node.chunk_id,
                        "parent_id": interface_node.chunk_id,
                        "kind": "method",
                        "level": child_level,
                        "source_doc": source_doc,
                        "interface_name": iface.name or "",
                        "function_name": method.name or "",
                        "name": method.name or "",
                        "description": method.description or "",
                        "return_type": method.return_type or "",
                        "param_count": len(method.parameters),
                    }
                )
                interface_node.child_ids.append(method_node.chunk_id)

                # ---- Parameters at level+2 (Task 6.6) ----
                param_level = child_level + 1
                if param_level < self.max_depth:
                    for param in method.parameters:
                        param_node = self._add_node(
                            graph=graph,
                            kind="parameter",
                            level=param_level,
                            parent_id=method_node.chunk_id,
                            source_doc=source_doc,
                        )
                        param_node.metadata.update(
                            {
                                "chunk_id": param_node.chunk_id,
                                "parent_id": method_node.chunk_id,
                                "kind": "parameter",
                                "level": param_level,
                                "source_doc": source_doc,
                                "interface_name": iface.name or "",
                                "function_name": method.name or "",
                                "name": param.name or "",
                                "type_annotation": param.type_annotation or "",
                                "description": param.description or "",
                                "optional": param.optional,
                            }
                        )
                        method_node.child_ids.append(param_node.chunk_id)
                else:
                    logger.debug(
                        "Skipping parameter nodes for %s.%s: "
                        "level %d >= max_depth %d",
                        iface.name, method.name, param_level, self.max_depth,
                    )
        else:
            logger.debug(
                "Skipping method nodes for %s: level %d >= max_depth %d",
                iface.name, child_level, self.max_depth,
            )

        # ---- Properties at level+1 (Task 6.6) ----
        if child_level < self.max_depth:
            for prop in iface.properties:
                prop_node = self._add_node(
                    graph=graph,
                    kind="property",
                    level=child_level,
                    parent_id=interface_node.chunk_id,
                    source_doc=source_doc,
                )
                prop_node.metadata.update(
                    {
                        "chunk_id": prop_node.chunk_id,
                        "parent_id": interface_node.chunk_id,
                        "kind": "property",
                        "level": child_level,
                        "source_doc": source_doc,
                        "interface_name": iface.name or "",
                        "name": prop.name or "",
                        "type_annotation": prop.type_annotation or "",
                        "access": prop.access or "",
                        "description": prop.description or "",
                    }
                )
                interface_node.child_ids.append(prop_node.chunk_id)
        else:
            logger.debug(
                "Skipping property nodes for %s: level %d >= max_depth %d",
                iface.name, child_level, self.max_depth,
            )

    def _add_enum(self, graph: ChunkGraph, enum_def: APIEnum, source_doc: str) -> None:
        """Create an enum node and its value children."""
        enum_node = self._add_node(
            graph=graph,
            kind="enum",
            level=0,
            source_doc=source_doc,
        )
        enum_value_names = ", ".join(v.name for v in enum_def.values)
        enum_node.metadata.update(
            {
                "chunk_id": enum_node.chunk_id,
                "parent_id": None,
                "kind": "enum",
                "level": 0,
                "source_doc": source_doc,
                "type_name": enum_def.name or "",
                "description": enum_def.description or "",
                "enum_values": enum_value_names,
                # Task 6.4 — parent interface correlation
                "interface_name": enum_def.parent_interface or "",
            }
        )
        graph.root_node_ids.append(enum_node.chunk_id)

        # Task 6.6 — respect max_depth
        if 1 < self.max_depth:
            for value in enum_def.values:
                value_node = self._add_node(
                    graph=graph,
                    kind="enum_value",
                    level=1,
                    parent_id=enum_node.chunk_id,
                    source_doc=source_doc,
                )
                value_node.metadata.update(
                    {
                        "chunk_id": value_node.chunk_id,
                        "parent_id": enum_node.chunk_id,
                        "kind": "enum_value",
                        "level": 1,
                        "source_doc": source_doc,
                        "type_name": enum_def.name or "",
                        "name": value.name or "",
                        "value": repr(value.value) if value.value is not None else "",
                        "description": value.description or "",
                    }
                )
                enum_node.child_ids.append(value_node.chunk_id)
        else:
            logger.debug(
                "Skipping enum value nodes for %s: level 1 >= max_depth %d",
                enum_def.name, self.max_depth,
            )

    def _add_error_code(
        self, graph: ChunkGraph, ec: APIErrorCode, source_doc: str
    ) -> None:
        """Create a standalone error-code node."""
        node = self._add_node(
            graph=graph,
            kind="error_code",
            level=0,
            source_doc=source_doc,
        )
        node.metadata.update(
            {
                "chunk_id": node.chunk_id,
                "parent_id": None,
                "kind": "error_code",
                "level": 0,
                "source_doc": source_doc,
                "name": ec.name or "",
                "code": str(ec.code) if ec.code is not None else "",
                "description": ec.description or "",
                # Task 6.4 — parent interface correlation
                "interface_name": ec.parent_interface or "",
            }
        )
        graph.root_node_ids.append(node.chunk_id)

    # ------------------------------------------------------------------
    # Record nodes (Task 6.5)
    # ------------------------------------------------------------------

    def _add_record(self, graph: ChunkGraph, record: APIRecord, source_doc: str, level: int = 0) -> None:
        """Create a record node and its field children.

        Args:
            graph: The chunk graph to add nodes to.
            record: The record domain object.
            source_doc: Source document identifier.
            level: The nesting level for the record node (default 0).
                   Fields are created at ``level + 1``.
        """
        record_node = self._add_node(
            graph=graph,
            kind="record",
            level=level,
            source_doc=source_doc,
        )
        record_node.metadata.update(
            {
                "chunk_id": record_node.chunk_id,
                "parent_id": None,
                "kind": "record",
                "level": level,
                "source_doc": source_doc,
                "record_name": record.name or "",
                "type_name": record.name or "",
                "description": record.description or "",
                "interface_name": record.parent_interface or "",
            }
        )
        graph.root_node_ids.append(record_node.chunk_id)

        # ---- Fields at level+1 (Task 6.6) ----
        child_level = level + 1
        if child_level < self.max_depth:
            for field in record.fields:
                field_node = self._add_node(
                    graph=graph,
                    kind="record_field",
                    level=child_level,
                    parent_id=record_node.chunk_id,
                    source_doc=source_doc,
                )
                field_node.metadata.update(
                    {
                        "chunk_id": field_node.chunk_id,
                        "parent_id": record_node.chunk_id,
                        "kind": "record_field",
                        "level": child_level,
                        "source_doc": source_doc,
                        "record_name": record.name or "",
                        "name": field.name or "",
                        "type_annotation": field.type_annotation or "",
                        "description": field.description or "",
                    }
                )
                record_node.child_ids.append(field_node.chunk_id)
        else:
            logger.debug(
                "Skipping field nodes for record %s: level %d >= max_depth %d",
                record.name, child_level, self.max_depth,
            )

    # ------------------------------------------------------------------
    # Low-level node factory
    # ------------------------------------------------------------------

    @staticmethod
    def _add_node(
        graph: ChunkGraph,
        kind: str,
        level: int,
        parent_id: str | None = None,
        source_doc: str = "",
    ) -> ChunkNode:
        """Create a new ChunkNode, add it to the graph, and return it."""
        chunk_id = str(uuid.uuid4())
        node = ChunkNode(
            chunk_id=chunk_id,
            parent_id=parent_id,
            kind=kind,
            level=level,
            source_doc=source_doc,
        )
        graph.nodes[chunk_id] = node
        return node
