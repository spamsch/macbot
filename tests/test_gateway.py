"""Tests for the gateway service."""

import asyncio
import tempfile
from pathlib import Path

import pytest

from macbot.gateway import GatewayRunLoop, GatewayServer, LoopState


class TestGatewayRunLoop:
    """Tests for GatewayRunLoop."""

    def test_initial_state(self) -> None:
        """Test initial loop state."""
        loop = GatewayRunLoop()

        assert loop.state == LoopState.STOPPED
        assert loop.is_running is False
        assert loop.stats.start_count == 0

    @pytest.mark.asyncio
    async def test_startup_callbacks(self) -> None:
        """Test startup callbacks are called."""
        loop = GatewayRunLoop()
        startup_called = False

        @loop.on_startup
        async def startup():
            nonlocal startup_called
            startup_called = True

        # Start and immediately request shutdown
        async def run_briefly():
            loop.request_shutdown()

        task = asyncio.create_task(loop.run(run_briefly))
        await asyncio.sleep(0.1)

        assert startup_called
        await task

    @pytest.mark.asyncio
    async def test_shutdown_callbacks(self) -> None:
        """Test shutdown callbacks are called."""
        loop = GatewayRunLoop()
        shutdown_called = False

        @loop.on_shutdown
        async def shutdown():
            nonlocal shutdown_called
            shutdown_called = True

        async def trigger_shutdown():
            await asyncio.sleep(0.05)
            loop.request_shutdown()

        await loop.run(trigger_shutdown)

        assert shutdown_called
        assert loop.state == LoopState.STOPPED

    @pytest.mark.asyncio
    async def test_request_shutdown(self) -> None:
        """Test requesting shutdown."""
        loop = GatewayRunLoop()

        async def wait_for_shutdown():
            # This would run forever without shutdown
            while True:
                await asyncio.sleep(0.1)

        # Start loop in background
        task = asyncio.create_task(loop.run(wait_for_shutdown))

        # Give it time to start
        await asyncio.sleep(0.1)
        assert loop.state == LoopState.RUNNING

        # Request shutdown
        loop.request_shutdown()

        # Wait for completion
        await task

        assert loop.state == LoopState.STOPPED

    @pytest.mark.asyncio
    async def test_stats_tracking(self) -> None:
        """Test statistics are tracked."""
        loop = GatewayRunLoop()

        async def short_task():
            await asyncio.sleep(0.1)
            loop.request_shutdown()

        await loop.run(short_task)

        assert loop.stats.start_count == 1
        assert loop.stats.total_runtime_seconds > 0


class TestGatewayServer:
    """Tests for GatewayServer."""

    def test_server_initialization(self) -> None:
        """Test server initializes with components."""
        with tempfile.TemporaryDirectory() as tmpdir:
            server = GatewayServer(
                cron_storage_path=Path(tmpdir) / "cron.json",
            )

            assert server.command_queue is not None
            assert server.followup_queue is not None
            assert server.cron_service is not None
            assert server.run_loop is not None

    def test_custom_configuration(self) -> None:
        """Test server with custom configuration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            server = GatewayServer(
                cron_storage_path=Path(tmpdir) / "cron.json",
                main_lane_concurrency=2,
                followup_cap=50,
            )

            stats = server.command_queue.get_lane_stats("main")
            assert stats["max_concurrent"] == 2

            queue_stats = server.followup_queue.get_stats()
            assert queue_stats["cap"] == 50

    def test_get_stats(self) -> None:
        """Test getting server statistics."""
        with tempfile.TemporaryDirectory() as tmpdir:
            server = GatewayServer(
                cron_storage_path=Path(tmpdir) / "cron.json",
            )

            stats = server.get_stats()

            assert "run_loop" in stats
            assert "command_queue" in stats
            assert "followup_queue" in stats
            assert "cron" in stats

    @pytest.mark.asyncio
    async def test_start_background(self) -> None:
        """Test starting server in background."""
        with tempfile.TemporaryDirectory() as tmpdir:
            server = GatewayServer(
                cron_storage_path=Path(tmpdir) / "cron.json",
            )

            task = await server.start_background()

            # Should be running
            await asyncio.sleep(0.1)
            assert server.is_running

            # Stop it
            server.stop()
            await asyncio.sleep(0.2)

            assert not server.is_running

    @pytest.mark.asyncio
    async def test_stop_server(self) -> None:
        """Test stopping the server."""
        with tempfile.TemporaryDirectory() as tmpdir:
            server = GatewayServer(
                cron_storage_path=Path(tmpdir) / "cron.json",
            )

            task = await server.start_background()
            await asyncio.sleep(0.1)

            server.stop()
            await asyncio.sleep(0.2)

            assert server.run_loop.state == LoopState.STOPPED
