"""Tasks: macOS Automation

Provides agent tools for automating Apple's native productivity apps
(Mail, Calendar, Reminders, Notes, Safari) via AppleScript wrappers.

These tasks wrap the shell scripts in /workspace/macos-automation/.
"""

import asyncio
import os
import sys
from typing import Any

from macbot.tasks.base import Task

# Base path to the automation scripts
# When running from PyInstaller bundle, use sys._MEIPASS
# Otherwise, compute relative to the package location
if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    # Running from PyInstaller bundle
    SCRIPTS_BASE = os.path.join(sys._MEIPASS, "macos-automation")
else:
    # Running from source
    _PACKAGE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    SCRIPTS_BASE = os.path.join(_PACKAGE_DIR, "macos-automation")


async def run_script(script_path: str, args: list[str] | None = None, timeout: int = 30) -> dict[str, Any]:
    """Run a macOS automation script and return the result.

    Args:
        script_path: Path to the script relative to SCRIPTS_BASE
        args: Command line arguments to pass
        timeout: Maximum execution time in seconds

    Returns:
        Dictionary with return_code, stdout, stderr
    """
    import logging
    logger = logging.getLogger(__name__)

    full_path = os.path.join(SCRIPTS_BASE, script_path)
    cmd_parts = [full_path] + (args or [])
    cmd = " ".join(f'"{p}"' if " " in p else p for p in cmd_parts)

    logger.debug(f"Running script: {cmd}")
    logger.debug(f"Script path exists: {os.path.exists(full_path)}")

    if not os.path.exists(full_path):
        return {
            "success": False,
            "error": f"Script not found: {full_path}",
            "debug": {
                "scripts_base": SCRIPTS_BASE,
                "script_path": script_path,
                "full_path": full_path,
            },
        }

    try:
        process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=timeout
        )

        stdout_str = stdout.decode().strip()
        stderr_str = stderr.decode().strip()

        logger.debug(f"Script return code: {process.returncode}")
        logger.debug(f"Script stdout: {stdout_str[:200] if stdout_str else '(empty)'}")
        logger.debug(f"Script stderr: {stderr_str[:200] if stderr_str else '(empty)'}")

        if process.returncode != 0:
            return {
                "success": False,
                "error": stderr_str or f"Script exited with code {process.returncode}",
                "output": stdout_str,
                "debug": {
                    "command": cmd,
                    "return_code": process.returncode,
                    "stderr": stderr_str,
                },
            }

        return {
            "success": True,
            "output": stdout_str,
        }
    except asyncio.TimeoutError:
        return {
            "success": False,
            "error": f"Script timed out after {timeout} seconds",
            "debug": {"command": cmd},
        }
    except Exception as e:
        logger.exception(f"Script execution failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "debug": {"command": cmd, "exception": type(e).__name__},
        }


# =============================================================================
# MAIL TASKS
# =============================================================================

class GetUnreadEmailsTask(Task):
    """Get a summary of unread emails from the inbox."""

    @property
    def name(self) -> str:
        return "get_unread_emails"

    @property
    def description(self) -> str:
        return "Get a summary of all unread emails in the Mail.app inbox, showing subject, sender, and date."

    async def execute(self, count_only: bool = False) -> dict[str, Any]:
        """Get unread emails.

        Args:
            count_only: If True, only return the count of unread messages.

        Returns:
            Dictionary with email summary or count.
        """
        args = ["--count-only"] if count_only else []
        return await run_script("mail/get-unread-summary.sh", args)


class SearchEmailsTask(Task):
    """Search emails by sender, subject, or account."""

    @property
    def name(self) -> str:
        return "search_emails"

    @property
    def description(self) -> str:
        return (
            "Search emails in Mail.app. Can search by sender, subject, message_id, or list all emails in an account. "
            "IMPORTANT: 'emails from X account' means emails RECEIVED BY that account (use account parameter), "
            "not emails FROM that sender. Use message_id for precise lookup of a specific email. "
            "Use with_content=True to include the full email body text (needed to read what an email says)."
        )

    async def execute(
        self,
        sender: str | None = None,
        subject: str | None = None,
        message_id: str | None = None,
        account: str | None = None,
        mailbox: str | None = None,
        today_only: bool = False,
        days: int | None = None,
        all_mailboxes: bool = False,
        with_content: bool = False,
        limit: int = 20
    ) -> dict[str, Any]:
        """Search emails.

        Args:
            sender: Search for emails from sender containing this pattern.
            subject: Search for emails with subject containing this pattern.
            message_id: Search for specific email by Message-ID (fast direct lookup).
            account: Search in specified account (e.g., "waas.rent" for all emails in that account).
            mailbox: Search specific mailbox (e.g., "Archive", "Sent Items").
            today_only: Only return emails from today.
            days: Only return emails from the last N days.
            all_mailboxes: Search all mailboxes including Sent, Trash, etc.
            with_content: Include the full email body text (use when you need to read the email content).
            limit: Maximum number of results to return.

        Returns:
            Dictionary with matching emails.
        """
        if not sender and not subject and not account and not message_id:
            return {"success": False, "error": "Must specify sender, subject, message_id, or account"}

        args = []
        if sender:
            args.extend(["--sender", sender])
        if subject:
            args.extend(["--subject", subject])
        if message_id:
            args.extend(["--message-id", message_id])
        if account:
            args.extend(["--account", account])
        if mailbox:
            args.extend(["--mailbox", mailbox])
        if today_only:
            args.append("--today")
        if days:
            args.extend(["--days", str(days)])
        if all_mailboxes:
            args.append("--all-mailboxes")
        if with_content:
            args.append("--with-content")
        args.extend(["--limit", str(limit)])

        return await run_script("mail/search-emails.sh", args, timeout=60)


class SendEmailTask(Task):
    """Send an email via Mail.app."""

    @property
    def name(self) -> str:
        return "send_email"

    @property
    def description(self) -> str:
        return (
            "Send an email using Mail.app. Can send immediately or save as draft. "
            "Drafts are saved silently to the Drafts folder without opening a window."
        )

    async def execute(
        self,
        to: str,
        subject: str,
        body: str,
        cc: str | None = None,
        bcc: str | None = None,
        draft: bool = False,
        draft_visible: bool = False
    ) -> dict[str, Any]:
        """Send an email.

        Args:
            to: Recipient email address.
            subject: Email subject line.
            body: Email body content.
            cc: CC recipient (optional).
            bcc: BCC recipient (optional).
            draft: If True, save as draft instead of sending (silently).
            draft_visible: If True with draft, open compose window for review.

        Returns:
            Dictionary with send status.
        """
        args = ["--to", to, "--subject", subject, "--body", body]
        if cc:
            args.extend(["--cc", cc])
        if bcc:
            args.extend(["--bcc", bcc])
        if draft:
            if draft_visible:
                args.append("--draft-visible")
            else:
                args.append("--draft")

        return await run_script("mail/send-email.sh", args)


class MoveEmailTask(Task):
    """Move emails to Archive, Trash, or another mailbox."""

    @property
    def name(self) -> str:
        return "move_email"

    @property
    def description(self) -> str:
        return (
            "Move emails to Archive, Trash, or a custom mailbox. Best used with message_id "
            "from search_emails for precise matching. Use this to archive processed emails."
        )

    async def execute(
        self,
        to: str,
        message_id: str | None = None,
        sender: str | None = None,
        subject: str | None = None,
        account: str | None = None,
        mailbox: str | None = None,
        limit: int = 10
    ) -> dict[str, Any]:
        """Move emails to a destination.

        Args:
            to: Destination - "archive", "trash", or mailbox name.
            message_id: Match specific email by Message-ID (recommended).
            sender: Match emails from sender containing this pattern.
            subject: Match emails with subject containing this pattern.
            account: Only search in specified account.
            mailbox: Only search in specified mailbox (default: Inbox).
            limit: Maximum number of emails to move.

        Returns:
            Dictionary with move result.
        """
        if not message_id and not sender and not subject:
            return {"success": False, "error": "Must specify message_id, sender, or subject"}

        args = ["--to", to]
        if message_id:
            args.extend(["--message-id", message_id])
        if sender:
            args.extend(["--sender", sender])
        if subject:
            args.extend(["--subject", subject])
        if account:
            args.extend(["--account", account])
        if mailbox:
            args.extend(["--mailbox", mailbox])
        args.extend(["--limit", str(limit)])

        return await run_script("mail/move-email.sh", args, timeout=60)


class DownloadAttachmentsTask(Task):
    """Download email attachments to a folder."""

    @property
    def name(self) -> str:
        return "download_attachments"

    @property
    def description(self) -> str:
        return (
            "Download attachments from emails to a specified folder. Best used with message_id "
            "from search_emails for precise matching."
        )

    async def execute(
        self,
        output: str,
        message_id: str | None = None,
        sender: str | None = None,
        subject: str | None = None,
        account: str | None = None,
        mailbox: str | None = None,
        limit: int = 5
    ) -> dict[str, Any]:
        """Download attachments from matching emails.

        Args:
            output: Destination folder for attachments.
            message_id: Match specific email by Message-ID (recommended).
            sender: Match emails from sender containing this pattern.
            subject: Match emails with subject containing this pattern.
            account: Only search in specified account.
            mailbox: Only search in specified mailbox (default: Inbox).
            limit: Maximum number of emails to process.

        Returns:
            Dictionary with download result.
        """
        if not message_id and not sender and not subject:
            return {"success": False, "error": "Must specify message_id, sender, or subject"}

        args = ["--output", output]
        if message_id:
            args.extend(["--message-id", message_id])
        if sender:
            args.extend(["--sender", sender])
        if subject:
            args.extend(["--subject", subject])
        if account:
            args.extend(["--account", account])
        if mailbox:
            args.extend(["--mailbox", mailbox])
        args.extend(["--limit", str(limit)])

        return await run_script("mail/download-attachments.sh", args, timeout=60)


class MarkEmailsReadTask(Task):
    """Mark emails as read."""

    @property
    def name(self) -> str:
        return "mark_emails_read"

    @property
    def description(self) -> str:
        return "Mark emails as read. Can mark all unread, by sender pattern, subject pattern, or age."

    async def execute(
        self,
        all_unread: bool = False,
        sender: str | None = None,
        subject: str | None = None,
        older_than_days: int | None = None,
        dry_run: bool = False
    ) -> dict[str, Any]:
        """Mark emails as read.

        Args:
            all_unread: Mark all unread emails as read.
            sender: Mark emails from sender matching this pattern.
            subject: Mark emails with subject matching this pattern.
            older_than_days: Mark emails older than this many days.
            dry_run: Preview what would be marked without actually marking.

        Returns:
            Dictionary with result.
        """
        args = []
        if all_unread:
            args.append("--all")
        elif sender:
            args.extend(["--sender", sender])
        elif subject:
            args.extend(["--subject", subject])
        elif older_than_days:
            args.extend(["--older-than", str(older_than_days)])
        else:
            return {"success": False, "error": "Must specify all_unread, sender, subject, or older_than_days"}

        if dry_run:
            args.append("--dry-run")

        return await run_script("mail/mark-as-read.sh", args)


# =============================================================================
# CALENDAR TASKS
# =============================================================================

class GetTodayEventsTask(Task):
    """Get today's calendar events."""

    @property
    def name(self) -> str:
        return "get_today_events"

    @property
    def description(self) -> str:
        return "Get all calendar events scheduled for today from Calendar.app."

    async def execute(self, calendar: str | None = None) -> dict[str, Any]:
        """Get today's events.

        Args:
            calendar: Only show events from this calendar (optional).

        Returns:
            Dictionary with today's events.
        """
        args = ["--calendar", calendar] if calendar else []
        return await run_script("calendar/get-today-events.sh", args)


class GetWeekEventsTask(Task):
    """Get upcoming calendar events."""

    @property
    def name(self) -> str:
        return "get_week_events"

    @property
    def description(self) -> str:
        return "Get calendar events for the next 7 days (or custom range) from Calendar.app."

    async def execute(
        self,
        days: int = 7,
        calendar: str | None = None
    ) -> dict[str, Any]:
        """Get upcoming events.

        Args:
            days: Number of days to look ahead (default: 7).
            calendar: Only show events from this calendar (optional).

        Returns:
            Dictionary with upcoming events.
        """
        args = ["--days", str(days)]
        if calendar:
            args.extend(["--calendar", calendar])
        return await run_script("calendar/get-week-events.sh", args)


class CreateCalendarEventTask(Task):
    """Create a new calendar event."""

    @property
    def name(self) -> str:
        return "create_calendar_event"

    @property
    def description(self) -> str:
        return "Create a new event in Calendar.app with title, date/time, location, and notes."

    async def execute(
        self,
        calendar: str,
        title: str,
        start: str | None = None,
        end: str | None = None,
        duration_minutes: int | None = None,
        date: str | None = None,
        all_day: bool = False,
        location: str | None = None,
        notes: str | None = None
    ) -> dict[str, Any]:
        """Create a calendar event.

        Args:
            calendar: Calendar name (e.g., "Work", "Personal").
            title: Event title.
            start: Start datetime as "YYYY-MM-DD HH:MM" (for timed events).
            end: End datetime as "YYYY-MM-DD HH:MM" (optional).
            duration_minutes: Duration in minutes (alternative to end).
            date: Date as "YYYY-MM-DD" (for all-day events).
            all_day: Create an all-day event.
            location: Event location (optional).
            notes: Event description/notes (optional).

        Returns:
            Dictionary with creation result.
        """
        args = ["--calendar", calendar, "--title", title]

        if all_day:
            if not date:
                return {"success": False, "error": "date is required for all-day events"}
            args.extend(["--date", date, "--all-day"])
        else:
            if not start:
                return {"success": False, "error": "start is required for timed events"}
            args.extend(["--start", start])
            if end:
                args.extend(["--end", end])
            elif duration_minutes:
                args.extend(["--duration", str(duration_minutes)])

        if location:
            args.extend(["--location", location])
        if notes:
            args.extend(["--notes", notes])

        return await run_script("calendar/create-event.sh", args)


class ListCalendarsTask(Task):
    """List all available calendars."""

    @property
    def name(self) -> str:
        return "list_calendars"

    @property
    def description(self) -> str:
        return "List all calendars available in Calendar.app."

    async def execute(self, with_counts: bool = False) -> dict[str, Any]:
        """List calendars.

        Args:
            with_counts: Include event counts for each calendar.

        Returns:
            Dictionary with calendar list.
        """
        args = ["--with-counts"] if with_counts else []
        return await run_script("calendar/list-calendars.sh", args)


# =============================================================================
# REMINDERS TASKS
# =============================================================================

class GetDueTodayRemindersTask(Task):
    """Get reminders due today."""

    @property
    def name(self) -> str:
        return "get_due_today_reminders"

    @property
    def description(self) -> str:
        return "Get all incomplete reminders due today from Reminders.app."

    async def execute(
        self,
        include_overdue: bool = False,
        list_name: str | None = None
    ) -> dict[str, Any]:
        """Get reminders due today.

        Args:
            include_overdue: Also show overdue reminders.
            list_name: Only check the specified list.

        Returns:
            Dictionary with today's reminders.
        """
        args = []
        if include_overdue:
            args.append("--include-overdue")
        if list_name:
            args.extend(["--list", list_name])
        return await run_script("reminders/get-due-today.sh", args)


class CreateReminderTask(Task):
    """Create a new reminder."""

    @property
    def name(self) -> str:
        return "create_reminder"

    @property
    def description(self) -> str:
        return "Create a new reminder in Reminders.app with optional due date, priority, and notes."

    async def execute(
        self,
        title: str,
        list_name: str = "Reminders",
        due: str | None = None,
        priority: str | None = None,
        flag: bool = False,
        notes: str | None = None
    ) -> dict[str, Any]:
        """Create a reminder.

        Args:
            title: Reminder title.
            list_name: List name (default: "Reminders").
            due: Due date as "YYYY-MM-DD" or "YYYY-MM-DD HH:MM".
            priority: Priority level: "high", "medium", "low", or "none".
            flag: Flag the reminder.
            notes: Additional notes/description.

        Returns:
            Dictionary with creation result.
        """
        args = ["--title", title, "--list", list_name]
        if due:
            args.extend(["--due", due])
        if priority:
            args.extend(["--priority", priority])
        if flag:
            args.append("--flag")
        if notes:
            args.extend(["--notes", notes])

        return await run_script("reminders/create-reminder.sh", args)


class CompleteReminderTask(Task):
    """Mark reminders as complete."""

    @property
    def name(self) -> str:
        return "complete_reminder"

    @property
    def description(self) -> str:
        return "Mark one or more reminders as complete in Reminders.app."

    async def execute(
        self,
        name: str | None = None,
        pattern: str | None = None,
        list_name: str | None = None,
        dry_run: bool = False
    ) -> dict[str, Any]:
        """Complete reminders.

        Args:
            name: Exact reminder name to complete.
            pattern: Complete all reminders containing this text.
            list_name: Only search in the specified list.
            dry_run: Preview what would be completed.

        Returns:
            Dictionary with result.
        """
        if not name and not pattern:
            return {"success": False, "error": "Must specify name or pattern"}

        args = []
        if name:
            args.extend(["--name", name])
        elif pattern:
            args.extend(["--pattern", pattern])

        if list_name:
            args.extend(["--list", list_name])
        if dry_run:
            args.append("--dry-run")

        return await run_script("reminders/complete-reminder.sh", args)


class ListRemindersTask(Task):
    """List reminders with filters."""

    @property
    def name(self) -> str:
        return "list_reminders"

    @property
    def description(self) -> str:
        return "List reminders from Reminders.app with various filter options."

    async def execute(
        self,
        list_name: str | None = None,
        flagged: bool = False,
        high_priority: bool = False,
        overdue: bool = False,
        completed: bool = False,
        limit: int = 50
    ) -> dict[str, Any]:
        """List reminders.

        Args:
            list_name: Only show reminders from this list.
            flagged: Only show flagged reminders.
            high_priority: Only show high priority reminders.
            overdue: Only show overdue reminders.
            completed: Show completed instead of incomplete.
            limit: Maximum number of results.

        Returns:
            Dictionary with reminder list.
        """
        args = ["--limit", str(limit)]
        if list_name:
            args.extend(["--list", list_name])
        if flagged:
            args.append("--flagged")
        if high_priority:
            args.append("--high-priority")
        if overdue:
            args.append("--overdue")
        if completed:
            args.append("--completed")

        return await run_script("reminders/list-reminders.sh", args)


# =============================================================================
# NOTES TASKS
# =============================================================================

class CreateNoteTask(Task):
    """Create a new note."""

    @property
    def name(self) -> str:
        return "create_note"

    @property
    def description(self) -> str:
        return "Create a new note in Notes.app with title and content."

    async def execute(
        self,
        title: str,
        body: str,
        folder: str = "Notes"
    ) -> dict[str, Any]:
        """Create a note.

        Args:
            title: Note title.
            body: Note body content.
            folder: Folder name (default: "Notes").

        Returns:
            Dictionary with creation result.
        """
        args = ["--title", title, "--body", body, "--folder", folder]
        return await run_script("notes/create-note.sh", args)


class SearchNotesTask(Task):
    """Search notes by title or content."""

    @property
    def name(self) -> str:
        return "search_notes"

    @property
    def description(self) -> str:
        return "Search for notes in Notes.app matching a query in title or content."

    async def execute(
        self,
        query: str,
        folder: str | None = None,
        title_only: bool = False,
        show_preview: bool = False,
        limit: int = 20
    ) -> dict[str, Any]:
        """Search notes.

        Args:
            query: Search text.
            folder: Only search in this folder.
            title_only: Only search in note titles (faster).
            show_preview: Show a preview of note content.
            limit: Maximum number of results.

        Returns:
            Dictionary with matching notes.
        """
        args = ["--query", query, "--limit", str(limit)]
        if folder:
            args.extend(["--folder", folder])
        if title_only:
            args.append("--title-only")
        if show_preview:
            args.append("--show-preview")

        return await run_script("notes/search-notes.sh", args)


class ListNotesTask(Task):
    """List notes with various options."""

    @property
    def name(self) -> str:
        return "list_notes"

    @property
    def description(self) -> str:
        return "List notes from Notes.app with optional filters."

    async def execute(
        self,
        folder: str | None = None,
        recent_days: int | None = None,
        with_attachments: bool = False,
        limit: int = 50
    ) -> dict[str, Any]:
        """List notes.

        Args:
            folder: Only list notes from this folder.
            recent_days: Only show notes modified in last n days.
            with_attachments: Only show notes with attachments.
            limit: Maximum number of results.

        Returns:
            Dictionary with note list.
        """
        args = ["--limit", str(limit), "--show-folders"]
        if folder:
            args.extend(["--folder", folder])
        if recent_days:
            args.extend(["--recent", str(recent_days)])
        if with_attachments:
            args.append("--with-attachments")

        return await run_script("notes/list-notes.sh", args)


# =============================================================================
# SAFARI TASKS
# =============================================================================

class GetCurrentPageTask(Task):
    """Get information about the current Safari tab."""

    @property
    def name(self) -> str:
        return "get_current_safari_page"

    @property
    def description(self) -> str:
        return "Get information about the currently active Safari tab including URL, title, and optionally content."

    async def execute(
        self,
        with_text: bool = False,
        with_source: bool = False
    ) -> dict[str, Any]:
        """Get current page info.

        Args:
            with_text: Include extracted text content from the page.
            with_source: Include HTML source (truncated).

        Returns:
            Dictionary with page information.
        """
        args = []
        if with_text:
            args.append("--with-text")
        if with_source:
            args.append("--with-source")

        return await run_script("safari/get-current-page.sh", args)


class OpenUrlTask(Task):
    """Open a URL in Safari."""

    @property
    def name(self) -> str:
        return "open_url_in_safari"

    @property
    def description(self) -> str:
        return "Open a URL in Safari, optionally in a new tab or window."

    async def execute(
        self,
        url: str,
        new_tab: bool = True,
        new_window: bool = False,
        wait: bool = False,
        wait_seconds: int = 3
    ) -> dict[str, Any]:
        """Open a URL.

        Args:
            url: The URL to open.
            new_tab: Open in a new tab (default).
            new_window: Open in a new window.
            wait: Wait for page to load.
            wait_seconds: How long to wait for page load.

        Returns:
            Dictionary with result.
        """
        args = [url]
        if new_window:
            args.append("--new-window")
        elif new_tab:
            args.append("--new-tab")
        else:
            args.append("--current")

        if wait:
            args.extend(["--wait-time", str(wait_seconds)])

        return await run_script("safari/open-url.sh", args)


class ExtractLinksTask(Task):
    """Extract links from the current Safari page."""

    @property
    def name(self) -> str:
        return "extract_safari_links"

    @property
    def description(self) -> str:
        return "Extract all links from the current Safari page. Requires JavaScript permission in Safari."

    async def execute(
        self,
        domain: str | None = None,
        pattern: str | None = None,
        external_only: bool = False,
        with_text: bool = False,
        limit: int = 100
    ) -> dict[str, Any]:
        """Extract links.

        Args:
            domain: Only show links to this domain.
            pattern: Only show links containing this pattern.
            external_only: Only show external links.
            with_text: Include link text alongside URLs.
            limit: Maximum number of links.

        Returns:
            Dictionary with extracted links.
        """
        args = ["--limit", str(limit)]
        if domain:
            args.extend(["--domain", domain])
        if pattern:
            args.extend(["--pattern", pattern])
        if external_only:
            args.append("--external")
        if with_text:
            args.append("--with-text")

        return await run_script("safari/extract-links.sh", args)


class ListSafariTabsTask(Task):
    """List all open Safari tabs."""

    @property
    def name(self) -> str:
        return "list_safari_tabs"

    @property
    def description(self) -> str:
        return "List all open tabs across all Safari windows."

    async def execute(
        self,
        urls_only: bool = False,
        titles_only: bool = False,
        window: int | None = None
    ) -> dict[str, Any]:
        """List Safari tabs.

        Args:
            urls_only: Only output URLs.
            titles_only: Only output titles.
            window: Only show tabs from this window number.

        Returns:
            Dictionary with tab list.
        """
        args = []
        if urls_only:
            args.append("--urls-only")
        elif titles_only:
            args.append("--titles-only")
        if window:
            args.extend(["--window", str(window)])

        return await run_script("safari/list-tabs.sh", args)


# =============================================================================
# WEB TASKS
# =============================================================================

class GetHackerNewsTask(Task):
    """Get top stories from Hacker News."""

    @property
    def name(self) -> str:
        return "get_hacker_news"

    @property
    def description(self) -> str:
        return (
            "Get top stories from Hacker News (news.ycombinator.com) using Safari. "
            "Returns title, score, age, and URL for each story. "
            "Requires Safari's 'Allow JavaScript from Apple Events' to be enabled."
        )

    async def execute(self, count: int = 5) -> dict[str, Any]:
        """Get top Hacker News stories.

        Args:
            count: Number of stories to retrieve (default: 5, max: 30).

        Returns:
            Dictionary with top stories.
        """
        args = ["--count", str(count)]
        return await run_script("web/get-hn-top-stories.sh", args, timeout=30)


class GoogleSearchTask(Task):
    """Perform a Google search using Safari."""

    @property
    def name(self) -> str:
        return "google_search"

    @property
    def description(self) -> str:
        return (
            "Perform a Google search using Safari and extract the top results. "
            "Returns title, URL, and snippet for each result. "
            "Requires Safari's 'Allow JavaScript from Apple Events' to be enabled."
        )

    async def execute(self, query: str, count: int = 5) -> dict[str, Any]:
        """Perform a Google search.

        Args:
            query: The search query.
            count: Number of results to retrieve (default: 5, max: 20).

        Returns:
            Dictionary with search results.
        """
        args = ["--count", str(count), query]
        return await run_script("web/google-search.sh", args, timeout=30)


# =============================================================================
# REGISTRATION HELPER
# =============================================================================

def register_macos_tasks(registry) -> None:
    """Register all macOS automation tasks with a registry.

    Args:
        registry: TaskRegistry to register tasks with.
    """
    # Mail tasks
    registry.register(GetUnreadEmailsTask())
    registry.register(SearchEmailsTask())
    registry.register(SendEmailTask())
    registry.register(MoveEmailTask())
    registry.register(DownloadAttachmentsTask())
    registry.register(MarkEmailsReadTask())

    # Calendar tasks
    registry.register(GetTodayEventsTask())
    registry.register(GetWeekEventsTask())
    registry.register(CreateCalendarEventTask())
    registry.register(ListCalendarsTask())

    # Reminders tasks
    registry.register(GetDueTodayRemindersTask())
    registry.register(CreateReminderTask())
    registry.register(CompleteReminderTask())
    registry.register(ListRemindersTask())

    # Notes tasks
    registry.register(CreateNoteTask())
    registry.register(SearchNotesTask())
    registry.register(ListNotesTask())

    # Safari tasks
    registry.register(GetCurrentPageTask())
    registry.register(OpenUrlTask())
    registry.register(ExtractLinksTask())
    registry.register(ListSafariTabsTask())

    # Web tasks
    registry.register(GetHackerNewsTask())
    registry.register(GoogleSearchTask())
