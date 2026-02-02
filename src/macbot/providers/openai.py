"""OpenAI LLM provider implementation."""

import json
from typing import Any

from openai import AsyncOpenAI

from macbot.providers.base import LLMProvider, LLMResponse, Message, StreamCallback, ToolCall


class OpenAIProvider(LLMProvider):
    """LLM provider for OpenAI models."""

    def __init__(self, api_key: str, model: str = "gpt-4o") -> None:
        super().__init__(api_key, model)
        self.client = AsyncOpenAI(api_key=api_key)

    async def chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        system_prompt: str | None = None,
        stream_callback: StreamCallback | None = None,
    ) -> LLMResponse:
        """Send a chat completion request to OpenAI."""
        # Convert messages to OpenAI format
        openai_messages: list[dict[str, Any]] = []

        if system_prompt:
            openai_messages.append({"role": "system", "content": system_prompt})

        for msg in messages:
            if msg.role == "assistant" and msg.tool_calls:
                # Assistant message with tool calls
                openai_msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": msg.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments),
                            },
                        }
                        for tc in msg.tool_calls
                    ],
                }
                openai_messages.append(openai_msg)
            elif msg.role == "tool":
                # Tool result message
                openai_messages.append({
                    "role": "tool",
                    "tool_call_id": msg.tool_call_id,
                    "content": msg.content or "",
                })
            else:
                openai_messages.append({"role": msg.role, "content": msg.content})

        # Build request kwargs
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": openai_messages,
        }

        if tools:
            # Convert from Anthropic-style to OpenAI-style tool format
            openai_tools = []
            for tool in tools:
                openai_tool = {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                        "parameters": tool.get("input_schema", {}),
                    },
                }
                openai_tools.append(openai_tool)
            kwargs["tools"] = openai_tools

        # Use streaming if callback provided
        if stream_callback:
            return await self._chat_stream(kwargs, stream_callback)

        # Make the API call (non-streaming)
        response = await self.client.chat.completions.create(**kwargs)

        # Parse response
        choice = response.choices[0]
        message = choice.message

        content = message.content
        tool_calls = []

        if message.tool_calls:
            for tc in message.tool_calls:
                arguments = {}
                if tc.function.arguments:
                    try:
                        arguments = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        arguments = {"raw": tc.function.arguments}

                tool_calls.append(
                    ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=arguments,
                    )
                )

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            stop_reason=choice.finish_reason,
            usage={
                "input_tokens": response.usage.prompt_tokens if response.usage else 0,
                "output_tokens": response.usage.completion_tokens if response.usage else 0,
            },
        )

    async def _chat_stream(
        self,
        kwargs: dict[str, Any],
        stream_callback: StreamCallback,
    ) -> LLMResponse:
        """Handle streaming chat completion."""
        kwargs["stream"] = True
        kwargs["stream_options"] = {"include_usage": True}

        content_chunks: list[str] = []
        tool_calls_data: dict[int, dict[str, Any]] = {}
        finish_reason = None
        usage = {"input_tokens": 0, "output_tokens": 0}

        async for chunk in await self.client.chat.completions.create(**kwargs):
            if chunk.usage:
                usage = {
                    "input_tokens": chunk.usage.prompt_tokens,
                    "output_tokens": chunk.usage.completion_tokens,
                }

            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta
            if chunk.choices[0].finish_reason:
                finish_reason = chunk.choices[0].finish_reason

            # Handle content
            if delta.content:
                content_chunks.append(delta.content)
                stream_callback(delta.content)

            # Handle tool calls
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_data:
                        tool_calls_data[idx] = {
                            "id": tc.id or "",
                            "name": tc.function.name if tc.function and tc.function.name else "",
                            "arguments": "",
                        }
                    if tc.id:
                        tool_calls_data[idx]["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            tool_calls_data[idx]["name"] = tc.function.name
                        if tc.function.arguments:
                            tool_calls_data[idx]["arguments"] += tc.function.arguments

        # Build tool calls
        tool_calls = []
        for idx in sorted(tool_calls_data.keys()):
            tc_data = tool_calls_data[idx]
            arguments = {}
            if tc_data["arguments"]:
                try:
                    arguments = json.loads(tc_data["arguments"])
                except json.JSONDecodeError:
                    arguments = {"raw": tc_data["arguments"]}
            tool_calls.append(
                ToolCall(
                    id=tc_data["id"],
                    name=tc_data["name"],
                    arguments=arguments,
                )
            )

        return LLMResponse(
            content="".join(content_chunks) if content_chunks else None,
            tool_calls=tool_calls,
            stop_reason=finish_reason,
            usage=usage,
        )

    def format_tool_result(self, tool_call_id: str, result: str) -> Message:
        """Format a tool result for OpenAI's format."""
        # OpenAI expects tool results as tool messages with tool_call_id
        return Message(role="tool", content=result, tool_call_id=tool_call_id)

    def format_tool_results_batch(
        self, tool_calls: list[ToolCall], results: list[str]
    ) -> list[dict[str, Any]]:
        """Format multiple tool results for OpenAI.

        Args:
            tool_calls: Original tool calls
            results: Results from executing the tools

        Returns:
            List of message dicts in OpenAI's expected format
        """
        return [
            {
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            }
            for tc, result in zip(tool_calls, results)
        ]
