from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ElementType = Literal[
    "PAGE", "SECTION", "HEADING", "PARAGRAPH", "CODE_BLOCK", "TABLE",
    "LIST", "FIGURE", "INFERRED_CODE_BLOCK", "INFERRED_TABLE", "FALLBACK_TEXT",
]


@dataclass
class DocumentElement:
    type: ElementType
    content: str
    metadata: dict = field(default_factory=dict)
    children: list[DocumentElement] = field(default_factory=list)
    bbox: tuple[float, float, float, float] | None = None
    confidence: float = 1.0

    def add_child(self, child: DocumentElement) -> None:
        self.children.append(child)

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "content": self.content,
            "metadata": self.metadata,
            "children": [c.to_dict() for c in self.children],
            "bbox": self.bbox,
            "confidence": self.confidence,
        }


class DocumentHierarchy:
    def __init__(self, root: DocumentElement | None = None):
        self.root = root or DocumentElement(type="PAGE", content="", metadata={"name": "root"})

    def find_by_type(self, element_type: ElementType) -> list[DocumentElement]:
        return [el for el in self.traverse() if el.type == element_type]

    def traverse(self) -> list[DocumentElement]:
        result: list[DocumentElement] = []

        def _dfs(node: DocumentElement) -> None:
            result.append(node)
            for child in node.children:
                _dfs(child)

        _dfs(self.root)
        return result

    def flatten_depth_first(self) -> list[DocumentElement]:
        return self.traverse()

    def to_dict(self) -> dict:
        return {"root": self.root.to_dict()}
