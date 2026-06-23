"""Cross-reference link traversal for API documentation chunks.

Task 5.4: LinkTraverser implementation.

Detects COM interface cross-references in chunk text content (e.g.
"See INode", parameter type ``INode``) and recursively follows them to
include referenced interface chunks in the result set.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.domain.rag.api_docs.chunking.builder import ChunkGraph

logger = logging.getLogger(__name__)

# Pattern: word boundary, "I", uppercase letter, then alphanum/underscore
_INTERFACE_REF_PATTERN = re.compile(r"\bI[A-Z][a-zA-Z0-9_]*\b")


class LinkTraverser:
    """Detects and follows type cross-references in chunk content.

    When a retrieved chunk's text references a COM interface (e.g. ``INode``,
    ``IElement``), this traverser appends the referenced interface chunk to
    the result set and recurses up to *max_depth* levels.
    """

    def __init__(self) -> None:
        self._interface_name_to_id: dict[str, str] = {}

    def traverse(
        self,
        chunk_ids: list[str],
        graph: ChunkGraph,
        max_depth: int = 2,
    ) -> list[str]:
        """Traverse cross-references starting from *chunk_ids*.

        Args:
            chunk_ids: The initially retrieved chunk IDs.
            graph: The chunk graph (used to look up node content and resolve
                   interface name → chunk_id).
            max_depth: Maximum recursion depth for link following (default 2).

        Returns:
            Expanded list of chunk IDs (original IDs plus any newly discovered
            referenced chunks), preserving order and deduplicated.
        """
        if not chunk_ids or not graph.nodes:
            return list(chunk_ids)

        # Build the interface name → chunk_id lookup once per traversal
        self._interface_name_to_id.clear()
        for node in graph.nodes.values():
            if node.kind == "interface":
                name = node.metadata.get("interface_name", "")
                if name:
                    self._interface_name_to_id[name] = node.chunk_id

        result: list[str] = []
        visited: set[str] = set()

        def _traverse(current_ids: list[str], depth: int) -> None:
            if depth > max_depth:
                return

            next_ids: list[str] = []
            for cid in current_ids:
                if cid in visited:
                    continue
                visited.add(cid)
                result.append(cid)

                node = graph.nodes.get(cid)
                if node is None:
                    continue

                # Find all interface references in this node's content
                for ref_name in self._find_interface_refs(node.content):
                    ref_id = self._interface_name_to_id.get(ref_name)
                    if ref_id is not None and ref_id not in visited:
                        visited.add(ref_id)
                        result.append(ref_id)
                        next_ids.append(ref_id)

            if next_ids:
                _traverse(next_ids, depth + 1)

        _traverse(chunk_ids, 0)
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _find_interface_refs(content: str) -> list[str]:
        """Extract unique COM interface names from *content*.

        Matches tokens that follow the COM convention: ``I`` followed by
        an uppercase letter and then word characters (e.g. ``INode``,
        ``IElementFactory``).
        """
        if not content:
            return []
        matches = _INTERFACE_REF_PATTERN.findall(content)
        # Remove duplicates while preserving some order
        seen: set[str] = set()
        unique: list[str] = []
        for m in matches:
            if m not in seen:
                seen.add(m)
                unique.append(m)
        return unique
