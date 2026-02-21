"""Tests for CreatePDFTask."""

import asyncio
import os
from typing import Any
from unittest.mock import MagicMock, patch

import pymupdf
import pytest

from macbot.tasks.pdf_create import CreatePDFTask

MOCK_MEMORY = "macbot.memory.AgentMemory"


def _run(coro):  # type: ignore[no-untyped-def]
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


class TestCreatePDFTask:
    """Tests for PDF document generation."""

    def test_simple_html(self, tmp_path: Any) -> None:
        """Simple HTML produces a valid PDF with the content."""
        out = str(tmp_path / "test.pdf")
        task = CreatePDFTask()

        with patch(MOCK_MEMORY):
            result = _run(task.execute(
                content="<h1>Hello</h1><p>World</p>",
                output_path=out,
            ))

        assert "1-page PDF" in result
        assert os.path.isfile(out)

        doc = pymupdf.open(out)
        text = doc[0].get_text()
        doc.close()
        assert "Hello" in text
        assert "World" in text

    def test_german_umlauts(self, tmp_path: Any) -> None:
        """Unicode characters like German umlauts render correctly."""
        out = str(tmp_path / "umlauts.pdf")
        task = CreatePDFTask()

        with patch(MOCK_MEMORY):
            _run(task.execute(
                content="<p>Ährenfeld Übung Öffnung Straße</p>",
                output_path=out,
            ))

        doc = pymupdf.open(out)
        text = doc[0].get_text()
        doc.close()
        assert "Ährenfeld" in text
        assert "Straße" in text

    def test_plain_text_format(self, tmp_path: Any) -> None:
        """format='text' wraps plain text in HTML paragraphs."""
        out = str(tmp_path / "plain.pdf")
        task = CreatePDFTask()

        with patch(MOCK_MEMORY):
            _run(task.execute(
                content="Line one\nLine two",
                output_path=out,
                format="text",
            ))

        doc = pymupdf.open(out)
        text = doc[0].get_text()
        doc.close()
        assert "Line one" in text
        assert "Line two" in text

    def test_auto_append_pdf_extension(self, tmp_path: Any) -> None:
        """.pdf extension is auto-appended when missing."""
        out = str(tmp_path / "report")
        task = CreatePDFTask()

        with patch(MOCK_MEMORY):
            result = _run(task.execute(content="<p>test</p>", output_path=out))

        assert result.endswith(out + ".pdf")
        assert os.path.isfile(out + ".pdf")

    def test_multipage(self, tmp_path: Any) -> None:
        """Content long enough to span multiple pages produces multiple pages."""
        out = str(tmp_path / "multi.pdf")
        task = CreatePDFTask()
        long_content = "<p>Paragraph. </p>" * 200

        with patch(MOCK_MEMORY):
            result = _run(task.execute(content=long_content, output_path=out))

        doc = pymupdf.open(out)
        page_count = len(doc)
        doc.close()
        assert page_count > 1
        assert f"{page_count}-page PDF" in result

    def test_table_rendering(self, tmp_path: Any) -> None:
        """HTML tables render into the PDF."""
        out = str(tmp_path / "table.pdf")
        task = CreatePDFTask()
        table_html = (
            "<table>"
            "<tr><th>Name</th><th>Value</th></tr>"
            "<tr><td>Alpha</td><td>100</td></tr>"
            "<tr><td>Beta</td><td>200</td></tr>"
            "</table>"
        )

        with patch(MOCK_MEMORY):
            _run(task.execute(content=table_html, output_path=out))

        doc = pymupdf.open(out)
        text = doc[0].get_text()
        doc.close()
        assert "Alpha" in text
        assert "200" in text

    def test_parent_directory_creation(self, tmp_path: Any) -> None:
        """Non-existent parent directories are created automatically."""
        out = str(tmp_path / "sub" / "dir" / "doc.pdf")
        task = CreatePDFTask()

        with patch(MOCK_MEMORY):
            _run(task.execute(content="<p>nested</p>", output_path=out))

        assert os.path.isfile(out)

    def test_memory_recording(self, tmp_path: Any) -> None:
        """File write is recorded to AgentMemory with summary."""
        out = str(tmp_path / "memo.pdf")
        task = CreatePDFTask()

        with patch(MOCK_MEMORY) as mock_cls:
            mock_memory = MagicMock()
            mock_cls.return_value = mock_memory

            _run(task.execute(
                content="<p>hello</p>",
                output_path=out,
                summary="Test memo",
            ))

            mock_memory.record_file_written.assert_called_once_with(out, "Test memo")

    def test_tool_schema(self) -> None:
        """Tool schema contains expected parameters."""
        task = CreatePDFTask()
        schema = task.to_tool_schema()

        assert schema["name"] == "create_pdf"
        props = schema["input_schema"]["properties"]
        assert "content" in props
        assert "output_path" in props
        assert "format" in props
        assert "page_size" in props
        assert "margin" in props
        assert "summary" in props

        required = schema["input_schema"]["required"]
        assert "content" in required
        assert "output_path" in required

    def test_letter_page_size(self, tmp_path: Any) -> None:
        """page_size='letter' produces US Letter dimensions."""
        out = str(tmp_path / "letter.pdf")
        task = CreatePDFTask()

        with patch(MOCK_MEMORY):
            _run(task.execute(
                content="<p>US Letter</p>",
                output_path=out,
                page_size="letter",
            ))

        doc = pymupdf.open(out)
        page = doc[0]
        # US Letter: 612 x 792 points
        assert abs(page.rect.width - 612) < 1
        assert abs(page.rect.height - 792) < 1
        doc.close()

    def test_tilde_expansion(self, tmp_path: Any) -> None:
        """~ in output_path is expanded to home directory."""
        task = CreatePDFTask()

        with patch(MOCK_MEMORY):
            result = _run(task.execute(
                content="<p>test</p>",
                output_path=str(tmp_path / "tilde_test.pdf"),
            ))

        assert "~" not in result
