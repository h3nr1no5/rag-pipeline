import re
import logging
from typing import Optional

from .model import ComDocumentElement, ComElementType
from .interface_detector import InterfaceDetector
from .classifier import ElementClassifier
from .parameter_extractor import ParameterExtractor
from ..extraction.model import DocumentElement, DocumentHierarchy

logger = logging.getLogger(__name__)


class EnumMemberExtractor:
    def extract(self, element: ComDocumentElement) -> list[dict]:
        content = element.content
        members: list[dict] = []
        brace_start = content.find("{")
        brace_end = content.rfind("}")
        if brace_start == -1 or brace_end == -1 or brace_end <= brace_start:
            return members
        body = content[brace_start + 1:brace_end]
        for line in body.split("\n"):
            line = line.strip().rstrip(",")
            if not line:
                continue
            m = re.match(r"^(\w+)\s*=\s*([^,]+)", line)
            if m:
                members.append({"name": m.group(1), "value": m.group(2).strip()})
                continue
            m = re.match(r"^(\w+)$", line)
            if m:
                members.append({"name": m.group(1), "value": None})
        return members


class ErrorCodeGrouper:
    def group(self, element: ComDocumentElement) -> list[str]:
        content = element.content
        members = re.findall(r"err\w+", content)
        return members


class COMEnricher:
    def __init__(self):
        self.interface_detector = InterfaceDetector()
        self.classifier = ElementClassifier()
        self.parameter_extractor = ParameterExtractor()
        self.enum_extractor = EnumMemberExtractor()
        self.error_code_grouper = ErrorCodeGrouper()

    def enrich(self, hierarchy: DocumentHierarchy) -> DocumentHierarchy:
        enriched_root = ComDocumentElement(
            type="PAGE", content="", metadata={"name": "enriched_root"}
        )
        flat = hierarchy.flatten_depth_first()
        current_interface: Optional[ComDocumentElement] = None
        sections: dict[str, list[ComDocumentElement]] = {}
        interface_name: Optional[str] = None

        for element in flat:
            com_el = self._convert_to_com(element)
            if self.interface_detector.detect_interface_boundary(com_el):
                if current_interface is not None and sections:
                    self._finalize_interface(current_interface, sections)
                    enriched_root.add_child(current_interface)
                    current_interface = None
                    sections = {}
                interface_name = self.interface_detector.extract_interface_name(com_el)
                current_interface = ComDocumentElement(
                    type="SECTION",
                    content="",
                    metadata={"element_name": interface_name or "unknown"},
                    com_type="COM_INTERFACE",
                    element_name=interface_name,
                    com_confidence=self.interface_detector.compute_confidence(com_el),
                )
                current_interface.add_child(com_el)
                interface_name = None
                continue

            com_type = self.classifier.classify(com_el)
            if com_type:
                element_name = self.classifier.extract_element_name(com_el, com_type)
                return_type = self.classifier.extract_return_type(com_el, com_type)
                signature = self._reconstruct_signature(com_el)
                com_el.com_type = com_type
                com_el.element_name = element_name
                com_el.return_type = return_type
                com_el.signature = signature
                com_el.com_confidence = 0.8

                if com_type == "COM_METHOD":
                    params = self.parameter_extractor.extract_from_signature(signature or "")
                    desc = self._get_adjacent_description(com_el, flat)
                    params = self.parameter_extractor.associate_descriptions(params, desc)
                    com_el.parameters = params

                if com_type == "COM_ENUM":
                    com_el.enum_members = self.enum_extractor.extract(com_el)

                if com_type == "COM_ERROR_CODE":
                    com_el.error_codes = self.error_code_grouper.group(com_el)

                com_el.keywords = self._extract_keywords(com_el)

                section_name = self._get_section_name(com_type)
                if section_name:
                    sections.setdefault(section_name, []).append(com_el)

                if current_interface is not None:
                    current_interface.add_child(com_el)
                else:
                    enriched_root.add_child(com_el)
            else:
                com_el.com_confidence = 0.0
                if current_interface is not None:
                    current_interface.add_child(com_el)
                else:
                    enriched_root.add_child(com_el)

        if current_interface is not None and sections:
            self._finalize_interface(current_interface, sections)
            enriched_root.add_child(current_interface)

        return DocumentHierarchy(root=enriched_root)

    def _convert_to_com(self, element: DocumentElement) -> ComDocumentElement:
        return ComDocumentElement(
            type=element.type,
            content=element.content,
            metadata=element.metadata,
            children=[self._convert_to_com(c) for c in element.children],
            bbox=element.bbox,
            confidence=element.confidence,
        )

    def _reconstruct_signature(self, element: ComDocumentElement) -> Optional[str]:
        content = element.content
        lines = content.split("\n")
        sig_lines: list[str] = []
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                if sig_lines:
                    break
                continue
            if sig_lines and stripped.startswith(("(", "public", "private", "protected")):
                sig_lines.append(stripped)
            elif re.search(r"\b(long|void|int|bool|double|string|ELongBoolean|E[\w]+Result|"
                           r"short|byte|float|uint|ulong|HWND|IntPtr|object|char|decimal|"
                           r"sbyte|ushort|SafeArray|Array|DateTime|Guid|Variant|dynamic)\s+",
                           stripped):
                sig_lines.append(stripped)
            elif sig_lines and "(" in stripped:
                sig_lines.append(stripped)
            elif re.match(r"\[\w", stripped) and not sig_lines:
                sig_lines.append(stripped)
            elif sig_lines:
                break
        return " ".join(sig_lines) if sig_lines else None

    def _get_adjacent_description(self, element: ComDocumentElement, flat: list[DocumentElement]) -> str:
        return ""

    def _get_section_name(self, com_type: ComElementType) -> str:
        mapping = {
            "COM_METHOD": "Functions",
            "COM_PROPERTY": "Properties",
            "COM_ENUM": "Enumerated types",
            "COM_RECORD": "Records / structures",
            "COM_ERROR_CODE": "Error codes",
        }
        return mapping.get(com_type, "Other")

    def _finalize_interface(
        self, interface: ComDocumentElement, sections: dict[str, list[ComDocumentElement]]
    ) -> None:
        pass

    def _extract_keywords(self, element: ComDocumentElement) -> list[str]:
        keywords: list[str] = []
        name = element.element_name or ""
        parts = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)", name)
        keywords.extend(p.lower() for p in parts if len(p) > 1)
        return keywords
