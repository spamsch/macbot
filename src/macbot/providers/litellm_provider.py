"""LiteLLM unified provider implementation.

Supports 100+ LLM providers through a single interface using the model string
format: provider/model (e.g., anthropic/claude-sonnet-4-20250514, openai/gpt-4o).
"""

import json
import logging
import os
import re
from typing import Any

import litellm

from macbot.providers.base import (
    LLMProvider,
    LLMResponse,
    Message,
    StreamCallback,
    ToolCall,
)

logger = logging.getLogger(__name__)


class LiteLLMProvider(LLMProvider):
    """Unified LLM provider using LiteLLM.

    Supports 100+ providers via model string format:
    - anthropic/claude-sonnet-4-20250514
    - openai/gpt-4o
    - groq/llama3-70b-8192
    - ollama/llama2

    API keys are routed based on the model prefix. You can either:
    1. Set them via environment variables (ANTHROPIC_API_KEY, OPENAI_API_KEY, etc.)
    2. Pass them via the api_key parameter (will be set in environment)
    """

    def __init__(self, model: str, api_key: str | None = None, api_base: str | None = None) -> None:
        """Initialize the LiteLLM provider.

        Args:
            model: Model string in provider/model format
            api_key: Optional API key (will be set in environment for the provider)
            api_base: Optional API base URL (e.g. for Pico/Ollama local servers)
        """
        # Translate pico/ prefix to ollama_chat/ for LiteLLM
        if model.startswith("pico/"):
            model = "ollama_chat/" + model[5:]

        # ChatGPT subscription models (Codex / GPT-5.x) authenticate with OAuth
        # tokens, not an API key. Bridge the Codex CLI credentials into the
        # environment LiteLLM's chatgpt/ provider expects.
        if model.startswith("chatgpt/"):
            from macbot.providers.chatgpt_auth import sync_codex_auth

            if not sync_codex_auth():
                logger.warning(
                    "chatgpt/ model selected but no Codex credentials found. "
                    "Sign in with the Codex CLI (`codex login`) or set CHATGPT_TOKEN_DIR."
                )

        super().__init__(api_key or "", model)
        self.api_base = api_base
        self._context_window: int | None = None
        self._context_window_looked_up: bool = False

        # Suppress LiteLLM's verbose logging
        litellm.suppress_debug_info = True

        # Set API key in environment if provided
        if api_key:
            provider = model.split("/")[0] if "/" in model else "openai"
            key_map = {
                "anthropic": "ANTHROPIC_API_KEY",
                "openai": "OPENAI_API_KEY",
                "openrouter": "OPENROUTER_API_KEY",
                "gemini": "GEMINI_API_KEY",
                "groq": "GROQ_API_KEY",
                "mistral": "MISTRAL_API_KEY",
                "cohere": "COHERE_API_KEY",
                "together_ai": "TOGETHER_API_KEY",
                "replicate": "REPLICATE_API_KEY",
            }
            if provider in key_map:
                os.environ[key_map[provider]] = api_key

    def get_context_window(self) -> int | None:
        """Return the model's context window using litellm model info.

        Caches the result (including None) so the lookup happens at most once.
        """
        if self._context_window_looked_up:
            return self._context_window
        self._context_window_looked_up = True
        try:
            info = litellm.get_model_info(self.model)
            self._context_window = info.get("max_input_tokens")
        except Exception:
            logger.debug("Could not look up context window for %s", self.model)
            self._context_window = None
        return self._context_window

    def estimate_tokens(
        self,
        messages: list[Message],
        system_prompt: str | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> int:
        """Estimate token count using litellm.token_counter.

        Falls back to the base class character heuristic on failure.
        """
        try:
            litellm_messages: list[dict[str, Any]] = []
            if system_prompt:
                litellm_messages.append({"role": "system", "content": system_prompt})
            for msg in messages:
                if msg.role == "assistant" and msg.tool_calls:
                    litellm_messages.append({
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
                    })
                elif msg.role == "tool":
                    # Extract text-only for token estimation
                    if isinstance(msg.content, list):
                        text_parts = [
                            block["text"]
                            for block in msg.content
                            if isinstance(block, dict) and block.get("type") == "text"
                        ]
                        est_content = "\n".join(text_parts) if text_parts else ""
                    else:
                        est_content = msg.content or ""
                    litellm_messages.append({
                        "role": "tool",
                        "tool_call_id": msg.tool_call_id,
                        "content": est_content,
                    })
                else:
                    litellm_messages.append({
                        "role": msg.role,
                        "content": msg.content,
                    })

            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": litellm_messages,
            }
            if tools:
                kwargs["tools"] = [
                    {
                        "type": "function",
                        "function": {
                            "name": t["name"],
                            "description": t.get("description", ""),
                            "parameters": t.get("input_schema", {}),
                        },
                    }
                    for t in tools
                ]
            return litellm.token_counter(**kwargs)
        except Exception:
            logger.debug("litellm.token_counter failed, using char heuristic")
            return super().estimate_tokens(messages, system_prompt, tools)

    async def chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        system_prompt: str | None = None,
        stream_callback: StreamCallback | None = None,
    ) -> LLMResponse:
        """Send a chat completion request via LiteLLM.

        Args:
            messages: Conversation history
            tools: Tool definitions for function calling
            system_prompt: System prompt to set context
            stream_callback: Optional callback for streaming text chunks

        Returns:
            LLM response with content and/or tool calls
        """
        # ChatGPT subscription (Codex backend) is Responses-API native and
        # rejects the chat/completions route for most models. Route it through
        # the Responses API instead.
        if self.model.startswith("chatgpt/"):
            return await self._chat_responses(messages, tools, system_prompt, stream_callback)

        # Build messages in OpenAI format (LiteLLM uses this internally)
        litellm_messages: list[dict[str, Any]] = []

        # Some local model servers (e.g. Pico) don't support tool_call /
        # tool roles in their chat templates.  For those models we flatten
        # tool exchanges into plain assistant/user messages.
        flatten_tools = self.model.startswith("ollama_chat/")

        if system_prompt:
            litellm_messages.append({"role": "system", "content": system_prompt})

        for msg in messages:
            if msg.role == "assistant" and msg.tool_calls:
                if flatten_tools:
                    # Convert tool calls to plain text the model can understand
                    parts = []
                    if msg.content:
                        parts.append(msg.content)
                    for tc in msg.tool_calls:
                        args_str = json.dumps(tc.arguments) if tc.arguments else "{}"
                        parts.append(f"<|channel|>commentary to=functions.{tc.name} "
                                     f"<|constrain|>json<|message|>{args_str}<|end|>")
                    litellm_messages.append({
                        "role": "assistant",
                        "content": "\n".join(parts),
                    })
                else:
                    litellm_messages.append({
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
                    })
            elif msg.role == "tool":
                # Extract text-only content for tool results (images not supported)
                if isinstance(msg.content, list):
                    text_parts = [
                        block["text"]
                        for block in msg.content
                        if isinstance(block, dict) and block.get("type") == "text"
                    ]
                    tool_text = "\n".join(text_parts) if text_parts else ""
                else:
                    tool_text = msg.content or ""

                if flatten_tools:
                    # Convert tool result to a user message
                    litellm_messages.append({
                        "role": "user",
                        "content": f"[Tool result: {tool_text}]",
                    })
                else:
                    litellm_messages.append({
                        "role": "tool",
                        "tool_call_id": msg.tool_call_id,
                        "content": tool_text,
                    })
            else:
                # Pass content as-is — LiteLLM/OpenAI natively support
                # content block arrays for multimodal messages
                litellm_messages.append({
                    "role": msg.role,
                    "content": msg.content,
                })

        # Build request kwargs
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": litellm_messages,
        }

        if self.api_base:
            kwargs["api_base"] = self.api_base

        # Convert tools to OpenAI format (LiteLLM expects this)
        if tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get("input_schema", {}),
                    },
                }
                for t in tools
            ]

        if stream_callback:
            return await self._chat_stream(kwargs, stream_callback)

        # Non-streaming request
        response = await litellm.acompletion(**kwargs)
        return self._parse_response(response)

    async def _chat_stream(
        self,
        kwargs: dict[str, Any],
        stream_callback: StreamCallback,
    ) -> LLMResponse:
        """Handle streaming chat completion.

        Args:
            kwargs: Request parameters
            stream_callback: Callback for text chunks

        Returns:
            Complete LLM response after stream finishes
        """
        kwargs["stream"] = True
        kwargs["stream_options"] = {"include_usage": True}

        content_chunks: list[str] = []
        reasoning_chunks: list[str] = []
        tool_calls_data: dict[int, dict[str, Any]] = {}
        finish_reason: str | None = None
        usage = {"input_tokens": 0, "output_tokens": 0}

        # Buffer for detecting and suppressing protocol tokens during streaming.
        # Once we know the stream is clean (no protocol tokens in first chunk)
        # or we've found the final channel marker, we forward directly.
        _stream_buf = ""
        _stream_forwarding = False  # True once we're past any protocol preamble
        _FINAL_MARKER = "<|channel|>final<|message|>"
        _PROTOCOL_START = "<|"

        response = await litellm.acompletion(**kwargs)

        async for chunk in response:
            # Handle usage if present (comes in final chunk)
            if hasattr(chunk, "usage") and chunk.usage:
                usage = {
                    "input_tokens": getattr(chunk.usage, "prompt_tokens", 0),
                    "output_tokens": getattr(chunk.usage, "completion_tokens", 0),
                }

            if not chunk.choices:
                continue

            choice = chunk.choices[0]
            delta = choice.delta

            if choice.finish_reason:
                finish_reason = choice.finish_reason

            # Capture native reasoning tokens from reasoning models (e.g.
            # gpt-5.x, DeepSeek-R1). LiteLLM normalizes these to
            # delta.reasoning_content, separate from user-facing content.
            reasoning_piece = getattr(delta, "reasoning_content", None)
            if reasoning_piece:
                reasoning_chunks.append(reasoning_piece)

            # Handle content chunks
            if delta.content:
                content_chunks.append(delta.content)

                if _stream_forwarding:
                    # Already past protocol preamble — forward directly
                    stream_callback(delta.content)
                else:
                    # Still buffering — check for protocol tokens
                    _stream_buf += delta.content

                    if _FINAL_MARKER in _stream_buf:
                        # Found the final channel — forward everything after it
                        _, after = _stream_buf.split(_FINAL_MARKER, 1)
                        if after:
                            stream_callback(after)
                        _stream_forwarding = True
                    elif _PROTOCOL_START not in _stream_buf and len(_stream_buf) > 10:
                        # No protocol tokens detected — stream is clean, forward all
                        stream_callback(_stream_buf)
                        _stream_forwarding = True

            # Handle tool call chunks
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_data:
                        tool_calls_data[idx] = {"id": "", "name": "", "arguments": ""}
                    if tc.id:
                        tool_calls_data[idx]["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            tool_calls_data[idx]["name"] = tc.function.name
                        if tc.function.arguments:
                            tool_calls_data[idx]["arguments"] += tc.function.arguments

        # Flush remaining buffer if stream ended while still buffering
        if not _stream_forwarding and _stream_buf:
            cleaned = self._strip_protocol_tokens(_stream_buf)
            if cleaned:
                stream_callback(cleaned)

        # Build final tool calls list
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

        content = "".join(content_chunks) if content_chunks else None

        # Fallback: extract tool calls from protocol tokens when the API
        # didn't return structured tool_calls (common with local models).
        if not tool_calls and content:
            tool_calls = self._extract_tool_calls_from_protocol(content)

        # Internal reasoning: native reasoning tokens (reasoning models) plus
        # any reasoning leaked into protocol tokens (local gpt-oss models).
        internal_reasoning = "".join(reasoning_chunks).strip() or None
        if content:
            protocol_reasoning = self._extract_reasoning_from_protocol(content)
            internal_reasoning = self._merge_reasoning(internal_reasoning, protocol_reasoning)
            content = self._strip_protocol_tokens(content)

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            stop_reason=finish_reason,
            usage=usage,
            internal_reasoning=internal_reasoning,
        )

    async def _chat_responses(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None,
        system_prompt: str | None,
        stream_callback: StreamCallback | None,
    ) -> LLMResponse:
        """Send a request via the OpenAI Responses API (ChatGPT/Codex backend).

        The ChatGPT subscription backend is Responses-native and streaming-only;
        LiteLLM aggregates the backend stream into a single response for us. We
        therefore make a non-streaming call and, when a stream_callback is given,
        forward the final text once (token-level streaming is not exposed cleanly
        for this backend in LiteLLM).
        """
        input_items = self._to_responses_input(messages)

        kwargs: dict[str, Any] = {
            "model": self.model,
            "input": input_items,
        }
        if system_prompt:
            kwargs["instructions"] = system_prompt
        if self.api_base:
            kwargs["api_base"] = self.api_base
        if tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {}),
                }
                for t in tools
            ]

        response = await litellm.aresponses(**kwargs)
        result = self._parse_responses(response)

        if stream_callback and result.content:
            stream_callback(result.content)

        return result

    @staticmethod
    def _to_responses_input(messages: list[Message]) -> list[dict[str, Any]]:
        """Translate internal Message history into Responses API input items."""
        items: list[dict[str, Any]] = []
        for msg in messages:
            if msg.role == "assistant":
                text = msg.content_text
                if text:
                    items.append({
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": text}],
                    })
                for tc in msg.tool_calls or []:
                    items.append({
                        "type": "function_call",
                        "call_id": tc.id,
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments),
                    })
            elif msg.role == "tool":
                items.append({
                    "type": "function_call_output",
                    "call_id": msg.tool_call_id,
                    "output": msg.content_text,
                })
            elif msg.role == "system":
                items.append({
                    "role": "system",
                    "content": [{"type": "input_text", "text": msg.content_text}],
                })
            else:  # user
                items.append({
                    "role": "user",
                    "content": LiteLLMProvider._to_responses_content(msg.content),
                })
        return items

    @staticmethod
    def _to_responses_content(
        content: str | list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        """Convert message content into Responses API input content parts."""
        if isinstance(content, str):
            return [{"type": "input_text", "text": content}]
        if isinstance(content, list):
            parts: list[dict[str, Any]] = []
            for block in content:
                if not isinstance(block, dict):
                    parts.append({"type": "input_text", "text": str(block)})
                    continue
                btype = block.get("type")
                if btype == "text":
                    parts.append({"type": "input_text", "text": block.get("text", "")})
                elif btype == "input_text":
                    parts.append(block)
                elif btype == "image_url":
                    image = block.get("image_url")
                    url = image.get("url") if isinstance(image, dict) else image
                    parts.append({"type": "input_image", "image_url": url})
                elif btype == "input_image":
                    parts.append(block)
                else:
                    parts.append({"type": "input_text", "text": str(block)})
            return parts
        return [{"type": "input_text", "text": ""}]

    def _parse_responses(self, response: Any) -> LLMResponse:
        """Parse a LiteLLM Responses API result into an LLMResponse."""
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        for item in getattr(response, "output", None) or []:
            data = item.model_dump() if hasattr(item, "model_dump") else dict(item)
            itype = data.get("type")
            if itype == "message":
                for block in data.get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "output_text":
                        content_parts.append(block.get("text", ""))
            elif itype == "function_call":
                raw_args = data.get("arguments") or ""
                try:
                    arguments = json.loads(raw_args) if raw_args else {}
                except json.JSONDecodeError:
                    arguments = {"raw": raw_args}
                tool_calls.append(
                    ToolCall(
                        id=data.get("call_id") or data.get("id") or "",
                        name=data.get("name", ""),
                        arguments=arguments,
                    )
                )
            elif itype == "reasoning":
                for summary in data.get("summary") or []:
                    if isinstance(summary, dict):
                        text = summary.get("text", "")
                        if text:
                            reasoning_parts.append(text)

        content = "".join(content_parts) or None
        if content is None:
            # Fall back to the convenience aggregate if no message items.
            content = getattr(response, "output_text", None) or None

        usage_obj = getattr(response, "usage", None)
        usage = {
            "input_tokens": getattr(usage_obj, "input_tokens", 0) if usage_obj else 0,
            "output_tokens": getattr(usage_obj, "output_tokens", 0) if usage_obj else 0,
        }

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            stop_reason="tool_calls" if tool_calls else getattr(response, "status", None),
            usage=usage,
            internal_reasoning="\n".join(reasoning_parts).strip() or None,
        )

    @staticmethod
    def _extract_tool_calls_from_protocol(text: str) -> list[ToolCall]:
        """Extract tool calls from model protocol tokens.

        Some local models (e.g. gpt-oss via Pico) embed function calls in
        protocol tokens instead of using the OpenAI tool_calls format:
            <|channel|>commentary to=functions.NAME <|constrain|>json<|message|>ARGS

        This parses those into proper ToolCall objects.
        """
        calls: list[ToolCall] = []
        # Match: to=functions.NAME ... <|constrain|>json<|message|>ARGS
        pattern = re.compile(
            r"to=functions\.(\w+)\s*"           # function name
            r"<\|constrain\|>json<\|message\|>"  # delimiter
            r"(.*?)"                              # JSON arguments
            r"(?:<\|end\|>|<\|start\|>|$)",       # end of block
            re.DOTALL,
        )
        for match in pattern.finditer(text):
            name = match.group(1)
            raw_args = match.group(2).strip()
            arguments: dict[str, Any] = {}
            if raw_args:
                try:
                    arguments = json.loads(raw_args)
                except json.JSONDecodeError:
                    # Try to fix truncated JSON
                    if not raw_args.endswith("}"):
                        raw_args += "}"
                    try:
                        arguments = json.loads(raw_args)
                    except json.JSONDecodeError:
                        arguments = {"raw": raw_args}
            calls.append(ToolCall(
                id=f"call_{name}_{len(calls)}",
                name=name,
                arguments=arguments,
            ))
        return calls

    @staticmethod
    def _merge_reasoning(primary: str | None, extra: str | None) -> str | None:
        """Combine two reasoning sources, dropping empties and duplicates."""
        parts = [p.strip() for p in (primary, extra) if p and p.strip()]
        if not parts:
            return None
        if len(parts) == 2 and parts[0] == parts[1]:
            return parts[0]
        return "\n".join(parts)

    @staticmethod
    def _extract_reasoning_from_protocol(text: str) -> str | None:
        """Extract internal reasoning/analysis from protocol tokens.

        Models like gpt-4.1 produce reasoning in protocol blocks:
            <|channel|>analysis<|message|>...reasoning...<|end|>
        This extracts that reasoning before _strip_protocol_tokens removes it.
        """
        # Match analysis or commentary blocks
        reasoning_parts: list[str] = []
        for match in re.finditer(
            r"<\|channel\|>(?:analysis|commentary)\s*<\|(?:constrain\|>\w+<\|)?message\|>"
            r"(.*?)"
            r"(?:<\|end\|>|<\|start\|>|$)",
            text,
            re.DOTALL,
        ):
            part = match.group(1).strip()
            if part:
                reasoning_parts.append(part)
        return "\n".join(reasoning_parts) if reasoning_parts else None

    @staticmethod
    def _strip_protocol_tokens(text: str) -> str:
        """Strip leaked model protocol/reasoning tokens from content.

        Some models (e.g. GPT-5.x) may leak internal channel markers like
        <|channel|>analysis<|message|>...<|end|><|start|>assistant<|channel|>final<|message|>...
        This extracts only the final user-facing content.
        """
        # If there's a final channel message, extract just that content
        final_match = re.search(
            r"<\|channel\|>final<\|message\|>",
            text,
        )
        if final_match:
            text = text[final_match.end():]
            # Strip trailing protocol tokens from the extracted content
            text = re.sub(r"<\|end\|>.*", "", text, flags=re.DOTALL)
            return text.strip()

        # No final channel — strip all protocol-enclosed blocks.
        # Pattern: <|token|>...(content)...<|end|> or <|token|>...(content)...<|start|>
        # Remove complete protocol blocks (analysis, commentary, etc.)
        text = re.sub(
            r"<\|(?:channel|start)\|>.*?(?=<\|(?:start|end)\|>|$)",
            "",
            text,
            flags=re.DOTALL,
        )

        # Strip any remaining individual protocol tokens
        text = re.sub(r"<\|(?:channel|message|start|end|constrain|system)\|>", "", text)

        return text.strip()

    def _parse_response(self, response: Any) -> LLMResponse:
        """Parse a non-streaming LiteLLM response.

        Args:
            response: LiteLLM completion response

        Returns:
            Parsed LLMResponse
        """
        choice = response.choices[0]
        message = choice.message

        # Parse tool calls if present
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

        content = message.content

        # Fallback: extract tool calls from protocol tokens when the API
        # didn't return structured tool_calls (common with local models).
        if not tool_calls and content:
            tool_calls = self._extract_tool_calls_from_protocol(content)

        # Native reasoning tokens (reasoning models expose these on the
        # message as reasoning_content) plus any protocol-token reasoning.
        internal_reasoning = (getattr(message, "reasoning_content", None) or "").strip() or None
        if content:
            protocol_reasoning = self._extract_reasoning_from_protocol(content)
            internal_reasoning = self._merge_reasoning(internal_reasoning, protocol_reasoning)
            content = self._strip_protocol_tokens(content)

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            stop_reason=choice.finish_reason,
            usage={
                "input_tokens": response.usage.prompt_tokens if response.usage else 0,
                "output_tokens": response.usage.completion_tokens if response.usage else 0,
            },
            internal_reasoning=internal_reasoning,
        )

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
        return Message(role="tool", content=result, tool_call_id=tool_call_id)
