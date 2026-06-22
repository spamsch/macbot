"""Cron service for managing and executing scheduled jobs.

This module provides the main CronService class that orchestrates
job scheduling, execution, and persistence.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Awaitable

from macbot.cron.executor import CronExecutor, ExecutionResult, default_executor
from macbot.cron.schedule import compute_next_run
from macbot.cron.storage import CronStorage
from macbot.cron.types import (
    CronJob,
    CronJobCreate,
    CronJobState,
    CronJobUpdate,
    CronPayload,
    CronSchedule,
    ScheduleKind,
)

logger = logging.getLogger(__name__)

# Default storage path
DEFAULT_STORAGE_PATH = Path.home() / ".macbot" / "cron.json"


class CronService:
    """Service for managing cron jobs.

    The CronService handles:
    - Job creation, modification, and deletion
    - Scheduling and next-run computation
    - Periodic execution of due jobs
    - Persistence to JSON storage

    Example:
        service = CronService()

        # Create a job
        job = service.create_job(CronJobCreate(
            name="Daily reminder",
            schedule=CronSchedule(kind=ScheduleKind.CRON, cron_expr="0 9 * * *"),
            payload=CronPayload(message="Good morning!"),
        ))

        # Start the service
        await service.start()
    """

    def __init__(
        self,
        storage_path: str | Path | None = None,
        executor: CronExecutor | None = None,
        check_interval: float = 1.0,
    ) -> None:
        """Initialize the cron service.

        Args:
            storage_path: Path to the JSON storage file.
            executor: Custom executor for job payloads.
            check_interval: Seconds between job checks.
        """
        self._storage = CronStorage(storage_path or DEFAULT_STORAGE_PATH)
        self._executor = executor or default_executor
        self._check_interval = check_interval

        self._running = False
        self._task: asyncio.Task | None = None
        self._jobs: dict[str, CronJob] = {}

        # Load jobs from storage
        self._load_jobs()

    @property
    def storage_path(self) -> Path:
        """Get the storage file path."""
        return self._storage.path

    @property
    def is_running(self) -> bool:
        """Check if the service is running."""
        return self._running

    def _load_jobs(self) -> None:
        """Load jobs from storage into memory."""
        jobs = self._storage.load()
        self._jobs = {job.id: job for job in jobs}
        logger.info(f"Loaded {len(self._jobs)} cron jobs")

    def _save_jobs(self) -> None:
        """Save all jobs to storage."""
        self._storage.save(list(self._jobs.values()))

    def _generate_id(self) -> str:
        """Generate a unique job ID.

        Returns:
            Unique job identifier.
        """
        return f"job_{uuid.uuid4().hex[:12]}"

    def create_job(self, create: CronJobCreate) -> CronJob:
        """Create a new cron job.

        Args:
            create: Job creation parameters.

        Returns:
            The created job.
        """
        job_id = self._generate_id()
        now = datetime.now(timezone.utc)

        job = CronJob(
            id=job_id,
            name=create.name,
            description=create.description,
            enabled=create.enabled,
            schedule=create.schedule,
            payload=create.payload,
            state=CronJobState(),
            created_at=now,
            updated_at=now,
        )

        # Compute initial next run
        if job.enabled:
            job.state.next_run_at = compute_next_run(job.schedule)

        self._jobs[job.id] = job
        self._storage.add(job)

        logger.info(f"Created cron job: {job.name} ({job.id})")
        return job

    def get_job(self, job_id: str) -> CronJob | None:
        """Get a job by ID.

        Args:
            job_id: The job ID.

        Returns:
            The job if found.
        """
        return self._jobs.get(job_id)

    def list_jobs(self) -> list[CronJob]:
        """List all jobs.

        Returns:
            List of all jobs.
        """
        return list(self._jobs.values())

    def update_job(self, job_id: str, update: CronJobUpdate) -> CronJob | None:
        """Update a job.

        Args:
            job_id: The job ID.
            update: Update parameters.

        Returns:
            The updated job, or None if not found.
        """
        job = self._jobs.get(job_id)
        if job is None:
            return None

        # Apply updates
        if update.name is not None:
            job.name = update.name
        if update.description is not None:
            job.description = update.description
        if update.schedule is not None:
            job.schedule = update.schedule
            # Recompute next run
            job.state.next_run_at = compute_next_run(
                job.schedule,
                job.state.last_run_at,
            )
        if update.payload is not None:
            job.payload = update.payload
        if update.enabled is not None:
            job.enabled = update.enabled
            if job.enabled and job.state.next_run_at is None:
                job.state.next_run_at = compute_next_run(job.schedule)

        job.updated_at = datetime.now(timezone.utc)
        self._storage.update(job)

        logger.info(f"Updated cron job: {job.name} ({job.id})")
        return job

    def delete_job(self, job_id: str) -> bool:
        """Delete a job.

        Args:
            job_id: The job ID.

        Returns:
            True if the job was deleted.
        """
        if job_id not in self._jobs:
            return False

        job = self._jobs.pop(job_id)
        self._storage.remove(job_id)

        logger.info(f"Deleted cron job: {job.name} ({job_id})")
        return True

    def enable_job(self, job_id: str) -> bool:
        """Enable a job.

        Args:
            job_id: The job ID.

        Returns:
            True if the job was enabled.
        """
        job = self._jobs.get(job_id)
        if job is None:
            return False

        if not job.enabled:
            job.enabled = True
            job.state.next_run_at = compute_next_run(job.schedule)
            job.updated_at = datetime.now(timezone.utc)
            self._storage.update(job)
            logger.info(f"Enabled cron job: {job.name} ({job_id})")

        return True

    def disable_job(self, job_id: str) -> bool:
        """Disable a job.

        Args:
            job_id: The job ID.

        Returns:
            True if the job was disabled.
        """
        job = self._jobs.get(job_id)
        if job is None:
            return False

        if job.enabled:
            job.enabled = False
            job.updated_at = datetime.now(timezone.utc)
            self._storage.update(job)
            logger.info(f"Disabled cron job: {job.name} ({job_id})")

        return True

    async def run_job(self, job_id: str) -> ExecutionResult | None:
        """Run a job immediately.

        Args:
            job_id: The job ID.

        Returns:
            Execution result, or None if job not found.
        """
        job = self._jobs.get(job_id)
        if job is None:
            return None

        return await self._execute_job(job)

    async def _execute_job(self, job: CronJob) -> ExecutionResult:
        """Execute a job and update its state.

        Args:
            job: The job to execute.

        Returns:
            Execution result.
        """
        result = await self._executor.execute(job)

        # Update job state
        now = datetime.now(timezone.utc)
        job.state.last_run_at = now
        job.state.run_count += 1

        if result.success:
            job.state.last_result = str(result.output)[:500]  # Limit result size
            job.state.last_error = None
        else:
            job.state.error_count += 1
            job.state.last_error = result.error

        # Compute next run (if recurring)
        if job.is_one_shot():
            job.enabled = False
            job.state.next_run_at = None
        else:
            job.state.next_run_at = compute_next_run(
                job.schedule,
                job.state.last_run_at,
            )

        job.updated_at = now
        self._storage.update(job)

        return result

    async def _check_and_run_due_jobs(self) -> None:
        """Check for and execute any due jobs."""
        now = datetime.now(timezone.utc)

        for job in list(self._jobs.values()):
            if job.is_due(now):
                try:
                    await self._execute_job(job)
                except Exception as e:
                    logger.exception(f"Error executing job {job.id}: {e}")

    async def _run_loop(self) -> None:
        """Main service loop that checks for due jobs."""
        logger.info("Cron service started")

        while self._running:
            try:
                await self._check_and_run_due_jobs()
            except Exception as e:
                logger.exception(f"Error in cron service loop: {e}")

            await asyncio.sleep(self._check_interval)

        logger.info("Cron service stopped")

    async def start(self) -> None:
        """Start the cron service.

        Begins the background loop that checks for and executes due jobs.
        """
        if self._running:
            logger.warning("Cron service is already running")
            return

        self._running = True
        self._task = asyncio.create_task(
            self._run_loop(),
            name="cron_service_loop",
        )

    async def stop(self) -> None:
        """Stop the cron service.

        Gracefully stops the background loop.
        """
        if not self._running:
            return

        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def set_agent_handler(
        self,
        handler: Callable[[CronPayload], Awaitable[ExecutionResult]],
    ) -> None:
        """Set the handler for agent_turn payloads.

        This allows integrating the cron service with the agent system.

        Args:
            handler: Async function to handle agent turn payloads.
        """
        self._executor.set_handler("agent_turn", handler)

    def set_handler(
        self,
        payload_kind: str,
        handler: Callable[[CronPayload], Awaitable[ExecutionResult]],
    ) -> None:
        """Register a handler for an arbitrary payload kind (e.g. memory_maintenance)."""
        self._executor.set_handler(payload_kind, handler)

    # Convenience methods for quick job creation

    def schedule_at(
        self,
        name: str,
        at_time: datetime,
        message: str,
        **payload_kwargs,
    ) -> CronJob:
        """Schedule a one-shot job at a specific time.

        Args:
            name: Job name.
            at_time: When to execute.
            message: Message to process.
            **payload_kwargs: Additional payload parameters.

        Returns:
            The created job.
        """
        # Convert to milliseconds
        at_ms = int(at_time.timestamp() * 1000)

        return self.create_job(CronJobCreate(
            name=name,
            schedule=CronSchedule(kind=ScheduleKind.AT, at_ms=at_ms),
            payload=CronPayload(message=message, **payload_kwargs),
        ))

    def schedule_every(
        self,
        name: str,
        interval_seconds: int,
        message: str,
        **payload_kwargs,
    ) -> CronJob:
        """Schedule a recurring job at fixed intervals.

        Args:
            name: Job name.
            interval_seconds: Interval between executions.
            message: Message to process.
            **payload_kwargs: Additional payload parameters.

        Returns:
            The created job.
        """
        return self.create_job(CronJobCreate(
            name=name,
            schedule=CronSchedule(
                kind=ScheduleKind.EVERY,
                every_ms=interval_seconds * 1000,
            ),
            payload=CronPayload(message=message, **payload_kwargs),
        ))

    def schedule_cron(
        self,
        name: str,
        cron_expr: str,
        message: str,
        timezone: str = "UTC",
        **payload_kwargs,
    ) -> CronJob:
        """Schedule a job with a cron expression.

        Args:
            name: Job name.
            cron_expr: Cron expression (e.g., "0 9 * * *").
            message: Message to process.
            timezone: Timezone for the cron expression.
            **payload_kwargs: Additional payload parameters.

        Returns:
            The created job.
        """
        return self.create_job(CronJobCreate(
            name=name,
            schedule=CronSchedule(
                kind=ScheduleKind.CRON,
                cron_expr=cron_expr,
                timezone=timezone,
            ),
            payload=CronPayload(message=message, **payload_kwargs),
        ))
