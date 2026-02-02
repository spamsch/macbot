"""MacBot - A modular agent loop with scheduled LLM-powered tasks."""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("macbot")
except PackageNotFoundError:
    __version__ = "0.0.0-dev"

from macbot.core.agent import Agent
from macbot.core.scheduler import TaskScheduler
from macbot.core.task import Task, TaskRegistry

__all__ = ["Agent", "TaskScheduler", "Task", "TaskRegistry"]
