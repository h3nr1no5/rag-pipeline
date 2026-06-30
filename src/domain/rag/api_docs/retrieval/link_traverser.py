"""Cross-reference link traversal for API documentation chunks.

Task 5.4: LinkTraverser implementation.

Detects COM interface (``I``-prefix) and enum (``E``-prefix) cross-references
in chunk text content (e.g. "See INode", parameter type ``INode``,
``EMaterialType``) and recursively follows them to include referenced
interface/enum chunks in the result set.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.domain.rag.api_docs.chunking.builder import ChunkGraph

logger = logging.getLogger(__name__)

# Pattern: word boundary, "I" or "E", uppercase letter, then alphanum/underscore
_TYPE_REF_PATTERN = re.compile(r"\b[IE][A-Z][a-zA-Z0-9_]*\b")


class LinkTraverser:
    """Detects and follows type cross-references in chunk content.

    When a retrieved chunk's text references a COM interface (e.g. ``INode``,
    ``IElement``) or enum (e.g. ``EMaterialType``, ``ENationalDesignCode``),
    this traverser appends the referenced interface/enum chunk to the result
    set and recurses up to *max_depth* levels.

    No mutable instance state — thread-safe for concurrent traversal calls.
    """

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
                   interface/enum name → chunk_id).
            max_depth: Maximum recursion depth for link following (default 2).

        Returns:
            Expanded list of chunk IDs (original IDs plus any newly discovered
            referenced chunks), preserving order and deduplicated.
        """
        if not chunk_ids or not graph.nodes:
            return list(chunk_ids)

        # Build name → chunk_id lookups once per traversal
        interface_name_to_id: dict[str, str] = {}
        enum_name_to_id: dict[str, str] = {}
        for node in graph.nodes.values():
            if node.kind == "interface":
                name = node.metadata.get("interface_name", "")
                if name:
                    interface_name_to_id[name] = node.chunk_id
            elif node.kind == "enum":
                name = node.metadata.get("type_name", "")
                if name:
                    enum_name_to_id[name] = node.chunk_id

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

                # Find all type references (interfaces + enums) in this node's content
                for ref_name in self._find_type_refs(node.content):
                    # Try interface first, then enum
                    ref_id = interface_name_to_id.get(ref_name)
                    if ref_id is None:
                        ref_id = enum_name_to_id.get(ref_name)
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
    def _find_type_refs(content: str) -> list[str]:
        """Extract unique COM type names from *content*.

        Matches tokens that follow the COM convention: ``I`` or ``E`` followed
        by an uppercase letter and then word characters (e.g. ``INode``,
        ``IElementFactory``, ``ENationalDesignCode``, ``EMaterialType``).
        """
        if not content:
            return []
        matches = _TYPE_REF_PATTERN.findall(content)
        # Remove duplicates while preserving some order
        seen: set[str] = set()
        unique: list[str] = []
        for m in matches:
            if m not in seen:
                seen.add(m)
                unique.append(m)
        return unique
