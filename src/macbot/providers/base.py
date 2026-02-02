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
    content: str | None = None
    tool_calls: list["ToolCall"] | None = None  # For assistant messages with tool calls
    tool_call_id: str | None = None  # For tool result messages


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

    @abstractmethod
    def format_tool_result(self, tool_call_id: str, result: str) -> Message:
        """Format a tool result as a message.

        Args:
            tool_call_id: ID of the tool call
            result: Result from the tool execution

        Returns:
            Formatted message for the conversation
        """
        ...
