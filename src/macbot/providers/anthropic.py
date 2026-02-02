"""Anthropic (Claude) LLM provider implementation."""

from typing import Any

from anthropic import AsyncAnthropic

from macbot.providers.base import LLMProvider, LLMResponse, Message, StreamCallback, ToolCall


class AnthropicProvider(LLMProvider):
    """LLM provider for Anthropic's Claude models."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514") -> None:
        super().__init__(api_key, model)
        self.client = AsyncAnthropic(api_key=api_key)

    async def chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        system_prompt: str | None = None,
        stream_callback: StreamCallback | None = None,
    ) -> LLMResponse:
        """Send a chat completion request to Claude."""
        # Convert messages to Anthropic format
        anthropic_messages: list[dict[str, Any]] = []
        for msg in messages:
            if msg.role == "system":
                # System messages are handled separately in Anthropic
                continue
            elif msg.role == "assistant" and msg.tool_calls:
                # Assistant message with tool calls
                content_blocks: list[dict[str, Any]] = []
                if msg.content:
                    content_blocks.append({"type": "text", "text": msg.content})
                for tc in msg.tool_calls:
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.name,
                        "input": tc.arguments,
                    })
                anthropic_messages.append({"role": "assistant", "content": content_blocks})
            elif msg.role == "tool":
                # Tool result - Anthropic expects this as a user message with tool_result block
                anthropic_messages.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": msg.tool_call_id,
                            "content": msg.content or "",
                        }
                    ],
                })
            else:
                anthropic_messages.append({"role": msg.role, "content": msg.content})

        # Build request kwargs
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": anthropic_messages,
        }

        if system_prompt:
            kwargs["system"] = system_prompt

        if tools:
            kwargs["tools"] = tools

        # Use streaming if callback provided
        if stream_callback:
            return await self._chat_stream(kwargs, stream_callback)

        # Make the API call (non-streaming)
        response = await self.client.messages.create(**kwargs)

        # Parse response
        content = None
        tool_calls = []

        for block in response.content:
            if block.type == "text":
                content = block.text
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=dict(block.input) if block.input else {},
                    )
                )

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            stop_reason=response.stop_reason,
            usage={
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
        )

    async def _chat_stream(
        self,
        kwargs: dict[str, Any],
        stream_callback: StreamCallback,
    ) -> LLMResponse:
        """Handle streaming chat completion."""
        import json

        content_chunks: list[str] = []
        tool_calls: list[ToolCall] = []
        current_tool: dict[str, Any] | None = None
        stop_reason = None
        usage = {"input_tokens": 0, "output_tokens": 0}

        async with self.client.messages.stream(**kwargs) as stream:
            async for event in stream:
                if event.type == "message_start":
                    if event.message.usage:
                        usage["input_tokens"] = event.message.usage.input_tokens
                elif event.type == "message_delta":
                    if event.delta.stop_reason:
                        stop_reason = event.delta.stop_reason
                    if event.usage:
                        usage["output_tokens"] = event.usage.output_tokens
                elif event.type == "content_block_start":
                    if event.content_block.type == "tool_use":
                        current_tool = {
                            "id": event.content_block.id,
                            "name": event.content_block.name,
                            "input_json": "",
                        }
                elif event.type == "content_block_delta":
                    if event.delta.type == "text_delta":
                        content_chunks.append(event.delta.text)
                        stream_callback(event.delta.text)
                    elif event.delta.type == "input_json_delta" and current_tool:
                        current_tool["input_json"] += event.delta.partial_json
                elif event.type == "content_block_stop":
                    if current_tool:
                        arguments = {}
                        if current_tool["input_json"]:
                            try:
                                arguments = json.loads(current_tool["input_json"])
                            except json.JSONDecodeError:
                                arguments = {"raw": current_tool["input_json"]}
                        tool_calls.append(
                            ToolCall(
                                id=current_tool["id"],
                                name=current_tool["name"],
                                arguments=arguments,
                            )
                        )
                        current_tool = None

        return LLMResponse(
            content="".join(content_chunks) if content_chunks else None,
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            usage=usage,
        )

    def format_tool_result(self, tool_call_id: str, result: str) -> Message:
        """Format a tool result for Anthropic's format."""
        # Use unified Message format - conversion to Anthropic's format happens in chat()
        return Message(role="tool", content=result, tool_call_id=tool_call_id)

    def format_tool_results_batch(
        self, results: list[tuple[str, str]]
    ) -> dict[str, Any]:
        """Format multiple tool results for Anthropic.

        Args:
            results: List of (tool_call_id, result) tuples

        Returns:
            Message dict in Anthropic's expected format
        """
        return {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": tool_id, "content": result}
                for tool_id, result in results
            ],
        }
