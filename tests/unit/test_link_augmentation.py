"""Unit tests for build_augmented_text_with_links()."""

from src.pdf_semantic_chunking.augmentation import (
    build_augmented_text,
    build_augmented_text_with_links,
)


def test_no_links_returns_base():
    """No links/backlinks in metadata → returns same as build_augmented_text()."""
    content = "Some chunk content"
    metadata = {
        "element_type": "paragraph",
        "section": "Introduction",
    }
    result = build_augmented_text_with_links(content, metadata)
    expected = build_augmented_text(content, metadata)
    assert result == expected


def test_outgoing_internal_links():
    """Has links with target_chunk_ids → shows 'Links To:' section with truncated content."""
    content = "Some chunk content"
    metadata = {
        "links": [
            {
                "type": "internal",
                "target_chunk_ids": ["chunk_1"],
                "target_page": 2,
                "uri": None,
            }
        ]
    }
    link_targets = {
        "chunk_1": "Target chunk content that should appear in the augmentation"
    }
    result = build_augmented_text_with_links(content, metadata, link_targets)

    assert "Links To:" in result
    assert "Target chunk content" in result
    assert "(type: internal)" in result


def test_external_links():
    """External links (no target_chunk_ids) → shows URI in 'Links To:' section."""
    content = "Some chunk content"
    metadata = {
        "links": [
            {
                "type": "external",
                "uri": "https://example.com/docs/api",
                "target_chunk_ids": None,
            }
        ]
    }
    result = build_augmented_text_with_links(content, metadata)

    assert "Links To:" in result
    assert "https://example.com/docs/api" in result
    assert "(type: external)" in result


def test_backlinks():
    """Has backlinks → shows 'Referenced From:' section."""
    content = "Some chunk content"
    metadata = {
        "backlinks": [
            {"source_chunk_id": "src_1", "source_page": 1}
        ]
    }
    link_targets = {
        "src_1": "Source chunk that references this content"
    }
    result = build_augmented_text_with_links(content, metadata, link_targets)

    assert "Referenced From:" in result
    assert "Source chunk that references" in result
    assert "(type: internal)" in result


def test_cap_at_3_links():
    """More than 3 links → only 3 shown."""
    content = "Some chunk content"
    metadata = {
        "links": [
            {
                "type": "external",
                "uri": f"https://example.com/link/{i}",
            }
            for i in range(5)
        ]
    }
    result = build_augmented_text_with_links(content, metadata)

    assert "Links To:" in result
    # Each link produces one line with "- https://..."
    link_lines = [
        line for line in result.split("\n") if line.startswith("- https://")
    ]
    assert len(link_lines) == 3


def test_deleted_chunk_fallback():
    """Backlink targets missing from link_target_contents → shows '[deleted chunk]'."""
    content = "Some chunk content"
    metadata = {
        "backlinks": [
            {"source_chunk_id": "deleted_chunk", "source_page": 5}
        ]
    }
    # No entry for "deleted_chunk" in link_target_contents
    link_targets = {"other_chunk": "some unrelated content"}
    result = build_augmented_text_with_links(content, metadata, link_targets)

    assert "Referenced From:" in result
    assert "[deleted chunk]" in result


def test_link_content_truncation():
    """Content longer than 150 chars → truncated to 150."""
    content = "Some chunk content"
    long_target = "A" * 200  # 200 chars, should be truncated to 150
    metadata = {
        "links": [
            {
                "type": "internal",
                "target_chunk_ids": ["chunk_long"],
            }
        ]
    }
    link_targets = {"chunk_long": long_target}
    result = build_augmented_text_with_links(content, metadata, link_targets)

    assert "Links To:" in result
    assert "A" * 150 in result
    # The 151st character onwards should not be present
    assert "A" * 151 not in result


def test_no_links_or_backlinks():
    """Empty links and backlinks arrays → returns base text."""
    content = "Some chunk content"
    metadata = {
        "links": [],
        "backlinks": [],
    }
    result = build_augmented_text_with_links(content, metadata)
    expected = build_augmented_text(content, metadata)
    assert result == expected
