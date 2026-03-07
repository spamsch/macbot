"""Tasks: Channel Management

Provides tasks for the agent to send messages to other channels
and list available channels.
"""

from __future__ import annotations

from typing import Any

from macbot.tasks.base import Task


class SendToChannelTask(Task):
    """Send a message to another channel."""

    def __init__(self, channel_registry: Any = None) -> None:
        self._registry = channel_registry

    @property
    def name(self) -> str:
        return "send_to_channel"

    @property
    def description(self) -> str:
        return (
            "Send a message or result to a different channel. Channels are isolated "
            "conversation contexts (like tmux windows). Built-in channels: 'main' "
            "(interactive), 'tasks' (cron jobs), 'heartbeat' (periodic check-ins), "
            "plus Telegram and custom channels. The message will be submitted to the "
            "target channel's agent for processing."
        )

    async def execute(
        self, channel_id: str, message: str
    ) -> dict[str, Any]:
        """Send a message to another channel.

        Args:
            channel_id: Target channel ID (e.g. 'main', 'tasks', 'heartbeat', 'custom:research')
            message: The message to send to the target channel

        Returns:
            Dictionary with result status
        """
        if self._registry is None:
            return {"success": False, "error": "Channel system not available"}

        ch = self._registry.get(channel_id)
        if ch is None:
            available = [c.id for c in self._registry.list_channels()]
            return {
                "success": False,
                "error": f"Channel '{channel_id}' not found. Available: {', '.join(available)}",
            }

        try:
            result = await self._registry.submit(channel_id, message)
        except Exception as e:
            return {"success": False, "error": str(e)}

        return {
            "success": True,
            "channel": channel_id,
            "output": result,
        }


class ListChannelsTask(Task):
    """List all available channels."""

    def __init__(self, channel_registry: Any = None) -> None:
        self._registry = channel_registry

    @property
    def name(self) -> str:
        return "list_channels"

    @property
    def description(self) -> str:
        return (
            "List all available channels. Channels are isolated conversation contexts, "
            "each with their own agent and history. Use this to see what channels exist "
            "before sending messages to them with send_to_channel."
        )

    async def execute(self) -> dict[str, Any]:
        """List all channels.

        Returns:
            Dictionary with channel list
        """
        if self._registry is None:
            return {"success": False, "error": "Channel system not available"}

        channels = []
        for ch in self._registry.list_channels():
            channels.append({
                "id": ch.id,
                "name": ch.name,
                "kind": ch.kind.value,
                "messages": len(ch.agent.messages),
                "active": ch.id == self._registry.active_id,
            })

        return {"success": True, "channels": channels}


def register_channel_tasks(registry: Any, channel_registry: Any = None) -> None:
    """Register channel management tasks.

    Args:
        registry: TaskRegistry to register tasks with
        channel_registry: ChannelRegistry instance (can be set later)
    """
    registry.register(SendToChannelTask(channel_registry))
    registry.register(ListChannelsTask(channel_registry))
