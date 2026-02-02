"""SQLite database for agent memory.

Tracks what the agent has done across sessions - processed emails,
created reminders, and other actions.
"""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


class AgentMemory:
    """Persistent memory store for the agent."""

    def __init__(self, db_path: Path | str | None = None):
        """Initialize the memory database.

        Args:
            db_path: Path to SQLite database file. Defaults to ~/.macbot/memory.db
        """
        if db_path is None:
            db_path = Path.home() / ".macbot" / "memory.db"

        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                -- Track processed emails
                CREATE TABLE IF NOT EXISTS emails_processed (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id TEXT UNIQUE,
                    subject TEXT,
                    sender TEXT,
                    account TEXT,
                    received_date TEXT,
                    processed_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    action_taken TEXT,
                    notes TEXT
                );

                -- Track created reminders
                CREATE TABLE IF NOT EXISTS reminders_created (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT,
                    list_name TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    source_email_id TEXT,
                    due_date TEXT,
                    notes TEXT,
                    FOREIGN KEY (source_email_id) REFERENCES emails_processed(message_id)
                );

                -- Index for faster lookups
                CREATE INDEX IF NOT EXISTS idx_emails_message_id ON emails_processed(message_id);
                CREATE INDEX IF NOT EXISTS idx_emails_processed_at ON emails_processed(processed_at);
                CREATE INDEX IF NOT EXISTS idx_reminders_source ON reminders_created(source_email_id);
            """)

    # =========================================================================
    # Email tracking
    # =========================================================================

    def is_email_processed(self, message_id: str) -> bool:
        """Check if an email has been processed.

        Args:
            message_id: The RFC Message-ID of the email

        Returns:
            True if the email has been processed before
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT 1 FROM emails_processed WHERE message_id = ?",
                (message_id,)
            )
            return cursor.fetchone() is not None

    def mark_email_processed(
        self,
        message_id: str,
        subject: str,
        sender: str,
        account: str = "",
        received_date: str = "",
        action_taken: str = "",
        notes: str = ""
    ) -> bool:
        """Mark an email as processed.

        Args:
            message_id: The RFC Message-ID of the email
            subject: Email subject
            sender: Sender email/name
            account: Mail account name
            received_date: When the email was received
            action_taken: What action was taken (e.g., 'replied', 'reminder_created')
            notes: Additional notes about the processing

        Returns:
            True if newly marked, False if already existed
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """INSERT INTO emails_processed
                       (message_id, subject, sender, account, received_date, action_taken, notes)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (message_id, subject, sender, account, received_date, action_taken, notes)
                )
                return True
        except sqlite3.IntegrityError:
            # Already exists - update the action/notes
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """UPDATE emails_processed
                       SET action_taken = ?, notes = ?, processed_at = CURRENT_TIMESTAMP
                       WHERE message_id = ?""",
                    (action_taken, notes, message_id)
                )
                return False

    def get_processed_emails(
        self,
        limit: int = 20,
        days: int | None = None,
        account: str | None = None
    ) -> list[dict[str, Any]]:
        """Get list of processed emails.

        Args:
            limit: Maximum number of results
            days: Only show emails processed in last N days
            account: Filter by account name

        Returns:
            List of processed email records
        """
        query = "SELECT * FROM emails_processed WHERE 1=1"
        params: list[Any] = []

        if days:
            query += " AND processed_at >= datetime('now', ?)"
            params.append(f"-{days} days")

        if account:
            query += " AND account = ?"
            params.append(account)

        query += " ORDER BY processed_at DESC LIMIT ?"
        params.append(limit)

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_unprocessed_filter(self, message_ids: list[str]) -> list[str]:
        """Filter a list of message IDs to only those not yet processed.

        Args:
            message_ids: List of message IDs to check

        Returns:
            List of message IDs that haven't been processed
        """
        if not message_ids:
            return []

        placeholders = ",".join("?" * len(message_ids))
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                f"SELECT message_id FROM emails_processed WHERE message_id IN ({placeholders})",
                message_ids
            )
            processed = {row[0] for row in cursor.fetchall()}
            return [mid for mid in message_ids if mid not in processed]

    # =========================================================================
    # Reminder tracking
    # =========================================================================

    def record_reminder_created(
        self,
        title: str,
        list_name: str = "Reminders",
        source_email_id: str | None = None,
        due_date: str | None = None,
        notes: str = ""
    ) -> int:
        """Record that a reminder was created.

        Args:
            title: Reminder title
            list_name: Reminders list name
            source_email_id: Message-ID of email that triggered this reminder
            due_date: Due date if set
            notes: Additional notes

        Returns:
            ID of the created record
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """INSERT INTO reminders_created
                   (title, list_name, source_email_id, due_date, notes)
                   VALUES (?, ?, ?, ?, ?)""",
                (title, list_name, source_email_id, due_date, notes)
            )
            return cursor.lastrowid or 0

    def get_created_reminders(
        self,
        limit: int = 20,
        days: int | None = None
    ) -> list[dict[str, Any]]:
        """Get list of reminders created by the agent.

        Args:
            limit: Maximum number of results
            days: Only show reminders created in last N days

        Returns:
            List of reminder records
        """
        query = "SELECT * FROM reminders_created WHERE 1=1"
        params: list[Any] = []

        if days:
            query += " AND created_at >= datetime('now', ?)"
            params.append(f"-{days} days")

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    # =========================================================================
    # Summary / Stats
    # =========================================================================

    def get_summary(self, days: int = 7) -> dict[str, Any]:
        """Get a summary of agent activity.

        Args:
            days: Number of days to summarize

        Returns:
            Summary statistics
        """
        with sqlite3.connect(self.db_path) as conn:
            # Count processed emails
            cursor = conn.execute(
                """SELECT COUNT(*) FROM emails_processed
                   WHERE processed_at >= datetime('now', ?)""",
                (f"-{days} days",)
            )
            emails_count = cursor.fetchone()[0]

            # Count created reminders
            cursor = conn.execute(
                """SELECT COUNT(*) FROM reminders_created
                   WHERE created_at >= datetime('now', ?)""",
                (f"-{days} days",)
            )
            reminders_count = cursor.fetchone()[0]

            # Get action breakdown
            cursor = conn.execute(
                """SELECT action_taken, COUNT(*) FROM emails_processed
                   WHERE processed_at >= datetime('now', ?)
                   GROUP BY action_taken""",
                (f"-{days} days",)
            )
            actions = {row[0] or "reviewed": row[1] for row in cursor.fetchall()}

            return {
                "period_days": days,
                "emails_processed": emails_count,
                "reminders_created": reminders_count,
                "actions_breakdown": actions,
            }

    def clear_old_records(self, days: int = 90) -> int:
        """Clear records older than specified days.

        Args:
            days: Delete records older than this many days

        Returns:
            Number of records deleted
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """DELETE FROM emails_processed
                   WHERE processed_at < datetime('now', ?)""",
                (f"-{days} days",)
            )
            emails_deleted = cursor.rowcount

            cursor = conn.execute(
                """DELETE FROM reminders_created
                   WHERE created_at < datetime('now', ?)""",
                (f"-{days} days",)
            )
            reminders_deleted = cursor.rowcount

            return emails_deleted + reminders_deleted
