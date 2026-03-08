"""Tests for Spotlight-based email search routing in SearchEmailsTask."""

from unittest.mock import MagicMock, patch

import pytest

from macbot.tasks.macos_automation import SearchEmailsTask


@pytest.fixture
def task() -> SearchEmailsTask:
    return SearchEmailsTask()


def _spotlight_result(
    subject: str = "Test",
    sender: str = "alice@example.com",
    date: str = "2026-02-21 10:00:00",
    content: str | None = None,
) -> dict:
    r: dict = {
        "subject": subject,
        "sender": sender,
        "recipients": "bob@example.com",
        "date_received": date,
        "is_read": True,
        "snippet": "Preview text",
    }
    if content:
        r["content"] = content
    return r


class TestSearchEmailsSpotlightRouting:
    """Tests for Spotlight routing logic in SearchEmailsTask.execute()."""

    @pytest.mark.asyncio
    @patch("macbot.spotlight.mail_search.MailSearchIndex")
    async def test_metadata_search_uses_spotlight(self, MockIndex: MagicMock, task: SearchEmailsTask) -> None:
        """Metadata-only search should use Spotlight index."""
        index = MockIndex.return_value
        index.message_count.return_value = 100
        # needs_rebuild is no longer called (watcher handles freshness)
        index.search.return_value = [_spotlight_result()]

        result = await task.execute(sender="alice", days=7)

        assert result["success"] is True
        assert result["source"] == "spotlight"
        index.search.assert_called_once()
        kwargs = index.search.call_args.kwargs
        assert kwargs["sender"] == "alice"
        assert kwargs["days"] == 7
        assert kwargs["resolve_urls"] is True

    @pytest.mark.asyncio
    @patch("macbot.spotlight.mail_search.MailSearchIndex")
    async def test_with_content_passed_to_spotlight(self, MockIndex: MagicMock, task: SearchEmailsTask) -> None:
        """with_content=True should be forwarded to Spotlight search."""
        index = MockIndex.return_value
        index.message_count.return_value = 100
        # needs_rebuild is no longer called (watcher handles freshness)
        index.search.return_value = [_spotlight_result(content="Full body text")]

        result = await task.execute(sender="alice", with_content=True, days=7)

        assert result["success"] is True
        kwargs = index.search.call_args.kwargs
        assert kwargs["with_content"] is True

    @pytest.mark.asyncio
    @patch("macbot.spotlight.mail_search.MailSearchIndex")
    async def test_with_links_passed_to_spotlight(self, MockIndex: MagicMock, task: SearchEmailsTask) -> None:
        """with_links=True should be forwarded to Spotlight search."""
        index = MockIndex.return_value
        index.message_count.return_value = 100
        # needs_rebuild is no longer called (watcher handles freshness)
        index.search.return_value = [_spotlight_result()]

        result = await task.execute(sender="alice", with_content=True, with_links=True, days=7)

        assert result["success"] is True
        kwargs = index.search.call_args.kwargs
        assert kwargs["with_links"] is True
        assert kwargs["with_content"] is True

    @pytest.mark.asyncio
    @patch("macbot.spotlight.mail_search.MailSearchIndex")
    async def test_empty_index_triggers_rebuild(self, MockIndex: MagicMock, task: SearchEmailsTask) -> None:
        """Empty index should trigger a rebuild before searching."""
        index = MockIndex.return_value
        index.message_count.return_value = 0
        index.search.return_value = [_spotlight_result()]

        result = await task.execute(sender="alice", days=7)

        assert result["success"] is True
        index.rebuild.assert_called_once()

    @pytest.mark.asyncio
    @patch("macbot.spotlight.mail_search.MailSearchIndex")
    async def test_spotlight_failure_returns_error(self, MockIndex: MagicMock, task: SearchEmailsTask) -> None:
        """When Spotlight raises an exception, return an error dict."""
        MockIndex.side_effect = Exception("Spotlight index corrupt")

        result = await task.execute(sender="alice", days=7)

        assert result["success"] is False
        assert "Spotlight search failed" in result["error"]

    @pytest.mark.asyncio
    @patch("macbot.spotlight.mail_search.MailSearchIndex")
    async def test_message_id_search(self, MockIndex: MagicMock, task: SearchEmailsTask) -> None:
        """Numeric message_id should be passed as int to Spotlight."""
        index = MockIndex.return_value
        index.message_count.return_value = 100
        # needs_rebuild is no longer called (watcher handles freshness)
        index.search.return_value = [_spotlight_result()]

        result = await task.execute(message_id="12345")

        assert result["success"] is True
        kwargs = index.search.call_args.kwargs
        assert kwargs["message_id"] == 12345

    @pytest.mark.asyncio
    async def test_non_numeric_message_id_returns_error(self, task: SearchEmailsTask) -> None:
        """Non-numeric message_id should return an error."""
        result = await task.execute(message_id="<abc@example.com>")

        assert result["success"] is False
        assert "numeric" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_no_criteria_returns_error(self, task: SearchEmailsTask) -> None:
        """Search with no criteria should return an error without calling any script."""
        result = await task.execute()

        assert result["success"] is False
        assert "Must specify" in result["error"]

    @pytest.mark.asyncio
    @patch("macbot.spotlight.mail_search.MailSearchIndex")
    async def test_account_filter_passed(self, MockIndex: MagicMock, task: SearchEmailsTask) -> None:
        """account parameter should be passed through to Spotlight."""
        index = MockIndex.return_value
        index.message_count.return_value = 100
        # needs_rebuild is no longer called (watcher handles freshness)
        index.search.return_value = [_spotlight_result()]

        await task.execute(account="work@example.com", days=7)

        kwargs = index.search.call_args.kwargs
        assert kwargs["account"] == "work@example.com"

    @pytest.mark.asyncio
    @patch("macbot.spotlight.mail_search.MailSearchIndex")
    async def test_result_format(self, MockIndex: MagicMock, task: SearchEmailsTask) -> None:
        """Result should have expected structure with email fields."""
        index = MockIndex.return_value
        index.message_count.return_value = 100
        # needs_rebuild is no longer called (watcher handles freshness)
        index.search.return_value = [_spotlight_result(subject="Invoice", sender="bob@test.com")]

        result = await task.execute(sender="bob", days=7)

        assert result["success"] is True
        assert result["count"] == 1
        email = result["emails"][0]
        assert email["subject"] == "Invoice"
        assert email["sender"] == "bob@test.com"

    @pytest.mark.asyncio
    @patch("macbot.spotlight.mail_search.MailSearchIndex")
    async def test_rfc_message_id_exposed_as_message_id(self, MockIndex: MagicMock, task: SearchEmailsTask) -> None:
        """RFC Message-ID should be exposed as 'message_id' without angle brackets."""
        index = MockIndex.return_value
        index.message_count.return_value = 100
        # needs_rebuild is no longer called (watcher handles freshness)
        r = _spotlight_result()
        r["rfc_message_id"] = "<abc123@example.com>"
        index.search.return_value = [r]

        result = await task.execute(sender="alice", days=7)

        email = result["emails"][0]
        assert email["message_id"] == "abc123@example.com"
        assert "mail_message_id" not in email
