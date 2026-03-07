"""Tests for Spotlight-based email search in SearchEmailsTask."""

import inspect
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from macbot.tasks.macos_automation import SearchEmailsTask


@pytest.fixture
def task() -> SearchEmailsTask:
    return SearchEmailsTask()


def _spotlight_success(emails: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if emails is None:
        emails = [{"subject": "Test", "sender": "alice@example.com", "date": "2026-02-21", "is_read": True, "snippet": ""}]
    return {"success": True, "source": "spotlight", "count": len(emails), "emails": emails}


def _spotlight_empty() -> dict[str, Any]:
    return {"success": False, "error": "Spotlight mail index is empty — run 'son start' to build it"}


class TestSearchEmailsSpotlight:
    """Tests for Spotlight-based routing in SearchEmailsTask.execute()."""

    @pytest.mark.asyncio
    async def test_no_criteria_returns_error(self, task: SearchEmailsTask) -> None:
        """Search with no criteria should return an error without calling Spotlight."""
        result = await task.execute()

        assert result["success"] is False
        assert "Must specify" in result["error"]

    @pytest.mark.asyncio
    async def test_all_mailboxes_not_accepted(self, task: SearchEmailsTask) -> None:
        """all_mailboxes is no longer a parameter; Spotlight searches all mailboxes by default."""
        sig = inspect.signature(task.execute)
        assert "all_mailboxes" not in sig.parameters

    @pytest.mark.asyncio
    @patch.object(SearchEmailsTask, "_try_spotlight_search", new_callable=AsyncMock)
    async def test_sender_search_uses_spotlight(self, mock_spotlight: AsyncMock, task: SearchEmailsTask) -> None:
        """Sender search should delegate to Spotlight."""
        mock_spotlight.return_value = _spotlight_success()

        result = await task.execute(sender="alice", days=7)

        assert result["success"] is True
        mock_spotlight.assert_called_once_with(
            sender="alice", recipient=None, subject=None, message_id=None,
            account=None, mailbox=None, today_only=False, days=7, limit=20,
            with_content=False, with_links=False,
        )

    @pytest.mark.asyncio
    @patch.object(SearchEmailsTask, "_try_spotlight_search", new_callable=AsyncMock)
    async def test_mailbox_filter_forwarded(self, mock_spotlight: AsyncMock, task: SearchEmailsTask) -> None:
        """mailbox parameter should be forwarded to Spotlight search."""
        mock_spotlight.return_value = _spotlight_success()

        await task.execute(sender="alice", mailbox="Archive", days=7)

        _, kwargs = mock_spotlight.call_args
        assert kwargs["mailbox"] == "Archive"

    @pytest.mark.asyncio
    @patch.object(SearchEmailsTask, "_try_spotlight_search", new_callable=AsyncMock)
    async def test_with_content_forwarded(self, mock_spotlight: AsyncMock, task: SearchEmailsTask) -> None:
        """with_content=True should be forwarded to Spotlight."""
        mock_spotlight.return_value = _spotlight_success()

        await task.execute(sender="alice", with_content=True, days=7)

        _, kwargs = mock_spotlight.call_args
        assert kwargs["with_content"] is True

    @pytest.mark.asyncio
    @patch.object(SearchEmailsTask, "_try_spotlight_search", new_callable=AsyncMock)
    async def test_with_links_forwarded(self, mock_spotlight: AsyncMock, task: SearchEmailsTask) -> None:
        """with_links=True should be forwarded to Spotlight."""
        mock_spotlight.return_value = _spotlight_success()

        await task.execute(sender="alice", with_content=True, with_links=True, days=7)

        _, kwargs = mock_spotlight.call_args
        assert kwargs["with_links"] is True

    @pytest.mark.asyncio
    @patch.object(SearchEmailsTask, "_try_spotlight_search", new_callable=AsyncMock)
    async def test_account_filter_forwarded(self, mock_spotlight: AsyncMock, task: SearchEmailsTask) -> None:
        """account parameter should be forwarded to Spotlight search."""
        mock_spotlight.return_value = _spotlight_success()

        await task.execute(account="work@example.com", days=7)

        _, kwargs = mock_spotlight.call_args
        assert kwargs["account"] == "work@example.com"

    @pytest.mark.asyncio
    @patch.object(SearchEmailsTask, "_try_spotlight_search", new_callable=AsyncMock)
    async def test_message_id_search(self, mock_spotlight: AsyncMock, task: SearchEmailsTask) -> None:
        """message_id lookup should be forwarded to Spotlight."""
        mock_spotlight.return_value = _spotlight_success()

        result = await task.execute(message_id="<abc@example.com>")

        assert result["success"] is True
        _, kwargs = mock_spotlight.call_args
        assert kwargs["message_id"] == "<abc@example.com>"

    @pytest.mark.asyncio
    @patch.object(SearchEmailsTask, "_try_spotlight_search", new_callable=AsyncMock)
    async def test_spotlight_error_propagated(self, mock_spotlight: AsyncMock, task: SearchEmailsTask) -> None:
        """Errors from Spotlight search should be returned as-is."""
        mock_spotlight.return_value = _spotlight_empty()

        result = await task.execute(sender="alice")

        assert result["success"] is False
        assert "Spotlight" in result["error"]
