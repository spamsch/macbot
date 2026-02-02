"""MacBot - A modular agent loop with scheduled LLM-powered tasks."""

__version__ = "0.1.0"

from macbot.core.agent import Agent
from macbot.core.scheduler import TaskScheduler
from macbot.core.task import Task, TaskRegistry

__all__ = ["Agent", "TaskScheduler", "Task", "TaskRegistry"]
