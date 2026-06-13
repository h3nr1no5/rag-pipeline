RE_COM_IMPORT = r"\[ComImport\]"
RE_GUID = r"\[Guid\([^)]*\)\]"
RE_INTERFACE_TYPE = r"\[InterfaceType\([^)]*\)\]"
RE_DLL_IMPORT = r"\[DllImport\([^)]*\)\]"
RE_INTERFACE_DECL = r"interface\s+I\w+"
RE_COCLASS = r"coclass\s+\w+"

RE_COM_RETURN_TYPES = (
    r"(long|void|int|bool|double|string|ELongBoolean|E[\w]+Result|"
    r"short|byte|float|uint|ulong|HWND|IntPtr|object|char|decimal|"
    r"sbyte|ushort|SafeArray|Array|DateTime|Guid|Variant|dynamic|"
    r"string\[\]|byte\[\]|int\[\]|long\[\]|double\[\]|float\[\])"
)
RE_METHOD_SIG = rf"\b{RE_COM_RETURN_TYPES}\s+\w+\s*\("

RE_PROPGET = r"\[propget\]"
RE_PROPPUT = r"\[propput\]"
RE_PROP_ACCESSOR = r"\b(get_|set_)\w+\s*\("
RE_PROP_SYNTAX = r"\{\s*(get|set)\s*(;\s*(get|set)\s*)?;\s*\}"

RE_ENUM_DECL = r"enum\s+E\w+\s*\{"
RE_RECORD_DECL = r"(readonly\s+)?record\s+(struct\s+)?R\w+"
RE_STRUCT_DECL = r"(readonly\s+)?struct\s+\w+"
RE_ERROR_ENUM = r"enum\s+E\w+(Error|Warning|Code)s?\s*\{"

RE_GENERIC_FUNC = r"(def\s+|function\s+|=>|(public|private|protected)\s+\w+\s+\w+\s*\()"
RE_GENERIC_CLASS = r"(class\s+\w+|interface\s+I\w+)"
