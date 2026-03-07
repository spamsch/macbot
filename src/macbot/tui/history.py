"""Session-based chat history for the TUI.

Each session is a JSON file under ~/.macbot/sessions/<id>.json containing
a list of {ts, role, text} entries plus metadata (created, title).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SESSIONS_DIR = Path.home() / ".macbot" / "sessions"
MAX_SESSIONS = 50


def _ensure_dir() -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def _session_path(session_id: str) -> Path:
    return SESSIONS_DIR / f"{session_id}.json"


def _load_session_file(path: Path) -> dict[str, Any] | None:
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


# ---- Session creation / writing ----

def create_session() -> str:
    """Create a new session and return its ID."""
    _ensure_dir()
    session_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    data = {
        "id": session_id,
        "created": datetime.now().isoformat(),
        "title": "",
        "messages": [],
    }
    with open(_session_path(session_id), "w") as f:
        json.dump(data, f, indent=2)
    _prune_old_sessions()
    return session_id


def append(session_id: str, role: str, text: str) -> None:
    """Append a message to a session."""
    path = _session_path(session_id)
    data = _load_session_file(path)
    if data is None:
        return
    entry = {
        "ts": datetime.now().isoformat(),
        "role": role,
        "text": text,
    }
    data["messages"].append(entry)
    # Auto-title from first user message
    if not data["title"] and role == "user":
        data["title"] = text[:80]
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# ---- Session listing / loading ----

def list_sessions() -> list[dict[str, Any]]:
    """List all sessions, newest first.

    Returns list of {id, created, title, message_count, preview}.
    """
    _ensure_dir()
    sessions: list[dict[str, Any]] = []
    for path in sorted(SESSIONS_DIR.glob("*.json"), reverse=True):
        data = _load_session_file(path)
        if data is None:
            continue
        msgs = data.get("messages", [])
        # Preview: last assistant message or last user message
        preview = ""
        for m in reversed(msgs):
            if m.get("role") in ("user", "assistant"):
                preview = m.get("text", "")[:100]
                break
        sessions.append({
            "id": data.get("id", path.stem),
            "created": data.get("created", ""),
            "title": data.get("title", ""),
            "message_count": len(msgs),
            "preview": preview,
        })
    return sessions


def load_session(session_id: str) -> list[dict[str, Any]]:
    """Load messages from a session. Returns list of {ts, role, text}."""
    path = _session_path(session_id)
    data = _load_session_file(path)
    if data is None:
        return []
    return data.get("messages", [])


def delete_session(session_id: str) -> bool:
    """Delete a session. Returns True if deleted."""
    path = _session_path(session_id)
    if path.exists():
        path.unlink()
        return True
    return False


def _prune_old_sessions() -> None:
    """Remove oldest sessions if we exceed MAX_SESSIONS."""
    files = sorted(SESSIONS_DIR.glob("*.json"))
    while len(files) > MAX_SESSIONS:
        files[0].unlink()
        files.pop(0)
