"""Multi-channel agent architecture.

Channels provide isolated conversation contexts, each with its own Agent
instance and message queue.  Built-in channels (main, tasks, heartbeat)
are created automatically; Telegram channels are created per-chat;
custom channels can be created by the user and persist across restarts.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from macbot.core.agent import Agent
from macbot.core.task import TaskRegistry

logger = logging.getLogger(__name__)

CHANNELS_DIR = Path.home() / ".macbot" / "channels"
CHANNELS_REGISTRY_FILE = CHANNELS_DIR / "registry.json"


class ChannelKind(str, Enum):
    MAIN = "main"
    TELEGRAM = "telegram"
    TASKS = "tasks"
    HEARTBEAT = "heartbeat"
    CUSTOM = "custom"


class Channel:
    """An isolated conversation context with its own agent and history."""

    def __init__(
        self,
        id: str,
        name: str,
        kind: ChannelKind,
        agent: Agent,
        created_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.id = id
        self.name = name
        self.kind = kind
        self.agent = agent
        self.created_at = created_at or datetime.now()
        self.metadata: dict[str, Any] = metadata or {}

    @property
    def session_dir(self) -> Path:
        """Directory for this channel's session data."""
        # Sanitise id for filesystem: replace colons with dashes
        safe_id = self.id.replace(":", "-")
        return CHANNELS_DIR / safe_id

    def save_session(self) -> None:
        """Persist the current agent conversation to disk."""
        self.session_dir.mkdir(parents=True, exist_ok=True)
        path = self.session_dir / "session.json"
        messages = [msg.model_dump() for msg in self.agent.messages]
        data = {
            "channel_id": self.id,
            "channel_name": self.name,
            "kind": self.kind.value,
            "saved_at": datetime.now().isoformat(),
            "messages": messages,
        }
        path.write_text(json.dumps(data, indent=2))

    def load_session(self) -> bool:
        """Restore agent conversation from disk.

        Returns:
            True if a session was loaded, False if no saved session exists.
        """
        from macbot.providers.base import Message

        path = self.session_dir / "session.json"
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text())
            self.agent.messages = [
                Message.model_validate(entry) for entry in data.get("messages", [])
            ]
            return True
        except Exception:
            logger.warning(f"Failed to load session for channel {self.id}", exc_info=True)
            return False

    def reset(self) -> None:
        """Clear conversation history for this channel."""
        self.agent.reset()


class ChannelRegistry:
    """Manages named channels with isolated agent instances."""

    def __init__(self, task_registry: TaskRegistry) -> None:
        self._channels: dict[str, Channel] = {}
        self._task_registry = task_registry
        self._active_channel_id: str = "main"

    def _make_agent(self) -> Agent:
        """Create a new Agent instance with the shared task registry."""
        return Agent(self._task_registry)

    def get_or_create(
        self,
        channel_id: str,
        kind: ChannelKind,
        name: str | None = None,
        agent: Agent | None = None,
    ) -> Channel:
        """Get an existing channel or create a new one.

        Args:
            channel_id: Unique channel identifier.
            kind: The channel kind.
            name: Display name (defaults to channel_id).
            agent: Optional pre-existing Agent to use.

        Returns:
            The channel instance.
        """
        if channel_id in self._channels:
            return self._channels[channel_id]

        ch = Channel(
            id=channel_id,
            name=name or channel_id,
            kind=kind,
            agent=agent or self._make_agent(),
        )
        self._channels[channel_id] = ch
        return ch

    def get(self, channel_id: str) -> Channel | None:
        """Get a channel by ID, or None if it doesn't exist."""
        return self._channels.get(channel_id)

    def switch(self, channel_id: str) -> Channel:
        """Switch the active channel.

        Args:
            channel_id: Channel to switch to.

        Returns:
            The now-active channel.

        Raises:
            KeyError: If the channel doesn't exist.
        """
        if channel_id not in self._channels:
            raise KeyError(f"Channel '{channel_id}' does not exist")
        self._active_channel_id = channel_id
        return self._channels[channel_id]

    @property
    def active(self) -> Channel:
        """The currently active channel."""
        return self._channels[self._active_channel_id]

    @property
    def active_id(self) -> str:
        return self._active_channel_id

    def list_channels(self) -> list[Channel]:
        """List all channels, built-in first then custom."""
        order = {
            ChannelKind.MAIN: 0,
            ChannelKind.TASKS: 1,
            ChannelKind.HEARTBEAT: 2,
            ChannelKind.TELEGRAM: 3,
            ChannelKind.CUSTOM: 4,
        }
        return sorted(self._channels.values(), key=lambda c: (order.get(c.kind, 99), c.id))

    def close(self, channel_id: str) -> bool:
        """Close a custom channel.

        Only CUSTOM channels can be closed. Built-in channels are permanent.

        Returns:
            True if the channel was closed, False if not found or not closable.
        """
        ch = self._channels.get(channel_id)
        if ch is None or ch.kind != ChannelKind.CUSTOM:
            return False
        del self._channels[channel_id]
        # Switch away if we closed the active channel
        if self._active_channel_id == channel_id:
            self._active_channel_id = "main"
        self._save_custom_channels()
        return True

    def reload_skills(self) -> None:
        """Reload skills for all channel agents."""
        for ch in self._channels.values():
            ch.agent.skills_registry.reload()

    def save_all_sessions(self) -> None:
        """Persist all channel sessions to disk."""
        for ch in self._channels.values():
            try:
                ch.save_session()
            except Exception:
                logger.warning(f"Failed to save session for channel {ch.id}", exc_info=True)

    def load_all_sessions(self) -> None:
        """Restore all channel sessions from disk."""
        for ch in self._channels.values():
            ch.load_session()

    # ---- Custom channel persistence ----

    def _save_custom_channels(self) -> None:
        """Save custom channel definitions to registry file."""
        CHANNELS_DIR.mkdir(parents=True, exist_ok=True)
        custom = []
        for ch in self._channels.values():
            if ch.kind == ChannelKind.CUSTOM:
                custom.append({
                    "id": ch.id,
                    "name": ch.name,
                    "created_at": ch.created_at.isoformat(),
                    "metadata": ch.metadata,
                })
        CHANNELS_REGISTRY_FILE.write_text(json.dumps(custom, indent=2))

    def load_custom_channels(self) -> None:
        """Load custom channel definitions from registry file."""
        if not CHANNELS_REGISTRY_FILE.exists():
            return
        try:
            entries = json.loads(CHANNELS_REGISTRY_FILE.read_text())
            for entry in entries:
                cid = entry["id"]
                if cid not in self._channels:
                    ch = Channel(
                        id=cid,
                        name=entry.get("name", cid),
                        kind=ChannelKind.CUSTOM,
                        agent=self._make_agent(),
                        created_at=datetime.fromisoformat(entry["created_at"]),
                        metadata=entry.get("metadata", {}),
                    )
                    self._channels[cid] = ch
        except Exception:
            logger.warning("Failed to load custom channels", exc_info=True)

    def create_custom_channel(self, name: str) -> Channel:
        """Create a new custom channel.

        Args:
            name: Display name for the channel.

        Returns:
            The new channel.

        Raises:
            ValueError: If a channel with that name already exists.
        """
        # Derive ID from name
        channel_id = f"custom:{name.lower().replace(' ', '-')}"
        if channel_id in self._channels:
            raise ValueError(f"Channel '{channel_id}' already exists")

        ch = Channel(
            id=channel_id,
            name=name,
            kind=ChannelKind.CUSTOM,
            agent=self._make_agent(),
        )
        self._channels[channel_id] = ch
        self._save_custom_channels()
        return ch
