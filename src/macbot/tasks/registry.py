"""Task registry for managing available tasks.

The registry maintains a collection of tasks that can be used by the agent.
Tasks can be registered by class, instance, or function.
"""

import logging
from typing import Any, Callable, TypeVar

from macbot.tasks.base import FunctionTask, Task, TaskDefinition, TaskResult

logger = logging.getLogger(__name__)

T = TypeVar("T")


class TaskRegistry:
    """Registry for managing available tasks.

    The registry maintains a collection of tasks that can be used by the agent.
    Tasks can be registered by class, instance, or function.

    Example:
        registry = TaskRegistry()

        # Register a task instance
        registry.register(MyTask())

        # Register a function
        @registry.task(description="Add numbers")
        def add(a: int, b: int) -> int:
            return a + b

        # Execute a task
        result = await registry.execute("add", a=1, b=2)
    """

    def __init__(self) -> None:
        """Initialize an empty task registry."""
        self._tasks: dict[str, Task] = {}

    def register(self, task: Task) -> None:
        """Register a task instance.

        Args:
            task: The task to register.

        Raises:
            ValueError: If a task with the same name is already registered.
        """
        if task.name in self._tasks:
            raise ValueError(f"Task '{task.name}' is already registered")
        self._tasks[task.name] = task
        logger.debug(f"Registered task: {task.name}")

    def register_function(
        self,
        func: Callable[..., Any],
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        """Register a function as a task.

        Args:
            func: The function to register.
            name: Task name (defaults to function name).
            description: Task description (defaults to function docstring).
        """
        task = FunctionTask(func, name, description)
        self.register(task)

    def task(
        self, name: str | None = None, description: str | None = None
    ) -> Callable[[Callable[..., T]], Callable[..., T]]:
        """Decorator to register a function as a task.

        Usage:
            registry = TaskRegistry()

            @registry.task(description="Add two numbers")
            def add(a: int, b: int) -> int:
                return a + b

        Args:
            name: Task name (defaults to function name).
            description: Task description (defaults to function docstring).

        Returns:
            Decorator function.
        """

        def decorator(func: Callable[..., T]) -> Callable[..., T]:
            self.register_function(func, name, description)
            return func

        return decorator

    def unregister(self, name: str) -> bool:
        """Unregister a task by name.

        Args:
            name: Name of the task to unregister.

        Returns:
            True if the task was unregistered, False if not found.
        """
        if name in self._tasks:
            del self._tasks[name]
            logger.debug(f"Unregistered task: {name}")
            return True
        return False

    def get(self, name: str) -> Task | None:
        """Get a task by name.

        Args:
            name: Name of the task.

        Returns:
            The task, or None if not found.
        """
        return self._tasks.get(name)

    def has(self, name: str) -> bool:
        """Check if a task is registered.

        Args:
            name: Name of the task.

        Returns:
            True if the task exists.
        """
        return name in self._tasks

    def list_tasks(self) -> list[Task]:
        """Get all registered tasks.

        Returns:
            List of all registered tasks.
        """
        return list(self._tasks.values())

    def list_names(self) -> list[str]:
        """Get names of all registered tasks.

        Returns:
            List of task names.
        """
        return list(self._tasks.keys())

    def get_definitions(self) -> list[TaskDefinition]:
        """Get definitions for all tasks (for LLM context).

        Returns:
            List of TaskDefinition objects.
        """
        return [task.to_definition() for task in self._tasks.values()]

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        """Get tool schemas for all tasks (for LLM APIs).

        Returns:
            List of tool schema dictionaries.
        """
        return [task.to_tool_schema() for task in self._tasks.values()]

    async def execute(self, name: str, **kwargs: Any) -> TaskResult:
        """Execute a task by name.

        Args:
            name: Name of the task to execute.
            **kwargs: Arguments to pass to the task.

        Returns:
            TaskResult with success status and output or error.
        """
        task = self.get(name)
        if task is None:
            return TaskResult(success=False, error=f"Task '{name}' not found")

        try:
            output = await task.execute(**kwargs)
            return TaskResult(success=True, output=output)
        except Exception as e:
            logger.exception(f"Error executing task '{name}'")
            return TaskResult(success=False, error=str(e))

    def __len__(self) -> int:
        """Get the number of registered tasks."""
        return len(self._tasks)

    def __contains__(self, name: str) -> bool:
        """Check if a task is registered."""
        return name in self._tasks

    def __iter__(self):
        """Iterate over registered tasks."""
        return iter(self._tasks.values())


# Global task registry instance
task_registry = TaskRegistry()
