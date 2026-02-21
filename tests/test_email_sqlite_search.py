"""Tests for SQLite-first email search routing in SearchEmailsTask."""

from unittest.mock import AsyncMock, patch

import pytest

from macbot.tasks.macos_automation import SearchEmailsTask


@pytest.fixture
def task() -> SearchEmailsTask:
    return SearchEmailsTask()


def _sqlite_success(output: str = "=== FOUND 1 MESSAGES ===\n\nMessage-ID: <test@example.com>\nSubject: Test\nFrom: alice@example.com\nDate: 2026-02-21 10:00:00\nRead: true\n---") -> dict:
    return {"success": True, "output": output}


def _sqlite_failure() -> dict:
    return {"success": False, "error": "Script exited with code 2", "output": "", "debug": {"return_code": 2}}


def _applescript_success() -> dict:
    return {"success": True, "output": "=== FOUND 1 MESSAGES ===\n\nMessage-ID: <test@example.com>\nSubject: Test\nFrom: Alice <alice@example.com>\nDate: Friday, February 21, 2026 at 10:00:00 AM\nRead: true\n---"}


class TestSearchEmailsSQLiteRouting:
    """Tests for SQLite-first routing logic in SearchEmailsTask.execute()."""

    @pytest.mark.asyncio
    @patch("macbot.tasks.macos_automation.run_script", new_callable=AsyncMock)
    async def test_metadata_search_tries_sqlite_first(self, mock_run: AsyncMock, task: SearchEmailsTask) -> None:
        """Metadata-only search should try SQLite script first."""
        mock_run.return_value = _sqlite_success()

        result = await task.execute(sender="alice", days=7)

        assert result["success"] is True
        mock_run.assert_called_once_with(
            "mail/search-emails-sqlite.sh",
            ["--sender", "alice", "--days", "7", "--limit", "20"],
            timeout=10,
        )

    @pytest.mark.asyncio
    @patch("macbot.tasks.macos_automation.run_script", new_callable=AsyncMock)
    async def test_with_content_skips_sqlite(self, mock_run: AsyncMock, task: SearchEmailsTask) -> None:
        """with_content=True should skip SQLite and go straight to AppleScript."""
        mock_run.return_value = _applescript_success()

        result = await task.execute(sender="alice", with_content=True, days=7)

        assert result["success"] is True
        mock_run.assert_called_once_with(
            "mail/search-emails.sh",
            ["--sender", "alice", "--days", "7", "--with-content", "--limit", "20"],
            timeout=60,
        )

    @pytest.mark.asyncio
    @patch("macbot.tasks.macos_automation.run_script", new_callable=AsyncMock)
    async def test_with_links_skips_sqlite(self, mock_run: AsyncMock, task: SearchEmailsTask) -> None:
        """with_links=True should skip SQLite and go straight to AppleScript."""
        mock_run.return_value = _applescript_success()

        result = await task.execute(sender="alice", with_content=True, with_links=True, days=7)

        assert result["success"] is True
        mock_run.assert_called_once_with(
            "mail/search-emails.sh",
            ["--sender", "alice", "--days", "7", "--with-content", "--with-links", "--limit", "20"],
            timeout=60,
        )

    @pytest.mark.asyncio
    @patch("macbot.tasks.macos_automation.run_script", new_callable=AsyncMock)
    async def test_sqlite_failure_falls_back_to_applescript(self, mock_run: AsyncMock, task: SearchEmailsTask) -> None:
        """When SQLite fails, should transparently fall back to AppleScript."""
        mock_run.side_effect = [_sqlite_failure(), _applescript_success()]

        result = await task.execute(sender="alice", days=7)

        assert result["success"] is True
        assert mock_run.call_count == 2
        # First call: SQLite
        assert mock_run.call_args_list[0].args[0] == "mail/search-emails-sqlite.sh"
        assert mock_run.call_args_list[0].kwargs.get("timeout", mock_run.call_args_list[0].args[2] if len(mock_run.call_args_list[0].args) > 2 else None) == 10
        # Second call: AppleScript
        assert mock_run.call_args_list[1].args[0] == "mail/search-emails.sh"

    @pytest.mark.asyncio
    @patch("macbot.tasks.macos_automation.run_script", new_callable=AsyncMock)
    async def test_sqlite_and_applescript_called_with_same_args(self, mock_run: AsyncMock, task: SearchEmailsTask) -> None:
        """Both scripts should receive the same CLI arguments."""
        mock_run.side_effect = [_sqlite_failure(), _applescript_success()]

        await task.execute(sender="bob", subject="Invoice", today_only=True, limit=5)

        expected_args = ["--sender", "bob", "--subject", "Invoice", "--today", "--limit", "5"]
        assert mock_run.call_args_list[0].args[1] == expected_args
        assert mock_run.call_args_list[1].args[1] == expected_args

    @pytest.mark.asyncio
    @patch("macbot.tasks.macos_automation.run_script", new_callable=AsyncMock)
    async def test_message_id_search_tries_sqlite(self, mock_run: AsyncMock, task: SearchEmailsTask) -> None:
        """Message-ID lookup without content should try SQLite first."""
        mock_run.return_value = _sqlite_success()

        result = await task.execute(message_id="<abc@example.com>")

        assert result["success"] is True
        mock_run.assert_called_once_with(
            "mail/search-emails-sqlite.sh",
            ["--message-id", "<abc@example.com>", "--limit", "20"],
            timeout=10,
        )

    @pytest.mark.asyncio
    @patch("macbot.tasks.macos_automation.run_script", new_callable=AsyncMock)
    async def test_message_id_with_content_skips_sqlite(self, mock_run: AsyncMock, task: SearchEmailsTask) -> None:
        """Message-ID + with_content should skip SQLite."""
        mock_run.return_value = _applescript_success()

        result = await task.execute(message_id="<abc@example.com>", with_content=True)

        assert result["success"] is True
        mock_run.assert_called_once_with(
            "mail/search-emails.sh",
            ["--message-id", "<abc@example.com>", "--with-content", "--limit", "20"],
            timeout=60,
        )

    @pytest.mark.asyncio
    async def test_no_criteria_returns_error(self, task: SearchEmailsTask) -> None:
        """Search with no criteria should return an error without calling any script."""
        result = await task.execute()

        assert result["success"] is False
        assert "Must specify" in result["error"]

    @pytest.mark.asyncio
    @patch("macbot.tasks.macos_automation.run_script", new_callable=AsyncMock)
    async def test_all_mailboxes_flag_passed(self, mock_run: AsyncMock, task: SearchEmailsTask) -> None:
        """all_mailboxes flag should be passed through to scripts."""
        mock_run.return_value = _sqlite_success()

        await task.execute(sender="alice", all_mailboxes=True, days=7)

        args = mock_run.call_args_list[0].args[1]
        assert "--all-mailboxes" in args

    @pytest.mark.asyncio
    @patch("macbot.tasks.macos_automation.run_script", new_callable=AsyncMock)
    async def test_account_filter_passed(self, mock_run: AsyncMock, task: SearchEmailsTask) -> None:
        """account parameter should be passed through to scripts."""
        mock_run.return_value = _sqlite_success()

        await task.execute(account="work@example.com", days=7)

        args = mock_run.call_args_list[0].args[1]
        assert "--account" in args
        assert "work@example.com" in args
