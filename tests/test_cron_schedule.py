"""Tests for cron schedule computation."""

from datetime import datetime, timedelta, timezone

import pytest

from macbot.cron.schedule import (
    compute_next_run,
    time_until_next_run,
    validate_cron_expression,
)
from macbot.cron.types import CronSchedule, ScheduleKind


class TestComputeNextRun:
    """Tests for compute_next_run function."""

    def test_at_schedule_future(self) -> None:
        """Test 'at' schedule with future time."""
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        at_ms = int(future.timestamp() * 1000)

        schedule = CronSchedule(kind=ScheduleKind.AT, at_ms=at_ms)
        next_run = compute_next_run(schedule)

        assert next_run is not None
        assert abs((next_run - future).total_seconds()) < 1

    def test_at_schedule_past(self) -> None:
        """Test 'at' schedule with past time returns None."""
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        at_ms = int(past.timestamp() * 1000)

        schedule = CronSchedule(kind=ScheduleKind.AT, at_ms=at_ms)
        next_run = compute_next_run(schedule)

        assert next_run is None

    def test_every_schedule_first_run(self) -> None:
        """Test 'every' schedule without last run."""
        schedule = CronSchedule(kind=ScheduleKind.EVERY, every_ms=60000)  # 60 seconds
        now = datetime.now(timezone.utc)

        next_run = compute_next_run(schedule, last_run=None, now=now)

        assert next_run is not None
        # Should be ~60 seconds from now
        diff = (next_run - now).total_seconds()
        assert 59 <= diff <= 61

    def test_every_schedule_with_last_run(self) -> None:
        """Test 'every' schedule with last run."""
        schedule = CronSchedule(kind=ScheduleKind.EVERY, every_ms=60000)  # 60 seconds
        now = datetime.now(timezone.utc)
        last_run = now - timedelta(seconds=30)

        next_run = compute_next_run(schedule, last_run=last_run, now=now)

        assert next_run is not None
        # Should be ~30 seconds from now (60 - 30 already elapsed)
        diff = (next_run - now).total_seconds()
        assert 29 <= diff <= 31

    def test_every_schedule_catchup(self) -> None:
        """Test 'every' schedule catches up when behind."""
        schedule = CronSchedule(kind=ScheduleKind.EVERY, every_ms=60000)  # 60 seconds
        now = datetime.now(timezone.utc)
        last_run = now - timedelta(seconds=120)  # 2 intervals ago

        next_run = compute_next_run(schedule, last_run=last_run, now=now)

        assert next_run is not None
        # Should be in the future
        assert next_run > now

    def test_cron_schedule(self) -> None:
        """Test cron expression schedule."""
        schedule = CronSchedule(
            kind=ScheduleKind.CRON,
            cron_expr="0 * * * *",  # Every hour at minute 0
        )
        now = datetime.now(timezone.utc)

        next_run = compute_next_run(schedule, now=now)

        assert next_run is not None
        assert next_run > now
        assert next_run.minute == 0  # Should be at minute 0

    def test_cron_schedule_with_timezone(self) -> None:
        """Test cron schedule respects timezone."""
        schedule = CronSchedule(
            kind=ScheduleKind.CRON,
            cron_expr="0 9 * * *",  # 9 AM daily
            timezone="America/New_York",
        )

        next_run = compute_next_run(schedule)

        assert next_run is not None
        # Result should be in UTC
        assert next_run.tzinfo == timezone.utc


class TestValidateCronExpression:
    """Tests for cron expression validation."""

    def test_valid_expressions(self) -> None:
        """Test valid cron expressions."""
        valid = [
            "* * * * *",
            "0 * * * *",
            "0 9 * * *",
            "0 9 * * 1-5",
            "*/5 * * * *",
            "0 0 1 * *",
        ]

        for expr in valid:
            assert validate_cron_expression(expr) is True, f"Should be valid: {expr}"

    def test_invalid_expressions(self) -> None:
        """Test invalid cron expressions."""
        invalid = [
            "",
            "invalid",
            "* * *",  # Too few fields
            "60 * * * *",  # Invalid minute
            "* 25 * * *",  # Invalid hour
        ]

        for expr in invalid:
            assert validate_cron_expression(expr) is False, f"Should be invalid: {expr}"


class TestTimeUntilNextRun:
    """Tests for time_until_next_run function."""

    def test_time_until_at_schedule(self) -> None:
        """Test time until 'at' schedule."""
        future = datetime.now(timezone.utc) + timedelta(hours=2)
        at_ms = int(future.timestamp() * 1000)

        schedule = CronSchedule(kind=ScheduleKind.AT, at_ms=at_ms)
        remaining = time_until_next_run(schedule)

        assert remaining is not None
        assert 7100 <= remaining.total_seconds() <= 7300  # ~2 hours

    def test_time_until_past_returns_none(self) -> None:
        """Test time until past schedule returns None."""
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        at_ms = int(past.timestamp() * 1000)

        schedule = CronSchedule(kind=ScheduleKind.AT, at_ms=at_ms)
        remaining = time_until_next_run(schedule)

        assert remaining is None

    def test_time_until_every_schedule(self) -> None:
        """Test time until 'every' schedule."""
        schedule = CronSchedule(kind=ScheduleKind.EVERY, every_ms=300000)  # 5 minutes
        now = datetime.now(timezone.utc)
        last_run = now - timedelta(minutes=2)

        remaining = time_until_next_run(schedule, last_run=last_run, now=now)

        assert remaining is not None
        # Should be ~3 minutes remaining
        assert 170 <= remaining.total_seconds() <= 190
