"""Unit tests for MetadataEnricher (chunking/metadata.py)."""

import re
import pytest
from src.pdf_semantic_chunking.pipeline.context import ChunkData
from src.pdf_semantic_chunking.chunking.metadata import MetadataEnricher


def _chunk(content: str = "", meta: dict | None = None, idx: int = 0) -> ChunkData:
    return ChunkData(content=content, metadata=meta or {}, chunk_index=idx)


# ======================================================================
# MetadataEnricher.enrich
# ======================================================================


class TestMetadataEnricherEnrich:
    """Tests for MetadataEnricher.enrich()."""

    def setup_method(self):
        self.enricher = MetadataEnricher()

    # ------------------------------------------------------------------ #
    # Happy path — standard enrichment
    # ------------------------------------------------------------------ #

    def test_enrich_adds_chunk_id(self):
        chunk = _chunk("hello", {"element_name": "Foo"}, idx=0)
        result = self.enricher.enrich([chunk], "/path/to/doc.pdf")
        assert len(result) == 1
        chunk_id = result[0].metadata.get("chunk_id")
        assert isinstance(chunk_id, str)
        assert len(chunk_id) > 0

    def test_chunk_id_is_uuid(self):
        chunk = _chunk("hello", {"element_name": "Foo"}, idx=0)
        result = self.enricher.enrich([chunk], "doc.pdf")
        chunk_id = result[0].metadata["chunk_id"]
        # Validate UUID v4 format
        uuid_pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
        assert re.match(uuid_pattern, chunk_id)

    def test_enrich_adds_source_document_basename(self):
        chunk = _chunk("hello", {"element_name": "Foo"}, idx=0)
        result = self.enricher.enrich([chunk], "/path/to/file.pdf")
        assert result[0].metadata["source_document"] == "file.pdf"

    def test_enrich_adds_source_document_no_path(self):
        chunk = _chunk("hello", {"element_name": "Foo"}, idx=0)
        result = self.enricher.enrich([chunk], "file.pdf")
        assert result[0].metadata["source_document"] == "file.pdf"

    def test_enrich_adds_created_at(self):
        chunk = _chunk("hello", {"element_name": "Foo"}, idx=0)
        result = self.enricher.enrich([chunk], "doc.pdf")
        created = result[0].metadata.get("created_at")
        assert isinstance(created, str)
        assert "T" in created  # ISO format

    def test_created_at_in_iso_format(self):
        chunk = _chunk("hello", {"element_name": "Foo"}, idx=0)
        result = self.enricher.enrich([chunk], "doc.pdf")
        created = result[0].metadata["created_at"]
        iso_pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
        assert re.match(iso_pattern, created)
        assert created.endswith("+00:00") or "+" in created

    # ------------------------------------------------------------------ #
    # Keywords from element_name
    # ------------------------------------------------------------------ #

    def test_keywords_extracted_from_element_name(self):
        chunk = _chunk("Some content here", {"element_name": "GetFooBar"}, idx=0)
        result = self.enricher.enrich([chunk], "doc.pdf")
        keywords = result[0].metadata.get("keywords", [])
        assert "get" in keywords
        assert "foo" in keywords
        assert "bar" in keywords

    def test_no_element_name_no_keywords_added(self):
        chunk = _chunk("Some content here", {}, idx=0)
        result = self.enricher.enrich([chunk], "doc.pdf")
        # Without element_name, the enrich code checks "element_name" in meta
        # and it won't be there, so no keywords key is added
        assert "keywords" not in result[0].metadata

    def test_empty_element_name_no_keywords(self):
        chunk = _chunk("Some content here", {"element_name": ""}, idx=0)
        result = self.enricher.enrich([chunk], "doc.pdf")
        assert "keywords" not in result[0].metadata

    # ------------------------------------------------------------------ #
    # Multiple chunks
    # ------------------------------------------------------------------ #

    def test_multiple_chunks_each_get_unique_ids(self):
        chunks = [
            _chunk("a", {"element_name": "Foo"}, idx=0),
            _chunk("b", {"element_name": "Bar"}, idx=1),
        ]
        result = self.enricher.enrich(chunks, "doc.pdf")
        assert len(result) == 2
        assert result[0].metadata["chunk_id"] != result[1].metadata["chunk_id"]

    def test_multiple_chunks_same_source_document(self):
        chunks = [
            _chunk("a", {"element_name": "Foo"}, idx=0),
            _chunk("b", {"element_name": "Bar"}, idx=1),
        ]
        result = self.enricher.enrich(chunks, "doc.pdf")
        for r in result:
            assert r.metadata["source_document"] == "doc.pdf"

    # ------------------------------------------------------------------ #
    # Input metadata preservation
    # ------------------------------------------------------------------ #

    def test_input_metadata_preserved(self):
        chunk = _chunk("hello", {"element_name": "Foo", "custom_key": "custom_value"}, idx=0)
        result = self.enricher.enrich([chunk], "doc.pdf")
        assert result[0].metadata["custom_key"] == "custom_value"

    def test_input_content_preserved(self):
        chunk = _chunk("original content", {"element_name": "Foo"}, idx=0)
        result = self.enricher.enrich([chunk], "doc.pdf")
        assert result[0].content == "original content"

    def test_input_chunk_index_preserved(self):
        chunk = _chunk("content", {"element_name": "Foo"}, idx=42)
        result = self.enricher.enrich([chunk], "doc.pdf")
        assert result[0].chunk_index == 42

    def test_source_document_is_basename_not_path(self):
        chunk = _chunk("hello", {"element_name": "Foo"}, idx=0)
        result = self.enricher.enrich([chunk], "/a/b/c/deep/nested/file.pdf")
        assert result[0].metadata["source_document"] == "file.pdf"
        assert "/" not in result[0].metadata["source_document"]

    def test_preserves_original_metadata_plus_new_fields(self):
        chunk = _chunk("content", {"element_name": "Foo", "token_count": 123}, idx=0)
        result = self.enricher.enrich([chunk], "source.pdf")
        meta = result[0].metadata
        assert meta["token_count"] == 123
        assert "chunk_id" in meta
        assert "source_document" in meta
        assert "created_at" in meta


# ======================================================================
# MetadataEnricher._extract_keywords
# ======================================================================


class TestExtractKeywords:
    """Tests for MetadataEnricher._extract_keywords()."""

    def setup_method(self):
        self.enricher = MetadataEnricher()

    def test_camelcase_split(self):
        result = self.enricher._extract_keywords("GetFooBar", "")
        assert "get" in result
        assert "foo" in result
        assert "bar" in result

    def test_pascalcase_split(self):
        """PascalCase is the same as CamelCase but first letter capital."""
        result = self.enricher._extract_keywords("PascalCaseExample", "")
        assert "pascal" in result
        assert "case" in result
        assert "example" in result

    def test_single_word_element_name(self):
        """Single uppercase word shouldn't split into single letters."""
        result = self.enricher._extract_keywords("FOO", "")
        # "FOO" -> re.findall with [A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$) -> ["FOO"]
        # Then len("foo") > 1 is True
        assert "foo" in result

    def test_single_letter_skipped(self):
        """Single letter parts should be excluded (len > 1 check)."""
        result = self.enricher._extract_keywords("A", "")
        assert result == []

    def test_content_common_terms_included(self):
        result = self.enricher._extract_keywords("Foo", "This contains error code 42")
        assert "error" in result
        assert "code" in result

    def test_content_term_not_duplicated_in_keywords(self):
        result = self.enricher._extract_keywords("GetError", "error")
        # "error" should appear only once
        assert result.count("error") == 1

    def test_content_term_not_matching_not_included(self):
        result = self.enricher._extract_keywords("Foo", "nothing relevant here")
        assert "error" not in result
        assert "code" not in result

    @pytest.mark.parametrize("term", ["error", "code", "return", "value", "get", "set", "interface", "method"])
    def test_all_common_terms_checked(self, term):
        """Each common term should be found when present in content."""
        result = self.enricher._extract_keywords("Foo", f"this has {term} in it")
        assert term in result

    def test_deduplication(self):
        """Same keyword from element_name and content should appear once."""
        result = self.enricher._extract_keywords("ErrorHandler", "error handling error code")
        # "error" from PascalCase split, also from content
        count = sum(1 for k in result if k == "error")
        assert count == 1

    def test_keyword_order_preserved(self):
        """Keywords should preserve order of first occurrence."""
        result = self.enricher._extract_keywords("FooBar", "error code")
        # element_name gives foo, bar, then content gives error, code
        foo_idx = result.index("foo")
        bar_idx = result.index("bar")
        error_idx = result.index("error")
        assert foo_idx < bar_idx
        # content terms come after element_name terms
        assert bar_idx < error_idx

    def test_underscore_in_element_name(self):
        """Underscores are not CamelCase separators; single-letter parts filtered."""
        result = self.enricher._extract_keywords("MY_CONSTANT", "")
        # re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)", "MY_CONSTANT")
        # matches: "M" (len=1 -> filtered), "CONSTANT" (len=8 -> kept)
        assert "my" not in result  # single letter "M" is filtered by len > 1
        assert "constant" in result

    def test_all_caps_words_with_min_length_kept(self):
        """ALL_CAPS words with 2+ letters (from consecutive caps) are kept."""
        result = self.enricher._extract_keywords("AB_VALUE", "")
        # "AB_VALUE": regex matches "AB" (lookahead at "_" fails, backtrack to
        # "A" with lookahead "B"=[A-Z] → "A" len=1 filtered). Then "B" no match.
        # Then "VALUE" matched (len=5, kept).
        # The individual letters "A" and "B" are filtered by len > 1 check.
        assert "value" in result

    def test_numbers_in_element_name(self):
        result = self.enricher._extract_keywords("Method2", "")
        # "Method2" -> "Method" matched by [A-Z]?[a-z]+ -> ["Method"]
        # "2" is not matched by the pattern
        assert "method" in result
        assert len(result) == 1
