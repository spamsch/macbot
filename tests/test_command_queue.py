"""Tests for the command queue system."""

import asyncio

import pytest

from macbot.core.command_queue import CommandLane, CommandQueue, QueueEntry


class TestQueueEntry:
    """Tests for QueueEntry."""

    @pytest.mark.asyncio
    async def test_wait_time_calculation(self) -> None:
        """Test that wait time is calculated correctly."""
        import time

        loop = asyncio.get_running_loop()
        entry = QueueEntry(
            task=lambda: asyncio.sleep(0),
            future=loop.create_future(),
            enqueued_at=time.time() - 1.0,  # 1 second ago
        )

        # Wait time should be ~1000ms
        assert entry.wait_time_ms >= 900
        assert entry.wait_time_ms < 1200


class TestCommandQueue:
    """Tests for CommandQueue."""

    @pytest.mark.asyncio
    async def test_basic_enqueue(self) -> None:
        """Test basic task enqueuing and execution."""
        queue = CommandQueue()

        async def my_task() -> str:
            return "done"

        result = await queue.enqueue(my_task)
        assert result == "done"

    @pytest.mark.asyncio
    async def test_lane_concurrency(self) -> None:
        """Test that lane concurrency limits are respected."""
        queue = CommandQueue()
        queue.set_lane_concurrency(CommandLane.MAIN, 1)

        execution_order = []

        async def task1() -> None:
            execution_order.append("start1")
            await asyncio.sleep(0.1)
            execution_order.append("end1")

        async def task2() -> None:
            execution_order.append("start2")
            await asyncio.sleep(0.1)
            execution_order.append("end2")

        # Run both tasks
        await asyncio.gather(
            queue.enqueue(task1, lane=CommandLane.MAIN),
            queue.enqueue(task2, lane=CommandLane.MAIN),
        )

        # With concurrency 1, task1 should complete before task2 starts
        assert execution_order[0] == "start1"
        assert execution_order[1] == "end1"
        assert execution_order[2] == "start2"
        assert execution_order[3] == "end2"

    @pytest.mark.asyncio
    async def test_multiple_lanes(self) -> None:
        """Test that different lanes operate independently."""
        queue = CommandQueue()
        queue.set_lane_concurrency(CommandLane.MAIN, 1)
        queue.set_lane_concurrency(CommandLane.CRON, 1)

        results = []

        async def main_task() -> str:
            await asyncio.sleep(0.05)
            return "main"

        async def cron_task() -> str:
            await asyncio.sleep(0.05)
            return "cron"

        # Both should run concurrently since they're in different lanes
        main_result, cron_result = await asyncio.gather(
            queue.enqueue(main_task, lane=CommandLane.MAIN),
            queue.enqueue(cron_task, lane=CommandLane.CRON),
        )

        assert main_result == "main"
        assert cron_result == "cron"

    @pytest.mark.asyncio
    async def test_exception_propagation(self) -> None:
        """Test that exceptions are propagated to the caller."""
        queue = CommandQueue()

        async def failing_task() -> None:
            raise ValueError("Task failed")

        with pytest.raises(ValueError, match="Task failed"):
            await queue.enqueue(failing_task)

    @pytest.mark.asyncio
    async def test_lane_draining(self) -> None:
        """Test that lanes can be drained."""
        queue = CommandQueue()

        async def slow_task() -> str:
            await asyncio.sleep(0.1)
            return "done"

        # Start a task
        task = asyncio.create_task(queue.enqueue(slow_task))

        # Wait a bit then drain
        await asyncio.sleep(0.01)
        await queue.drain_lane(CommandLane.MAIN)

        # Task should complete
        result = await task
        assert result == "done"

    @pytest.mark.asyncio
    async def test_draining_rejects_new_tasks(self) -> None:
        """Test that draining lanes reject new tasks."""
        queue = CommandQueue()
        state = queue._get_lane(CommandLane.MAIN)
        state.draining = True

        async def my_task() -> None:
            pass

        with pytest.raises(RuntimeError, match="draining"):
            await queue.enqueue(my_task)

        state.draining = False

    def test_get_lane_stats(self) -> None:
        """Test lane statistics retrieval."""
        queue = CommandQueue()
        queue.set_lane_concurrency(CommandLane.MAIN, 2)

        stats = queue.get_lane_stats(CommandLane.MAIN)

        assert stats["name"] == "main"
        assert stats["max_concurrent"] == 2
        assert stats["active"] == 0
        assert stats["draining"] is False

    @pytest.mark.asyncio
    async def test_shutdown(self) -> None:
        """Test graceful shutdown."""
        queue = CommandQueue()

        async def task() -> str:
            return "done"

        # Enqueue a task
        result = await queue.enqueue(task)
        assert result == "done"

        # Shutdown should complete without hanging
        await queue.shutdown(timeout=1.0)
