"""Unit tests for API documentation domain model validation.

Task 9.1 — Tests model creation, defaults, optional fields, serialization.
"""

from src.domain.rag.api_docs.model.models import (
    APIEnum,
    APIEnumValue,
    APIErrorCode,
    APIFunction,
    APIInterface,
    APIParameter,
    APIProperty,
)

# ---------------------------------------------------------------------------
# APIParameter
# ---------------------------------------------------------------------------

def test_api_parameter_valid():
    """Create APIParameter with all fields populated."""
    param = APIParameter(
        name="x",
        type_annotation="double",
        description="The x coordinate",
        optional=True,
        default_value="0.0",
    )
    assert param.name == "x"
    assert param.type_annotation == "double"
    assert param.description == "The x coordinate"
    assert param.optional is True
    assert param.default_value == "0.0"


def test_api_parameter_empty_type_annotation_defaults():
    """APIParameter without type_annotation should default to empty string."""
    param = APIParameter(name="y")
    assert param.name == "y"
    assert param.type_annotation == ""
    assert param.description == ""
    assert param.optional is False
    assert param.default_value is None


def test_api_parameter_none_default_value():
    """APIParameter can have None default_value."""
    param = APIParameter(name="z", type_annotation="int", default_value=None)
    assert param.default_value is None


def test_api_parameter_serialization_roundtrip():
    """model_dump() -> model_validate() round-trip preserves data."""
    param = APIParameter(
        name="count",
        type_annotation="int",
        description="Number of items",
        optional=True,
        default_value="42",
    )
    data = param.model_dump()
    restored = APIParameter.model_validate(data)
    assert restored == param
    assert restored.name == "count"
    assert restored.default_value == "42"


# ---------------------------------------------------------------------------
# APIFunction
# ---------------------------------------------------------------------------

def test_api_function_empty_parameters():
    """APIFunction with an empty parameters list."""
    func = APIFunction(name="DoSomething", return_type="void")
    assert func.name == "DoSomething"
    assert func.parameters == []
    assert func.return_type == "void"
    assert func.description == ""
    assert func.parent_interface is None


def test_api_function_with_parameters():
    """APIFunction with multiple APIParameters."""
    params = [
        APIParameter(name="a", type_annotation="int"),
        APIParameter(name="b", type_annotation="str", optional=True),
    ]
    func = APIFunction(
        name="Add",
        return_type="int",
        parameters=params,
        description="Adds two values",
        parent_interface="ICalculator",
    )
    assert func.name == "Add"
    assert len(func.parameters) == 2
    assert func.parameters[0].name == "a"
    assert func.parameters[1].name == "b"
    assert func.parent_interface == "ICalculator"


def test_api_function_serialization_roundtrip():
    """APIFunction serialization round-trip."""
    func = APIFunction(
        name="CreateNode",
        return_type="INode",
        parameters=[APIParameter(name="id", type_annotation="guid")],
        description="Creates a new node",
    )
    data = func.model_dump()
    restored = APIFunction.model_validate(data)
    assert restored == func
    assert restored.parameters[0].name == "id"


# ---------------------------------------------------------------------------
# APIInterface
# ---------------------------------------------------------------------------

def test_api_interface_with_methods_and_properties():
    """APIInterface with methods and properties."""
    iface = APIInterface(
        name="INode",
        guid="{00000000-0000-0000-0000-000000000001}",
        base_interface="IUnknown",
        methods=[
            APIFunction(name="AddRef", return_type="ulong"),
            APIFunction(name="Release", return_type="ulong"),
        ],
        properties=[
            APIProperty(name="Name", type_annotation="string", access="read"),
        ],
        description="Base node interface",
    )
    assert iface.name == "INode"
    assert iface.guid == "{00000000-0000-0000-0000-000000000001}"
    assert iface.base_interface == "IUnknown"
    assert len(iface.methods) == 2
    assert len(iface.properties) == 1
    assert iface.properties[0].name == "Name"


def test_api_interface_empty():
    """APIInterface with no methods or properties."""
    iface = APIInterface(name="IEmpty")
    assert iface.methods == []
    assert iface.properties == []
    assert iface.description == ""
    assert iface.guid is None


def test_api_interface_serialization_roundtrip():
    """APIInterface serialization round-trip."""
    iface = APIInterface(
        name="IFileDialog",
        methods=[
            APIFunction(name="Show", return_type="HRESULT",
                        parameters=[APIParameter(name="hwnd", type_annotation="HWND")]),
        ],
        properties=[
            APIProperty(name="FileName", type_annotation="string", access="read"),
        ],
    )
    data = iface.model_dump()
    restored = APIInterface.model_validate(data)
    assert restored == iface
    assert restored.methods[0].name == "Show"
    assert restored.properties[0].name == "FileName"


# ---------------------------------------------------------------------------
# APIProperty
# ---------------------------------------------------------------------------

def test_api_property_defaults():
    """APIProperty with minimal fields."""
    prop = APIProperty(name="Value")
    assert prop.type_annotation == ""
    assert prop.access == ""
    assert prop.description == ""
    assert prop.parent_interface is None


# ---------------------------------------------------------------------------
# APIEnum / APIEnumValue
# ---------------------------------------------------------------------------

def test_api_enum_with_values():
    """APIEnum with a list of APIEnumValue items."""
    values = [
        APIEnumValue(name="None", value=0, description="No value"),
        APIEnumValue(name="Some", value=1),
        APIEnumValue(name="All", value=2, description="All values"),
    ]
    enum = APIEnum(name="MyEnum", values=values, description="Test enum")
    assert enum.name == "MyEnum"
    assert len(enum.values) == 3
    assert enum.values[0].name == "None"
    assert enum.values[0].value == 0
    assert enum.values[2].description == "All values"


def test_api_enum_value_string_value():
    """APIEnumValue can have a string value."""
    val = APIEnumValue(name="Error", value="ERR_BAD_INPUT")
    assert val.value == "ERR_BAD_INPUT"


def test_api_enum_value_none_value():
    """APIEnumValue can have None value."""
    val = APIEnumValue(name="Default", value=None)
    assert val.value is None


def test_api_enum_serialization_roundtrip():
    """APIEnum serialization round-trip."""
    enum = APIEnum(
        name="StatusCode",
        values=[
            APIEnumValue(name="OK", value=200),
            APIEnumValue(name="NotFound", value=404),
        ],
    )
    data = enum.model_dump()
    restored = APIEnum.model_validate(data)
    assert restored == enum


# ---------------------------------------------------------------------------
# APIErrorCode
# ---------------------------------------------------------------------------

def test_api_error_code_int():
    """APIErrorCode with int code."""
    ec = APIErrorCode(name="E_INVALIDARG", code=0x80070057, description="Invalid argument")
    assert ec.name == "E_INVALIDARG"
    assert ec.code == 0x80070057


def test_api_error_code_str():
    """APIErrorCode with str code."""
    ec = APIErrorCode(name="S_OK", code="0x00000000")
    assert ec.code == "0x00000000"


def test_api_error_code_none_code():
    """APIErrorCode with None code."""
    ec = APIErrorCode(name="E_FAIL")
    assert ec.code is None


def test_api_error_code_serialization_roundtrip():
    """APIErrorCode serialization round-trip."""
    ec = APIErrorCode(name="E_POINTER", code=0x80004003, description="Null pointer")
    data = ec.model_dump()
    restored = APIErrorCode.model_validate(data)
    assert restored == ec
