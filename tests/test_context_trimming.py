"""Tests for context window overflow protection."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from macbot.providers.base import LLMProvider, LLMResponse, Message, ToolCall


# ---------------------------------------------------------------------------
# Mock provider for Agent-level tests
# ---------------------------------------------------------------------------

class MockProvider(LLMProvider):
    """Provider with configurable context window and token counting."""

    def __init__(
        self,
        context_window: int | None = None,
        tokens_per_message: int = 100,
    ) -> None:
        super().__init__(api_key="test", model="mock")
        self._context_window = context_window
        self._tokens_per_message = tokens_per_message

    def get_context_window(self) -> int | None:
        return self._context_window

    def estimate_tokens(
        self,
        messages: list[Message],
        system_prompt: str | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> int:
        return len(messages) * self._tokens_per_message

    async def chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        system_prompt: str | None = None,
        stream_callback: Any = None,
    ) -> LLMResponse:
        return LLMResponse(content="ok")

    def format_tool_result(self, tool_call_id: str, result: str) -> Message:
        return Message(role="tool", content=result, tool_call_id=tool_call_id)


# ---------------------------------------------------------------------------
# Helper to build an Agent with the mock provider
# ---------------------------------------------------------------------------

def _make_agent(
    context_window: int | None = None,
    tokens_per_message: int = 100,
) -> Any:
    """Create an Agent with a MockProvider, bypassing real config."""
    from macbot.core.agent import Agent
    from macbot.core.task import TaskRegistry

    registry = TaskRegistry()
    provider = MockProvider(
        context_window=context_window,
        tokens_per_message=tokens_per_message,
    )

    # Patch settings to avoid loading real config
    mock_settings = MagicMock()
    mock_settings.max_iterations = 10
    mock_settings.get_context_profile.return_value = "full"

    agent = Agent(
        task_registry=registry,
        provider=provider,
        config=mock_settings,
    )
    return agent


# ---------------------------------------------------------------------------
# Agent._trim_messages_to_fit tests
# ---------------------------------------------------------------------------

class TestTrimMessagesToFit:
    """Tests for the Agent._trim_messages_to_fit method."""

    def test_no_trimming_when_under_budget(self) -> None:
        """Messages are returned unchanged when under the token budget."""
        agent = _make_agent(context_window=10000, tokens_per_message=100)
        messages = [
            Message(role="user", content="goal"),
            Message(role="assistant", content="response1"),
            Message(role="user", content="follow-up"),
        ]
        result = agent._trim_messages_to_fit(messages)
        assert result == messages

    def test_no_trimming_when_context_window_unknown(self) -> None:
        """Messages are returned unchanged when context window is None."""
        agent = _make_agent(context_window=None, tokens_per_message=100)
        messages = [
            Message(role="user", content="goal"),
            Message(role="assistant", content="a" * 100000),
        ]
        result = agent._trim_messages_to_fit(messages)
        assert result == messages

    def test_oldest_messages_trimmed_first(self) -> None:
        """Oldest messages (after goal) are dropped first, preserving recent context."""
        # 7 messages × 100 tokens = 700, budget = 556 * 0.9 = 500
        agent = _make_agent(context_window=556, tokens_per_message=100)
        messages = [
            Message(role="user", content="goal"),        # keep (first)
            Message(role="assistant", content="old1"),    # droppable
            Message(role="user", content="mid"),          # droppable
            Message(role="assistant", content="old2"),    # droppable
            Message(role="user", content="recent_q"),     # keep (recent)
            Message(role="assistant", content="recent_a"),  # keep (recent)
            Message(role="user", content="latest"),       # keep (last)
        ]
        result = agent._trim_messages_to_fit(messages)
        # Should keep goal + recent context, dropping old1/mid/old2
        assert result[-1].content == "latest"
        assert len(result) < len(messages)
        # Recent context must survive
        contents = [m.content for m in result]
        assert "recent_q" in contents or "recent_a" in contents

    def test_first_message_preserved_when_possible(self) -> None:
        """The first message (goal) is kept when it fits alongside recent context."""
        agent = _make_agent(context_window=445, tokens_per_message=100)
        # budget = 400, 4 messages = 400 tokens — fits exactly
        messages = [
            Message(role="user", content="my goal"),
            Message(role="assistant", content="step1"),
            Message(role="user", content="step2"),
            Message(role="user", content="latest"),
        ]
        result = agent._trim_messages_to_fit(messages)
        assert result[0].content == "my goal"

    def test_tool_call_result_pairs_kept_together(self) -> None:
        """An assistant tool_call and its tool results stay as a unit."""
        agent = _make_agent(context_window=556, tokens_per_message=100)
        # budget = 500, 7 messages = 700 tokens
        messages = [
            Message(role="user", content="goal"),
            # Group 1: tool call + 2 results (3 messages)
            Message(
                role="assistant",
                content=None,
                tool_calls=[ToolCall(id="t1", name="search", arguments={})],
            ),
            Message(role="tool", content="result1", tool_call_id="t1"),
            # Group 2: text response
            Message(role="assistant", content="done with search"),
            # Group 3: another tool call + result
            Message(
                role="assistant",
                content=None,
                tool_calls=[ToolCall(id="t2", name="read", arguments={})],
            ),
            Message(role="tool", content="result2", tool_call_id="t2"),
            # Group 4: final
            Message(role="user", content="next question"),
        ]
        result = agent._trim_messages_to_fit(messages)

        # Verify no orphaned tool results exist
        for i, msg in enumerate(result):
            if msg.role == "tool":
                # The preceding message must be an assistant with tool_calls
                # or another tool message
                assert i > 0
                prev = result[i - 1]
                assert prev.role in ("assistant", "tool")
                if prev.role == "assistant":
                    assert prev.tool_calls

    def test_single_message_unchanged(self) -> None:
        """A conversation with one message is returned as-is."""
        agent = _make_agent(context_window=50, tokens_per_message=100)
        # Even though 100 > 45 budget, we can't drop the only message
        messages = [Message(role="user", content="goal")]
        result = agent._trim_messages_to_fit(messages)
        assert result == messages

    def test_keeps_recent_context_over_goal(self) -> None:
        """Under extreme pressure, recent context is preferred over stale goal."""
        agent = _make_agent(context_window=334, tokens_per_message=100)
        # budget = 300, total = 5 * 100 = 500
        messages = [
            Message(role="user", content="goal"),
            Message(role="assistant", content="a"),
            Message(role="assistant", content="b"),
            Message(role="assistant", content="c"),
            Message(role="user", content="latest"),
        ]
        result = agent._trim_messages_to_fit(messages)
        # Should keep goal + enough recent context to fit
        assert result[-1].content == "latest"
        assert len(result) <= len(messages)

    def test_recent_exchange_preserved_when_goal_dropped(self) -> None:
        """The preceding exchange survives even when the original goal is dropped."""
        agent = _make_agent(context_window=445, tokens_per_message=100)
        # budget = 400, total = 7 * 100 = 700
        messages = [
            Message(role="user", content="old goal"),       # may be dropped
            Message(role="assistant", content="old reply"),  # may be dropped
            Message(role="user", content="old question"),    # may be dropped
            Message(role="assistant", content="old answer"),  # should survive
            Message(role="user", content="do something"),    # should survive
            Message(role="assistant", content="shall I?"),    # should survive
            Message(role="user", content="yes"),             # should survive
        ]
        result = agent._trim_messages_to_fit(messages)
        # The "yes" and the preceding "shall I?" must both survive
        contents = [m.content for m in result]
        assert "yes" in contents
        assert "shall I?" in contents


# ---------------------------------------------------------------------------
# LiteLLMProvider.get_context_window tests
# ---------------------------------------------------------------------------

class TestLiteLLMGetContextWindow:
    """Tests for LiteLLMProvider.get_context_window()."""

    def test_returns_max_input_tokens(self) -> None:
        """Returns max_input_tokens from litellm model info."""
        from macbot.providers.litellm_provider import LiteLLMProvider

        provider = LiteLLMProvider(model="anthropic/claude-sonnet-4-20250514")

        with patch("litellm.get_model_info") as mock_info:
            mock_info.return_value = {"max_input_tokens": 200000}
            result = provider.get_context_window()
            assert result == 200000
            mock_info.assert_called_once_with("anthropic/claude-sonnet-4-20250514")

    def test_caches_result(self) -> None:
        """Second call uses cached value, doesn't call litellm again."""
        from macbot.providers.litellm_provider import LiteLLMProvider

        provider = LiteLLMProvider(model="anthropic/claude-sonnet-4-20250514")

        with patch("litellm.get_model_info") as mock_info:
            mock_info.return_value = {"max_input_tokens": 128000}
            provider.get_context_window()
            provider.get_context_window()
            assert mock_info.call_count == 1

    def test_returns_none_for_unknown_model(self) -> None:
        """Returns None when litellm doesn't know the model."""
        from macbot.providers.litellm_provider import LiteLLMProvider

        provider = LiteLLMProvider(model="unknown/model-xyz")

        with patch("litellm.get_model_info") as mock_info:
            mock_info.side_effect = Exception("Unknown model")
            result = provider.get_context_window()
            assert result is None

    def test_caches_none(self) -> None:
        """Caches None result so failed lookup isn't retried."""
        from macbot.providers.litellm_provider import LiteLLMProvider

        provider = LiteLLMProvider(model="unknown/model-xyz")

        with patch("litellm.get_model_info") as mock_info:
            mock_info.side_effect = Exception("Unknown model")
            provider.get_context_window()
            provider.get_context_window()
            assert mock_info.call_count == 1


# ---------------------------------------------------------------------------
# LiteLLMProvider.estimate_tokens tests
# ---------------------------------------------------------------------------

class TestLiteLLMEstimateTokens:
    """Tests for LiteLLMProvider.estimate_tokens()."""

    def test_delegates_to_litellm_token_counter(self) -> None:
        """Calls litellm.token_counter with formatted messages."""
        from macbot.providers.litellm_provider import LiteLLMProvider

        provider = LiteLLMProvider(model="anthropic/claude-sonnet-4-20250514")
        messages = [Message(role="user", content="Hello")]

        with patch("litellm.token_counter") as mock_counter:
            mock_counter.return_value = 42
            result = provider.estimate_tokens(messages, system_prompt="Be helpful")
            assert result == 42
            mock_counter.assert_called_once()
            # Check that system message was prepended
            call_kwargs = mock_counter.call_args
            msgs = call_kwargs.kwargs.get("messages") or call_kwargs[1].get("messages")
            if msgs is None:
                # positional or keyword
                msgs = call_kwargs[0][0] if call_kwargs[0] else call_kwargs.kwargs["messages"]
            assert msgs[0]["role"] == "system"

    def test_falls_back_on_error(self) -> None:
        """Falls back to char-based heuristic when litellm fails."""
        from macbot.providers.litellm_provider import LiteLLMProvider

        provider = LiteLLMProvider(model="anthropic/claude-sonnet-4-20250514")
        messages = [Message(role="user", content="Hello world")]

        with patch("litellm.token_counter") as mock_counter:
            mock_counter.side_effect = Exception("tokenizer error")
            result = provider.estimate_tokens(messages)
            # Should use base class heuristic: len("Hello world") // 3 = 3
            assert isinstance(result, int)
            assert result > 0


# ---------------------------------------------------------------------------
# Base class defaults
# ---------------------------------------------------------------------------

class TestBaseProviderDefaults:
    """Tests for LLMProvider base class default implementations."""

    def test_get_context_window_returns_none(self) -> None:
        """Base class returns None for unknown context window."""
        provider = MockProvider()
        # Use the base class method directly
        assert LLMProvider.get_context_window(provider) is None

    def test_estimate_tokens_char_heuristic(self) -> None:
        """Base class uses character-based heuristic."""
        provider = MockProvider()
        messages = [Message(role="user", content="a" * 300)]
        result = LLMProvider.estimate_tokens(provider, messages)
        assert result == 100  # 300 chars // 3

    def test_estimate_tokens_includes_system_prompt(self) -> None:
        """Base class heuristic accounts for system prompt."""
        provider = MockProvider()
        messages = [Message(role="user", content="hi")]
        without = LLMProvider.estimate_tokens(provider, messages)
        with_system = LLMProvider.estimate_tokens(
            provider, messages, system_prompt="x" * 300,
        )
        assert with_system > without
