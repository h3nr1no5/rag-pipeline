"""PDF fallback extractor for when DOCX is unavailable.

Uses ``pymupdf`` (``import fitz``) to extract text from PDF files and
returns a :class:`RawDocument` with page-level paragraphs, enabling the
downstream pipeline to process PDF uploads with the same converter logic.
"""

from pathlib import Path

import fitz  # pymupdf  (mypy: ignore)

from src.domain.rag.api_docs.extraction.docx_parser import (
    RawDocument,
    RawParagraph,
)


class PdfFallbackExtractor:
    """Extract text content from PDF files as paragraph-like raw structures.

    When only a PDF version of the API documentation is available (no
    corresponding ``.docx`` file), this extractor fills the role of
    :class:`DocxParser` by producing a :class:`RawDocument` where each
    page becomes a single :class:`RawParagraph`.

    No tables are extracted from PDFs — the ``tables`` list will be
    empty.  Structured extraction from PDFs (table detection, layout
    analysis) is **not** supported and is left to the DOCX pipeline.
    """

    def __init__(self, file_path: str | Path) -> None:
        self.file_path = Path(file_path)

    def extract(self) -> RawDocument:
        """Extract text from the PDF file.

        Returns
        -------
        RawDocument
            A document with empty ``tables`` and one :class:`RawParagraph`
            per page.  Each paragraph's text is prefixed with ``[Page N]``
            followed by the page's raw text content.

        Raises
        ------
        ValueError
            If the PDF file cannot be opened or parsed.
        """
        doc: fitz.Document | None = None
        try:
            doc = fitz.open(str(self.file_path))
        except Exception as exc:
            raise ValueError(
                f"Failed to open PDF file '{self.file_path}': {exc}"
            ) from exc

        paragraphs: list[RawParagraph] = []

        try:
            for page_num in range(len(doc)):
                page = doc.load_page(page_num)
                raw = page.get_text()
                page_text = str(raw).strip() if raw else ""
                if not page_text:
                    continue
                prefixed = f"[Page {page_num + 1}]\n{page_text}"
                paragraphs.append(RawParagraph(
                    text=prefixed,
                    style_name="",
                    heading_level=0,
                ))
        except Exception:
            # Ensure document is closed on any extraction error
            doc.close()
            raise

        doc.close()

        return RawDocument(
            tables=[],
            paragraphs=paragraphs,
            filename=self.file_path.name,
        )
