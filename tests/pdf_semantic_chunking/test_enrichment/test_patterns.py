"""Tests for src.pdf_semantic_chunking.enrichment.patterns regex constants.

Each regex is tested against matching and non-matching strings using re.search().
"""

import re

from src.pdf_semantic_chunking.enrichment.patterns import (
    RE_COCLASS,
    RE_COM_IMPORT,
    RE_DLL_IMPORT,
    RE_ENUM_DECL,
    RE_ERROR_ENUM,
    RE_GENERIC_CLASS,
    RE_GENERIC_FUNC,
    RE_GUID,
    RE_INTERFACE_DECL,
    RE_INTERFACE_TYPE,
    RE_METHOD_SIG,
    RE_PROP_ACCESSOR,
    RE_PROP_SYNTAX,
    RE_PROPGET,
    RE_PROPPUT,
    RE_RECORD_DECL,
    RE_STRUCT_DECL,
)


# ---------------------------------------------------------------------------
# RE_COM_IMPORT
# ---------------------------------------------------------------------------
class TestReComImport:
    def test_matches_bare(self) -> None:
        assert re.search(RE_COM_IMPORT, "[ComImport]")

    def test_matches_with_surrounding_text(self) -> None:
        assert re.search(RE_COM_IMPORT, "[ComImport]\npublic interface IFoo {}")

    def test_not_match_unclosed(self) -> None:
        assert re.search(RE_COM_IMPORT, "[ComImport") is None

    def test_not_match_with_extra_space(self) -> None:
        assert re.search(RE_COM_IMPORT, "[ComImport ]") is None

    def test_not_match_arbitrary_text(self) -> None:
        assert re.search(RE_COM_IMPORT, "ComImport") is None
        assert re.search(RE_COM_IMPORT, "[Comport]") is None


# ---------------------------------------------------------------------------
# RE_GUID
# ---------------------------------------------------------------------------
class TestReGuid:
    def test_matches_guid(self) -> None:
        assert re.search(RE_GUID, '[Guid("A8B5C3D2-E4F1-4A6B-9C8D-7E6F5A4B3C2D")]')
        assert re.search(RE_GUID, "[Guid(ABCD1234-...)]")

    def test_not_match_when_not_before_bracket(self) -> None:
        """RE_GUID requires '[' immediately before 'Guid(',
        so [ComImport, Guid(...)] does NOT match."""
        assert re.search(
            RE_GUID,
            '[ComImport, Guid("A8B5C3D2-E4F1-4A6B-9C8D-7E6F5A4B3C2D")]',
        ) is None

    def test_not_match_unclosed(self) -> None:
        assert re.search(RE_GUID, "[Guid(") is None

    def test_not_match_without_guid(self) -> None:
        assert re.search(RE_GUID, "SomeAttribute()") is None
        assert re.search(RE_GUID, "Guid") is None


# ---------------------------------------------------------------------------
# RE_INTERFACE_TYPE
# ---------------------------------------------------------------------------
class TestReInterfaceType:
    def test_matches_interface_type(self) -> None:
        assert re.search(
            RE_INTERFACE_TYPE,
            "[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]",
        )
        assert re.search(
            RE_INTERFACE_TYPE,
            "[InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]",
        )

    def test_not_match_bare(self) -> None:
        assert re.search(RE_INTERFACE_TYPE, "InterfaceType") is None


# ---------------------------------------------------------------------------
# RE_DLL_IMPORT
# ---------------------------------------------------------------------------
class TestReDllImport:
    def test_matches_dll_import(self) -> None:
        assert re.search(RE_DLL_IMPORT, '[DllImport("user32.dll")]')
        assert re.search(RE_DLL_IMPORT, '[DllImport("kernel32.dll", SetLastError=true)]')

    def test_not_match_bare(self) -> None:
        assert re.search(RE_DLL_IMPORT, "DllImport") is None
        assert re.search(RE_DLL_IMPORT, "[DllImport") is None


# ---------------------------------------------------------------------------
# RE_INTERFACE_DECL
# ---------------------------------------------------------------------------
class TestReInterfaceDecl:
    def test_matches_interface(self) -> None:
        assert re.search(RE_INTERFACE_DECL, "interface IAxisVMApplication")
        assert re.search(RE_INTERFACE_DECL, "interface IFoo")

    def test_not_match_lowercase_i(self) -> None:
        assert re.search(RE_INTERFACE_DECL, "interface Foo") is None

    def test_not_match_plain_word(self) -> None:
        assert re.search(RE_INTERFACE_DECL, "interface") is None


# ---------------------------------------------------------------------------
# RE_COCLASS
# ---------------------------------------------------------------------------
class TestReCoclass:
    def test_matches_coclass(self) -> None:
        assert re.search(RE_COCLASS, "coclass AxisVMApplication")
        assert re.search(RE_COCLASS, "coclass FooBar")

    def test_not_match_bare(self) -> None:
        assert re.search(RE_COCLASS, "coclass") is None


# ---------------------------------------------------------------------------
# RE_METHOD_SIG
# ---------------------------------------------------------------------------
class TestReMethodSig:
    def test_matches_hr_result_not_supported(self) -> None:
        """HRESULT is NOT in RE_COM_RETURN_TYPES, so it does not match."""
        assert re.search(RE_METHOD_SIG, "HRESULT BringToFront(") is None

    def test_matches_int(self) -> None:
        assert re.search(RE_METHOD_SIG, "int GetCount(")

    def test_matches_void(self) -> None:
        assert re.search(RE_METHOD_SIG, "void Foo(")

    def test_matches_bool(self) -> None:
        assert re.search(RE_METHOD_SIG, "bool IsValid(")

    def test_matches_string(self) -> None:
        assert re.search(RE_METHOD_SIG, "string GetName(")

    def test_matches_long(self) -> None:
        assert re.search(RE_METHOD_SIG, "long GetHandle(")

    def test_matches_double(self) -> None:
        assert re.search(RE_METHOD_SIG, "double GetValue(")

    def test_matches_ELongBoolean(self) -> None:
        assert re.search(RE_METHOD_SIG, "ELongBoolean GetStatus(")

    def test_matches_E_result_type(self) -> None:
        assert re.search(RE_METHOD_SIG, "EModelResult GetResult(")

    def test_matches_IntPtr(self) -> None:
        assert re.search(RE_METHOD_SIG, "IntPtr GetPointer(")

    def test_not_match_unknown_type(self) -> None:
        assert re.search(RE_METHOD_SIG, "MyCustomType Foo(") is None

    def test_not_match_no_open_paren(self) -> None:
        assert re.search(RE_METHOD_SIG, "int foo") is None

    def test_not_match_no_space_before_name(self) -> None:
        assert re.search(RE_METHOD_SIG, "intfoo(") is None


# ---------------------------------------------------------------------------
# RE_PROPGET
# ---------------------------------------------------------------------------
class TestRePropget:
    def test_matches(self) -> None:
        assert re.search(RE_PROPGET, "[propget]")

    def test_matches_with_surrounding(self) -> None:
        assert re.search(RE_PROPGET, "[propget] HRESULT Version()")

    def test_not_match(self) -> None:
        assert re.search(RE_PROPGET, "propget") is None
        assert re.search(RE_PROPGET, "[propput]") is None
        assert re.search(RE_PROPGET, "[propget") is None


# ---------------------------------------------------------------------------
# RE_PROPPUT
# ---------------------------------------------------------------------------
class TestRePropput:
    def test_matches(self) -> None:
        assert re.search(RE_PROPPUT, "[propput]")

    def test_not_match(self) -> None:
        assert re.search(RE_PROPPUT, "propput") is None
        assert re.search(RE_PROPPUT, "[propget]") is None


# ---------------------------------------------------------------------------
# RE_PROP_ACCESSOR
# ---------------------------------------------------------------------------
class TestRePropAccessor:
    def test_matches_get(self) -> None:
        assert re.search(RE_PROP_ACCESSOR, "get_ActiveModel(")

    def test_matches_set(self) -> None:
        assert re.search(RE_PROP_ACCESSOR, "set_ActiveModel(")

    def test_not_match_without_underscore(self) -> None:
        assert re.search(RE_PROP_ACCESSOR, "getActiveModel(") is None

    def test_not_match_no_paren(self) -> None:
        assert re.search(RE_PROP_ACCESSOR, "get_Foo") is None


# ---------------------------------------------------------------------------
# RE_PROP_SYNTAX
# ---------------------------------------------------------------------------
class TestRePropSyntax:
    def test_matches_get_set(self) -> None:
        assert re.search(RE_PROP_SYNTAX, "{ get; set; }")

    def test_matches_get_only(self) -> None:
        assert re.search(RE_PROP_SYNTAX, "{ get; }")

    def test_matches_with_surrounding(self) -> None:
        assert re.search(RE_PROP_SYNTAX, "string Name { get; set; }")

    def test_matches_without_spaces(self) -> None:
        assert re.search(RE_PROP_SYNTAX, "{get;set;}")

    def test_not_match_no_semicolons(self) -> None:
        assert re.search(RE_PROP_SYNTAX, "{ get set }") is None


# ---------------------------------------------------------------------------
# RE_ENUM_DECL
# ---------------------------------------------------------------------------
class TestReEnumDecl:
    def test_matches(self) -> None:
        assert re.search(RE_ENUM_DECL, "enum EModelType {")
        assert re.search(RE_ENUM_DECL, "enum EFoo {")

    def test_not_match_no_E_prefix(self) -> None:
        assert re.search(RE_ENUM_DECL, "enum ModelType {") is None
        assert re.search(RE_ENUM_DECL, "enum Foo {") is None

    def test_not_match_no_brace(self) -> None:
        assert re.search(RE_ENUM_DECL, "enum EModelType") is None


# ---------------------------------------------------------------------------
# RE_RECORD_DECL
# ---------------------------------------------------------------------------
class TestReRecordDecl:
    def test_matches_readonly_record_struct(self) -> None:
        assert re.search(RE_RECORD_DECL, "readonly record struct RModelData")

    def test_matches_record_only(self) -> None:
        assert re.search(RE_RECORD_DECL, "record RModelData")

    def test_matches_record_struct(self) -> None:
        assert re.search(RE_RECORD_DECL, "record struct RSomeData")

    def test_not_match_no_R_prefix(self) -> None:
        assert re.search(RE_RECORD_DECL, "record ModelData") is None

    def test_not_match_bare_record(self) -> None:
        assert re.search(RE_RECORD_DECL, "record") is None


# ---------------------------------------------------------------------------
# RE_STRUCT_DECL
# ---------------------------------------------------------------------------
class TestReStructDecl:
    def test_matches(self) -> None:
        assert re.search(RE_STRUCT_DECL, "struct SomeStruct")
        assert re.search(RE_STRUCT_DECL, "struct Foo")

    def test_matches_readonly(self) -> None:
        assert re.search(RE_STRUCT_DECL, "readonly struct Bar")

    def test_matches_public_readonly(self) -> None:
        assert re.search(RE_STRUCT_DECL, "public readonly struct Baz")

    def test_not_match_bare_struct(self) -> None:
        assert re.search(RE_STRUCT_DECL, "struct") is None


# ---------------------------------------------------------------------------
# RE_ERROR_ENUM
# ---------------------------------------------------------------------------
class TestReErrorEnum:
    def test_matches_error_suffix(self) -> None:
        assert re.search(RE_ERROR_ENUM, "enum EApplicationErrors {")

    def test_matches_warning_suffix(self) -> None:
        assert re.search(RE_ERROR_ENUM, "enum EModuleWarnings {")

    def test_matches_code_suffix(self) -> None:
        assert re.search(RE_ERROR_ENUM, "enum EReturnCodes {")

    def test_matches_singular_error(self) -> None:
        assert re.search(RE_ERROR_ENUM, "enum EApplicationError {")

    def test_not_match_other_enum(self) -> None:
        assert re.search(RE_ERROR_ENUM, "enum EModelType {") is None

    def test_not_match_no_E_prefix(self) -> None:
        assert re.search(RE_ERROR_ENUM, "enum Errors {") is None


# ---------------------------------------------------------------------------
# RE_GENERIC_FUNC
# ---------------------------------------------------------------------------
class TestReGenericFunc:
    def test_matches_def(self) -> None:
        assert re.search(RE_GENERIC_FUNC, "def foo(")

    def test_matches_function(self) -> None:
        assert re.search(RE_GENERIC_FUNC, "function foo(")

    def test_matches_lambda_arrow(self) -> None:
        assert re.search(RE_GENERIC_FUNC, "=>")

    def test_matches_public_return_type(self) -> None:
        assert re.search(RE_GENERIC_FUNC, "public void Foo(")
        assert re.search(RE_GENERIC_FUNC, "private int Bar(")
        assert re.search(RE_GENERIC_FUNC, "protected string Baz(")

    def test_not_match_regular_text(self) -> None:
        assert re.search(RE_GENERIC_FUNC, "void foo(") is None

    def test_not_match_empty(self) -> None:
        assert re.search(RE_GENERIC_FUNC, "") is None


# ---------------------------------------------------------------------------
# RE_GENERIC_CLASS
# ---------------------------------------------------------------------------
class TestReGenericClass:
    def test_matches_class(self) -> None:
        assert re.search(RE_GENERIC_CLASS, "class Foo")

    def test_matches_interface(self) -> None:
        assert re.search(RE_GENERIC_CLASS, "interface IBar")
        assert re.search(RE_GENERIC_CLASS, "interface IAxisVMApplication")

    def test_not_match_no_name(self) -> None:
        assert re.search(RE_GENERIC_CLASS, "class") is None
        assert re.search(RE_GENERIC_CLASS, "interface") is None

    def test_not_match_interface_with_lowercase_i(self) -> None:
        assert re.search(RE_GENERIC_CLASS, "interface Bar") is None
