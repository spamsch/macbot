"""Task: Time Utilities

Time-related utility tasks.
"""

from datetime import datetime

from macbot.tasks.base import Task
from macbot.tasks.registry import task_registry


class GetCurrentTimeTask(Task):
    """Get the current date and time.

    Example:
        task = GetCurrentTimeTask()
        result = await task.execute()
        # Returns: "2024-01-30T12:00:00.000000"
    """

    @property
    def name(self) -> str:
        """Get the task name."""
        return "get_current_time"

    @property
    def description(self) -> str:
        """Get the task description."""
        return "Get the current date and time."

    async def execute(self) -> str:
        """Get the current timestamp.

        Returns:
            Current time as ISO format string.
        """
        return datetime.now().isoformat()


class EchoTask(Task):
    """Echo back a message.

    Simple task for testing that returns the input message.

    Example:
        task = EchoTask()
        result = await task.execute(message="Hello!")
        # Returns: "Echo: Hello!"
    """

    @property
    def name(self) -> str:
        """Get the task name."""
        return "echo"

    @property
    def description(self) -> str:
        """Get the task description."""
        return "Echo back the provided message."

    async def execute(self, message: str) -> str:
        """Echo a message back.

        Args:
            message: Message to echo.

        Returns:
            Echoed message with prefix.
        """
        return f"Echo: {message}"


# Auto-register on import
task_registry.register(GetCurrentTimeTask())
task_registry.register(EchoTask())
