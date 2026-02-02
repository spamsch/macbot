"""Tests for cron type models."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from macbot.cron.types import (
    CronJob,
    CronJobCreate,
    CronJobState,
    CronPayload,
    CronSchedule,
    ScheduleKind,
)


class TestCronSchedule:
    """Tests for CronSchedule model."""

    def test_at_schedule_valid(self) -> None:
        """Test valid 'at' schedule."""
        schedule = CronSchedule(kind=ScheduleKind.AT, at_ms=1704067200000)

        assert schedule.kind == ScheduleKind.AT
        assert schedule.at_ms == 1704067200000

    def test_at_schedule_missing_at_ms(self) -> None:
        """Test that 'at' schedule requires at_ms."""
        with pytest.raises(ValueError, match="at_ms is required"):
            CronSchedule(kind=ScheduleKind.AT)

    def test_every_schedule_valid(self) -> None:
        """Test valid 'every' schedule."""
        schedule = CronSchedule(kind=ScheduleKind.EVERY, every_ms=60000)

        assert schedule.kind == ScheduleKind.EVERY
        assert schedule.every_ms == 60000

    def test_every_schedule_missing_every_ms(self) -> None:
        """Test that 'every' schedule requires every_ms."""
        with pytest.raises(ValueError, match="every_ms is required"):
            CronSchedule(kind=ScheduleKind.EVERY)

    def test_cron_schedule_valid(self) -> None:
        """Test valid 'cron' schedule."""
        schedule = CronSchedule(
            kind=ScheduleKind.CRON,
            cron_expr="0 9 * * *",
            timezone="America/New_York",
        )

        assert schedule.kind == ScheduleKind.CRON
        assert schedule.cron_expr == "0 9 * * *"
        assert schedule.timezone == "America/New_York"

    def test_cron_schedule_missing_expr(self) -> None:
        """Test that 'cron' schedule requires cron_expr."""
        with pytest.raises(ValueError, match="cron_expr is required"):
            CronSchedule(kind=ScheduleKind.CRON)

    def test_default_timezone(self) -> None:
        """Test default timezone is UTC."""
        schedule = CronSchedule(kind=ScheduleKind.CRON, cron_expr="* * * * *")
        assert schedule.timezone == "UTC"


class TestCronPayload:
    """Tests for CronPayload model."""

    def test_agent_turn_payload(self) -> None:
        """Test agent_turn payload creation."""
        payload = CronPayload(
            kind="agent_turn",
            message="Hello",
            model="gpt-4",
            timeout_seconds=60,
        )

        assert payload.kind == "agent_turn"
        assert payload.message == "Hello"
        assert payload.model == "gpt-4"
        assert payload.timeout_seconds == 60

    def test_system_event_payload(self) -> None:
        """Test system_event payload creation."""
        payload = CronPayload(kind="system_event", message="Check backups")

        assert payload.kind == "system_event"
        assert payload.message == "Check backups"

    def test_default_values(self) -> None:
        """Test default payload values."""
        payload = CronPayload(message="Test")

        assert payload.kind == "agent_turn"
        assert payload.timeout_seconds == 120
        assert payload.deliver is False
        assert payload.channel is None


class TestCronJobState:
    """Tests for CronJobState model."""

    def test_default_state(self) -> None:
        """Test default state values."""
        state = CronJobState()

        assert state.next_run_at is None
        assert state.last_run_at is None
        assert state.run_count == 0
        assert state.error_count == 0

    def test_state_with_values(self) -> None:
        """Test state with explicit values."""
        now = datetime.now(timezone.utc)
        state = CronJobState(
            next_run_at=now,
            last_run_at=now,
            run_count=5,
            error_count=1,
            last_error="Connection failed",
        )

        assert state.next_run_at == now
        assert state.run_count == 5
        assert state.error_count == 1


class TestCronJob:
    """Tests for CronJob model."""

    def test_job_creation(self) -> None:
        """Test complete job creation."""
        job = CronJob(
            id="job_123",
            name="Daily backup",
            description="Backup all data",
            schedule=CronSchedule(kind=ScheduleKind.CRON, cron_expr="0 3 * * *"),
            payload=CronPayload(message="Run backup"),
        )

        assert job.id == "job_123"
        assert job.name == "Daily backup"
        assert job.enabled is True
        assert job.state.run_count == 0

    def test_is_due(self) -> None:
        """Test is_due calculation."""
        past = datetime(2020, 1, 1, tzinfo=timezone.utc)
        future = datetime(2099, 1, 1, tzinfo=timezone.utc)

        job = CronJob(
            id="job_1",
            name="Test",
            schedule=CronSchedule(kind=ScheduleKind.EVERY, every_ms=60000),
            payload=CronPayload(message="Test"),
            state=CronJobState(next_run_at=past),
        )

        assert job.is_due() is True

        job.state.next_run_at = future
        assert job.is_due() is False

    def test_is_due_when_disabled(self) -> None:
        """Test is_due returns False when disabled."""
        job = CronJob(
            id="job_1",
            name="Test",
            enabled=False,
            schedule=CronSchedule(kind=ScheduleKind.EVERY, every_ms=60000),
            payload=CronPayload(message="Test"),
            state=CronJobState(next_run_at=datetime(2020, 1, 1, tzinfo=timezone.utc)),
        )

        assert job.is_due() is False

    def test_is_one_shot(self) -> None:
        """Test one-shot detection."""
        one_shot = CronJob(
            id="job_1",
            name="Test",
            schedule=CronSchedule(kind=ScheduleKind.AT, at_ms=1704067200000),
            payload=CronPayload(message="Test"),
        )

        recurring = CronJob(
            id="job_2",
            name="Test",
            schedule=CronSchedule(kind=ScheduleKind.EVERY, every_ms=60000),
            payload=CronPayload(message="Test"),
        )

        assert one_shot.is_one_shot() is True
        assert recurring.is_one_shot() is False


class TestCronJobCreate:
    """Tests for CronJobCreate model."""

    def test_minimal_creation(self) -> None:
        """Test minimal job creation input."""
        create = CronJobCreate(
            name="Test job",
            schedule=CronSchedule(kind=ScheduleKind.EVERY, every_ms=60000),
            payload=CronPayload(message="Test"),
        )

        assert create.name == "Test job"
        assert create.enabled is True
        assert create.description is None

    def test_full_creation(self) -> None:
        """Test full job creation input."""
        create = CronJobCreate(
            name="Full job",
            description="A complete job",
            schedule=CronSchedule(kind=ScheduleKind.CRON, cron_expr="0 * * * *"),
            payload=CronPayload(message="Test", timeout_seconds=300),
            enabled=False,
        )

        assert create.name == "Full job"
        assert create.description == "A complete job"
        assert create.enabled is False
