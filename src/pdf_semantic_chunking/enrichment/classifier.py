import re

from .model import ComDocumentElement, ComElementType

METHOD_SIG_PATTERN = re.compile(
    r"\b(long|void|int|bool|double|string|short|byte|float|uint|ulong|ELongBoolean|"
    r"E[\w]+Result|HWND|IntPtr|object|char|decimal|sbyte|ushort|uint|ulong|"
    r"SafeArray|Array|DateTime|Guid|Variant|object|dynamic)\s+\w+\s*\("
)

PROPGET_ATTR_PATTERN = re.compile(r"\[propget\]")
PROPPUT_ATTR_PATTERN = re.compile(r"\[propput\]")
PROP_ACCESSOR_PATTERN = re.compile(r"\b(get_|set_)\w+\s*\(")
PROP_SYNTAX_PATTERN = re.compile(r"\{\s*(get|set)\s*(;\s*(get|set)\s*)?;\s*\}")

ENUM_PATTERN = re.compile(r"(public\s+)?enum\s+E\w+\s*\{")
ENUM_MEMBER_PATTERN = re.compile(r"^\s*(\w+)\s*(=\s*([^,}]+))?,?\s*$", re.MULTILINE)

RECORD_PATTERN = re.compile(
    r"(public\s+)?(readonly\s+)?record\s+(struct\s+)?(class\s+)?R\w+"
)
STRUCT_PATTERN = re.compile(r"(public\s+)?(readonly\s+)?struct\s+\w+")
RECORD_PARAMS_PATTERN = re.compile(r"\(([^)]*)\)")

ERROR_CODE_PATTERN = re.compile(
    r"(public\s+)?enum\s+E\w+(Error|Warning|Code)s?\s*\{"
)
ERROR_MEMBER_PATTERN = re.compile(r"err\w+")


class ElementClassifier:
    def classify(self, element: ComDocumentElement) -> ComElementType | None:
        content = element.content

        if ERROR_CODE_PATTERN.search(content):
            return "COM_ERROR_CODE"

        if ENUM_PATTERN.search(content):
            return "COM_ENUM"

        if RECORD_PATTERN.search(content) or STRUCT_PATTERN.search(content):
            return "COM_RECORD"

        if PROPGET_ATTR_PATTERN.search(content) or PROPPUT_ATTR_PATTERN.search(content):
            return "COM_PROPERTY"

        if PROP_SYNTAX_PATTERN.search(content):
            return "COM_PROPERTY"

        if PROP_ACCESSOR_PATTERN.search(content):
            return "COM_PROPERTY"

        if METHOD_SIG_PATTERN.search(content):
            return "COM_METHOD"

        return None

    def extract_element_name(self, element: ComDocumentElement, com_type: ComElementType) -> str | None:
        content = element.content
        if com_type == "COM_ENUM":
            m = re.search(r"enum\s+(E\w+)", content)
            if m:
                return m.group(1)
        elif com_type == "COM_RECORD":
            m = re.search(r"(?:record|struct)\s+(R?\w+)", content)
            if m:
                return m.group(1)
        elif com_type == "COM_ERROR_CODE":
            m = re.search(r"enum\s+(E\w+)", content)
            if m:
                return m.group(1)
        elif com_type == "COM_METHOD":
            m = re.search(r"\b(long|void|int|bool|double|string|ELongBoolean|E[\w]+Result|"
                          r"short|byte|float|uint|ulong|HWND|IntPtr|object|char|decimal|"
                          r"sbyte|ushort|SafeArray|Array|DateTime|Guid|Variant|dynamic|"
                          r"string\[\]|byte\[\]|int\[\]|long\[\]|double\[\]|float\[\])\s+(\w+)\s*\(",
                          content)
            if m:
                return m.group(2)
        elif com_type == "COM_PROPERTY":
            m = re.search(r"\b(get_|set_)(\w+)", content)
            if m:
                return m.group(2)
            m = re.search(r"\b(\w+)\s*\{\s*(get|set)", content)
            if m:
                return m.group(1)
        return None

    def extract_return_type(self, element: ComDocumentElement, com_type: ComElementType) -> str | None:
        if com_type == "COM_METHOD":
            m = re.search(r"\b(long|void|int|bool|double|string|ELongBoolean|E[\w]+Result|"
                          r"short|byte|float|uint|ulong|HWND|IntPtr|object|char|decimal|"
                          r"sbyte|ushort|SafeArray|Array|DateTime|Guid|Variant|dynamic|"
                          r"string\[\]|byte\[\]|int\[\]|long\[\]|double\[\]|float\[\])\s+\w+\s*\(",
                          element.content)
            if m:
                return m.group(1)
        elif com_type == "COM_PROPERTY":
            m = re.search(r"\b(long|void|int|bool|double|string|ELongBoolean|E[\w]+Result|"
                          r"short|byte|float|uint|ulong|HWND|IntPtr|object|char|decimal|"
                          r"sbyte|ushort|SafeArray|Array|DateTime|Guid|Variant|dynamic"
                          r")\s+(get_|set_|(\w+)\s*\{)", element.content)
            if m:
                return m.group(1)
        return None
