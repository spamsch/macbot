"""Tests for the followup queue system."""

import asyncio

import pytest

from macbot.core.followup_queue import (
    DropPolicy,
    FollowupItem,
    FollowupQueue,
    QueueMode,
)


class TestFollowupItem:
    """Tests for FollowupItem."""

    def test_age_calculation(self) -> None:
        """Test that age is calculated correctly."""
        import time

        item = FollowupItem(
            prompt="test",
            enqueued_at=time.time() - 0.5,  # 500ms ago
        )

        assert item.age_ms >= 400
        assert item.age_ms < 700


class TestFollowupQueue:
    """Tests for FollowupQueue."""

    @pytest.mark.asyncio
    async def test_basic_enqueue(self) -> None:
        """Test basic item enqueuing."""
        queue = FollowupQueue()

        result = await queue.enqueue(FollowupItem(prompt="Hello"))

        assert result is True
        assert queue.size() == 1

    @pytest.mark.asyncio
    async def test_drain_collect_mode(self) -> None:
        """Test draining in collect mode."""
        queue = FollowupQueue(mode=QueueMode.COLLECT, debounce_ms=0)

        await queue.enqueue(FollowupItem(prompt="Message 1"))
        await queue.enqueue(FollowupItem(prompt="Message 2"))

        processed_batches = []

        async def processor(items: list[FollowupItem]) -> None:
            processed_batches.append(items)

        count = await queue.drain(processor)

        assert count == 2
        assert len(processed_batches) == 1
        assert len(processed_batches[0]) == 2

    @pytest.mark.asyncio
    async def test_drain_followup_mode(self) -> None:
        """Test draining in followup mode."""
        queue = FollowupQueue(mode=QueueMode.FOLLOWUP, debounce_ms=0)

        await queue.enqueue(FollowupItem(prompt="Message 1"))
        await queue.enqueue(FollowupItem(prompt="Message 2"))

        processed_batches = []

        async def processor(items: list[FollowupItem]) -> None:
            processed_batches.append(items)

        count = await queue.drain(processor)

        assert count == 2
        # In followup mode, each message is processed individually
        assert len(processed_batches) == 2
        assert len(processed_batches[0]) == 1
        assert len(processed_batches[1]) == 1

    @pytest.mark.asyncio
    async def test_cap_with_old_drop_policy(self) -> None:
        """Test queue cap with old drop policy."""
        queue = FollowupQueue(cap=2, drop_policy=DropPolicy.OLD)

        await queue.enqueue(FollowupItem(prompt="First", message_id="1"))
        await queue.enqueue(FollowupItem(prompt="Second", message_id="2"))
        await queue.enqueue(FollowupItem(prompt="Third", message_id="3"))

        assert queue.size() == 2
        items = queue.peek()
        # First message should be dropped
        assert items[0].message_id == "2"
        assert items[1].message_id == "3"

    @pytest.mark.asyncio
    async def test_cap_with_new_drop_policy(self) -> None:
        """Test queue cap with new drop policy."""
        queue = FollowupQueue(cap=2, drop_policy=DropPolicy.NEW)

        await queue.enqueue(FollowupItem(prompt="First", message_id="1"))
        await queue.enqueue(FollowupItem(prompt="Second", message_id="2"))
        result = await queue.enqueue(FollowupItem(prompt="Third", message_id="3"))

        assert result is False  # New message rejected
        assert queue.size() == 2
        items = queue.peek()
        assert items[0].message_id == "1"
        assert items[1].message_id == "2"

    @pytest.mark.asyncio
    async def test_channel_isolation(self) -> None:
        """Test that channels are processed independently."""
        queue = FollowupQueue(mode=QueueMode.COLLECT, debounce_ms=0)

        await queue.enqueue(FollowupItem(prompt="Channel A - 1", channel="a"))
        await queue.enqueue(FollowupItem(prompt="Channel A - 2", channel="a"))
        await queue.enqueue(FollowupItem(prompt="Channel B - 1", channel="b"))

        # Drain only channel A
        batches = []

        async def processor(items: list[FollowupItem]) -> None:
            batches.append(items)

        count = await queue.drain(processor, channel="a")

        assert count == 2
        assert queue.size(channel="a") == 0
        assert queue.size(channel="b") == 1

    @pytest.mark.asyncio
    async def test_clear(self) -> None:
        """Test clearing the queue."""
        queue = FollowupQueue()

        await queue.enqueue(FollowupItem(prompt="Message 1"))
        await queue.enqueue(FollowupItem(prompt="Message 2"))

        count = queue.clear()

        assert count == 2
        assert queue.is_empty()

    @pytest.mark.asyncio
    async def test_peek_does_not_modify(self) -> None:
        """Test that peek doesn't remove items."""
        queue = FollowupQueue()

        await queue.enqueue(FollowupItem(prompt="Message"))

        items1 = queue.peek()
        items2 = queue.peek()

        assert len(items1) == 1
        assert len(items2) == 1
        assert queue.size() == 1

    def test_get_stats(self) -> None:
        """Test statistics retrieval."""
        queue = FollowupQueue(
            mode=QueueMode.COLLECT,
            cap=50,
            debounce_ms=100,
            drop_policy=DropPolicy.OLD,
        )

        stats = queue.get_stats()

        assert stats["mode"] == "collect"
        assert stats["cap"] == 50
        assert stats["debounce_ms"] == 100
        assert stats["drop_policy"] == "old"
        assert stats["total_items"] == 0

    @pytest.mark.asyncio
    async def test_draining_rejects_new_items(self) -> None:
        """Test that draining queue rejects new items."""
        queue = FollowupQueue(debounce_ms=100)

        await queue.enqueue(FollowupItem(prompt="First"))

        # Start draining
        drain_task = asyncio.create_task(
            queue.drain(lambda items: asyncio.sleep(0))
        )

        # Give draining time to start
        await asyncio.sleep(0.01)

        # Try to enqueue during drain
        result = await queue.enqueue(FollowupItem(prompt="Second"))

        await drain_task

        # Item should be rejected while draining
        assert result is False
