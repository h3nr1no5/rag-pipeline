from pydantic import BaseModel


class APIParameter(BaseModel):
    name: str
    type_annotation: str = ""
    description: str = ""
    optional: bool = False
    default_value: str | None = None


class APIFunction(BaseModel):
    name: str
    return_type: str = ""
    parameters: list[APIParameter] = []
    description: str = ""
    parent_interface: str | None = None


class APIProperty(BaseModel):
    name: str
    type_annotation: str = ""
    access: str = ""
    description: str = ""
    parent_interface: str | None = None


class APIInterface(BaseModel):
    name: str
    guid: str | None = None
    base_interface: str | None = None
    methods: list[APIFunction] = []
    properties: list[APIProperty] = []
    description: str = ""


class APIEnum(BaseModel):
    name: str
    values: list["APIEnumValue"] = []
    description: str = ""
    parent_interface: str | None = None


class APIEnumValue(BaseModel):
    name: str
    value: int | str | None = None
    description: str = ""


class APIErrorCode(BaseModel):
    name: str
    code: int | str | None = None
    description: str = ""
    parent_interface: str | None = None


class APIRecordField(BaseModel):
    name: str
    type_annotation: str = ""
    description: str = ""


class APIRecord(BaseModel):
    name: str
    fields: list[APIRecordField] = []
    description: str = ""
    parent_interface: str | None = None
