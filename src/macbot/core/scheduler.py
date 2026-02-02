"""Task scheduler for running the agent at regular intervals."""

import asyncio
import logging
from datetime import datetime
from typing import Any, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from rich.console import Console

from macbot.config import Settings, settings
from macbot.core.agent import Agent
from macbot.core.task import TaskRegistry

logger = logging.getLogger(__name__)
console = Console()


class ScheduledJob:
    """Configuration for a scheduled job."""

    def __init__(
        self,
        name: str,
        goal: str | None = None,
        task_name: str | None = None,
        task_kwargs: dict[str, Any] | None = None,
        interval_seconds: int | None = None,
        cron: str | None = None,
    ) -> None:
        """Initialize a scheduled job.

        Either goal (for LLM-driven execution) or task_name (for direct execution)
        must be provided.

        Args:
            name: Unique identifier for this job
            goal: Goal for the agent to achieve (LLM-driven)
            task_name: Specific task to execute (direct execution)
            task_kwargs: Arguments for the task
            interval_seconds: Run every N seconds
            cron: Cron expression for scheduling (e.g., "0 * * * *" for hourly)
        """
        if not goal and not task_name:
            raise ValueError("Either 'goal' or 'task_name' must be provided")

        self.name = name
        self.goal = goal
        self.task_name = task_name
        self.task_kwargs = task_kwargs or {}
        self.interval_seconds = interval_seconds
        self.cron = cron


class TaskScheduler:
    """Scheduler for running agent tasks at regular intervals.

    The scheduler can run tasks in two modes:
    1. LLM-driven: Give the agent a goal to achieve
    2. Direct: Execute a specific task without LLM involvement
    """

    def __init__(
        self,
        task_registry: TaskRegistry,
        config: Settings | None = None,
    ) -> None:
        """Initialize the scheduler.

        Args:
            task_registry: Registry of available tasks
            config: Application settings
        """
        self.config = config or settings
        self.task_registry = task_registry
        self.scheduler = AsyncIOScheduler()
        self.jobs: dict[str, ScheduledJob] = {}
        self._agent: Agent | None = None

    def _get_agent(self) -> Agent:
        """Get or create the agent instance."""
        if self._agent is None:
            self._agent = Agent(self.task_registry, config=self.config)
        return self._agent

    def add_job(self, job: ScheduledJob) -> None:
        """Add a scheduled job.

        Args:
            job: Job configuration
        """
        if job.name in self.jobs:
            raise ValueError(f"Job '{job.name}' already exists")

        self.jobs[job.name] = job

        # Create the trigger
        if job.cron:
            trigger = CronTrigger.from_crontab(job.cron)
        elif job.interval_seconds:
            trigger = IntervalTrigger(seconds=job.interval_seconds)
        else:
            trigger = IntervalTrigger(seconds=self.config.default_interval_seconds)

        # Create the job function
        if job.goal:
            # LLM-driven execution
            async def run_goal(goal: str = job.goal) -> None:
                await self._run_agent_goal(job.name, goal)

            self.scheduler.add_job(
                run_goal,
                trigger=trigger,
                id=job.name,
                name=job.name,
            )
        else:
            # Direct task execution
            async def run_task(
                task_name: str = job.task_name or "",
                kwargs: dict[str, Any] = job.task_kwargs,
            ) -> None:
                await self._run_direct_task(job.name, task_name, kwargs)

            self.scheduler.add_job(
                run_task,
                trigger=trigger,
                id=job.name,
                name=job.name,
            )

        logger.info(f"Added job '{job.name}'")

    def remove_job(self, name: str) -> None:
        """Remove a scheduled job."""
        if name in self.jobs:
            self.scheduler.remove_job(name)
            del self.jobs[name]
            logger.info(f"Removed job '{name}'")

    async def _run_agent_goal(self, job_name: str, goal: str) -> None:
        """Run the agent to achieve a goal."""
        console.print(f"\n[bold blue]Running job:[/bold blue] {job_name}")
        console.print(f"[dim]Time: {datetime.now().isoformat()}[/dim]")

        try:
            agent = self._get_agent()
            agent.reset()
            result = await agent.run(goal, verbose=True)
            console.print(f"[green]Completed:[/green] {result[:200]}...")
        except Exception as e:
            logger.exception(f"Job '{job_name}' failed")
            console.print(f"[red]Error:[/red] {e}")

    async def _run_direct_task(
        self, job_name: str, task_name: str, kwargs: dict[str, Any]
    ) -> None:
        """Run a task directly without LLM involvement."""
        console.print(f"\n[bold blue]Running job:[/bold blue] {job_name}")
        console.print(f"[dim]Time: {datetime.now().isoformat()}[/dim]")

        try:
            agent = self._get_agent()
            result = await agent.run_single_task(task_name, verbose=True, **kwargs)

            if result.success:
                console.print(f"[green]Success:[/green] {result.output}")
            else:
                console.print(f"[red]Failed:[/red] {result.error}")
        except Exception as e:
            logger.exception(f"Job '{job_name}' failed")
            console.print(f"[red]Error:[/red] {e}")

    def start(self) -> None:
        """Start the scheduler."""
        console.print("[bold green]Starting scheduler...[/bold green]")
        console.print(f"[dim]Registered jobs: {list(self.jobs.keys())}[/dim]")
        self.scheduler.start()

    def stop(self) -> None:
        """Stop the scheduler."""
        console.print("[bold yellow]Stopping scheduler...[/bold yellow]")
        self.scheduler.shutdown()

    async def run_forever(self) -> None:
        """Run the scheduler until interrupted."""
        self.start()
        try:
            # Keep the event loop running
            while True:
                await asyncio.sleep(1)
        except (KeyboardInterrupt, asyncio.CancelledError):
            self.stop()

    def run_job_now(self, name: str) -> None:
        """Trigger a job to run immediately."""
        if name not in self.jobs:
            raise ValueError(f"Job '{name}' not found")
        self.scheduler.modify_job(name, next_run_time=datetime.now())
