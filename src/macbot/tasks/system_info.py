"""Task: Get System Information

Provides information about the current system including hostname,
operating system, architecture, and Python version.
"""

import platform
from datetime import datetime
from typing import Any

from macbot.tasks.base import Task
from macbot.tasks.registry import task_registry


class GetSystemInfoTask(Task):
    """Get information about the current system.

    Returns system details including hostname, OS, architecture,
    Python version, and current timestamp.

    Example:
        task = GetSystemInfoTask()
        result = await task.execute()
        # Returns: {"hostname": "...", "os": "...", ...}
    """

    @property
    def name(self) -> str:
        """Get the task name."""
        return "get_system_info"

    @property
    def description(self) -> str:
        """Get the task description."""
        return "Get information about the current system including hostname, OS, and current time."

    async def execute(self) -> dict[str, Any]:
        """Execute the system info task.

        Returns:
            Dictionary containing system information:
            - hostname: System hostname
            - os: Operating system name
            - os_version: OS version string
            - architecture: CPU architecture
            - python_version: Python version string
            - current_time: Current ISO timestamp
        """
        return {
            "hostname": platform.node(),
            "os": platform.system(),
            "os_version": platform.version(),
            "architecture": platform.machine(),
            "python_version": platform.python_version(),
            "current_time": datetime.now().isoformat(),
        }


# Auto-register on import
task_registry.register(GetSystemInfoTask())
