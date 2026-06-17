"""Unit tests for ChunkAssembler (chunking/assembler.py)."""

from src.pdf_semantic_chunking.extraction.model import DocumentElement, DocumentHierarchy
from src.pdf_semantic_chunking.enrichment.model import ComDocumentElement
from src.pdf_semantic_chunking.pipeline.context import ChunkData
from src.pdf_semantic_chunking.chunking.assembler import (
    ChunkAssembler,
    _count_tokens,
)


# ======================================================================
# Helper factories
# ======================================================================


def _make_el(
    el_type: str,
    content: str = "",
    font_size: float = 0,
    section_hierarchy: list[str] | None = None,
) -> DocumentElement:
    el = DocumentElement(type=el_type, content=content)  # type: ignore[arg-type]
    el.metadata["font_size"] = font_size
    if section_hierarchy:
        el.metadata["section_hierarchy"] = section_hierarchy
    return el


def _make_com_el(
    com_type: str | None,
    content: str = "",
    element_name: str | None = None,
    return_type: str | None = None,
    signature: str | None = None,
    parameters: list[dict] | None = None,
    error_codes: list[str] | None = None,
    keywords: list[str] | None = None,
    section_hierarchy: list[str] | None = None,
) -> ComDocumentElement:
    el = ComDocumentElement(
        type="PARAGRAPH",  # type: ignore[arg-type]
        content=content,
        com_type=com_type,
        element_name=element_name,
        return_type=return_type,
        signature=signature,
        parameters=parameters or [],
        error_codes=error_codes or [],
        keywords=keywords or [],
    )
    if section_hierarchy:
        el.metadata["section_hierarchy"] = section_hierarchy
    return el


def _hierarchy(els: list[DocumentElement]) -> DocumentHierarchy:
    root = DocumentElement(type="PAGE", content="")  # type: ignore[arg-type]
    root.children = els
    return DocumentHierarchy(root=root)


def _single_chunk(content: str, meta: dict | None = None, idx: int = 0) -> ChunkData:
    return ChunkData(content=content, metadata=meta or {}, chunk_index=idx)


# ======================================================================
# _count_tokens (module-level helper)
# ======================================================================


class TestCountTokens:
    """Tests for the _count_tokens word-count helper."""

    def test_empty_string(self):
        assert _count_tokens("") == 0

    def test_single_word(self):
        assert _count_tokens("hello") == 1

    def test_multiple_words(self):
        assert _count_tokens("hello world foo") == 3

    def test_whitespace_normalized(self):
        assert _count_tokens("hello   world") == 2

    def test_newlines_as_delimiters(self):
        assert _count_tokens("hello\nworld\nfoo") == 3


# ======================================================================
# ChunkAssembler
# ======================================================================


class TestChunkAssembler:
    """Tests for ChunkAssembler."""

    # ------------------------------------------------------------------ #
    # Empty / edge cases
    # ------------------------------------------------------------------ #

    def test_empty_hierarchy_returns_empty_list(self):
        assembler = ChunkAssembler()
        hierarchy = DocumentHierarchy()
        assert assembler.assemble(hierarchy, []) == []

    def test_root_with_empty_page_and_no_children(self):
        assembler = ChunkAssembler()
        root = DocumentElement(type="PAGE", content="")  # type: ignore[arg-type]
        hierarchy = DocumentHierarchy(root=root)
        assert assembler.assemble(hierarchy, []) == []

    def test_root_with_empty_page_and_children(self):
        """Root PAGE is stripped when it has empty content and is the only element."""
        assembler = ChunkAssembler()
        els = [
            _make_el("PARAGRAPH", "Hello world"),
        ]
        hierarchy = _hierarchy(els)
        chunks = assembler.assemble(hierarchy, [])
        assert len(chunks) == 1
        assert "Hello world" in chunks[0].content

    # ------------------------------------------------------------------ #
    # Single segment, no boundaries
    # ------------------------------------------------------------------ #

    def test_single_segment_no_boundaries(self):
        assembler = ChunkAssembler()
        els = [
            _make_el("PARAGRAPH", "First paragraph."),
            _make_el("PARAGRAPH", "Second paragraph."),
        ]
        hierarchy = _hierarchy(els)
        chunks = assembler.assemble(hierarchy, [])
        assert len(chunks) == 1
        assert "First paragraph." in chunks[0].content
        assert "Second paragraph." in chunks[0].content

    # ------------------------------------------------------------------ #
    # Boundaries split content
    # ------------------------------------------------------------------ #

    def test_boundaries_split_into_multiple_chunks(self):
        assembler = ChunkAssembler(max_tokens=200, chunk_overlap=0)
        # Each chunk needs >50 tokens (min_chunk_size=50) to survive merge
        chunk_a_words = "A " * 100
        chunk_b_words = "B " * 100
        els = [
            _make_el("PARAGRAPH", chunk_a_words),
            _make_el("HEADING", "Title"),
            _make_el("PARAGRAPH", chunk_b_words),
        ]
        hierarchy = _hierarchy(els)
        # flat = [PAGE(0), PARAGRAPH(1), HEADING(2), PARAGRAPH(3)]
        # _strip_root won't strip (more than 1 element), so boundary index
        # must account for root PAGE at index 0. Use index 2 to split
        # after Paragraph("Chunk A") before HEADING("Title").
        chunks = assembler.assemble(hierarchy, [2])
        assert len(chunks) >= 2
        assert any("A" in c.content and "B" not in c.content for c in chunks)
        assert any("B" in c.content and "A" not in c.content for c in chunks)

    # ------------------------------------------------------------------ #
    # Chunk data structure
    # ------------------------------------------------------------------ #

    def test_chunk_has_content_metadata_and_index(self):
        assembler = ChunkAssembler()
        els = [_make_el("PARAGRAPH", "Hello")]
        hierarchy = _hierarchy(els)
        chunks = assembler.assemble(hierarchy, [])
        assert len(chunks) == 1
        chunk = chunks[0]
        assert isinstance(chunk.content, str)
        assert isinstance(chunk.metadata, dict)
        assert isinstance(chunk.chunk_index, int)

    def test_chunk_index_sequential(self):
        assembler = ChunkAssembler()
        els = [
            _make_el("PARAGRAPH", "A"),
            _make_el("HEADING", "Split"),
            _make_el("PARAGRAPH", "B"),
        ]
        hierarchy = _hierarchy(els)
        chunks = assembler.assemble(hierarchy, [1])
        for i, c in enumerate(chunks):
            assert c.chunk_index == i

    def test_token_count_in_metadata(self):
        assembler = ChunkAssembler()
        els = [_make_el("PARAGRAPH", "one two three")]
        hierarchy = _hierarchy(els)
        chunks = assembler.assemble(hierarchy, [])
        assert chunks[0].metadata.get("token_count") == 3

    # ------------------------------------------------------------------ #
    # Metadata building
    # ------------------------------------------------------------------ #

    def test_element_type_from_com_element(self):
        assembler = ChunkAssembler()
        els = [
            _make_com_el(com_type="COM_METHOD", content="long Foo()", element_name="Foo"),
        ]
        hierarchy = _hierarchy(els)
        chunks = assembler.assemble(hierarchy, [])
        assert chunks[0].metadata.get("element_type") == "function"

    def test_element_type_mixed_when_multiple_types(self):
        assembler = ChunkAssembler()
        els = [
            _make_com_el(com_type="COM_METHOD", content="method"),
            _make_com_el(com_type="COM_PROPERTY", content="prop"),
        ]
        hierarchy = _hierarchy(els)
        chunks = assembler.assemble(hierarchy, [])
        assert chunks[0].metadata.get("element_type") == "mixed"

    def test_element_type_from_non_com_is_mixed(self):
        assembler = ChunkAssembler()
        els = [_make_el("PARAGRAPH", "plain")]
        hierarchy = _hierarchy(els)
        chunks = assembler.assemble(hierarchy, [])
        assert chunks[0].metadata.get("element_type") == "mixed"

    def test_has_code_block_when_present(self):
        assembler = ChunkAssembler()
        els = [
            _make_el("PARAGRAPH", "text"),
            _make_el("CODE_BLOCK", "code"),
        ]
        hierarchy = _hierarchy(els)
        chunks = assembler.assemble(hierarchy, [])
        assert chunks[0].metadata.get("has_code_block") is True

    def test_has_code_block_when_inferred(self):
        assembler = ChunkAssembler()
        els = [
            _make_el("INFERRED_CODE_BLOCK", "code"),
        ]
        hierarchy = _hierarchy(els)
        chunks = assembler.assemble(hierarchy, [])
        assert chunks[0].metadata.get("has_code_block") is True

    def test_no_code_block_metadata(self):
        assembler = ChunkAssembler()
        els = [_make_el("PARAGRAPH", "text")]
        hierarchy = _hierarchy(els)
        chunks = assembler.assemble(hierarchy, [])
        assert chunks[0].metadata.get("has_code_block") is False

    def test_section_hierarchy_propagated(self):
        assembler = ChunkAssembler()
        els = [
            _make_el("PARAGRAPH", "text", section_hierarchy=["doc", "intro"]),
        ]
        hierarchy = _hierarchy(els)
        chunks = assembler.assemble(hierarchy, [])
        assert chunks[0].metadata.get("section_hierarchy") == ["doc", "intro"]

    def test_element_name_from_first_com_element(self):
        assembler = ChunkAssembler()
        els = [
            _make_com_el(com_type="COM_METHOD", content="foo", element_name="FirstMethod"),
            _make_com_el(com_type="COM_METHOD", content="bar", element_name="SecondMethod"),
        ]
        hierarchy = _hierarchy(els)
        chunks = assembler.assemble(hierarchy, [])
        assert chunks[0].metadata.get("element_name") == "FirstMethod"

    def test_com_details_copied_to_metadata(self):
        assembler = ChunkAssembler()
        els = [
            _make_com_el(
                com_type="COM_METHOD",
                content="method",
                element_name="Foo",
                return_type="long",
                signature="long Foo()",
                parameters=[{"name": "x", "type": "int"}],
                error_codes=["E_FAIL"],
                keywords=["foo"],
            ),
        ]
        hierarchy = _hierarchy(els)
        chunks = assembler.assemble(hierarchy, [])
        meta = chunks[0].metadata
        assert meta.get("return_type") == "long"
        assert meta.get("signature") == "long Foo()"
        assert meta.get("parameters") == [{"name": "x", "type": "int"}]
        assert meta.get("error_codes") == ["E_FAIL"]
        assert meta.get("keywords") == ["foo"]

    # ------------------------------------------------------------------ #
    # _merge_undersized
    # ------------------------------------------------------------------ #

    def test_merge_undersized_merges_small_chunk(self):
        """A chunk below min_chunk_size merges with the next chunk."""
        assembler = ChunkAssembler(max_tokens=800)
        small = _single_chunk("small", {"element_type": "text"}, idx=0)
        large = _single_chunk(" ".join(["word"] * 300), {"element_type": "text"}, idx=1)
        merged = assembler._merge_undersized([small, large])
        assert len(merged) == 1
        assert "small" in merged[0].content

    def test_merge_undersized_keeps_large_chunk(self):
        assembler = ChunkAssembler(max_tokens=800)
        chunk1 = _single_chunk(" ".join(["word"] * 300), {"element_type": "text"}, idx=0)
        chunk2 = _single_chunk(" ".join(["word"] * 300), {"element_type": "text"}, idx=1)
        merged = assembler._merge_undersized([chunk1, chunk2])
        assert len(merged) == 2

    def test_merge_undersized_single_chunk_unchanged(self):
        assembler = ChunkAssembler()
        chunk = _single_chunk("hello", {}, idx=0)
        merged = assembler._merge_undersized([chunk])
        assert len(merged) == 1
        assert merged[0].content == "hello"

    def test_merge_undersized_empty_list(self):
        assembler = ChunkAssembler()
        merged = assembler._merge_undersized([])
        assert merged == []

    def test_merge_undersized_sets_merged_from_metadata(self):
        assembler = ChunkAssembler(max_tokens=800)
        small = _single_chunk("small", {"element_type": "a"}, idx=0)
        large = _single_chunk(" ".join(["word"] * 300), {"element_type": "b"}, idx=1)
        merged = assembler._merge_undersized([small, large])
        assert merged[0].metadata.get("merged_from") == ["a", "b"]

    # ------------------------------------------------------------------ #
    # _split_oversized
    # ------------------------------------------------------------------ #

    def test_split_oversized_splits_by_paragraphs(self):
        assembler = ChunkAssembler()
        paras = "\n\n".join([f"paragraph {i} " * 20 for i in range(5)])
        result = assembler._split_oversized(paras, {}, max_tokens=50)
        assert len(result) > 1

    def test_split_oversized_small_content_no_split(self):
        assembler = ChunkAssembler()
        content = "small content"
        result = assembler._split_oversized(content, {}, max_tokens=800)
        assert len(result) == 1

    def test_split_oversized_preserves_metadata(self):
        assembler = ChunkAssembler()
        paras = "\n\n".join([f"paragraph {i} " * 30 for i in range(3)])
        meta = {"element_type": "function", "source": "test"}
        result = assembler._split_oversized(paras, meta, max_tokens=50)
        for chunk in result:
            assert chunk.metadata.get("element_type") == "function"
            assert chunk.metadata.get("source") == "test"

    def test_split_oversized_empty_content(self):
        """Empty string produces one empty chunk (the empty paragraph piece)."""
        assembler = ChunkAssembler()
        result = assembler._split_oversized("", {}, max_tokens=100)
        assert len(result) == 1
        assert result[0].content == ""

    # ------------------------------------------------------------------ #
    # _apply_overlap
    # ------------------------------------------------------------------ #

    def test_apply_overlap_on_single_chunk_no_change(self):
        assembler = ChunkAssembler()
        chunk = _single_chunk("hello world", {}, idx=0)
        result = assembler._apply_overlap([chunk])
        assert len(result) == 1
        assert result[0].content == "hello world"

    def test_apply_overlap_adds_tail_of_previous(self):
        assembler = ChunkAssembler(max_tokens=800, chunk_overlap=10)
        words_a = "one two three four five six seven eight nine ten eleven twelve"
        words_b = "thirteen fourteen fifteen sixteen seventeen eighteen"
        chunk_a = _single_chunk(words_a, {}, idx=0)
        chunk_b = _single_chunk(words_b, {}, idx=1)
        result = assembler._apply_overlap([chunk_a, chunk_b])
        # overlap_tokens = 10
        # Last 10 words of chunk_a should be prepended to chunk_b
        assert len(result) == 2
        assert result[1].content.startswith("three four five six seven eight nine ten eleven twelve")
        assert "thirteen fourteen fifteen" in result[1].content

    def test_apply_overlap_does_not_modify_first_chunk(self):
        assembler = ChunkAssembler(max_tokens=800, chunk_overlap=10)
        words_a = "one two three four five six seven eight nine ten eleven twelve"
        words_b = "thirteen fourteen fifteen sixteen seventeen eighteen"
        chunk_a = _single_chunk(words_a, {}, idx=0)
        chunk_b = _single_chunk(words_b, {}, idx=1)
        result = assembler._apply_overlap([chunk_a, chunk_b])
        assert result[0].content == words_a

    def test_apply_overlap_minimum_ten_words(self):
        """Overlap should be at least 10 words even with tiny value."""
        assembler = ChunkAssembler(max_tokens=800, chunk_overlap=10)
        words_a = "w0 w1 w2 w3 w4 w5 w6 w7 w8 w9 w10 w11 w12 w13 w14 w15"
        words_b = "next chunk content"
        chunk_a = _single_chunk(words_a, {}, idx=0)
        chunk_b = _single_chunk(words_b, {}, idx=1)
        result = assembler._apply_overlap([chunk_a, chunk_b])
        # overlap_tokens = 10
        # With 16 words > 10, overlap IS applied
        assert "w6 w7 w8 w9 w10 w11 w12 w13 w14 w15" in result[1].content

    # ------------------------------------------------------------------ #
    # Full assemble pipeline (integration-style)
    # ------------------------------------------------------------------ #

    def test_assemble_pipeline_with_boundaries(self):
        assembler = ChunkAssembler(max_tokens=200)
        # Each segment needs >50 tokens (min_chunk_size=50) to survive merge
        intro = "Introduction. " * 30
        method_foo = "long Foo() " * 40
        method_bar = "int Bar() " * 40
        heading_props = "# Properties"
        prop_name = "string Name " * 40
        els = [
            _make_el("PARAGRAPH", intro),
            _make_el("HEADING", "# Methods"),
            _make_com_el(com_type="COM_METHOD", content=method_foo, element_name="Foo"),
            _make_com_el(com_type="COM_METHOD", content=method_bar, element_name="Bar"),
            _make_el("HEADING", heading_props),
            _make_com_el(com_type="COM_PROPERTY", content=prop_name, element_name="Name"),
        ]
        hierarchy = _hierarchy(els)
        boundaries = [1, 4]  # after "first paragraph" and after /# Properties
        chunks = assembler.assemble(hierarchy, boundaries)
        assert len(chunks) >= 2
        for chunk in chunks:
            assert isinstance(chunk.metadata, dict)

    def test_assembler_default_parameters(self):
        assembler = ChunkAssembler()
        assert assembler.max_tokens == 800
        assert assembler.chunk_overlap == 80
        assert assembler.min_chunk_size == 200

    def test_assembler_custom_parameters(self):
        assembler = ChunkAssembler(max_tokens=500, chunk_overlap=50)
        assert assembler.max_tokens == 500
        assert assembler.chunk_overlap == 50
