"""Tests for PDF support in ReadFileTask and multimodal tool result handling."""

import base64
import json
import os
import tempfile
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers to create test PDFs
# ---------------------------------------------------------------------------

def _create_text_pdf(path: str, text: str = "Hello, this is a test PDF with enough text to be considered meaningful content. " * 5) -> None:
    """Create a simple text-based PDF using pymupdf."""
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    doc.save(path)
    doc.close()


def _create_image_pdf(path: str) -> None:
    """Create a PDF with only an image (no extractable text)."""
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    # Draw a filled rectangle — no text at all
    page.draw_rect(pymupdf.Rect(50, 50, 200, 200), color=(1, 0, 0), fill=(0, 0, 1))
    doc.save(path)
    doc.close()


def _create_multipage_image_pdf(path: str, num_pages: int = 8) -> None:
    """Create a multi-page PDF with only images."""
    import pymupdf

    doc = pymupdf.open()
    for i in range(num_pages):
        page = doc.new_page()
        page.draw_rect(pymupdf.Rect(50, 50, 200, 200), color=(0, i / num_pages, 0), fill=(1, 0, 0))
    doc.save(path)
    doc.close()


# ---------------------------------------------------------------------------
# ReadFileTask tests
# ---------------------------------------------------------------------------

class TestReadFileTaskPDF:
    """Tests for PDF reading in ReadFileTask."""

    @pytest.mark.asyncio
    async def test_text_pdf_returns_string(self, tmp_path: Any) -> None:
        """Text-based PDF returns extracted text as a string."""
        from macbot.tasks.file_read import ReadFileTask

        pdf_path = str(tmp_path / "text.pdf")
        _create_text_pdf(pdf_path)

        task = ReadFileTask()
        result = await task.execute(path=pdf_path)

        assert isinstance(result, str)
        assert "Hello" in result

    @pytest.mark.asyncio
    async def test_image_pdf_returns_dict(self, tmp_path: Any) -> None:
        """Image-only PDF returns dict with type=pdf_images and base64 images."""
        from macbot.tasks.file_read import ReadFileTask

        pdf_path = str(tmp_path / "image.pdf")
        _create_image_pdf(pdf_path)

        task = ReadFileTask()
        result = await task.execute(path=pdf_path)

        assert isinstance(result, dict)
        assert result["type"] == "pdf_images"
        assert result["pages"] == 1
        assert len(result["images"]) == 1
        # Verify it's valid base64 PNG
        decoded = base64.b64decode(result["images"][0])
        assert decoded[:4] == b"\x89PNG"

    @pytest.mark.asyncio
    async def test_max_pages_limits_images(self, tmp_path: Any) -> None:
        """max_pages parameter caps the number of rendered images."""
        from macbot.tasks.file_read import ReadFileTask

        pdf_path = str(tmp_path / "multi.pdf")
        _create_multipage_image_pdf(pdf_path, num_pages=8)

        task = ReadFileTask()
        result = await task.execute(path=pdf_path, max_pages=3)

        assert isinstance(result, dict)
        assert result["pages"] == 8  # total pages in PDF
        assert len(result["images"]) == 3  # but only 3 rendered

    @pytest.mark.asyncio
    async def test_max_chars_truncates_text_pdf(self, tmp_path: Any) -> None:
        """max_chars truncates text extracted from a text PDF."""
        import pymupdf

        from macbot.tasks.file_read import ReadFileTask

        pdf_path = str(tmp_path / "long.pdf")
        # Insert text on many lines to ensure >100 chars extracted
        doc = pymupdf.open()
        page = doc.new_page()
        line = "This is a long line of text for testing truncation. "
        for i in range(50):
            page.insert_text((72, 72 + i * 14), line)
        doc.save(pdf_path)
        doc.close()

        task = ReadFileTask()
        result = await task.execute(path=pdf_path, max_chars=200)

        assert isinstance(result, str)
        assert len(result) <= 200

    @pytest.mark.asyncio
    async def test_non_pdf_unchanged(self, tmp_path: Any) -> None:
        """Non-PDF files still return plain string content."""
        from macbot.tasks.file_read import ReadFileTask

        txt_path = str(tmp_path / "hello.txt")
        with open(txt_path, "w") as f:
            f.write("plain text content")

        task = ReadFileTask()
        result = await task.execute(path=txt_path)

        assert isinstance(result, str)
        assert result == "plain text content"

    @pytest.mark.asyncio
    async def test_file_not_found(self) -> None:
        """Missing file raises FileNotFoundError."""
        from macbot.tasks.file_read import ReadFileTask

        task = ReadFileTask()
        with pytest.raises(FileNotFoundError):
            await task.execute(path="/nonexistent/file.txt")

    @pytest.mark.asyncio
    async def test_corrupted_pdf(self, tmp_path: Any) -> None:
        """Corrupted PDF raises ValueError."""
        from macbot.tasks.file_read import ReadFileTask

        bad_path = str(tmp_path / "bad.pdf")
        with open(bad_path, "wb") as f:
            f.write(b"this is not a PDF at all")

        task = ReadFileTask()
        with pytest.raises(ValueError, match="Could not open PDF"):
            await task.execute(path=bad_path)

    @pytest.mark.asyncio
    async def test_description_mentions_pdf(self) -> None:
        """Tool description mentions PDF support."""
        from macbot.tasks.file_read import ReadFileTask

        task = ReadFileTask()
        assert "PDF" in task.description or "pdf" in task.description.lower()

    @pytest.mark.asyncio
    async def test_tool_schema_includes_max_pages(self) -> None:
        """Tool schema includes max_pages parameter."""
        from macbot.tasks.file_read import ReadFileTask

        task = ReadFileTask()
        schema = task.to_tool_schema()
        props = schema["input_schema"]["properties"]
        assert "max_pages" in props


# ---------------------------------------------------------------------------
# Agent _format_tool_result tests
# ---------------------------------------------------------------------------

class TestFormatToolResultPDF:
    """Tests for _format_tool_result handling pdf_images output."""

    def _make_agent(self) -> Any:
        """Create a minimal Agent for testing _format_tool_result."""
        from macbot.core.task import TaskResult

        # We need an Agent instance — mock out the heavy parts
        with patch("macbot.core.agent.get_default_registry"), \
             patch("macbot.core.agent.LiteLLMProvider"), \
             patch("macbot.core.agent.settings") as mock_settings:
            mock_settings.get_model.return_value = "anthropic/claude-sonnet-4-20250514"
            mock_settings.get_api_key_for_model.return_value = "test-key"
            mock_settings.get_api_base_for_model.return_value = None
            mock_settings.context_profile = "full"
            mock_settings.max_iterations = 10
            mock_settings.agent_system_prompt = "test"

            from macbot.core.agent import Agent
            from macbot.core.task import TaskRegistry
            agent = Agent(task_registry=TaskRegistry())

        return agent

    def test_pdf_images_returns_content_blocks(self) -> None:
        """pdf_images output produces a list of content blocks."""
        from macbot.core.task import TaskResult

        agent = self._make_agent()
        result = TaskResult(
            success=True,
            output={
                "type": "pdf_images",
                "text": "Scanned PDF: 2 pages",
                "pages": 2,
                "images": ["aGVsbG8=", "d29ybGQ="],
            },
        )

        formatted = agent._format_tool_result(result)

        assert isinstance(formatted, list)
        assert formatted[0]["type"] == "text"
        assert formatted[0]["text"] == "Scanned PDF: 2 pages"
        assert formatted[1]["type"] == "image_url"
        assert formatted[1]["image_url"]["url"].startswith("data:image/png;base64,")
        assert formatted[2]["type"] == "image_url"

    def test_plain_dict_returns_string(self) -> None:
        """A regular dict (not pdf_images) returns JSON string."""
        from macbot.core.task import TaskResult

        agent = self._make_agent()
        result = TaskResult(
            success=True,
            output={"key": "value"},
        )

        formatted = agent._format_tool_result(result)

        assert isinstance(formatted, str)
        assert json.loads(formatted) == {"key": "value"}

    def test_error_returns_string(self) -> None:
        """Error results always return a string."""
        from macbot.core.task import TaskResult

        agent = self._make_agent()
        result = TaskResult(success=False, output=None, error="something broke")

        formatted = agent._format_tool_result(result)

        assert isinstance(formatted, str)
        assert "Error: something broke" in formatted


# ---------------------------------------------------------------------------
# Provider multimodal tool result handling
# ---------------------------------------------------------------------------

class TestAnthropicMultimodalToolResult:
    """Tests that Anthropic provider converts image blocks in tool results."""

    def test_multimodal_tool_result_conversion(self) -> None:
        """Multimodal tool result is converted to Anthropic format."""
        from macbot.providers.anthropic import AnthropicProvider
        from macbot.providers.base import Message

        provider = AnthropicProvider.__new__(AnthropicProvider)
        provider.model = "claude-sonnet-4-20250514"

        content_blocks = [
            {"type": "text", "text": "Scanned PDF"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,aGVsbG8="}},
        ]

        msg = provider.format_tool_result("call_123", content_blocks)

        assert msg.role == "tool"
        assert msg.tool_call_id == "call_123"
        assert isinstance(msg.content, list)

    def test_string_tool_result_unchanged(self) -> None:
        """String tool result stays as string."""
        from macbot.providers.anthropic import AnthropicProvider

        provider = AnthropicProvider.__new__(AnthropicProvider)
        provider.model = "claude-sonnet-4-20250514"

        msg = provider.format_tool_result("call_123", "plain text result")

        assert msg.content == "plain text result"


class TestOpenAIMultimodalFallback:
    """Tests that OpenAI extracts text-only from multimodal tool results."""

    def test_multimodal_tool_result_text_only(self) -> None:
        """OpenAI format_tool_result stores content blocks; chat() extracts text."""
        from macbot.providers.openai import OpenAIProvider

        provider = OpenAIProvider.__new__(OpenAIProvider)
        provider.model = "gpt-4o"

        content_blocks = [
            {"type": "text", "text": "Scanned PDF"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,aGVsbG8="}},
        ]

        msg = provider.format_tool_result("call_123", content_blocks)

        # The message stores the raw content blocks
        assert isinstance(msg.content, list)

    def test_string_tool_result_unchanged(self) -> None:
        """String tool result stays as string."""
        from macbot.providers.openai import OpenAIProvider

        provider = OpenAIProvider.__new__(OpenAIProvider)
        provider.model = "gpt-4o"

        msg = provider.format_tool_result("call_123", "plain text")

        assert msg.content == "plain text"


class TestLiteLLMMultimodalFallback:
    """Tests that LiteLLM extracts text-only from multimodal tool results."""

    def test_multimodal_tool_result_stored(self) -> None:
        """LiteLLM format_tool_result stores content blocks."""
        from macbot.providers.litellm_provider import LiteLLMProvider

        provider = LiteLLMProvider.__new__(LiteLLMProvider)
        provider.model = "anthropic/claude-sonnet-4-20250514"

        content_blocks = [
            {"type": "text", "text": "Scanned PDF"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,aGVsbG8="}},
        ]

        msg = provider.format_tool_result("call_123", content_blocks)

        assert isinstance(msg.content, list)

    def test_string_tool_result_unchanged(self) -> None:
        """String tool result stays as string."""
        from macbot.providers.litellm_provider import LiteLLMProvider

        provider = LiteLLMProvider.__new__(LiteLLMProvider)
        provider.model = "anthropic/claude-sonnet-4-20250514"

        msg = provider.format_tool_result("call_123", "plain text")

        assert msg.content == "plain text"


# ---------------------------------------------------------------------------
# Token estimation with images
# ---------------------------------------------------------------------------

class TestTokenEstimationImages:
    """Tests that image blocks use fixed estimate instead of stringifying base64."""

    def test_image_block_fixed_estimate(self) -> None:
        """Image blocks contribute ~3000 chars to estimate, not base64 length."""
        from macbot.providers.base import Message

        # Create a mock provider to test estimate_tokens
        class TestProvider:
            pass

        from macbot.providers.base import LLMProvider
        # Use the base class method directly
        large_b64 = "A" * 100000  # ~100KB of fake base64
        messages = [
            Message(
                role="tool",
                content=[
                    {"type": "text", "text": "PDF page"},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{large_b64}"}},
                ],
                tool_call_id="call_1",
            ),
        ]

        estimate = LLMProvider.estimate_tokens(None, messages)  # type: ignore[arg-type]

        # With the fix, the estimate should be much less than if we stringified the base64
        # 3000 (image) + ~50 (text block str) = ~3050 chars → ~1000 tokens
        # Without fix: ~100000 chars → ~33000 tokens
        assert estimate < 5000
