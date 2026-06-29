import re

from .model import ComDocumentElement

INTERFACE_ATTR_PATTERN = re.compile(
    r"\[(ComImport|Guid\([^)]*\)|InterfaceType\([^)]*\)|DllImport\([^)]*\))\]"
)
INTERFACE_DECL_PATTERN = re.compile(
    r"(public\s+)?(partial\s+)?interface\s+I\w+"
)
COCLASS_PATTERN = re.compile(r"(public\s+)?coclass\s+\w+")


class InterfaceDetector:
    def detect_interface_boundary(self, element: ComDocumentElement) -> bool:
        content = element.content
        has_interface_decl = bool(INTERFACE_DECL_PATTERN.search(content))
        has_coclass = bool(COCLASS_PATTERN.search(content))
        if has_interface_decl or has_coclass:
            return True
        return False

    def extract_interface_name(self, element: ComDocumentElement) -> str | None:
        m = INTERFACE_DECL_PATTERN.search(element.content)
        if m:
            parts = m.group(0).split()
            for p in parts:
                if p.startswith("I") and len(p) > 1 and p[1].isupper():
                    return p
        m = COCLASS_PATTERN.search(element.content)
        if m:
            parts = m.group(0).split()
            return parts[-1]
        return None

    def compute_confidence(self, element: ComDocumentElement) -> float:
        content = element.content
        score = 0.0
        if "[ComImport]" in content:
            score += 0.4
        if re.search(r"\[Guid\([^)]*\)\]", content):
            score += 0.3
        if re.search(r"\[InterfaceType\([^)]*\)\]", content):
            score += 0.3
        return min(score, 1.0)
