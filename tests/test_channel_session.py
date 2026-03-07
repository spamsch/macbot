"""Tests for Channel session persistence (save/load round-trip)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from macbot.core.channel import Channel, ChannelKind
from macbot.providers.base import Message, ToolCall


@pytest.fixture()
def channel(tmp_path: Path):
    agent = MagicMock()
    agent.messages = []
    ch = Channel(id="test-chan", name="Test", kind=ChannelKind.CUSTOM, agent=agent)
    # Override the session_dir property so nothing is written to ~/.macbot
    with patch.object(Channel, "session_dir", new_callable=lambda: property(lambda self: tmp_path)):
        yield ch


class TestSessionRoundTrip:
    """save_session → load_session must preserve the full Message structure."""

    def _save_and_reload(self, channel: Channel, messages: list[Message]) -> list[Message]:
        channel.agent.messages = messages
        channel.save_session()

        # Reset and reload
        channel.agent.messages = []
        loaded = channel.load_session()
        assert loaded is True
        return channel.agent.messages

    def test_plain_text_messages(self, channel: Channel, tmp_path: Path) -> None:
        msgs = [
            Message(role="user", content="Hello"),
            Message(role="assistant", content="Hi there"),
        ]
        result = self._save_and_reload(channel, msgs)
        assert len(result) == 2
        assert result[0].role == "user"
        assert result[0].content == "Hello"
        assert result[1].role == "assistant"
        assert result[1].content == "Hi there"

    def test_tool_call_messages_preserved(self, channel: Channel, tmp_path: Path) -> None:
        """Assistant tool-call turn and tool-result turn must survive the round-trip."""
        tool_call = ToolCall(id="call_abc", name="search_emails", arguments={"query": "invoice"})
        msgs = [
            Message(role="user", content="Find emails about invoices"),
            Message(role="assistant", content=None, tool_calls=[tool_call]),
            Message(role="tool", content="Found 3 emails", tool_call_id="call_abc"),
        ]
        result = self._save_and_reload(channel, msgs)
        assert len(result) == 3

        assistant_msg = result[1]
        assert assistant_msg.role == "assistant"
        assert assistant_msg.tool_calls is not None
        assert len(assistant_msg.tool_calls) == 1
        tc = assistant_msg.tool_calls[0]
        assert tc.id == "call_abc"
        assert tc.name == "search_emails"
        assert tc.arguments == {"query": "invoice"}

        tool_result = result[2]
        assert tool_result.role == "tool"
        assert tool_result.content == "Found 3 emails"
        assert tool_result.tool_call_id == "call_abc"

    def test_multimodal_content_blocks_preserved(self, channel: Channel, tmp_path: Path) -> None:
        """Messages with list-of-dict content blocks must survive the round-trip."""
        content_blocks: list[dict[str, Any]] = [
            {"type": "text", "text": "What is in this image?"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc123"}},
        ]
        msgs = [
            Message(role="user", content=content_blocks),
            Message(role="assistant", content="The image shows a chart."),
        ]
        result = self._save_and_reload(channel, msgs)
        assert len(result) == 2
        assert isinstance(result[0].content, list)
        assert result[0].content == content_blocks
        assert result[1].content == "The image shows a chart."

    def test_none_content_preserved(self, channel: Channel, tmp_path: Path) -> None:
        """Messages with None content (pure tool-call turns) must survive."""
        tool_call = ToolCall(id="call_xyz", name="list_files", arguments={})
        msgs = [
            Message(role="assistant", content=None, tool_calls=[tool_call]),
        ]
        result = self._save_and_reload(channel, msgs)
        assert len(result) == 1
        assert result[0].content is None
        assert result[0].tool_calls is not None
        assert result[0].tool_calls[0].id == "call_xyz"

    def test_load_returns_false_when_no_file(self, channel: Channel) -> None:
        assert channel.load_session() is False

    def test_load_returns_false_on_corrupt_json(self, channel: Channel, tmp_path: Path) -> None:
        session_file = tmp_path / "session.json"
        session_file.write_text("{corrupt}")
        assert channel.load_session() is False

    def test_session_file_is_valid_json(self, channel: Channel, tmp_path: Path) -> None:
        channel.agent.messages = [Message(role="user", content="test")]
        channel.save_session()
        data = json.loads((tmp_path / "session.json").read_text())
        assert data["channel_id"] == "test-chan"
        assert len(data["messages"]) == 1
        assert data["messages"][0]["role"] == "user"
        assert data["messages"][0]["content"] == "test"
