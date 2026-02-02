"""Built-in tasks for the agent.

This module provides the task system including base classes, registry,
and all built-in task implementations.

Example:
    from macbot.tasks import task_registry, Task

    # Get all registered tasks
    tasks = task_registry.list_tasks()

    # Execute a task
    result = await task_registry.execute("get_system_info")

    # Create a custom task
    class MyTask(Task):
        name = "my_task"
        description = "Does something"

        async def execute(self) -> str:
            return "done"

    task_registry.register(MyTask())
"""

# Base classes and types
from macbot.tasks.base import (
    FunctionTask,
    Task,
    TaskDefinition,
    TaskParameter,
    TaskResult,
)

# Registry
from macbot.tasks.registry import TaskRegistry, task_registry

# Import all task modules to trigger auto-registration
from macbot.tasks import (
    calculator,
    fetch_url,
    file_read,
    file_write,
    macos_automation,
    shell_command,
    system_info,
    time_utils,
)

__all__ = [
    # Base classes
    "Task",
    "FunctionTask",
    "TaskParameter",
    "TaskDefinition",
    "TaskResult",
    # Registry
    "TaskRegistry",
    "task_registry",
    # Task modules (for explicit imports if needed)
    "calculator",
    "fetch_url",
    "file_read",
    "file_write",
    "macos_automation",
    "shell_command",
    "system_info",
    "time_utils",
]


def create_default_registry() -> TaskRegistry:
    """Create a new task registry with all default tasks registered.

    This creates a fresh registry instance with all built-in tasks.
    Useful when you need an isolated registry.

    Returns:
        TaskRegistry with all default tasks.
    """
    registry = TaskRegistry()

    # Import and register all built-in task classes
    from macbot.tasks.calculator import CalculatorTask
    from macbot.tasks.fetch_url import FetchURLTask
    from macbot.tasks.file_read import ReadFileTask
    from macbot.tasks.file_write import WriteFileTask
    from macbot.tasks.macos_automation import register_macos_tasks
    from macbot.tasks.shell_command import RunShellCommandTask
    from macbot.tasks.system_info import GetSystemInfoTask
    from macbot.tasks.time_utils import EchoTask, GetCurrentTimeTask

    registry.register(GetSystemInfoTask())
    registry.register(RunShellCommandTask())
    registry.register(FetchURLTask())
    registry.register(ReadFileTask())
    registry.register(WriteFileTask())
    registry.register(CalculatorTask())
    registry.register(GetCurrentTimeTask())
    registry.register(EchoTask())

    # Register macOS automation tasks (Mail, Calendar, Reminders, Notes, Safari)
    register_macos_tasks(registry)

    return registry
