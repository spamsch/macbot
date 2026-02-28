"""Task: Heartbeat

Read or update the heartbeat prompt file (~/.macbot/heartbeat.md).
"""

import logging
import os
from pathlib import Path

from macbot.tasks.base import Task
from macbot.tasks.registry import task_registry

logger = logging.getLogger(__name__)

HEARTBEAT_PATH = Path("~/.macbot/heartbeat.md").expanduser()


class HeartbeatTask(Task):
    """Read or update the heartbeat prompt.

    The heartbeat file is a markdown prompt that runs periodically
    via the background service.

    Example:
        task = HeartbeatTask()
        # Read current heartbeat
        result = await task.execute()

        # Update heartbeat
        result = await task.execute(content="Check Mail for urgent messages")
    """

    @property
    def name(self) -> str:
        return "heartbeat"

    @property
    def description(self) -> str:
        return (
            "Read or update the heartbeat prompt (~/.macbot/heartbeat.md). "
            "Call without content to read the current heartbeat. "
            "Provide content to replace it."
        )

    async def execute(self, content: str | None = None) -> str:
        """Read or update the heartbeat file.

        Args:
            content: New heartbeat content to write. If omitted, reads current content.

        Returns:
            The current (or newly written) heartbeat content.
        """
        if content is not None:
            HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
            HEARTBEAT_PATH.write_text(content)
            logger.info("Heartbeat updated: %s", HEARTBEAT_PATH)
            return f"Heartbeat updated.\n\n{content}"

        if not HEARTBEAT_PATH.exists():
            return ""

        return HEARTBEAT_PATH.read_text()


# Auto-register on import
task_registry.register(HeartbeatTask())
