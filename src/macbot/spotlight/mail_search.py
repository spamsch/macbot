"""
Mail search using Core Spotlight index.

Reads Apple Mail messages from the Core Spotlight store.db, maintains a
local SQLite cache for fast repeated queries, and watches for changes.

Usage as CLI:
    python -m macbot.spotlight.mail_search --subject "invoice" --limit 10
    python -m macbot.spotlight.mail_search --sender "john@example.com" --days 7
    python -m macbot.spotlight.mail_search --rebuild

Usage as library:
    from macbot.spotlight.mail_search import MailSearchIndex
    index = MailSearchIndex()
    index.ensure_fresh()
    results = index.search(subject="invoice", limit=10)
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

from macbot.spotlight.parser import SpotlightStoreReader, epoch_us_to_datetime

log = logging.getLogger(__name__)

# Core Spotlight store locations (per-user, macOS)
_CS_BASE = Path.home() / "Library" / "Metadata" / "CoreSpotlight"
_CS_STORES = [
    _CS_BASE / "NSFileProtectionCompleteUntilFirstUserAuthentication" / "index.spotlightV3",
    _CS_BASE / "Priority" / "index.spotlightV3",
]

# Our cache
_CACHE_DIR = Path.home() / ".macbot" / "spotlight"
_CACHE_DB = _CACHE_DIR / "mail_index.db"

# Mail fields we extract from spotlight items
_MAIL_ENTITY_TYPE = "MailMessageEntity"


def _find_store_db() -> Path | None:
    """Find the most relevant store.db (the one with mail data)."""
    for store_dir in _CS_STORES:
        store_db = store_dir / "store.db"
        if store_db.exists():
            return store_db
    return None


def _derive_emlx_path(
    account_id: str | None,
    mailboxes: str | None,
    msg_id: int | None,
    attachment_paths: str | None,
    date_received: str | None = None,
    subject: str | None = None,
) -> str | None:
    """Try to derive the .emlx file path from spotlight metadata.

    The Spotlight mail_message_id is the Envelope Index ROWID, but for
    multi-account setups the same email may have different ROWIDs in
    different accounts/mailboxes. We first try a direct ROWID lookup,
    then fall back to querying the Envelope Index by date+subject+account
    to find the correct ROWID for the on-disk .emlx file.
    """
    if attachment_paths:
        match = re.search(r'(.+?/Data/)Attachments/', attachment_paths)
        if match and msg_id is not None:
            base = match.group(1)
            for suffix in [f"Messages/{msg_id}.emlx", f"Messages/{msg_id}.partial.emlx"]:
                path = base + suffix
                if os.path.exists(path):
                    return path

    mail_base = None
    if account_id:
        mail_base = Path.home() / "Library" / "Mail" / "V10" / account_id

    # Direct lookup by Spotlight msg_id (= Envelope Index ROWID)
    if mail_base and mail_base.exists() and msg_id is not None:
        for suffix in [f"{msg_id}.emlx", f"{msg_id}.partial.emlx"]:
            for mbox in mail_base.rglob(suffix):
                return str(mbox)

    # Fallback: query Envelope Index for the correct ROWID in this account.
    # Spotlight may have indexed a copy from a different account, so the
    # msg_id doesn't match the .emlx filename in this account's directory.
    if mail_base and mail_base.exists() and date_received:
        rowids = _find_rowids_from_envelope_index(account_id, date_received, subject)
        for rowid in rowids:
            for suffix in [f"{rowid}.emlx", f"{rowid}.partial.emlx"]:
                for mbox in mail_base.rglob(suffix):
                    return str(mbox)

    return None


def _find_rowids_from_envelope_index(
    account_id: str | None, date_received: str, subject: str | None = None,
) -> list[int]:
    """Query the Envelope Index for ROWIDs matching an account + date.

    The Envelope Index uses a separate subjects table with integer IDs.
    We match by date window and then optionally filter by subject text.
    """
    envelope_idx = Path.home() / "Library" / "Mail" / "V10" / "MailData" / "Envelope Index"
    if not envelope_idx.exists():
        return []
    try:
        dt = datetime.datetime.fromisoformat(date_received)
        # Envelope Index stores date_sent as Unix epoch.
        # Spotlight date_received can differ from Envelope date_sent by up to
        # ~2 hours due to timezone handling and send/receive delay.
        epoch = int(dt.timestamp())
        conn = sqlite3.connect(f"file:{envelope_idx}?mode=ro&immutable=1", uri=True)

        # If we have a subject, find the subject ID first for precise matching
        subject_ids: list[int] = []
        if subject:
            # subjects table: ROWID, subject, normalized_subject
            clean_subject = subject.removeprefix("Re: ").removeprefix("Fwd: ").removeprefix("AW: ").removeprefix("WG: ")
            srows = conn.execute(
                "SELECT ROWID FROM subjects WHERE subject LIKE ?",
                (f"%{clean_subject}%",),
            ).fetchall()
            subject_ids = [r[0] for r in srows]

        if account_id:
            rows = conn.execute(
                "SELECT ROWID FROM mailboxes WHERE url LIKE ?",
                (f"%{account_id}%",),
            ).fetchall()
            mbox_ids = [r[0] for r in rows]
            if not mbox_ids:
                conn.close()
                return []
            placeholders = ','.join('?' * len(mbox_ids))
            if subject_ids:
                subj_placeholders = ','.join('?' * len(subject_ids))
                results = conn.execute(
                    f"SELECT ROWID FROM messages WHERE mailbox IN ({placeholders}) "
                    f"AND subject IN ({subj_placeholders}) "
                    "AND date_sent BETWEEN ? AND ? ORDER BY ROWID DESC",
                    [*mbox_ids, *subject_ids, epoch - 7200, epoch + 7200],
                ).fetchall()
            else:
                results = conn.execute(
                    f"SELECT ROWID FROM messages WHERE mailbox IN ({placeholders}) "
                    "AND date_sent BETWEEN ? AND ? ORDER BY ROWID DESC",
                    [*mbox_ids, epoch - 7200, epoch + 7200],
                ).fetchall()
        else:
            results = conn.execute(
                "SELECT ROWID FROM messages WHERE date_sent BETWEEN ? AND ? ORDER BY ROWID DESC",
                (epoch - 7200, epoch + 7200),
            ).fetchall()
        conn.close()
        return [r[0] for r in results]
    except Exception:
        log.debug("Envelope Index lookup failed", exc_info=True)
        return []


def _extract_rfc_message_id(emlx_path: str) -> str | None:
    """Extract RFC Message-ID from an .emlx file (read only headers)."""
    try:
        with open(emlx_path, 'r', errors='replace') as f:
            # First line is byte count, skip it
            f.readline()
            for line in f:
                if line.strip() == '':
                    break  # End of headers
                if line.lower().startswith('message-id:'):
                    mid = line.split(':', 1)[1].strip()
                    return mid
    except OSError:
        pass
    return None


def _extract_emlx_body(emlx_path: str, with_links: bool = False) -> str | None:
    """Extract plain-text body from an .emlx file."""
    try:
        with open(emlx_path, 'rb') as f:
            # First line is the byte count of the RFC822 message
            size_line = f.readline()
            try:
                msg_size = int(size_line.strip())
            except ValueError:
                return None
            raw = f.read(msg_size)

        import email
        import email.policy
        msg = email.message_from_bytes(raw, policy=email.policy.default)

        # Extract plain text body
        body = msg.get_body(preferencelist=('plain',))
        if body:
            text = body.get_content()
            if with_links:
                # Also extract links from HTML part
                html_body = msg.get_body(preferencelist=('html',))
                if html_body:
                    html = html_body.get_content()
                    links = re.findall(r'href=["\']([^"\']+)["\']', html)
                    if links:
                        text += "\n\n--- Links ---\n" + "\n".join(links)
            return text

        # Fall back to HTML → strip tags
        html_body = msg.get_body(preferencelist=('html',))
        if html_body:
            html = html_body.get_content()
            links = []
            if with_links:
                links = re.findall(r'href=["\']([^"\']+)["\']', html)
            # Simple tag stripping
            text = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'\s+', ' ', text).strip()
            if with_links and links:
                text += "\n\n--- Links ---\n" + "\n".join(links)
            return text

    except Exception:
        log.debug("Failed to extract body from %s", emlx_path, exc_info=True)
    return None


def _fetch_content_via_applescript(
    subject: str,
    account_id: str | None = None,
) -> str | None:
    """Fetch email content via AppleScript when .emlx is not available on disk.

    Uses subject + account to find the message via whose clause (fast).
    """
    import subprocess
    escaped_subject = subject.replace('\\', '\\\\').replace('"', '\\"')

    if account_id:
        script = f'''
            tell application "Mail"
                repeat with mb in mailboxes of account id "{account_id}"
                    set msgs to (messages of mb whose subject is "{escaped_subject}")
                    if (count of msgs) > 0 then
                        return content of item 1 of msgs
                    end if
                end repeat
            end tell
        '''
    else:
        script = f'''
            tell application "Mail"
                repeat with acct in every account
                    repeat with mb in mailboxes of acct
                        set msgs to (messages of mb whose subject is "{escaped_subject}")
                        if (count of msgs) > 0 then
                            return content of item 1 of msgs
                        end if
                    end repeat
                end repeat
            end tell
        '''
    try:
        result = subprocess.run(
            ['osascript', '-e', script],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        log.debug("AppleScript content fetch failed for '%s'", subject, exc_info=True)
    return None


def _make_message_url(rfc_message_id: str) -> str:
    """Create a message:// URL from an RFC Message-ID."""
    mid = rfc_message_id.strip('<>').strip()
    return f"message://%3c{mid}%3e"


class MailSearchIndex:
    """SQLite-backed index of mail messages from Core Spotlight."""

    def __init__(self, cache_path: Path | None = None):
        self._cache_path = cache_path or _CACHE_DB
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._store_mtime: float = 0

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self._cache_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._create_tables()
        return self._conn

    def _create_tables(self) -> None:
        conn = self._conn
        assert conn is not None
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS messages (
                spotlight_id INTEGER PRIMARY KEY,
                subject TEXT,
                sender TEXT,
                sender_name TEXT,
                recipients TEXT,
                cc_recipients TEXT,
                snippet TEXT,
                date_received TEXT,
                account TEXT,
                account_type TEXT,
                mailboxes TEXT,
                is_read INTEGER DEFAULT 0,
                is_flagged INTEGER DEFAULT 0,
                is_junk INTEGER DEFAULT 0,
                has_attachments INTEGER DEFAULT 0,
                attachment_names TEXT,
                mail_message_id INTEGER,
                conversation_id INTEGER,
                account_id TEXT,
                attachment_paths TEXT,
                emlx_path TEXT,
                rfc_message_id TEXT,
                message_url TEXT,
                storage_size INTEGER DEFAULT 0,
                content_length INTEGER DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_subject ON messages(subject);
            CREATE INDEX IF NOT EXISTS idx_sender ON messages(sender);
            CREATE INDEX IF NOT EXISTS idx_date ON messages(date_received);
            CREATE INDEX IF NOT EXISTS idx_account ON messages(account);
            CREATE INDEX IF NOT EXISTS idx_mail_msg_id ON messages(mail_message_id);
            CREATE INDEX IF NOT EXISTS idx_read ON messages(is_read);
            CREATE INDEX IF NOT EXISTS idx_flagged ON messages(is_flagged);

            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                subject, sender, sender_name, snippet, recipients, attachment_names,
                content='messages',
                content_rowid='spotlight_id'
            );

            -- Triggers to keep FTS in sync
            CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
                INSERT INTO messages_fts(rowid, subject, sender, sender_name, snippet, recipients, attachment_names)
                VALUES (new.spotlight_id, new.subject, new.sender, new.sender_name, new.snippet, new.recipients, new.attachment_names);
            END;
            CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
                INSERT INTO messages_fts(messages_fts, rowid, subject, sender, sender_name, snippet, recipients, attachment_names)
                VALUES ('delete', old.spotlight_id, old.subject, old.sender, old.sender_name, old.snippet, old.recipients, old.attachment_names);
            END;
            CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
                INSERT INTO messages_fts(messages_fts, rowid, subject, sender, sender_name, snippet, recipients, attachment_names)
                VALUES ('delete', old.spotlight_id, old.subject, old.sender, old.sender_name, old.snippet, old.recipients, old.attachment_names);
                INSERT INTO messages_fts(rowid, subject, sender, sender_name, snippet, recipients, attachment_names)
                VALUES (new.spotlight_id, new.subject, new.sender, new.sender_name, new.snippet, new.recipients, new.attachment_names);
            END;
        """)
        conn.commit()

    def _get_meta(self, key: str) -> str | None:
        row = self._get_conn().execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def _set_meta(self, key: str, value: str) -> None:
        self._get_conn().execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
            (key, value)
        )
        self._get_conn().commit()

    def _store_mtime_current(self) -> float:
        store_db = _find_store_db()
        if store_db is None:
            return 0
        return store_db.stat().st_mtime

    def needs_rebuild(self) -> bool:
        """Check if our cache is stale compared to the spotlight store."""
        store_db = _find_store_db()
        if store_db is None:
            return False

        last_built = self._get_meta("last_store_mtime")
        if last_built is None:
            return True

        current_mtime = store_db.stat().st_mtime
        return current_mtime > float(last_built)

    def message_count(self) -> int:
        return self._get_conn().execute("SELECT COUNT(*) FROM messages").fetchone()[0]

    def rebuild(self, progress_callback: Any = None) -> int:
        """Full rebuild of the cache from Core Spotlight store.db."""
        store_db = _find_store_db()
        if store_db is None:
            raise FileNotFoundError("No Core Spotlight store.db found")

        store_mtime = store_db.stat().st_mtime
        conn = self._get_conn()

        # Clear existing data
        conn.execute("DELETE FROM messages")
        conn.execute("DELETE FROM messages_fts")
        conn.commit()

        count = 0
        batch: list[tuple] = []
        batch_size = 500

        with SpotlightStoreReader(store_db) as reader:
            for item in reader.iter_items():
                entity_type = item.props.get('_kMDItemAppEntityTypeIdentifier')
                if entity_type != _MAIL_ENTITY_TYPE:
                    continue

                row = self._item_to_row(item)
                batch.append(row)
                count += 1

                if len(batch) >= batch_size:
                    self._insert_batch(conn, batch)
                    batch.clear()
                    if progress_callback:
                        progress_callback(count)

            if batch:
                self._insert_batch(conn, batch)

        self._set_meta("last_store_mtime", str(store_mtime))
        self._set_meta("last_rebuild", datetime.datetime.now().isoformat())
        self._set_meta("message_count", str(count))
        conn.commit()

        log.info("Indexed %d mail messages", count)
        return count

    def _item_to_row(self, item: Any) -> tuple:
        p = item.props
        subject = p.get('kMDItemSubject', p.get('kMDItemAppEntityTitle', ''))
        sender = p.get('kMDItemAuthorEmailAddresses', '')
        sender_name = p.get('kMDItemAuthors', '')
        recipients = p.get('kMDItemPrimaryRecipientEmailAddresses', '')
        cc = p.get('kMDItemAdditionalRecipientEmailAddresses', '')
        snippet = p.get('_kMDItemSnippet', '')
        account = p.get('kMDItemAccountHandles', '')
        account_type = p.get('kMDItemAccountType', '')
        account_id = p.get('kMDItemAccountIdentifier', '')
        mailboxes = p.get('kMDItemMailboxes', '')
        attachment_names = p.get('kMDItemAttachmentNames', '')
        attachment_paths = p.get('kMDItemAttachmentPaths', '')
        mail_msg_id = p.get('com_apple_mail_messageID')
        conversation_id = p.get('kMDItemEmailConversationID')

        # Date
        date_received = p.get('com_apple_mail_dateReceived')
        if isinstance(date_received, datetime.datetime):
            date_received = date_received.isoformat()
        elif date_received is None:
            cd = p.get('kMDItemContentCreationDate')
            if isinstance(cd, datetime.datetime):
                date_received = cd.isoformat()

        # Stringify lists
        if isinstance(sender, list):
            sender = ', '.join(str(s) for s in sender)
        if isinstance(sender_name, list):
            sender_name = ', '.join(str(s) for s in sender_name)
        if isinstance(recipients, list):
            recipients = ', '.join(str(s) for s in recipients)
        if isinstance(cc, list):
            cc = ', '.join(str(s) for s in cc)
        if isinstance(attachment_names, list):
            attachment_names = ', '.join(str(s) for s in attachment_names)
        if isinstance(attachment_paths, list):
            attachment_paths = ', '.join(str(s) for s in attachment_paths)
        if isinstance(mailboxes, list):
            mailboxes = ', '.join(str(s) for s in mailboxes)

        is_read = p.get('com_apple_mail_read', 0)
        is_flagged = p.get('com_apple_mail_flagged', 0)
        is_junk = p.get('kMDItemIsLikelyJunk', 0)
        has_attachments = 1 if attachment_names else 0
        storage_size = p.get('_kMDItemStorageSize', 0)
        content_length = p.get('_kMDItemTextContentLength', 0)

        return (
            item.id,                    # spotlight_id
            str(subject) if subject else '',
            str(sender) if sender else '',
            str(sender_name) if sender_name else '',
            str(recipients) if recipients else '',
            str(cc) if cc else '',
            str(snippet) if snippet else '',
            str(date_received) if date_received else '',
            str(account) if account else '',
            str(account_type) if account_type else '',
            str(mailboxes) if mailboxes else '',
            int(is_read) if is_read else 0,
            int(is_flagged) if is_flagged else 0,
            int(is_junk) if is_junk else 0,
            has_attachments,
            str(attachment_names) if attachment_names else '',
            int(mail_msg_id) if mail_msg_id is not None else None,
            int(conversation_id) if conversation_id is not None else None,
            str(account_id) if account_id else '',
            str(attachment_paths) if attachment_paths else '',
            None,  # emlx_path — resolved lazily
            None,  # rfc_message_id — resolved lazily
            None,  # message_url — resolved lazily
            int(storage_size) if storage_size else 0,
            int(content_length) if content_length else 0,
        )

    def _insert_batch(self, conn: sqlite3.Connection, batch: list[tuple]) -> None:
        conn.executemany("""
            INSERT OR REPLACE INTO messages (
                spotlight_id, subject, sender, sender_name, recipients,
                cc_recipients, snippet, date_received, account, account_type,
                mailboxes, is_read, is_flagged, is_junk, has_attachments,
                attachment_names, mail_message_id, conversation_id,
                account_id, attachment_paths,
                emlx_path, rfc_message_id, message_url,
                storage_size, content_length
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, batch)

    def ensure_fresh(self, max_age_seconds: float = 60.0) -> bool:
        """Rebuild if cache is stale. Returns True if rebuilt."""
        if not self._cache_path.exists() or self.message_count() == 0:
            self.rebuild()
            return True
        if self.needs_rebuild():
            self.rebuild()
            return True
        return False

    def search(
        self,
        query: str | None = None,
        sender: str | None = None,
        recipient: str | None = None,
        subject: str | None = None,
        message_id: int | None = None,
        account: str | None = None,
        mailbox: str | None = None,
        days: int | None = None,
        today_only: bool = False,
        unread_only: bool = False,
        flagged_only: bool = False,
        has_attachments: bool = False,
        limit: int = 20,
        resolve_urls: bool = False,
        with_content: bool = False,
        with_links: bool = False,
    ) -> list[dict[str, Any]]:
        """Search the mail index.

        Args:
            query: Full-text search across subject, sender, snippet.
            sender: Filter by sender email (substring match).
            recipient: Filter by recipient email/name (searches To and CC).
            subject: Filter by subject (substring match).
            message_id: Lookup by Mail.app internal message ID.
            account: Filter by account email.
            mailbox: Filter by mailbox name.
            days: Only last N days.
            today_only: Only today.
            unread_only: Only unread messages.
            flagged_only: Only flagged messages.
            has_attachments: Only messages with attachments.
            limit: Max results.
            resolve_urls: Resolve message:// URLs (slower, reads .emlx files).
            with_content: Include full email body from .emlx file.
            with_links: Also extract hyperlinks from HTML email (requires with_content).
        """
        conn = self._get_conn()
        conditions: list[str] = []
        params: list[Any] = []

        # FTS query
        if query:
            conditions.append("spotlight_id IN (SELECT rowid FROM messages_fts WHERE messages_fts MATCH ?)")
            # Escape special FTS5 chars and add prefix matching
            safe_query = query.replace('"', '""')
            params.append(f'"{safe_query}"')

        if message_id is not None:
            conditions.append("mail_message_id = ?")
            params.append(message_id)

        if sender:
            conditions.append("(sender LIKE ? OR sender_name LIKE ?)")
            params.extend([f"%{sender}%", f"%{sender}%"])

        if recipient:
            conditions.append("(recipients LIKE ? OR cc_recipients LIKE ?)")
            params.extend([f"%{recipient}%", f"%{recipient}%"])

        if subject:
            conditions.append("subject LIKE ?")
            params.append(f"%{subject}%")

        if account:
            conditions.append("account LIKE ?")
            params.append(f"%{account}%")

        if mailbox:
            conditions.append("mailboxes LIKE ?")
            params.append(f"%{mailbox}%")

        if today_only:
            today = datetime.date.today().isoformat()
            conditions.append("date_received >= ?")
            params.append(today)
        elif days:
            cutoff = (datetime.datetime.now() - datetime.timedelta(days=days)).isoformat()
            conditions.append("date_received >= ?")
            params.append(cutoff)

        if unread_only:
            conditions.append("is_read = 0")
        if flagged_only:
            conditions.append("is_flagged = 1")
        if has_attachments:
            conditions.append("has_attachments = 1")

        where = " AND ".join(conditions) if conditions else "1=1"
        sql = f"""
            SELECT * FROM messages
            WHERE {where}
            ORDER BY date_received DESC
            LIMIT ?
        """
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        results = []
        for row in rows:
            d = dict(row)
            if (resolve_urls or with_content) and not d.get('message_url'):
                self._resolve_message_url(d)
            # Extract full content from .emlx before popping internal fields
            if with_content:
                body = None
                emlx = d.get('emlx_path')
                if not emlx:
                    emlx = _derive_emlx_path(
                        d.get('account_id'),
                        d.get('mailboxes'),
                        d.get('mail_message_id'),
                        d.get('attachment_paths'),
                        d.get('date_received'),
                        d.get('subject'),
                    )
                if emlx:
                    body = _extract_emlx_body(emlx, with_links=with_links)
                # Fallback: AppleScript for messages without local .emlx
                if not body and d.get('subject'):
                    body = _fetch_content_via_applescript(
                        d['subject'], d.get('account_id'),
                    )
                if body:
                    d['content'] = body
            # Clean up internal fields for output
            d.pop('spotlight_id', None)
            d.pop('content_length', None)
            d.pop('storage_size', None)
            d.pop('account_id', None)
            d.pop('attachment_paths', None)
            results.append(d)

        return results

    def _resolve_message_url(self, row: dict) -> None:
        """Lazily resolve the message:// URL for a row."""
        emlx_path = row.get('emlx_path')
        if not emlx_path:
            emlx_path = _derive_emlx_path(
                row.get('account_id'),
                row.get('mailboxes'),
                row.get('mail_message_id'),
                row.get('attachment_paths'),
                row.get('date_received'),
                row.get('subject'),
            )
            if emlx_path:
                row['emlx_path'] = emlx_path

        if emlx_path:
            rfc_id = _extract_rfc_message_id(emlx_path)
            if rfc_id:
                row['rfc_message_id'] = rfc_id
                row['message_url'] = _make_message_url(rfc_id)
                # Cache it back to the DB
                try:
                    conn = self._get_conn()
                    conn.execute(
                        "UPDATE messages SET emlx_path=?, rfc_message_id=?, message_url=? WHERE mail_message_id=?",
                        (emlx_path, rfc_id, row['message_url'], row.get('mail_message_id'))
                    )
                    conn.commit()
                except Exception:
                    pass

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None


# ---------------------------------------------------------------------------
# CLI interface
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Search Apple Mail via Core Spotlight index",
        prog="python -m macbot.spotlight.mail_search",
    )
    parser.add_argument("--query", "-q", help="Full-text search query")
    parser.add_argument("--sender", help="Filter by sender email/name")
    parser.add_argument("--recipient", help="Filter by recipient email/name (To/CC)")
    parser.add_argument("--subject", help="Filter by subject")
    parser.add_argument("--account", help="Filter by account")
    parser.add_argument("--mailbox", help="Filter by mailbox")
    parser.add_argument("--days", type=int, help="Only last N days")
    parser.add_argument("--today", action="store_true", help="Only today")
    parser.add_argument("--unread", action="store_true", help="Only unread")
    parser.add_argument("--flagged", action="store_true", help="Only flagged")
    parser.add_argument("--attachments", action="store_true", help="Only with attachments")
    parser.add_argument("--limit", type=int, default=20, help="Max results (default: 20)")
    parser.add_argument("--resolve-urls", action="store_true", help="Resolve message:// URLs")
    parser.add_argument("--rebuild", action="store_true", help="Force rebuild index")
    parser.add_argument("--stats", action="store_true", help="Show index stats")
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        stream=sys.stderr,
    )

    index = MailSearchIndex()

    if args.stats:
        count = index.message_count()
        last_rebuild = index._get_meta("last_rebuild") or "never"
        store_db = _find_store_db()
        store_mtime = ""
        if store_db:
            store_mtime = datetime.datetime.fromtimestamp(store_db.stat().st_mtime).isoformat()
        info = {
            "message_count": count,
            "last_rebuild": last_rebuild,
            "store_mtime": store_mtime,
            "cache_path": str(index._cache_path),
            "needs_rebuild": index.needs_rebuild(),
        }
        if args.json:
            print(json.dumps(info, indent=2))
        else:
            for k, v in info.items():
                print(f"{k}: {v}")
        return

    if args.rebuild:
        t0 = time.time()
        def progress(n: int) -> None:
            print(f"\rIndexing... {n} messages", end="", file=sys.stderr)
        count = index.rebuild(progress_callback=progress)
        elapsed = time.time() - t0
        print(f"\rIndexed {count} messages in {elapsed:.1f}s", file=sys.stderr)
        if not any([args.query, args.sender, args.subject, args.account,
                     args.mailbox, args.days, args.today]):
            return

    # Ensure index is fresh
    if not args.rebuild:
        if index.needs_rebuild() or index.message_count() == 0:
            t0 = time.time()
            def progress(n: int) -> None:
                print(f"\rIndexing... {n} messages", end="", file=sys.stderr)
            count = index.rebuild(progress_callback=progress)
            elapsed = time.time() - t0
            print(f"\rIndexed {count} messages in {elapsed:.1f}s", file=sys.stderr)

    results = index.search(
        query=args.query,
        sender=args.sender,
        recipient=args.recipient,
        subject=args.subject,
        account=args.account,
        mailbox=args.mailbox,
        days=args.days,
        today_only=args.today,
        unread_only=args.unread,
        flagged_only=args.flagged,
        has_attachments=args.attachments,
        limit=args.limit,
        resolve_urls=args.resolve_urls,
    )

    if args.json:
        print(json.dumps({"success": True, "count": len(results), "emails": results}, indent=2))
    else:
        if not results:
            print("No results found.")
            return
        for i, msg in enumerate(results, 1):
            date = msg.get('date_received', '')[:19]
            subj = msg.get('subject', '')[:80]
            sender = msg.get('sender', '')
            read = "" if msg.get('is_read') else " [UNREAD]"
            flag = " [FLAGGED]" if msg.get('is_flagged') else ""
            attach = f" [{msg.get('attachment_names')}]" if msg.get('attachment_names') else ""
            print(f"{i:3d}. {date}  {sender}")
            print(f"     {subj}{read}{flag}{attach}")
            if msg.get('snippet'):
                snip = msg['snippet'][:120]
                print(f"     {snip}...")
            if msg.get('message_url'):
                print(f"     {msg['message_url']}")
            print()

    index.close()


if __name__ == "__main__":
    main()
