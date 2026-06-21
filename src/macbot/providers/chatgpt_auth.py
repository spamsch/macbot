"""Bridge Codex CLI credentials into LiteLLM's ChatGPT subscription provider.

ChatGPT Pro/Max models (``chatgpt/gpt-5.x``, Codex) authenticate with an OAuth
device flow, not an API key. LiteLLM's ``chatgpt/`` provider reads tokens from a
*flat* ``auth.json`` (``access_token``/``refresh_token``/``id_token``/``account_id``
at the top level) inside ``$CHATGPT_TOKEN_DIR``.

The Codex CLI already performs that login and stores the same tokens at
``~/.codex/auth.json`` — but *nested* under a ``tokens`` key, which LiteLLM does
not understand. This module discovers the Codex credentials, flattens them into a
directory MacBot owns (``~/.macbot/chatgpt`` by default), and points LiteLLM at
it via the ``CHATGPT_TOKEN_DIR``/``CHATGPT_AUTH_FILE`` environment variables.

We never write back into ``~/.codex`` — the Codex CLI owns that file and expects
the nested format. LiteLLM refreshes the access token (rotating it in *our* copy)
on its own. If the user re-logs in with Codex, the newer mtime triggers a
re-sync the next time a ``chatgpt/`` provider is created.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Keys LiteLLM's Authenticator reads from the flat auth file.
_TOKEN_KEYS = ("access_token", "refresh_token", "id_token", "account_id")


def codex_home() -> Path:
    """Return the Codex CLI config directory (honors ``CODEX_HOME``)."""
    env = os.getenv("CODEX_HOME")
    return Path(env).expanduser() if env else Path.home() / ".codex"


def find_codex_auth() -> Path | None:
    """Return the path to the Codex ``auth.json`` if it exists."""
    auth = codex_home() / "auth.json"
    return auth if auth.is_file() else None


def macbot_token_dir() -> Path:
    """Return the directory MacBot uses for LiteLLM's flat ChatGPT auth file.

    Honors ``MACBOT_CHATGPT_TOKEN_DIR`` (via settings) and falls back to
    ``~/.macbot/chatgpt``.
    """
    try:
        from macbot.config import settings

        configured = settings.chatgpt_token_dir
        if configured:
            return Path(configured).expanduser()
    except Exception:
        pass
    return Path.home() / ".macbot" / "chatgpt"


def _flatten(codex_data: dict[str, Any]) -> dict[str, Any]:
    """Flatten Codex's nested ``{tokens: {...}}`` into LiteLLM's flat format."""
    tokens = codex_data.get("tokens")
    source = tokens if isinstance(tokens, dict) else codex_data
    flat = {key: source.get(key) for key in _TOKEN_KEYS if source.get(key)}
    # Codex stores the account id inside the id_token claims when absent.
    if "account_id" not in flat:
        derived = _account_id_from_token(flat.get("id_token") or flat.get("access_token"))
        if derived:
            flat["account_id"] = derived
    return flat


def _account_id_from_token(token: str | None) -> str | None:
    """Best-effort extraction of the ChatGPT account id from a JWT."""
    if not token:
        return None
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return None
    auth = claims.get("https://api.openai.com/auth")
    if isinstance(auth, dict):
        account_id = auth.get("chatgpt_account_id")
        if isinstance(account_id, str) and account_id:
            return account_id
    return None


def sync_codex_auth() -> bool:
    """Bootstrap LiteLLM's ChatGPT auth from the Codex CLI credentials.

    Idempotent and cheap (an mtime check). Re-syncs only when Codex's file is
    newer than MacBot's copy, so LiteLLM's own token refreshes are not clobbered.

    Returns:
        True if a usable flat auth file with an access token is in place.
    """
    # Respect an explicit user override — they manage their own token dir.
    if os.getenv("CHATGPT_TOKEN_DIR"):
        target = Path(os.environ["CHATGPT_TOKEN_DIR"]).expanduser() / os.getenv(
            "CHATGPT_AUTH_FILE", "auth.json"
        )
        return _has_access_token(target)

    token_dir = macbot_token_dir()
    target = token_dir / "auth.json"
    codex_auth = find_codex_auth()

    if codex_auth is not None:
        try:
            should_sync = (
                not target.exists()
                or codex_auth.stat().st_mtime > target.stat().st_mtime
            )
        except OSError:
            should_sync = True
        if should_sync:
            try:
                flat = _flatten(json.loads(codex_auth.read_text()))
                if flat.get("access_token"):
                    token_dir.mkdir(parents=True, exist_ok=True)
                    target.write_text(json.dumps(flat))
                    os.chmod(target, 0o600)
                    logger.debug("Synced ChatGPT auth from Codex at %s", codex_auth)
            except Exception as exc:
                logger.warning("Failed to sync Codex ChatGPT auth: %s", exc)

    if _has_access_token(target):
        # Point LiteLLM's authenticator at our flat copy.
        os.environ["CHATGPT_TOKEN_DIR"] = str(token_dir)
        os.environ.setdefault("CHATGPT_AUTH_FILE", "auth.json")
        return True
    return False


def _has_access_token(auth_file: Path) -> bool:
    try:
        data = json.loads(auth_file.read_text())
    except Exception:
        return False
    return bool(data.get("access_token"))


def chatgpt_auth_status() -> dict[str, Any]:
    """Report ChatGPT/Codex credential status for ``son doctor``."""
    codex_auth = find_codex_auth()
    target = macbot_token_dir() / "auth.json"
    available = sync_codex_auth()
    account_id: str | None = None
    if available:
        try:
            data = json.loads(target.read_text())
            account_id = data.get("account_id")
        except Exception:
            pass
    return {
        "available": available,
        "codex_auth_path": str(codex_auth) if codex_auth else None,
        "synced_path": str(target) if target.exists() else None,
        "account_id": account_id,
    }
