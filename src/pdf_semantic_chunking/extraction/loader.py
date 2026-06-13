import os
import logging

from .model import DocumentElement, DocumentHierarchy, ElementType

logger = logging.getLogger(__name__)


class PdfminerParser:
    def parse(self, file_path: str) -> DocumentHierarchy:
        from pdfminer.high_level import extract_pages

        root = DocumentElement(type="PAGE", content="", metadata={"name": "document_root", "filename": os.path.basename(file_path)})
        pages_data = extract_pages(file_path)
        for page_num, lt_page in enumerate(pages_data, 1):
            page_el = DocumentElement(
                type="PAGE",
                content="",
                metadata={
                    "page_number": page_num,
                    "bbox": (
                        lt_page.bbox[0], lt_page.bbox[1],
                        lt_page.bbox[2], lt_page.bbox[3],
                    ) if hasattr(lt_page, "bbox") else None,
                },
            )
            self._process_lt_element(lt_page, page_el)
            root.add_child(page_el)

        return DocumentHierarchy(root=root)

    def _process_lt_element(self, lt_elem, parent_el: DocumentElement) -> None:
        from pdfminer.layout import LTTextBox, LTFigure, LTTextLine, LTChar, LTAnno, LTRect, LTLine, LTCurve

        if isinstance(lt_elem, (LTTextBox, LTTextLine)):
            text = lt_elem.get_text().strip()
            if not text:
                return
            bbox = (lt_elem.bbox[0], lt_elem.bbox[1], lt_elem.bbox[2], lt_elem.bbox[3]) if hasattr(lt_elem, "bbox") else None
            font_sizes: list[float] = []
            font_names: list[str] = []
            if hasattr(lt_elem, "__iter__"):
                for child in lt_elem:
                    if isinstance(child, LTChar):
                        if hasattr(child, "size") and child.size:
                            font_sizes.append(child.size)
                        if hasattr(child, "fontname") and child.fontname:
                            font_names.append(child.fontname)
                    elif isinstance(child, LTAnno):
                        pass

            metadata: dict = {"bbox": bbox}
            if font_sizes:
                metadata["font_size"] = max(font_sizes)
            if font_names:
                metadata["font_name"] = font_names[0]

            el_type = self._infer_element_type(text, metadata)
            child_el = DocumentElement(type=el_type, content=text, metadata=metadata)
            parent_el.add_child(child_el)

        elif isinstance(lt_elem, LTFigure):
            for child in lt_elem:
                self._process_lt_element(child, parent_el)

        elif isinstance(lt_elem, (LTRect, LTLine)):
            pass

        elif isinstance(lt_elem, LTCurve):
            # In some pdfminer versions LTCurve is not iterable; skip
            # to avoid "'LTCurve' object is not iterable" TypeError.
            pass

        elif hasattr(lt_elem, "__iter__"):
            for child in lt_elem:
                self._process_lt_element(child, parent_el)

    def _infer_element_type(self, text: str, metadata: dict) -> ElementType:

        font_size = metadata.get("font_size", 0)
        font_name = metadata.get("font_name", "").lower()

        if font_size > 14 and len(text) < 200:
            return "HEADING"
        if "monospace" in font_name or "courier" in font_name or "consolas" in font_name:
            return "CODE_BLOCK"
        return "PARAGRAPH"
