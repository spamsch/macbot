"""Example tasks demonstrating the modular task system.

DEPRECATED: This module is kept for backwards compatibility.
New code should import from macbot.tasks directly.

Example:
    # New way (preferred)
    from macbot.tasks import create_default_registry, task_registry

    # Old way (still works)
    from macbot.tasks.examples import create_example_registry
"""

import warnings

from macbot.tasks import TaskRegistry, create_default_registry

# Re-export task classes for backwards compatibility
from macbot.tasks.calculator import CalculatorTask
from macbot.tasks.fetch_url import FetchURLTask
from macbot.tasks.file_read import ReadFileTask
from macbot.tasks.file_write import WriteFileTask
from macbot.tasks.shell_command import RunShellCommandTask
from macbot.tasks.system_info import GetSystemInfoTask
from macbot.tasks.time_utils import EchoTask, GetCurrentTimeTask


def register_example_tasks(registry: TaskRegistry) -> None:
    """Register all example tasks with the given registry.

    DEPRECATED: Use create_default_registry() instead.

    Args:
        registry: The registry to register tasks with.
    """
    registry.register(GetSystemInfoTask())
    registry.register(RunShellCommandTask())
    registry.register(FetchURLTask())
    registry.register(WriteFileTask())
    registry.register(ReadFileTask())
    registry.register(CalculatorTask())
    registry.register(GetCurrentTimeTask())
    registry.register(EchoTask())


def create_example_registry() -> TaskRegistry:
    """Create a task registry with example tasks.

    DEPRECATED: Use create_default_registry() from macbot.tasks instead.

    Returns:
        TaskRegistry with all default tasks.
    """
    return create_default_registry()

