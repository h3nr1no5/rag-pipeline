"""DOCX / PDF extraction layer for API documentation."""

from src.domain.rag.api_docs.extraction.converter import DocumentConverter
from src.domain.rag.api_docs.extraction.docx_parser import (
    DocxParser,
    RawDocument,
    RawParagraph,
    RawTable,
)
from src.domain.rag.api_docs.extraction.pdf_fallback import PdfFallbackExtractor
from src.domain.rag.api_docs.extraction.table_detector import (
    TableDetector,
    merge_multi_row_functions,
)

__all__ = [
    "DocumentConverter",
    "DocxParser",
    "PdfFallbackExtractor",
    "RawDocument",
    "RawParagraph",
    "RawTable",
    "TableDetector",
    "merge_multi_row_functions",
]
