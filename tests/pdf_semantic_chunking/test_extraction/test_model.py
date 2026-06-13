"""Tests for src.pdf_semantic_chunking.extraction.model.

Covers DocumentElement creation, tree building, serialization,
and DocumentHierarchy traversal/filtering.
"""

import pytest

from src.pdf_semantic_chunking.extraction.model import (
    DocumentElement,
    DocumentHierarchy,
    ElementType,
)


class TestDocumentElement:
    """Tests for DocumentElement dataclass."""

    @pytest.mark.parametrize(
        "elem_type",
        [
            "PAGE",
            "SECTION",
            "HEADING",
            "PARAGRAPH",
            "CODE_BLOCK",
            "TABLE",
            "LIST",
            "FIGURE",
            "INFERRED_CODE_BLOCK",
            "INFERRED_TABLE",
            "FALLBACK_TEXT",
        ],
    )
    def test_create_with_all_types(self, elem_type: str) -> None:
        """DocumentElement can be created with every valid ElementType literal."""
        el = DocumentElement(type=elem_type, content=f"test-{elem_type}")
        assert el.type == elem_type
        assert el.content == f"test-{elem_type}"

    def test_default_confidence(self) -> None:
        """Default confidence is 1.0."""
        el = DocumentElement(type="PARAGRAPH", content="hello")
        assert el.confidence == 1.0

    def test_bbox_defaults_to_none(self) -> None:
        """Default bbox is None."""
        el = DocumentElement(type="PARAGRAPH", content="hello")
        assert el.bbox is None

    def test_bbox_explicit_tuple(self) -> None:
        """bbox can be set to a 4-tuple of floats."""
        bbox = (10.0, 20.0, 300.0, 400.0)
        el = DocumentElement(type="TABLE", content="data", bbox=bbox)
        assert el.bbox == bbox

    def test_metadata_defaults_to_empty_dict(self) -> None:
        """Default metadata is an empty dict (mutable default handled by dataclass field)."""
        el = DocumentElement(type="HEADING", content="Title")
        assert el.metadata == {}

    def test_metadata_explicit(self) -> None:
        """metadata can be provided at construction."""
        el = DocumentElement(
            type="PAGE", content="page1", metadata={"page_num": 1, "source": "doc.pdf"}
        )
        assert el.metadata["page_num"] == 1
        assert el.metadata["source"] == "doc.pdf"

    def test_children_defaults_to_empty_list(self) -> None:
        """Default children is an empty list."""
        el = DocumentElement(type="SECTION", content="sec")
        assert el.children == []

    def test_add_child_appends(self) -> None:
        """add_child appends a DocumentElement to children."""
        parent = DocumentElement(type="SECTION", content="parent")
        child = DocumentElement(type="PARAGRAPH", content="child")
        parent.add_child(child)
        assert len(parent.children) == 1
        assert parent.children[0] is child

    def test_add_child_multiple(self) -> None:
        """Multiple children can be added and maintain order."""
        parent = DocumentElement(type="SECTION", content="root")
        c1 = DocumentElement(type="PARAGRAPH", content="first")
        c2 = DocumentElement(type="PARAGRAPH", content="second")
        c3 = DocumentElement(type="TABLE", content="third")
        parent.add_child(c1)
        parent.add_child(c2)
        parent.add_child(c3)
        assert [c.content for c in parent.children] == ["first", "second", "third"]

    def test_add_child_nested_tree(self) -> None:
        """add_child supports building arbitrarily deep trees."""
        root = DocumentElement(type="SECTION", content="root")
        child = DocumentElement(type="SECTION", content="child")
        grandchild = DocumentElement(type="PARAGRAPH", content="grandchild")
        child.add_child(grandchild)
        root.add_child(child)
        assert root.children[0].children[0].content == "grandchild"

    def test_to_dict_basic(self) -> None:
        """to_dict returns a plain dict with all fields."""
        el = DocumentElement(type="PARAGRAPH", content="Hello world.")
        d = el.to_dict()
        assert d == {
            "type": "PARAGRAPH",
            "content": "Hello world.",
            "metadata": {},
            "children": [],
            "bbox": None,
            "confidence": 1.0,
        }

    def test_to_dict_with_children(self) -> None:
        """to_dict recursively serializes children."""
        parent = DocumentElement(type="SECTION", content="parent")
        child = DocumentElement(type="PARAGRAPH", content="child", bbox=(1, 2, 3, 4), confidence=0.95)
        parent.add_child(child)
        d = parent.to_dict()
        assert d["type"] == "SECTION"
        assert d["content"] == "parent"
        assert len(d["children"]) == 1
        assert d["children"][0] == {
            "type": "PARAGRAPH",
            "content": "child",
            "metadata": {},
            "children": [],
            "bbox": (1, 2, 3, 4),
            "confidence": 0.95,
        }

    def test_to_dict_returns_new_dict_each_call(self) -> None:
        """to_dict returns a fresh dict, not a reference to internal state."""
        el = DocumentElement(type="PAGE", content="x")
        d1 = el.to_dict()
        d2 = el.to_dict()
        assert d1 is not d2
        assert d1 == d2


class TestDocumentHierarchy:
    """Tests for DocumentHierarchy."""

    def test_default_root_creation(self) -> None:
        """Default root is a PAGE element with empty content and metadata name 'root'."""
        dh = DocumentHierarchy()
        assert dh.root.type == "PAGE"
        assert dh.root.content == ""
        assert dh.root.metadata == {"name": "root"}

    def test_custom_root(self) -> None:
        """A custom root can be passed to the constructor."""
        custom = DocumentElement(type="SECTION", content="custom-root")
        dh = DocumentHierarchy(root=custom)
        assert dh.root is custom

    def test_traverse_single_node(self) -> None:
        """traverse on a single-node tree returns just the root."""
        dh = DocumentHierarchy()
        result = dh.traverse()
        assert len(result) == 1
        assert result[0] is dh.root

    def test_traverse_depth_first(self) -> None:
        """traverse performs a depth-first traversal."""
        root = DocumentElement(type="SECTION", content="root")
        a = DocumentElement(type="PARAGRAPH", content="A")
        b = DocumentElement(type="PARAGRAPH", content="B")
        a1 = DocumentElement(type="LIST", content="A1")
        a2 = DocumentElement(type="TABLE", content="A2")
        a.add_child(a1)
        a.add_child(a2)
        root.add_child(a)
        root.add_child(b)
        dh = DocumentHierarchy(root=root)
        result = dh.traverse()
        assert [el.content for el in result] == ["root", "A", "A1", "A2", "B"]

    def test_traverse_does_not_mutate(self) -> None:
        """Multiple calls to traverse return independent lists."""
        dh = DocumentHierarchy()
        r1 = dh.traverse()
        r2 = dh.traverse()
        assert r1 == r2
        assert r1 is not r2

    def test_flatten_depth_first_equals_traverse(self) -> None:
        """flatten_depth_first returns the same result as traverse."""
        root = DocumentElement(type="SECTION", content="root")
        c1 = DocumentElement(type="PARAGRAPH", content="c1")
        c2 = DocumentElement(type="TABLE", content="c2")
        c1a = DocumentElement(type="LIST", content="c1a")
        c1.add_child(c1a)
        root.add_child(c1)
        root.add_child(c2)
        dh = DocumentHierarchy(root=root)
        assert dh.flatten_depth_first() == dh.traverse()

    def test_find_by_type_returns_matching(self) -> None:
        """find_by_type returns all elements of a given type."""
        root = DocumentElement(type="SECTION", content="root")
        p1 = DocumentElement(type="PARAGRAPH", content="p1")
        p2 = DocumentElement(type="PARAGRAPH", content="p2")
        t1 = DocumentElement(type="TABLE", content="t1")
        root.add_child(p1)
        root.add_child(p2)
        root.add_child(t1)
        dh = DocumentHierarchy(root=root)
        paragraphs = dh.find_by_type("PARAGRAPH")
        assert len(paragraphs) == 2
        assert all(e.type == "PARAGRAPH" for e in paragraphs)

    def test_find_by_type_no_match(self) -> None:
        """find_by_type returns empty list when no match."""
        root = DocumentElement(type="SECTION", content="root")
        dh = DocumentHierarchy(root=root)
        assert dh.find_by_type("FIGURE") == []

    def test_find_by_type_includes_root(self) -> None:
        """find_by_type can find the root element if its type matches."""
        root = DocumentElement(type="PAGE", content="root")
        dh = DocumentHierarchy(root=root)
        pages = dh.find_by_type("PAGE")
        assert len(pages) == 1
        assert pages[0] is root

    def test_to_dict_serialization(self) -> None:
        """to_dict returns a dict with root key."""
        root = DocumentElement(type="PAGE", content="whole page")
        dh = DocumentHierarchy(root=root)
        d = dh.to_dict()
        assert "root" in d
        assert d["root"]["type"] == "PAGE"
        assert d["root"]["content"] == "whole page"
        assert d["root"]["children"] == []

    def test_to_dict_nested(self) -> None:
        """to_dict with nested children."""
        root = DocumentElement(type="SECTION", content="s1")
        p = DocumentElement(type="PARAGRAPH", content="p1")
        root.add_child(p)
        dh = DocumentHierarchy(root=root)
        d = dh.to_dict()
        assert len(d["root"]["children"]) == 1
        assert d["root"]["children"][0]["content"] == "p1"
