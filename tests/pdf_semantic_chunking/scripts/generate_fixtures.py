"""
Generate test fixture PDFs for the semantic PDF chunking pipeline.

Produces 4 PDFs in tests/pdf_semantic_chunking/fixtures/:
  - structured.pdf      — H1/H2 headings, paragraphs, code block, table
  - unstructured.pdf    — plain narrative prose with no headings/tables
  - com_sample.pdf      — C# COM interop declarations (code-heavy)
  - multi_column.pdf    — two-column text with a vertical separator

Usage:
    uv run python tests/pdf_semantic_chunking/scripts/generate_fixtures.py
"""

import os

import fitz  # PyMuPDF

# ── Paths ──────────────────────────────────────────────────────────────────
FIXTURES_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "fixtures")
)

# ── US Letter page constants ──────────────────────────────────────────────
PAGE_W, PAGE_H = 612, 792
ML, MR = 72, 72          # left / right margins
MT, MB = 50, 50          # top / bottom margins
TEXT_W = PAGE_W - ML - MR  # 468 (usable text width)


# ---------------------------------------------------------------------------
# Line-height helpers  (empirically measured from PyMuPDF 1.27.2)
# ---------------------------------------------------------------------------
# These constants map fontsize → effective line advance (leading).
# For Helvetica 11pt the leading is ~16.25 pt; Courier 9pt is ~13.3 pt.
def _line_advance(fontsize: float, is_code: bool = False) -> float:
    """Return the effective line-to-line advance for a given fontsize."""
    factor = 1.477 if not is_code else 1.478
    return fontsize * factor


def _text_height(text: str, fontsize: float, fontname: str, width: float) -> float:
    """Estimate the total height of word-wrapped text."""
    advance = _line_advance(fontsize,             fontname.lower().startswith("courier") or fontname.lower() == "courier")  # noqa: E501
    total = 0.0
    for paragraph in text.split("\n"):
        if not paragraph:
            total += advance
            continue
        words = paragraph.split()
        line = ""
        for word in words:
            candidate = line + " " + word if line else word
            w = fitz.get_text_length(
                candidate, fontname=fontname, fontsize=fontsize
            )
            if w > width and line:
                total += advance
                line = word
            else:
                line = candidate
        if line:
            total += advance
    return total


# ---------------------------------------------------------------------------
# DocBuilder — helper for single-column documents
# ---------------------------------------------------------------------------
class DocBuilder:
    """Convenience builder for single-column, top-down PDF documents."""

    def __init__(self, filename: str):
        self.path = os.path.join(FIXTURES_DIR, filename)
        self.doc = fitz.open()
        self._y: float = MT
        self._page: fitz.Page | None = None
        self._new_page()

    # -- page management ---------------------------------------------------

    def _new_page(self) -> fitz.Page:
        self._page = self.doc.new_page(width=PAGE_W, height=PAGE_H)
        self._y = MT
        return self._page

    @property
    def page(self) -> fitz.Page:
        assert self._page is not None
        return self._page

    def _ensure(self, needed: float) -> None:
        """Start a new page if insufficient vertical room remains."""
        if self._y + needed > PAGE_H - MB:
            self._new_page()

    # -- content helpers ---------------------------------------------------

    def heading(self, text: str, level: int = 1) -> None:
        """Add a heading at the appropriate size."""
        fs = {1: 24, 2: 18, 3: 14}.get(level, 14)
        bold = level <= 2
        advance = _line_advance(fs)
        self._ensure(advance + 6)
        self.page.insert_text(
            fitz.Point(ML, self._y + fs * 0.85),  # ~baseline
            text,
            fontname="Helvetica-Bold" if bold else "Helvetica",
            fontsize=fs,
            color=(0, 0, 0),
        )
        self._y += advance + 6

    def paragraph(self, text: str, fontsize: float = 11) -> None:
        """Add a word-wrapped paragraph."""
        height = _text_height(text, fontsize, "helv", TEXT_W)
        self._ensure(height + 4)
        rect = fitz.Rect(ML, self._y, PAGE_W - MR, PAGE_H - MB)
        self.page.insert_textbox(
            rect,
            text,
            fontname="Helvetica",
            fontsize=fontsize,
            color=(0, 0, 0),
        )
        self._y += height + 6

    def code_block(self, code: str, fontsize: float = 9) -> None:
        """Insert a code block with a light-grey background."""
        lines = code.split("\n")
        advance = _line_advance(fontsize, is_code=True)
        block_h = max(len(lines), 1) * advance + 12
        self._ensure(block_h)

        bg = fitz.Rect(ML, self._y, PAGE_W - MR, self._y + block_h)
        self.page.draw_rect(bg, color=(0.9, 0.9, 0.9), fill=(0.9, 0.9, 0.9))

        x = ML + 8
        y = self._y + advance * 0.85
        for i, line in enumerate(lines):
            self.page.insert_text(
                fitz.Point(x, y + i * advance),
                line,
                fontname="Courier",
                fontsize=fontsize,
                color=(0, 0, 0),
            )

        self._y += block_h + 8

    def table(
        self,
        headers: list[str],
        rows: list[list[str]],
        col_widths: list[int] | None = None,
    ) -> None:
        """Draw a simple table with a header row and grid lines."""
        ncols = len(headers)
        if col_widths is None:
            col_widths = [TEXT_W // ncols] * ncols
        total_w = sum(col_widths)
        row_h = 20
        header_h = 24
        total_h = header_h + len(rows) * row_h + 2
        self._ensure(total_h)

        x0 = ML
        xs = [x0]
        for w in col_widths:
            xs.append(xs[-1] + w)
        y0 = self._y

        # header background
        hdr_rect = fitz.Rect(x0, y0, x0 + total_w, y0 + header_h)
        self.page.draw_rect(hdr_rect, color=(0.8, 0.8, 0.8), fill=(0.8, 0.8, 0.8))

        # header text
        for j, hdr in enumerate(headers):
            self.page.insert_text(
                fitz.Point(xs[j] + 4, y0 + 16),
                hdr,
                fontname="Helvetica-Bold",
                fontsize=10,
                color=(0, 0, 0),
            )

        # row text
        for i, row in enumerate(rows):
            ry = y0 + header_h + i * row_h
            for j, cell in enumerate(row):
                self.page.insert_text(
                    fitz.Point(xs[j] + 4, ry + 14),
                    str(cell),
                    fontname="Helvetica",
                    fontsize=9,
                    color=(0, 0, 0),
                )

        # horizontal grid lines
        y_positions = [y0, y0 + header_h]
        for i in range(len(rows) + 1):
            y_positions.append(y0 + header_h + i * row_h)
        y_positions.append(y0 + header_h + len(rows) * row_h)
        for ly in y_positions:
            self.page.draw_line(
                fitz.Point(x0, ly),
                fitz.Point(x0 + total_w, ly),
                color=(0, 0, 0),
            )

        # vertical grid lines
        for x in xs:
            self.page.draw_line(
                fitz.Point(x, y0),
                fitz.Point(x, y0 + header_h + len(rows) * row_h),
                color=(0, 0, 0),
            )

        self._y = y0 + header_h + len(rows) * row_h + 8

    def spacer(self, pts: float = 10) -> None:
        """Add vertical whitespace."""
        self._ensure(pts)
        self._y += pts

    def save(self) -> str:
        """Write the PDF to disk and return the file path."""
        self.doc.save(self.path)
        self.doc.close()
        return self.path


# ===================================================================
#  PDF 1 — structured.pdf
# ===================================================================
def _make_structured() -> str:
    b = DocBuilder("structured.pdf")

    b.heading("Introduction", level=1)
    b.paragraph(
        "This document demonstrates a structured PDF layout suitable for "
        "testing the semantic chunking pipeline. It contains hierarchically "
        "organised headings, explanatory paragraphs, code fragments, and "
        "tabular data. The semantic parser should split this content along "
        "structural boundaries such as headings and section transitions."
    )

    b.heading("Architecture", level=2)
    b.paragraph(
        "The system follows a modular architecture comprising three principal "
        "layers. The ingestion layer handles document parsing and normalisation, "
        "the indexing layer builds vector representations, and the retrieval "
        "layer serves ranked results to the caller. Each layer is independently "
        "deployable and communicates via well-defined interfaces."
    )
    b.paragraph(
        "Below is an example configuration script used during the indexing "
        "phase. It demonstrates how to initialise the embedding model and "
        "construct the vector store."
    )

    b.code_block(
        "def build_index(documents: list[Document]) -> VectorStore:\n"
        '    \"\"\"Build a FAISS index from a list of documents.\"\"\"\n'
        "    embedder = EmbeddingModel(model_name=\"all-mpnet-base-v2\")\n"
        "    vectors = embedder.encode([d.text for d in documents])\n"
        "    index = faiss.IndexFlatL2(vectors.shape[1])\n"
        "    index.add(vectors)\n"
        "    return VectorStore(index=index, documents=documents)"
    )

    b.heading("Configuration", level=2)
    b.paragraph(
        "The following table summarises the supported environment variables."
    )
    b.table(
        headers=["Variable", "Default", "Description"],
        rows=[
            ["LLM_MODEL", "Qwen2.5-1.5B", "Language model identifier"],
            ["EMBEDDING_MODEL", "all-mpnet-base-v2", "Embedding model name"],
            ["CHUNK_SIZE", "512", "Max tokens per chunk"],
            ["CHUNK_OVERLAP", "64", "Overlap between adjacent chunks"],
            ["TOP_K", "10", "Number of results to retrieve"],
        ],
        col_widths=[160, 140, 168],
    )

    b.heading("API Reference", level=1)
    b.heading("GET /api/v1/query", level=3)
    b.paragraph(
        "Accepts a search query and returns the top-k ranked document chunks. "
        "The response includes chunk text, metadata, and similarity scores."
    )
    b.heading("POST /api/v1/documents", level=3)
    b.paragraph(
        "Ingests a new document into the system. The document is parsed, "
        "chunked, embedded, and stored asynchronously. Returns a job ID "
        "that can be polled for completion status."
    )

    return b.save()


# ===================================================================
#  PDF 2 — unstructured.pdf
# ===================================================================
def _make_unstructured() -> str:
    b = DocBuilder("unstructured.pdf")

    b.paragraph(
        "The old lighthouse keeper had lived on the island for forty-seven "
        "years. Every evening at sunset he climbed the spiral staircase, "
        "one hundred and thirty-two steps, and kindled the great lamp that "
        "guided ships safely past the treacherous reefs. He knew every creak "
        "of the weathered boards, every whisper of the wind through the iron "
        "railings. The sea was his oldest companion, sometimes gentle, "
        "sometimes fierce, but never silent."
    )
    b.paragraph(
        "One morning in early spring he found a message in a bottle washed "
        "up on the shingle beach. The paper inside was yellowed and the ink "
        "had run in places, but he could still make out the careful script: "
        "\"To whoever finds this, know that you are not alone.\" He read "
        "the words three times, then folded the paper neatly and placed it "
        "in his pocket beside the worn silver watch that had belonged to his "
        "father."
    )
    b.paragraph(
        "That afternoon he climbed the tower steps more slowly than usual, "
        "pausing at the narrow window on the third landing to watch a distant "
        "freighter on the horizon. The bottle and its message had stirred "
        "something in him, a feeling he could not quite name. He thought of "
        "all the ships that had passed in the night, all the hands on deck "
        "who might have looked toward his light and felt a moment of "
        "reassurance. He thought of the unknown hand that had written those "
        "words and set them adrift on the current."
    )
    b.paragraph(
        "When darkness fell and the lamp cast its steady beam across the "
        "water, the lighthouse keeper sat in his small kitchen and wrote his "
        "own message. He did not put it in a bottle. Instead, he wrote it in "
        "the logbook, beside the weather observations and the times of "
        "sunrise: \"Every light is a greeting. Every keeper is a keeper of "
        "hope.\" Then he closed the book, brewed a cup of tea, and listened "
        "to the sea."
    )

    return b.save()


# ===================================================================
#  PDF 3 — com_sample.pdf
# ===================================================================
def _make_com_sample() -> str:
    b = DocBuilder("com_sample.pdf")

    b.heading("AxisVM COM Interop Declarations", level=1)
    b.paragraph(
        "The following C# declarations define the COM interop layer for "
        "the AxisVM structural analysis engine. These interfaces are used "
        "to control the application programmatically from .NET clients."
    )

    b.heading("Error Codes", level=2)
    b.code_block(
        "public const int EApplicationError = -1;\n"
        "public const int EInvalidHandle   = -2;\n"
        "public const int ENotImplemented  = -3;\n"
        "public const int EAccessDenied    = -4;\n"
        "public const int S_OK             =  0;\n"
        "public const int S_FALSE          =  1;"
    )

    b.heading("Enumerations", level=2)
    b.code_block(
        "public enum EModelType\n"
        "{\n"
        "    mt2D    = 0,\n"
        "    mt3D    = 1,\n"
        "    mtFrame = 2,\n"
        "    mtTruss = 3,\n"
        "    mtMixed = 4,\n"
        "}"
    )
    b.code_block(
        "public enum ELoadCaseType\n"
        "{\n"
        "    lctPermanent = 0,\n"
        "    lctVariable  = 1,\n"
        "    lctSeismic   = 2,\n"
        "    lctAccidental = 3,\n"
        "}"
    )

    b.heading("Main Application Interface", level=2)
    b.code_block(
        "[ComImport]\n"
        '[Guid("B7B8A5C2-3D4E-4F6A-9B1C-2D3E4F5A6B7C")]\n'
        "[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]\n"
        "public interface IAxisVMApplication\n"
        "{\n"
        "    bool get_Visible();\n"
        "    void set_Visible([In] bool value);\n"
        "\n"
        "    [return: MarshalAs(UnmanagedType.BStr)]\n"
        "    string get_Version();\n"
        "\n"
        "    int NewModel([In] EModelType modelType);\n"
        "\n"
        "    int OpenModel([In, Out] ref string filePath);\n"
        "\n"
        "    int SaveModel([In, Out] ref string filePath);\n"
        "\n"
        "    int CloseModel();\n"
        "}"
    )

    b.spacer(4)
    b.heading("Data Structures", level=2)
    b.code_block(
        "public readonly record struct RModelData\n"
        "{\n"
        "    public int    Id         { get; init; }\n"
        "    public string Name       { get; init; }\n"
        "    public EModelType Type  { get; init; }\n"
        "    public bool   IsModified { get; init; }\n"
        "}"
    )

    b.spacer(4)
    b.heading("CoClass Declaration", level=2)
    b.code_block(
        "[ComImport]\n"
        '[Guid("A1B2C3D4-E5F6-7890-ABCD-EF1234567890")]\n'
        "public class AxisVMApplicationClass\n"
        "{\n"
        "    // CoClass — implemented by the AxisVM COM server.\n"
        "}"
    )

    return b.save()


# ===================================================================
#  PDF 4 — multi_column.pdf  (direct fitz calls)
# ===================================================================
def _make_multi_column() -> str:
    path = os.path.join(FIXTURES_DIR, "multi_column.pdf")
    doc = fitz.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)

    column_gap = 24
    col_w = (TEXT_W - column_gap) // 2  # 222

    # Column geometry
    left_rect = fitz.Rect(ML, MT, ML + col_w, PAGE_H - MB)
    right_rect = fitz.Rect(
        PAGE_W - MR - col_w, MT, PAGE_W - MR, PAGE_H - MB
    )
    sep_x = ML + col_w + column_gap // 2

    # Vertical separator line
    page.draw_line(
        fitz.Point(sep_x, MT),
        fitz.Point(sep_x, PAGE_H - MB),
        color=(0.5, 0.5, 0.5),
        width=0.5,
    )

    # -- Left column --
    left_text = (
        "Left Column\n"
        "\n"
        "This is the left column of a multi-column layout. It contains "
        "several paragraphs of text that should be wrapped within the "
        "column boundaries. Multi-column layouts are common in academic "
        "papers, technical reports, and news articles.\n"
        "\n"
        "The primary advantage of multi-column layouts is that they allow "
        "more text to fit on a single page while maintaining comfortable "
        "line lengths for readability. Shorter lines reduce eye strain and "
        "improve reading speed for dense content.\n"
        "\n"
        "In the context of PDF parsing and semantic chunking, recognising "
        "multi-column layouts is a significant challenge. Naive "
        "top-to-bottom text extraction will interleave content from "
        "different columns, producing garbled output. Advanced chunking "
        "pipelines must detect column boundaries and reorder text "
        "accordingly before further processing."
    )

    page.insert_textbox(
        left_rect,
        left_text,
        fontname="Helvetica",
        fontsize=11,
        color=(0, 0, 0),
        align=0,
    )

    # -- Right column --
    right_text = (
        "Right Column\n"
        "\n"
        "This is the right column. It runs parallel to the left column "
        "and contains entirely different content. Semantic chunking "
        "algorithms that work page-by-page must learn to identify "
        "column boundaries and treat each column as a separate reading "
        "order sequence.\n"
        "\n"
        "Several approaches exist for column detection in PDFs. One "
        "common method analyses the spatial distribution of text blocks "
        "and groups them by x-position. Another uses computer vision "
        "techniques to detect vertical whitespace gaps and separator "
        "lines.\n"
        "\n"
        "Once columns are identified, the text from each column should "
        "be extracted in reading order (left-to-right, top-to-bottom "
        "within each column) and then concatenated or processed "
        "independently. This fixture provides a controlled test case "
        "with clearly separated columns.\n"
        "\n"
        "The vertical line between the two columns serves as an "
        "additional visual cue that helps both human readers and "
        "automated detectors identify the column boundary."
    )

    page.insert_textbox(
        right_rect,
        right_text,
        fontname="Helvetica",
        fontsize=11,
        color=(0, 0, 0),
        align=0,
    )

    doc.save(path)
    doc.close()
    return path


# ===================================================================
#  Main
# ===================================================================
def main() -> None:
    os.makedirs(FIXTURES_DIR, exist_ok=True)

    generators = [
        ("structured.pdf", _make_structured),
        ("unstructured.pdf", _make_unstructured),
        ("com_sample.pdf", _make_com_sample),
        ("multi_column.pdf", _make_multi_column),
    ]

    results = []
    for name, gen in generators:
        path = gen()
        size = os.path.getsize(path)
        # Quick verification: re-open and count pages
        doc = fitz.open(path)
        npages = doc.page_count
        doc.close()
        results.append((name, path, npages, size))
        print(f"  ✓ {name:20s}  {npages} page(s)  {size / 1024:.1f} KB")

    print()
    print("All PDFs generated successfully in:")
    print(f"  {FIXTURES_DIR}/")

    # Print summary table
    print()
    print(f"{'File':20s} {'Pages':>6s} {'Size':>8s}")
    print("-" * 36)
    for name, _, npages, size in results:
        print(f"{name:20s} {npages:6d} {size / 1024:7.1f} KB")


if __name__ == "__main__":
    main()
