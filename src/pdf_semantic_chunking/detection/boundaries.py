from __future__ import annotations

import re
import logging
from typing import Optional, Callable

from ..extraction.model import DocumentElement, DocumentHierarchy

logger = logging.getLogger(__name__)

BoundaryMarker = tuple[int, str, float]  # (element_index, boundary_type, priority)


class HeadingBoundaryDetector:
    def detect(self, flat: list[DocumentElement]) -> list[BoundaryMarker]:
        markers: list[BoundaryMarker] = []
        for i, el in enumerate(flat):
            if el.type == "HEADING":
                font_size = el.metadata.get("font_size", 0)
                content = el.content.strip()
                if content.startswith("#"):
                    hashes = len(content.split()[0]) if content.split() else 0
                    if hashes <= 2:
                        markers.append((i, "heading", 90.0))
                elif font_size > 18:
                    markers.append((i, "heading", 90.0))
                elif font_size > 14:
                    markers.append((i, "heading", 80.0))
        return markers


class FunctionSignatureDetector:
    def __init__(self):
        self._patterns = [
            (r"\b(long|void|int|bool|double|string|ELongBoolean|E[\w]+Result|"
             r"short|byte|float|uint|ulong|HWND|IntPtr|object|char|decimal|"
             r"sbyte|ushort|SafeArray|Array|DateTime|Guid|Variant|dynamic)\s+\w+\s*\(", 90.0),
            (r"\[ComImport\]", 100.0),
            (r"\[Guid\([^)]*\)\]", 100.0),
            (r"\[InterfaceType\([^)]*\)\]", 100.0),
            (r"\[DllImport\([^)]*\)\]", 100.0),
            (r"interface\s+I\w+", 95.0),
            (r"\b(def\s+|function\s+)", 80.0),
            (r"\b(class\s+\w+)", 80.0),
            (r"(public|private|protected)\s+\w+\s+\w+\s*\(", 80.0),
            (r"=>", 60.0),
        ]
        self._compiled = [(re.compile(p, re.MULTILINE), prio) for p, prio in self._patterns]

    def detect(self, flat: list[DocumentElement]) -> list[BoundaryMarker]:
        markers: list[BoundaryMarker] = []
        for i, el in enumerate(flat):
            if hasattr(el, "com_type") and el.com_type:
                continue
            for pattern, prio in self._compiled:
                if pattern.search(el.content):
                    markers.append((i, "function_signature", prio))
                    break
        return markers


class CodeBlockBoundaryDetector:
    def detect(self, flat: list[DocumentElement]) -> list[BoundaryMarker]:
        markers: list[BoundaryMarker] = []
        for i, el in enumerate(flat):
            if el.type in ("CODE_BLOCK", "INFERRED_CODE_BLOCK"):
                markers.append((i, "code_block_start", 70.0))
                if i < len(flat) - 1:
                    markers.append((i + 1, "code_block_end", 70.0))
                else:
                    markers.append((i, "code_block_end", 70.0))
        return markers


class TableBoundaryDetector:
    def detect(self, flat: list[DocumentElement]) -> list[BoundaryMarker]:
        markers: list[BoundaryMarker] = []
        for i, el in enumerate(flat):
            if el.type in ("TABLE", "INFERRED_TABLE"):
                markers.append((i, "table_start", 70.0))
                if i < len(flat) - 1:
                    markers.append((i + 1, "table_end", 70.0))
                else:
                    markers.append((i, "table_end", 70.0))
        return markers


def _com_priority_sort_key(marker: BoundaryMarker) -> float:
    _idx, btype, priority = marker
    com_priority_map = {
        "function": 100.0,
        "property": 90.0,
        "enum": 80.0,
        "record": 70.0,
        "error_code": 60.0,
    }
    return com_priority_map.get(btype, priority)


class ContextPrefixBuilder:
    def build(self, interface_name: Optional[str], section: Optional[str], element_name: Optional[str]) -> str:
        parts: list[str] = []
        if interface_name:
            parts.append(f"Interface: {interface_name}")
        if section:
            parts.append(f"Section: {section}")
        if element_name:
            parts.append(f"Element: {element_name}")
        return " | ".join(parts)


class BoundaryDetector:
    def __init__(self):
        self.detectors: list[Callable[[list[DocumentElement]], list[BoundaryMarker]]] = [
            HeadingBoundaryDetector().detect,
            FunctionSignatureDetector().detect,
            CodeBlockBoundaryDetector().detect,
            TableBoundaryDetector().detect,
        ]

    def register_detector(self, detector_fn: Callable[[list[DocumentElement]], list[BoundaryMarker]]) -> None:
        self.detectors.append(detector_fn)

    def detect(self, hierarchy: DocumentHierarchy) -> list[int]:
        flat = hierarchy.flatten_depth_first()
        all_markers: list[BoundaryMarker] = []

        for detector_fn in self.detectors:
            try:
                markers = detector_fn(flat)
                all_markers.extend(markers)
            except Exception as e:
                logger.warning(f"Boundary detector failed: {e}")

        com_markers = [
            m for m in all_markers
            if m[1] in ("function_signature", "function", "property", "enum", "record", "error_code")
        ]
        other_markers = [m for m in all_markers if m not in com_markers]

        com_markers.sort(key=_com_priority_sort_key, reverse=True)
        other_markers.sort(key=lambda m: m[2], reverse=True)

        seen_indices: set[int] = set()
        final_markers: list[BoundaryMarker] = []
        for marker in com_markers + other_markers:
            idx = marker[0]
            if idx not in seen_indices:
                seen_indices.add(idx)
                final_markers.append(marker)

        final_markers.sort(key=lambda m: m[0])
        boundary_indices = [m[0] for m in final_markers]

        return sorted(set(boundary_indices))
