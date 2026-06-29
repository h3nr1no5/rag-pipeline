"""Parent chunk expansion for hierarchical API documentation.

Task 5.5: ParentExpander implementation.

When a child chunk (parameter-level or method-level) is retrieved, this
module expands the result set to include its parent chunks (method-level
or interface-level) up to a configurable depth.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.domain.rag.api_docs.chunking.builder import ChunkGraph


class ParentExpander:
    """Expands a list of chunk IDs to include ancestor chunks.

    Walks the ``parent_id`` chain of each chunk and adds all ancestors up
    to *max_parents* levels deep.
    """

    def expand(
        self,
        chunk_ids: list[str],
        graph: ChunkGraph,
        max_parents: int = 2,
    ) -> list[str]:
        """Expand *chunk_ids* with their parent/grandparent chunks.

        Args:
            chunk_ids: The initially retrieved chunk IDs.
            graph: The chunk graph used to look up ``parent_id`` chains.
            max_parents: Maximum number of ancestor levels to include
                         (default 2, meaning parent and grandparent).

        Returns:
            Deduplicated list of chunk IDs containing the original IDs plus
            any discovered ancestors.
        """
        result: set[str] = set(chunk_ids)

        for cid in chunk_ids:
            node = graph.nodes.get(cid)
            if node is None:
                continue

            parent_id = node.parent_id
            depth = 0
            while parent_id is not None and depth < max_parents:
                result.add(parent_id)
                parent_node = graph.nodes.get(parent_id)
                parent_id = parent_node.parent_id if parent_node else None
                depth += 1

        return list(result)
