"""Unified macbot service.

Runs the cron scheduler and Telegram listener together as a single service.
"""

import asyncio
import logging
import os
import signal
from datetime import datetime
from pathlib import Path

from macbot.config import settings
from macbot.core.agent import Agent
from macbot.cron import CronPayload, CronService
from macbot.tasks import create_default_registry

logger = logging.getLogger(__name__)

# Service paths
MACBOT_DIR = Path.home() / ".macbot"
PID_FILE = MACBOT_DIR / "service.pid"
LOG_FILE = MACBOT_DIR / "service.log"


def get_service_pid() -> int | None:
    """Get the PID of a running macbot service, or None if not running."""
    if not PID_FILE.exists():
        return None
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 0)
        return pid
    except (ValueError, ProcessLookupError, PermissionError):
        PID_FILE.unlink(missing_ok=True)
        return None


def stop_service() -> bool:
    """Stop the running macbot service.

    Returns:
        True if service was stopped, False if not running
    """
    pid = get_service_pid()
    if not pid:
        return False

    try:
        os.kill(pid, signal.SIGTERM)
        # Wait for process to exit
        import time
        for _ in range(20):
            time.sleep(0.2)
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                PID_FILE.unlink(missing_ok=True)
                return True
        return True
    except ProcessLookupError:
        PID_FILE.unlink(missing_ok=True)
        return False


class MacbotService:
    """Unified service that runs cron jobs and listens for Telegram messages."""

    def __init__(self):
        """Initialize the service."""
        self.registry = create_default_registry()
        self.agent = Agent(self.registry)  # Default agent for cron jobs
        self._chat_agents: dict[str, Agent] = {}  # Per-chat agents for Telegram conversations
        self.cron_service: CronService | None = None
        self.telegram_service = None
        self._running = False
        self._tasks: list[asyncio.Task] = []

    def _get_chat_agent(self, chat_id: str) -> Agent:
        """Get or create an agent for a specific chat.

        Each chat gets its own agent instance to maintain conversation history.

        Args:
            chat_id: The Telegram chat ID

        Returns:
            Agent instance for this chat
        """
        if chat_id not in self._chat_agents:
            self._chat_agents[chat_id] = Agent(self.registry)
        return self._chat_agents[chat_id]

    def _setup_cron(self) -> bool:
        """Set up the cron service.

        Returns:
            True if cron has enabled jobs, False otherwise
        """
        self.cron_service = CronService(storage_path=settings.get_cron_storage_path())
        jobs = self.cron_service.list_jobs()
        enabled_jobs = [j for j in jobs if j.enabled]

        if not enabled_jobs:
            return False

        async def agent_handler(payload: CronPayload):
            from macbot.cron.executor import ExecutionResult
            try:
                timestamp = datetime.now().strftime("%H:%M:%S")
                # Show cron job in console
                print(f"\n[{timestamp}] ⏰ Cron: {payload.message[:100]}{'...' if len(payload.message) > 100 else ''}")
                logger.info(f"Cron: Running '{payload.message[:50]}...'")
                result = await self.agent.run(payload.message, stream=False)
                logger.info(f"Cron: Completed, result length: {len(result)}")
                return ExecutionResult(success=True, output=result)
            except Exception as e:
                logger.error(f"Cron: Error - {e}")
                return ExecutionResult(success=False, error=str(e))

        self.cron_service.set_agent_handler(agent_handler)
        return True

    def _setup_telegram(self) -> bool:
        """Set up the Telegram service.

        Returns:
            True if Telegram is configured, False otherwise
        """
        if not settings.telegram_bot_token:
            return False

        from macbot.telegram import TelegramService

        self.telegram_service = TelegramService(
            bot_token=settings.telegram_bot_token,
            chat_id=settings.telegram_chat_id or None,
            allowed_users=settings.telegram_allowed_users or None,
        )

        async def message_handler(text: str, chat_id: str) -> str:
            from datetime import datetime
            timestamp = datetime.now().strftime("%H:%M:%S")
            # Show incoming message in console
            print(f"\n[{timestamp}] 📩 Telegram: {text[:100]}{'...' if len(text) > 100 else ''}")
            logger.info(f"Telegram: Message from {chat_id}: {text[:50]}...")

            # Handle special commands
            if text.strip().lower() in ("/reset", "/clear", "/new"):
                if chat_id in self._chat_agents:
                    self._chat_agents[chat_id].reset()
                return "Conversation cleared. Starting fresh!"

            # Send acknowledgment
            await self.telegram_service.send_message("⏳ Working on it...", chat_id, parse_mode=None)

            try:
                # Get per-chat agent and continue conversation
                agent = self._get_chat_agent(chat_id)

                # Track tool calls for progress feedback
                tools_called = []
                original_execute = agent._execute_tool_calls

                async def tracking_execute(response, verbose=False):
                    for tc in response.tool_calls:
                        tools_called.append(tc.name)
                        # Send progress update every few tools
                        if len(tools_called) == 1:
                            await self.telegram_service.send_message(
                                f"🔧 `{tc.name}`...", chat_id, parse_mode="Markdown"
                            )
                        elif len(tools_called) % 3 == 0:
                            await self.telegram_service.send_message(
                                f"🔧 `{tc.name}` ({len(tools_called)} steps)...", chat_id, parse_mode="Markdown"
                            )
                    return await original_execute(response, verbose)

                agent._execute_tool_calls = tracking_execute

                result = await agent.run(text, stream=False, continue_conversation=True)

                # Restore original method
                agent._execute_tool_calls = original_execute

                # Show response in terminal
                timestamp = datetime.now().strftime("%H:%M:%S")
                print(f"[{timestamp}] 🤖 Response:")
                # Indent the response for readability
                for line in result.split('\n'):
                    print(f"    {line}")
                print()

                logger.info(f"Telegram: Response sent, length: {len(result)}, tools: {len(tools_called)}")
                return result
            except Exception as e:
                logger.error(f"Telegram: Error - {e}")
                return f"Error: {e}"

        self.telegram_service.set_message_handler(message_handler)
        return True

    async def _run_cron(self) -> None:
        """Run the cron service loop."""
        if not self.cron_service:
            return
        await self.cron_service.start()
        while self._running:
            await asyncio.sleep(1)

    async def _run_telegram(self) -> None:
        """Run the Telegram service loop."""
        if not self.telegram_service:
            return
        await self.telegram_service.start()

    def _format_tokens(self, count: int) -> str:
        """Format token count with K suffix for thousands."""
        if count >= 1000:
            return f"{count / 1000:.1f}K"
        return str(count)

    async def _run_stdin_reader(self) -> None:
        """Run stdin reader for GUI/foreground mode (non-interactive)."""
        import sys
        from concurrent.futures import ThreadPoolExecutor

        executor = ThreadPoolExecutor(max_workers=1)
        loop = asyncio.get_event_loop()

        # Use the same agent as the primary Telegram chat for shared context
        if settings.telegram_chat_id:
            agent = self._get_chat_agent(settings.telegram_chat_id)
        else:
            agent = self.agent

        def read_line():
            try:
                return sys.stdin.readline()
            except Exception:
                return None

        def output(msg: str):
            """Print and flush immediately for GUI to receive."""
            print(msg, flush=True)

        while self._running:
            try:
                # Read line from stdin in a thread to not block the event loop
                line = await loop.run_in_executor(executor, read_line)

                if line is None or line == "":
                    # EOF or error
                    await asyncio.sleep(0.1)
                    continue

                user_input = line.strip()
                if not user_input:
                    continue

                if user_input.lower() in ("quit", "exit", "q"):
                    output("[Stopping service...]")
                    await self.stop()
                    break

                if user_input.lower() == "clear":
                    agent.reset()
                    output("[Conversation cleared]")
                    continue

                # Process query through shared agent
                timestamp = datetime.now().strftime("%H:%M:%S")
                output(f"[{timestamp}] Processing: {user_input[:50]}{'...' if len(user_input) > 50 else ''}")

                try:
                    result = await agent.run(user_input, stream=False, continue_conversation=True)

                    # Output the response
                    output(f"\n[{timestamp}] Response:")
                    output(result)
                    output("-" * 60 + "\n")
                except Exception as e:
                    output(f"[{timestamp}] Error: {e}\n")

            except EOFError:
                break
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Stdin reader error: {e}")
                await asyncio.sleep(0.1)

        executor.shutdown(wait=False)

    async def _run_interactive(self) -> None:
        """Run interactive console input loop."""
        from concurrent.futures import ThreadPoolExecutor
        from rich.console import Console
        from rich.markdown import Markdown

        executor = ThreadPoolExecutor(max_workers=1)
        loop = asyncio.get_event_loop()
        console = Console()

        # Use the same agent as the primary Telegram chat for shared context
        if settings.telegram_chat_id:
            agent = self._get_chat_agent(settings.telegram_chat_id)
            console.print(f"\n[dim][Context shared with Telegram chat {settings.telegram_chat_id}][/dim]")
        else:
            agent = self.agent

        console.print("[dim][Ready for input - type a query or 'quit' to exit][/dim]")
        console.print("[dim][Commands: 'clear' resets conversation, 'stats' shows token usage][/dim]\n")

        while self._running:
            try:
                # Build prompt with token stats
                stats = agent.get_token_stats()
                ctx = self._format_tokens(stats["context_tokens"])
                total = self._format_tokens(stats["session_total_tokens"])

                if stats["session_total_tokens"] > 0:
                    prompt = f"[dim](ctx:{ctx} total:{total})[/dim] [bold blue]→[/bold blue] "
                else:
                    prompt = "[bold blue]→[/bold blue] "

                # Read input in a thread to not block the event loop
                user_input = await loop.run_in_executor(
                    executor, lambda p=prompt: console.input(p).strip()
                )

                if not user_input:
                    continue

                if user_input.lower() in ("quit", "exit", "q"):
                    # Show final stats
                    stats = agent.get_token_stats()
                    if stats["session_total_tokens"] > 0:
                        console.print(f"\n[dim]Session total: {stats['session_total_tokens']:,} tokens "
                                      f"(in: {stats['session_input_tokens']:,}, out: {stats['session_output_tokens']:,})[/dim]")
                    console.print("[dim][Stopping service...][/dim]")
                    await self.stop()
                    break

                if user_input.lower() == "clear":
                    agent.reset()
                    console.print("[dim][Conversation cleared - token session continues][/dim]")
                    continue

                if user_input.lower() == "stats":
                    stats = agent.get_token_stats()
                    console.print(f"\n[bold]Token Statistics[/bold]")
                    console.print(f"  Context size:    {stats['context_tokens']:,} tokens")
                    console.print(f"  Messages:        {stats['message_count']}")
                    console.print(f"  Session input:   {stats['session_input_tokens']:,} tokens")
                    console.print(f"  Session output:  {stats['session_output_tokens']:,} tokens")
                    console.print(f"  Session total:   {stats['session_total_tokens']:,} tokens\n")
                    continue

                # Process query through shared agent (cancellable with Escape)
                timestamp = datetime.now().strftime("%H:%M:%S")
                console.print(f"[dim][{timestamp}] Processing... (Escape to cancel)[/dim]\n")

                try:
                    from macbot.utils.cancellable import run_with_escape_cancel

                    result, cancelled = await run_with_escape_cancel(
                        agent.run(user_input, stream=False, continue_conversation=True)
                    )

                    if cancelled:
                        console.print("\n[dim][Cancelled by Escape][/dim]\n")
                    else:
                        console.print()
                        console.print("[bold green]A:[/bold green]", end=" ")
                        console.print(Markdown(result))
                        console.print("[dim]─" * 60 + "[/dim]\n")
                except Exception as e:
                    console.print(f"\n[red]Error: {e}[/red]\n")

            except EOFError:
                break
            except asyncio.CancelledError:
                break

        executor.shutdown(wait=False)

    async def start(self, interactive: bool = False, stdin_reader: bool = False) -> None:
        """Start all configured services.

        Args:
            interactive: Whether to also run an interactive input loop (CLI mode)
            stdin_reader: Whether to read queries from stdin (GUI/foreground mode)
        """
        self._running = True

        has_cron = self._setup_cron()
        has_telegram = self._setup_telegram()

        if has_cron:
            jobs = [j for j in self.cron_service.list_jobs() if j.enabled]
            logger.info(f"Starting cron service with {len(jobs)} enabled jobs")
            self._tasks.append(asyncio.create_task(self._run_cron()))

        if has_telegram:
            from macbot.telegram.bot import validate_token
            ok, msg = await validate_token(settings.telegram_bot_token)
            if ok:
                logger.info(f"Starting Telegram service as {msg}")
                self._tasks.append(asyncio.create_task(self._run_telegram()))
            else:
                logger.error(f"Telegram token invalid: {msg}")

        # Add interactive loop if requested (CLI mode)
        if interactive:
            self._tasks.append(asyncio.create_task(self._run_interactive()))
        # Add stdin reader for GUI/foreground mode
        elif stdin_reader:
            self._tasks.append(asyncio.create_task(self._run_stdin_reader()))
        elif not self._tasks:
            logger.warning("No services configured (no cron jobs, no Telegram)")
            return

        # Wait for all tasks
        try:
            await asyncio.gather(*self._tasks)
        except asyncio.CancelledError:
            pass

    async def stop(self) -> None:
        """Stop all services gracefully."""
        self._running = False

        if self.telegram_service:
            await self.telegram_service.stop()

        if self.cron_service:
            await self.cron_service.stop()

        for task in self._tasks:
            task.cancel()

        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    def get_status(self) -> dict:
        """Get status of all services.

        Returns:
            Dictionary with service status information
        """
        status = {
            "running": self._running,
            "cron": {
                "enabled": False,
                "jobs_total": 0,
                "jobs_enabled": 0,
            },
            "telegram": {
                "enabled": False,
                "connected": False,
                "bot_username": None,
            },
        }

        # Cron status
        cron_service = CronService(storage_path=settings.get_cron_storage_path())
        jobs = cron_service.list_jobs()
        enabled_jobs = [j for j in jobs if j.enabled]
        status["cron"]["jobs_total"] = len(jobs)
        status["cron"]["jobs_enabled"] = len(enabled_jobs)
        status["cron"]["enabled"] = len(enabled_jobs) > 0

        # Telegram status
        if settings.telegram_bot_token:
            status["telegram"]["enabled"] = True
            status["telegram"]["chat_id"] = settings.telegram_chat_id or None

        return status


def run_service(daemon: bool = False, verbose: bool = False, foreground: bool = False) -> None:
    """Run the macbot service.

    Args:
        daemon: Whether to run as a background daemon
        verbose: Whether to show verbose output
        foreground: Whether to run in foreground without interactive console (for GUI)
    """
    from rich.console import Console
    console = Console()

    # Check what's available
    service = MacbotService()
    status = service.get_status()

    has_cron = status["cron"]["enabled"]
    has_telegram = status["telegram"]["enabled"]

    if not has_cron and not has_telegram:
        console.print("[yellow]Nothing to run:[/yellow]")
        console.print("  - No scheduled tasks configured")
        console.print("  - No Telegram configured (set up in Settings)")
        return

    # Show what will run
    console.print("[bold]Starting Son of Simon...[/bold]\n")

    if has_cron:
        console.print(f"  [green]✓[/green] Scheduled Tasks: {status['cron']['jobs_enabled']} active")
    else:
        console.print(f"  [dim]○[/dim] Scheduled Tasks: None configured")

    if has_telegram:
        chat_info = f" (chat: {status['telegram']['chat_id']})" if status['telegram']['chat_id'] else ""
        console.print(f"  [green]✓[/green] Telegram: Connected{chat_info}")
    else:
        console.print(f"  [dim]○[/dim] Telegram: Not connected")

    console.print()

    if daemon:
        # Check if already running
        existing_pid = get_service_pid()
        if existing_pid:
            console.print(f"[yellow]Service already running[/yellow] (PID {existing_pid})")
            console.print("Stop it first with: macbot stop")
            return

        console.print(f"[green]Starting in background...[/green]")
        console.print(f"  Log: {LOG_FILE}")
        console.print(f"\nUse 'macbot stop' to stop")

        # Daemonize
        _daemonize()

        # Now in daemon process
        _run_daemon_service()
    else:
        # Foreground mode
        if foreground:
            # Non-interactive foreground mode (for GUI integration)
            # Set up simple logging to stdout
            logging.basicConfig(
                level=logging.INFO if verbose else logging.WARNING,
                format="%(asctime)s %(message)s",
                datefmt="%H:%M:%S",
            )
            console.print("[green]✓[/green] Ready! You can now send commands.")

            try:
                # Enable stdin reader so GUI can send queries
                asyncio.run(service.start(interactive=False, stdin_reader=True))
            except KeyboardInterrupt:
                console.print("\n[dim]Stopping...[/dim]")
                asyncio.run(service.stop())
            console.print("[dim]Service stopped.[/dim]")
        else:
            # Interactive mode with input prompt
            console.print("[dim]Type queries below, or 'quit' to exit. Ctrl+C also stops.[/dim]")

            # Set up logging for foreground
            if verbose:
                logging.basicConfig(
                    level=logging.INFO,
                    format="%(asctime)s [%(name)s] %(message)s",
                    datefmt="%H:%M:%S",
                )

            try:
                asyncio.run(service.start(interactive=True))
            except KeyboardInterrupt:
                console.print("\n[dim]Stopping...[/dim]")
                asyncio.run(service.stop())
            console.print("[dim]Service stopped.[/dim]")


def _daemonize() -> None:
    """Fork the process to run in the background."""
    import sys

    # First fork
    pid = os.fork()
    if pid > 0:
        sys.exit(0)

    os.chdir("/")
    os.setsid()
    os.umask(0)

    # Second fork
    pid = os.fork()
    if pid > 0:
        sys.exit(0)

    # Redirect file descriptors
    sys.stdout.flush()
    sys.stderr.flush()

    MACBOT_DIR.mkdir(parents=True, exist_ok=True)
    log_fd = os.open(str(LOG_FILE), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    null_fd = os.open(os.devnull, os.O_RDONLY)

    os.dup2(null_fd, sys.stdin.fileno())
    os.dup2(log_fd, sys.stdout.fileno())
    os.dup2(log_fd, sys.stderr.fileno())

    os.close(null_fd)
    os.close(log_fd)

    # Write PID file
    PID_FILE.write_text(str(os.getpid()))


def _run_daemon_service() -> None:
    """Run the service in daemon mode."""
    import sys

    print(f"\n{'='*60}")
    print(f"MacBot Service started at {datetime.now().isoformat()}")
    print(f"PID: {os.getpid()}")
    print(f"{'='*60}\n")

    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Set up signal handler
    def handle_signal(signum, frame):
        print(f"\nReceived signal {signum}, shutting down...")
        PID_FILE.unlink(missing_ok=True)
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    service = MacbotService()

    try:
        asyncio.run(service.start())
    except Exception as e:
        print(f"Service error: {e}")
    finally:
        PID_FILE.unlink(missing_ok=True)
