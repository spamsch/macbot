"""Task: Read File

Read content from a file on the filesystem, including PDF support.
"""

import base64
import logging
import os
from typing import Any

from macbot.tasks.base import Task
from macbot.tasks.registry import task_registry

logger = logging.getLogger(__name__)


class ReadFileTask(Task):
    """Read content from a file.

    Reads file content with configurable maximum character limit.
    For PDF files, extracts text or renders pages as images for vision-capable LLMs.

    Example:
        task = ReadFileTask()
        result = await task.execute(path="/tmp/test.txt")
        # Returns file content as string

        result = await task.execute(path="/tmp/document.pdf")
        # Returns extracted text, or dict with page images for scanned PDFs
    """

    @property
    def name(self) -> str:
        """Get the task name."""
        return "read_file"

    @property
    def description(self) -> str:
        """Get the task description."""
        return "Read and return the content of a file. Supports text files and PDFs (text extraction with image fallback for scanned documents)."

    async def execute(
        self, path: str, max_chars: int = 10000, max_pages: int = 5
    ) -> str | dict[str, Any]:
        """Read content from a file.

        Args:
            path: File path to read from.
            max_chars: Maximum characters to return (for text content).
            max_pages: Maximum pages to render as images (for scanned PDFs).

        Returns:
            File content as string, or dict with page images for scanned PDFs.

        Raises:
            FileNotFoundError: If the file does not exist.
            PermissionError: If the file cannot be read.
        """
        path = os.path.expanduser(path)

        if path.lower().endswith(".pdf"):
            return self._read_pdf(path, max_chars, max_pages)

        with open(path) as f:
            content = f.read(max_chars)
        return content

    def _read_pdf(
        self, path: str, max_chars: int, max_pages: int
    ) -> str | dict[str, Any]:
        """Read a PDF file, extracting text or rendering pages as images.

        Args:
            path: Absolute path to the PDF file.
            max_chars: Maximum characters for text extraction.
            max_pages: Maximum pages to render as images.

        Returns:
            Extracted text as string if the PDF has meaningful text content,
            or a dict with type="pdf_images" containing base64-encoded page images.
        """
        try:
            import pymupdf
        except ImportError:
            raise RuntimeError(
                "pymupdf is required for PDF support. Install it with: pip install pymupdf"
            )

        try:
            doc = pymupdf.open(path)
        except Exception as e:
            error_msg = str(e).lower()
            if "password" in error_msg or "encrypted" in error_msg:
                raise PermissionError(f"PDF is password-protected: {path}") from e
            raise ValueError(f"Could not open PDF: {e}") from e

        try:
            # Extract text from all pages
            text_parts: list[str] = []
            for page in doc:
                text = page.get_text()
                if text.strip():
                    text_parts.append(text)

            full_text = "\n".join(text_parts)

            # If meaningful text found (>100 chars), return as text
            if len(full_text.strip()) > 100:
                if len(full_text) > max_chars:
                    full_text = full_text[:max_chars]
                return full_text

            # Image-based PDF: render pages as PNG images
            pages_to_render = min(len(doc), max_pages)
            images: list[str] = []

            for i in range(pages_to_render):
                page = doc[i]
                # Render at 150 DPI for good quality without excessive size
                pix = page.get_pixmap(dpi=150)
                png_data = pix.tobytes("png")
                b64_data = base64.b64encode(png_data).decode("ascii")
                images.append(b64_data)

            summary = f"Scanned PDF: {len(doc)} page(s)"
            if full_text.strip():
                summary += f", minimal text extracted: {full_text.strip()[:200]}"

            return {
                "type": "pdf_images",
                "text": summary,
                "pages": len(doc),
                "images": images,
            }
        finally:
            doc.close()


# Auto-register on import
task_registry.register(ReadFileTask())
