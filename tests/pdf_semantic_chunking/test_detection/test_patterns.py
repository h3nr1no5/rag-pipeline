"""Unit tests for PatternRegistry and PatternEntry (detection/patterns.py)."""

import re

import pytest

from src.pdf_semantic_chunking.detection.patterns import PatternEntry, PatternRegistry


class TestPatternEntry:
    """PatternEntry is a simple NamedTuple — basic construction tests."""

    def test_construction(self):
        entry = PatternEntry("test", r"\d+", 50)
        assert entry.name == "test"
        assert entry.pattern == r"\d+"
        assert entry.priority == 50

    def test_immutable(self):
        entry = PatternEntry("a", "b", 0)
        with pytest.raises(AttributeError):
            entry.name = "other"  # type: ignore[misc]


class TestPatternRegistry:
    """Tests for PatternRegistry."""

    # ------------------------------------------------------------------ #
    # Empty registry
    # ------------------------------------------------------------------ #

    def test_empty_registry_has_no_patterns(self):
        registry = PatternRegistry()
        assert registry.get_patterns() == []
        assert registry.get_compiled() == []
        assert registry.match_any("some text") == []

    # ------------------------------------------------------------------ #
    # Registration
    # ------------------------------------------------------------------ #

    def test_register_single_pattern(self):
        registry = PatternRegistry()
        registry.register("foo", r"\d+", priority=10)
        patterns = registry.get_patterns()
        assert len(patterns) == 1
        assert patterns[0] == PatternEntry("foo", r"\d+", 10)

    def test_register_multiple_patterns(self):
        registry = PatternRegistry()
        registry.register("a", r"a", priority=1)
        registry.register("b", r"b", priority=2)
        assert len(registry.get_patterns()) == 2

    def test_default_priority_is_zero(self):
        registry = PatternRegistry()
        registry.register("no-prio", r"hello")
        assert registry.get_patterns()[0].priority == 0

    # ------------------------------------------------------------------ #
    # Priority ordering (descending)
    # ------------------------------------------------------------------ #

    def test_returns_in_descending_priority_order(self):
        registry = PatternRegistry()
        registry.register("low", r"low", priority=10)
        registry.register("high", r"high", priority=100)
        registry.register("mid", r"mid", priority=50)
        names = [e.name for e in registry.get_patterns()]
        assert names == ["high", "mid", "low"]

    def test_same_priority_both_returned(self):
        registry = PatternRegistry()
        registry.register("x", r"x", priority=50)
        registry.register("y", r"y", priority=50)
        assert len(registry.get_patterns()) == 2
        names = {e.name for e in registry.get_patterns()}
        assert names == {"x", "y"}

    # ------------------------------------------------------------------ #
    # min_priority filtering
    # ------------------------------------------------------------------ #

    def test_get_patterns_filters_by_min_priority(self):
        registry = PatternRegistry()
        registry.register("low", r"", priority=10)
        registry.register("mid", r"", priority=50)
        registry.register("high", r"", priority=100)

        filtered = registry.get_patterns(min_priority=50)
        names = {e.name for e in filtered}
        assert names == {"mid", "high"}
        assert "low" not in names

    def test_get_patterns_exact_threshold(self):
        registry = PatternRegistry()
        registry.register("edge", r"", priority=70)
        assert len(registry.get_patterns(min_priority=70)) == 1
        assert len(registry.get_patterns(min_priority=71)) == 0

    def test_get_patterns_negative_threshold_includes_all(self):
        registry = PatternRegistry()
        registry.register("a", r"", priority=-5)
        registry.register("b", r"", priority=0)
        registry.register("c", r"", priority=5)
        assert len(registry.get_patterns(min_priority=-999)) == 3
        # default should also include all
        assert len(registry.get_patterns()) == 3

    # ------------------------------------------------------------------ #
    # get_compiled
    # ------------------------------------------------------------------ #

    def test_get_compiled_returns_compiled_regex(self):
        registry = PatternRegistry()
        registry.register("digits", r"\d+", priority=10)
        compiled = registry.get_compiled()
        assert len(compiled) == 1
        name, pattern, prio = compiled[0]
        assert name == "digits"
        assert isinstance(pattern, re.Pattern)
        assert prio == 10
        # Verify it's a working compiled regex
        assert pattern.search("abc123def") is not None

    def test_get_compiled_multiline_flag(self):
        registry = PatternRegistry()
        registry.register("start", r"^hello", priority=0)
        compiled = registry.get_compiled()[0][1]
        # multiline flag ensures ^ matches start of each line, not just string start
        assert compiled.search("foo\nhello world") is not None

    def test_get_compiled_respects_min_priority(self):
        registry = PatternRegistry()
        registry.register("visible", r".", priority=50)
        registry.register("hidden", r".", priority=10)
        assert len(registry.get_compiled(min_priority=50)) == 1
        assert len(registry.get_compiled(min_priority=10)) == 2

    # ------------------------------------------------------------------ #
    # match_any
    # ------------------------------------------------------------------ #

    def test_match_any_returns_matched_names(self):
        registry = PatternRegistry()
        registry.register("has_digit", r"\d+", priority=10)
        registry.register("has_word", r"\bfoo\b", priority=5)
        matched = registry.match_any("hello 123 foo")
        assert "has_digit" in matched
        assert "has_word" in matched

    def test_match_any_no_match_returns_empty_list(self):
        registry = PatternRegistry()
        registry.register("only_letter_a", r"a+", priority=10)
        assert registry.match_any("xyz") == []

    def test_match_any_empty_text(self):
        registry = PatternRegistry()
        registry.register("any", r".+", priority=10)
        assert registry.match_any("") == []

    def test_match_any_with_min_priority_filtering(self):
        registry = PatternRegistry()
        registry.register("matches", r"target", priority=100)
        registry.register("ignored", r"target", priority=10)
        # Both should match with default threshold
        assert len(registry.match_any("target")) == 2
        # Only high-priority should match
        assert len(registry.match_any("target", min_priority=50)) == 1

    # ------------------------------------------------------------------ #
    # create_default
    # ------------------------------------------------------------------ #

    def test_create_default_has_expected_pattern_count(self):
        registry = PatternRegistry.create_default()
        patterns = registry.get_patterns()
        assert len(patterns) == 12  # all default patterns (count register calls in create_default)

    def test_create_default_has_expected_names(self):
        registry = PatternRegistry.create_default()
        names = {e.name for e in registry.get_patterns()}
        expected = {
            "com_import", "guid_attr", "interface_type", "dll_import",
            "interface_decl", "coclass",
            "com_return_types",
            "generic_func", "generic_class", "access_modifier",
            "heading_marker", "code_marker",
        }
        assert names == expected

    def test_create_default_priority_order(self):
        registry = PatternRegistry.create_default()
        priorities = [e.priority for e in registry.get_patterns()]
        # Should be strictly descending
        for i in range(len(priorities) - 1):
            assert priorities[i] >= priorities[i + 1], (
                f"Priority order broken at index {i}: {priorities[i]} < {priorities[i + 1]}"
            )

    def test_create_default_sorted_descending(self):
        registry = PatternRegistry.create_default()
        patterns = registry.get_patterns()
        assert patterns[0].name == "com_import" or patterns[0].priority == 100

    # ------------------------------------------------------------------ #
    # Default patterns — actual content matching
    # ------------------------------------------------------------------ #

    def test_default_com_import_matches(self):
        registry = PatternRegistry.create_default()
        matched = registry.match_any("[ComImport]")
        assert "com_import" in matched

    def test_default_guid_attr_matches(self):
        registry = PatternRegistry.create_default()
        matched = registry.match_any('[Guid("12345678-1234-1234-1234-123456789abc")]')
        assert "guid_attr" in matched

    def test_default_interface_type_matches(self):
        registry = PatternRegistry.create_default()
        matched = registry.match_any("[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]")
        assert "interface_type" in matched

    def test_default_dll_import_matches(self):
        registry = PatternRegistry.create_default()
        matched = registry.match_any('[DllImport("user32.dll")]')
        assert "dll_import" in matched

    def test_default_interface_decl_matches(self):
        registry = PatternRegistry.create_default()
        matched = registry.match_any("interface IMyInterface")
        assert "interface_decl" in matched

    def test_default_coclass_matches(self):
        registry = PatternRegistry.create_default()
        matched = registry.match_any("coclass MyCoClass")
        assert "coclass" in matched

    def test_default_com_return_types_matches(self):
        registry = PatternRegistry.create_default()
        matched = registry.match_any("long Foo(")
        assert "com_return_types" in matched

    def test_default_generic_func_matches_def(self):
        registry = PatternRegistry.create_default()
        matched = registry.match_any("def my_function")
        assert "generic_func" in matched

    def test_default_generic_func_matches_arrow(self):
        registry = PatternRegistry.create_default()
        matched = registry.match_any("x => x + 1")
        assert "generic_func" in matched

    def test_default_generic_class_matches(self):
        registry = PatternRegistry.create_default()
        matched = registry.match_any("class MyClass")
        assert "generic_class" in matched

    def test_default_access_modifier_matches(self):
        registry = PatternRegistry.create_default()
        matched = registry.match_any("public void DoSomething(")
        assert "access_modifier" in matched

    def test_default_heading_marker_matches(self):
        registry = PatternRegistry.create_default()
        matched = registry.match_any("# Introduction")
        assert "heading_marker" in matched

    def test_default_code_marker_matches(self):
        registry = PatternRegistry.create_default()
        matched = registry.match_any("```python")
        assert "code_marker" in matched

    def test_default_no_match_on_plain_text(self):
        registry = PatternRegistry.create_default()
        matched = registry.match_any("This is just a plain paragraph of text.")
        assert matched == []

    # ------------------------------------------------------------------ #
    # Edge cases
    # ------------------------------------------------------------------ #

    def test_register_duplicate_name_allowed(self):
        registry = PatternRegistry()
        registry.register("dup", r"a", priority=10)
        registry.register("dup", r"b", priority=20)  # same name
        assert len(registry.get_patterns()) == 2

    def test_pattern_with_special_regex_chars(self):
        registry = PatternRegistry()
        registry.register("special", r"[.*+?^${}()|\[\]\\]", priority=10)
        assert registry.match_any("[") == ["special"]

    def test_priority_re_registration_reorders(self):
        """Re-registering should maintain correct order."""
        registry = PatternRegistry()
        registry.register("a", r"a", priority=10)
        registry.register("b", r"b", priority=50)
        # Now insert one in between
        registry.register("c", r"c", priority=25)
        priorities = [e.priority for e in registry.get_patterns()]
        assert priorities == [50, 25, 10]

    def test_match_any_returns_all_matches(self):
        """When multiple patterns match the same text, all names are returned."""
        registry = PatternRegistry()
        registry.register("num", r"\d+", priority=10)
        registry.register("word", r"\w+", priority=5)
        matched = registry.match_any("42")
        assert "num" in matched
        assert "word" in matched

    def test_match_any_deduplication(self):
        """match_any naturally deduplicates because it iterates patterns once."""
        registry = PatternRegistry()
        registry.register("a", r"\d+", priority=10)
        registry.register("b", r"\d+", priority=10)  # same pattern diff name
        matched = registry.match_any("42")
        assert len(matched) == 2  # both match but each only once
