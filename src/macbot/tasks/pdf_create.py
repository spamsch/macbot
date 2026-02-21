"""Task: Create PDF

Generate PDF documents from HTML or plain text using pymupdf.
"""

import html
import os

import pymupdf

from macbot.tasks.base import Task
from macbot.tasks.registry import task_registry

# Page dimensions in points (1 pt = 1/72 inch)
PAGE_SIZES: dict[str, tuple[float, float]] = {
    "a4": (595.276, 841.89),
    "letter": (612, 792),
}

DEFAULT_CSS = """\
body { font-family: Helvetica, Arial, sans-serif; font-size: 11pt; line-height: 1.4; }
h1 { font-size: 18pt; margin-bottom: 6pt; }
h2 { font-size: 14pt; margin-bottom: 4pt; }
h3 { font-size: 12pt; margin-bottom: 4pt; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0; }
th, td { border: 1px solid #999; padding: 4pt 6pt; text-align: left; }
th { background-color: #f0f0f0; font-weight: bold; }
"""


class CreatePDFTask(Task):
    """Create a PDF document from HTML or plain text.

    Example:
        task = CreatePDFTask()
        result = await task.execute(
            content="<h1>Report</h1><p>Hello world</p>",
            output_path="~/Documents/report.pdf",
        )
    """

    @property
    def name(self) -> str:
        return "create_pdf"

    @property
    def description(self) -> str:
        return (
            "Create a PDF document from HTML or plain text. "
            "Supports headings, paragraphs, lists, tables, and Unicode characters. "
            "Include a summary describing the document purpose."
        )

    async def execute(
        self,
        content: str,
        output_path: str,
        summary: str = "",
        format: str = "html",
        page_size: str = "a4",
        margin: int = 54,
    ) -> str:
        """Create a PDF document.

        Args:
            content: HTML or plain text content for the PDF.
            output_path: File path to save the PDF.
            summary: Brief description of the document (e.g., "Letter to Frank").
            format: Content format — "html" or "text".
            page_size: Page size — "a4" or "letter".
            margin: Page margin in points (default 54 ≈ 19mm).

        Returns:
            Success message with page count and file path.
        """
        output_path = os.path.expanduser(output_path)
        if not output_path.lower().endswith(".pdf"):
            output_path += ".pdf"

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        if format == "text":
            escaped = html.escape(content)
            body = "".join(f"<p>{line}</p>" for line in escaped.split("\n"))
        else:
            body = content

        page_w, page_h = PAGE_SIZES.get(page_size.lower(), PAGE_SIZES["a4"])
        content_rect = pymupdf.Rect(margin, margin, page_w - margin, page_h - margin)
        page_rect = pymupdf.Rect(0, 0, page_w, page_h)

        story = pymupdf.Story(html=body, user_css=DEFAULT_CSS)

        # Render Story into temp pages at origin (required for text extraction)
        inner_rect = pymupdf.Rect(0, 0, content_rect.width, content_rect.height)

        def rectfn(rect_num: int, filled: float) -> tuple:
            return inner_rect, inner_rect, None

        temp_doc = story.write_with_links(rectfn)

        # Place each temp page into final document with margins via show_pdf_page
        doc = pymupdf.Document()
        for page_idx in range(len(temp_doc)):
            page = doc.new_page(width=page_w, height=page_h)
            page.show_pdf_page(content_rect, temp_doc, page_idx)
        temp_doc.close()

        doc.save(output_path)
        page_count = len(doc)
        doc.close()

        from macbot.memory import AgentMemory

        memory = AgentMemory()
        memory.record_file_written(output_path, summary)

        return f"Successfully created {page_count}-page PDF at {output_path}"


# Auto-register on import
task_registry.register(CreatePDFTask())
