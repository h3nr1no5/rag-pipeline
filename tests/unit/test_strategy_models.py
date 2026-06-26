"""Unit tests for strategy config schema models and APIRecord models.

Task 9.5 — Pydantic models: ParamInfo, StrategyTypeInfo, StrategyTypesResponse
Task 9.6 — APIRecordField and APIRecord domain models
"""

import json

from src.api.schemas.document import (
    STRATEGY_TYPE_SCHEMAS,
    ParamInfo,
    StrategyTypeInfo,
    StrategyTypesResponse,
)
from src.domain.rag.api_docs.model.models import APIRecord, APIRecordField

# ---------------------------------------------------------------------------
# Task 9.5 — Strategy config schema models
# ---------------------------------------------------------------------------


class TestParamInfo:
    """ParamInfo model serialization and defaults."""

    def test_basic_creation(self):
        p = ParamInfo(type="integer", default=100, description="Max size")
        assert p.type == "integer"
        assert p.default == 100
        assert p.description == "Max size"
        assert p.items is None
        assert p.enum is None
        assert p.nullable is False

    def test_with_items(self):
        p = ParamInfo(type="array", items="string", default=["a", "b"])
        assert p.items == "string"

    def test_with_enum(self):
        p = ParamInfo(type="string", enum=["detailed", "compact"])
        assert p.enum == ["detailed", "compact"]

    def test_nullable(self):
        p = ParamInfo(type="array", items="string", nullable=True)
        assert p.nullable is True

    def test_serialization_roundtrip(self):
        p = ParamInfo(type="integer", default=20, description="Min length")
        data = json.loads(p.model_dump_json())
        restored = ParamInfo.model_validate(data)
        assert restored.type == "integer"
        assert restored.default == 20
        assert restored.description == "Min length"


class TestStrategyTypeInfo:
    """StrategyTypeInfo model."""

    def test_with_params(self):
        info = StrategyTypeInfo(
            params={
                "chunk_size": ParamInfo(type="integer", default=1000),
                "separators": ParamInfo(type="array", items="string"),
            }
        )
        assert info.params is not None
        assert "chunk_size" in info.params
        assert info.params["chunk_size"].default == 1000

    def test_with_config_schema(self):
        info = StrategyTypeInfo(
            config_schema={
                "max_depth": ParamInfo(type="integer", default=3),
            }
        )
        assert info.config_schema is not None
        assert info.config_schema["max_depth"].default == 3

    def test_both_none(self):
        info = StrategyTypeInfo()
        assert info.params is None
        assert info.config_schema is None

    def test_serialization_roundtrip(self):
        info = StrategyTypeInfo(
            params={"size": ParamInfo(type="integer", default=100)},
        )
        data = json.loads(info.model_dump_json())
        restored = StrategyTypeInfo.model_validate(data)
        assert restored.params is not None
        assert restored.params["size"].default == 100


class TestStrategyTypesResponse:
    """StrategyTypesResponse wraps a dict of StrategyTypeInfo."""

    def test_contains_three_types(self):
        response = StrategyTypesResponse(types=STRATEGY_TYPE_SCHEMAS)
        assert "recursive" in response.types
        assert "semantic" in response.types
        assert "api-docs" in response.types

    def test_recursive_has_params(self):
        response = StrategyTypesResponse(types=STRATEGY_TYPE_SCHEMAS)
        recursive = response.types["recursive"]
        assert recursive.params is not None
        assert "chunk_size" in recursive.params
        assert recursive.params["chunk_size"].type == "integer"
        assert recursive.params["chunk_size"].default == 1000

    def test_semantic_has_params(self):
        response = StrategyTypesResponse(types=STRATEGY_TYPE_SCHEMAS)
        semantic = response.types["semantic"]
        assert semantic.params is not None
        assert "min_chunk_length" in semantic.params
        assert "use_hyperlinks" in semantic.params

    def test_api_docs_has_config_schema(self):
        response = StrategyTypesResponse(types=STRATEGY_TYPE_SCHEMAS)
        api_docs = response.types["api-docs"]
        assert api_docs.config_schema is not None
        assert "max_depth" in api_docs.config_schema
        assert "format_style" in api_docs.config_schema
        assert "include_signatures" in api_docs.config_schema
        assert "include_descriptions" in api_docs.config_schema
        assert "min_chunk_length" in api_docs.config_schema

    def test_serialization_roundtrip(self):
        response = StrategyTypesResponse(types=STRATEGY_TYPE_SCHEMAS)
        data = json.loads(response.model_dump_json())
        restored = StrategyTypesResponse.model_validate(data)
        assert set(restored.types.keys()) == {"recursive", "semantic", "api-docs"}


# ---------------------------------------------------------------------------
# Task 9.6 — APIRecordField and APIRecord domain models
# ---------------------------------------------------------------------------


class TestAPIRecordField:
    """APIRecordField model creation and field access."""

    def test_basic_creation(self):
        field = APIRecordField(
            name="Id",
            type_annotation="int",
            description="Unique identifier",
        )
        assert field.name == "Id"
        assert field.type_annotation == "int"
        assert field.description == "Unique identifier"

    def test_default_values(self):
        field = APIRecordField(name="Name")
        assert field.type_annotation == ""
        assert field.description == ""

    def test_serialization_roundtrip(self):
        field = APIRecordField(
            name="Count",
            type_annotation="int",
            description="Number of items",
        )
        data = json.loads(field.model_dump_json())
        restored = APIRecordField.model_validate(data)
        assert restored.name == "Count"
        assert restored.type_annotation == "int"


class TestAPIRecord:
    """APIRecord model creation and field access."""

    def test_basic_creation(self):
        record = APIRecord(
            name="MyRecord",
            fields=[
                APIRecordField(name="Id", type_annotation="int"),
                APIRecordField(name="Name", type_annotation="string"),
            ],
            description="A test record",
        )
        assert record.name == "MyRecord"
        assert len(record.fields) == 2
        assert record.fields[0].name == "Id"
        assert record.description == "A test record"

    def test_default_fields_list(self):
        record = APIRecord(name="EmptyRecord")
        assert record.fields == []
        assert record.description == ""

    def test_parent_interface_assignment(self):
        record = APIRecord(
            name="NestedRecord",
            fields=[APIRecordField(name="X", type_annotation="int")],
            parent_interface="IInterface",
        )
        assert record.parent_interface == "IInterface"

    def test_parent_interface_default_none(self):
        record = APIRecord(name="Record")
        assert record.parent_interface is None

    def test_serialization_roundtrip(self):
        record = APIRecord(
            name="TestRecord",
            fields=[
                APIRecordField(name="A", type_annotation="string"),
            ],
            parent_interface="IFoo",
        )
        data = json.loads(record.model_dump_json())
        restored = APIRecord.model_validate(data)
        assert restored.name == "TestRecord"
        assert len(restored.fields) == 1
        assert restored.fields[0].name == "A"
        assert restored.parent_interface == "IFoo"
