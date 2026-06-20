"""Tests for src.pdf_semantic_chunking.enrichment.classifier.ElementClassifier.

Covers classify(), extract_element_name(), and extract_return_type()
for all COM element types as well as non-COM content.
"""

import pytest

from src.pdf_semantic_chunking.enrichment.classifier import ElementClassifier
from src.pdf_semantic_chunking.enrichment.model import ComDocumentElement


@pytest.fixture
def classifier() -> ElementClassifier:
    return ElementClassifier()


# ============================== classify ======================================
class TestClassify:
    def test_method_long_return(self, classifier: ElementClassifier) -> None:
        """long is a supported return type in METHOD_SIG_PATTERN."""
        el = ComDocumentElement(type="CODE_BLOCK", content="long GetHandle();")
        assert classifier.classify(el) == "COM_METHOD"

    def test_method_int_return(self, classifier: ElementClassifier) -> None:
        el = ComDocumentElement(type="CODE_BLOCK", content="int GetCount();")
        assert classifier.classify(el) == "COM_METHOD"

    def test_method_void(self, classifier: ElementClassifier) -> None:
        el = ComDocumentElement(type="CODE_BLOCK", content="void Close();")
        assert classifier.classify(el) == "COM_METHOD"

    def test_method_bool(self, classifier: ElementClassifier) -> None:
        el = ComDocumentElement(type="CODE_BLOCK", content="bool IsValid();")
        assert classifier.classify(el) == "COM_METHOD"

    def test_method_string(self, classifier: ElementClassifier) -> None:
        el = ComDocumentElement(type="CODE_BLOCK", content="string GetName();")
        assert classifier.classify(el) == "COM_METHOD"

    def test_method_ELongBoolean(self, classifier: ElementClassifier) -> None:
        el = ComDocumentElement(type="CODE_BLOCK", content="ELongBoolean GetStatus();")
        assert classifier.classify(el) == "COM_METHOD"

    def test_method_E_result_type(self, classifier: ElementClassifier) -> None:
        el = ComDocumentElement(type="CODE_BLOCK", content="EModelResult GetResult();")
        assert classifier.classify(el) == "COM_METHOD"

    def test_method_hr_result_not_supported(self, classifier: ElementClassifier) -> None:
        """HRESULT is NOT in METHOD_SIG_PATTERN's types list, so it classifies as None."""
        el = ComDocumentElement(
            type="CODE_BLOCK",
            content="HRESULT BringToFront([In] int nHwnd);",
        )
        assert classifier.classify(el) is None

    def test_property_get_accessor(self, classifier: ElementClassifier) -> None:
        """get_ accessor is detected by PROP_ACCESSOR_PATTERN before METHOD_SIG."""
        el = ComDocumentElement(
            type="CODE_BLOCK",
            content="long get_ActiveModel([Out] out IAxisVMModel ppModel);",
        )
        assert classifier.classify(el) == "COM_PROPERTY"

    def test_property_set_accessor(self, classifier: ElementClassifier) -> None:
        el = ComDocumentElement(
            type="CODE_BLOCK",
            content="long set_Visible([In] int value);",
        )
        assert classifier.classify(el) == "COM_PROPERTY"

    def test_property_get_set_syntax(self, classifier: ElementClassifier) -> None:
        el = ComDocumentElement(type="CODE_BLOCK", content="string Name { get; set; }")
        assert classifier.classify(el) == "COM_PROPERTY"

    def test_property_get_only_syntax(self, classifier: ElementClassifier) -> None:
        el = ComDocumentElement(type="CODE_BLOCK", content="int Count { get; }")
        assert classifier.classify(el) == "COM_PROPERTY"

    def test_property_propget_attr(self, classifier: ElementClassifier) -> None:
        el = ComDocumentElement(type="CODE_BLOCK", content="[propget] long Version();")
        assert classifier.classify(el) == "COM_PROPERTY"

    def test_enum_decl(self, classifier: ElementClassifier) -> None:
        el = ComDocumentElement(
            type="CODE_BLOCK",
            content="public enum EModelType { mt2D = 0, mt3D = 1 };",
        )
        assert classifier.classify(el) == "COM_ENUM"

    def test_record_decl(self, classifier: ElementClassifier) -> None:
        el = ComDocumentElement(
            type="CODE_BLOCK",
            content="readonly record struct RModelData { int Id; string Name; };",
        )
        assert classifier.classify(el) == "COM_RECORD"

    def test_record_decl_without_readonly(self, classifier: ElementClassifier) -> None:
        el = ComDocumentElement(
            type="CODE_BLOCK",
            content="record RModelData(int Id, string Name);",
        )
        assert classifier.classify(el) == "COM_RECORD"

    def test_struct_decl(self, classifier: ElementClassifier) -> None:
        el = ComDocumentElement(type="CODE_BLOCK", content="public struct SomeStruct { int x; };")
        assert classifier.classify(el) == "COM_RECORD"

    def test_error_code_enum(self, classifier: ElementClassifier) -> None:
        el = ComDocumentElement(
            type="CODE_BLOCK",
            content="enum EApplicationErrors { errFileNotFound = 1 };",
        )
        assert classifier.classify(el) == "COM_ERROR_CODE"

    def test_error_code_enum_singular(self, classifier: ElementClassifier) -> None:
        el = ComDocumentElement(type="CODE_BLOCK", content="enum EApplicationError { errGeneric = 0 };")
        assert classifier.classify(el) == "COM_ERROR_CODE"

    def test_error_code_checked_before_enum(self, classifier: ElementClassifier) -> None:
        """ERROR_CODE_PATTERN is checked before ENUM_PATTERN, so error enums
        classify as COM_ERROR_CODE, not COM_ENUM."""
        el = ComDocumentElement(
            type="CODE_BLOCK",
            content="enum EApplicationErrors { errFileNotFound = 1 };",
        )
        assert classifier.classify(el) == "COM_ERROR_CODE"

    def test_non_com_content_returns_none(self, classifier: ElementClassifier) -> None:
        el = ComDocumentElement(type="PARAGRAPH", content="This is a regular paragraph.")
        assert classifier.classify(el) is None

    def test_empty_content_returns_none(self, classifier: ElementClassifier) -> None:
        el = ComDocumentElement(type="PARAGRAPH", content="")
        assert classifier.classify(el) is None

    def test_generic_csharp_code_does_not_match(self, classifier: ElementClassifier) -> None:
        el = ComDocumentElement(type="CODE_BLOCK", content="var x = new List<int>();")
        assert classifier.classify(el) is None

    def test_no_false_positive_on_method_with_unknown_return(self, classifier: ElementClassifier) -> None:
        el = ComDocumentElement(type="CODE_BLOCK", content="MyCustomType DoSomething();")
        assert classifier.classify(el) is None


# ========================== extract_element_name ==============================
class TestExtractElementName:
    def test_method_name(self, classifier: ElementClassifier) -> None:
        el = ComDocumentElement(type="CODE_BLOCK", content="long GetHandle();")
        assert classifier.extract_element_name(el, "COM_METHOD") == "GetHandle"

    def test_method_name_hr_result_not_supported(self, classifier: ElementClassifier) -> None:
        """HRESULT is not in the return-types list, so extraction returns None."""
        el = ComDocumentElement(type="CODE_BLOCK", content="HRESULT BringToFront([In] int nHwnd);")
        assert classifier.extract_element_name(el, "COM_METHOD") is None

    def test_enum_name(self, classifier: ElementClassifier) -> None:
        el = ComDocumentElement(type="CODE_BLOCK", content="public enum EModelType { mt2D = 0 };")
        assert classifier.extract_element_name(el, "COM_ENUM") == "EModelType"

    def test_record_name_simple(self, classifier: ElementClassifier) -> None:
        """Simple form: 'record RModelData' extracts name correctly."""
        el = ComDocumentElement(type="CODE_BLOCK", content="record RModelData(int Id, string Name);")
        assert classifier.extract_element_name(el, "COM_RECORD") == "RModelData"

    def test_record_name_readonly_record_struct_limitation(self, classifier: ElementClassifier) -> None:
        """With 'readonly record struct RModelData', the regex matches 'record struct'
        and incorrectly captures 'struct' as the name (known limitation)."""
        el = ComDocumentElement(type="CODE_BLOCK", content="readonly record struct RModelData { };")
        result = classifier.extract_element_name(el, "COM_RECORD")
        # The pattern (?:record|struct)\s+(R?\w+) matches 'record struct'
        # capturing 'struct' instead of 'RModelData'
        assert result == "struct"

    def test_struct_name(self, classifier: ElementClassifier) -> None:
        el = ComDocumentElement(type="CODE_BLOCK", content="public struct SomeStruct { int x; };")
        assert classifier.extract_element_name(el, "COM_RECORD") == "SomeStruct"

    def test_error_code_name(self, classifier: ElementClassifier) -> None:
        el = ComDocumentElement(type="CODE_BLOCK", content="enum EApplicationErrors { errFileNotFound };")
        assert classifier.extract_element_name(el, "COM_ERROR_CODE") == "EApplicationErrors"

    def test_property_get_accessor_name(self, classifier: ElementClassifier) -> None:
        el = ComDocumentElement(type="CODE_BLOCK", content="long get_ActiveModel(...);")
        assert classifier.extract_element_name(el, "COM_PROPERTY") == "ActiveModel"

    def test_property_set_accessor_name(self, classifier: ElementClassifier) -> None:
        el = ComDocumentElement(type="CODE_BLOCK", content="long set_Visible([In] int value);")
        assert classifier.extract_element_name(el, "COM_PROPERTY") == "Visible"

    def test_property_get_set_syntax_name(self, classifier: ElementClassifier) -> None:
        el = ComDocumentElement(type="CODE_BLOCK", content="string Name { get; set; }")
        assert classifier.extract_element_name(el, "COM_PROPERTY") == "Name"

    def test_property_get_only_name(self, classifier: ElementClassifier) -> None:
        el = ComDocumentElement(type="CODE_BLOCK", content="int Count { get; }")
        assert classifier.extract_element_name(el, "COM_PROPERTY") == "Count"

    def test_unknown_type_returns_none(self, classifier: ElementClassifier) -> None:
        el = ComDocumentElement(type="PARAGRAPH", content="hello")
        assert classifier.extract_element_name(el, "COM_INTERFACE") is None


# =========================== extract_return_type ==============================
class TestExtractReturnType:
    def test_method_returns_long(self, classifier: ElementClassifier) -> None:
        el = ComDocumentElement(type="CODE_BLOCK", content="long GetHandle();")
        assert classifier.extract_return_type(el, "COM_METHOD") == "long"

    def test_method_returns_int(self, classifier: ElementClassifier) -> None:
        el = ComDocumentElement(type="CODE_BLOCK", content="int GetCount();")
        assert classifier.extract_return_type(el, "COM_METHOD") == "int"

    def test_method_returns_void(self, classifier: ElementClassifier) -> None:
        el = ComDocumentElement(type="CODE_BLOCK", content="void Close();")
        assert classifier.extract_return_type(el, "COM_METHOD") == "void"

    def test_method_returns_bool(self, classifier: ElementClassifier) -> None:
        el = ComDocumentElement(type="CODE_BLOCK", content="bool IsValid();")
        assert classifier.extract_return_type(el, "COM_METHOD") == "bool"

    def test_method_returns_string(self, classifier: ElementClassifier) -> None:
        el = ComDocumentElement(type="CODE_BLOCK", content="string GetName();")
        assert classifier.extract_return_type(el, "COM_METHOD") == "string"

    def test_method_returns_hr_result_not_supported(self, classifier: ElementClassifier) -> None:
        """HRESULT is not in the types list, so returns None."""
        el = ComDocumentElement(type="CODE_BLOCK", content="HRESULT BringToFront([In] int nHwnd);")
        assert classifier.extract_return_type(el, "COM_METHOD") is None

    def test_property_get_returns_type(self, classifier: ElementClassifier) -> None:
        """Property with get_ accessor returns the type before get_."""
        el = ComDocumentElement(type="CODE_BLOCK", content="long get_ActiveModel(...);")
        assert classifier.extract_return_type(el, "COM_PROPERTY") == "long"

    def test_property_get_hr_result_not_supported(self, classifier: ElementClassifier) -> None:
        """HRESULT is not in the types list for property return extraction either."""
        el = ComDocumentElement(type="CODE_BLOCK", content="HRESULT get_ActiveModel(...);")
        assert classifier.extract_return_type(el, "COM_PROPERTY") is None

    def test_property_get_set_syntax_return_type(self, classifier: ElementClassifier) -> None:
        el = ComDocumentElement(type="CODE_BLOCK", content="string Name { get; set; }")
        assert classifier.extract_return_type(el, "COM_PROPERTY") == "string"

    def test_enum_returns_none(self, classifier: ElementClassifier) -> None:
        el = ComDocumentElement(type="CODE_BLOCK", content="public enum EModelType { };")
        assert classifier.extract_return_type(el, "COM_ENUM") is None

    def test_record_returns_none(self, classifier: ElementClassifier) -> None:
        el = ComDocumentElement(type="CODE_BLOCK", content="readonly record struct RModelData { };")
        assert classifier.extract_return_type(el, "COM_RECORD") is None

    def test_error_code_returns_none(self, classifier: ElementClassifier) -> None:
        el = ComDocumentElement(type="CODE_BLOCK", content="enum EApplicationErrors { };")
        assert classifier.extract_return_type(el, "COM_ERROR_CODE") is None
