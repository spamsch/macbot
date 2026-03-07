"""Tasks: macOS Automation

Provides agent tools for automating Apple's native productivity apps
(Mail, Calendar, Reminders, Notes, Safari) via AppleScript wrappers.

These tasks wrap the shell scripts in /workspace/macos-automation/.
"""

import asyncio
import os
import shlex
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
    cmd = " ".join(shlex.quote(p) for p in cmd_parts)

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
            "Search emails in Mail.app. Uses the Core Spotlight index for fast searches when available, "
            "with automatic fallback to AppleScript/SQLite for environments where the Spotlight cache is not yet built. "
            "Can search by sender, recipient, subject, message_id, or list all emails in an account. "
            "Use recipient to find emails SENT TO someone (searches To and CC fields — Spotlight only; not supported in fallback mode). "
            "IMPORTANT: 'emails from X account' means emails RECEIVED BY that account (use account parameter), "
            "not emails FROM that sender. Use message_id for precise lookup of a specific email. "
            "IMPORTANT: When the user asks to READ an email, see its content/body, or wants to know WHAT an email says, "
            "you MUST set with_content=True in the FIRST search call — without it you only get a short snippet. "
            "Add with_links=True to also extract hyperlinks from HTML emails (slower, only when URLs are needed)."
        )

    async def execute(
        self,
        sender: str | None = None,
        recipient: str | None = None,
        subject: str | None = None,
        message_id: str | None = None,
        account: str | None = None,
        mailbox: str | None = None,
        today_only: bool = False,
        days: int | None = None,
        all_mailboxes: bool = False,
        with_content: bool = False,
        with_links: bool = False,
        limit: int = 20
    ) -> dict[str, Any]:
        """Search emails.

        Args:
            sender: Search for emails from sender containing this pattern.
            recipient: Search for emails sent to recipient (To/CC) containing this pattern.
            subject: Search for emails with subject containing this pattern.
            message_id: Search for specific email by Message-ID (fast direct lookup).
            account: Search in specified account (e.g., "waas.rent" for all emails in that account).
            mailbox: Search specific mailbox (e.g., "Archive", "Sent Items").
            today_only: Only return emails from today.
            days: Only return emails from the last N days.
            all_mailboxes: Search all mailboxes including Sent, Trash, etc.
            with_content: Include the full email body text (use when you need to read the email content).
            with_links: Also extract hyperlinks from HTML email source (slower, use only when URLs are needed). Requires with_content.
            limit: Maximum number of results to return.

        Returns:
            Dictionary with matching emails.
        """
        if not sender and not recipient and not subject and not account and not message_id and not today_only and not days:
            return {"success": False, "error": "Must specify sender, recipient, subject, message_id, account, today_only, or days"}

        # Try Spotlight index first; fall back to AppleScript/SQLite when unavailable.
        spotlight_result = await self._try_spotlight_search(
            sender=sender, recipient=recipient, subject=subject,
            message_id=message_id, account=account, mailbox=mailbox,
            today_only=today_only, days=days, limit=limit,
            with_content=with_content, with_links=with_links,
        )
        if spotlight_result is not None:
            return spotlight_result

        # Spotlight cache unavailable — fall back to AppleScript/SQLite path.
        # Note: recipient search is not supported in the fallback path.
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
        if with_links:
            args.append("--with-links")
        args.extend(["--limit", str(limit)])

        # Metadata-only search: try fast SQLite path first.
        if not with_content and not with_links:
            result = await run_script("mail/search-emails-sqlite.sh", args, timeout=10)
            if result.get("success"):
                return result

        return await run_script("mail/search-emails.sh", args, timeout=60)

    async def _try_spotlight_search(
        self,
        sender: str | None = None,
        recipient: str | None = None,
        subject: str | None = None,
        message_id: str | None = None,
        account: str | None = None,
        mailbox: str | None = None,
        today_only: bool = False,
        days: int | None = None,
        limit: int = 20,
        with_content: bool = False,
        with_links: bool = False,
    ) -> dict[str, Any] | None:
        """Search using the Core Spotlight index.

        Returns ``None`` when the Spotlight cache is unavailable so the caller
        can fall back to the AppleScript/SQLite path.
        """
        try:
            import asyncio

            from macbot.spotlight.mail_search import MailSearchIndex

            # Convert message_id string to int if provided
            msg_id_int = None
            if message_id:
                try:
                    msg_id_int = int(message_id)
                except ValueError:
                    pass

            def _search() -> tuple[bool, list[dict[str, Any]]]:
                index = MailSearchIndex()
                # Auto-rebuild if index is empty or stale
                if index.message_count() == 0 or index.needs_rebuild():
                    try:
                        index.rebuild()
                    except FileNotFoundError:
                        index.close()
                        return (False, [])
                results = index.search(
                    sender=sender, recipient=recipient, subject=subject,
                    message_id=msg_id_int, account=account, mailbox=mailbox,
                    today_only=today_only, days=days, limit=limit,
                    with_content=with_content, with_links=with_links,
                )
                index.close()
                return (True, results)

            loop = asyncio.get_running_loop()
            has_data, results = await loop.run_in_executor(None, _search)

            if not has_data:
                # Cache could not be built (Spotlight store missing) — signal fallback.
                return None

            emails = []
            for r in results:
                email = {
                    "subject": r.get("subject", ""),
                    "sender": r.get("sender", ""),
                    "recipients": r.get("recipients", ""),
                    "date": r.get("date_received", ""),
                    "is_read": bool(r.get("is_read")),
                    "snippet": r.get("snippet", "")[:200],
                }
                if r.get("content"):
                    email["content"] = r["content"]
                if r.get("cc_recipients"):
                    email["cc_recipients"] = r["cc_recipients"]
                if r.get("attachment_names"):
                    email["attachments"] = r["attachment_names"]
                if r.get("account"):
                    email["account"] = r["account"]
                if r.get("mailboxes"):
                    email["mailbox"] = r["mailboxes"]
                if r.get("mail_message_id"):
                    email["mail_message_id"] = r["mail_message_id"]
                emails.append(email)

            return {
                "success": True,
                "source": "spotlight",
                "count": len(emails),
                "emails": emails,
            }
        except Exception:
            # Spotlight module unavailable — signal fallback.
            return None


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
        attachments: list[str] | None = None,
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
            attachments: List of absolute file paths to attach (optional).
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
        if attachments:
            for path in attachments:
                abs_path = os.path.abspath(os.path.expanduser(path))
                if not os.path.exists(abs_path):
                    return {"return_code": 1, "stdout": "", "stderr": f"Attachment not found: {abs_path}"}
                args.extend(["--attachment", abs_path])
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

        result = await run_script("mail/move-email.sh", args, timeout=60)
        if result.get("success") and "No matching messages found" in result.get("output", ""):
            result["success"] = False
            result["error"] = result["output"]
        return result


class DownloadAttachmentsTask(Task):
    """Download email attachments to a folder."""

    @property
    def name(self) -> str:
        return "download_attachments"

    @property
    def description(self) -> str:
        return (
            "Download attachments from emails to a specified folder. Best used with message_id "
            "from search_emails for precise matching. "
            "Use output='/tmp/attachments' for a guaranteed-writable location. "
            "Avoid guessing usernames in paths — use ~/Downloads or /tmp instead."
        )

    async def execute(
        self,
        output: str,
        message_id: str | None = None,
        sender: str | None = None,
        subject: str | None = None,
        account: str | None = None,
        mailbox: str | None = None,
        all_mailboxes: bool = False,
        limit: int = 5,
        days: int | None = None,
    ) -> dict[str, Any]:
        """Download attachments from matching emails.

        Args:
            output: Destination folder for attachments (e.g. ~/Downloads or /tmp/attachments). Supports ~ expansion.
            message_id: Match specific email by Message-ID (recommended).
            sender: Match emails from sender containing this pattern.
            subject: Match emails with subject containing this pattern.
            account: Only search in specified account.
            mailbox: Only search in specified mailbox (default: Inbox).
            all_mailboxes: Search all mailboxes including Sent, Archive, Trash, etc.
            limit: Maximum number of emails to process.
            days: Only include emails from the last N days.

        Returns:
            Dictionary with download result.
        """
        if not message_id and not sender and not subject:
            return {"success": False, "error": "Must specify message_id, sender, or subject"}

        # Expand ~ and resolve to absolute path so the shell script gets a real path
        output = os.path.expanduser(output)
        output = os.path.abspath(output)

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
        if all_mailboxes:
            args.append("--all-mailboxes")
        args.extend(["--limit", str(limit)])
        if days is not None:
            args.extend(["--days", str(days)])

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

    async def execute(
        self,
        calendar: str | None = None,
        account: str | None = None,
    ) -> dict[str, Any]:
        """Get today's events.

        Args:
            calendar: Only show events from this calendar (optional).
            account: Only show events from calendars in this account (optional).

        Returns:
            Dictionary with today's events.
        """
        args: list[str] = []
        if calendar:
            args.extend(["--calendar", calendar])
        if account:
            args.extend(["--account", account])
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
        calendar: str | None = None,
        account: str | None = None,
    ) -> dict[str, Any]:
        """Get upcoming events.

        Args:
            days: Number of days to look ahead (default: 7).
            calendar: Only show events from this calendar (optional).
            account: Only show events from calendars in this account (optional).

        Returns:
            Dictionary with upcoming events.
        """
        args = ["--days", str(days)]
        if calendar:
            args.extend(["--calendar", calendar])
        if account:
            args.extend(["--account", account])
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
        notes: str | None = None,
        account: str | None = None,
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
            account: Account name to disambiguate calendars with the same name (optional).

        Returns:
            Dictionary with creation result.
        """
        args = ["--calendar", calendar, "--title", title]

        if account:
            args.extend(["--account", account])

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
    """List all available calendars grouped by account."""

    @property
    def name(self) -> str:
        return "list_calendars"

    @property
    def description(self) -> str:
        return "List all calendars available in Calendar.app, grouped by account."

    async def execute(
        self,
        with_counts: bool = False,
        account: str | None = None,
    ) -> dict[str, Any]:
        """List calendars.

        Args:
            with_counts: Include event counts for each calendar.
            account: Only show calendars from this account (optional).

        Returns:
            Dictionary with calendar list grouped by account.
        """
        args: list[str] = []
        if with_counts:
            args.append("--with-counts")
        if account:
            args.extend(["--account", account])
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
        include_completed: bool = False,
        limit: int = 50
    ) -> dict[str, Any]:
        """List reminders.

        Args:
            list_name: Only show reminders from this list.
            flagged: Only show flagged reminders.
            high_priority: Only show high priority reminders.
            overdue: Only show overdue reminders.
            completed: Show completed instead of incomplete.
            include_completed: Alias for completed.
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
        if completed or include_completed:
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
        folder: str = "Notes",
        html: bool = False
    ) -> dict[str, Any]:
        """Create a note.

        Args:
            title: Note title.
            body: Note body content (plain text or HTML).
            folder: Folder name (default: "Notes").
            html: If True, treat body as HTML. Use <ul><li> for bullet lists,
                  <strike> for completed items. This is how todo lists are
                  formatted in Notes.app.

        Returns:
            Dictionary with creation result.
        """
        args = ["--title", title, "--body", body, "--folder", folder]
        if html:
            args.append("--html")
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


class ReadNoteTask(Task):
    """Read a note's full content."""

    @property
    def name(self) -> str:
        return "read_note"

    @property
    def description(self) -> str:
        return "Read the full content of a note from Notes.app by title."

    async def execute(
        self,
        title: str,
        folder: str | None = None
    ) -> dict[str, Any]:
        """Read a note's content.

        Args:
            title: Note title (or partial match).
            folder: Optional folder to search in.

        Returns:
            Dictionary with note title, folder, and full plaintext content.
        """
        args = ["--title", title]
        if folder:
            args.extend(["--folder", folder])

        return await run_script("notes/read-note.sh", args)


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


class ListNoteFoldersTask(Task):
    """List all folders in Notes.app."""

    @property
    def name(self) -> str:
        return "list_note_folders"

    @property
    def description(self) -> str:
        return "List all folders in Notes.app with note counts."

    async def execute(self) -> dict[str, Any]:
        """List note folders.

        Returns:
            Dictionary with folder list and note counts.
        """
        return await run_script("notes/list-folders.sh", [])


class CreateNoteFolderTask(Task):
    """Create a new folder in Notes.app."""

    @property
    def name(self) -> str:
        return "create_note_folder"

    @property
    def description(self) -> str:
        return "Create a new folder in Notes.app. Optionally nest inside a parent folder."

    async def execute(
        self,
        folder_name: str,
        parent: str | None = None,
    ) -> dict[str, Any]:
        """Create a note folder.

        Args:
            folder_name: Name for the new folder.
            parent: Parent folder name to nest inside (optional).

        Returns:
            Dictionary with creation result.
        """
        args = ["--name", folder_name]
        if parent:
            args.extend(["--parent", parent])
        return await run_script("notes/create-folder.sh", args)


class DeleteNoteFolderTask(Task):
    """Delete a folder in Notes.app."""

    @property
    def name(self) -> str:
        return "delete_note_folder"

    @property
    def description(self) -> str:
        return "Delete a folder in Notes.app. Folder must be empty (move or delete notes first)."

    async def execute(self, folder_name: str) -> dict[str, Any]:
        """Delete a note folder.

        Args:
            folder_name: Name of the folder to delete.

        Returns:
            Dictionary with deletion result.
        """
        return await run_script("notes/delete-folder.sh", ["--name", folder_name])


class RenameNoteFolderTask(Task):
    """Rename a folder in Notes.app."""

    @property
    def name(self) -> str:
        return "rename_note_folder"

    @property
    def description(self) -> str:
        return "Rename a folder in Notes.app."

    async def execute(self, folder_name: str, new_name: str) -> dict[str, Any]:
        """Rename a note folder.

        Args:
            folder_name: Current folder name.
            new_name: New folder name.

        Returns:
            Dictionary with rename result.
        """
        return await run_script("notes/rename-folder.sh", ["--name", folder_name, "--new-name", new_name])


class MoveNoteTask(Task):
    """Move a note to a different folder in Notes.app."""

    @property
    def name(self) -> str:
        return "move_note"

    @property
    def description(self) -> str:
        return "Move a note to a different folder in Notes.app. Searches by title (partial match)."

    async def execute(
        self,
        title: str,
        to: str,
        folder: str | None = None,
    ) -> dict[str, Any]:
        """Move a note.

        Args:
            title: Title (or partial title) of the note to move.
            to: Destination folder name.
            folder: Source folder to search in (optional, searches all if omitted).

        Returns:
            Dictionary with move result.
        """
        args = ["--title", title, "--to", to]
        if folder:
            args.extend(["--from", folder])
        return await run_script("notes/move-note.sh", args)


class DeleteNoteTask(Task):
    """Delete a note in Notes.app."""

    @property
    def name(self) -> str:
        return "delete_note"

    @property
    def description(self) -> str:
        return "Delete a note in Notes.app. Searches by title (partial match). Moves to Recently Deleted."

    async def execute(
        self,
        title: str,
        folder: str | None = None,
    ) -> dict[str, Any]:
        """Delete a note.

        Args:
            title: Title (or partial title) of the note to delete.
            folder: Folder to search in (optional, searches all if omitted).

        Returns:
            Dictionary with deletion result.
        """
        args = ["--title", title]
        if folder:
            args.extend(["--folder", folder])
        return await run_script("notes/delete-note.sh", args)


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
# SPOTLIGHT TASKS
# =============================================================================

class SpotlightSearchTask(Task):
    """Search for emails, files, and documents using macOS Spotlight index."""

    @property
    def name(self) -> str:
        return "spotlight_search"

    @property
    def description(self) -> str:
        return (
            "Fast indexed search using macOS Spotlight (mdfind). "
            "Searches files and documents on disk by name, content, or type. "
            "Use recently_used=True to find files the user recently opened (answers 'what did I work on'). "
            "Can also find .eml files on disk (but NOT Mail.app inbox — use search_emails for that)."
        )

    async def execute(
        self,
        query: str | None = None,
        content_type: str | None = None,
        sender: str | None = None,
        recipient: str | None = None,
        subject: str | None = None,
        body: str | None = None,
        file_name: str | None = None,
        days: int | None = None,
        recently_used: bool = False,
        exclude_apps: bool = False,
        unread: bool = False,
        flagged: bool = False,
        has_attachments: bool = False,
        directory: str | None = None,
        limit: int = 20
    ) -> dict[str, Any]:
        """Search using Spotlight.

        Args:
            query: Free text search across content.
            content_type: Filter by type: "email", "pdf", "image", "document", "presentation", "spreadsheet".
            sender: Email sender address pattern (partial match, for emails).
            recipient: Email recipient address pattern (partial match, for emails).
            subject: Email subject text (partial match, for emails).
            body: Search email body or file content text (fast indexed search).
            file_name: Search by file/document name pattern.
            days: Only return results from the last N days.
            recently_used: Search by last-opened date instead of modification date. Use with days to find recently opened files. Defaults days to 1 if not specified.
            exclude_apps: Exclude application bundles from results. Useful with recently_used to show only documents/files.
            unread: Only return unread emails.
            flagged: Only return flagged emails.
            has_attachments: Only return emails with attachments.
            directory: Restrict search to a specific directory path.
            limit: Maximum number of results to return.

        Returns:
            Dictionary with search results including metadata.
        """
        if not any([query, sender, recipient, subject, body, file_name, recently_used, unread, flagged, has_attachments]):
            return {"success": False, "error": "Must specify at least one search criterion"}

        args = []
        if query:
            args.extend(["--query", query])
        if content_type:
            args.extend(["--type", content_type])
        if sender:
            args.extend(["--from", sender])
        if recipient:
            args.extend(["--to", recipient])
        if subject:
            args.extend(["--subject", subject])
        if body:
            args.extend(["--body", body])
        if file_name:
            args.extend(["--name", file_name])
        if days:
            args.extend(["--days", str(days)])
        if recently_used:
            args.append("--last-used")
        if exclude_apps:
            args.append("--exclude-apps")
        if unread:
            args.append("--unread")
        if flagged:
            args.append("--flagged")
        if has_attachments:
            args.append("--has-attachments")
        if directory:
            args.extend(["--dir", os.path.expanduser(directory)])
        args.extend(["--limit", str(limit)])

        result = await run_script("spotlight/search.sh", args, timeout=30)

        # Assign unique short IDs to each result for easy user reference
        if result.get("success") and result.get("output"):
            result["output"] = self._add_result_ids(result["output"])

        return result

    @staticmethod
    def _add_result_ids(output: str) -> str:
        """Replace numeric indices with unique short IDs (e.g. [f3a]) for easy reference.

        Adds a Ref: field line after each header so the LLM includes it in responses.
        """
        import random
        import re
        import string

        chars = string.ascii_lowercase + string.digits
        has_ids = False

        def _make_id() -> str:
            return "".join(random.choices(chars, k=3))

        def _replace(m: re.Match) -> str:
            nonlocal has_ids
            has_ids = True
            kind = m.group(1)  # "File", "Email", or "Email file"
            uid = _make_id()
            return f"--- {kind} [{uid}] ---\nRef: {uid}"

        output = re.sub(r"--- (File|Email file|Email) \d+ ---", _replace, output)

        if has_ids:
            output = ("IMPORTANT: Always include the Ref ID (e.g. [abc]) for each result "
                      "so the user can reference files by ID.\n\n" + output)

        return output


# =============================================================================
# FINDER TASKS
# =============================================================================

class ListDirectoryTask(Task):
    """List files in a directory with metadata, pagination, and summary."""

    @property
    def name(self) -> str:
        return "list_directory"

    @property
    def description(self) -> str:
        return (
            "List files in a directory with metadata (name, size, date, type). "
            "Use summary=True for a quick overview with counts by type and age. "
            "Supports pagination with offset/limit for large directories. "
            "Use filter_type to list only specific categories: images, documents, "
            "spreadsheets, archives, installers, videos, audio, code. "
            "Use dirs_only=True to list subdirectories instead of files, with metadata "
            "(size, item count, contents breakdown). Skips known category folders."
        )

    async def execute(
        self,
        directory: str = "~/Downloads",
        offset: int = 0,
        limit: int = 50,
        sort_by: str = "date",
        sort_order: str = "desc",
        filter_type: str | None = None,
        summary: bool = False,
        include_hidden: bool = False,
        dirs_only: bool = False,
    ) -> dict[str, Any]:
        """List files in a directory with metadata and pagination.

        Args:
            directory: Directory to list (default: ~/Downloads).
            offset: Skip first N entries for pagination.
            limit: Maximum entries to return (default: 50).
            sort_by: Sort field: "name", "size", "date", or "type".
            sort_order: Sort order: "asc" or "desc" (default: desc, newest first).
            filter_type: Filter by category: images, documents, spreadsheets, archives, installers, videos, audio, code.
            summary: If True, return a high-level overview with counts by type and age instead of individual files.
            include_hidden: Include dotfiles (hidden files).
            dirs_only: If True, list subdirectories instead of files. Shows size, item count, and contents breakdown. Skips known category folders (Images/, Documents/, etc.).

        Returns:
            Dictionary with file listing or summary.
        """
        args = ["--dir", os.path.expanduser(directory)]

        if dirs_only:
            args.append("--dirs-only")

        if summary:
            args.append("--summary")
        else:
            if offset > 0:
                args.extend(["--offset", str(offset)])
            if limit != 50:
                args.extend(["--limit", str(limit)])
            if sort_by != "date":
                args.extend(["--sort", sort_by])
            if sort_order != "desc":
                args.extend(["--order", sort_order])
            if filter_type:
                args.extend(["--filter-type", filter_type])

        if include_hidden:
            args.append("--include-hidden")

        timeout = 60 if dirs_only else 30
        return await run_script("finder/list-directory.sh", args, timeout=timeout)


# =============================================================================
# SHORTCUTS TASKS
# =============================================================================

class ListShortcutsTask(Task):
    """List available macOS Shortcuts."""

    @property
    def name(self) -> str:
        return "list_shortcuts"

    @property
    def description(self) -> str:
        return (
            "List available shortcuts from the macOS Shortcuts app. "
            "Can filter by folder or list folders."
        )

    async def execute(
        self,
        folder_name: str | None = None,
        list_folders: bool = False
    ) -> dict[str, Any]:
        """List shortcuts.

        Args:
            folder_name: Only list shortcuts in this folder.
            list_folders: List shortcut folders instead of shortcuts.

        Returns:
            Dictionary with shortcut list.
        """
        args = []
        if list_folders:
            args.append("--folders")
        elif folder_name:
            args.extend(["--folder", folder_name])

        return await run_script("shortcuts/list-shortcuts.sh", args)


class RunShortcutTask(Task):
    """Run a macOS Shortcut by name."""

    @property
    def name(self) -> str:
        return "run_shortcut"

    @property
    def description(self) -> str:
        return (
            "Run a shortcut from the macOS Shortcuts app by name. "
            "Shortcuts can automate third-party apps, HomeKit, Focus modes, Music, and more. "
            "Use list_shortcuts first to see available shortcuts."
        )

    async def execute(
        self,
        shortcut_name: str,
        input_text: str | None = None
    ) -> dict[str, Any]:
        """Run a shortcut.

        Args:
            shortcut_name: Name of the shortcut to run.
            input_text: Optional text input to pass to the shortcut.

        Returns:
            Dictionary with shortcut output.
        """
        args = ["--name", shortcut_name]

        if input_text:
            # Write input to a temp file and pass as --input
            import tempfile
            tmp = tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", prefix="shortcut-input-", delete=False
            )
            try:
                tmp.write(input_text)
                tmp.close()
                args.extend(["--input", tmp.name])
                return await run_script("shortcuts/run-shortcut.sh", args, timeout=60)
            finally:
                os.unlink(tmp.name)
        else:
            return await run_script("shortcuts/run-shortcut.sh", args, timeout=60)


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
# CONTACTS TASKS
# =============================================================================

class SearchContactsTask(Task):
    """Search contacts by name, email, phone, or organization."""

    @property
    def name(self) -> str:
        return "search_contacts"

    @property
    def description(self) -> str:
        return (
            "Search contacts in Contacts.app by name, email, phone, or organization. "
            "Name and organization searches are fast (use `whose` clause). "
            "Email and phone searches are slower (bulk fetch then filter). "
            "At least one search criterion is required."
        )

    async def execute(
        self,
        name: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        organization: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Search contacts.

        Args:
            name: Search by contact name (partial match).
            email: Search by email address (partial match).
            phone: Search by phone number (partial match).
            organization: Search by organization/company name (partial match).
            limit: Maximum number of results (default: 20).

        Returns:
            Dictionary with matching contacts.
        """
        if not name and not email and not phone and not organization:
            return {"success": False, "error": "Must specify at least one of: name, email, phone, organization"}

        args = []
        if name:
            args.extend(["--name", name])
        if email:
            args.extend(["--email", email])
        if phone:
            args.extend(["--phone", phone])
        if organization:
            args.extend(["--organization", organization])
        args.extend(["--limit", str(limit)])

        return await run_script("contacts/search-contacts.sh", args, timeout=30)


class GetContactTask(Task):
    """Get full details of a specific contact."""

    @property
    def name(self) -> str:
        return "get_contact"

    @property
    def description(self) -> str:
        return (
            "Get the full contact card from Contacts.app including all emails, phones, "
            "addresses, organization, job title, birthday, notes, and groups. "
            "Search by name (partial match) or use --exact for exact match."
        )

    async def execute(
        self,
        name: str | None = None,
        id: str | None = None,
        exact: bool = False,
    ) -> dict[str, Any]:
        """Get contact details.

        Args:
            name: Contact name to look up.
            id: Contact ID for direct lookup.
            exact: If True, match name exactly instead of partial match.

        Returns:
            Dictionary with full contact details.
        """
        if not name and not id:
            return {"success": False, "error": "Must specify name or id"}

        args = []
        if name:
            args.extend(["--name", name])
        if id:
            args.extend(["--id", id])
        if exact:
            args.append("--exact")

        return await run_script("contacts/get-contact.sh", args, timeout=15)


class CreateContactTask(Task):
    """Create a new contact in Contacts.app."""

    @property
    def name(self) -> str:
        return "create_contact"

    @property
    def description(self) -> str:
        return (
            "Create a new contact in Contacts.app. First name is required. "
            "Can set email, phone, organization, job title, and assign to a group."
        )

    async def execute(
        self,
        first_name: str,
        last_name: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        organization: str | None = None,
        group: str | None = None,
        job_title: str | None = None,
    ) -> dict[str, Any]:
        """Create a contact.

        Args:
            first_name: First name (required).
            last_name: Last name.
            email: Email address.
            phone: Phone number.
            organization: Company/organization name.
            group: Contact group to add to (must exist).
            job_title: Job title.

        Returns:
            Dictionary with created contact info.
        """
        args = ["--first-name", first_name]
        if last_name:
            args.extend(["--last-name", last_name])
        if email:
            args.extend(["--email", email])
        if phone:
            args.extend(["--phone", phone])
        if organization:
            args.extend(["--organization", organization])
        if group:
            args.extend(["--group", group])
        if job_title:
            args.extend(["--job-title", job_title])

        return await run_script("contacts/create-contact.sh", args, timeout=15)


class ListContactGroupsTask(Task):
    """List contact groups from Contacts.app."""

    @property
    def name(self) -> str:
        return "list_contact_groups"

    @property
    def description(self) -> str:
        return "List all contact groups in Contacts.app with member counts."

    async def execute(
        self,
        with_members: bool = False,
        limit: int = 50,
    ) -> dict[str, Any]:
        """List contact groups.

        Args:
            with_members: If True, include member names for each group.
            limit: Maximum number of groups to return (default: 50).

        Returns:
            Dictionary with contact groups.
        """
        args = []
        if with_members:
            args.append("--with-members")
        args.extend(["--limit", str(limit)])

        return await run_script("contacts/list-groups.sh", args, timeout=15)


# =============================================================================
# MESSAGES TASKS
# =============================================================================

class SendMessageTask(Task):
    """Send an iMessage via Messages.app."""

    @property
    def name(self) -> str:
        return "send_imessage"

    @property
    def description(self) -> str:
        return (
            "Send an iMessage using Messages.app. "
            "Requires a recipient (phone number with country code or Apple ID email) and message body. "
            "Always confirm the message content with the user before sending."
        )

    async def execute(
        self,
        to: str,
        body: str,
    ) -> dict[str, Any]:
        """Send an iMessage.

        Args:
            to: Recipient phone number (with country code, e.g. +15551234567) or Apple ID email.
            body: Message text to send.

        Returns:
            Dictionary with send confirmation.
        """
        args = ["--to", to, "--body", body]
        return await run_script("messages/send-message.sh", args, timeout=15)


class ListChatsTask(Task):
    """List recent iMessage chats."""

    @property
    def name(self) -> str:
        return "list_imessage_chats"

    @property
    def description(self) -> str:
        return (
            "List recent iMessage/SMS chats from Messages.app history. "
            "Reads from chat.db (requires Full Disk Access). "
            "Shows chat name, last message date, and preview."
        )

    async def execute(
        self,
        limit: int = 20,
        days: int = 7,
    ) -> dict[str, Any]:
        """List recent chats.

        Args:
            limit: Maximum number of chats to return (default: 20).
            days: Only show chats with messages in the last N days (default: 7).

        Returns:
            Dictionary with recent chats.
        """
        args = ["--limit", str(limit), "--days", str(days)]
        return await run_script("messages/list-chats.sh", args, timeout=10)


class SearchMessagesTask(Task):
    """Search iMessage history."""

    @property
    def name(self) -> str:
        return "search_imessages"

    @property
    def description(self) -> str:
        return (
            "Search iMessage/SMS history by text content or sender. "
            "Reads from chat.db (requires Full Disk Access). "
            "At least query or from_handle is required."
        )

    async def execute(
        self,
        query: str | None = None,
        from_handle: str | None = None,
        days: int = 7,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Search messages.

        Args:
            query: Text to search for in message content.
            from_handle: Sender phone number or email to filter by.
            days: Only search messages from the last N days (default: 7).
            limit: Maximum number of results (default: 20).

        Returns:
            Dictionary with matching messages.
        """
        if not query and not from_handle:
            return {"success": False, "error": "Must specify at least query or from_handle"}

        args = []
        if query:
            args.extend(["--query", query])
        if from_handle:
            args.extend(["--from", from_handle])
        args.extend(["--days", str(days)])
        args.extend(["--limit", str(limit)])

        return await run_script("messages/search-messages.sh", args, timeout=15)


# =============================================================================
# SYSTEM CONTROL TASKS
# =============================================================================

class GetSystemStatusTask(Task):
    """Get current system status (WiFi, Bluetooth, volume, dark mode, DND)."""

    @property
    def name(self) -> str:
        return "get_system_status"

    @property
    def description(self) -> str:
        return (
            "Get the current system status including WiFi (on/off and network name), "
            "Bluetooth (on/off), volume (level and muted state), dark mode, and Do Not Disturb."
        )

    async def execute(self) -> dict[str, Any]:
        """Get system status.

        Returns:
            Dictionary with current system status.
        """
        return await run_script("system/get-system-status.sh", timeout=10)


class ToggleWifiTask(Task):
    """Toggle WiFi on or off."""

    @property
    def name(self) -> str:
        return "toggle_wifi"

    @property
    def description(self) -> str:
        return (
            "Toggle WiFi on or off, or set to a specific state. "
            "Auto-detects the WiFi hardware device. Idempotent — reports if already in desired state."
        )

    async def execute(self, state: str | None = None) -> dict[str, Any]:
        """Toggle WiFi.

        Args:
            state: Desired state — "on", "off", or None to toggle.

        Returns:
            Dictionary with WiFi state after change.
        """
        args = []
        if state == "on":
            args.append("--on")
        elif state == "off":
            args.append("--off")

        return await run_script("system/toggle-wifi.sh", args, timeout=10)


class ToggleBluetoothTask(Task):
    """Toggle Bluetooth on or off."""

    @property
    def name(self) -> str:
        return "toggle_bluetooth"

    @property
    def description(self) -> str:
        return (
            "Toggle Bluetooth on or off, or set to a specific state. "
            "Uses IOBluetooth framework (no third-party deps). Idempotent."
        )

    async def execute(self, state: str | None = None) -> dict[str, Any]:
        """Toggle Bluetooth.

        Args:
            state: Desired state — "on", "off", or None to toggle.

        Returns:
            Dictionary with Bluetooth state after change.
        """
        args = []
        if state == "on":
            args.append("--on")
        elif state == "off":
            args.append("--off")

        return await run_script("system/toggle-bluetooth.sh", args, timeout=10)


class ListBluetoothDevicesTask(Task):
    """List paired Bluetooth devices."""

    @property
    def name(self) -> str:
        return "list_bluetooth_devices"

    @property
    def description(self) -> str:
        return "List paired Bluetooth devices with their connection status."

    async def execute(
        self,
        connected_only: bool = False,
        limit: int = 20,
    ) -> dict[str, Any]:
        """List Bluetooth devices.

        Args:
            connected_only: If True, only show connected devices.
            limit: Maximum number of devices to return (default: 20).

        Returns:
            Dictionary with Bluetooth device list.
        """
        args = []
        if connected_only:
            args.append("--connected-only")
        args.extend(["--limit", str(limit)])

        return await run_script("system/list-bluetooth-devices.sh", args, timeout=10)


class SetVolumeTask(Task):
    """Set system volume level or mute/unmute."""

    @property
    def name(self) -> str:
        return "set_volume"

    @property
    def description(self) -> str:
        return (
            "Set the system output volume level (0-100) and/or mute/unmute. "
            "Can set level and mute state independently or together."
        )

    async def execute(
        self,
        level: int | None = None,
        mute: bool | None = None,
    ) -> dict[str, Any]:
        """Set volume.

        Args:
            level: Volume level from 0 to 100.
            mute: True to mute, False to unmute, None to leave unchanged.

        Returns:
            Dictionary with volume state after change.
        """
        if level is None and mute is None:
            return {"success": False, "error": "Must specify level or mute"}

        args = []
        if level is not None:
            args.extend(["--level", str(level)])
        if mute is True:
            args.append("--mute")
        elif mute is False:
            args.append("--unmute")

        return await run_script("system/set-volume.sh", args, timeout=10)


class ToggleDarkModeTask(Task):
    """Toggle dark mode on or off."""

    @property
    def name(self) -> str:
        return "toggle_dark_mode"

    @property
    def description(self) -> str:
        return (
            "Toggle macOS dark mode on or off, or set to a specific state. "
            "Idempotent — reports if already in desired state."
        )

    async def execute(self, state: str | None = None) -> dict[str, Any]:
        """Toggle dark mode.

        Args:
            state: Desired state — "on", "off", or None to toggle.

        Returns:
            Dictionary with dark mode state after change.
        """
        args = []
        if state == "on":
            args.append("--on")
        elif state == "off":
            args.append("--off")

        return await run_script("system/toggle-dark-mode.sh", args, timeout=10)


class ToggleDndTask(Task):
    """Toggle Do Not Disturb on or off."""

    @property
    def name(self) -> str:
        return "toggle_dnd"

    @property
    def description(self) -> str:
        return (
            "Toggle Do Not Disturb (Focus mode) on or off. "
            "Uses a Shortcuts bridge — requires a shortcut named 'Toggle Do Not Disturb'. "
            "Outputs setup instructions if the shortcut is not found."
        )

    async def execute(self, state: str | None = None) -> dict[str, Any]:
        """Toggle Do Not Disturb.

        Args:
            state: Desired state — "on", "off", or None to toggle.

        Returns:
            Dictionary with DND state or setup instructions.
        """
        args = []
        if state == "on":
            args.append("--on")
        elif state == "off":
            args.append("--off")

        return await run_script("system/toggle-dnd.sh", args, timeout=15)


# =============================================================================
# THINGS3 TASKS
# =============================================================================

class ShowThingsTodayTask(Task):
    """Show the Things3 Today list."""

    @property
    def name(self) -> str:
        return "show_things_today"

    @property
    def description(self) -> str:
        return "Show all to-dos in the Things3 Today list with project, tags, and due dates."

    async def execute(self) -> dict[str, Any]:
        """Show Today list.

        Returns:
            Dictionary with Today's to-dos.
        """
        return await run_script("things/show-today.sh", timeout=15)


class ShowThingsInboxTask(Task):
    """Show the Things3 Inbox."""

    @property
    def name(self) -> str:
        return "show_things_inbox"

    @property
    def description(self) -> str:
        return "Show all to-dos in the Things3 Inbox (unprocessed items)."

    async def execute(self) -> dict[str, Any]:
        """Show Inbox items.

        Returns:
            Dictionary with Inbox to-dos.
        """
        return await run_script("things/show-inbox.sh", timeout=15)


class ListThingsTodosTask(Task):
    """List Things3 to-dos with filters."""

    @property
    def name(self) -> str:
        return "list_things_todos"

    @property
    def description(self) -> str:
        return (
            "List to-dos from Things3 with optional filters by built-in list, project, tag, and status. "
            "Built-in lists: Inbox, Today, Upcoming, Anytime, Someday, Logbook, Trash."
        )

    async def execute(
        self,
        list_name: str | None = None,
        project: str | None = None,
        tag: str | None = None,
        status: str = "open",
        limit: int = 50
    ) -> dict[str, Any]:
        """List to-dos.

        Args:
            list_name: Filter by built-in list (Inbox, Today, Upcoming, Anytime, Someday, Logbook, Trash).
            project: Filter by project name.
            tag: Filter by tag name.
            status: Filter by status: open, completed, canceled (default: open).
            limit: Maximum number of results (default: 50).

        Returns:
            Dictionary with to-do list.
        """
        args = ["--status", status, "--limit", str(limit)]
        if list_name:
            args.extend(["--list", list_name])
        if project:
            args.extend(["--project", project])
        if tag:
            args.extend(["--tag", tag])

        return await run_script("things/list-todos.sh", args, timeout=15)


class SearchThingsTodosTask(Task):
    """Search Things3 to-dos by name or notes."""

    @property
    def name(self) -> str:
        return "search_things_todos"

    @property
    def description(self) -> str:
        return "Search to-dos in Things3 by matching text in the name or notes fields."

    async def execute(
        self,
        query: str,
        status: str = "open",
        include_completed: bool = False,
        limit: int = 20
    ) -> dict[str, Any]:
        """Search to-dos.

        Args:
            query: Search text to match in name or notes.
            status: Filter by status: open, completed, canceled (default: open).
            include_completed: Include completed to-dos in search results.
            limit: Maximum number of results (default: 20).

        Returns:
            Dictionary with matching to-dos.
        """
        args = ["--query", query, "--status", status, "--limit", str(limit)]
        if include_completed:
            args.append("--include-completed")

        return await run_script("things/search-todos.sh", args, timeout=15)


class CreateThingsTodoTask(Task):
    """Create a new Things3 to-do."""

    @property
    def name(self) -> str:
        return "create_things_todo"

    @property
    def description(self) -> str:
        return (
            "Create a new to-do in Things3 with optional notes, due date, tags, project (by name or ID), "
            "and scheduling (today, evening, tomorrow, someday, anytime, or a date). "
            "Prefer project_id over project name for reliable assignment."
        )

    async def execute(
        self,
        name: str,
        notes: str | None = None,
        due: str | None = None,
        tags: str | None = None,
        project: str | None = None,
        project_id: str | None = None,
        list_name: str | None = None,
        schedule: str | None = None,
        heading: str | None = None,
    ) -> dict[str, Any]:
        """Create a to-do.

        Args:
            name: To-do name/title.
            notes: Notes or description.
            due: Due date as "YYYY-MM-DD".
            tags: Comma-separated tag names.
            project: Assign to project by name.
            project_id: Assign to project by ID (more reliable than name).
            list_name: Add to built-in list (Inbox, Today, Anytime, Someday).
            schedule: Schedule: "today", "evening", "tomorrow", "someday", "anytime", or "YYYY-MM-DD".
            heading: Place under a heading within the project.

        Returns:
            Dictionary with creation result.
        """
        args = ["--name", name]
        if notes:
            args.extend(["--notes", notes])
        if due:
            args.extend(["--due", due])
        if tags:
            args.extend(["--tags", tags])
        if project_id:
            args.extend(["--project-id", project_id])
        elif project:
            args.extend(["--project", project])
        if list_name:
            args.extend(["--list", list_name])
        if schedule:
            args.extend(["--schedule", schedule])
        if heading:
            args.extend(["--heading", heading])

        return await run_script("things/create-todo.sh", args, timeout=15)


class CompleteThingsTodoTask(Task):
    """Mark a Things3 to-do as complete."""

    @property
    def name(self) -> str:
        return "complete_things_todo"

    @property
    def description(self) -> str:
        return "Mark one or more Things3 to-dos as complete by name, pattern, or ID."

    async def execute(
        self,
        name: str | None = None,
        pattern: str | None = None,
        id: str | None = None,
        dry_run: bool = False
    ) -> dict[str, Any]:
        """Complete a to-do.

        Args:
            name: Exact to-do name to complete.
            pattern: Complete all to-dos containing this text.
            id: Complete to-do by ID (recommended for precision).
            dry_run: Preview what would be completed without completing.

        Returns:
            Dictionary with completion result.
        """
        if not name and not pattern and not id:
            return {"success": False, "error": "Must specify name, pattern, or id"}

        args = []
        if id:
            args.extend(["--id", id])
        elif name:
            args.extend(["--name", name])
        elif pattern:
            args.extend(["--pattern", pattern])

        if dry_run:
            args.append("--dry-run")

        return await run_script("things/complete-todo.sh", args, timeout=15)


class UpdateThingsTodoTask(Task):
    """Update a Things3 to-do."""

    @property
    def name(self) -> str:
        return "update_things_todo"

    @property
    def description(self) -> str:
        return (
            "Update properties of an existing Things3 to-do. Find by ID (recommended) or name, "
            "then set new name, notes, due date, tags, project (by name or ID), status, or schedule. "
            "Use set_schedule to control when the to-do appears (today, tomorrow, a date, etc.). "
            "Prefer set_project_id over name for reliable project assignment."
        )

    async def execute(
        self,
        id: str | None = None,
        name: str | None = None,
        set_name: str | None = None,
        set_notes: str | None = None,
        set_due: str | None = None,
        clear_due: bool = False,
        set_tags: str | None = None,
        set_project: str | None = None,
        set_project_id: str | None = None,
        set_status: str | None = None,
        set_schedule: str | None = None,
    ) -> dict[str, Any]:
        """Update a to-do.

        Args:
            id: Find to-do by ID (recommended).
            name: Find to-do by exact name.
            set_name: Set new name.
            set_notes: Set new notes.
            set_due: Set due date as "YYYY-MM-DD".
            clear_due: Remove the due date.
            set_tags: Set tags (comma-separated, replaces existing).
            set_project: Move to project by name.
            set_project_id: Move to project by ID (more reliable than name).
            set_status: Set status: completed, canceled, open.
            set_schedule: Set schedule/when date: "today", "evening", "tomorrow", "someday", "anytime", or "YYYY-MM-DD". This controls when the to-do appears in Things (Upcoming/Today). Requires MACBOT_THINGS_AUTH_TOKEN.

        Returns:
            Dictionary with update result.
        """
        if not id and not name:
            return {"success": False, "error": "Must specify id or name"}

        args = []
        if id:
            args.extend(["--id", id])
        if name:
            args.extend(["--name", name])
        if set_name:
            args.extend(["--set-name", set_name])
        if set_notes:
            args.extend(["--set-notes", set_notes])
        if set_due:
            args.extend(["--set-due", set_due])
        if clear_due:
            args.append("--clear-due")
        if set_tags:
            args.extend(["--set-tags", set_tags])
        if set_project_id:
            args.extend(["--set-project-id", set_project_id])
        elif set_project:
            args.extend(["--set-project", set_project])
        if set_status:
            args.extend(["--set-status", set_status])
        if set_schedule:
            args.extend(["--set-schedule", set_schedule])

        return await run_script("things/update-todo.sh", args, timeout=15)


class MoveThingsTodoTask(Task):
    """Move a Things3 to-do to a list or project."""

    @property
    def name(self) -> str:
        return "move_things_todo"

    @property
    def description(self) -> str:
        return (
            "Move a Things3 to-do to a different built-in list (Inbox, Today, Anytime, Someday) "
            "or to a project (by name or ID). Note: 'Upcoming' is NOT a valid list target — "
            "to-dos appear in Upcoming when they have a future schedule date (use update_things_todo "
            "with set_schedule instead). Prefer to_project_id over name for reliable assignment."
        )

    async def execute(
        self,
        id: str | None = None,
        name: str | None = None,
        to_list: str | None = None,
        to_project: str | None = None,
        to_project_id: str | None = None,
    ) -> dict[str, Any]:
        """Move a to-do.

        Args:
            id: Find to-do by ID (recommended).
            name: Find to-do by exact name.
            to_list: Move to built-in list (Inbox, Today, Anytime, Someday).
            to_project: Move to project by name.
            to_project_id: Move to project by ID (more reliable than name).

        Returns:
            Dictionary with move result.
        """
        if not id and not name:
            return {"success": False, "error": "Must specify id or name"}
        if not to_list and not to_project and not to_project_id:
            return {"success": False, "error": "Must specify to_list, to_project, or to_project_id"}

        args = []
        if id:
            args.extend(["--id", id])
        if name:
            args.extend(["--name", name])
        if to_list:
            args.extend(["--to-list", to_list])
        if to_project_id:
            args.extend(["--to-project-id", to_project_id])
        elif to_project:
            args.extend(["--to-project", to_project])

        return await run_script("things/move-todo.sh", args, timeout=15)


class ListThingsProjectsTask(Task):
    """List Things3 projects."""

    @property
    def name(self) -> str:
        return "list_things_projects"

    @property
    def description(self) -> str:
        return "List projects in Things3 with optional status filtering and to-do counts."

    async def execute(
        self,
        status: str = "open",
        with_todos: bool = False,
        limit: int = 50
    ) -> dict[str, Any]:
        """List projects.

        Args:
            status: Filter by status: open, completed, canceled (default: open).
            with_todos: Include open to-do counts for each project.
            limit: Maximum number of projects (default: 50).

        Returns:
            Dictionary with project list.
        """
        args = ["--status", status, "--limit", str(limit)]
        if with_todos:
            args.append("--with-todos")

        return await run_script("things/list-projects.sh", args, timeout=15)


class CreateThingsProjectTask(Task):
    """Create a new Things3 project."""

    @property
    def name(self) -> str:
        return "create_things_project"

    @property
    def description(self) -> str:
        return "Create a new project in Things3 with optional notes, due date, tags, and area."

    async def execute(
        self,
        name: str,
        notes: str | None = None,
        due: str | None = None,
        tags: str | None = None,
        area: str | None = None,
    ) -> dict[str, Any]:
        """Create a project.

        Args:
            name: Project name.
            notes: Project notes/description.
            due: Due date as "YYYY-MM-DD".
            tags: Comma-separated tag names.
            area: Assign to this area.

        Returns:
            Dictionary with creation result.
        """
        args = ["--name", name]
        if notes:
            args.extend(["--notes", notes])
        if due:
            args.extend(["--due", due])
        if tags:
            args.extend(["--tags", tags])
        if area:
            args.extend(["--area", area])

        return await run_script("things/create-project.sh", args, timeout=15)


class UpdateThingsProjectTask(Task):
    """Update a Things3 project."""

    @property
    def name(self) -> str:
        return "update_things_project"

    @property
    def description(self) -> str:
        return (
            "Update properties of an existing Things3 project. Find by ID (recommended) or name, "
            "then set new name, notes, due date, tags, area, or status."
        )

    async def execute(
        self,
        id: str | None = None,
        name: str | None = None,
        set_name: str | None = None,
        set_notes: str | None = None,
        clear_notes: bool = False,
        set_due: str | None = None,
        set_tags: str | None = None,
        set_area: str | None = None,
        set_status: str | None = None,
    ) -> dict[str, Any]:
        """Update a project.

        Args:
            id: Find project by ID (recommended).
            name: Find project by exact name.
            set_name: Set new name.
            set_notes: Set new notes.
            clear_notes: Clear notes.
            set_due: Set due date as "YYYY-MM-DD".
            set_tags: Set tags (comma-separated, replaces existing).
            set_area: Move to this area.
            set_status: Set status: completed, canceled, open.

        Returns:
            Dictionary with update result.
        """
        if not id and not name:
            return {"success": False, "error": "Must specify id or name"}

        args = []
        if id:
            args.extend(["--id", id])
        if name:
            args.extend(["--name", name])
        if set_name:
            args.extend(["--set-name", set_name])
        if set_notes:
            args.extend(["--set-notes", set_notes])
        if clear_notes:
            args.append("--clear-notes")
        if set_due:
            args.extend(["--set-due", set_due])
        if set_tags:
            args.extend(["--set-tags", set_tags])
        if set_area:
            args.extend(["--set-area", set_area])
        if set_status:
            args.extend(["--set-status", set_status])

        return await run_script("things/update-project.sh", args, timeout=15)


class ListThingsTagsTask(Task):
    """List all Things3 tags."""

    @property
    def name(self) -> str:
        return "list_things_tags"

    @property
    def description(self) -> str:
        return "List all tags defined in Things3, optionally with open to-do counts."

    async def execute(
        self,
        with_counts: bool = False,
        limit: int = 100
    ) -> dict[str, Any]:
        """List tags.

        Args:
            with_counts: Show number of open to-dos per tag.
            limit: Maximum number of tags (default: 100).

        Returns:
            Dictionary with tag list.
        """
        args = ["--limit", str(limit)]
        if with_counts:
            args.append("--with-counts")

        return await run_script("things/list-tags.sh", args, timeout=15)


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
    registry.register(ReadNoteTask())
    registry.register(ListNotesTask())
    registry.register(ListNoteFoldersTask())
    registry.register(CreateNoteFolderTask())
    registry.register(DeleteNoteFolderTask())
    registry.register(RenameNoteFolderTask())
    registry.register(MoveNoteTask())
    registry.register(DeleteNoteTask())

    # Safari tasks
    registry.register(GetCurrentPageTask())
    registry.register(OpenUrlTask())
    registry.register(ExtractLinksTask())
    registry.register(ListSafariTabsTask())

    # Spotlight tasks
    registry.register(SpotlightSearchTask())

    # Finder tasks
    registry.register(ListDirectoryTask())

    # Shortcuts tasks
    registry.register(ListShortcutsTask())
    registry.register(RunShortcutTask())

    # Web tasks
    registry.register(GetHackerNewsTask())
    registry.register(GoogleSearchTask())

    # Contacts tasks
    registry.register(SearchContactsTask())
    registry.register(GetContactTask())
    registry.register(CreateContactTask())
    registry.register(ListContactGroupsTask())

    # Messages tasks
    registry.register(SendMessageTask())
    registry.register(ListChatsTask())
    registry.register(SearchMessagesTask())

    # System tasks
    registry.register(GetSystemStatusTask())
    registry.register(ToggleWifiTask())
    registry.register(ToggleBluetoothTask())
    registry.register(ListBluetoothDevicesTask())
    registry.register(SetVolumeTask())
    registry.register(ToggleDarkModeTask())
    registry.register(ToggleDndTask())

    # Things3 tasks
    registry.register(ShowThingsTodayTask())
    registry.register(ShowThingsInboxTask())
    registry.register(ListThingsTodosTask())
    registry.register(SearchThingsTodosTask())
    registry.register(CreateThingsTodoTask())
    registry.register(CompleteThingsTodoTask())
    registry.register(UpdateThingsTodoTask())
    registry.register(MoveThingsTodoTask())
    registry.register(ListThingsProjectsTask())
    registry.register(CreateThingsProjectTask())
    registry.register(UpdateThingsProjectTask())
    registry.register(ListThingsTagsTask())
