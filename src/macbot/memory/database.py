"""SQLite database for agent memory.

Tracks what the agent has done across sessions - processed emails,
created reminders, and other actions.
"""

import json
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

                -- Track file write operations
                CREATE TABLE IF NOT EXISTS files_written (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    summary TEXT,
                    written_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_files_written_at ON files_written(written_at);
                CREATE INDEX IF NOT EXISTS idx_files_filename ON files_written(filename);

                -- Episodic log of agent turns (auto-captured). The nightly
                -- maintenance job distills un-consolidated rows into knowledge
                -- memory, then marks them consolidated.
                CREATE TABLE IF NOT EXISTS turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT DEFAULT CURRENT_TIMESTAMP,
                    goal TEXT,
                    domain TEXT,
                    tools_used TEXT,        -- JSON array of tool names
                    outcome TEXT,           -- 'success' | 'error' | 'partial'
                    summary TEXT,
                    model TEXT,
                    tokens INTEGER DEFAULT 0,
                    consolidated INTEGER DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_turns_ts ON turns(ts);
                CREATE INDEX IF NOT EXISTS idx_turns_consolidated ON turns(consolidated);
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
    # File write tracking
    # =========================================================================

    def record_file_written(
        self,
        path: str,
        summary: str = "",
    ) -> int:
        """Record that a file was written.

        Args:
            path: Full path to the file
            summary: Brief description of the file/content purpose

        Returns:
            ID of the created record
        """
        import os
        filename = os.path.basename(path)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """INSERT INTO files_written (path, filename, summary)
                   VALUES (?, ?, ?)""",
                (path, filename, summary)
            )
            return cursor.lastrowid or 0

    def search_files_written(
        self,
        query: str | None = None,
        days: int | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search for files that were written.

        Args:
            query: Search in filename and summary (optional)
            days: Only show files from last N days
            limit: Maximum number of results

        Returns:
            List of file records
        """
        sql = "SELECT * FROM files_written WHERE 1=1"
        params: list[Any] = []

        if query:
            sql += " AND (filename LIKE ? OR summary LIKE ?)"
            pattern = f"%{query}%"
            params.extend([pattern, pattern])

        if days:
            sql += " AND written_at >= datetime('now', ?)"
            params.append(f"-{days} days")

        sql += " ORDER BY written_at DESC LIMIT ?"
        params.append(limit)

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_recent_files(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get recently written files.

        Args:
            limit: Maximum number of results

        Returns:
            List of recent file records
        """
        return self.search_files_written(limit=limit)

    # =========================================================================
    # Turn log (episodic capture)
    # =========================================================================

    def record_turn(
        self,
        goal: str,
        domain: str = "general",
        tools_used: list[str] | None = None,
        outcome: str = "success",
        summary: str = "",
        model: str = "",
        tokens: int = 0,
    ) -> int:
        """Record a single agent turn for later consolidation.

        Args:
            goal: The user goal/message that started the turn.
            domain: Coarse domain tag (see memory.tagging).
            tools_used: Tool names invoked during the turn.
            outcome: 'success', 'error', or 'partial'.
            summary: Short summary of the result (truncated final response).
            model: Model that handled the turn.
            tokens: Total tokens (input + output) spent on the turn.

        Returns:
            ID of the created record.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """INSERT INTO turns
                   (goal, domain, tools_used, outcome, summary, model, tokens)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    goal,
                    domain,
                    json.dumps(tools_used or []),
                    outcome,
                    summary,
                    model,
                    tokens,
                ),
            )
            return cursor.lastrowid or 0

    def get_unconsolidated_turns(self, limit: int = 200) -> list[dict[str, Any]]:
        """Get turns not yet folded into knowledge memory (oldest first).

        Args:
            limit: Maximum number of rows to return.

        Returns:
            List of turn records with ``tools_used`` decoded to a list.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """SELECT * FROM turns WHERE consolidated = 0
                   ORDER BY ts ASC LIMIT ?""",
                (limit,),
            )
            return [self._decode_turn(row) for row in cursor.fetchall()]

    def get_recent_turns(
        self, limit: int = 20, days: int | None = None
    ) -> list[dict[str, Any]]:
        """Get the most recent turns (newest first), for inspection/CLI."""
        query = "SELECT * FROM turns WHERE 1=1"
        params: list[Any] = []
        if days:
            query += " AND ts >= datetime('now', ?)"
            params.append(f"-{days} days")
        query += " ORDER BY ts DESC LIMIT ?"
        params.append(limit)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, params)
            return [self._decode_turn(row) for row in cursor.fetchall()]

    def mark_turns_consolidated(self, turn_ids: list[int]) -> int:
        """Mark turns as consolidated so they aren't distilled again.

        Args:
            turn_ids: IDs of turns to mark.

        Returns:
            Number of rows updated.
        """
        if not turn_ids:
            return 0
        placeholders = ",".join("?" * len(turn_ids))
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                f"UPDATE turns SET consolidated = 1 WHERE id IN ({placeholders})",
                turn_ids,
            )
            return cursor.rowcount

    @staticmethod
    def _decode_turn(row: sqlite3.Row) -> dict[str, Any]:
        """Convert a turns row to a dict, decoding the tools_used JSON."""
        rec = dict(row)
        try:
            rec["tools_used"] = json.loads(rec.get("tools_used") or "[]")
        except (json.JSONDecodeError, TypeError):
            rec["tools_used"] = []
        return rec

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

            # Only prune turns already folded into knowledge memory, so an
            # un-run maintenance job never silently loses raw turns.
            cursor = conn.execute(
                """DELETE FROM turns
                   WHERE consolidated = 1 AND ts < datetime('now', ?)""",
                (f"-{days} days",)
            )
            turns_deleted = cursor.rowcount

            return emails_deleted + reminders_deleted + turns_deleted

    def clear_recent_records(self, hours: int = 0, minutes: int = 0) -> dict[str, int]:
        """Clear records newer than specified time ago.

        Use this to "undo" recent processing and allow re-processing of emails.

        Args:
            hours: Delete records from the last N hours
            minutes: Additional minutes to add

        Returns:
            Dictionary with counts of deleted records by type
        """
        # Convert to minutes for SQLite
        total_minutes = hours * 60 + minutes
        if total_minutes <= 0:
            return {"emails_deleted": 0, "reminders_deleted": 0}

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """DELETE FROM emails_processed
                   WHERE processed_at >= datetime('now', ?)""",
                (f"-{total_minutes} minutes",)
            )
            emails_deleted = cursor.rowcount

            cursor = conn.execute(
                """DELETE FROM reminders_created
                   WHERE created_at >= datetime('now', ?)""",
                (f"-{total_minutes} minutes",)
            )
            reminders_deleted = cursor.rowcount

            return {
                "emails_deleted": emails_deleted,
                "reminders_deleted": reminders_deleted,
                "total": emails_deleted + reminders_deleted,
            }
