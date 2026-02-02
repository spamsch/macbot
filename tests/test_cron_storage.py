"""Tests for cron job storage."""

import tempfile
from pathlib import Path

import pytest

from macbot.cron.storage import CronStorage
from macbot.cron.types import (
    CronJob,
    CronJobState,
    CronPayload,
    CronSchedule,
    ScheduleKind,
)


def create_test_job(job_id: str = "test_job") -> CronJob:
    """Create a test job."""
    return CronJob(
        id=job_id,
        name=f"Test Job {job_id}",
        schedule=CronSchedule(kind=ScheduleKind.EVERY, every_ms=60000),
        payload=CronPayload(message="Test message"),
    )


class TestCronStorage:
    """Tests for CronStorage."""

    def test_create_storage_file(self) -> None:
        """Test that storage file is created if missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "subdir" / "cron.json"
            storage = CronStorage(path)

            # Loading should create the file
            jobs = storage.load()

            assert path.exists()
            assert jobs == []

    def test_save_and_load(self) -> None:
        """Test saving and loading jobs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "cron.json"
            storage = CronStorage(path)

            jobs = [create_test_job("job1"), create_test_job("job2")]
            storage.save(jobs)

            loaded = storage.load()

            assert len(loaded) == 2
            assert loaded[0].id == "job1"
            assert loaded[1].id == "job2"

    def test_add_job(self) -> None:
        """Test adding a single job."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "cron.json"
            storage = CronStorage(path)

            job = create_test_job("new_job")
            storage.add(job)

            loaded = storage.load()

            assert len(loaded) == 1
            assert loaded[0].id == "new_job"

    def test_add_duplicate_fails(self) -> None:
        """Test that adding duplicate job raises error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "cron.json"
            storage = CronStorage(path)

            storage.add(create_test_job("job1"))

            with pytest.raises(ValueError, match="already exists"):
                storage.add(create_test_job("job1"))

    def test_get_job(self) -> None:
        """Test getting a specific job."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "cron.json"
            storage = CronStorage(path)

            storage.add(create_test_job("job1"))
            storage.add(create_test_job("job2"))

            job = storage.get("job1")

            assert job is not None
            assert job.id == "job1"

    def test_get_nonexistent_job(self) -> None:
        """Test getting a job that doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "cron.json"
            storage = CronStorage(path)

            job = storage.get("nonexistent")

            assert job is None

    def test_update_job(self) -> None:
        """Test updating a job."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "cron.json"
            storage = CronStorage(path)

            job = create_test_job("job1")
            storage.add(job)

            # Modify and update
            job.name = "Updated Name"
            result = storage.update(job)

            assert result is True

            loaded = storage.get("job1")
            assert loaded is not None
            assert loaded.name == "Updated Name"

    def test_update_nonexistent_job(self) -> None:
        """Test updating a job that doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "cron.json"
            storage = CronStorage(path)

            job = create_test_job("nonexistent")
            result = storage.update(job)

            assert result is False

    def test_remove_job(self) -> None:
        """Test removing a job."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "cron.json"
            storage = CronStorage(path)

            storage.add(create_test_job("job1"))
            storage.add(create_test_job("job2"))

            result = storage.remove("job1")

            assert result is True
            assert storage.count() == 1
            assert storage.get("job1") is None
            assert storage.get("job2") is not None

    def test_remove_nonexistent_job(self) -> None:
        """Test removing a job that doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "cron.json"
            storage = CronStorage(path)

            result = storage.remove("nonexistent")

            assert result is False

    def test_clear_jobs(self) -> None:
        """Test clearing all jobs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "cron.json"
            storage = CronStorage(path)

            storage.add(create_test_job("job1"))
            storage.add(create_test_job("job2"))
            storage.add(create_test_job("job3"))

            count = storage.clear()

            assert count == 3
            assert storage.count() == 0

    def test_count_jobs(self) -> None:
        """Test counting jobs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "cron.json"
            storage = CronStorage(path)

            assert storage.count() == 0

            storage.add(create_test_job("job1"))
            assert storage.count() == 1

            storage.add(create_test_job("job2"))
            assert storage.count() == 2

    def test_persistence_across_instances(self) -> None:
        """Test that data persists across storage instances."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "cron.json"

            # Create and save with one instance
            storage1 = CronStorage(path)
            storage1.add(create_test_job("persistent_job"))

            # Load with new instance
            storage2 = CronStorage(path)
            loaded = storage2.load()

            assert len(loaded) == 1
            assert loaded[0].id == "persistent_job"

    def test_file_not_found_without_create(self) -> None:
        """Test that FileNotFoundError is raised when create_if_missing=False."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "nonexistent" / "cron.json"
            storage = CronStorage(path, create_if_missing=False)

            with pytest.raises(FileNotFoundError):
                storage.load()
