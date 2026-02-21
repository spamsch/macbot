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
    browser_automation,
    calculator,
    fetch_url,
    file_read,
    file_write,
    macos_automation,
    mindwtr,
    pdf_create,
    shell_command,
    system_info,
    teams,
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
    "browser_automation",
    "calculator",
    "fetch_url",
    "file_read",
    "file_write",
    "macos_automation",
    "mindwtr",
    "pdf_create",
    "shell_command",
    "system_info",
    "teams",
    "time_utils",
]


def create_default_registry(config: "Settings | None" = None) -> TaskRegistry:
    """Create a new task registry with all default tasks registered.

    This creates a fresh registry instance with all built-in tasks.
    Useful when you need an isolated registry.

    Args:
        config: Optional settings (subagent task uses this to configure itself).

    Returns:
        TaskRegistry with all default tasks.
    """
    from macbot.config import Settings  # noqa: F811
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

    from macbot.tasks.pdf_create import CreatePDFTask
    registry.register(CreatePDFTask())

    registry.register(CalculatorTask())
    registry.register(GetCurrentTimeTask())
    registry.register(EchoTask())

    # Register macOS automation tasks (Mail, Calendar, Reminders, Notes, Safari)
    register_macos_tasks(registry)

    # Register browser automation tasks (ARIA-based Safari automation)
    from macbot.tasks.browser_automation import register_browser_tasks
    register_browser_tasks(registry)

    # Register agent memory tasks
    from macbot.tasks.memory import register_memory_tasks
    register_memory_tasks(registry)

    # Register Telegram tasks
    from macbot.tasks.telegram import register_telegram_tasks
    register_telegram_tasks(registry)

    # Register Paperless-ngx tasks
    from macbot.tasks.paperless import register_paperless_tasks
    register_paperless_tasks(registry)

    # Register web tasks (simple fetch/search - use instead of browser for quick lookups)
    from macbot.tasks.web import register_web_tasks
    register_web_tasks(registry)

    # Register time tracking tasks
    from macbot.tasks.time_tracking import register_time_tracking_tasks
    register_time_tracking_tasks(registry)

    # Register skill enrichment task
    from macbot.tasks.skill_enrich import register_skill_enrich_tasks
    register_skill_enrich_tasks(registry)

    # Register Microsoft Teams tasks
    from macbot.tasks.teams import register_teams_tasks
    register_teams_tasks(registry)

    # Register Mindwtr GTD tasks (only when data path is configured)
    if config and config.mindwtr_data_path:
        from macbot.tasks.mindwtr import register_mindwtr_tasks
        register_mindwtr_tasks(registry)

    # Register core preferences task
    from macbot.tasks.preferences import register_preferences_tasks
    register_preferences_tasks(registry)

    # Register subagent task (passes registry ref so subagents get scoped copies)
    from macbot.tasks.subagent import RunSubagentTask
    registry.register(RunSubagentTask(config=config, parent_registry=registry))

    return registry
