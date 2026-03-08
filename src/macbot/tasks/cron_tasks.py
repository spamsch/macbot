"""Tasks: Scheduled Task Management

Provides tools for the agent to create, list, update, delete, and run
scheduled (cron) tasks. Uses the existing CronService infrastructure.
"""

from typing import Any

from macbot.config import settings
from macbot.cron.schedule import (
    get_cron_description,
    validate_cron_expression,
)
from macbot.cron.service import CronService
from macbot.cron.types import (
    CronJobCreate,
    CronJobUpdate,
    CronPayload,
    CronSchedule,
    ScheduleKind,
)
from macbot.tasks.base import Task

# Singleton cron service instance
_cron_service: CronService | None = None


def get_cron_service() -> CronService:
    """Get the shared cron service instance."""
    global _cron_service
    if _cron_service is None:
        _cron_service = CronService(
            storage_path=settings.get_cron_storage_path()
        )
    return _cron_service


def _job_summary(job: Any) -> dict[str, Any]:
    """Build a summary dict for a cron job."""
    schedule = job.schedule
    if schedule.kind == ScheduleKind.CRON and schedule.cron_expr:
        schedule_desc = get_cron_description(schedule.cron_expr)
        schedule_expr = schedule.cron_expr
    elif schedule.kind == ScheduleKind.EVERY and schedule.every_ms:
        mins = schedule.every_ms / 60_000
        schedule_desc = f"every {mins:.0f} minutes" if mins >= 1 else f"every {schedule.every_ms / 1000:.0f} seconds"
        schedule_expr = f"{schedule.every_ms}ms"
    elif schedule.kind == ScheduleKind.AT and schedule.at_ms:
        from datetime import datetime, timezone
        at_dt = datetime.fromtimestamp(schedule.at_ms / 1000, tz=timezone.utc)
        schedule_desc = f"once at {at_dt.isoformat()}"
        schedule_expr = str(schedule.at_ms)
    else:
        schedule_desc = "unknown"
        schedule_expr = ""

    return {
        "id": job.id,
        "name": job.name,
        "description": job.description,
        "enabled": job.enabled,
        "schedule_kind": schedule.kind.value,
        "schedule_description": schedule_desc,
        "schedule_expression": schedule_expr,
        "timezone": schedule.timezone,
        "message": job.payload.message,
        "next_run_at": job.state.next_run_at.isoformat() if job.state.next_run_at else None,
        "last_run_at": job.state.last_run_at.isoformat() if job.state.last_run_at else None,
        "run_count": job.state.run_count,
    }


class ScheduleTaskTask(Task):
    """Create a new scheduled task."""

    @property
    def name(self) -> str:
        return "schedule_task"

    @property
    def description(self) -> str:
        return (
            "Create a new scheduled task that runs automatically. "
            "Provide exactly ONE schedule type: cron_expression (e.g. '0 9 * * 1' for Mondays at 9am), "
            "at_time (ISO datetime for one-shot), or interval_minutes (recurring interval). "
            "The message is the goal/instruction the agent will execute each time."
        )

    async def execute(
        self,
        name: str,
        message: str,
        cron_expression: str | None = None,
        at_time: str | None = None,
        interval_minutes: int | None = None,
        timezone: str = "Europe/Berlin",
        description: str | None = None,
    ) -> dict[str, Any]:
        """Create a scheduled task.

        Args:
            name: Human-readable name for the task
            message: The goal/instruction the agent will execute
            cron_expression: Cron expression (e.g. '0 9 * * *' for daily at 9am)
            at_time: ISO datetime for one-shot execution (e.g. '2025-01-15T14:00:00')
            interval_minutes: Recurring interval in minutes
            timezone: Timezone for cron expressions (default: Europe/Berlin)
            description: Optional description of what this task does

        Returns:
            Dictionary with the created job details
        """
        # Validate exactly one schedule type
        schedule_count = sum(1 for s in [cron_expression, at_time, interval_minutes] if s is not None)
        if schedule_count == 0:
            return {
                "success": False,
                "error": "Must provide exactly one schedule type: cron_expression, at_time, or interval_minutes",
            }
        if schedule_count > 1:
            return {
                "success": False,
                "error": "Provide only ONE schedule type, not multiple",
            }

        # Build schedule
        if cron_expression:
            if not validate_cron_expression(cron_expression):
                return {
                    "success": False,
                    "error": f"Invalid cron expression: {cron_expression}",
                }
            schedule = CronSchedule(
                kind=ScheduleKind.CRON,
                cron_expr=cron_expression,
                timezone=timezone,
            )
        elif at_time:
            from datetime import datetime, timezone as tz
            try:
                dt = datetime.fromisoformat(at_time)
                if dt.tzinfo is None:
                    from zoneinfo import ZoneInfo
                    dt = dt.replace(tzinfo=ZoneInfo(timezone))
                at_ms = int(dt.timestamp() * 1000)
            except (ValueError, KeyError) as e:
                return {
                    "success": False,
                    "error": f"Invalid at_time format: {e}",
                }
            schedule = CronSchedule(kind=ScheduleKind.AT, at_ms=at_ms)
        else:
            assert interval_minutes is not None
            schedule = CronSchedule(
                kind=ScheduleKind.EVERY,
                every_ms=int(interval_minutes) * 60_000,
            )

        service = get_cron_service()
        job = service.create_job(CronJobCreate(
            name=name,
            description=description,
            schedule=schedule,
            payload=CronPayload(kind="agent_turn", message=message),
        ))

        result = _job_summary(job)
        result["success"] = True
        result["message_info"] = f"Scheduled task '{name}' created successfully"
        return result


class ListScheduledTasksTask(Task):
    """List all scheduled tasks."""

    @property
    def name(self) -> str:
        return "list_scheduled_tasks"

    @property
    def description(self) -> str:
        return (
            "List all scheduled tasks. Shows each task's name, schedule, "
            "enabled status, next run time, and run count."
        )

    async def execute(
        self,
        enabled_only: bool = False,
    ) -> dict[str, Any]:
        """List scheduled tasks.

        Args:
            enabled_only: If true, only show enabled tasks

        Returns:
            Dictionary with list of scheduled tasks
        """
        service = get_cron_service()
        jobs = service.list_jobs()

        if enabled_only:
            jobs = [j for j in jobs if j.enabled]

        return {
            "success": True,
            "count": len(jobs),
            "jobs": [_job_summary(j) for j in jobs],
        }


class DeleteScheduledTaskTask(Task):
    """Delete a scheduled task."""

    @property
    def name(self) -> str:
        return "delete_scheduled_task"

    @property
    def description(self) -> str:
        return (
            "Delete a scheduled task by its job ID. "
            "Use list_scheduled_tasks first to find the job ID."
        )

    async def execute(self, job_id: str) -> dict[str, Any]:
        """Delete a scheduled task.

        Args:
            job_id: The ID of the job to delete

        Returns:
            Dictionary with result
        """
        service = get_cron_service()
        job = service.get_job(job_id)
        if job is None:
            return {
                "success": False,
                "error": f"No scheduled task found with ID: {job_id}",
            }

        job_name = job.name
        deleted = service.delete_job(job_id)
        return {
            "success": deleted,
            "job_id": job_id,
            "name": job_name,
            "message": f"Deleted scheduled task '{job_name}'" if deleted else "Failed to delete",
        }


class UpdateScheduledTaskTask(Task):
    """Update a scheduled task."""

    @property
    def name(self) -> str:
        return "update_scheduled_task"

    @property
    def description(self) -> str:
        return (
            "Update a scheduled task. Can change its name, message, schedule, "
            "or enable/disable it. Use list_scheduled_tasks first to find the job ID."
        )

    async def execute(
        self,
        job_id: str,
        name: str | None = None,
        message: str | None = None,
        cron_expression: str | None = None,
        enabled: bool | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Update a scheduled task.

        Args:
            job_id: The ID of the job to update
            name: New name for the task
            message: New message/goal for the task
            cron_expression: New cron expression
            enabled: Enable or disable the task
            description: New description

        Returns:
            Dictionary with updated job details
        """
        service = get_cron_service()
        job = service.get_job(job_id)
        if job is None:
            return {
                "success": False,
                "error": f"No scheduled task found with ID: {job_id}",
            }

        # Build update
        schedule = None
        if cron_expression is not None:
            if not validate_cron_expression(cron_expression):
                return {
                    "success": False,
                    "error": f"Invalid cron expression: {cron_expression}",
                }
            schedule = CronSchedule(
                kind=ScheduleKind.CRON,
                cron_expr=cron_expression,
                timezone=job.schedule.timezone,
            )

        payload = None
        if message is not None:
            payload = CronPayload(kind="agent_turn", message=message)

        update = CronJobUpdate(
            name=name,
            description=description,
            schedule=schedule,
            payload=payload,
            enabled=enabled,
        )

        updated = service.update_job(job_id, update)
        if updated is None:
            return {"success": False, "error": "Failed to update task"}

        result = _job_summary(updated)
        result["success"] = True
        result["message_info"] = f"Updated scheduled task '{updated.name}'"
        return result


class RunScheduledTaskTask(Task):
    """Get a scheduled task's message for inline execution."""

    @property
    def name(self) -> str:
        return "run_scheduled_task"

    @property
    def description(self) -> str:
        return (
            "Run a scheduled task NOW by retrieving its goal. "
            "IMPORTANT: After calling this tool, you MUST immediately execute "
            "the returned goal/instruction as if the user had typed it. "
            "Do NOT just report what the task does — actually carry it out."
        )

    async def execute(self, job_id: str) -> dict[str, Any]:
        """Get the task's message for immediate execution.

        Args:
            job_id: The ID of the job to run

        Returns:
            Dictionary with the task's goal that must be executed
        """
        service = get_cron_service()
        job = service.get_job(job_id)
        if job is None:
            return {
                "success": False,
                "error": f"No scheduled task found with ID: {job_id}",
            }

        return {
            "success": True,
            "job_id": job.id,
            "name": job.name,
            "action_required": (
                f"YOU MUST NOW EXECUTE THIS GOAL: {job.payload.message}"
            ),
        }


def register_cron_tasks(registry: Any) -> None:
    """Register all cron tasks with a registry.

    Args:
        registry: TaskRegistry to register tasks with.
    """
    registry.register(ScheduleTaskTask())
    registry.register(ListScheduledTasksTask())
    registry.register(DeleteScheduledTaskTask())
    registry.register(UpdateScheduledTaskTask())
    registry.register(RunScheduledTaskTask())
