"""Headless mail access — IMAP (XOAUTH2 or app-password) or Microsoft Graph.

Operate on mailboxes (search / mark-read / move-to-trash) with **Mail.app closed**
and without EWS. Each account uses one transport, chosen at login and stored in
the account config:

  * ``imap``  — IMAP+XOAUTH2 (Microsoft/Exchange Online via outlook.office365.com).
  * ``graph`` — Microsoft Graph REST, for tenants that disable IMAP (e.g. pamies.de).
  * ``basic`` — IMAP LOGIN with an app password, for Gmail / iCloud. OAuth for the
    Gmail full-mailbox scope is a restricted scope (verification + 7-day testing
    tokens), so app passwords are the pragmatic path. The password lives in the
    macOS Keychain, never in config.

Microsoft transports authenticate via MSAL device-code; their tokens cache under
``~/.macbot/mail/<email>/``. Login is a one-time interactive step a human runs;
operations are silent and agent-drivable.
"""
from __future__ import annotations

import base64
import datetime
import html as html_lib
import imaplib
import json
import mimetypes
import re
import sqlite3
from dataclasses import dataclass, field
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.parser import BytesParser
from email.policy import default as default_policy
from email.utils import formatdate, make_msgid
from pathlib import Path
from typing import Any

import httpx
import msal  # type: ignore[import-untyped]

from macbot.core.keychain import delete_keychain, get_keychain, set_keychain

MAIL_DIR = Path.home() / ".macbot" / "mail"
ACCOUNTS_DB = Path.home() / "Library" / "Accounts" / "Accounts4.sqlite"
AUTHORITY = "https://login.microsoftonline.com/organizations"
GRAPH_BASE = "https://graph.microsoft.com/v1.0"

# macOS Internet-Account type description -> our provider key.
MACOS_TYPE_TO_PROVIDER = {
    "Exchange": "microsoft",
    "MSO": "microsoft",
    "Gmail": "google",
    "Google": "google",
    "iCloud": "icloud",
    "IMAP": "imap_generic",
    "IMAPMail": "imap_generic",
}

# OAuth scopes per Microsoft transport. "basic" needs no scope (password auth).
OAUTH_SCOPES = {
    "imap": ["https://outlook.office365.com/IMAP.AccessAsUser.All"],
    "graph": ["https://graph.microsoft.com/Mail.ReadWrite"],
}
DEFAULT_TRANSPORT = "imap"  # back-compat for configs written before transports


@dataclass
class Provider:
    oauth: str  # "msal" | "app_password"
    transports: list[str] = field(default_factory=list)
    imap_host: str = ""
    imap_port: int = 993
    trash_folder: str = ""
    archive_folder: str = ""
    drafts_folder: str = ""


PROVIDERS: dict[str, Provider] = {
    # Gmail's "Archive" is removing the inbox label; moving to [Gmail]/All Mail
    # achieves exactly that over IMAP (the message already lives in All Mail).
    "microsoft": Provider("msal", ["imap", "graph"], "outlook.office365.com", 993, "Deleted Items", "Archive", "Drafts"),
    "google": Provider("app_password", ["basic"], "imap.gmail.com", 993, "[Gmail]/Trash", "[Gmail]/All Mail", "[Gmail]/Drafts"),
    "icloud": Provider("app_password", ["basic"], "imap.mail.me.com", 993, "Deleted Messages", "Archive", "Drafts"),
}

# Graph well-known folder ids keyed by names callers tend to pass.
GRAPH_FOLDERS = {
    "inbox": "inbox", "archive": "archive", "sent": "sentitems",
    "sent items": "sentitems", "drafts": "drafts", "junk": "junkemail",
    "deleted items": "deleteditems", "trash": "deleteditems",
}


class NotLoggedInError(RuntimeError):
    """Raised when an account has no usable credential (login required)."""


class TransportUnavailableError(RuntimeError):
    """Raised when a tenant won't grant a transport's scope (try another transport)."""


def _decode(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _quote(folder: str) -> str:
    return '"' + folder.replace('"', '\\"') + '"'


def _strip_html(s: str) -> str:
    """Crude HTML → text: drop script/style, turn breaks into newlines, unescape."""
    s = re.sub(r"(?is)<(script|style)\b.*?</\1>", "", s)
    s = re.sub(r"(?is)<br\s*/?>", "\n", s)
    s = re.sub(r"(?is)</(p|div|tr|h[1-6])>", "\n", s)
    s = re.sub(r"(?s)<[^>]+>", "", s)
    s = html_lib.unescape(s)
    return re.sub(r"\n{3,}", "\n\n", s)


def _safe_filename(name: str) -> str:
    """Reduce an attachment name to a single safe path component."""
    name = name.replace("\x00", "").strip().replace("/", "_").replace("\\", "_")
    name = name.lstrip(".") or "attachment"
    return name[:200]


def _unique_path(path: "Path") -> "Path":
    """Return a non-colliding path by appending ' (n)' before the suffix."""
    if not path.exists():
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    i = 1
    while True:
        candidate = parent / f"{stem} ({i}){suffix}"
        if not candidate.exists():
            return candidate
        i += 1


def _extract_body(msg: Any) -> tuple[str, str]:
    """Best-effort plain-text body. Returns (text, format)."""
    for pref, fmt in (("plain", "text"), ("html", "html-stripped")):
        try:
            part = msg.get_body(preferencelist=(pref,))
        except Exception:
            part = None
        if part is not None:
            content = part.get_content()
            text = _strip_html(content) if pref == "html" else content
            return text.strip(), fmt
    if not msg.is_multipart():
        try:
            return (msg.get_content() or "").strip(), "text"
        except Exception:
            return "", "none"
    return "", "none"


def _attachment_meta(msg: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for att in msg.iter_attachments():
        try:
            payload = att.get_content()
            size = len(payload) if isinstance(payload, (bytes, bytearray, str)) else None
        except Exception:
            size = None
        out.append({
            "name": att.get_filename() or "(unnamed)",
            "content_type": att.get_content_type(),
            "size": size,
        })
    return out


def _save_attachments(msg: Any, save_dir: str | None, uid: str) -> dict[str, Any]:
    dest = Path(save_dir).expanduser() if save_dir else (Path.home() / "Downloads")
    dest.mkdir(parents=True, exist_ok=True)
    saved: list[dict[str, Any]] = []
    for i, att in enumerate(msg.iter_attachments()):
        try:
            payload = att.get_content()
        except Exception:
            continue
        if isinstance(payload, str):
            payload = payload.encode("utf-8", "replace")
        name = _safe_filename(att.get_filename() or f"attachment-{uid}-{i}")
        path = _unique_path(dest / name)
        path.write_bytes(payload)
        saved.append({
            "name": name,
            "path": str(path),
            "size": len(payload),
            "content_type": att.get_content_type(),
        })
    return {"uid": uid, "count": len(saved), "saved": saved, "dir": str(dest)}


def _addr_list(value: Any) -> list[str]:
    """Normalize an address input (None / str / list) into a clean list of addresses.

    A string may hold several addresses separated by commas or semicolons.
    """
    if value is None:
        return []
    if isinstance(value, str):
        parts = re.split(r"[,;]", value)
    else:
        parts = [str(v) for v in value]
    return [p.strip() for p in parts if p and p.strip()]


def _build_draft_message(
    from_addr: str,
    to: Any,
    subject: str,
    body: str,
    cc: Any = None,
    bcc: Any = None,
    attachments: list[str] | None = None,
    html: bool = False,
) -> EmailMessage:
    """Assemble an RFC-822 message (with attachments) for use as a draft.

    Raises FileNotFoundError if an attachment path does not point at a file.
    """
    msg = EmailMessage()
    if from_addr:
        msg["From"] = from_addr
    to_list, cc_list, bcc_list = _addr_list(to), _addr_list(cc), _addr_list(bcc)
    if to_list:
        msg["To"] = ", ".join(to_list)
    if cc_list:
        msg["Cc"] = ", ".join(cc_list)
    if bcc_list:
        msg["Bcc"] = ", ".join(bcc_list)
    msg["Subject"] = subject or ""
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()
    if html:
        # Keep a plain-text alternative so the draft renders everywhere.
        msg.set_content(_strip_html(body or ""))
        msg.add_alternative(body or "", subtype="html")
    else:
        msg.set_content(body or "")
    for raw_path in attachments or []:
        path = Path(raw_path).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"Attachment not found: {raw_path}")
        ctype, _ = mimetypes.guess_type(path.name)
        maintype, _, subtype = (ctype or "application/octet-stream").partition("/")
        msg.add_attachment(
            path.read_bytes(),
            maintype=maintype,
            subtype=subtype or "octet-stream",
            filename=path.name,
        )
    return msg


def _kc_account(email: str) -> str:
    return f"mail:{email}"


def _is_transport_unavailable(result: dict[str, Any]) -> bool:
    err = (result.get("error") or "").lower()
    desc = (result.get("error_description") or "").lower()
    if err in ("unauthorized_client", "invalid_grant", "consent_required"):
        return True
    return any(s in desc for s in ("aadsts65006", "no entitlements", "admin", "not found in the directory"))


def detect_provider(email: str) -> str:
    """Best guess of the provider for an email: config, then macOS, then domain."""
    client = MailClient(email)
    if client.is_configured():
        return client.provider_key
    for a in discover_macos_accounts():
        if a["email"].lower() == email.lower():
            return str(a["provider"])
    dom = email.split("@")[-1].lower()
    if dom in ("gmail.com", "googlemail.com"):
        return "google"
    if dom in ("icloud.com", "me.com", "mac.com"):
        return "icloud"
    return "microsoft"


# ---------------------------------------------------------------------------
# Account discovery
# ---------------------------------------------------------------------------


def discover_macos_accounts() -> list[dict[str, Any]]:
    """Enumerate mail accounts macOS already has configured (read-only)."""
    if not ACCOUNTS_DB.exists():
        return []
    try:
        con = sqlite3.connect(f"file:{ACCOUNTS_DB}?mode=ro&immutable=1", uri=True)
    except sqlite3.Error:
        return []
    try:
        rows = con.execute(
            """
            SELECT a.ZUSERNAME, t.ZACCOUNTTYPEDESCRIPTION
            FROM ZACCOUNT a
            JOIN ZACCOUNTTYPE t ON a.ZACCOUNTTYPE = t.Z_PK
            WHERE t.ZACCOUNTTYPEDESCRIPTION IN
                  ('Exchange','MSO','Gmail','Google','iCloud','IMAP','IMAPMail')
              AND a.ZUSERNAME IS NOT NULL AND a.ZUSERNAME != ''
            """
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()

    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for username, macos_type in rows:
        email = username.strip()
        if "@" not in email or email.lower() in seen:
            continue
        seen.add(email.lower())
        provider = MACOS_TYPE_TO_PROVIDER.get(macos_type, "imap_generic")
        # Domain wins over the macOS account type: e.g. a gmail.com address that
        # doubles as the iCloud Apple ID is registered as type 'iCloud' but is a
        # Gmail mailbox (imap.gmail.com), not iCloud.
        dom = email.split("@")[-1].lower()
        if dom in ("gmail.com", "googlemail.com"):
            provider = "google"
        elif dom in ("icloud.com", "me.com", "mac.com"):
            provider = "icloud"
        out.append(
            {
                "email": email,
                "macos_type": macos_type,
                "provider": provider,
                "supported": provider in PROVIDERS,
            }
        )
    return out


def list_configured_accounts() -> list[str]:
    """Email addresses that have a config under ~/.macbot/mail/."""
    if not MAIL_DIR.exists():
        return []
    return sorted(
        d.name for d in MAIL_DIR.iterdir()
        if d.is_dir() and (d / "config.json").exists()
    )


def account_overview() -> list[dict[str, Any]]:
    """Merge macOS-available accounts with our configured/logged-in state (no network)."""
    macos = {a["email"].lower(): a for a in discover_macos_accounts()}
    configured = set(list_configured_accounts())

    emails = set(macos) | {e.lower() for e in configured}
    overview: list[dict[str, Any]] = []
    for email_l in sorted(emails):
        info = macos.get(email_l, {})
        email = next((c for c in configured if c.lower() == email_l), info.get("email", email_l))
        client = MailClient(email) if email in configured else None
        overview.append(
            {
                "email": email,
                "provider": (client.provider_key if client else info.get("provider", "imap_generic")),
                "transport": client.transport if client else None,
                "macos_type": info.get("macos_type"),
                "configured": email in configured,
                "logged_in": bool(client and client.has_valid_token()),
                "supported": info.get("supported", email in configured),
            }
        )
    return overview


def probe_account(email: str) -> dict[str, Any]:
    """Live capability check: actually reach the mailbox. Networked."""
    client = MailClient(email)
    if not client.is_configured():
        return {"ok": False, "transport": None, "detail": "not configured"}
    if not client.has_valid_token():
        return {"ok": False, "transport": client.transport, "detail": "not logged in"}
    try:
        return {"ok": True, "transport": client.transport, "detail": client.probe()}
    except Exception as e:
        return {"ok": False, "transport": client.transport, "detail": str(e)[:140]}


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class MailClient:
    """One mailbox over its configured transport (imap | graph | basic)."""

    def __init__(self, email: str) -> None:
        self.email = email
        self.account_dir = MAIL_DIR / email
        self.config_path = self.account_dir / "config.json"
        self.cache_path = self.account_dir / "token_cache.json"

    # --- config --------------------------------------------------------------

    def is_configured(self) -> bool:
        return self.config_path.exists()

    def load_config(self) -> dict[str, Any]:
        if not self.config_path.exists():
            raise FileNotFoundError(
                f"Mail account '{self.email}' not configured. Run mail login first."
            )
        data: dict[str, Any] = json.loads(self.config_path.read_text())
        return data

    def save_config(self, provider: str, transport: str, client_id: str) -> None:
        self.account_dir.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps(
                {"email": self.email, "provider": provider,
                 "transport": transport, "client_id": client_id},
                indent=2,
            )
        )

    @property
    def provider_key(self) -> str:
        try:
            return str(self.load_config().get("provider", "microsoft"))
        except FileNotFoundError:
            return "microsoft"

    @property
    def provider(self) -> Provider:
        return PROVIDERS.get(self.provider_key, PROVIDERS["microsoft"])

    @property
    def transport(self) -> str:
        try:
            return str(self.load_config().get("transport", DEFAULT_TRANSPORT))
        except FileNotFoundError:
            return DEFAULT_TRANSPORT

    @property
    def scopes(self) -> list[str]:
        return OAUTH_SCOPES[self.transport]

    # --- app password (basic transport) -------------------------------------

    def _app_password(self) -> str | None:
        return get_keychain(_kc_account(self.email))

    def set_app_password(self, password: str) -> bool:
        return set_keychain(_kc_account(self.email), password)

    def clear_app_password(self) -> bool:
        return delete_keychain(_kc_account(self.email))

    # --- token (OAuth transports) -------------------------------------------

    def _get_cache(self) -> msal.SerializableTokenCache:
        cache = msal.SerializableTokenCache()
        if self.cache_path.exists():
            cache.deserialize(self.cache_path.read_text())
        return cache

    def _save_cache(self, cache: msal.SerializableTokenCache) -> None:
        if cache.has_state_changed:
            self.account_dir.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(cache.serialize())

    def _msal_app(self, cache: msal.SerializableTokenCache, client_id: str) -> msal.PublicClientApplication:
        return msal.PublicClientApplication(client_id=client_id, authority=AUTHORITY, token_cache=cache)

    def get_token_silent(self) -> str | None:
        cache = self._get_cache()
        app = self._msal_app(cache, self.load_config()["client_id"])
        accounts = app.get_accounts(username=self.email) or app.get_accounts()
        if not accounts:
            return None
        result = app.acquire_token_silent(self.scopes, account=accounts[0])
        self._save_cache(cache)
        if result and "access_token" in result:
            token: str = result["access_token"]
            return token
        return None

    def has_valid_token(self) -> bool:
        if self.transport == "basic":
            return self._app_password() is not None
        try:
            return self.get_token_silent() is not None
        except Exception:
            return False

    def _require_token(self) -> str:
        token = self.get_token_silent()
        if not token:
            raise NotLoggedInError(f"No valid token for '{self.email}'. Run mail login first.")
        return token

    def login_device_flow(self, client_id: str, provider: str, transport: str, on_prompt: Any) -> str:
        """Interactive device-code login for a Microsoft transport. Returns the transport."""
        if transport not in OAUTH_SCOPES:
            raise ValueError(f"Transport '{transport}' is not an OAuth transport")
        self.save_config(provider=provider, transport=transport, client_id=client_id)
        cache = self._get_cache()
        app = self._msal_app(cache, client_id)
        flow = app.initiate_device_flow(scopes=OAUTH_SCOPES[transport])
        if "user_code" not in flow:
            if _is_transport_unavailable(flow):
                raise TransportUnavailableError(f"{transport}: {flow.get('error_description', flow)}")
            raise RuntimeError(f"Device flow init failed: {flow}")
        on_prompt(flow["message"])
        result = app.acquire_token_by_device_flow(flow)  # blocks
        self._save_cache(cache)
        if "access_token" in result:
            return transport
        if _is_transport_unavailable(result):
            raise TransportUnavailableError(
                f"{transport}: {result.get('error_description', result.get('error'))}"
            )
        raise RuntimeError(f"Login failed: {result.get('error')}: {result.get('error_description')}")

    # --- dispatch ------------------------------------------------------------

    def probe(self) -> str:
        return self._graph_probe() if self.transport == "graph" else self._imap_probe()

    def search(self, mailbox: str = "INBOX", unread_only: bool = False,
               since_days: int | None = None, sender: str | None = None,
               subject: str | None = None, limit: int = 25) -> list[dict[str, Any]]:
        if self.transport == "graph":
            return self._graph_search(mailbox, unread_only, since_days, sender, subject, limit)
        return self._imap_search(mailbox, unread_only, since_days, sender, subject, limit)

    def set_read(self, uid: str, read: bool = True, mailbox: str = "INBOX") -> dict[str, Any]:
        if self.transport == "graph":
            return self._graph_set_read(uid, read)
        return self._imap_set_read(uid, read, mailbox)

    def move_to_trash(self, uid: str, mailbox: str = "INBOX") -> dict[str, Any]:
        if self.transport == "graph":
            return self._graph_trash(uid)
        return self._imap_trash(uid, mailbox)

    def move_to_archive(self, uid: str, mailbox: str = "INBOX") -> dict[str, Any]:
        if self.transport == "graph":
            return self._graph_archive(uid)
        return self._imap_archive(uid, mailbox)

    def fetch_content(self, uid: str, mailbox: str = "INBOX", max_chars: int = 20000) -> dict[str, Any]:
        if self.transport == "graph":
            return self._graph_content(uid, max_chars)
        return self._imap_content(uid, mailbox, max_chars)

    def download_attachments(self, uid: str, mailbox: str = "INBOX",
                             save_dir: str | None = None) -> dict[str, Any]:
        if self.transport == "graph":
            return self._graph_download_attachments(uid, save_dir)
        return self._imap_download_attachments(uid, mailbox, save_dir)

    def create_draft(self, to: Any = None, subject: str = "", body: str = "",
                     cc: Any = None, bcc: Any = None,
                     attachments: list[str] | None = None,
                     html: bool = False) -> dict[str, Any]:
        if self.transport == "graph":
            return self._graph_create_draft(to, subject, body, cc, bcc, attachments, html)
        return self._imap_create_draft(to, subject, body, cc, bcc, attachments, html)

    # --- IMAP transport (XOAUTH2 or app-password LOGIN) ----------------------

    def _imap_connect(self) -> imaplib.IMAP4_SSL:
        p = self.provider
        host = p.imap_host or "outlook.office365.com"
        imap = imaplib.IMAP4_SSL(host, p.imap_port or 993)
        if self.transport == "basic":
            pw = self._app_password()
            if not pw:
                raise NotLoggedInError(
                    f"No app password stored for '{self.email}'. Run: son mail login {self.email}"
                )
            imap.login(self.email, pw)
        else:
            token = self._require_token()
            auth = f"user={self.email}\x01auth=Bearer {token}\x01\x01".encode()
            imap.authenticate("XOAUTH2", lambda _: auth)
        return imap

    def _imap_probe(self) -> str:
        imap = self._imap_connect()
        try:
            typ, data = imap.select("INBOX", readonly=True)
            if typ != "OK":
                raise RuntimeError(f"SELECT INBOX failed: {data}")
            count = int(data[0]) if data and data[0] else 0
            return f"{self.transport}: INBOX reachable ({count} msgs)"
        finally:
            self._imap_logout(imap)

    def _imap_search(self, mailbox: str, unread_only: bool, since_days: int | None,
                     sender: str | None, subject: str | None, limit: int) -> list[dict[str, Any]]:
        imap = self._imap_connect()
        try:
            typ, data = imap.select(_quote(mailbox), readonly=True)
            if typ != "OK":
                raise RuntimeError(f"SELECT {mailbox} failed: {data}")
            criteria: list[str] = []
            if unread_only:
                criteria.append("UNSEEN")
            if since_days is not None:
                since = datetime.date.today() - datetime.timedelta(days=since_days)
                criteria += ["SINCE", since.strftime("%d-%b-%Y")]
            if sender:
                criteria += ["FROM", f'"{sender}"']
            if subject:
                criteria += ["SUBJECT", f'"{subject}"']
            if not criteria:
                criteria = ["ALL"]
            typ, data = imap.uid("SEARCH", None, *criteria)  # type: ignore[arg-type]
            if typ != "OK":
                raise RuntimeError(f"SEARCH failed: {data}")
            raw = data[0] if data else None
            uid_list = [u.decode() for u in raw.split()] if raw else []
            uid_list = list(reversed(uid_list))[:limit]
            results: list[dict[str, Any]] = []
            for uid in uid_list:
                typ, msg_data = imap.uid(
                    "FETCH", uid,
                    "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID)] FLAGS)",
                )
                if typ != "OK":
                    continue
                headers = b""
                flags = b""
                for part in msg_data:
                    if isinstance(part, tuple):
                        headers = part[1]
                    elif isinstance(part, bytes):
                        flags += part
                hdr = BytesParser(policy=default_policy).parsebytes(headers)
                results.append({
                    "uid": uid,
                    "subject": _decode(hdr.get("subject")),
                    "from": _decode(hdr.get("from")),
                    "date": hdr.get("date", ""),
                    "message_id": hdr.get("message-id", ""),
                    "seen": b"\\Seen" in flags,
                    "flagged": b"\\Flagged" in flags,
                })
            return results
        finally:
            self._imap_logout(imap)

    def _imap_set_read(self, uid: str, read: bool, mailbox: str) -> dict[str, Any]:
        imap = self._imap_connect()
        try:
            imap.select(_quote(mailbox))
            op = "+FLAGS" if read else "-FLAGS"
            typ, data = imap.uid("STORE", uid, op, "(\\Seen)")
            return {"uid": uid, "read": read, "ok": typ == "OK", "transport": self.transport}
        finally:
            self._imap_logout(imap)

    def _imap_trash(self, uid: str, mailbox: str) -> dict[str, Any]:
        imap = self._imap_connect()
        try:
            imap.select(_quote(mailbox))
            trash = _quote(self.provider.trash_folder)
            typ, data = imap.uid("MOVE", uid, trash)
            if typ == "OK":
                return {"uid": uid, "ok": True, "method": "MOVE",
                        "transport": self.transport, "trash": self.provider.trash_folder}
            imap.uid("COPY", uid, trash)
            imap.uid("STORE", uid, "+FLAGS", "(\\Deleted)")
            imap.expunge()
            return {"uid": uid, "ok": True, "method": "COPY+EXPUNGE",
                    "transport": self.transport, "trash": self.provider.trash_folder}
        finally:
            self._imap_logout(imap)

    def _imap_archive(self, uid: str, mailbox: str) -> dict[str, Any]:
        dest = self.provider.archive_folder
        if not dest:
            raise RuntimeError(f"No archive folder configured for '{self.email}'.")
        imap = self._imap_connect()
        try:
            imap.select(_quote(mailbox))
            archive = _quote(dest)
            typ, data = imap.uid("MOVE", uid, archive)
            if typ == "OK":
                return {"uid": uid, "ok": True, "method": "MOVE",
                        "transport": self.transport, "archive": dest}
            imap.uid("COPY", uid, archive)
            imap.uid("STORE", uid, "+FLAGS", "(\\Deleted)")
            imap.expunge()
            return {"uid": uid, "ok": True, "method": "COPY+EXPUNGE",
                    "transport": self.transport, "archive": dest}
        finally:
            self._imap_logout(imap)

    def _imap_fetch_message(self, uid: str, mailbox: str) -> Any:
        """Fetch and parse a full message into an EmailMessage."""
        imap = self._imap_connect()
        try:
            typ, _ = imap.select(_quote(mailbox), readonly=True)
            if typ != "OK":
                raise RuntimeError(f"SELECT {mailbox} failed")
            typ, msg_data = imap.uid("FETCH", uid, "(BODY.PEEK[])")
            if typ != "OK" or not msg_data:
                raise RuntimeError(f"FETCH {uid} failed")
            raw = next((p[1] for p in msg_data if isinstance(p, tuple)), None)
            if raw is None:
                raise RuntimeError(f"Message uid {uid} not found in {mailbox}")
            return BytesParser(policy=default_policy).parsebytes(raw)
        finally:
            self._imap_logout(imap)

    def _imap_content(self, uid: str, mailbox: str, max_chars: int) -> dict[str, Any]:
        msg = self._imap_fetch_message(uid, mailbox)
        body, fmt = _extract_body(msg)
        return {
            "uid": uid,
            "transport": self.transport,
            "subject": _decode(msg.get("subject")),
            "from": _decode(msg.get("from")),
            "to": _decode(msg.get("to")),
            "date": msg.get("date", ""),
            "message_id": msg.get("message-id", ""),
            "body": body[:max_chars],
            "body_format": fmt,
            "truncated": len(body) > max_chars,
            "attachments": _attachment_meta(msg),
        }

    def _imap_download_attachments(self, uid: str, mailbox: str,
                                   save_dir: str | None) -> dict[str, Any]:
        msg = self._imap_fetch_message(uid, mailbox)
        return {**_save_attachments(msg, save_dir, uid), "transport": self.transport}

    def _imap_create_draft(self, to: Any, subject: str, body: str, cc: Any,
                           bcc: Any, attachments: list[str] | None,
                           html: bool) -> dict[str, Any]:
        dest = self.provider.drafts_folder
        if not dest:
            raise RuntimeError(f"No drafts folder configured for '{self.email}'.")
        msg = _build_draft_message(self.email, to, subject, body, cc, bcc, attachments, html)
        raw = msg.as_bytes()
        imap = self._imap_connect()
        try:
            # APPEND into the Drafts folder, flagged \Draft (and \Seen so it isn't
            # counted unread). imaplib stamps the internal date when date is None.
            typ, data = imap.append(_quote(dest), r"(\Draft \Seen)", None, raw)
            if typ != "OK":
                raise RuntimeError(f"APPEND to {dest} failed: {data}")
            return {
                "ok": True,
                "transport": self.transport,
                "folder": dest,
                "to": _addr_list(to),
                "cc": _addr_list(cc),
                "subject": subject or "",
                "attachments": [Path(a).name for a in (attachments or [])],
                "size": len(raw),
            }
        finally:
            self._imap_logout(imap)

    @staticmethod
    def _imap_logout(imap: imaplib.IMAP4_SSL) -> None:
        try:
            imap.logout()
        except Exception:
            pass

    # --- Graph transport -----------------------------------------------------

    def _graph(self) -> httpx.Client:
        token = self._require_token()
        return httpx.Client(base_url=GRAPH_BASE, headers={"Authorization": f"Bearer {token}"}, timeout=30.0)

    def _graph_probe(self) -> str:
        with self._graph() as c:
            r = c.get("/me/mailFolders/inbox", params={"$select": "displayName,totalItemCount"})
            r.raise_for_status()
            return f"graph: inbox reachable ({r.json().get('totalItemCount', '?')} msgs)"

    def _graph_search(self, mailbox: str, unread_only: bool, since_days: int | None,
                      sender: str | None, subject: str | None, limit: int) -> list[dict[str, Any]]:
        folder = GRAPH_FOLDERS.get(mailbox.strip().lower(), mailbox.strip().lower())
        select = "id,subject,from,receivedDateTime,isRead,flag,internetMessageId"
        with self._graph() as c:
            if sender or subject:
                terms = []
                if sender:
                    terms.append(f"from:{sender}")
                if subject:
                    terms.append(f"subject:{subject}")
                if unread_only:
                    terms.append("isRead:false")
                params: dict[str, Any] = {"$search": '"' + " ".join(terms) + '"', "$top": limit, "$select": select}
            else:
                filters = []
                if unread_only:
                    filters.append("isRead eq false")
                if since_days is not None:
                    since = datetime.datetime.utcnow() - datetime.timedelta(days=since_days)
                    filters.append(f"receivedDateTime ge {since.strftime('%Y-%m-%dT%H:%M:%SZ')}")
                params = {"$top": limit, "$select": select, "$orderby": "receivedDateTime desc"}
                if filters:
                    params["$filter"] = " and ".join(filters)
            r = c.get(f"/me/mailFolders/{folder}/messages", params=params)
            r.raise_for_status()
            results: list[dict[str, Any]] = []
            for m in r.json().get("value", []):
                frm = (m.get("from") or {}).get("emailAddress") or {}
                results.append({
                    "uid": m.get("id"),
                    "subject": m.get("subject", ""),
                    "from": f"{frm.get('name', '')} <{frm.get('address', '')}>".strip(),
                    "date": m.get("receivedDateTime", ""),
                    "message_id": m.get("internetMessageId", ""),
                    "seen": bool(m.get("isRead")),
                    "flagged": (m.get("flag") or {}).get("flagStatus") == "flagged",
                })
            return results

    def _graph_set_read(self, uid: str, read: bool) -> dict[str, Any]:
        with self._graph() as c:
            c.patch(f"/me/messages/{uid}", json={"isRead": read}).raise_for_status()
            return {"uid": uid, "read": read, "ok": True, "transport": "graph"}

    def _graph_trash(self, uid: str) -> dict[str, Any]:
        with self._graph() as c:
            r = c.post(f"/me/messages/{uid}/move", json={"destinationId": "deleteditems"})
            r.raise_for_status()
            return {"uid": uid, "ok": True, "method": "move", "transport": "graph",
                    "new_id": r.json().get("id"), "trash": "deleteditems"}

    def _graph_archive(self, uid: str) -> dict[str, Any]:
        with self._graph() as c:
            r = c.post(f"/me/messages/{uid}/move", json={"destinationId": "archive"})
            r.raise_for_status()
            return {"uid": uid, "ok": True, "method": "move", "transport": "graph",
                    "new_id": r.json().get("id"), "archive": "archive"}

    def _graph_content(self, uid: str, max_chars: int) -> dict[str, Any]:
        select = ("subject,from,toRecipients,receivedDateTime,internetMessageId,"
                  "body,bodyPreview,hasAttachments")
        with self._graph() as c:
            r = c.get(f"/me/messages/{uid}", params={"$select": select})
            r.raise_for_status()
            m = r.json()
            body = m.get("body") or {}
            raw = body.get("content") or m.get("bodyPreview") or ""
            if (body.get("contentType") or "").lower() == "html":
                text, fmt = _strip_html(raw).strip(), "html-stripped"
            else:
                text, fmt = raw.strip(), "text"
            attachments: list[dict[str, Any]] = []
            if m.get("hasAttachments"):
                ar = c.get(f"/me/messages/{uid}/attachments",
                           params={"$select": "name,contentType,size"})
                ar.raise_for_status()
                for a in ar.json().get("value", []):
                    attachments.append({
                        "name": a.get("name"),
                        "content_type": a.get("contentType"),
                        "size": a.get("size"),
                    })
            to = ", ".join(
                ((rcpt.get("emailAddress") or {}).get("address", ""))
                for rcpt in (m.get("toRecipients") or [])
            )
            return {
                "uid": uid,
                "transport": "graph",
                "subject": m.get("subject", ""),
                "from": ((m.get("from") or {}).get("emailAddress") or {}).get("address", ""),
                "to": to,
                "date": m.get("receivedDateTime", ""),
                "message_id": m.get("internetMessageId", ""),
                "body": text[:max_chars],
                "body_format": fmt,
                "truncated": len(text) > max_chars,
                "attachments": attachments,
            }

    def _graph_download_attachments(self, uid: str, save_dir: str | None) -> dict[str, Any]:
        dest = Path(save_dir).expanduser() if save_dir else (Path.home() / "Downloads")
        dest.mkdir(parents=True, exist_ok=True)
        saved: list[dict[str, Any]] = []
        with self._graph() as c:
            r = c.get(f"/me/messages/{uid}/attachments")
            r.raise_for_status()
            for a in r.json().get("value", []):
                if not str(a.get("@odata.type", "")).endswith("fileAttachment"):
                    continue  # skip itemAttachment / referenceAttachment
                content_bytes = a.get("contentBytes")
                if not content_bytes:
                    continue
                data = base64.b64decode(content_bytes)
                name = _safe_filename(a.get("name") or f"attachment-{uid}")
                path = _unique_path(dest / name)
                path.write_bytes(data)
                saved.append({
                    "name": name,
                    "path": str(path),
                    "size": len(data),
                    "content_type": a.get("contentType"),
                })
        return {"uid": uid, "transport": "graph", "count": len(saved),
                "saved": saved, "dir": str(dest)}

    def _graph_create_draft(self, to: Any, subject: str, body: str, cc: Any,
                            bcc: Any, attachments: list[str] | None,
                            html: bool) -> dict[str, Any]:
        def _recips(value: Any) -> list[dict[str, Any]]:
            return [{"emailAddress": {"address": a}} for a in _addr_list(value)]

        payload: dict[str, Any] = {
            "subject": subject or "",
            "body": {"contentType": "HTML" if html else "Text", "content": body or ""},
            "toRecipients": _recips(to),
        }
        if _addr_list(cc):
            payload["ccRecipients"] = _recips(cc)
        if _addr_list(bcc):
            payload["bccRecipients"] = _recips(bcc)
        # Read attachments up front so a bad path fails before the draft is created.
        files: list[tuple[str, bytes, str]] = []
        for raw_path in attachments or []:
            path = Path(raw_path).expanduser()
            if not path.is_file():
                raise FileNotFoundError(f"Attachment not found: {raw_path}")
            data = path.read_bytes()
            if len(data) > 3_000_000:
                raise ValueError(
                    f"Attachment '{path.name}' is {len(data) // 1_000_000} MB; the Graph "
                    "draft path only supports attachments up to ~3 MB."
                )
            ctype, _ = mimetypes.guess_type(path.name)
            files.append((path.name, data, ctype or "application/octet-stream"))
        with self._graph() as c:
            r = c.post("/me/messages", json=payload)
            r.raise_for_status()
            msg = r.json()
            new_id = msg.get("id")
            for name, data, ctype in files:
                ar = c.post(
                    f"/me/messages/{new_id}/attachments",
                    json={
                        "@odata.type": "#microsoft.graph.fileAttachment",
                        "name": name,
                        "contentType": ctype,
                        "contentBytes": base64.b64encode(data).decode("ascii"),
                    },
                )
                ar.raise_for_status()
            return {
                "ok": True,
                "transport": "graph",
                "uid": new_id,
                "folder": "drafts",
                "to": _addr_list(to),
                "cc": _addr_list(cc),
                "subject": subject or "",
                "attachments": [f[0] for f in files],
                "web_link": msg.get("webLink"),
            }


# Back-compat alias (old name).
MailImapClient = MailClient


def basic_login(email: str, provider: str, app_password: str) -> str:
    """Store a Gmail/iCloud app password (Keychain) and verify it. Returns 'basic'."""
    if PROVIDERS.get(provider, Provider("")).oauth != "app_password":
        raise ValueError(f"Provider '{provider}' does not use app-password login")
    client = MailClient(email)
    client.save_config(provider=provider, transport="basic", client_id="")
    if not client.set_app_password(app_password):
        raise RuntimeError("Could not store the app password in the macOS Keychain.")
    try:
        client.probe()  # connect + select; raises on bad password / IMAP off
    except Exception:
        client.clear_app_password()
        raise
    return "basic"


def login_account(email: str, client_id: str, transport: str, on_prompt: Any) -> str:
    """Log in a Microsoft account via OAuth. transport='auto' tries imap then graph."""
    candidates = ["imap", "graph"] if transport == "auto" else [transport]
    last: Exception | None = None
    for t in candidates:
        try:
            return MailClient(email).login_device_flow(client_id, "microsoft", t, on_prompt)
        except TransportUnavailableError as e:
            last = e
            on_prompt(f"[{t}] not available for this tenant — trying the next transport…")
            continue
    raise last or RuntimeError("No transport could be used for this account.")


def resolve_account(email: str | None) -> str:
    """Resolve which configured account to use: explicit, single, or error."""
    if email:
        return email
    configured = list_configured_accounts()
    if not configured:
        raise ValueError("No mail accounts configured. Run mail login first.")
    if len(configured) == 1:
        return configured[0]
    raise ValueError(f"Multiple mail accounts configured: {', '.join(configured)}. Specify email.")
