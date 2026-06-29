"""Chunk graph serialization — JSON-compatible dict conversions for persistence.

Task 4.3: serialize_chunk_graph / deserialize_chunk_graph
"""

from __future__ import annotations

from src.domain.rag.api_docs.chunking.builder import ChunkGraph
from src.domain.rag.api_docs.chunking.graph import ChunkNode


def serialize_chunk_graph(graph: ChunkGraph) -> dict:
    """Convert a ChunkGraph to a JSON-compatible dictionary.

    Each ChunkNode is serialised as a plain dict so the result can be
    passed directly to ``json.dumps()`` (or similar).

    Args:
        graph: The chunk graph to serialise.

    Returns:
        A dictionary with keys ``nodes`` (list of node dicts) and
        ``root_node_ids`` (list of strings).
    """
    nodes_list: list[dict] = []
    for chunk_id, node in graph.nodes.items():
        nodes_list.append(_serialize_node(node))

    return {
        "nodes": nodes_list,
        "root_node_ids": list(graph.root_node_ids),
    }


def deserialize_chunk_graph(data: dict) -> ChunkGraph:
    """Reconstruct a ChunkGraph from a dictionary produced by
    :func:`serialize_chunk_graph`.

    Args:
        data: The dictionary previously returned by ``serialize_chunk_graph``.

    Returns:
        A fully populated ``ChunkGraph`` instance.
    """
    nodes_list: list[dict] = data.get("nodes", [])
    root_ids: list[str] = data.get("root_node_ids", [])

    nodes: dict[str, ChunkNode] = {}
    for node_dict in nodes_list:
        node = _deserialize_node(node_dict)
        nodes[node.chunk_id] = node

    return ChunkGraph(nodes=nodes, root_node_ids=root_ids)


# ------------------------------------------------------------------
# Per-node helpers
# ------------------------------------------------------------------


def _serialize_node(node: ChunkNode) -> dict:
    """Convert a single ChunkNode to a plain dictionary."""
    return {
        "chunk_id": node.chunk_id,
        "parent_id": node.parent_id,
        "child_ids": list(node.child_ids),
        "kind": node.kind,
        "level": node.level,
        "source_doc": node.source_doc,
        "content": node.content,
        "metadata": dict(node.metadata),
    }


def _deserialize_node(data: dict) -> ChunkNode:
    """Convert a plain dictionary back to a ChunkNode."""
    return ChunkNode(
        chunk_id=data["chunk_id"],
        parent_id=data.get("parent_id"),
        child_ids=data.get("child_ids", []),
        kind=data.get("kind", "section"),
        level=data.get("level", 0),
        source_doc=data.get("source_doc", ""),
        content=data.get("content", ""),
        metadata=data.get("metadata", {}),
    )
