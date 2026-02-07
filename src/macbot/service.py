"""Unified macbot service.

Runs the cron scheduler and Telegram listener together as a single service.
"""

import asyncio
import logging
import os
import signal
from collections.abc import Callable
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
HEARTBEAT_FILE = MACBOT_DIR / "heartbeat.md"


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

    def __init__(self, stderr_console: bool = False):
        """Initialize the service.

        Args:
            stderr_console: If True, Rich console output goes to stderr
                           (keeps stdout clean for JSON-lines protocol in foreground mode).
        """
        from rich.console import Console
        self.registry = create_default_registry()
        self.agent = Agent(self.registry)  # Default agent for cron jobs
        self._chat_agents: dict[str, Agent] = {}  # Per-chat agents for Telegram conversations
        self._console = Console(stderr=True) if stderr_console else Console()
        self.cron_service: CronService | None = None
        self.telegram_service = None
        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._emit: Callable | None = None

    def reload_skills(self) -> None:
        """Reload skills from disk for all agents.

        Called via SIGHUP signal when skills are added/modified.
        """
        logger.info("Reloading skills...")

        # Reload the main agent's skills registry
        self.agent.skills_registry.reload()

        # Reload skills for all chat agents
        for chat_id, agent in self._chat_agents.items():
            agent.skills_registry.reload()
            logger.debug(f"Reloaded skills for chat {chat_id}")

        skill_count = len(self.agent.skills_registry)
        enabled_count = len(self.agent.skills_registry.list_enabled_skills())
        logger.info(f"Skills reloaded: {enabled_count}/{skill_count} enabled")

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

    def _save_chat_id(self, chat_id: str) -> None:
        """Auto-save a detected Telegram chat ID to the config file.

        Called on the first incoming message when MACBOT_TELEGRAM_CHAT_ID
        is not set, so the user doesn't have to configure it manually.
        """
        env_file = Path.home() / ".macbot" / ".env"
        try:
            if env_file.exists():
                content = env_file.read_text()
            else:
                content = ""

            # Don't duplicate if already present
            if f"MACBOT_TELEGRAM_CHAT_ID={chat_id}" in content:
                return

            # Remove any existing (empty) chat ID line
            lines = [l for l in content.splitlines()
                     if not l.strip().startswith("MACBOT_TELEGRAM_CHAT_ID=")]
            lines.append(f"MACBOT_TELEGRAM_CHAT_ID={chat_id}")
            env_file.write_text("\n".join(lines) + "\n")

            # Update in-memory settings
            settings.telegram_chat_id = chat_id
            self.telegram_service.default_chat_id = chat_id

            self._console.print(f"  ✓ Auto-saved Telegram chat ID: {chat_id}")
            logger.info(f"Auto-saved MACBOT_TELEGRAM_CHAT_ID={chat_id}")
        except Exception as e:
            logger.error(f"Failed to auto-save chat ID: {e}")

    async def _detect_chat_id_at_startup(self) -> None:
        """Try to detect chat ID from pending Telegram messages at startup.

        Does a quick non-blocking poll. If the user previously sent a message
        to the bot (e.g. during onboarding), we pick up the chat ID without
        requiring them to send another message.
        """
        try:
            from macbot.telegram import TelegramBot
            bot = TelegramBot(settings.telegram_bot_token)
            updates = await bot.get_updates(offset=None, timeout=0)
            await bot.close()

            for update in updates:
                if update.message:
                    chat_id = str(update.message.chat_id)
                    self._save_chat_id(chat_id)
                    return
        except Exception as e:
            logger.debug(f"Chat ID startup detection failed (non-fatal): {e}")

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
                self._console.print(f"\n[{timestamp}] ⏰ Cron: {payload.message[:100]}{'...' if len(payload.message) > 100 else ''}")
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
            self._console.print(f"\n[{timestamp}] 📩 Telegram: {text[:100]}{'...' if len(text) > 100 else ''}")
            logger.info(f"Telegram: Message from {chat_id}: {text[:50]}...")

            # Emit incoming message to GUI
            if self._emit:
                self._emit({"type": "telegram_message", "text": text, "chat_id": chat_id, "direction": "incoming"})

            # Auto-detect chat ID if not configured
            if not settings.telegram_chat_id:
                self._save_chat_id(chat_id)

            # Handle special commands
            if text.strip().lower() in ("/reset", "/clear", "/new"):
                if chat_id in self._chat_agents:
                    self._chat_agents[chat_id].reset()
                reply = "Conversation cleared. Starting fresh!"
                if self._emit:
                    self._emit({"type": "telegram_message", "text": reply, "chat_id": chat_id, "direction": "outgoing"})
                return reply

            # Send acknowledgment
            await self.telegram_service.send_message("⏳ Working on it...", chat_id, parse_mode=None)

            try:
                # Get per-chat agent and continue conversation
                agent = self._get_chat_agent(chat_id)

                # Track tool calls for progress feedback
                tools_called = []
                original_execute = agent._execute_tool_calls

                async def tracking_execute(response, verbose=False, **kwargs):
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
                    return await original_execute(response, verbose, **kwargs)

                agent._execute_tool_calls = tracking_execute

                result = await agent.run(
                    text, stream=False, continue_conversation=True,
                    on_event=self._emit,
                )

                # Restore original method
                agent._execute_tool_calls = original_execute

                # Emit outgoing response to GUI
                if self._emit:
                    self._emit({"type": "telegram_message", "text": result, "chat_id": chat_id, "direction": "outgoing"})

                # Show response in terminal as rendered markdown
                from rich.markdown import Markdown
                from rich.panel import Panel
                timestamp = datetime.now().strftime("%H:%M:%S")
                self._console.print(Panel(
                    Markdown(result),
                    title=f"[dim]{timestamp}[/dim] 🤖 Response",
                    border_style="green",
                    padding=(0, 1),
                ))

                logger.info(f"Telegram: Response sent, length: {len(result)}, tools: {len(tools_called)}")
                return result
            except Exception as e:
                logger.error(f"Telegram: Error - {e}")
                error_msg = f"Error: {e}"
                if self._emit:
                    self._emit({"type": "telegram_message", "text": error_msg, "chat_id": chat_id, "direction": "outgoing"})
                return error_msg

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

    async def _run_heartbeat(self) -> None:
        """Run the heartbeat loop at the configured interval.

        Reads ~/.macbot/heartbeat.md and executes its content as a prompt.
        If the file doesn't exist or is empty, just prints 'heartbeat'.
        Only runs during active hours to save API costs.
        """
        while self._running:
            try:
                await asyncio.sleep(settings.heartbeat_interval)
            except asyncio.CancelledError:
                return

            now = datetime.now()
            timestamp = now.strftime("%H:%M:%S")

            # Skip outside active hours
            if not (settings.heartbeat_active_start <= now.hour < settings.heartbeat_active_end):
                logger.debug(f"Heartbeat: Skipping outside active hours ({settings.heartbeat_active_start}:00-{settings.heartbeat_active_end}:00)")
                continue

            try:
                if HEARTBEAT_FILE.exists():
                    content = HEARTBEAT_FILE.read_text().strip()
                else:
                    content = ""

                if not content:
                    self._console.print(f"[{timestamp}] heartbeat")
                    continue

                self._console.print(f"\n[{timestamp}] 💓 Heartbeat: {content[:100]}{'...' if len(content) > 100 else ''}")
                logger.info(f"Heartbeat: Running '{content[:50]}...'")
                result = await self.agent.run(content, stream=False)
                logger.info(f"Heartbeat: Completed, result length: {len(result)}")
                from rich.markdown import Markdown
                from rich.panel import Panel
                self._console.print(Panel(
                    Markdown(result),
                    title=f"[dim]{timestamp}[/dim] 💓 Heartbeat",
                    border_style="magenta",
                    padding=(0, 1),
                ))

                # Send result to Telegram if configured
                if self.telegram_service and result:
                    try:
                        chat_id = settings.telegram_chat_id
                        if chat_id:
                            await self.telegram_service.send_message(result, chat_id)
                    except Exception as e:
                        logger.warning(f"Heartbeat: Failed to send to Telegram: {e}")
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.error(f"Heartbeat: Error - {e}")
                self._console.print(f"[{timestamp}] 💓 Heartbeat error: {e}")

    def _format_tokens(self, count: int) -> str:
        """Format token count with K suffix for thousands."""
        if count >= 1000:
            return f"{count / 1000:.1f}K"
        return str(count)

    async def _run_stdin_reader(self) -> None:
        """Run stdin reader for GUI/foreground mode using JSON-lines protocol.

        Input (stdin):  {"type": "message", "text": "..."}
        Output (stdout): {"type": "ready"}
                         {"type": "tool_call", "name": "...", "arguments": {...}}
                         {"type": "tool_result", "success": true/false, ...}
                         {"type": "chunk", "text": "..."}
                         {"type": "done"}
                         {"type": "error", "text": "..."}
        """
        import json
        import sys
        from concurrent.futures import ThreadPoolExecutor

        executor = ThreadPoolExecutor(max_workers=1)
        loop = asyncio.get_event_loop()

        # Use the same agent as the primary Telegram chat for shared context
        if settings.telegram_chat_id:
            agent = self._get_chat_agent(settings.telegram_chat_id)
        else:
            agent = self.agent

        def _emit(obj: dict) -> None:
            sys.stdout.write(json.dumps(obj) + "\n")
            sys.stdout.flush()

        self._emit = _emit

        def read_line():
            try:
                return sys.stdin.readline()
            except Exception:
                return None

        _emit({"type": "ready"})

        while self._running:
            try:
                raw = await loop.run_in_executor(executor, read_line)

                if raw is None or raw == "":
                    # EOF — stdin closed
                    await asyncio.sleep(0.1)
                    continue

                raw = raw.strip()
                if not raw:
                    continue

                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    _emit({"type": "error", "text": "Invalid JSON input"})
                    continue

                if msg.get("type") != "message":
                    _emit({"type": "error", "text": f"Unknown message type: {msg.get('type')}"})
                    continue

                text = msg.get("text", "").strip()
                if not text:
                    _emit({"type": "error", "text": "Empty message"})
                    continue

                try:
                    result = await agent.run(
                        text, stream=False,
                        continue_conversation=True, on_event=_emit,
                    )
                    _emit({"type": "chunk", "text": result})
                except Exception as e:
                    _emit({"type": "error", "text": str(e)})

                _emit({"type": "done"})

            except EOFError:
                break
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Stdin reader error: {e}")
                await asyncio.sleep(0.1)

        executor.shutdown(wait=False)

    async def _run_interactive(self) -> None:
        """Run interactive console input loop with readline support."""
        import readline
        from concurrent.futures import ThreadPoolExecutor
        from rich.console import Console
        from rich.markdown import Markdown

        # Set up readline with persistent history
        history_file = MACBOT_DIR / "input_history"
        try:
            readline.read_history_file(history_file)
        except FileNotFoundError:
            pass
        readline.set_history_length(500)

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
                    prompt = f"\x1b[2m(ctx:{ctx} total:{total})\x1b[0m \x1b[1;34m→\x1b[0m "
                else:
                    prompt = "\x1b[1;34m→\x1b[0m "

                # Use input() instead of console.input() for readline support
                user_input = await loop.run_in_executor(
                    executor, lambda p=prompt: input(p).strip()
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
                    readline.write_history_file(history_file)
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
                readline.write_history_file(history_file)
                break
            except asyncio.CancelledError:
                readline.write_history_file(history_file)
                break

        executor.shutdown(wait=False)

    async def start(self, interactive: bool = False, stdin_reader: bool = False) -> None:
        """Start all configured services.

        Args:
            interactive: Whether to also run an interactive input loop (CLI mode)
            stdin_reader: Whether to read queries from stdin (GUI/foreground mode)
        """
        self._running = True

        # Set up SIGHUP handler for skills reload
        loop = asyncio.get_event_loop()
        loop.add_signal_handler(signal.SIGHUP, self.reload_skills)
        logger.debug("SIGHUP handler registered for skills reload")

        has_cron = self._setup_cron()
        has_telegram = self._setup_telegram()

        # Heartbeat always runs
        logger.info(f"Starting heartbeat (every {settings.heartbeat_interval}s)")
        self._tasks.append(asyncio.create_task(self._run_heartbeat()))

        if has_cron:
            jobs = [j for j in self.cron_service.list_jobs() if j.enabled]
            logger.info(f"Starting cron service with {len(jobs)} enabled jobs")
            self._tasks.append(asyncio.create_task(self._run_cron()))

        if has_telegram:
            from macbot.telegram.bot import validate_token
            ok, msg = await validate_token(settings.telegram_bot_token)
            if ok:
                logger.info(f"Starting Telegram service as {msg}")

                # Auto-detect chat ID from pending messages if not configured
                if not settings.telegram_chat_id:
                    await self._detect_chat_id_at_startup()

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
    # In foreground mode, use stderr for all Rich output to keep stdout clean for JSON-lines
    console = Console(stderr=True) if foreground else Console()

    # Check what's available
    service = MacbotService(stderr_console=foreground)
    status = service.get_status()

    has_cron = status["cron"]["enabled"]
    has_telegram = status["telegram"]["enabled"]

    # Show what will run
    from macbot import __version__
    console.print(f"[bold]Starting Son of Simon[/bold] v{__version__}...\n")

    console.print(f"  [green]✓[/green] Heartbeat: every {settings.heartbeat_interval // 60} minutes, {settings.heartbeat_active_start}:00-{settings.heartbeat_active_end}:00 (~/.macbot/heartbeat.md)")

    if has_cron:
        console.print(f"  [green]✓[/green] Scheduled Tasks: {status['cron']['jobs_enabled']} active")
    else:
        console.print(f"  [dim]○[/dim] Scheduled Tasks: None configured")

    if has_telegram:
        chat_info = f" (chat: {status['telegram']['chat_id']})" if status['telegram'].get('chat_id') else ""
        console.print(f"  [green]✓[/green] Telegram: Connected{chat_info}")
        if not status['telegram'].get('chat_id'):
            console.print(f"  [yellow]![/yellow] Chat ID not set — send any message to your bot on Telegram to link it automatically")
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
            # Use stderr for Rich output so stdout stays clean for JSON-lines protocol
            from rich.console import Console as RichConsole
            stderr_console = RichConsole(stderr=True)

            logging.basicConfig(
                level=logging.INFO if verbose else logging.WARNING,
                format="%(asctime)s %(message)s",
                datefmt="%H:%M:%S",
                stream=__import__("sys").stderr,
            )

            # Write PID file as safety net for cleanup
            MACBOT_DIR.mkdir(parents=True, exist_ok=True)
            PID_FILE.write_text(str(os.getpid()))

            stderr_console.print("[green]✓[/green] Ready! You can now send commands.")

            try:
                # Enable stdin reader so GUI can send queries via JSON-lines
                asyncio.run(service.start(interactive=False, stdin_reader=True))
            except KeyboardInterrupt:
                stderr_console.print("\n[dim]Stopping...[/dim]")
                asyncio.run(service.stop())
            finally:
                PID_FILE.unlink(missing_ok=True)
            stderr_console.print("[dim]Service stopped.[/dim]")
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
                # Close stdin to unblock any thread still waiting on console.input()
                import sys
                try:
                    sys.stdin.close()
                except Exception:
                    pass
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
