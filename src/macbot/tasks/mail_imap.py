"""Tasks: headless IMAP mail over OAuth2 (XOAUTH2).

Lets the agent (1) discover which mail accounts exist and which are logged in,
and (2) run search / mark-read / move-to-trash on logged-in accounts — all with
Mail.app closed and without EWS. See ``macbot.mail_imap`` for the mechanics.

Login is a one-time interactive (device-code) step a human runs; the operation
tasks are fully silent and agent-drivable.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

from macbot.tasks.base import Task


def _resolve(email: str | None) -> str | dict[str, Any]:
    from macbot.mail_imap import resolve_account

    try:
        return resolve_account(email)
    except ValueError as e:
        return {"success": False, "error": str(e)}


class MailImapAccountsTask(Task):
    """Discover available mail accounts and their login state."""

    @property
    def name(self) -> str:
        return "mail_imap_accounts"

    @property
    def description(self) -> str:
        return (
            "List mail accounts and whether each can run IMAP operations right now. "
            "Returns, per account: email, provider, whether macOS has it configured, "
            "whether it is set up here (configured), and whether it is logged_in "
            "(has a valid OAuth token — only logged_in accounts can run search/mark/"
            "trash without interaction). Call this first. Accounts that are available "
            "but not logged_in need a one-time human login via mail_imap_login."
        )

    async def execute(self) -> dict[str, Any]:
        from macbot.mail_imap import account_overview

        accounts = await asyncio.to_thread(account_overview)
        ready = [a["email"] for a in accounts if a["logged_in"]]
        return {
            "success": True,
            "accounts": accounts,
            "logged_in": ready,
            "count": len(accounts),
        }


class MailImapLoginTask(Task):
    """One-time interactive OAuth login for a mailbox (device-code flow)."""

    @property
    def name(self) -> str:
        return "mail_imap_login"

    @property
    def description(self) -> str:
        return (
            "Interactively log in a Microsoft/Exchange mailbox for headless mail "
            "access (device-code OAuth). Blocks while the user opens the shown URL "
            "and enters the code. transport='auto' (default) tries IMAP then falls "
            "back to Microsoft Graph for tenants that disable IMAP; or force "
            "transport='imap'/'graph'. Requires a multi-tenant Azure app client_id "
            "(env MACBOT_MS_OAUTH_CLIENT_ID, or pass client_id). Best run from an "
            "interactive terminal so the device code is visible — or use the "
            "non-agent CLI: son mail login <email>."
        )

    async def execute(
        self,
        email: str,
        client_id: str | None = None,
        transport: str = "auto",
    ) -> dict[str, Any]:
        from macbot.config import settings
        from macbot.mail_imap import PROVIDERS, detect_provider, login_account

        provider = detect_provider(email)
        if PROVIDERS.get(provider, None) is not None and PROVIDERS[provider].oauth == "app_password":
            return {
                "success": False,
                "error": (
                    f"{provider} accounts ({email}) log in with an app password, which "
                    f"can't be entered through the agent. Run it in a terminal: "
                    f"son mail login {email}"
                ),
                "needs_cli_login": True,
            }

        cid = (
            client_id
            or settings.ms_oauth_client_id
            or os.environ.get("MACBOT_MS_OAUTH_CLIENT_ID")
        )
        if not cid:
            return {
                "success": False,
                "error": (
                    "No client_id. Set MACBOT_MS_OAUTH_CLIENT_ID in ~/.macbot/.env "
                    "or pass client_id (the multi-tenant Azure app id)."
                ),
            }

        def on_prompt(message: str) -> None:
            print("\n" + "=" * 70 + f"\n{message}\nSign in as: {email}\n" + "=" * 70, flush=True)

        try:
            chosen = await asyncio.to_thread(login_account, email, cid, transport, on_prompt)
            return {
                "success": True,
                "email": email,
                "transport": chosen,
                "message": f"Logged in {email} via {chosen}.",
            }
        except Exception as e:
            return {"success": False, "error": f"Login failed: {e}"}


class MailImapSearchTask(Task):
    """Search a mailbox over IMAP (no Mail.app needed)."""

    @property
    def name(self) -> str:
        return "mail_imap_search"

    @property
    def description(self) -> str:
        return (
            "Search a logged-in mailbox over IMAP and return message headers + flags "
            "(uid, subject, from, date, message_id, seen, flagged). Works with Mail.app "
            "closed. uid values are needed for mail_imap_mark_read / move_to_trash. "
            "If email is omitted and exactly one account is configured, it is used."
        )

    async def execute(
        self,
        email: str | None = None,
        mailbox: str = "INBOX",
        unread_only: bool = False,
        since_days: int | None = None,
        sender: str | None = None,
        subject: str | None = None,
        limit: int = 25,
    ) -> dict[str, Any]:
        from macbot.mail_imap import MailImapClient, NotLoggedInError

        resolved = _resolve(email)
        if isinstance(resolved, dict):
            return resolved
        client = MailImapClient(resolved)
        try:
            messages = await asyncio.to_thread(
                client.search, mailbox, unread_only, since_days, sender, subject, limit
            )
            return {
                "success": True,
                "email": resolved,
                "mailbox": mailbox,
                "count": len(messages),
                "messages": messages,
            }
        except NotLoggedInError as e:
            return {"success": False, "error": str(e), "needs_login": True}
        except Exception as e:
            return {"success": False, "error": f"Search failed: {e}"}


class MailImapMarkReadTask(Task):
    """Mark a message read/unread over IMAP."""

    @property
    def name(self) -> str:
        return "mail_imap_mark_read"

    @property
    def description(self) -> str:
        return (
            "Mark a message read (or unread) over IMAP, with Mail.app closed. "
            "Needs the uid from mail_imap_search. Set read=false to mark unread."
        )

    async def execute(
        self,
        uid: str,
        email: str | None = None,
        read: bool = True,
        mailbox: str = "INBOX",
    ) -> dict[str, Any]:
        from macbot.mail_imap import MailImapClient, NotLoggedInError

        resolved = _resolve(email)
        if isinstance(resolved, dict):
            return resolved
        client = MailImapClient(resolved)
        try:
            result = await asyncio.to_thread(client.set_read, uid, read, mailbox)
            return {"success": result.get("ok", False), "email": resolved, **result}
        except NotLoggedInError as e:
            return {"success": False, "error": str(e), "needs_login": True}
        except Exception as e:
            return {"success": False, "error": f"Mark read failed: {e}"}


class MailImapMoveToTrashTask(Task):
    """Move a message to the trash folder over IMAP."""

    @property
    def name(self) -> str:
        return "mail_imap_move_to_trash"

    @property
    def description(self) -> str:
        return (
            "Move a message to the account's trash (Deleted Items / [Gmail]/Trash) "
            "over IMAP, with Mail.app closed. Needs the uid from mail_imap_search. "
            "Recoverable — the message lands in the trash folder, not hard-deleted."
        )

    async def execute(
        self,
        uid: str,
        email: str | None = None,
        mailbox: str = "INBOX",
    ) -> dict[str, Any]:
        from macbot.mail_imap import MailImapClient, NotLoggedInError

        resolved = _resolve(email)
        if isinstance(resolved, dict):
            return resolved
        client = MailImapClient(resolved)
        try:
            result = await asyncio.to_thread(client.move_to_trash, uid, mailbox)
            return {"success": result.get("ok", False), "email": resolved, **result}
        except NotLoggedInError as e:
            return {"success": False, "error": str(e), "needs_login": True}
        except Exception as e:
            return {"success": False, "error": f"Move to trash failed: {e}"}


def register_mail_imap_tasks(registry) -> None:  # type: ignore[no-untyped-def]
    """Register headless IMAP mail tasks with a registry."""
    registry.register(MailImapAccountsTask())
    registry.register(MailImapLoginTask())
    registry.register(MailImapSearchTask())
    registry.register(MailImapMarkReadTask())
    registry.register(MailImapMoveToTrashTask())
