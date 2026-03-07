"""Tests for Spotlight-based email search routing in SearchEmailsTask."""

from unittest.mock import MagicMock, patch

import pytest

from macbot.tasks.macos_automation import SearchEmailsTask

_DEFAULT_SEARCH_ROW: dict = {
    "subject": "Test Subject",
    "sender": "alice@example.com",
    "sender_name": "Alice",
    "recipients": "bob@example.com",
    "cc_recipients": "",
    "date_received": "2026-02-21T10:00:00",
    "is_read": 1,
    "snippet": "Hello there",
    "account": "work",
    "mailboxes": "INBOX",
    "mail_message_id": 42,
}


@pytest.fixture
def task() -> SearchEmailsTask:
    return SearchEmailsTask()


def _make_index_mock(
    message_count: int = 5,
    needs_rebuild: bool = False,
    search_results: list | None = None,
) -> MagicMock:
    """Return a MagicMock shaped like MailSearchIndex.

    Args:
        message_count: Value returned by ``index.message_count()``.
        needs_rebuild: Value returned by ``index.needs_rebuild()``.
        search_results: List of row dicts returned by ``index.search()``.
            Each dict should include the same keys as ``_DEFAULT_SEARCH_ROW``.
            Defaults to a single row built from ``_DEFAULT_SEARCH_ROW``.
    """
    index = MagicMock()
    index.message_count.return_value = message_count
    index.needs_rebuild.return_value = needs_rebuild
    index.search.return_value = search_results if search_results is not None else [_DEFAULT_SEARCH_ROW.copy()]
    return index


class TestSearchEmailsSpotlightRouting:
    """Tests for Spotlight-based routing in SearchEmailsTask.execute()."""

    @pytest.mark.asyncio
    @patch("macbot.spotlight.mail_search.MailSearchIndex")
    async def test_sender_search_uses_spotlight(
        self, mock_cls: MagicMock, task: SearchEmailsTask
    ) -> None:
        """Sender search should use MailSearchIndex.search() with the sender arg."""
        mock_cls.return_value = _make_index_mock()

        result = await task.execute(sender="alice", days=7)

        assert result["success"] is True
        assert result["source"] == "spotlight"
        _, kwargs = mock_cls.return_value.search.call_args
        assert kwargs["sender"] == "alice"
        assert kwargs["days"] == 7

    @pytest.mark.asyncio
    @patch("macbot.spotlight.mail_search.MailSearchIndex")
    async def test_recipient_search_uses_spotlight(
        self, mock_cls: MagicMock, task: SearchEmailsTask
    ) -> None:
        """recipient= should be passed to MailSearchIndex.search() to search To/CC."""
        mock_cls.return_value = _make_index_mock()

        result = await task.execute(recipient="bob@example.com", days=7)

        assert result["success"] is True
        _, kwargs = mock_cls.return_value.search.call_args
        assert kwargs["recipient"] == "bob@example.com"

    @pytest.mark.asyncio
    @patch("macbot.spotlight.mail_search.MailSearchIndex")
    async def test_subject_filter_passed(
        self, mock_cls: MagicMock, task: SearchEmailsTask
    ) -> None:
        """subject= should be forwarded to MailSearchIndex.search()."""
        mock_cls.return_value = _make_index_mock()

        await task.execute(subject="Invoice", days=7)

        _, kwargs = mock_cls.return_value.search.call_args
        assert kwargs["subject"] == "Invoice"

    @pytest.mark.asyncio
    @patch("macbot.spotlight.mail_search.MailSearchIndex")
    async def test_account_filter_passed(
        self, mock_cls: MagicMock, task: SearchEmailsTask
    ) -> None:
        """account= should be forwarded to MailSearchIndex.search()."""
        mock_cls.return_value = _make_index_mock()

        await task.execute(account="work@example.com", days=7)

        _, kwargs = mock_cls.return_value.search.call_args
        assert kwargs["account"] == "work@example.com"

    @pytest.mark.asyncio
    @patch("macbot.spotlight.mail_search.MailSearchIndex")
    async def test_with_content_passed_to_index(
        self, mock_cls: MagicMock, task: SearchEmailsTask
    ) -> None:
        """with_content=True should be forwarded to MailSearchIndex.search()."""
        row = {**_DEFAULT_SEARCH_ROW, "content": "Full email body text"}
        mock_cls.return_value = _make_index_mock(search_results=[row])

        result = await task.execute(sender="alice", with_content=True, days=7)

        assert result["success"] is True
        _, kwargs = mock_cls.return_value.search.call_args
        assert kwargs["with_content"] is True
        assert result["emails"][0]["content"] == "Full email body text"

    @pytest.mark.asyncio
    @patch("macbot.spotlight.mail_search.MailSearchIndex")
    async def test_with_links_passed_to_index(
        self, mock_cls: MagicMock, task: SearchEmailsTask
    ) -> None:
        """with_links=True should be forwarded to MailSearchIndex.search()."""
        mock_cls.return_value = _make_index_mock()

        await task.execute(sender="alice", with_content=True, with_links=True, days=7)

        _, kwargs = mock_cls.return_value.search.call_args
        assert kwargs["with_links"] is True

    @pytest.mark.asyncio
    @patch("macbot.spotlight.mail_search.MailSearchIndex")
    async def test_numeric_message_id_converted_to_int(
        self, mock_cls: MagicMock, task: SearchEmailsTask
    ) -> None:
        """A numeric string message_id should be converted to int before lookup."""
        mock_cls.return_value = _make_index_mock()

        result = await task.execute(message_id="123")

        assert result["success"] is True
        _, kwargs = mock_cls.return_value.search.call_args
        assert kwargs["message_id"] == 123

    @pytest.mark.asyncio
    async def test_non_numeric_message_id_returns_error(self, task: SearchEmailsTask) -> None:
        """An RFC Message-ID string (non-numeric) should return a descriptive error."""
        result = await task.execute(message_id="<abc@example.com>")

        assert result["success"] is False
        assert "numeric" in result["error"]

    @pytest.mark.asyncio
    @patch("macbot.spotlight.mail_search.MailSearchIndex")
    async def test_empty_index_triggers_rebuild(
        self, mock_cls: MagicMock, task: SearchEmailsTask
    ) -> None:
        """An empty index should trigger a rebuild before searching."""
        mock_index = _make_index_mock(message_count=0, needs_rebuild=False)
        mock_cls.return_value = mock_index

        result = await task.execute(sender="alice", days=7)

        assert result["success"] is True
        mock_index.rebuild.assert_called_once()

    @pytest.mark.asyncio
    @patch("macbot.spotlight.mail_search.MailSearchIndex")
    async def test_stale_index_triggers_rebuild(
        self, mock_cls: MagicMock, task: SearchEmailsTask
    ) -> None:
        """A stale (needs_rebuild) index should trigger a rebuild before searching."""
        mock_index = _make_index_mock(message_count=10, needs_rebuild=True)
        mock_cls.return_value = mock_index

        result = await task.execute(sender="alice", days=7)

        assert result["success"] is True
        mock_index.rebuild.assert_called_once()

    @pytest.mark.asyncio
    @patch("macbot.spotlight.mail_search.MailSearchIndex")
    async def test_missing_store_returns_error(
        self, mock_cls: MagicMock, task: SearchEmailsTask
    ) -> None:
        """FileNotFoundError during rebuild (no spotlight store) returns an error."""
        mock_index = _make_index_mock(message_count=0)
        mock_index.rebuild.side_effect = FileNotFoundError("No store.db found")
        mock_cls.return_value = mock_index

        result = await task.execute(sender="alice", days=7)

        assert result["success"] is False
        assert "Spotlight mail index is empty" in result["error"]

    @pytest.mark.asyncio
    async def test_no_criteria_returns_error(self, task: SearchEmailsTask) -> None:
        """Search with no criteria should return an error without touching the index."""
        result = await task.execute()

        assert result["success"] is False
        assert "Must specify" in result["error"]

    @pytest.mark.asyncio
    @patch("macbot.spotlight.mail_search.MailSearchIndex")
    async def test_spotlight_exception_returns_error(
        self, mock_cls: MagicMock, task: SearchEmailsTask
    ) -> None:
        """An unexpected exception in the spotlight path should return a graceful error."""
        mock_cls.side_effect = RuntimeError("index corrupted")

        result = await task.execute(sender="alice", days=7)

        assert result["success"] is False
        assert "Spotlight search failed" in result["error"]

    @pytest.mark.asyncio
    @patch("macbot.spotlight.mail_search.MailSearchIndex")
    async def test_result_formatting(
        self, mock_cls: MagicMock, task: SearchEmailsTask
    ) -> None:
        """Results should be formatted with the expected fields."""
        mock_cls.return_value = _make_index_mock()

        result = await task.execute(sender="alice", days=7)

        assert result["success"] is True
        assert result["count"] == 1
        email = result["emails"][0]
        assert email["subject"] == "Test Subject"
        assert email["sender"] == "alice@example.com"
        assert email["is_read"] is True
        assert "snippet" in email

    @pytest.mark.asyncio
    @patch("macbot.spotlight.mail_search.MailSearchIndex")
    async def test_limit_passed_to_index(
        self, mock_cls: MagicMock, task: SearchEmailsTask
    ) -> None:
        """limit= should be forwarded to MailSearchIndex.search()."""
        mock_cls.return_value = _make_index_mock()

        await task.execute(sender="alice", limit=5)

        _, kwargs = mock_cls.return_value.search.call_args
        assert kwargs["limit"] == 5

    @pytest.mark.asyncio
    @patch("macbot.spotlight.mail_search.MailSearchIndex")
    async def test_today_only_passed_to_index(
        self, mock_cls: MagicMock, task: SearchEmailsTask
    ) -> None:
        """today_only=True should be forwarded to MailSearchIndex.search()."""
        mock_cls.return_value = _make_index_mock()

        await task.execute(today_only=True)

        _, kwargs = mock_cls.return_value.search.call_args
        assert kwargs["today_only"] is True
