"""Type definitions for the cron job system.

This module defines the Pydantic models used for cron job configuration,
scheduling, and state management.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ScheduleKind(str, Enum):
    """Type of schedule for a cron job.

    Attributes:
        AT: One-shot execution at a specific timestamp.
        EVERY: Recurring execution at fixed intervals.
        CRON: Recurring execution based on cron expression.
    """

    AT = "at"
    EVERY = "every"
    CRON = "cron"


class CronSchedule(BaseModel):
    """Schedule configuration for a cron job.

    Exactly one of at_ms, every_ms, or cron_expr should be set,
    corresponding to the schedule kind.

    Attributes:
        kind: Type of schedule (at, every, or cron).
        at_ms: Unix timestamp in milliseconds for one-shot execution.
        every_ms: Interval in milliseconds for recurring execution.
        cron_expr: Cron expression for cron-based scheduling.
        timezone: Timezone for cron expression evaluation.
    """

    kind: ScheduleKind = Field(..., description="Type of schedule")
    at_ms: int | None = Field(
        default=None,
        description="Unix timestamp in ms for one-shot execution"
    )
    every_ms: int | None = Field(
        default=None,
        description="Interval in ms for recurring execution"
    )
    cron_expr: str | None = Field(
        default=None,
        description="Cron expression (e.g., '0 9 * * *')"
    )
    timezone: str = Field(
        default="UTC",
        description="Timezone for cron expression evaluation"
    )

    def model_post_init(self, __context: Any) -> None:
        """Validate that the correct field is set for the schedule kind."""
        if self.kind == ScheduleKind.AT and self.at_ms is None:
            raise ValueError("at_ms is required for 'at' schedule kind")
        if self.kind == ScheduleKind.EVERY and self.every_ms is None:
            raise ValueError("every_ms is required for 'every' schedule kind")
        if self.kind == ScheduleKind.CRON and self.cron_expr is None:
            raise ValueError("cron_expr is required for 'cron' schedule kind")


class CronPayload(BaseModel):
    """Payload configuration for a cron job execution.

    Defines what happens when the cron job fires.

    Attributes:
        kind: Type of payload (system_event or agent_turn).
        message: Message to process or event to trigger.
        model: Optional model override for agent_turn payloads.
        timeout_seconds: Maximum execution time.
        deliver: Whether to deliver results to a channel.
        channel: Target channel for delivery.
    """

    kind: Literal["system_event", "agent_turn", "memory_maintenance"] = Field(
        default="agent_turn",
        description="Type of payload"
    )
    message: str = Field(..., description="Message to process or event to trigger")
    model: str | None = Field(
        default=None,
        description="Optional model override for agent_turn"
    )
    timeout_seconds: int = Field(
        default=120,
        description="Maximum execution time in seconds"
    )
    deliver: bool = Field(
        default=False,
        description="Whether to deliver results to a channel"
    )
    channel: str | None = Field(
        default=None,
        description="Target channel for delivery"
    )


class CronJobState(BaseModel):
    """Runtime state for a cron job.

    Tracks execution history and next scheduled run.

    Attributes:
        next_run_at: Timestamp of next scheduled execution.
        last_run_at: Timestamp of last execution.
        last_result: Result of the last execution.
        run_count: Total number of executions.
        error_count: Number of failed executions.
        last_error: Error message from last failed execution.
    """

    next_run_at: datetime | None = Field(
        default=None,
        description="Next scheduled execution time"
    )
    last_run_at: datetime | None = Field(
        default=None,
        description="Last execution time"
    )
    last_result: str | None = Field(
        default=None,
        description="Result of last execution"
    )
    run_count: int = Field(
        default=0,
        description="Total number of executions"
    )
    error_count: int = Field(
        default=0,
        description="Number of failed executions"
    )
    last_error: str | None = Field(
        default=None,
        description="Error from last failed execution"
    )


class CronJob(BaseModel):
    """A scheduled cron job.

    Complete definition of a cron job including its schedule,
    payload, and current state.

    Attributes:
        id: Unique job identifier.
        name: Human-readable job name.
        description: Optional job description.
        enabled: Whether the job is active.
        schedule: Schedule configuration.
        payload: Execution payload.
        state: Runtime state.
        created_at: Job creation timestamp.
        updated_at: Last modification timestamp.
    """

    id: str = Field(..., description="Unique job identifier")
    name: str = Field(..., description="Human-readable job name")
    description: str | None = Field(
        default=None,
        description="Optional job description"
    )
    enabled: bool = Field(
        default=True,
        description="Whether the job is active"
    )
    schedule: CronSchedule = Field(..., description="Schedule configuration")
    payload: CronPayload = Field(..., description="Execution payload")
    state: CronJobState = Field(
        default_factory=CronJobState,
        description="Runtime state"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Job creation timestamp"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Last modification timestamp"
    )

    def is_due(self, now: datetime | None = None) -> bool:
        """Check if the job is due to run.

        Args:
            now: Current time (defaults to utcnow).

        Returns:
            True if the job should be executed.
        """
        if not self.enabled:
            return False
        if self.state.next_run_at is None:
            return False
        now = now or datetime.now(timezone.utc)
        return now >= self.state.next_run_at

    def is_one_shot(self) -> bool:
        """Check if this is a one-shot job.

        Returns:
            True if the job executes only once.
        """
        return self.schedule.kind == ScheduleKind.AT


class CronJobCreate(BaseModel):
    """Input model for creating a new cron job.

    Attributes:
        name: Human-readable job name.
        description: Optional job description.
        schedule: Schedule configuration.
        payload: Execution payload.
        enabled: Whether the job starts enabled.
    """

    name: str = Field(..., description="Human-readable job name")
    description: str | None = Field(default=None, description="Optional description")
    schedule: CronSchedule = Field(..., description="Schedule configuration")
    payload: CronPayload = Field(..., description="Execution payload")
    enabled: bool = Field(default=True, description="Whether to start enabled")


class CronJobUpdate(BaseModel):
    """Input model for updating a cron job.

    All fields are optional; only provided fields are updated.

    Attributes:
        name: New job name.
        description: New description.
        schedule: New schedule configuration.
        payload: New execution payload.
        enabled: New enabled state.
    """

    name: str | None = Field(default=None, description="New job name")
    description: str | None = Field(default=None, description="New description")
    schedule: CronSchedule | None = Field(default=None, description="New schedule")
    payload: CronPayload | None = Field(default=None, description="New payload")
    enabled: bool | None = Field(default=None, description="New enabled state")
