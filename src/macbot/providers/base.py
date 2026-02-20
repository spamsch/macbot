"""Base LLM provider interface."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Callable
from typing import Any

from pydantic import BaseModel


# Type alias for streaming callback
StreamCallback = Callable[[str], None]


class Message(BaseModel):
    """A message in the conversation."""

    role: str  # "user", "assistant", "system", or "tool"
    content: str | list[dict[str, Any]] | None = None  # str for text, list for multimodal content blocks
    tool_calls: list["ToolCall"] | None = None  # For assistant messages with tool calls
    tool_call_id: str | None = None  # For tool result messages

    @property
    def content_text(self) -> str:
        """Extract the text portion of content for logging/display.

        Returns the string as-is for str content, or extracts the first
        text block from a content block list.
        """
        if isinstance(self.content, str):
            return self.content
        if isinstance(self.content, list):
            for block in self.content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "")
                    return str(text)
            return ""
        return ""


class ToolCall(BaseModel):
    """A tool call requested by the LLM."""

    id: str
    name: str
    arguments: dict[str, Any]


class LLMResponse(BaseModel):
    """Response from an LLM."""

    content: str | None = None
    tool_calls: list[ToolCall] = []
    stop_reason: str | None = None
    usage: dict[str, int] = {}


class LLMProvider(ABC):
    """Abstract base class for LLM providers.

    Implementations should handle:
    - Chat completions
    - Tool/function calling
    - Streaming (optional)
    """

    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    @abstractmethod
    async def chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        system_prompt: str | None = None,
        stream_callback: StreamCallback | None = None,
    ) -> LLMResponse:
        """Send a chat completion request.

        Args:
            messages: Conversation history
            tools: Tool definitions for function calling
            system_prompt: System prompt to set context
            stream_callback: Optional callback for streaming text chunks

        Returns:
            LLM response with content and/or tool calls
        """
        ...

    def get_context_window(self) -> int | None:
        """Return the model's context window size in tokens.

        Returns None if unknown. Subclasses should override with
        provider-specific lookups.
        """
        return None

    def estimate_tokens(
        self,
        messages: list[Message],
        system_prompt: str | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> int:
        """Estimate token count for a request payload.

        Conservative character-based heuristic (total_chars // 3).
        Subclasses should override with provider-specific tokenisers.
        """
        total_chars = 0
        if system_prompt:
            total_chars += len(system_prompt)
        for msg in messages:
            if isinstance(msg.content, str):
                total_chars += len(msg.content)
            elif isinstance(msg.content, list):
                for block in msg.content:
                    if isinstance(block, dict):
                        if block.get("type") == "image_url":
                            # Estimate ~1000 tokens (~3000 chars) per image
                            # instead of stringifying the base64 data
                            total_chars += 3000
                        else:
                            total_chars += len(str(block))
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    total_chars += len(tc.name) + len(str(tc.arguments))
        if tools:
            total_chars += len(str(tools))
        return total_chars // 3

    @abstractmethod
    def format_tool_result(
        self, tool_call_id: str, result: str | list[dict[str, Any]]
    ) -> Message:
        """Format a tool result as a message.

        Args:
            tool_call_id: ID of the tool call
            result: Result from the tool execution (string or content blocks)

        Returns:
            Formatted message for the conversation
        """
        ...
