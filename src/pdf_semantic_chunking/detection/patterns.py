import re
from typing import NamedTuple


class PatternEntry(NamedTuple):
    name: str
    pattern: str
    priority: int


class PatternRegistry:
    def __init__(self):
        self._entries: list[PatternEntry] = []

    def register(self, name: str, pattern: str, priority: int = 0) -> None:
        self._entries.append(PatternEntry(name, pattern, priority))
        self._entries.sort(key=lambda e: e.priority, reverse=True)

    def get_patterns(self, min_priority: int = -999) -> list[PatternEntry]:
        return [e for e in self._entries if e.priority >= min_priority]

    def get_compiled(self, min_priority: int = -999) -> list[tuple[str, re.Pattern, int]]:
        return [
            (e.name, re.compile(e.pattern, re.MULTILINE), e.priority)
            for e in self._entries
            if e.priority >= min_priority
        ]

    def match_any(self, text: str, min_priority: int = -999) -> list[str]:
        matched: list[str] = []
        for name, pat, prio in self.get_compiled(min_priority=min_priority):
            if pat.search(text):
                matched.append(name)
        return matched

    @classmethod
    def create_default(cls) -> "PatternRegistry":
        registry = cls()
        registry.register("com_import", r"\[ComImport\]", priority=100)
        registry.register("guid_attr", r"\[Guid\([^)]*\)\]", priority=100)
        registry.register("interface_type", r"\[InterfaceType\([^)]*\)\]", priority=100)
        registry.register("dll_import", r"\[DllImport\([^)]*\)\]", priority=100)
        registry.register("interface_decl", r"interface\s+I\w+", priority=90)
        registry.register("coclass", r"coclass\s+\w+", priority=90)
        registry.register("com_return_types", (
            r"\b(long|void|int|bool|double|string|ELongBoolean|E[\w]+Result|"
            r"short|byte|float|uint|ulong|HWND|IntPtr|object|char|decimal|"
            r"sbyte|ushort|SafeArray|Array|DateTime|Guid|Variant)\s+\w+\s*\("
        ), priority=80)
        registry.register("generic_func", r"(def\s+|function\s+|=>)", priority=70)
        registry.register("generic_class", r"(class\s+\w+|interface\s+I\w+)", priority=70)
        registry.register("access_modifier", r"(public|private|protected)\s+\w+\s+\w+\s*\(", priority=70)
        registry.register("heading_marker", r"^(#{1,6}\s)", priority=60)
        registry.register("code_marker", r"```", priority=60)
        return registry
